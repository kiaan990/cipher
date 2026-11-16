"""Exterior of 53 West 53: curtain wall, exposed concrete diagrid, crown.

Geometry follows config.section(z) exactly:
  * below Z_SPLIT (the lowest spire-facet z0) the tower is the footprint prism;
  * above it, the tower is the convex polyhedron  footprint-prism  AND  the
    three full sloped planes (none of them cuts the footprint below its own
    z0 except where z0 == Z_SPLIT, which the split handles; a small horizontal
    "ledge" closes the step that appears at Z_SPLIT).

Every facade facet is a "group": one plane with an orthonormal frame
(h = horizontal, w = up the facet, N = outward normal) and one or more convex
2D pieces in (u, v) = (p.h, p.w).  Glass, mullions, spandrels, louvres and the
diagrid are all generated in those 2D coordinates and lifted back to 3D with
an outward offset along N, so nothing ever enters the floor plates.

Objects (all in collection "Exterior"):
  Ext_Glass, Ext_Mullions, Ext_Spandrels, Ext_PodiumPanels, Ext_Diagrid,
  Ext_Louvres, Ext_RoofCap, Ext_Ledge, Ext_Canopy, Ext_CrownGrille.

Above C.roof_z() (last occupied ceiling, ~290 m) the converging spire facets
are replaced by two exterior-only crown blades (see _crown): a high west
blade (~320 m) whose sloped top is a dark louvred grille, and a lower east
peak (~307 m) with a light glazed lattice top, with a V-notch between them.
Entrance opening (no geometry): x 19.4..22.6, y = 0, z 0..3.0.

ctx["diagrid_members"]: one dict per structural member (diagonals, node-level
horizontal ties, ridge/edge members) with centre-line endpoints p0/p1 in world
coordinates, width (in the facet plane), depth (along facet_normal), the
outward facet_normal, plus "kind" (diagonal | tie | ridge) and "facet".
"""
import math
import random

import mathutils

import config as C

V = mathutils.Vector

# ----------------------------------------------------------------- constants
DOOR_U = (C.ENTRANCE[0] - 1.6, C.ENTRANCE[0] + 1.6)   # 19.4 .. 22.6
DOOR_H = 3.0
CANOPY_Z = (3.30, 3.48)
GLASS_OFF = 0.02          # glass plane, outward from section boundary
SPANDREL_OFF = 0.04
PANEL_OFF = 0.05
MULL_OFF = 0.10           # mullion centre (depth 0.12 -> 0.04..0.16)
MULL_W, MULL_D = 0.075, 0.12
TRANSOM_W = 0.055
DIA_OFF = 0.27            # diagrid centre (depth 0.42 -> 0.06..0.48): near-flush
DIA_D = 0.42              # with the glass, as in photos of the finished tower
RIDGE_OFF, RIDGE_W, RIDGE_D = 0.32, 1.05, 0.58
# Colours from daylight photos (57th St view): light-medium warm grey
# architectural concrete diagrid, grey-blue reflective glass.
DIAGRID_RGBA = (0.48, 0.47, 0.45, 1.0)
GLASS_RGBA = (0.20, 0.27, 0.32, 1.0)
SEED = 5353


def _roof_z():
    return C.roof_z()


def _ext_floor_z(n):
    """floor_z extended above the last floor with 3.6 m 'virtual' storeys."""
    if n <= C.NUM_FLOORS:
        return C.floor_z(n)
    return C.roof_z() + (n - C.NUM_FLOORS - 1) * C.TYPICAL_FLOOR_H


# ----------------------------------------------------------------- 3D planes
def _footprint_planes():
    out = []
    fp = C.FOOTPRINT
    for i in range(len(fp)):
        (x1, y1), (x2, y2) = fp[i], fp[(i + 1) % len(fp)]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        a = V((dy / L, -dx / L, 0.0))
        out.append(("E%d" % i, a, a.x * x1 + a.y * y1))
    return out


def _slope_planes():
    out = []
    for i, ((nx, ny), d, z0, k) in enumerate(C._SPIRE_FACETS):
        a = V((nx, ny, k))
        L = a.length
        out.append(("S%d" % i, a / L, (d + k * z0) / L, z0))
    return out


def _clip3(poly, a, b):
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        dp, dq = a.dot(p) - b, a.dot(q) - b
        if dp <= 0:
            out.append(p)
        if (dp < 0) != (dq < 0) and dp != dq:
            t = dp / (dp - dq)
            out.append(p.lerp(q, t))
    return out


def _frame(N):
    """Orthonormal (h, w) for a plane with unit normal N; w points up."""
    L = math.hypot(N.x, N.y)
    if L < 1e-6:
        h = V((1, 0, 0))
    else:
        h = V((-N.y / L, N.x / L, 0.0))
    w = N.cross(h).normalized()
    if w.z < 0:
        h, w = -h, -w
    return h, w


def _dedupe3(poly, tol=1e-4):
    out = []
    for p in poly:
        if not out or (p - out[-1]).length > tol:
            out.append(p)
    while len(out) > 1 and (out[0] - out[-1]).length <= tol:
        out.pop()
    return out


def _face(planes, i):
    _, a, b = planes[i][:3]
    h, w = _frame(a)
    p0 = a * b
    R = 3000.0
    poly = [p0 + h * su * R + w * sv * R for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    for j, pl in enumerate(planes):
        if j == i:
            continue
        poly = _clip3(poly, pl[1], pl[2])
        if len(poly) < 3:
            return []
    poly = _dedupe3(poly)
    return poly if len(poly) >= 3 else []


# ----------------------------------------------------------------- 2D helpers
def _area2(poly):
    s = 0.0
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def _ccw(poly):
    return poly if _area2(poly) >= 0 else list(reversed(poly))


def _clip2(poly, a, b, c):
    """Keep a*u + b*v <= c."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        dp = a * p[0] + b * p[1] - c
        dq = a * q[0] + b * q[1] - c
        if dp <= 0:
            out.append(p)
        if (dp < 0) != (dq < 0) and dp != dq:
            t = dp / (dp - dq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out if len(out) >= 3 else []


def _clip_box(poly, u0=None, u1=None, v0=None, v1=None):
    if u0 is not None and poly:
        poly = _clip2(poly, -1, 0, -u0)
    if u1 is not None and poly:
        poly = _clip2(poly, 1, 0, u1)
    if v0 is not None and poly:
        poly = _clip2(poly, 0, -1, -v0)
    if v1 is not None and poly:
        poly = _clip2(poly, 0, 1, v1)
    if poly and abs(_area2(poly)) < 1e-4:
        return []
    return poly


def _hull(pts):
    pts = sorted(set((round(p[0], 6), round(p[1], 6)) for p in pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 1e-9:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 1e-9:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def _interval_v(poly, v):
    """u-interval of a convex poly on the horizontal line v (or None)."""
    vs = [p[1] for p in poly]
    vmin, vmax = min(vs), max(vs)
    if v > vmax + 1e-6 or v < vmin - 1e-6:
        return None
    if v >= vmax - 1e-4:
        us = [p[0] for p in poly if p[1] >= vmax - 1e-3]
        return (min(us), max(us))
    if v <= vmin + 1e-4:
        us = [p[0] for p in poly if p[1] <= vmin + 1e-3]
        return (min(us), max(us))
    xs = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        if (p[1] - v) * (q[1] - v) <= 0 and p[1] != q[1]:
            t = (v - p[1]) / (q[1] - p[1])
            xs.append(p[0] + t * (q[0] - p[0]))
    if not xs:
        return None
    return (min(xs), max(xs))


def _interval_u(poly, u):
    """v-interval of a convex poly on the vertical line u (or None)."""
    sw = [(p[1], p[0]) for p in poly]
    return _interval_v(sw, u)


def _seg_minus_rect(P, Q, rect):
    """Parts of segment PQ outside axis-aligned rect (u0,v0,u1,v1)."""
    u0, v0, u1, v1 = rect
    du, dv = Q[0] - P[0], Q[1] - P[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-du, P[0] - u0), (du, u1 - P[0]), (-dv, P[1] - v0), (dv, v1 - P[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return [(P, Q)]
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
    if t0 >= t1:
        return [(P, Q)]

    def at(t):
        return (P[0] + du * t, P[1] + dv * t)

    out = []
    if t0 > 1e-6:
        out.append((P, at(t0)))
    if t1 < 1 - 1e-6:
        out.append((at(t1), Q))
    return [s for s in out if math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) > 0.3]


# ----------------------------------------------------------------- groups
class Group:
    def __init__(self, name, N, c, pieces3d, is_south=False):
        self.name = name
        self.N = N.normalized()
        self.h, self.w = _frame(self.N)
        self.c = c
        self.is_south = is_south
        self.pieces = [_ccw([self.uv(p) for p in pc]) for pc in pieces3d]

    def uv(self, p):
        return (p.dot(self.h), p.dot(self.w))

    def p3(self, u, v, off=0.0):
        return self.h * u + self.w * v + self.N * (self.c + off)

    def v_of_z(self, z):
        return (z - self.c * self.N.z) / self.w.z

    def z_of_v(self, v):
        return v * self.w.z + self.c * self.N.z

    def urange(self):
        us = [p[0] for pc in self.pieces for p in pc]
        return min(us), max(us)


def _build_geometry():
    """Return (groups, ridges, ledge_polys, z_split).

    ridges: list of (p0, p1, outward_dir) in 3D."""
    fps = _footprint_planes()
    slopes = _slope_planes()
    z_split = min(s[3] for s in slopes)
    top = 1000.0
    upper = [(n, a, b) for n, a, b in fps] + [(n, a, b) for n, a, b, _ in slopes]
    upper += [("BOT", V((0, 0, -1)), -z_split), ("TOP", V((0, 0, 1)), top)]
    faces = {}
    for i, pl in enumerate(upper):
        if pl[0] in ("BOT", "TOP"):
            continue
        f = _face(upper, i)
        if f and _poly3_area(f) > 0.05:
            faces[pl[0]] = (pl[1], pl[2], f)

    groups, ridges, split_belts = [], [], []
    fp = C.FOOTPRINT
    for i, (name, a, b) in enumerate(fps):
        (x1, y1), (x2, y2) = fp[i], fp[(i + 1) % len(fp)]
        lower = [V((x1, y1, 0)), V((x2, y2, 0)), V((x2, y2, z_split)), V((x1, y1, z_split))]
        pieces = [lower]
        g = Group(name, a, b, [], is_south=(abs(a.y + 1) < 1e-6 and abs(y1) < 1e-6 and abs(y2) < 1e-6))
        if name in faces:
            up = faces[name][2]
            lo_uv = [g.uv(p) for p in lower]
            up_uv = [g.uv(p) for p in up]
            vsp = g.v_of_z(z_split)
            top_lo = _interval_v(_ccw(lo_uv), vsp)
            bot_up = _interval_v(_ccw(up_uv), vsp)
            if bot_up and top_lo and abs(bot_up[0] - top_lo[0]) < 0.05 and abs(bot_up[1] - top_lo[1]) < 0.05:
                g.pieces = [_ccw(_hull(lo_uv + up_uv))]
            else:
                g.pieces = [_ccw(lo_uv), _ccw(up_uv)]
                split_belts.append((g, vsp, top_lo))
        else:
            g.pieces = [_ccw([g.uv(p) for p in lower])]
        groups.append(g)
    for name, a, b, z0 in slopes:
        if name in faces:
            groups.append(Group(name, a, b, [faces[name][2]]))

    # ridges of the upper convex polyhedron
    names = list(faces.keys())
    for ii in range(len(names)):
        for jj in range(ii + 1, len(names)):
            ai, bi, fi = faces[names[ii]]
            aj, bj, fj = faces[names[jj]]
            on = [p for p in fi if abs(aj.dot(p) - bj) < 2e-3]
            if len(on) < 2:
                continue
            best, pair = 0.0, None
            for p in on:
                for q in on:
                    d = (p - q).length
                    if d > best:
                        best, pair = d, (p, q)
            if best < 0.5:
                continue
            p, q = pair
            if p.z > q.z:
                p, q = q, p
            ridges.append((p, q, (ai + aj).normalized()))
    # vertical corners of the lower prism
    n = len(fp)
    for k in range(n):
        x, y = fp[k]
        a_prev, a_next = fps[k - 1][1], fps[k][1]
        ridges.append((V((x, y, 0)), V((x, y, z_split)), (a_prev + a_next).normalized()))

    # ledge(s): parts of the footprint at z_split cut by slopes starting there
    ledges = []
    for name, a, b, z0 in slopes:
        if abs(z0 - z_split) > 1e-6:
            continue
        hz = V((a.x, a.y, 0))
        L = hz.length
        # plane at z_split: (a.x x + a.y y) <= b - a.z*z_split
        cpoly = list(fp)
        cpoly = C._clip(cpoly, -a.x / L, -a.y / L, -(b - a.z * z_split) / L)
        if len(cpoly) >= 3 and abs(_area2(cpoly)) > 0.05:
            pts = [V((x, y, z_split)) for x, y in cpoly]
            ledges.append(pts)
            for i in range(len(pts)):
                p, q = pts[i], pts[(i + 1) % len(pts)]
                mid = (p + q) * 0.5
                # outward normal of the side face at this edge
                side = None
                for (nm, fa, fb) in fps:
                    if abs(fa.dot(p) - fb) < 1e-3 and abs(fa.dot(q) - fb) < 1e-3:
                        side = fa
                if side is None:
                    side = a
                ridges.append((p, q, (side + V((0, 0, 1))).normalized()))
    return groups, ridges, ledges, split_belts, z_split


def _poly3_area(poly):
    s = V((0, 0, 0))
    for i in range(len(poly)):
        s += poly[i].cross(poly[(i + 1) % len(poly)])
    return 0.5 * s.length


# ----------------------------------------------------------------- emitters
class Acc:
    """Light wrapper around MeshBuilder with oriented bars and polygons."""

    def __init__(self, name, material, col, members=None):
        self.mb = C.MeshBuilder(name, C.mat(material) if isinstance(material, str) else material, col)
        self.members = members   # optional list: records centre-line members

    def poly(self, pts):
        b = len(self.mb.verts)
        self.mb.verts += [tuple(p) for p in pts]
        self.mb.faces.append(tuple(range(b, b + len(pts))))

    def bar(self, a, b, side, depth_dir, w, d, caps=True):
        s = side * (w / 2)
        t = depth_dir * (d / 2)
        cs = [-s - t, s - t, s + t, -s + t]
        base = len(self.mb.verts)
        self.mb.verts += [tuple(a + c) for c in cs] + [tuple(b + c) for c in cs]
        f = self.mb.faces
        if caps:
            f += [(base + 3, base + 2, base + 1, base), (base + 4, base + 5, base + 6, base + 7)]
        for i in range(4):
            j = (i + 1) % 4
            f.append((base + i, base + j, base + 4 + j, base + 4 + i))

    def finish(self):
        return self.mb.finish()


def _uv_bar(acc, g, P, Q, w, d, off, caps=True, kind="diagonal"):
    du, dv = Q[0] - P[0], Q[1] - P[1]
    L = math.hypot(du, dv)
    if L < 1e-4:
        return
    side = (g.h * (-dv / L) + g.w * (du / L)).normalized()
    a, b = g.p3(P[0], P[1], off), g.p3(Q[0], Q[1], off)
    acc.bar(a, b, side, g.N, w, d, caps)
    if acc.members is not None:
        acc.members.append({"p0": tuple(a), "p1": tuple(b), "width": w, "depth": d,
                            "facet_normal": tuple(g.N), "kind": kind, "facet": g.name})


def _uv_poly(acc, g, poly, off):
    acc.poly([g.p3(u, v, off) for u, v in poly])


# ----------------------------------------------------------------- bands
def _bands(rng):
    """Floor bands sharing one vertical-mullion pattern: (z0, z1, kind, floors)."""
    out = [(0.0, C.floor_z(2), "lobby", [1]),
           (C.floor_z(2), C.floor_z(7), "podium", [2, 3, 4, 5, 6])]
    # Tower: ONE continuous mullion rhythm per facet from floor 7 to the
    # crown (photos show unbroken vertical lines the full height).
    out.append((C.floor_z(7), C.roof_z() + 60.0, "typical", list(range(7, C.NUM_FLOORS + 1))))
    return out


# Tall narrow panes ~1.5 m wide, with the occasional narrow (0.75-1.0 m)
# operable pane and a few wide bays -> dense, slightly irregular rhythm.
SPACINGS = (1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 0.75, 1.0, 1.2, 1.8)
PODIUM_SPACINGS = (1.2, 1.5, 1.8, 1.8, 2.1, 2.4, 3.0)


def _mullion_us(rng, umin, umax, kind):
    us = []
    u = umin + rng.uniform(0.3, 1.2)
    while u < umax - 0.3:
        us.append(u)
        if kind == "lobby":
            u += rng.choice((2.4, 3.0, 3.0, 3.6))
        elif kind == "podium":
            u += rng.choice(PODIUM_SPACINGS)
        else:
            u += rng.choice(SPACINGS)
    return us


# ----------------------------------------------------------------- build
def build(ctx):
    col = C.collection("Exterior")
    rng = random.Random(SEED)
    groups, ridges, ledges, split_belts, z_split = _build_geometry()
    roof = C.roof_z()
    glass_top = roof + 0.3

    glass = Acc("Ext_Glass", "Glass_Curtain", col)
    gm = C.mat("Glass_Curtain")
    gm.diffuse_color = (gm.diffuse_color[0], gm.diffuse_color[1], gm.diffuse_color[2], 0.3)
    mull = Acc("Ext_Mullions", "Mullion_Alu", col)
    spand = Acc("Ext_Spandrels", C.mat("Spandrel_Dark", color=(0.10, 0.11, 0.12, 1)), col)
    panels = Acc("Ext_PodiumPanels", C.mat("Panel_Podium", color=(0.80, 0.78, 0.73, 1)), col)
    members = []
    dia = Acc("Ext_Diagrid", "Concrete_Diagrid", col, members)
    _tint(C.mat("Concrete_Diagrid"), DIAGRID_RGBA, rough=0.7)
    _tint(gm, GLASS_RGBA)
    louv = Acc("Ext_Louvres", C.mat("Louvre_Metal", color=(0.30, 0.31, 0.32, 1)), col)

    door_rect = (DOOR_U[0], -1.0, DOOR_U[1], DOOR_H)
    bands = _bands(rng)

    for gi, g in enumerate(groups):
        grng = random.Random(SEED * 31 + gi * 7919)
        vtop = g.v_of_z(glass_top)
        umin, umax = g.urange()

        band_us = [_mullion_us(grng, umin, umax, kind) for (_, _, kind, _) in bands]
        tower_us = band_us[-1]
        v_tower = g.v_of_z(C.floor_z(7))
        # ---- tower glass: one quad per pane, each with a tiny random tilt
        # (+-0.25 deg) so reflections break up pane by pane like real IGUs
        cuts_u = [umin - 1.0] + tower_us + [umax + 1.0]
        rows_v = []
        for n in range(7, C.NUM_FLOORS + 1):
            zf = C.floor_z(n)
            rows_v += [g.v_of_z(zf), g.v_of_z(zf + 1.75)]
        rows_v += [g.v_of_z(roof), vtop]
        prng = random.Random(gi * 104729 + 17)
        for pc in g.pieces:
            for r in range(len(rows_v) - 1):
                va, vb = rows_v[r], rows_v[r + 1]
                if vb - va < 0.05:
                    continue
                strip = _clip_box(pc, v0=va, v1=vb)
                if not strip:
                    continue
                for k in range(len(cuts_u) - 1):
                    cell = _clip_box(strip, u0=cuts_u[k], u1=cuts_u[k + 1])
                    if not cell:
                        continue
                    uc = sum(p[0] for p in cell) / len(cell)
                    vc = sum(p[1] for p in cell) / len(cell)
                    ta, tb = prng.uniform(-0.0045, 0.0045), prng.uniform(-0.0045, 0.0045)
                    glass.poly([g.p3(u, v, GLASS_OFF + 0.012 + ta * (u - uc) + tb * (v - vc))
                                for u, v in cell])
        # ---- base glass (lobby + podium, large panes, door cut out)
        for pc in g.pieces:
            pc = _clip_box(pc, v1=min(vtop, v_tower))
            if not pc:
                continue
            if g.is_south:
                vd = g.v_of_z(DOOR_H)
                parts = [_clip_box(pc, u1=DOOR_U[0]), _clip_box(pc, u0=DOOR_U[1]),
                         _clip_box(pc, u0=DOOR_U[0], u1=DOOR_U[1], v0=vd)]
            else:
                parts = [pc]
            for p in parts:
                if p:
                    _uv_poly(glass, g, p, GLASS_OFF)

        # ---- spandrels + horizontal mullions at every floor line
        zs = [C.floor_z(n) for n in range(2, C.NUM_FLOORS + 1)] + [roof]
        for fi, zf in enumerate(zs):
            v0, v1 = g.v_of_z(zf - 0.40), g.v_of_z(zf + 0.12)
            for pc in g.pieces:
                sp = _clip_box(pc, v0=v0, v1=v1)
                if sp:
                    _uv_poly(spand, g, sp, SPANDREL_OFF)
                for vv in (v0, v1):
                    iv = _interval_v(pc, vv)
                    if iv and iv[1] - iv[0] > 0.3:
                        _uv_bar(mull, g, (iv[0], vv), (iv[1], vv), MULL_W, MULL_D, MULL_OFF, caps=False)
                # intermediate transom: two pane rows per storey (photos)
                if zf >= C.floor_z(7) and zf < roof - 1:
                    vt = g.v_of_z(zf + 1.75)
                    iv = _interval_v(pc, vt)
                    if iv and iv[1] - iv[0] > 0.3:
                        _uv_bar(mull, g, (iv[0], vt), (iv[1], vt), TRANSOM_W, MULL_D * 0.8,
                                MULL_OFF - 0.01, caps=False)

        # ---- vertical mullions (irregular rhythm, re-drawn every band)
        for (z0, z1, kind, floors), us in zip(bands, band_us):
            vb0, vb1 = g.v_of_z(z0), g.v_of_z(min(z1, glass_top))
            for pc in g.pieces:
                for u in us:
                    iv = _interval_u(pc, u)
                    if not iv:
                        continue
                    a, b = max(iv[0], vb0), min(iv[1], vb1)
                    if b - a < 0.3:
                        continue
                    segs = [((u, a), (u, b))]
                    if g.is_south:
                        r = (door_rect[0] - MULL_W, door_rect[1], door_rect[2] + MULL_W, door_rect[3] + 0.1)
                        segs = _seg_minus_rect(segs[0][0], segs[0][1], r)
                    for P, Q in segs:
                        _uv_bar(mull, g, P, Q, MULL_W, MULL_D, MULL_OFF, caps=False)
                # podium: opaque gallery panels in a random subset of bays
                if kind == "podium":
                    cuts = [umin - 1] + us + [umax + 1]
                    for n in floors:
                        zf0, zf1 = C.floor_z(n), C.floor_z(n) + C.floor_height(n)
                        for k in range(len(cuts) - 1):
                            if grng.random() < 0.45:
                                continue
                            pp = _clip_box(pc, u0=cuts[k], u1=cuts[k + 1],
                                           v0=g.v_of_z(zf0 + 0.15), v1=g.v_of_z(zf1 - 0.45))
                            if pp:
                                _uv_poly(panels, g, pp, PANEL_OFF)

        # ---- lobby door frame + canopy
        if g.is_south:
            vd = g.v_of_z(DOOR_H)
            for u in (DOOR_U[0] - 0.07, DOOR_U[1] + 0.07):
                _uv_bar(mull, g, (u, g.v_of_z(0)), (u, vd + 0.14), 0.14, 0.18, MULL_OFF)
            _uv_bar(mull, g, (DOOR_U[0] - 0.14, vd + 0.07), (DOOR_U[1] + 0.14, vd + 0.07), 0.14, 0.18, MULL_OFF)

        # ---- diagrid
        _diagrid(dia, g, grng, door_rect)

    # ---- ridge (edge) members
    for p, q, n in ridges:
        clipped = False
        if p.z >= roof - 0.05:
            continue                     # above the roof: crown blades instead
        if q.z > roof:
            q = p.lerp(q, (roof - p.z) / (q.z - p.z))
            clipped = True
        d = q - p
        if d.length < 0.3:
            continue
        side = d.cross(n).normalized()
        dn = n.normalized()
        # extend slightly so ridge members meet at corners
        e = d.normalized() * 0.4
        a, b = p - e, (q if clipped else q + e)
        if p.z < 0.01:
            a = p.copy()
        acc_off = dn * RIDGE_OFF
        dia.bar(a + acc_off, b + acc_off, side, dn, RIDGE_W, RIDGE_D)
        members.append({"p0": tuple(a + acc_off), "p1": tuple(b + acc_off), "width": RIDGE_W,
                        "depth": RIDGE_D, "facet_normal": tuple(dn), "kind": "ridge", "facet": "ridge"})

    # belts where a facet changes plane at z_split (the west ledge)
    for g, vsp, iv in split_belts:
        if iv:
            _uv_bar(dia, g, (iv[0], vsp), (iv[1], vsp), 1.0, DIA_D, DIA_OFF, kind="tie")

    ctx["diagrid_members"] = members
    # ---- objects (glass, mullions, louvres, diagrid finish after the crown)
    for acc in (spand, panels):
        acc.finish()

    roofm = C.mat("Roof_Membrane", color=(0.22, 0.22, 0.23, 1))
    sec = C.section(roof)
    if sec:
        C.prism("Ext_RoofCap", sec, roof, roof + 0.35, roofm, col)
    for i, lp in enumerate(ledges):
        C.mesh_object("Ext_Ledge" if i == 0 else "Ext_Ledge.%d" % i,
                      [tuple(p + V((0, 0, 0.02))) for p in lp], [tuple(range(len(lp)))], roofm, col)

    # canopy over the entrance (outside the glass, y < 0)
    can = C.MeshBuilder("Ext_Canopy", C.mat("Metal_Dark"), col)
    cx = C.ENTRANCE[0]
    can.add_box(cx - 2.6, -2.4, CANOPY_Z[0], cx + 2.6, -0.02, CANOPY_Z[1])
    for sx in (-2.2, 2.2):
        can.add_beam((cx + sx, -2.3, CANOPY_Z[1]), (cx + sx, -0.05, 5.6), 0.06)
    can.finish()

    # two-peak crown above the last occupied floor (exterior-only)
    _crown(col, roof, glass, mull, louv, dia, members)
    for acc in (glass, mull, louv, dia):
        acc.finish()


def _tint(m, rgba, rough=None):
    """Set the viewport + Principled base colour (materials.py may refine)."""
    m.diffuse_color = (rgba[0], rgba[1], rgba[2], m.diffuse_color[3])
    if m.use_nodes:
        b = m.node_tree.nodes.get("Principled BSDF")
        if b:
            b.inputs["Base Color"].default_value = rgba
            if rough is not None:
                b.inputs["Roughness"].default_value = rough


def _row_levels(rng):
    """Node elevations for one facet: irregular, denser toward the base
    (every 2-4 storeys in the podium, 4-8 storeys in the shaft)."""
    zs = [0.0]
    n = 1 + rng.choice((0, 1))
    while True:
        if n < 10:
            n += rng.choice((2, 3, 3, 4))
        elif n < 40:
            n += rng.choice((4, 5, 5, 6, 7))
        else:
            n += rng.choice((5, 6, 7, 8))
        z = _ext_floor_z(n)
        if z > C.SPIRE_TIP_Z:
            break
        zs.append(z)
    return zs


def _member_w(z, rng):
    """Diagonal width: ~1.5 m at grade tapering to ~0.75 m at the crown."""
    t = min(1.0, max(0.0, z / 300.0))
    return rng.uniform(0.92, 1.08) * (1.55 - 0.8 * t)


def _diagrid(acc, g, rng, door_rect):
    levels = _row_levels(rng)
    for pc in g.pieces:
        vs = [p[1] for p in pc]
        vmin, vmax = min(vs), max(vs)
        zmin, zmax = g.z_of_v(vmin), g.z_of_v(vmax)
        zmax = min(zmax, C.roof_z())          # the crown blades take over above
        if zmax - zmin < 1.0:
            continue
        vmax = g.v_of_z(zmax)
        rows_z = [zmin] + [z for z in levels if zmin + 2.5 < z < zmax - 2.5] + [zmax]
        rows = []
        for r, z in enumerate(rows_z):
            v = g.v_of_z(z)
            v = min(max(v, vmin), vmax)
            iv = _interval_v(pc, v)
            if not iv:
                continue
            ua, ub = iv
            W = ub - ua
            if W < 1.0:
                rows.append([((ua + ub) / 2, v, 0.5)])
                continue
            zr = g.z_of_v(v)
            spacing = rng.uniform(9.0, 12.0) if zr < 40 else rng.uniform(12.0, 17.0)
            N = max(1, int(round(W / spacing)))
            s = 0.5 if (r % 2) else 0.0
            ts = [0.0, 1.0]
            for k in range(N + 1):
                t = (k + s) / N + rng.uniform(-0.16, 0.16) / N
                if 0.22 / N < t < 1 - 0.22 / N:
                    ts.append(t)
            ts = sorted(ts)
            nodes = []
            for t in ts:
                u = ua + t * W
                if g.is_south and z < 1.0 and door_rect[0] - 4.0 < u < door_rect[2] + 4.0 and 0 < t < 1:
                    continue
                nodes.append((u, v, t))
            rows.append(nodes)
        for lo, up in zip(rows, rows[1:]):
            for P, Q in _zipper(lo, up):
                segs = [(P, Q)]
                if g.is_south:
                    r = (door_rect[0] - 1.6, -1.0, door_rect[2] + 1.6, CANOPY_Z[1] + 1.2)
                    segs = _seg_minus_rect(P, Q, r)
                zmid = g.z_of_v((P[1] + Q[1]) / 2)
                w = _member_w(zmid, rng)
                for a, b in segs:
                    _uv_bar(acc, g, a, b, w, DIA_D, DIA_OFF)
        # horizontal ties at some node levels (visible in photos as flat
        # bands linking the diagonal nodes), never at grade
        for r, nodes in enumerate(rows[1:-1], start=1):
            if len(nodes) < 2 or rng.random() > 0.45:
                continue
            P, Q = nodes[0], nodes[-1]
            z = g.z_of_v(P[1])
            segs = [((P[0], P[1]), (Q[0], Q[1]))]
            if g.is_south:
                segs = _seg_minus_rect(segs[0][0], segs[0][1],
                                       (door_rect[0] - 1.6, -1.0, door_rect[2] + 1.6, CANOPY_Z[1] + 1.2))
            for a, b in segs:
                _uv_bar(acc, g, a, b, 0.75 * _member_w(z, rng), DIA_D * 0.9, DIA_OFF, kind="tie")


def _zipper(lo, up):
    """Non-crossing triangulation between two node rows (sorted by t).
    Skips the two side edges (they lie on ridges, which get edge members)."""
    out = []
    i = j = 0

    def side_edge(a, b):
        return (a[2] <= 0.0 and b[2] <= 0.0) or (a[2] >= 1.0 and b[2] >= 1.0)

    single = len(lo) == 1 or len(up) == 1

    def add(a, b):
        if single and (a[2] in (0.0, 1.0) or b[2] in (0.0, 1.0)):
            return
        if not side_edge(a, b) and not (len(lo) == 1 and len(up) == 1):
            out.append(((a[0], a[1]), (b[0], b[1])))

    add(lo[0], up[0])
    while i < len(lo) - 1 or j < len(up) - 1:
        if i == len(lo) - 1:
            j += 1
        elif j == len(up) - 1:
            i += 1
        elif lo[i + 1][2] < up[j + 1][2]:
            i += 1
        else:
            j += 1
        add(lo[i], up[j])
    return out


# ----------------------------------------------------------------- crown
# Heights (m) of the blade tops above each roof-section vertex.  The roof
# section is a triangle: SW, SE on the 53rd St side and the N apex; it is
# split by the N-S line through the apex into a WEST (high) and EAST (low)
# blade.  Calibrated on the 57th St photo (crown_ref.jpg): high blade top
# ~320 m sloping down to the north, lower peak ~307 m sloping into the notch.
CROWN_W = {"SW": 309.5, "S1": 319.4, "S": 320.0, "N": 297.0}
CROWN_E = {"SE": 307.0, "SE1": 306.4, "S": 297.5, "N": 296.0}
CROWN_FLAT = 2.4      # length of the short, nearly level top edge of each peak
CROWN_PANE_U, CROWN_PANE_V = 1.5, 1.8
CROWN_TAPER = 0.5     # fraction of the shaft's taper carried into the blades


def _crown_frame(pts):
    """Group for a planar 3D polygon (outward = right-hand rule CCW)."""
    nrm = V((0, 0, 0))
    for i in range(len(pts)):
        nrm += pts[i].cross(pts[(i + 1) % len(pts)])
    nrm.normalize()
    return Group("CR", nrm, nrm.dot(pts[0]), [pts])


def _seg_in_poly(poly, P, Q):
    """Clip segment PQ (uv) to a convex CCW polygon (Cyrus-Beck)."""
    t0, t1 = 0.0, 1.0
    du, dv = Q[0] - P[0], Q[1] - P[1]
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        nx, ny = ey, -ex                      # outward normal of a CCW edge
        num = nx * (P[0] - a[0]) + ny * (P[1] - a[1])
        den = nx * du + ny * dv
        if abs(den) < 1e-12:
            if num > 0:
                return None
            continue
        t = -num / den
        if den < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 >= t1:
            return None
    return (P[0] + du * t0, P[1] + dv * t0), (P[0] + du * t1, P[1] + dv * t1)


def _crown_glass_face(g, glass, mull, prng, v_base):
    """Vertical crown face: panes + mullions + transoms continuing the shaft."""
    pc = g.pieces[0]
    umin, umax = g.urange()
    vs = [p[1] for p in pc]
    us = []
    u = umin + 0.75
    while u < umax - 0.3:
        us.append(u)
        u += CROWN_PANE_U
    vrows = []
    v = v_base
    while v < max(vs):
        vrows.append(v)
        v += CROWN_PANE_V
    vrows.append(max(vs) + 0.01)
    cuts = [umin - 1] + us + [umax + 1]
    for va, vb in zip(vrows, vrows[1:]):
        strip = _clip_box(pc, v0=va, v1=vb)
        if not strip:
            continue
        for k in range(len(cuts) - 1):
            cell = _clip_box(strip, u0=cuts[k], u1=cuts[k + 1])
            if not cell:
                continue
            uc = sum(p[0] for p in cell) / len(cell)
            vc = sum(p[1] for p in cell) / len(cell)
            ta, tb = prng.uniform(-0.0045, 0.0045), prng.uniform(-0.0045, 0.0045)
            glass.poly([g.p3(uu, vv, GLASS_OFF + 0.012 + ta * (uu - uc) + tb * (vv - vc)) for uu, vv in cell])
    for u in us:
        iv = _interval_u(pc, u)
        if iv and iv[1] - iv[0] > 0.3:
            _uv_bar(mull, g, (u, iv[0]), (u, iv[1]), MULL_W, MULL_D, MULL_OFF, caps=False)
    for v in vrows[1:-1]:
        iv = _interval_v(pc, v)
        if iv and iv[1] - iv[0] > 0.3:
            _uv_bar(mull, g, (iv[0], v), (iv[1], v), MULL_W, MULL_D, MULL_OFF, caps=False)


def _crown(col, roof, glass, mull, louv, dia, members):
    sec = C.section(roof)
    if len(sec) != 3:
        return
    # identify N apex (max y) and the two south corners
    n_i = max(range(3), key=lambda i: sec[i][1])
    south = [sec[i] for i in range(3) if i != n_i]
    sw, se = sorted(south, key=lambda p: p[0])
    nx_, ny_ = sec[n_i]
    # split point on the south edge directly below the apex
    t = (nx_ - sw[0]) / (se[0] - sw[0])
    sx, sy = nx_, sw[1] + t * (se[1] - sw[1])
    P2 = {"SW": sw, "SE": se, "N": (nx_, ny_), "S": (sx, sy)}

    # The blades keep tapering (at half the shaft's rate) by a z-dependent
    # homothety about the spire axis; it maps planes to planes, so every
    # blade face stays planar and the shared split wall stays shared.
    cx, cy = C.SPIRE_TIP_X, C.SPIRE_TIP_Y
    rate = CROWN_TAPER / max(1.0, C.SPIRE_TIP_Z - roof)

    def pt(k, z):
        f = 1.0 - rate * (z - roof)
        return V((cx + (P2[k][0] - cx) * f, cy + (P2[k][1] - cy) * f, z))

    grille = Acc("Ext_CrownGrille", C.mat("Louvre_Backing", color=(0.05, 0.055, 0.06, 1)), col)
    prng = random.Random(9091)
    edges = {}

    def edge(a, b):
        key = tuple(sorted((tuple(round(c, 2) for c in a), tuple(round(c, 2) for c in b))))
        edges[key] = (a, b)

    # extra points on the south edge, CROWN_FLAT m in from each blade's
    # tip, so each peak ends in a short, nearly level edge (not a needle)
    def on_south(a, b, dist):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        t = dist / L
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    P2["S1"] = on_south(P2["S"], P2["SW"], CROWN_FLAT)      # west of S
    P2["SE1"] = on_south(P2["SE"], P2["S"], CROWN_FLAT)     # west of SE
    HW, HE = CROWN_W, CROWN_E

    def B(k):
        return pt(k, roof)

    def TW(k):
        return pt(k, HW[k])

    def TE(k):
        return pt(k, HE[k])

    blades = {
        "W": {"cen": (B("SW") + B("S") + B("N")) / 3,
              "sides": [[B("SW"), B("S"), TW("S"), TW("S1"), TW("SW")],
                        [B("N"), B("SW"), TW("SW"), TW("N")]],
              "tops": [[TW("SW"), TW("S1"), TW("N")], [TW("S1"), TW("S"), TW("N")]]},
        "E": {"cen": (B("S") + B("SE") + B("N")) / 3,
              "sides": [[B("S"), B("SE"), TE("SE"), TE("SE1"), TE("S")],
                        [B("SE"), B("N"), TE("N"), TE("SE")]],
              "tops": [[TE("S"), TE("SE1"), TE("N")], [TE("SE1"), TE("SE"), TE("N")]]},
    }
    # the V-notch wall: west blade's split face above the east blade's top
    notch = [TE("S"), TE("N"), TW("N"), TW("S")]
    if HW["N"] - HE["N"] < 0.05:
        notch = [TE("S"), TE("N"), TW("S")]
    blades["W"]["sides"].append(notch)

    for tag, bl in blades.items():
        cen = bl["cen"]
        for fi, face in enumerate(bl["sides"]):
            g = _crown_frame(face)
            fc = sum(face, V((0, 0, 0))) / len(face)
            if g.N.dot(fc - V((cen.x, cen.y, fc.z))) < 0:
                face = list(reversed(face))
                g = _crown_frame(face)
            is_notch = face is notch or fi == 2
            v_from = g.v_of_z(min(p.z for p in face))
            _crown_glass_face(g, glass, mull, prng, v_from)
            for a, b in zip(face, face[1:] + face[:1]):
                if abs(a.z - roof) < 0.01 and abs(b.z - roof) < 0.01:
                    continue
                edge(a, b)
            if not is_notch:
                # one diagonal across each outer face (continuing the diagrid)
                pc = g.pieces[0]
                umin, umax = g.urange()
                vb = g.v_of_z(roof)
                lean = (tag == "W") == (fi == 0)
                ua, ub = (umin + 0.8, umax - 0.8) if lean else (umax - 0.8, umin + 0.8)
                iv = _interval_u(pc, ub)
                if iv and iv[1] - vb > 6.0:
                    _uv_bar(dia, g, (ua, vb), (ub, iv[1] - 0.8), _member_w(roof, prng), DIA_D,
                            DIA_OFF, kind="crown")
        for tf in bl["tops"]:
            g = _crown_frame(tf)
            if g.N.z < 0:
                tf = list(reversed(tf))
                g = _crown_frame(tf)
            pc = g.pieces[0]
            umin, umax = g.urange()
            vs = [p[1] for p in pc]
            for a, b in zip(tf, tf[1:] + tf[:1]):
                edge(a, b)
            if tag == "W":
                # dark louvred grille: backing + slats across the slope
                _uv_poly(grille, g, pc, 0.03)
                v = min(vs) + 0.35
                while v < max(vs) - 0.2:
                    iv = _interval_v(pc, v)
                    if iv and iv[1] - iv[0] > 0.4:
                        _uv_bar(louv, g, (iv[0] + 0.1, v), (iv[1] - 0.1, v), 0.32, 0.10, 0.16, caps=False)
                    v += 0.55
            else:
                # light glazed lattice: glass with a diamond grid of light members
                _uv_poly(glass, g, pc, GLASS_OFF + 0.01)
                span = (umax - umin) + (max(vs) - min(vs))
                k = -span
                while k < span:
                    for sgn in (1, -1):
                        P = (umin + k, min(vs) - 0.01)
                        Q = (umin + k + sgn * span * 2, min(vs) + span * 2)
                        seg = _seg_in_poly(pc, P, Q)
                        if seg and math.hypot(seg[1][0] - seg[0][0], seg[1][1] - seg[0][1]) > 0.4:
                            _uv_bar(mull, g, seg[0], seg[1], 0.09, 0.12, 0.08, caps=False)
                    k += 1.6
    # edge members along every crown edge (continuing the shaft's ridges)
    for a, b in edges.values():
        d = b - a
        if d.length < 0.3:
            continue
        mid = (a + b) * 0.5
        cen = V((P2["N"][0] * 0.4 + P2["S"][0] * 0.6, (P2["N"][1] + P2["S"][1]) / 2, mid.z))
        n = mid - cen
        dn = d.normalized()
        n = (n - dn * n.dot(dn))
        if n.length < 1e-4:
            continue
        n.normalize()
        side = d.cross(n).normalized()
        w = RIDGE_W * 0.8
        off = n * (RIDGE_OFF * 0.8)
        dia.bar(a + off, b + off, side, n, w, RIDGE_D * 0.8)
        members.append({"p0": tuple(a + off), "p1": tuple(b + off), "width": w, "depth": RIDGE_D * 0.8,
                        "facet_normal": tuple(n), "kind": "crown", "facet": "crown"})
    grille.finish()
