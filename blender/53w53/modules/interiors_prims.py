"""Mesh primitives for the interiors (pure python, no bpy).

Every function returns (verts, faces) with outward-facing winding, ready for
MultiMesh.mesh(). Shapes: chamfered box (bevelled edges), rounded "pillow"
box (superellipsoid), lathe (revolved profile), cylinder, oriented beam,
extruded polygon, leaf, disc. `xf` rotates/translates a (verts, faces) pair.
"""
import math

V3 = tuple


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    L = math.sqrt(_dot(a, a))
    return (a[0] / L, a[1] / L, a[2] / L) if L > 1e-12 else (0.0, 0.0, 0.0)


def newell(pts):
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx, ny, nz)


def orient(verts, faces, center):
    """Flip faces whose normal points towards `center` (star-shaped solids)."""
    out = []
    for f in faces:
        pts = [verts[i] for i in f]
        c = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
        if _dot(newell(pts), _sub(c, center)) < 0:
            f = tuple(reversed(f))
        out.append(tuple(f))
    return out


# ------------------------------------------------------------------ boxes
def cbox(x0, y0, z0, x1, y1, z1, b=0.01):
    """Axis-aligned box with chamfered (bevelled) edges, 26 faces."""
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    z0, z1 = min(z0, z1), max(z0, z1)
    b = min(b, (x1 - x0) * 0.45, (y1 - y0) * 0.45, (z1 - z0) * 0.45)
    if b < 1e-4:
        return box(x0, y0, z0, x1, y1, z1)
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
    X, Y, Z = (x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2
    verts = []
    idx = {}
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                for ax in range(3):
                    p = [sx * (X - b), sy * (Y - b), sz * (Z - b)]
                    p[ax] = (sx, sy, sz)[ax] * (X, Y, Z)[ax]
                    idx[(sx, sy, sz, ax)] = len(verts)
                    verts.append((cx + p[0], cy + p[1], cz + p[2]))
    faces = []
    # main faces
    for ax in range(3):
        for s in (-1, 1):
            corners = []
            o = [a for a in range(3) if a != ax]
            for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                sg = [0, 0, 0]
                sg[ax], sg[o[0]], sg[o[1]] = s, u, v
                corners.append(idx[(sg[0], sg[1], sg[2], ax)])
            faces.append(tuple(corners))
    # edge chamfers
    for ax in range(3):            # edge runs along axis `ax`
        o = [a for a in range(3) if a != ax]
        for su in (-1, 1):
            for sv in (-1, 1):
                q = []
                for s_ax, which in ((-1, o[0]), (1, o[0]), (1, o[1]), (-1, o[1])):
                    sg = [0, 0, 0]
                    sg[ax], sg[o[0]], sg[o[1]] = s_ax, su, sv
                    q.append(idx[(sg[0], sg[1], sg[2], which)])
                faces.append(tuple(q))
    # corner triangles
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                faces.append((idx[(sx, sy, sz, 0)], idx[(sx, sy, sz, 1)], idx[(sx, sy, sz, 2)]))
    return verts, orient(verts, faces, (cx, cy, cz))


def book(x0, y0, z0, x1, y1, z1):
    """Box with only the faces seen on a shelf (spine +y, top, two sides)."""
    verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    return verts, [(4, 5, 6, 7), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def box(x0, y0, z0, x1, y1, z1, bottom=True):
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    z0, z1 = min(z0, z1), max(z0, z1)
    verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    if bottom:
        faces.append((3, 2, 1, 0))
    return verts, faces


def rbox(x0, y0, z0, x1, y1, z1, e=0.3, nu=10, nv=6, sag=0.0):
    """Rounded 'pillow' box (superellipsoid). e: 0.15 boxy .. 1 ellipsoid.
    sag pulls the top centre down (seat cushions)."""
    cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
    X, Y, Z = abs(x1 - x0) / 2, abs(y1 - y0) / 2, abs(z1 - z0) / 2

    def sp(c, ex):
        return math.copysign(abs(c) ** ex, c)

    verts = [(cx, cy, cz - Z)]
    for j in range(1, nv):
        v = -math.pi / 2 + math.pi * j / nv
        for i in range(nu):
            u = 2 * math.pi * i / nu + math.pi / nu
            dx, dy, dz = math.cos(v) * math.cos(u), math.cos(v) * math.sin(u), math.sin(v)
            px, py, pz = sp(dx, e) * X, sp(dy, e) * Y, sp(dz, e) * Z
            if sag and pz > 0:
                k = (1 - min(1, abs(px) / X)) * (1 - min(1, abs(py) / Y))
                pz -= sag * k * (pz / Z)
            verts.append((cx + px, cy + py, cz + pz))
    top = len(verts)
    verts.append((cx, cy, cz + Z - sag))
    faces = []
    for i in range(nu):
        faces.append((0, 1 + (i + 1) % nu, 1 + i))
    for j in range(nv - 2):
        r0, r1 = 1 + j * nu, 1 + (j + 1) * nu
        for i in range(nu):
            k = (i + 1) % nu
            faces.append((r0 + i, r0 + k, r1 + k, r1 + i))
    rl = 1 + (nv - 2) * nu
    for i in range(nu):
        faces.append((rl + i, rl + (i + 1) % nu, top))
    return verts, orient(verts, faces, (cx, cy, cz))


# ------------------------------------------------------------------ revolved
def lathe(profile, seg=16, cx=0.0, cy=0.0, cap0=True, cap1=True, a0=0.0, a1=None, cap_ends=False):
    """Revolve [(r, z), ...] (bottom -> top) about the vertical axis."""
    full = a1 is None
    a1 = 2 * math.pi if full else a1
    nring = seg if full else seg + 1
    verts = []
    for r, z in profile:
        for i in range(nring):
            a = a0 + (a1 - a0) * i / seg
            verts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    faces = []
    for k in range(len(profile) - 1):
        b0, b1 = k * nring, (k + 1) * nring
        for i in range(seg):
            j = (i + 1) % nring
            if profile[k][0] < 1e-6 and profile[k + 1][0] < 1e-6:
                continue
            faces.append((b0 + i, b0 + j, b1 + j, b1 + i))
    if not full and cap_ends:                 # close a partial revolve (closed profile)
        for i, sgn in ((0, -1.0), (seg, 1.0)):
            a = a0 + (a1 - a0) * i / seg
            npf = len(profile) - (1 if tuple(profile[0]) == tuple(profile[-1]) else 0)
            f = [k * nring + i for k in range(npf)]
            nrm = newell([verts[q] for q in f])
            tx, ty = -math.sin(a) * sgn, math.cos(a) * sgn
            if nrm[0] * tx + nrm[1] * ty < 0:
                f.reverse()
            faces.append(tuple(f))
    if full:
        if cap0 and profile[0][0] > 1e-6:
            faces.append(tuple(reversed(range(seg))))
        if cap1 and profile[-1][0] > 1e-6:
            b = (len(profile) - 1) * nring
            faces.append(tuple(b + i for i in range(seg)))
    return verts, faces


def cyl(cx, cy, z0, z1, r, seg=12, cap0=True, cap1=True):
    return lathe([(r, z0), (r, z1)], seg, cx, cy, cap0, cap1)


def disc(cx, cy, z, r, seg=16, up=True):
    verts = [(cx + r * math.cos(2 * math.pi * i / seg), cy + r * math.sin(2 * math.pi * i / seg), z)
             for i in range(seg)]
    f = tuple(range(seg)) if up else tuple(reversed(range(seg)))
    return verts, [f]


# ------------------------------------------------------------------ beams / prisms
def beam(p0, p1, w, h=None, up=(0.0, 0.0, 1.0)):
    """Rectangular bar from p0 to p1 (w across, h along `up`-ish)."""
    h = h or w
    d = _norm(_sub(p1, p0))
    if abs(_dot(d, up)) > 0.95:
        up = (1.0, 0.0, 0.0)
    u = _norm(_cross(d, up))
    v = _norm(_cross(u, d))
    return obeam(p0, p1, u, v, w, h)


def obeam(p0, p1, side, nrm, w, d):
    """Bar from p0 to p1 with cross-section w along `side`, d along `nrm`."""
    cs = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    verts = []
    for p in (p0, p1):
        for a, b in cs:
            verts.append((p[0] + side[0] * w / 2 * a + nrm[0] * d / 2 * b,
                          p[1] + side[1] * w / 2 * a + nrm[1] * d / 2 * b,
                          p[2] + side[2] * w / 2 * a + nrm[2] * d / 2 * b))
    faces = [(0, 1, 2, 3), (4, 5, 6, 7)]
    for i in range(4):
        j = (i + 1) % 4
        faces.append((i, j, 4 + j, 4 + i))
    c = tuple((p0[k] + p1[k]) / 2 for k in range(3))
    return verts, orient(verts, faces, c)


def prism(poly, z0, z1):
    """Vertical extrusion of a CCW 2D polygon."""
    n = len(poly)
    verts = [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return verts, faces


def leaf(base, direction, length, width, droop=0.3, twist=0.0):
    """Folded diamond leaf: base point, unit-ish direction (3D)."""
    d = _norm(direction)
    side = _cross(d, (0.0, 0.0, 1.0))
    if _dot(side, side) < 1e-6:
        side = (1.0, 0.0, 0.0)
    side = _norm(side)
    ca, sa = math.cos(twist), math.sin(twist)
    up = _cross(side, d)
    side = tuple(side[k] * ca + up[k] * sa for k in range(3))
    tip = tuple(base[k] + d[k] * length for k in range(3))
    tip = (tip[0], tip[1], tip[2] - droop * length)
    mid = tuple(base[k] + d[k] * length * 0.45 for k in range(3))
    mid = (mid[0], mid[1], mid[2] - droop * length * 0.3)
    l = tuple(mid[k] + side[k] * width / 2 for k in range(3))
    r = tuple(mid[k] - side[k] * width / 2 for k in range(3))
    l = (l[0], l[1], l[2] - width * 0.15)
    r = (r[0], r[1], r[2] - width * 0.15)
    return [base, r, tip, l], [(0, 1, 2), (0, 2, 3)]


# ------------------------------------------------------------------ transforms
def xf(vf, rz=0.0, rx=0.0, ry=0.0, t=(0.0, 0.0, 0.0), pivot=(0.0, 0.0, 0.0)):
    """Rotate (x, then y, then z; radians) about pivot, then translate."""
    verts, faces = vf
    cx, sx = math.cos(rx), math.sin(rx)
    cy_, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    out = []
    for x, y, z in verts:
        x, y, z = x - pivot[0], y - pivot[1], z - pivot[2]
        y, z = y * cx - z * sx, y * sx + z * cx
        x, z = x * cy_ + z * sy, -x * sy + z * cy_
        x, y = x * cz - y * sz, x * sz + y * cz
        out.append((x + pivot[0] + t[0], y + pivot[1] + t[1], z + pivot[2] + t[2]))
    return out, faces


def merge(*vfs):
    verts, faces = [], []
    for v, f in vfs:
        b = len(verts)
        verts += list(v)
        faces += [tuple(b + i for i in ff) for ff in f]
    return verts, faces


def tris(vf):
    return sum(len(f) - 2 for f in vf[1])
