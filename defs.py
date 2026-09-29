"""Index of the AllSpark editor definitions (.xcd components, .xmd modules).

Builds, for each component type:
  - props: id -> PropDef(name, fullname, type, typeid, channels[(name,id)], default_datum_xml)
  - byfull: fullname -> id   (FullName as written in the .lsfx, e.g. "Appearance.Size")
and for modules:
  - modules: id -> (name, required, {component: [(propname, propid)]})
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

REQUIRED_MODULE = '286df729-035e-4bb8-a210-c836ddbbbacc'
BUILTIN = {  # common properties, not listed in the .xcd <component> entries
    'ef1d7d1e-02b6-4548-80d9-5ef2fbcda237': ('Name', 'Text'),
    '035b5248-d0ca-44b7-853f-3acb84110e67': ('Start / End Time', 'StartEnd'),
}


@dataclass
class PropDef:
    id: str
    name: str
    type: str
    typeid: str
    fullname: str = ''
    channels: list = field(default_factory=list)
    default: ET.Element = None      # default <datum>
    elem: ET.Element = None


@dataclass
class CompDef:
    name: str
    props: dict = field(default_factory=dict)     # id -> PropDef
    order: list = field(default_factory=list)     # declaration order
    byfull: dict = field(default_factory=dict)    # fullname -> id
    groups: list = field(default_factory=list)    # (group id, name, path)


class Defs:
    def __init__(self, xcd, xmd):
        self.comps = {}
        root = ET.parse(xcd).getroot()
        for c in root.find('components'):
            cd = CompDef(c.get('name'))
            props = c.find('properties')
            for p in props.findall('property'):
                d = p.find('definition')
                pid = p.get('id').lower()
                ch = []
                chs = d.find('channels') if d is not None else None
                if chs is not None:
                    ch = [(x.get('name'), x.get('id').lower()) for x in chs]
                dd = d.find('data/datum') if d is not None else None
                cd.props[pid] = PropDef(pid, p.get('name'), d.get('type') if d is not None else '',
                                        (d.get('typeid') or '').lower() if d is not None else '',
                                        channels=ch, default=dd, elem=p)
                cd.order.append(pid)
            # groups -> FullName
            def walk(g, path, top):
                name = g.get('name')
                p2 = path if top else path + [name]
                cd.groups.append((g.get('id').lower(), name, '.'.join(p2)))
                ps = g.find('properties')
                if ps is not None:
                    for r in ps.findall('property'):
                        rid = r.get('id').lower()
                        if rid in cd.props:
                            cd.props[rid].fullname = '.'.join(p2 + [cd.props[rid].name])
                ch = g.find('children')
                if ch is not None:
                    for k in ch.findall('propertygroup'):
                        walk(k, p2, False)
            for g in props.findall('propertygroup'):
                walk(g, [], True)
            for pid, pd in cd.props.items():
                if not pd.fullname:
                    pd.fullname = pd.name
                cd.byfull.setdefault(pd.fullname, pid)
            self.comps[cd.name] = cd

        self.inputs = {i.get('name'): i.get('id').lower() for i in root.find('inputs')}
        self.modules = {}
        mroot = ET.parse(xmd).getroot()
        for m in mroot.find('modules'):
            per = {}
            for p in m.find('properties').findall('property'):
                per.setdefault(p.get('component'), []).append((p.get('name'), p.get('id').lower()))
            self.modules[m.get('id').lower()] = (m.get('name'), m.get('required') == 'True', per)

    def find_module(self, comp, name, prop_fullnames):
        """Find a module from its name + the FullNames of the properties listed in the .lsfx."""
        cd = self.comps.get(comp)
        best = None
        for mid, (mname, req, per) in self.modules.items():
            if mname != name or comp not in per:
                continue
            ids = {pid for _, pid in per[comp]}
            want = {cd.byfull.get(f) for f in prop_fullnames} if cd else set()
            score = len(ids & want)
            if best is None or score > best[0]:
                best = (score, mid)
        return best[1] if best else None


if __name__ == '__main__':
    import sys
    d = Defs(sys.argv[1], sys.argv[2])
    for n, c in d.comps.items():
        print(n, len(c.props))
    for pid in d.comps['Billboard'].order:
        p = d.comps['Billboard'].props[pid]
        print(' ', p.fullname, '|', p.type, p.channels and [x for x, _ in p.channels])
