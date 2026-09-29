"""Re-implementation of the AllSpark editor's curve compiler
(FloatRampChannel.GenerateSplineValues / GenerateFreeTangentSplineValues).

A Bezier curve (P0, P1, P2, P3) in (time, value) is split into cubic Hermite
pieces: on each piece [s0, s1] (Bezier parameter) the polynomial goes through
B(s0), B(s1) with the exact slopes dy/dx at those points. Recursive split
(depth <= 10) wherever the slope error exceeds 1% of the slope range
(samples every 0.02)."""
from array import array


def f32(x):
    """Rounds to a 32-bit float (like C# floats)."""
    return array('f', [x])[0]


def bez(P, s):
    s = f32(s); u = f32(1 - s)
    b0 = f32(f32(u * u) * u); b1 = f32(f32(f32(3 * u) * u) * s)
    b2 = f32(f32(f32(3 * u) * s) * s); b3 = f32(f32(s * s) * s)
    x = f32(f32(f32(f32(b0 * P[0][0]) + f32(b1 * P[1][0])) + f32(b2 * P[2][0])) + f32(b3 * P[3][0]))
    y = f32(f32(f32(f32(b0 * P[0][1]) + f32(b1 * P[1][1])) + f32(b2 * P[2][1])) + f32(b3 * P[3][1]))
    return x, y


def dbez(P, s):
    s = f32(s); u = f32(1 - s)
    c0 = f32(f32(3 * u) * u); c1 = f32(f32(6 * u) * s); c2 = f32(f32(3 * s) * s)
    dx = f32(f32(f32(c0 * f32(P[1][0] - P[0][0])) + f32(c1 * f32(P[2][0] - P[1][0]))) + f32(c2 * f32(P[3][0] - P[2][0])))
    dy = f32(f32(f32(c0 * f32(P[1][1] - P[0][1])) + f32(c1 * f32(P[2][1] - P[1][1]))) + f32(c2 * f32(P[3][1] - P[2][1])))
    return dx, dy


def create(s0, s1, P):
    x0, y0 = bez(P, s0)
    x1, y1 = bez(P, s1)
    d0 = dbez(P, s0)
    d1 = dbez(P, s1)
    if d0[0] == 0 or d1[0] == 0:
        raise ValueError('Ramp should not be a vertical line')
    dy = f32(y1 - y0); dx = f32(x1 - x0)
    m0 = f32(d0[1] / d0[0]); m1 = f32(d1[1] / d1[0])
    A = f32(f32(-2.0 * float(dy) / float(dx) + (float(m0) + float(m1))) / dx / dx)
    B = f32(f32(3.0 * float(dy) / float(dx) - (2.0 * float(m0) + float(m1))) / dx)
    return dict(start=x0, end=f32(x0 + dx), A=A, B=B, C=m0, D=y0)


def slope(pc, x):
    u = f32(x - pc['start'])
    return f32(f32(u * f32(f32(f32(3 * u) * pc['A']) + f32(2 * pc['B']))) + pc['C'])


def samples(P, spline):
    pts = []
    s = f32(0.02) if spline else f32(0.0)
    while (s < 1.0) if spline else (s <= 1.0):
        x, y = bez(P, s)
        dx, dy = dbez(P, s)
        if dx != 0:
            pts.append((x, s, f32(dy / dx)))
        s = f32(s + f32(0.02))
    return pts


def _feq(a, b, eps):
    return abs(float(a) - float(b)) <= eps


def compile_fts(P):
    """P = 4 points (x, y). -> list of pieces (dict start,end,A,B,C,D)."""
    P = [[f32(p[0]), f32(p[1])] for p in P]
    pts = samples(P, False)
    sl = [p[2] for p in pts]
    tol = max(f32(f32(max(sl) - min(sl)) * f32(0.01)), f32(1e-5)) if sl else f32(1e-5)

    def rec(s0, s1, Q, depth):
        Q = [list(q) for q in Q]
        if _feq(Q[1][0], Q[0][0], 1e-4):
            Q[1][0] = f32(Q[1][0] + f32(0.001))
        if _feq(Q[3][0], Q[2][0], 1e-4):
            Q[2][0] = f32(Q[2][0] - f32(0.001))
        pc = create(s0, s1, Q)
        best, split, found = tol, s1, False
        for X, perc, sp in pts:
            if not perc > s0:
                continue
            if not perc < s1:
                break
            e = abs(slope(pc, X) - sp)
            if e > best:
                best, split, found = e, perc, True
        if depth > 9:
            found = False
        if found and not _feq(split, s1, 1e-4):
            return rec(s0, split, Q, depth + 1) + rec(split, s1, Q, depth + 1)
        return [pc]
    return rec(f32(0), f32(1), P, 0)


def compile_spline_interval(k0, k1):
    """Spline: horizontal handles, half the interval long."""
    (t0, v0), (t1, v1) = k0, k1
    h = f32((float(t1) - float(t0)) / 2.0)
    P = [[f32(t0), f32(v0)], [f32(t0 + h), f32(v0)], [f32(t1 - h), f32(v1)], [f32(t1), f32(v1)]]
    pts = samples(P, True)
    sl = [p[2] for p in pts]
    tol = max(f32(f32(max(sl) - min(sl)) * f32(0.01)), f32(1e-5)) if sl else f32(1e-5)

    def rec(s0, s1, depth):
        pc = create(s0, s1, P)
        best, splitx, found = tol, pc['end'], False
        for X, perc, sp in pts:
            if not X > pc['start']:
                continue
            if not X < pc['end']:
                break
            e = abs(slope(pc, X) - sp)
            if e > best:
                best, splitx, found = e, X, True
        if depth > 9:
            found = False
        if found:
            sm = f32((float(splitx) - float(P[0][0])) / (float(P[3][0]) - float(P[0][0])))
            if not _feq(sm, s1, 1e-4):
                return rec(s0, sm, depth + 1) + rec(sm, s1, depth + 1)
        return [pc]
    return rec(f32(0), f32(1), 0)


def compile_channel(rtype, keyframes):
    """keyframes = [(t, v)] (FTS: anchor, cp, cp, anchor, ...). -> pieces."""
    out = []
    if rtype == 'Spline':
        for a, b in zip(keyframes, keyframes[1:]):
            if float(b[0]) - float(a[0]) >= 1e-6:
                out += compile_spline_interval(a, b)
    else:
        for i in range(0, len(keyframes) - 3, 3):
            seg = keyframes[i:i + 4]
            if float(seg[3][0]) - float(seg[0][0]) >= 1e-6:
                out += compile_fts(seg)
    return out
