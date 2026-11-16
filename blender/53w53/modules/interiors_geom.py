"""Geometry helpers for the interiors module (owned by the interiors agent).

MultiMesh: one mesh object holding many boxes/prisms with several material
slots (keeps object count per floor low). Polygon helpers for convex plates,
slabs with rectangular holes, walls with door openings, and a simple
furniture placement planner.
"""
import math
import bpy
import config as C

EPS = 1e-6


# ------------------------------------------------------------------ polygons
def contains(poly, x, y, margin=0.0):
    """Point inside convex CCW polygon (at least `margin` from every edge)."""
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        L = math.hypot(bx - ax, by - ay)
        if L < EPS:
            continue
        if ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / L < margin:
            return False
    return True


def rect_inside(poly, r, margin=0.0):
    x0, y0, x1, y1 = r
    return all(contains(poly, x, y, margin) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def ray_len(poly, p, d):
    """Distance from p (inside convex poly) along unit d to the boundary."""
    t = float("inf")
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        nx, ny = by - ay, -(bx - ax)
        L = math.hypot(nx, ny)
        if L < EPS:
            continue
        nx, ny = nx / L, ny / L
        den = nx * d[0] + ny * d[1]
        if den > EPS:
            tt = (nx * ax + ny * ay - nx * p[0] - ny * p[1]) / den
            t = min(t, tt)
    return t


def clip_rect(poly, x0, y0, x1, y1):
    p = list(poly)
    for nx, ny, d in ((-1, 0, -x0), (1, 0, x1), (0, -1, -y0), (0, 1, y1)):
        p = C._clip(p, nx, ny, d)
        if len(p) < 3:
            return []
    return p


def area(poly):
    a = 0.0
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return a / 2


def rects_overlap(a, b, m=0.0):
    return a[0] < b[2] + m and b[0] < a[2] + m and a[1] < b[3] + m and b[1] < a[3] + m


def poly_minus_rects(poly, holes):
    """Convex pieces covering poly minus axis-aligned rect holes."""
    if not holes:
        return [list(poly)]
    xs0 = min(p[0] for p in poly) - 1
    xs1 = max(p[0] for p in poly) + 1
    ys = sorted(set([min(p[1] for p in poly) - 1, max(p[1] for p in poly) + 1]
                    + [h[1] for h in holes] + [h[3] for h in holes]))
    pieces = []
    for j in range(len(ys) - 1):
        ya, yb = ys[j], ys[j + 1]
        if yb - ya < 1e-4:
            continue
        ym = (ya + yb) / 2
        cuts = sorted((h[0], h[2]) for h in holes if h[1] < ym < h[3])
        x = xs0
        intervals = []
        for hx0, hx1 in cuts:
            if hx0 > x:
                intervals.append((x, hx0))
            x = max(x, hx1)
        intervals.append((x, xs1))
        for a, b in intervals:
            if b - a < 1e-4:
                continue
            pc = clip_rect(poly, a, ya, b, yb)
            if len(pc) >= 3 and abs(area(pc)) > 1e-4:
                pieces.append(pc)
    return pieces


# ------------------------------------------------------------------ mesh
class MultiMesh:
    """Accumulates faces with per-face material; finish() -> one object."""

    def __init__(self):
        self.v, self.f, self.fm = [], [], []
        self.mats, self.mi = [], {}
        self.smooth = set()          # indices of smooth-shaded faces

    def _m(self, name):
        i = self.mi.get(name)
        if i is None:
            i = self.mi[name] = len(self.mats)
            self.mats.append(name)
        return i

    def face(self, mat, pts):
        b = len(self.v)
        self.v += [tuple(p) for p in pts]
        self.f.append(tuple(range(b, b + len(pts))))
        self.fm.append(self._m(mat))

    def prism(self, mat, poly, z0, z1, top=True, bottom=True, sides=True):
        m = self._m(mat)
        b = len(self.v)
        n = len(poly)
        self.v += [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
        if bottom:
            self.f.append(tuple(b + i for i in reversed(range(n))))
            self.fm.append(m)
        if top:
            self.f.append(tuple(b + n + i for i in range(n)))
            self.fm.append(m)
        if sides:
            for i in range(n):
                j = (i + 1) % n
                self.f.append((b + i, b + j, b + n + j, b + n + i))
                self.fm.append(m)

    def box(self, mat, x0, y0, z0, x1, y1, z1, **kw):
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        z0, z1 = min(z0, z1), max(z0, z1)
        if x1 - x0 < 1e-5 or y1 - y0 < 1e-5 or z1 - z0 < 1e-5:
            return
        self.prism(mat, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, **kw)

    def hface(self, mat, poly, z, up=True):
        pts = [(x, y, z) for x, y in poly]
        self.face(mat, pts if up else list(reversed(pts)))

    def beam(self, mat, p0, p1, w, h=None):
        h = h or w
        ax, ay, az = p0
        dx, dy, dz = p1[0] - ax, p1[1] - ay, p1[2] - az
        L = math.sqrt(dx * dx + dy * dy + dz * dz)
        if L < 1e-6:
            return
        dx, dy, dz = dx / L, dy / L, dz / L
        upx, upy, upz = (0, 0, 1) if abs(dz) < 0.95 else (1, 0, 0)
        ux, uy, uz = dy * upz - dz * upy, dz * upx - dx * upz, dx * upy - dy * upx
        ul = math.sqrt(ux * ux + uy * uy + uz * uz)
        ux, uy, uz = ux / ul * w / 2, uy / ul * w / 2, uz / ul * w / 2
        vx, vy, vz = dy * uz - dz * uy, dz * ux - dx * uz, dx * uy - dy * ux
        vl = math.sqrt(vx * vx + vy * vy + vz * vz)
        vx, vy, vz = vx / vl * h / 2, vy / vl * h / 2, vz / vl * h / 2
        cs = [(-ux - vx, -uy - vy, -uz - vz), (ux - vx, uy - vy, uz - vz),
              (ux + vx, uy + vy, uz + vz), (-ux + vx, -uy + vy, -uz + vz)]
        m = self._m(mat)
        b = len(self.v)
        self.v += [(ax + c[0], ay + c[1], az + c[2]) for c in cs]
        self.v += [(p1[0] + c[0], p1[1] + c[1], p1[2] + c[2]) for c in cs]
        self.f += [(b + 3, b + 2, b + 1, b), (b + 4, b + 5, b + 6, b + 7)]
        self.fm += [m, m]
        for i in range(4):
            j = (i + 1) % 4
            self.f.append((b + i, b + j, b + 4 + j, b + 4 + i))
            self.fm.append(m)

    def mesh(self, mat, verts, faces, smooth=False):
        """Append an indexed mesh (shared vertices) with one material."""
        m = self._m(mat)
        b = len(self.v)
        self.v += [tuple(p) for p in verts]
        f0 = len(self.f)
        self.f += [tuple(b + i for i in f) for f in faces]
        self.fm += [m] * len(faces)
        if smooth:
            self.smooth.update(range(f0, len(self.f)))

    def tris(self):
        return sum(len(f) - 2 for f in self.f)

    def finish(self, name, col, floor, collide):
        if not self.f:
            return None
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        for mname in self.mats:
            me.materials.append(C.mat(mname))
        me.polygons.foreach_set("material_index", self.fm)
        if self.smooth:
            flags = [False] * len(self.f)
            for i in self.smooth:
                flags[i] = True
            me.polygons.foreach_set("use_smooth", flags)
        me.validate(clean_customdata=False)
        me.update()
        ob = bpy.data.objects.new(name, me)
        col.objects.link(ob)
        ob["floor"] = int(floor)
        ob["collide"] = bool(collide)
        return ob


# ------------------------------------------------------------------ slabs / walls
def slab(mm, mat, poly, holes, z0, z1):
    """Slab prism with rectangular holes (holes must lie inside poly)."""
    for pc in poly_minus_rects(poly, holes):
        mm.hface(mat, pc, z1, True)
        mm.hface(mat, pc, z0, False)
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        mm.face(mat, [(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)])
    for x0, y0, x1, y1 in holes:   # inward-facing hole walls
        q = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for i in range(4):
            (ax, ay), (bx, by) = q[i], q[(i + 1) % 4]
            mm.face(mat, [(bx, by, z0), (ax, ay, z0), (ax, ay, z1), (bx, by, z1)])


def finish_floor(mm, mat, poly, holes, z):
    for pc in poly_minus_rects(poly, holes):
        mm.hface(mat, pc, z, True)


def wall(mm, mat, p0, p1, z0, z1, th=0.15, openings=(), faces=None):
    """Straight wall p0->p1 centred on the line, with openings
    (s0, s1, top) measured along the wall from p0. Returns solid intervals.
    If `faces` is a list, appends (a, b, normal, z0, z1) hanging segments
    for both faces of every solid piece (used for art)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    if L < 0.05:
        return []
    ux, uy = dx / L, dy / L
    nx, ny = -uy * th / 2, ux * th / 2

    def piece(a, b, za, zb):
        if b - a < 0.01 or zb - za < 0.01:
            return
        ax, ay = p0[0] + ux * a, p0[1] + uy * a
        bx, by = p0[0] + ux * b, p0[1] + uy * b
        poly = [(ax - nx, ay - ny), (bx - nx, by - ny), (bx + nx, by + ny), (ax + nx, ay + ny)]
        if area(poly) < 0:
            poly.reverse()
        mm.prism(mat, poly, za, zb)

    solid = []
    cur = 0.0
    for s0, s1, top in sorted(openings):
        s0, s1 = max(0.0, s0), min(L, s1)
        if s0 > cur:
            piece(cur, s0, z0, z1)
            solid.append((cur, s0))
        piece(s0, s1, top, z1)
        cur = max(cur, s1)
    if cur < L:
        piece(cur, L, z0, z1)
        solid.append((cur, L))
    if faces is not None:
        for a, b in solid:
            for sgn in (1, -1):
                off = sgn * th / 2
                pa = (p0[0] + ux * a - uy * off, p0[1] + uy * a + ux * off)
                pb = (p0[0] + ux * b - uy * off, p0[1] + uy * b + ux * off)
                faces.append((pa, pb, (-uy * sgn, ux * sgn), z0, z1))
    return solid


def wall_rect(p0, p1, th):
    """Axis-aligned obstacle rect for an axis-aligned wall."""
    x0, x1 = min(p0[0], p1[0]), max(p0[0], p1[0])
    y0, y1 = min(p0[1], p1[1]), max(p0[1], p1[1])
    return (x0 - th / 2, y0 - th / 2, x1 + th / 2, y1 + th / 2)


# ------------------------------------------------------------------ planner
class Planner:
    """Places rectangular furniture kits inside a convex plate avoiding
    obstacles (core, walls, door clearances, other furniture)."""

    def __init__(self, inner, rng):
        self.inner = inner
        self.obst = []
        self.rng = rng

    def block(self, r):
        self.obst.append(r)

    def free(self, r, clear=0.0, margin=0.1):
        if not rect_inside(self.inner, r, margin):
            return False
        for o in self.obst:
            if rects_overlap(r, o, clear):
                return False
        return True

    def place(self, kit, room, pref, rot, step=0.3, clear=0.45):
        """Try kit (w, d, parts) at positions inside room rect, nearest to
        pref first. Returns (cx, cy, rot) or None."""
        w, d, _ = kit
        if rot % 2:
            w, d = d, w
        x0, y0, x1, y1 = room
        cands = []
        nx = max(1, int((x1 - x0 - w) / step) + 1)
        ny = max(1, int((y1 - y0 - d) / step) + 1)
        if x1 - x0 < w or y1 - y0 < d:
            return None
        for i in range(nx):
            cx = x0 + w / 2 + i * step
            for j in range(ny):
                cy = y0 + d / 2 + j * step
                cands.append(((cx - pref[0]) ** 2 + (cy - pref[1]) ** 2, cx, cy))
        cands.sort()
        for _, cx, cy in cands:
            r = (cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
            if self.free(r, clear):
                self.obst.append(r)
                return (cx, cy, rot)
        return None


def emit_kit(kit, cx, cy, rot, z, sinks):
    """Write kit parts rotated by rot*90deg about (cx, cy) at floor z.
    sinks: dict category -> MultiMesh."""
    _, _, parts = kit
    for cat, mat, x0, y0, z0, x1, y1, z1 in parts:
        pts = [(x0, y0), (x1, y1)]
        out = []
        for x, y in pts:
            for _ in range(rot % 4):
                x, y = -y, x
            out.append((x, y))
        (ax, ay), (bx, by) = out
        sinks[cat].box(mat, cx + ax, cy + ay, z + z0, cx + bx, cy + by, z + z1)
