"""lsfx2lsefx - rebuilds an effect source file (.lsefx, BG3 Toolkit AllSpark
editor) from a compiled effect (.lsfx).

Usage:
    python lsfx2lsefx.py effect.lsfx [more.lsfx ...] -o <output> (--defs <folder
        containing ComponentDefinition.xcd and ModuleDefinition.xmd> | --auto-defs)
        [--names names.txt]

How it works:
  * each EffectComponent of the .lsfx becomes a <component>; its ID = instancename;
  * each Property is looked up in the .xcd through its FullName
    (property group path + name), which gives the .lsefx property GUID;
  * curves (Frames) are turned back into rampchannels:
      FrameType 00 -> "Linear" (same points),
      FrameType 01 -> cubic polynomial pieces A*u^3+B*u^2+C*u+D
                      (u = t - piece start, Time = piece end);
                      "Spline" and "FreeTangentSpline" keys are recovered by
                      inverting the editor's curve compiler (see curvefit.py).
"""
import os, sys, uuid, argparse
from xml.sax.saxutils import quoteattr
from lsfx_read import read_tree, av, kids, kid
from defs import Defs, REQUIRED_MODULE
try:
    from curvefit import fit_fts_chain, try_spline_exact   # pure Python
    FIT_BEZIER = True
except ImportError:
    FIT_BEZIER = False

NAME_ID = 'ef1d7d1e-02b6-4548-80d9-5ef2fbcda237'
STARTEND_ID = '035b5248-d0ca-44b7-853f-3acb84110e67'
ZERO = '00000000-0000-0000-0000-000000000000'
PHASE_DEFS = {  # phase definitions (ComponentDefinition.xcd)
    'leadin': 'fc34bad5-e4a8-4855-bdd1-ece88d327719',
    'loop': '2d6a16c1-4632-4f7f-8097-4717dc65d7bd',
    'leadout': 'fc8e9f77-827a-433f-a58d-ad1007605399',
}


# ---------------------------------------------------------------- formats
def f7(x):
    """Float in the editor's format (.NET Framework float.ToString() = G7)."""
    if x == 0:
        return '0'
    s = '%.7G' % x
    if 'E' in s:
        m, e = s.split('E')
        if '.' in m:
            m = m.rstrip('0').rstrip('.')
        s = m + 'E' + e
    return s


def argb(c):
    """(r,g,b,a) floats 0..1 -> signed ARGB integer (color keyframe format)."""
    r, g, b, a = [max(0, min(255, int(round(v * 255)))) for v in c]
    v = (a << 24) | (r << 16) | (g << 8) | b
    return v - (1 << 32) if v & 0x80000000 else v


def scalar_value(p, typ, names):
    t = av(p, 'Type')
    v = av(p, 'Value')
    if t in ('02', '05'):
        fmt = str if t == '02' else f7
        return f"{fmt(av(p, 'Min'))},{fmt(av(p, 'Max'))}"
    if t == '04':
        return f7(v)
    if t == '08':
        return ','.join(f7(x) for x in v)
    if t in ('00', '01'):
        return str(v)
    if t == '0a' and typ == 'Guid' and v:
        n = names.get(v.lower())
        # no name: GUID only (accepted by the compiler, see GuidPropertyCompiler)
        return f"{n} <{v}>" if n else v
    return '' if v is None else str(v)


# ---------------------------------------------------------------- curves
def poly_eval(fr, u):
    return ((fr['A'] * u + fr['B']) * u + fr['C']) * u + fr['D']


def pieces(frames):
    """FrameType 01 frames -> list of (t0, t1, A, B, C, D)."""
    out, t0 = [], 0.0
    for f in frames:
        a = {k: v[1] for k, v in f['attrs'].items()}
        out.append((t0, a['Time'], a['A'], a['B'], a['C'], a['D']))
        t0 = a['Time']
    return out


def end_value(pc):
    t0, t1, A, B, C, D = pc
    u = t1 - t0
    return ((A * u + B) * u + C) * u + D


SPLINE_FRACTIONS = (0.377556, 0.405017, 0.442561, 0.5, 0.557439, 0.594983, 0.622444, 1.0)


def try_spline(pcs):
    """"Spline" pattern: the start slope is zero at every key (C == 0) and each
    interval between two keys is either 1 constant piece or 8 pieces."""
    keys, i = [], 0
    while i < len(pcs):
        t0, t1, A, B, C, D = pcs[i]
        if C != 0:
            return None
        keys.append((t0, D))
        if A == 0 and B == 0:
            i += 1
            continue
        if i + 8 > len(pcs):
            return None
        grp = pcs[i:i + 8]
        if any(g[4] == 0 for g in grp[1:]):
            return None
        # bounds of the 8 pieces: fixed positions for a "Spline" (horizontal handles of
        # length 1/2); a FreeTangentSpline with horizontal handles has other bounds
        h = grp[-1][1] - t0
        fr = [(g[1] - t0) / h for g in grp]
        if any(abs(a - b) > 2e-3 for a, b in zip(fr, SPLINE_FRACTIONS)):
            return None
        i += 8
    keys.append((pcs[-1][1], end_value(pcs[-1])))
    return keys


def bezier_keys(pcs):
    """Exact conversion: each cubic piece -> one Bezier segment with control points
    at 1/3 and 2/3 of its duration (same curve)."""
    kf = []
    for n, (t0, t1, A, B, C, D) in enumerate(pcs):
        h = t1 - t0
        a, b, c, d = A * h ** 3, B * h ** 2, C * h, D
        p1 = d + c / 3
        p2 = d + 2 * c / 3 + b / 3
        p3 = a + b + c + d
        if n == 0:
            kf.append((t0, d, False))
        kf += [(t0 + h / 3, p1, True), (t0 + 2 * h / 3, p2, True), (t1, p3, False)]
    return kf


def simplify(pts, tol):
    """Ramer-Douglas-Peucker on a multi-channel curve [(t, (v1, v2, ...))]."""
    if len(pts) <= 2:
        return pts
    (ta, va), (tb, vb) = pts[0], pts[-1]
    worst, wi = -1, 0
    for i in range(1, len(pts) - 1):
        t, v = pts[i]
        k = (t - ta) / (tb - ta) if tb != ta else 0
        d = max(abs(v[c] - (va[c] + (vb[c] - va[c]) * k)) for c in range(len(v)))
        if d > worst:
            worst, wi = d, i
    if worst <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:wi + 1], tol)[:-1] + simplify(pts[wi:], tol)


def ramp_channel(frames_node, is_color):
    """-> (type, [(time, value_str, is_control_point)])"""
    ft = av(frames_node, 'FrameType')
    fr = frames_node['children']
    if ft == '00' or (is_color and ft == '01'):
        pts = []
        for f in fr:
            a = {k: v[1] for k, v in f['attrs'].items()}
            pts.append((a['Time'], a['Color'] if is_color else (a['Value'],)))
        if ft == '01':   # sampled "FreeTangentSpline" color -> simplified to linear
            pts = simplify(pts, 1.5 / 255)
        return 'Linear', [(t, str(argb(v)) if is_color else f7(v[0]), False) for t, v in pts]
    pcs = pieces(fr)
    sp = None
    if FIT_BEZIER:
        try:
            sp = try_spline_exact(pcs)          # verified by recompiling
        except Exception:
            sp = None
    else:
        sp = try_spline(pcs)                    # fallback heuristic
    if sp:
        return 'Spline', [(t, f7(v), False) for t, v in sp]
    kf = None
    if FIT_BEZIER:
        try:
            kf = fit_fts_chain(pcs)             # verified by recompiling
        except Exception:
            kf = None
    if kf is None:
        kf = bezier_keys(pcs)     # exact conversion (more points)
        if any(p[1] - p[0] < 3e-4 for p in pcs):
            print('  ! warning: a FreeTangentSpline curve has very short pieces; '
                  'it may recompile slightly differently.')
    vals = [float(v) for _, v, _ in kf]
    eps = 1e-4 * max(1.0, max(vals) - min(vals))
    return 'FreeTangentSpline', [(float(t), f7(0.0 if abs(float(v)) < eps else float(v)), cp) for t, v, cp in kf]


# ---------------------------------------------------------------- writing
class W:
    def __init__(self):
        self.lines = []

    def __call__(self, depth, s):
        self.lines.append('  ' * depth + s)


def datum_open(extra=''):
    return f'<datum platform="{ZERO}" lod="{ZERO}"{extra}'


def write_property(w, d, pid, p, pdef, names, inputs):
    attr = f' id="{pid}"'
    inp = av(p, 'Input')
    if inp:
        attr += f' input="{inputs.get(inp, ZERO)}"'
    w(6, f'<property{attr}>')
    w(7, '<data>')
    t = av(p, 'Type')
    if t in ('03', '06'):
        w(8, datum_open('>'))
        w(9, '<rampchanneldata>')
        chans = pdef.channels if pdef else []
        for i, fn in enumerate(kids(p, 'Frames')):
            cid = chans[i][1] if i < len(chans) else str(uuid.uuid4())
            rtype, kf = ramp_channel(fn, t == '03')
            w(10, f'<rampchannel type="{rtype}" id="{cid}">')
            w(11, '<keyframes>')
            for tm, val, cp in kf:
                w(12, f'<keyframe time="{f7(tm)}" value="{val}"'
                      + (' is_control_point="True"' if cp else '') + ' />')
            w(11, '</keyframes>')
            w(10, '</rampchannel>')
        w(9, '</rampchanneldata>')
        w(8, '</datum>')
    else:
        exposed = ' is_exposed="True"' if kids(p, 'Parameter') else ''
        val = scalar_value(p, pdef.type if pdef else '', names)
        w(8, datum_open(f'{exposed} value={quoteattr(val)} />'))
    w(7, '</data>')
    w(6, '</property>')


def convert(path, defs, names=None, log=print):
    names = names or {}
    roots = read_tree(path)
    eff = [r for r in roots if r['name'] == 'Effect'][0]
    comps = kid(eff, 'EffectComponents')['children']
    inputs = {n: i for n, i in defs.inputs.items()}
    w = W()
    w(0, '<?xml version="1.0" encoding="utf-8"?>')
    w(0, f'<effect version="0.0" effectversion="1.0.0" id="{ZERO}">')
    # phases
    ph = kid(eff, 'Phases')
    phases = ph['children'] if ph else []
    if phases:
        w(1, '<phases>')
        n = len(phases)
        for i, p in enumerate(phases):
            pc = av(p, 'PlayCount')
            if pc == -1:
                kind = 'loop'
            elif i == 0:
                kind = 'leadin'
            else:
                kind = 'leadout'
            w(2, f'<object class="" classid="{ZERO}" assembly="">')
            w(3, f'<data id="{uuid.uuid4()}" duration="{f7(av(p, "Duration"))}" '
                 f'playcount="{pc}" definitionid="{PHASE_DEFS[kind]}" />')
            w(2, '</object>')
        w(1, '</phases>')
    else:
        w(1, '<phases />')
    w(1, '<colors />')
    w(1, '<trackgroups>')
    groups = {}
    for c in comps:
        groups.setdefault(av(c, 'Track'), []).append(c)
    stats = dict(components=0, properties=0, unknown=[], ramps={})
    # Track = track group index; empty groups (whose content was all muted) are
    # recreated too, otherwise the following indices would shift on recompiling
    for gi in range(0, max(groups) + 1 if groups else 0):
        w(2, '<trackgroup name="New Track Group">')
        w(3, '<ids>')
        w(4, f'<id value="{gi}" />')
        w(3, '</ids>')
        if gi not in groups:
            w(3, '<track name="Track" muted="False" locked="False" mutestateoverride="None" />')
        for c in groups.get(gi, []):
            ctype = av(c, 'Type')
            cd = defs.comps.get(ctype)
            if cd is None:
                log(f'  ! unknown component type: {ctype} (skipped)')
                continue
            stats['components'] += 1
            w(3, '<track name="Track" muted="False" locked="False" mutestateoverride="None">')
            w(4, f'<component class={quoteattr(ctype)} start="{f7(av(c, "StartTime"))}" '
                 f'end="{f7(av(c, "EndTime"))}" instancename="{av(c, "ID")}">')
            w(5, '<properties>')
            props = kid(c, 'Properties')['children']
            written = {}
            for p in props:
                fn = av(p, 'FullName')
                pid = NAME_ID if fn == 'Name' else cd.byfull.get(fn)
                if pid is None:
                    stats['unknown'].append(f'{ctype}.{fn}')
                    log(f'  ! unknown property: {ctype} / {fn} (skipped)')
                    continue
                stats['properties'] += 1
                sub = W()
                write_property(sub, defs, pid, p, cd.props.get(pid), names, inputs)
                w.lines += sub.lines
                written[pid] = sub.lines
                if pid == NAME_ID:  # Start / End right after the name, like the editor
                    w(6, f'<property id="{STARTEND_ID}">')
                    w(7, '<data>')
                    w(8, datum_open(f' value="{f7(av(c, "StartTime"))},{f7(av(c, "EndTime"))}" />'))
                    w(7, '</data>')
                    w(6, '</property>')
            w(6, f'<propertygroup id="{uuid.uuid4()}" name="Property Group" collapsed="False" />')
            w(5, '</properties>')
            w(5, '<modules>')
            w(6, f'<module id="{REQUIRED_MODULE}" muted="False" index="0" />')
            idx = 1
            mods = kid(c, 'Modules')
            if mods and kids(mods, 'Module'):
                # recent format: the module list is stored in the .lsfx
                mids = []
                for m in kids(mods, 'Module'):
                    mname = av(m, 'Name')
                    mid = defs.find_module(ctype, mname, [av(x, 'Object') for x in kids(m, 'FullName')])
                    if mid is None:
                        log(f'  ! unknown module: {ctype} / {mname} (skipped)')
                    elif mid != REQUIRED_MODULE:
                        mids.append(mid)
            else:
                # older format: modules are inferred from non-default values
                mids = infer_modules(defs, ctype, written)
            for mid in mids:
                w(6, f'<module id="{mid}" muted="False" index="{idx}" />')
                idx += 1
            w(5, '</modules>')
            w(4, '</component>')
            w(3, '</track>')
        w(2, '</trackgroup>')
    w(1, '</trackgroups>')
    w(0, '</effect>')
    return '\r\n'.join(w.lines) + '\r\n', stats


# ---------------------------------------------------------------- modules
EMITTERS = ['Cube Emitter', 'Sphere Emitter', 'Cylinder Emitter', 'Point Emitter', 'Fixed Line Emitter',
            'Random Line Emitter', 'Circle Emitter', 'Mesh Emitter', 'Cone Emitter']


def _sig(datum):
    if datum is None:
        return None
    rc = datum.findall('.//rampchannel')
    if rc:
        return [(r.get('type'), [(float(k.get('time')), k.get('value')) for k in r.iter('keyframe')]) for r in rc]
    v = datum.get('value')
    try:
        return [round(float(x), 5) for x in v.split(',')]
    except (ValueError, AttributeError):
        return v


def infer_modules(defs, ctype, written):
    """Older .lsfx files do not list modules (the game does not need them: every
    property is compiled). For the editor, a module is enabled as soon as one of its
    own properties has a non-default value; the emitter is chosen from the
    Emitter.Type property."""
    import xml.etree.ElementTree as ET
    cd = defs.comps[ctype]
    owners = {}
    for mid, (mn, req, per) in defs.modules.items():
        for _, pid in per.get(ctype, []):
            owners.setdefault(pid, set()).add(mid)
    out = []
    emitter = None
    tid = cd.byfull.get('Emitter.Type')
    if ctype == 'ParticleSystem' and tid in written:
        d = ET.fromstring('\n'.join(written[tid])).find('data/datum')
        try:
            emitter = EMITTERS[int(d.get('value'))]
            if emitter == 'Point Emitter':   # default emitter: no module
                emitter = None
        except (ValueError, IndexError, TypeError):
            pass
    for mid, (mn, req, per) in defs.modules.items():
        if mid == REQUIRED_MODULE or ctype not in per:
            continue
        if mn in EMITTERS:
            if mn == emitter:
                out.append(mid)
            continue
        for _, pid in per[ctype]:
            if pid not in written or len(owners[pid]) > 1:
                continue
            pd = cd.props.get(pid)
            cur = ET.fromstring('\n'.join(written[pid])).find('data/datum')
            if pd is None or pd.default is None or _sig(cur) != _sig(pd.default):
                out.append(mid)
                break
    return out


def load_names(path):
    """Optional text file, one "guid name" pair per line (resource names)."""
    out = {}
    if path and os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                out[parts[0].lower()] = parts[1]
    return out


AUTO_DEFS_DIR = r'C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3\Data\Editor\Config\AllSpark'
DEF_FILES = ('ComponentDefinition.xcd', 'ModuleDefinition.xmd')


def missing_defs(folder):
    return [f for f in DEF_FILES if not os.path.isfile(os.path.join(folder, f))]


def main():
    ap = argparse.ArgumentParser(description='Converts a compiled .lsfx effect into an editable .lsefx source')
    ap.add_argument('lsfx', nargs='+', help='compiled .lsfx effect(s) to convert')
    ap.add_argument('-o', '--out', help='output folder, or output .lsefx file when converting a single effect')
    ap.add_argument('--defs', help='folder containing ComponentDefinition.xcd and ModuleDefinition.xmd '
                    '(default: a Definitions folder next to this script)', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Definitions'))
    ap.add_argument('--auto-defs', action='store_true',
                    help=f'use the definitions from the default Steam install ({AUTO_DEFS_DIR})')
    ap.add_argument('--names', help='optional guid -> resource name table')
    a = ap.parse_args()
    if a.auto_defs:
        a.defs = AUTO_DEFS_DIR
    manq = missing_defs(a.defs)
    if manq:
        print(f"! Editor definitions not found in: {a.defs}")
        print(f"  Missing file(s): {', '.join(manq)}")
        if a.auto_defs:
            print("  The game (with the Toolkit) is not installed in the default Steam folder.")
        print("  Give the folder that contains these files with --defs, for example:")
        print('  --defs "D:\\SteamLibrary\\steamapps\\common\\Baldurs Gate 3\\Data\\Editor\\Config\\AllSpark"')
        sys.exit(1)
    defs = Defs(os.path.join(a.defs, DEF_FILES[0]), os.path.join(a.defs, DEF_FILES[1]))
    names = load_names(a.names)
    for src in a.lsfx:
        # safety checks: the input must be a compiled .lsfx (binary LSF file)
        try:
            with open(src, 'rb') as f:
                magic = f.read(4)
        except OSError as e:
            print(f'{src}\n  ! cannot read the file: {e}')
            continue
        if magic != b'LSOF':
            hint = ''
            if magic.startswith(b'<?xm') or magic.startswith(b'\xef\xbb\xbf<') or src.lower().endswith('.lsefx'):
                hint = (" This is a .lsefx source file (XML): give the compiled .lsfx instead, usually in "
                        "Data\\Public\\<mod>\\Assets\\Effects\\Effects_Banks\\...")
            print(f'{src}\n  ! skipped: not a compiled .lsfx file.{hint}')
            continue
        if a.out and len(a.lsfx) == 1 and a.out.lower().endswith('.lsefx'):
            dst = a.out
        else:
            base = os.path.splitext(os.path.basename(src))[0] + '.lsefx'
            dst = os.path.join(a.out or os.path.dirname(src), base)
        if os.path.abspath(dst).lower() == os.path.abspath(src).lower() or (
                os.path.exists(dst) and 'steamapps' in os.path.abspath(dst).lower()):
            print(f'{src}\n  ! refused: the output {dst} would overwrite an existing game/Toolkit file. '
                  f'Choose an output folder with -o.')
            continue
        print(f'{src}\n  -> {dst}')
        xml, st = convert(src, defs, names)
        with open(dst, 'w', encoding='utf-8', newline='') as f:
            f.write(xml)
        print(f"  {st['components']} components, {st['properties']} properties, "
              f"{len(st['unknown'])} unknown")


if __name__ == '__main__':
    main()
