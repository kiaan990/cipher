"""Geometry kit for the site module: material-merged builders + primitives.

Everything is accumulated into one MeshBuilder per (group, material, collide)
so the whole Midtown context ends up as a few dozen objects.
"""
import math
import config as C

# Site-only materials (created on demand through C.mat)
COLORS = {
    "Curb_Granite":     (0.62, 0.62, 0.60, 1),
    "Road_Marking":     (0.85, 0.85, 0.82, 1),
    "Road_Yellow":      (0.85, 0.68, 0.10, 1),
    "Window_Dark":      (0.10, 0.12, 0.14, 1),
    "Storefront":       (0.16, 0.20, 0.23, 1),
    "Granite_Black":    (0.07, 0.07, 0.075, 1),
    "Alu_Panel":        (0.62, 0.64, 0.66, 1),
    "Marble_White":     (0.88, 0.87, 0.84, 1),
    "Thermolux":        (0.78, 0.80, 0.78, 1),
    "MoMA_Charcoal":    (0.20, 0.21, 0.22, 1),
    "Limestone_Church": (0.72, 0.68, 0.60, 1),
    "Roof_Slate":       (0.22, 0.24, 0.26, 1),
    "Roof_Grey":        (0.38, 0.38, 0.38, 1),
    "Stone_Light":      (0.78, 0.75, 0.68, 1),
    "Brick_Light":      (0.58, 0.40, 0.30, 1),
    "Glass_Blue":       (0.22, 0.32, 0.40, 1),
    "Glass_Green":      (0.24, 0.34, 0.32, 1),
    "Taxi_Yellow":      (0.95, 0.70, 0.05, 1),
    "Tire_Black":       (0.03, 0.03, 0.03, 1),
    "Car_Glass":        (0.10, 0.13, 0.16, 1),
    "Lamp_Grey":        (0.30, 0.32, 0.33, 1),
    "Hydrant_Red":      (0.60, 0.08, 0.06, 1),
    "Bark":             (0.22, 0.16, 0.11, 1),
    "Soil":             (0.16, 0.12, 0.09, 1),
    "Kiosk_Green":      (0.12, 0.28, 0.20, 1),
    "Garden_Paving":    (0.70, 0.68, 0.64, 1),
    "Pool_Dark":        (0.10, 0.20, 0.24, 1),
}


def material(name):
    return C.mat(name, color=COLORS.get(name))


class Kit:
    def __init__(self, col):
        self.col = col
        self.builders = {}

    def b(self, mat, group="Bldg", collide=True):
        key = (group, mat, collide)
        mb = self.builders.get(key)
        if mb is None:
            name = f"Site_{group}_{mat}" + ("" if collide else "_nc")
            mb = C.MeshBuilder(name, material(mat), self.col)
            self.builders[key] = mb
        return mb

    def finish(self):
        objs = []
        for (group, mat, collide), mb in self.builders.items():
            ob = mb.finish()
            if ob is None:
                continue
            ob["collide"] = bool(collide)
            ob["floor"] = 0
            ob["site_group"] = group
            objs.append(ob)
        return objs

    # ------------------------------------------------------------ primitives
    def prism(self, mat, poly, z0, z1, group="Bldg", collide=True, bottom=False):
        mb = self.b(mat, group, collide)
        b = len(mb.verts)
        n = len(poly)
        mb.verts += [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
        if bottom:
            mb.faces.append(tuple(b + i for i in reversed(range(n))))
        mb.faces.append(tuple(b + n + i for i in range(n)))
        for i in range(n):
            j = (i + 1) % n
            mb.faces.append((b + i, b + j, b + n + j, b + n + i))

    def box(self, mat, x0, y0, z0, x1, y1, z1, group="Bldg", collide=True, bottom=False):
        self.prism(mat, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, group, collide, bottom)

    def quad(self, mat, a, b_, c, d, group="Bldg", collide=False):
        self.b(mat, group, collide).add_quad(a, b_, c, d)

    def ngon(self, mat, pts, group="Bldg", collide=False):
        self.b(mat, group, collide).extend(pts, [tuple(range(len(pts)))])

    def hquad(self, mat, x0, y0, x1, y1, z, group="Street", collide=False):
        """Horizontal quad facing up."""
        self.quad(mat, (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), group, collide)

    def cyl(self, mat, cx, cy, z0, z1, r0, r1=None, n=8, group="Furn", collide=True, top=True):
        r1 = r0 if r1 is None else r1
        mb = self.b(mat, group, collide)
        b = len(mb.verts)
        for k in range(n):
            a = 2 * math.pi * k / n
            mb.verts.append((cx + r0 * math.cos(a), cy + r0 * math.sin(a), z0))
        for k in range(n):
            a = 2 * math.pi * k / n
            mb.verts.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a), z1))
        for k in range(n):
            j = (k + 1) % n
            mb.faces.append((b + k, b + j, b + n + j, b + n + k))
        if top:
            mb.faces.append(tuple(b + n + k for k in range(n)))

    def beam(self, mat, p0, p1, w, h=None, group="Furn", collide=True):
        self.b(mat, group, collide).add_beam(p0, p1, w, h)

    def part(self, mat, verts, faces, loc, rot=0.0, group="Furn", collide=True):
        """Add local geometry rotated about z by rot and moved to loc."""
        c, s = math.cos(rot), math.sin(rot)
        lx, ly, lz = loc
        vv = [(lx + x * c - y * s, ly + x * s + y * c, lz + z) for x, y, z in verts]
        self.b(mat, group, collide).extend(vv, faces)


# ---------------------------------------------------------------- local shapes
def box_vf(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


def merge_vf(*parts):
    V, F = [], []
    for v, f in parts:
        b = len(V)
        V += v
        F += [tuple(b + i for i in ff) for ff in f]
    return V, F


def xz_prism_vf(profile, y0, y1):
    """Extrude a CCW (x, z) profile along y from y0 to y1."""
    n = len(profile)
    v = [(x, y0, z) for x, z in profile] + [(x, y1, z) for x, z in profile]
    f = [tuple(range(n)), tuple(n + i for i in reversed(range(n)))]
    for i in range(n):
        j = (i + 1) % n
        f.append((j, i, n + i, n + j))
    return v, f


def wheel_vf(x, y0, y1, r, z, n=8):
    """Wheel: n-gon in xz plane extruded along y."""
    prof = [(x + r * math.cos(2 * math.pi * k / n), z + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    return xz_prism_vf(prof, y0, y1)


_ICO = None
_ICO0 = None


def ico_vf(level=1):
    """Unit icosphere (subdiv 1, 80 tris; level 0: icosahedron), cached."""
    global _ICO, _ICO0
    if level == 0:
        if _ICO0 is None:
            t = (1 + 5 ** 0.5) / 2
            v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
                 (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
            L = math.sqrt(1 + t * t)
            ico_vf(1)
            _ICO0 = ([tuple(c / L for c in p) for p in v], _ICO[2])
        return _ICO0[0], _ICO0[1]
    if _ICO is None:
        t = (1 + 5 ** 0.5) / 2
        v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
             (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
        f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
        v = [tuple(c / math.sqrt(sum(cc * cc for cc in p)) for c in p) for p in v]
        cache = {}

        def mid(a, b):
            k = (min(a, b), max(a, b))
            if k not in cache:
                p = [(v[a][i] + v[b][i]) / 2 for i in range(3)]
                L = math.sqrt(sum(c * c for c in p))
                v.append(tuple(c / L for c in p))
                cache[k] = len(v) - 1
            return cache[k]
        nf = []
        for a, b, c in f:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        _ICO = (v, nf, f)
    return _ICO[0], _ICO[1]


# ---------------------------------------------------------------- facades
def edge_normal(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    return (dy / L, -dx / L), L


def facade_bands(kit, poly, z0, z1, mat, off, h0, h1, step, edges=None):
    """Horizontal strips on the outside of each polygon edge, repeating every
    `step` metres: strip from h0 to h1 above each level start."""
    n = len(poly)
    for i in range(n):
        if edges is not None and i not in edges:
            continue
        a, b = poly[i], poly[(i + 1) % n]
        (nx, ny), L = edge_normal(a, b)
        if L < 1.5:
            continue
        ax, ay = a[0] + nx * off, a[1] + ny * off
        bx, by = b[0] + nx * off, b[1] + ny * off
        z = z0
        while z + h1 <= z1 + 1e-6:
            za, zb = z + h0, z + h1
            kit.quad(mat, (ax, ay, za), (bx, by, za), (bx, by, zb), (ax, ay, zb))
            z += step


def facade_piers(kit, poly, z0, z1, mat, off, pitch, width, edges=None):
    """Vertical strips (piers/mullions) every `pitch` metres along each edge."""
    n = len(poly)
    for i in range(n):
        if edges is not None and i not in edges:
            continue
        a, b = poly[i], poly[(i + 1) % n]
        (nx, ny), L = edge_normal(a, b)
        if L < 2 * pitch:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        cnt = int(L / pitch)
        s0 = (L - cnt * pitch) / 2
        for k in range(cnt + 1):
            s = s0 + k * pitch
            s_a, s_b = max(0.0, s - width / 2), min(L, s + width / 2)
            pa = (a[0] + ux * s_a + nx * off, a[1] + uy * s_a + ny * off)
            pb = (a[0] + ux * s_b + nx * off, a[1] + uy * s_b + ny * off)
            kit.quad(mat, (pa[0], pa[1], z0), (pb[0], pb[1], z0), (pb[0], pb[1], z1), (pa[0], pa[1], z1))


def building(kit, poly, h, wall, win="Window_Dark", floor_h=3.4, ground_h=4.6,
             detail=2, pier_pitch=3.2, pier_w=0.9, store=True, street_edges=None,
             roof="Roof_Grey", style="punched"):
    """Generic neighbour: solid massing + facade banding.

    detail 0: plain prism. 1: window bands. 2: bands + piers (punched grid).
    style "glass": body glass, spandrel bands in `win`.
    """
    kit.prism(wall, poly, 0.0, h)
    if h > 40 and detail >= 1:
        # rooftop mechanical bulkhead
        cx, cy = C.centroid(poly)
        s = min(6.0, 0.15 * math.sqrt(abs(_area(poly))))
        kit.box(roof, cx - s, cy - s * 0.7, h, cx + s, cy + s * 0.7, h + 4.0)
    if detail <= 0:
        return
    top = h - 1.2
    if style == "glass":
        facade_bands(kit, poly, ground_h, top, win, 0.03, floor_h - 0.9, floor_h, floor_h)
        if detail >= 2:
            facade_piers(kit, poly, ground_h, top, win, 0.05, pier_pitch * 0.5, 0.12)
    else:
        facade_bands(kit, poly, ground_h, top, win, 0.03, 0.9, floor_h - 0.6, floor_h)
        if detail >= 2:
            facade_piers(kit, poly, ground_h, top, wall, 0.06, pier_pitch, pier_w)
    if store:
        facade_bands(kit, poly, 0.0, ground_h, "Storefront", 0.03, 0.25, ground_h - 0.9,
                     ground_h, edges=street_edges)
    # cornice line
    if detail >= 2 and style != "glass":
        facade_bands(kit, poly, h - 1.0, h, wall, 0.25, 0.0, 0.6, 10.0)


def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
