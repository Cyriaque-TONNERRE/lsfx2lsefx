"""Exact inversion of compiled curves (FrameType 01), using rampcompile.py,
a re-implementation of the AllSpark curve compiler.

Every piece bound is an exact point of the original Bezier curve, and the
start/end slope of every piece is the exact slope of the curve. Only the length
of the two handles of each segment is unknown; the result is then checked by
recompiling it: it must give back the same pieces."""
import math
from rampcompile import compile_fts, compile_spline_interval


def _end(p):
    t0, t1, A, B, C, D = p
    u = t1 - t0
    return ((A * u + B) * u + C) * u + D


def _end_slope(p):
    t0, t1, A, B, C, D = p
    u = t1 - t0
    return (3 * A * u + 2 * B) * u + C


def _bez(P, s):
    u = 1 - s
    return (u ** 3 * P[0][0] + 3 * u * u * s * P[1][0] + 3 * u * s * s * P[2][0] + s ** 3 * P[3][0],
            u ** 3 * P[0][1] + 3 * u * u * s * P[1][1] + 3 * u * s * s * P[2][1] + s ** 3 * P[3][1])


def _y_at(P, ts):
    """Bezier values at times ts (list), by bisection on the curve parameter."""
    out = []
    for t in ts:
        lo, hi = 0.0, 1.0
        for _ in range(40):
            m = (lo + hi) / 2
            if _bez(P, m)[0] < t:
                lo = m
            else:
                hi = m
        out.append(_bez(P, (lo + hi) / 2)[1])
    return out


def _lsq2(f, x0, lo, hi, iters=60):
    """Bounded 2-parameter least squares (minimal Levenberg-Marquardt)."""
    clip = lambda x: [min(max(x[0], lo), hi), min(max(x[1], lo), hi)]
    x = clip(list(x0))
    r = f(x)
    cost = sum(v * v for v in r)
    lam = 1e-3
    for _ in range(iters):
        eps = [max(1e-9, abs(x[0]) * 1e-6), max(1e-9, abs(x[1]) * 1e-6)]
        J = []
        for k in range(2):
            xp = list(x); xp[k] += eps[k]
            rp = f(clip(xp))
            J.append([(a - b) / eps[k] for a, b in zip(rp, r)])
        a11 = sum(v * v for v in J[0]); a22 = sum(v * v for v in J[1]); a12 = sum(p * q for p, q in zip(J[0], J[1]))
        g1 = sum(p * q for p, q in zip(J[0], r)); g2 = sum(p * q for p, q in zip(J[1], r))
        improved = False
        for _ in range(8):
            m11, m22 = a11 * (1 + lam), a22 * (1 + lam)
            det = m11 * m22 - a12 * a12
            if det == 0 or not math.isfinite(det):
                lam *= 10
                continue
            dx0 = -(m22 * g1 - a12 * g2) / det
            dx1 = -(m11 * g2 - a12 * g1) / det
            xn = clip([x[0] + dx0, x[1] + dx1])
            rn = f(xn)
            cn = sum(v * v for v in rn)
            if cn < cost:
                x, r, cost, lam, improved = xn, rn, cn, lam / 3, True
                break
            lam *= 10
        if not improved or cost < 1e-24:
            break
    return x


def _same(pcs_a, pcs_b):
    if len(pcs_a) != len(pcs_b):
        return False
    for a, b in zip(pcs_a, pcs_b):
        # a: dict (recompiled), b: tuple (t0, t1, A, B, C, D) from the .lsfx
        sc = max(1.0, abs(b[5]))
        if abs(float(a['end']) - b[1]) > 1e-4 or abs(float(a['D']) - b[5]) > 1e-4 * sc:
            return False
        if abs(float(a['C']) - b[4]) > 2e-3 * max(1.0, abs(b[4])):
            return False
    return True


def _r7(x):
    return float('%.7G' % x)


def _grid():
    from rampcompile import f32
    out, x = [], f32(0.02)
    while x < 1.0:
        out.append(float(x))
        x = f32(x + f32(0.02))
    return out


S_GRID = _grid()


def _finish(P, P0, P3, sub):
    """Rounding, undoing the 0.001 shift the compiler applies to near-vertical
    handles (|dx| < 1e-4), then verification by recompiling."""
    a = P[1][0] - P0[0]
    b = P3[0] - P[2][0]
    va = [a] + ([a - 0.001] if 0.001 - 2e-5 <= a < 0.0011 else [])
    vb = [b] + ([b - 0.001] if 0.001 - 2e-5 <= b < 0.0011 else [])
    for aa in reversed(va):
        for bb in reversed(vb):
            Q = [list(P0), [P0[0] + aa, P[1][1]], [P3[0] - bb, P[2][1]], list(P3)]
            if abs(aa) < 2e-5:
                Q[1][0] = P0[0]
            if abs(bb) < 2e-5:
                Q[2][0] = P3[0]
            Q = [[_r7(p[0]), _r7(p[1])] for p in Q]
            try:
                if _same(compile_fts(Q), sub):
                    return Q
            except (ValueError, ZeroDivisionError):
                pass
    return None


def fit_fts_segment_exact(pcs, i, j):
    """Direct solve: inner bounds are points B(s) with s a multiple of 0.02
    (the compiler's samples). For a fixed s, B(s) is linear in (a, b)."""
    sub = pcs[i:j]
    P0 = (sub[0][0], sub[0][5])
    P3 = (sub[-1][1], _end(sub[-1]))
    m0, m1 = sub[0][4], _end_slope(sub[-1])
    inner = [(p[0], p[5]) for p in sub[1:]]
    if not inner:
        h = P3[0] - P0[0]
        if h <= 1e-6:
            return None
        return _finish([P0, (P0[0] + h / 3, P0[1] + m0 * h / 3), (P3[0] - h / 3, P3[1] - m1 * h / 3), P3], P0, P3, sub)
    t, v = inner[0]
    tried = set()
    for s in S_GRID:
        u = 1 - s
        c0, c1, c2, c3 = u ** 3, 3 * u * u * s, 3 * u * s * s, s ** 3
        rx = t - (c0 + c1) * P0[0] - (c2 + c3) * P3[0]
        ry = v - (c0 + c1) * P0[1] - (c2 + c3) * P3[1]
        # c1*a*(1,m0) - c2*b*(1,m1) = (rx, ry)
        det = (c1 * 1) * (-c2 * m1) - (-c2 * 1) * (c1 * m0)
        if abs(det) < 1e-12:
            continue
        a = (rx * (-c2 * m1) - (-c2) * ry) / det
        b = ((c1) * ry - (c1 * m0) * rx) / det
        key = (round(a, 7), round(b, 7))
        if key in tried:
            continue
        tried.add(key)
        P = [P0, (P0[0] + a, P0[1] + m0 * a), (P3[0] - b, P3[1] - m1 * b), P3]
        sc = max(1e-6, abs(P3[1] - P0[1]), max(abs(q[1] - P0[1]) for q in inner))
        # refinement: each inner bound -> nearest sample s, then linear least
        # squares on (a, b) using every bound
        for _ in range(3):
            rows = []
            for tt, vv in inner:
                s2 = min(S_GRID, key=lambda q: abs(_bez(P, q)[0] - tt) + abs(_bez(P, q)[1] - vv) / sc)
                w = 1 - s2
                k0, k1, k2, k3 = w ** 3, 3 * w * w * s2, 3 * w * s2 * s2, s2 ** 3
                rows.append((k1, -k2, tt - (k0 + k1) * P0[0] - (k2 + k3) * P3[0], 1.0))
                rows.append((k1 * m0, -k2 * m1, vv - (k0 + k1) * P0[1] - (k2 + k3) * P3[1], 1.0 / sc))
            s11 = sum((r[0] * r[3]) ** 2 for r in rows); s22 = sum((r[1] * r[3]) ** 2 for r in rows)
            s12 = sum(r[0] * r[1] * r[3] ** 2 for r in rows)
            y1 = sum(r[0] * r[2] * r[3] ** 2 for r in rows); y2 = sum(r[1] * r[2] * r[3] ** 2 for r in rows)
            dd = s11 * s22 - s12 * s12
            if abs(dd) < 1e-30:
                break
            a = (y1 * s22 - y2 * s12) / dd
            b = (s11 * y2 - s12 * y1) / dd
            P = [P0, (P0[0] + a, P0[1] + m0 * a), (P3[0] - b, P3[1] - m1 * b), P3]
        # quick check: every inner bound must fall on a sample
        ok = True
        for tt, vv in inner:
            if min(abs(_bez(P, s2)[0] - tt) + abs(_bez(P, s2)[1] - vv) / sc for s2 in S_GRID) > 2e-4:
                ok = False
                break
        if ok:
            r = _finish(P, P0, P3, sub)
            if r:
                return r
    return None


def fit_fts_segment(pcs, i, j):
    r = fit_fts_segment_exact(pcs, i, j)
    return r if r is not None else fit_fts_segment_lsq(pcs, i, j)


def fit_fts_segment_lsq(pcs, i, j):
    """Recovers (P0,P1,P2,P3) for pieces i..j-1, or None if impossible."""
    sub = pcs[i:j]
    P0 = (sub[0][0], sub[0][5])
    P3 = (sub[-1][1], _end(sub[-1]))
    m0, m1 = sub[0][4], _end_slope(sub[-1])
    h = P3[0] - P0[0]
    if h <= 1e-6:
        return None
    inner = [(p[0], p[5]) for p in sub[1:]]
    scale = max(1e-6, abs(P3[1] - P0[1]), max((abs(v - P0[1]) for _, v in inner), default=0))
    it = [t for t, _ in inner]; iv = [v for _, v in inner]

    def curve(x):
        a, b = x
        return [P0, (P0[0] + a, P0[1] + m0 * a), (P3[0] - b, P3[1] - m1 * b), P3]

    def resid(x):
        r = [(y - v) / scale for y, v in zip(_y_at(curve(x), it), iv)] if inner else []
        return r + [0.0] if len(r) < 2 else r

    # starting points: best points of a coarse grid (handles from 0.001 to h)
    grid = sorted({min(h, g) for g in (0.001, 0.003, 0.01, 0.03, 0.1, 0.2, 0.3333, 0.5, 0.7, 1.0)
                   for g in [g * (h if g > 0.005 else 1)]})
    starts = [(h / 3, h / 3)]
    if inner:
        sc = sorted((sum(v * v for v in resid((a, b))), a, b) for a in grid for b in grid)
        starts = [(a, b) for _, a, b in sc[:4]]
    cands = []
    for a0, b0 in starts:
        try:
            cands.append(_lsq2(resid, [a0, b0], 0.0, h))
        except (ZeroDivisionError, OverflowError, ValueError):
            pass
    if not inner:
        cands.insert(0, [h / 3, h / 3])
    for x in cands:
        r = _finish(curve(x), P0, P3, sub)
        if r is not None:
            return r
    return None


def fit_fts_chain(pcs):
    """Smallest number of Bezier segments that recompile identically.
    -> keyframes [(t, v, is_cp)] or None."""
    n = len(pcs)
    segs, i = [], 0
    while i < n:            # greedy: longest verified segment first
        for j in range(n, i, -1):
            P = fit_fts_segment(pcs, i, j)
            if P is not None:
                break
        else:
            return None
        segs.append(P)
        i = j
    kf = [(segs[0][0][0], segs[0][0][1], False)]
    for P in segs:
        kf += [(P[1][0], P[1][1], True), (P[2][0], P[2][1], True), (P[3][0], P[3][1], False)]
    return kf


def try_spline_exact(pcs):
    """"Spline" keys: bounds where the start slope is zero; validated by
    recompiling. -> [(t, v)] or None."""
    cand = [(p[0], p[5]) for p in pcs if p[4] == 0] + [(pcs[-1][1], _end(pcs[-1]))]
    keys = [cand[0]]
    for c in cand[1:]:
        if c[0] - keys[-1][0] > 1e-6:
            keys.append(c)
    keys = [(_r7(t), _r7(v)) for t, v in keys]
    out = []
    try:
        for a, b in zip(keys, keys[1:]):
            out += compile_spline_interval(a, b)
    except ValueError:
        return None
    return keys if _same(out, pcs) else None
