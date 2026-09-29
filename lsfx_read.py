"""Reads a .lsfx (compressed LSF) into a simple Python tree.

Node = dict(name=str, attrs={name: (lsf_type, value)}, children=[Node])
"""
import lsfc, lsf2


def read_tree(path):
    b = open(path, 'rb').read()
    d = lsf2.parse(lsfc.to_uncompressed(b))
    nodes = [dict(name=n['name'], attrs={}, children=[]) for n in d['nodes']]
    for a in d['attrs']:
        if a['node'] >= 0:
            nodes[a['node']]['attrs'][a['name']] = (a['type'], lsf2.val(d, a))
    roots = []
    for i, n in enumerate(d['nodes']):
        (roots if n['parent'] == -1 else nodes[n['parent']]['children']).append(nodes[i])
    return roots


def av(node, name, default=None):
    """Attribute value (without its type)."""
    t = node['attrs'].get(name)
    return t[1] if t else default


def kids(node, name):
    return [c for c in node['children'] if c['name'] == name]


def kid(node, name):
    k = kids(node, name)
    return k[0] if k else None
