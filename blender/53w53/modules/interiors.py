"""Interiors of 53 West 53: slabs, cores, stairs, lifts and fit-out.

Everything lives in collection "Interiors" with one sub-collection per floor
(F01..F77). Each floor's geometry is merged into a few multi-material
objects named F##_<part>:

  F##_slab    structural slab (with stair / lift shaft holes)     collide
  F##_floor   floor finishes (oak, stone, gallery oak, teak)      no
  F##_core    core walls, stair shaft walls                       collide
  F##_stair   stair flights, landings, spine wall                 collide
  F##_rail    handrails                                           no
  F##_lift    lift cars and landing doors                         collide
  F##_walls   partitions                                          collide
  F##_glass_partitions                                            collide
  F##_furniture  big furniture (beds, sofas, tables, counters)    collide
  F##_decor   chairs, rugs, books, plants, small things           no
  F##_art     artworks (gallery floors / lobby)                   no
  F##_lights  ceiling light panels (emissive)                     no
  F06_pool / F06_water                                            yes / no

Every object carries obj["floor"] = n and obj["collide"].
Empties: LIFT_STOP_F## (1 m in front of the lift door, at floor level) and
STAIR_DOOR_F## (0.5 m outside the stair door, at floor level). Floor 60 also
has STAIR_DOOR_F60_LOW, the top door of the full-core stair (transfer).

Stairs: continuous switchback from floor 1 to 77. The full-core stair
(C.STAIR) runs floors 1->60; the compact stair (C.STAIR_SMALL) runs 60->77.
On floor 60 you leave the full stair by its north door, walk ~6 m east
through the transfer lobby and enter the compact stair's north door.
"""
import importlib
import math
import random
import time

import bpy
import config as C
from modules import interiors_geom as G
from modules import interiors_kits as K

importlib.reload(G)
importlib.reload(K)

WALL_T = 0.15
DOOR_H = 2.25
RISER_MAX = 0.18
TREAD_MIN = 0.28

SINKS = {
    # name: collide
    "slab": True, "floor": False, "core": True, "stair": True, "rail": False,
    "lift": True, "walls": True, "glass_partitions": True, "furniture": True,
    "decor": False, "art": False, "lights": False, "pool": True, "water": False,
}

# ---------------------------------------------------------------- stairs
# Each stair: outer rect, wall thickness, spine width, floor landing depth,
# min mid landing depth, door x-range (in the north wall).
FULL_STAIR = dict(rect=C.STAIR, wt=0.25, spine=0.3, fl=1.5, ml=1.3, door=(15.0, 16.2),
                  first=1, last=60)
SMALL_STAIR = dict(rect=C.STAIR_SMALL, wt=0.15, spine=0.2, fl=1.05, ml=1.05, door=(19.3, 20.4),
                   first=None, last=C.NUM_FLOORS)


def _first_small():
    for n in range(1, C.NUM_FLOORS + 1):
        if C.core_is_small(n):
            return n
    return C.NUM_FLOORS + 1


FIRST_SMALL = _first_small()            # 60
FULL_STAIR["last"] = FIRST_SMALL        # full stair arrives on the transfer floor
SMALL_STAIR["first"] = FIRST_SMALL


def stair_inner(s):
    x0, y0, x1, y1 = s["rect"]
    w = s["wt"]
    return (x0 + w, y0 + w, x1 - w, y1 - w)


def stair_storey(s, Fz, h):
    """Geometry numbers for the flights from a floor at Fz up by h."""
    ix0, iy0, ix1, iy1 = stair_inner(s)
    N = int(math.ceil(h / RISER_MAX - 1e-9))
    if N % 2:
        N += 1
    r = h / N
    k = N // 2 - 1                      # treads per flight (between landings)
    fl_y0 = iy1 - s["fl"]
    avail = fl_y0 - (iy0 + s["ml"])
    t = min(0.32, avail / k)
    y_land = fl_y0 - k * t
    fw = (ix1 - ix0 - s["spine"]) / 2
    return dict(N=N, r=r, k=k, t=t, fl_y0=fl_y0, y_land=y_land, fw=fw,
                ix0=ix0, iy0=iy0, ix1=ix1, iy1=iy1)


def build_stair_storey(fc, s, Fz, h):
    g = stair_storey(s, Fz, h)
    st, rail = fc.sink("stair"), fc.sink("rail")
    ix0, ix1, fw, r, t, k = g["ix0"], g["ix1"], g["fw"], g["r"], g["t"], g["k"]
    fl_y0, y_land = g["fl_y0"], g["y_land"]
    xa0, xa1 = ix0, ix0 + fw              # flight A (west): up, heading south
    xb0, xb1 = ix1 - fw, ix1              # flight B (east): up, heading north
    for i in range(1, k + 1):
        top = Fz + i * r
        st.box("Stair_Concrete", xa0, fl_y0 - i * t, top - r - 0.2, xa1, fl_y0 - (i - 1) * t, top)
        st.box("Stair_Nosing", xa0, fl_y0 - i * t, top, xa1, fl_y0 - i * t + 0.04, top + 0.004)
    zm = Fz + h / 2
    st.box("Stair_Concrete", ix0, g["iy0"], zm - 0.25, ix1, y_land, zm)
    for j in range(1, k + 1):
        top = zm + j * r
        st.box("Stair_Concrete", xb0, y_land + (j - 1) * t, top - r - 0.2, xb1, y_land + j * t, top)
        st.box("Stair_Nosing", xb0, y_land + (j - 1) * t, top, xb1, y_land + (j - 1) * t + 0.04, top + 0.004)
    # spine wall between the flights
    st.box("Core_Wall", xa1, y_land, Fz, xb0, fl_y0, Fz + h)
    # handrails (0.9 m above the pitch line), outer wall side and spine side
    for x in (xa0 + 0.06, xa1 - 0.06):
        rail.beam("Metal_Dark", (x, fl_y0, Fz + 0.9), (x, y_land, zm + 0.9), 0.05)
    for x in (xb0 + 0.06, xb1 - 0.06):
        rail.beam("Metal_Dark", (x, y_land, zm + 0.9), (x, fl_y0, Fz + h + 0.9), 0.05)
    # light on the mid landing soffit
    fc.sink("lights").hface("Light_Emit", [(ix0 + 1.0, g["iy0"] + 0.3), (ix1 - 1.0, g["iy0"] + 0.3),
                                           (ix1 - 1.0, g["iy0"] + 0.6), (ix0 + 1.0, g["iy0"] + 0.6)],
                            zm + h / 2 - 0.32, up=False)
    return g


def build_stair_landing(fc, s, Fz):
    ix0, iy0, ix1, iy1 = stair_inner(s)
    fc.sink("stair").box("Stair_Concrete", ix0, iy1 - s["fl"], Fz - 0.3, ix1, iy1, Fz)


# ---------------------------------------------------------------- materials
ART_MATS = {
    "Art_Red": (0.70, 0.10, 0.08, 1), "Art_Blue": (0.10, 0.22, 0.55, 1),
    "Art_Yellow": (0.92, 0.75, 0.15, 1), "Art_Black": (0.05, 0.05, 0.05, 1),
    "Art_Teal": (0.10, 0.45, 0.42, 1), "Art_Orange": (0.88, 0.42, 0.12, 1),
    "Art_Pink": (0.85, 0.55, 0.60, 1), "Art_Ivory": (0.92, 0.88, 0.78, 1),
}
EXTRA_MATS = {
    "Stair_Concrete": (0.60, 0.59, 0.56, 1), "Stair_Nosing": (0.10, 0.10, 0.10, 1),
    "Lift_Steel": (0.62, 0.62, 0.60, 1), "Floor_Gallery": (0.68, 0.56, 0.40, 1),
    "Floor_Rubber": (0.18, 0.18, 0.19, 1), "Pool_Tile": (0.78, 0.88, 0.90, 1),
    "Screen_White": (0.95, 0.95, 0.95, 1), "Frame_White": (0.97, 0.97, 0.96, 1),
    "Bronze": (0.35, 0.22, 0.10, 1),
}


def ensure_materials():
    for name, rgba in list(K.KIT_MATS.items()) + list(ART_MATS.items()) + list(EXTRA_MATS.items()):
        C.mat(name, color=rgba)
    m = bpy.data.materials.get("Glass_Partition")
    if m is None:
        m = C.mat("Glass_Partition", color=(0.75, 0.85, 0.88, 1))
        m.diffuse_color = (0.75, 0.85, 0.88, 0.3)
        b = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
        if b:
            b.inputs["Alpha"].default_value = 0.3
            b.inputs["Roughness"].default_value = 0.05
        for attr, val in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
            if hasattr(m, attr):
                try:
                    setattr(m, attr, val)
                except Exception:
                    pass
    me = bpy.data.materials.get("Stair_Nosing")
    return m, me


# ---------------------------------------------------------------- floor context
class FloorCtx:
    def __init__(self, n, parent):
        self.n = n
        self.Fz = C.floor_z(n)
        self.h = C.floor_height(n)
        self.zc = self.Fz + self.h - C.SLAB_T if n < C.NUM_FLOORS else self.Fz + self.h
        self.col = C.collection("F%02d" % n, parent)
        self.rng = random.Random(n * 7919 + 13)
        self.inner = C.inset(C.plate(n), 0.6)
        self.slab_poly = C.inset(C.section(self.Fz), 0.25)
        self.planner = G.Planner(self.inner, self.rng)
        self.sinks = {}
        self.lights = []
        self.art_faces = []

    def sink(self, name):
        mm = self.sinks.get(name)
        if mm is None:
            mm = self.sinks[name] = G.MultiMesh()
        return mm

    def block(self, r):
        self.planner.block(r)

    def to_edge(self, p, d):
        if not G.contains(self.inner, p[0], p[1], 0.01):
            return None
        L = G.ray_len(self.inner, p, d)
        return (p[0] + d[0] * L, p[1] + d[1] * L)

    def wall(self, p0, p1, openings=(), mat="Wall_White", sink="walls", th=WALL_T, door_h=DOOR_H,
             top=None, art=False, block=True):
        """Axis-aligned or free wall; openings (s0, s1) along the wall from p0."""
        if p0 is None or p1 is None:
            return
        z1 = top if top is not None else self.zc
        ops = [(a, b, self.Fz + door_h) for a, b in openings]
        G.wall(self.sink(sink), mat, p0, p1, self.Fz, z1, th, ops, self.art_faces if art else None)
        if block:
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            self.block(G.wall_rect(p0, p1, th))
            for a, b in openings:
                pa = (p0[0] + ux * a, p0[1] + uy * a)
                pb = (p0[0] + ux * b, p0[1] + uy * b)
                dep = 1.2
                if abs(uy) < 0.5:
                    self.block((min(pa[0], pb[0]) - 0.1, pa[1] - dep, max(pa[0], pb[0]) + 0.1, pa[1] + dep))
                else:
                    self.block((pa[0] - dep, min(pa[1], pb[1]) - 0.1, pa[0] + dep, max(pa[1], pb[1]) + 0.1))

    def kit(self, kit, room, pref, rot=0, clear=0.45, step=0.3):
        res = self.planner.place(kit, room, pref, rot, step, clear)
        if res:
            G.emit_kit(kit, res[0], res[1], res[2], self.Fz,
                       {"furn": self.sink("furniture"), "decor": self.sink("decor")})
        return res

    def light_grid(self, spacing=4.2, size=0.5, holes=(), strip=None, poly=None):
        poly = poly or self.inner
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        hx, hy = (size, size) if strip is None else strip
        lit = self.sink("lights")
        x = min(xs) + spacing / 2
        while x < max(xs):
            y = min(ys) + spacing / 2
            while y < max(ys):
                r = (x - hx / 2, y - hy / 2, x + hx / 2, y + hy / 2)
                if G.rect_inside(poly, r, 0.3) and not any(G.rects_overlap(r, h, 0.3) for h in holes):
                    lit.hface("Light_Emit", [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])],
                              self.zc - 0.01, up=False)
                y += spacing
            x += spacing

    def empty(self, name, loc, **props):
        ob = bpy.data.objects.new(name, None)
        ob.empty_display_type = "SINGLE_ARROW"
        ob.empty_display_size = 0.6
        ob.location = loc
        ob["floor"] = self.n
        for k, v in props.items():
            ob[k] = v
        self.col.objects.link(ob)
        return ob

    def point_light(self, name, loc, energy=80.0, kind="POINT", size=0.3, color=(1.0, 0.9, 0.78)):
        ld = bpy.data.lights.new(name, kind)
        ld.energy = energy
        ld.color = color
        if kind == "AREA":
            ld.size = size
        elif hasattr(ld, "shadow_soft_size"):
            ld.shadow_soft_size = size
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob["floor"] = self.n
        ob["collide"] = False
        self.col.objects.link(ob)
        self.lights.append(ob)
        return ob

    def finish(self):
        objs = []
        for name, mm in self.sinks.items():
            ob = mm.finish("F%02d_%s" % (self.n, name), self.col, self.n, SINKS.get(name, False))
            if ob:
                objs.append(ob)
        return objs

    def tris(self):
        return sum(mm.tris() for mm in self.sinks.values())


# ---------------------------------------------------------------- core / lifts
def lift_car(fc, x0, y0, x1, y1, door_y_side="north"):
    """Open lift car standing at floor level in a shaft (doors open)."""
    L = fc.sink("lift")
    Fz = fc.Fz
    L.box("Lift_Steel", x0, y0, Fz - 0.25, x1, y1 + 0.1, Fz)         # car floor + sill (walkable)
    L.box("Floor_Stone", x0 + 0.05, y0 + 0.05, Fz, x1 - 0.05, y1 - 0.05, Fz + 0.01, sides=False, bottom=False)
    L.box("Wood_Walnut", x0, y0, Fz, x1, y0 + 0.05, Fz + 2.6)        # back
    L.box("Lift_Steel", x0, y0, Fz, x0 + 0.05, y1, Fz + 2.6)
    L.box("Lift_Steel", x1 - 0.05, y0, Fz, x1, y1, Fz + 2.6)
    L.box("Lift_Steel", x0, y0, Fz + 2.6, x1, y1, Fz + 2.7)          # roof
    fc.sink("lights").hface("Light_Emit", [(x0 + 0.4, y0 + 0.4), (x1 - 0.4, y0 + 0.4),
                                           (x1 - 0.4, y1 - 0.4), (x0 + 0.4, y1 - 0.4)], Fz + 2.59, up=False)
    fc.sink("rail").beam("Metal_Dark", (x0 + 0.2, y0 + 0.1, Fz + 0.9), (x1 - 0.2, y0 + 0.1, Fz + 0.9), 0.04)


def landing_door(fc, xc, y_face, w, outward):
    """Closed lift landing door leaves in an opening (y_face = outer face)."""
    L = fc.sink("lift")
    y = y_face - 0.12 if outward > 0 else y_face + 0.06
    L.box("Lift_Steel", xc - w / 2, y, fc.Fz, xc + w / 2, y + 0.06, fc.Fz + 2.3)
    L.box("Metal_Dark", xc - 0.005, y - 0.002, fc.Fz, xc + 0.005, y + 0.062, fc.Fz + 2.3)


def call_button(fc, x, y_face):
    fc.sink("decor").box("Light_Emit", x - 0.05, y_face, fc.Fz + 1.05, x + 0.05, y_face + 0.03, fc.Fz + 1.25)


def build_full_core(fc, with_lifts=True):
    """Full core (C.CORE): stair west, 3 lifts east with doors facing north."""
    n, Fz = fc.n, fc.Fz
    z1 = fc.zc
    x0, y0, x1, y1 = C.CORE
    w = FULL_STAIR["wt"]
    core = fc.sink("core")
    m = "Core_Wall"
    if not with_lifts:                        # transfer floor: stair enclosure only
        x0, y0, x1, y1 = C.STAIR
    # outer walls
    core.box(m, x0, y0, Fz, x1, y0 + w, z1)                      # south
    core.box(m, x0, y0 + w, Fz, x0 + w, y1 - w, z1)              # west
    core.box(m, x1 - w, y0 + w, Fz, x1, y1 - w, z1)              # east
    d0, d1 = FULL_STAIR["door"]
    ops = [(d0 - x0, d1 - x0, Fz + DOOR_H)]
    shafts = []
    if with_lifts:
        sx = [(19.25, 21.85), (22.15, 24.85), (25.15, 27.75)]
        for a, b in sx:
            c = (a + b) / 2
            shafts.append((a, b, c))
            ops.append((c - 0.6 - x0, c + 0.6 - x0, Fz + 2.3))
    G.wall(core, m, (x0, y1 - w / 2), (x1, y1 - w / 2), Fz, z1, w, ops)
    # door frame (stair) + exit sign
    fc.sink("decor").box("Metal_Dark", d0 - 0.05, y1 - 0.02, Fz, d0, y1 + 0.03, Fz + DOOR_H)
    fc.sink("decor").box("Metal_Dark", d1, y1 - 0.02, Fz, d1 + 0.05, y1 + 0.03, Fz + DOOR_H)
    fc.sink("decor").box("Art_Red", (d0 + d1) / 2 - 0.2, y1, Fz + DOOR_H + 0.1,
                         (d0 + d1) / 2 + 0.2, y1 + 0.04, Fz + DOOR_H + 0.3)
    fc.block((x0 - 0.1, y0 - 0.1, x1 + 0.1, y1 + 0.1))
    fc.block((d0 - 0.3, y1, d1 + 0.3, y1 + 1.6))
    if with_lifts:
        core.box(m, 18.75, 9.25, Fz, 19.25, 18.75, z1)             # stair / lift wall
        core.box(m, 19.25, 15.25, Fz, 27.75, 15.5, z1)             # shaft back wall
        core.box(m, 21.85, 15.5, Fz, 22.15, 18.75, z1)
        core.box(m, 24.85, 15.5, Fz, 25.15, 18.75, z1)
        for i, (a, b, c) in enumerate(shafts):
            if i == 1:
                lift_car(fc, a + 0.05, 15.55, b - 0.05, 18.70)
            else:
                landing_door(fc, c, y1, 1.2, +1)
            call_button(fc, c + 0.85, y1)
        fc.block((19.0, y1, 28.0, y1 + 1.8))
        fc.empty("LIFT_STOP_F%02d" % n, (23.5, y1 + 1.0, Fz), kind="lift", core="full")
    name = "STAIR_DOOR_F%02d" % n if with_lifts else "STAIR_DOOR_F%02d_LOW" % n
    fc.empty(name, ((d0 + d1) / 2, y1 + 0.5, Fz), kind="stair", core="full",
             door_x0=d0, door_x1=d1, door_y=y1, door_h=DOOR_H)


def build_small_core(fc):
    n, Fz, z1 = fc.n, fc.Fz, fc.zc
    x0, y0, x1, y1 = C.CORE_SMALL
    w = SMALL_STAIR["wt"]
    core = fc.sink("core")
    m = "Core_Wall"
    core.box(m, x0, y0, Fz, x1, y0 + w, z1)
    core.box(m, x0, y0 + w, Fz, x0 + w, y1 - w, z1)
    core.box(m, x1 - w, y0 + w, Fz, x1, y1 - w, z1)
    sx0, _, sx1, _ = C.STAIR_SMALL
    core.box(m, sx1 - w, y0 + w, Fz, sx1 + w, y1 - w, z1)          # stair / lift wall
    d0, d1 = SMALL_STAIR["door"]
    lc = (C.ELEVATOR_SMALL[0] + C.ELEVATOR_SMALL[2]) / 2
    ops = [(d0 - x0, d1 - x0, Fz + DOOR_H), (lc - 0.55 - x0, lc + 0.55 - x0, Fz + 2.3)]
    G.wall(core, m, (x0, y1 - w / 2), (x1, y1 - w / 2), Fz, z1, w, ops)
    if n == C.NUM_FLOORS:                                            # cap over the core
        core.box(m, x0, y0, z1, x1, y1, z1 + 0.3)
    fc.sink("decor").box("Art_Red", (d0 + d1) / 2 - 0.2, y1, Fz + DOOR_H + 0.1,
                         (d0 + d1) / 2 + 0.2, y1 + 0.04, Fz + DOOR_H + 0.3)
    lift_car(fc, sx1 + w + 0.05, y0 + w + 0.05, x1 - w - 0.05, y1 - w - 0.05)
    call_button(fc, lc + 0.8, y1)
    fc.block((x0 - 0.1, y0 - 0.1, x1 + 0.1, y1 + 0.1))
    fc.block((x0 - 0.2, y1, x1 + 0.4, y1 + 1.8))
    fc.empty("LIFT_STOP_F%02d" % n, (lc, y1 + 1.0, Fz), kind="lift", core="compact")
    fc.empty("STAIR_DOOR_F%02d" % n, ((d0 + d1) / 2, y1 + 0.5, Fz), kind="stair", core="compact",
             door_x0=d0, door_x1=d1, door_y=y1, door_h=DOOR_H)


def slab_holes(n):
    holes = []
    if 2 <= n <= FULL_STAIR["last"]:
        holes.append(stair_inner(FULL_STAIR))
    if 2 <= n < FIRST_SMALL:
        holes.append((19.25, 15.5, 27.75, 18.75))
    if n > FIRST_SMALL:
        holes.append(stair_inner(SMALL_STAIR))
        w = SMALL_STAIR["wt"]
        ex0, ey0, ex1, ey1 = C.ELEVATOR_SMALL
        holes.append((ex0 + w, ey0 + w, ex1 - w, ey1 - w))
    return holes


def build_structure(fc):
    n = fc.n
    holes = slab_holes(n)
    extra = getattr(fc, "extra_holes", [])
    G.slab(fc.sink("slab"), "Slab_Concrete", fc.slab_poly, holes + extra, fc.Fz - C.SLAB_T, fc.Fz)
    small = C.core_is_small(n)
    if not small:
        build_full_core(fc, True)
    else:
        if n == FIRST_SMALL:
            build_full_core(fc, with_lifts=False)
        build_small_core(fc)
    # stairs
    if FULL_STAIR["first"] <= n <= FULL_STAIR["last"]:
        if n > 1:
            build_stair_landing(fc, FULL_STAIR, fc.Fz)
        if n < FULL_STAIR["last"]:
            build_stair_storey(fc, FULL_STAIR, fc.Fz, fc.h)
    if SMALL_STAIR["first"] <= n <= SMALL_STAIR["last"]:
        if n > SMALL_STAIR["first"]:
            build_stair_landing(fc, SMALL_STAIR, fc.Fz)
        if n < SMALL_STAIR["last"]:
            build_stair_storey(fc, SMALL_STAIR, fc.Fz, fc.h)


def core_holes(n):
    hs = [C.core_rect(n)]
    if n == FIRST_SMALL:
        hs.append(C.STAIR)
    return hs


# ---------------------------------------------------------------- art
ART_KEYS = list(ART_MATS)


def hang_art(fc, faces, rng, zc=1.65, min_len=2.0, big=False):
    art = fc.sink("art")
    for (a, b, nrm, z0, z1) in faces:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < min_len:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        s = 0.7
        while True:
            w = rng.uniform(1.0, 2.6 if big else 1.8)
            if s + w > L - 0.7:
                break
            hgt = rng.uniform(0.8, min(2.2, w * 1.3))
            m0, m1 = s, s + w
            zc_ = fc.Fz + zc + (0.25 if hgt > 1.6 else 0.0)
            za, zb = zc_ - hgt / 2, zc_ + hgt / 2
            frame = rng.choice(["Metal_Dark", "Frame_White", "Wood_Walnut"])
            col = rng.choice(ART_KEYS)
            for (d0, d1, mat, inset) in ((0.0, 0.05, frame, 0.0), (0.05, 0.065, col, 0.06)):
                p = [(a[0] + ux * (m0 + inset) + nrm[0] * d0, a[1] + uy * (m0 + inset) + nrm[1] * d0),
                     (a[0] + ux * (m1 - inset) + nrm[0] * d0, a[1] + uy * (m1 - inset) + nrm[1] * d0),
                     (a[0] + ux * (m1 - inset) + nrm[0] * d1, a[1] + uy * (m1 - inset) + nrm[1] * d1),
                     (a[0] + ux * (m0 + inset) + nrm[0] * d1, a[1] + uy * (m0 + inset) + nrm[1] * d1)]
                if G.area(p) < 0:
                    p.reverse()
                art.prism(mat, p, za + inset, zb - inset)
            # second colour block for some paintings
            if rng.random() < 0.5:
                col2 = rng.choice(ART_KEYS)
                f0, f1 = m0 + w * 0.2, m0 + w * rng.uniform(0.45, 0.8)
                p = [(a[0] + ux * f0 + nrm[0] * 0.065, a[1] + uy * f0 + nrm[1] * 0.065),
                     (a[0] + ux * f1 + nrm[0] * 0.065, a[1] + uy * f1 + nrm[1] * 0.065),
                     (a[0] + ux * f1 + nrm[0] * 0.075, a[1] + uy * f1 + nrm[1] * 0.075),
                     (a[0] + ux * f0 + nrm[0] * 0.075, a[1] + uy * f0 + nrm[1] * 0.075)]
                if G.area(p) < 0:
                    p.reverse()
                art.prism(col2, p, za + hgt * 0.25, zb - hgt * 0.3)
            s += w + rng.uniform(1.2, 2.2)


def core_faces(fc):
    """Hangable outer faces of the full core (south, west, east)."""
    x0, y0, x1, y1 = C.CORE
    z0, z1 = fc.Fz, fc.zc
    return [((x1, y0), (x0, y0), (0, -1), z0, z1),
            ((x0, y0), (x0, y1), (-1, 0), z0, z1),
            ((x1, y1), (x1, y0), (1, 0), z0, z1)]


# ---------------------------------------------------------------- floor types
def finish_default(fc, mat, extra_stone=()):
    holes = core_holes(fc.n) + list(extra_stone)
    G.finish_floor(fc.sink("floor"), mat, fc.slab_poly, holes, fc.Fz + 0.005)
    for r in extra_stone:
        pc = G.clip_rect(fc.slab_poly, *r)
        if pc:
            G.finish_floor(fc.sink("floor"), "Floor_Stone", pc, [], fc.Fz + 0.005)


def lobby_f01(fc):
    Fz, zc = fc.Fz, fc.zc
    finish_default(fc, "Floor_Stone")
    fl = fc.sink("floor")
    # entrance threshold bridging the facade line to the slab
    fl.box("Floor_Stone", 19.4, -0.1, Fz - 0.3, 22.6, 0.3, Fz + 0.005)
    fl.box("Metal_Dark", 19.6, 0.4, Fz + 0.005, 22.4, 2.2, Fz + 0.012, sides=True)   # entry mat
    # keep the route clear: entrance -> around the core -> lift lobby
    for r in ((18.0, 0.0, 24.0, 8.8), (10.5, 6.5, 14.0, 24.0), (28.0, 6.5, 31.5, 24.0),
              (13.0, 18.8, 29.0, 24.0)):
        fc.block(r)
    # walnut cladding on core (south / west / east faces) and north frieze
    d = fc.sink("decor")
    x0, y0, x1, y1 = C.CORE
    w = fc.sink("walls")
    w.box("Wood_Walnut", x0 - 0.06, y0 - 0.06, Fz, x1 + 0.06, y0, zc)
    w.box("Wood_Walnut", x0 - 0.06, y0, Fz, x0, y1, zc)
    w.box("Wood_Walnut", x1, y0, Fz, x1 + 0.06, y1, zc)
    w.box("Wood_Walnut", x0, y1, Fz + 2.7, x1, y1 + 0.06, zc)
    # big artwork facing the entrance (on the core's south face)
    hang_art(fc, [((26.5, y0 - 0.06), (15.5, y0 - 0.06), (0, -1), Fz, zc)], random.Random(53), zc=3.3, big=True)
    # reception desk (east of the entry route)
    f = fc.sink("furniture")
    f.box("Wood_Walnut", 32.0, 5.0, Fz, 36.5, 5.9, Fz + 1.05)
    f.box("Marble_White", 31.9, 4.9, Fz + 1.05, 36.6, 6.0, Fz + 1.1)
    f.box("Wood_Walnut", 32.0, 7.6, Fz, 36.5, 8.0, Fz + 2.6)
    d.box("Metal_Dark", 33.0, 5.3, Fz + 1.1, 33.5, 5.35, Fz + 1.45)
    d.box("Leather_Tan", 33.8, 6.4, Fz, 34.3, 6.9, Fz + 0.5)
    fc.block((31.5, 4.5, 37.0, 8.5))
    # seating groups west, plants, benches
    fc.kit(K.living_set(2.6), (-3, 1, 10.4, 9.5), (5, 5.5), rot=1)
    fc.kit(K.living_set(2.4), (-3, 9.5, 10.4, 24), (4.5, 15.5), rot=1)
    fc.kit(K.bench(3.0), (24.5, 1, 31.0, 8.5), (27.5, 3.0), rot=0, clear=0.3)
    for p in ((17.5, 1.2), (24.6, 1.2), (2.0, 21.0), (40.0, 18.0), (30.5, 23.0), (11.0, 23.5)):
        fc.kit(K.plant(), (p[0] - 1, p[1] - 1, p[0] + 1, p[1] + 1), p, clear=0.1)
    fc.kit(K.living_set(2.4), (32, 9, 46, 23), (38, 15), rot=3)
    # mailroom/package room enclosure (north-east)
    fc.wall((31.5, 24.0), (36.0, 24.0), openings=[(1.0, 2.2)], mat="Wood_Walnut")
    e = fc.to_edge((36.0, 24.0), (0.0, 1.0))
    fc.wall((36.0, 24.0), e, mat="Wood_Walnut")
    e2 = fc.to_edge((31.5, 24.0), (0.0, 1.0))
    fc.wall((31.5, 24.0), e2, mat="Wood_Walnut")
    # lights: emissive ceiling panels + a few real lights
    fc.light_grid(spacing=5.0, size=0.9, holes=[C.CORE])
    for i, (x, y) in enumerate(((7, 6), (21, 4.5), (35, 9), (21, 21.5), (6, 17), (38, 18))):
        fc.point_light("Lobby_Area_%d" % i, (x, y, zc - 0.2), energy=500.0, kind="AREA", size=3.0)
    fc.point_light("Lobby_Point_Desk", (34.2, 6.5, Fz + 3.0), energy=150.0)
    fc.point_light("Lobby_Point_Entry", (21.0, 2.0, Fz + 3.5), energy=200.0)


def gallery(fc):
    """MoMA gallery floors 2, 4, 5."""
    n, Fz, zc = fc.n, fc.Fz, fc.zc
    rng = fc.rng
    finish_default(fc, "Floor_Gallery")
    fc.block((13.0, 18.8, 29.0, 23.0))                      # lift lobby
    T = 0.25
    gm = "Gallery_Wall"
    var = {2: (0.0, 0.0), 4: (1.0, -1.5), 5: (-1.0, 1.5)}[n] if n in (2, 4, 5) else (0.0, 0.0)
    xw, xe = 12.0 + var[0] * 0.5, 30.0 - var[0] * 0.5
    ys = fc.to_edge((xw, 9.0), (0, -1))
    if ys:
        L = 24.0 - ys[1]
        a = 3.0 - ys[1] + var[1]
        fc.wall(ys, (xw, 24.0), openings=[(a, a + 2.6), (14.0 - ys[1], 16.8 - ys[1])], mat=gm, th=T,
                door_h=3.6, art=True)
    ye = fc.to_edge((xe, 9.0), (0, -1))
    if ye:
        a = 5.0 - ye[1] - var[1]
        fc.wall(ye, (xe, 24.0), openings=[(a, a + 2.6), (13.0 - ye[1], 15.8 - ye[1])], mat=gm, th=T,
                door_h=3.6, art=True)
    fc.wall((xw, 24.0), (xe, 24.0), openings=[(7.5 - var[0], 11.5 - var[0])], mat=gm, th=T, door_h=3.6, art=True)
    # free-standing display walls
    free = {2: [((5.0, 8.0), (5.0, 16.0)), ((37.0, 6.0), (37.0, 13.0)), ((17.0, 27.0), (25.0, 27.0))],
            4: [((6.0, 5.0), (6.0, 13.5)), ((35.5, 9.5), (40.5, 9.5)), ((14.0, 4.5), (20.0, 4.5))],
            5: [((3.0, 11.0), (9.0, 11.0)), ((37.0, 4.0), (37.0, 12.0)), ((22.0, 4.5), (28.0, 4.5))]}
    for p0, p1 in free.get(n, free[2]):
        if G.contains(fc.inner, *p0, 0.8) and G.contains(fc.inner, *p1, 0.8):
            fc.wall(p0, p1, mat=gm, th=0.3, top=Fz + 4.2, art=True)
    faces = list(fc.art_faces) + core_faces(fc)
    hang_art(fc, faces, rng)
    # benches and plinths with sculptures
    rooms = [(-3, 1, xw, 24), (xw, 0.6, xe, 9), (xe, 0.6, 46, 24), (-3, 24, 46, 30)]
    for r in rooms:
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        fc.kit(K.bench(2.4), r, (cx, cy), rot=0 if (r[2] - r[0]) > (r[3] - r[1]) else 1, clear=1.0)
    for i in range(3):
        r = rooms[rng.randrange(len(rooms))]
        px, py = rng.uniform(r[0], r[2]), rng.uniform(r[1], r[3])
        res = fc.planner.place((0.8, 0.8, []), r, (px, py), 0, 0.4, 1.0)
        if res:
            x, y, _ = res
            fc.sink("furniture").box("Gallery_Wall", x - 0.4, y - 0.4, Fz, x + 0.4, y + 0.4, Fz + 0.9)
            hgt = rng.uniform(0.6, 1.4)
            fc.sink("decor").box(rng.choice(["Bronze", "Art_Black", "Art_Red", "Metal_Dark"]),
                                 x - 0.22, y - 0.18, Fz + 0.9, x + 0.22, y + 0.18, Fz + 0.9 + hgt)
    # east connection doorway towards MoMA (x ~ 46)
    yc0, yc1 = 10.3, 13.7
    pa = fc.to_edge((38.0, yc0), (1, 0))
    pb = fc.to_edge((38.0, yc1), (1, 0))
    if pa and pb:
        dep = 2.6
        fc.wall((pa[0] - dep, yc0), pa, mat=gm, th=0.3, top=Fz + 4.4)
        fc.wall((pb[0] - dep, yc1), pb, mat=gm, th=0.3, top=Fz + 4.4)
        xm = min(pa[0], pb[0]) - dep
        w = fc.sink("walls")
        w.box(gm, xm, yc0 - 0.15, Fz + 3.6, max(pa[0], pb[0]), yc1 + 0.15, Fz + 4.4)
        fc.sink("decor").box("Art_Black", xm - 0.02, yc0 + 0.4, Fz + 3.75, xm, yc1 - 0.4, Fz + 4.25)
        fc.sink("floor").box("Metal_Dark", xm, yc0 + 0.15, Fz, max(pa[0], pb[0]), yc1 - 0.15, Fz + 0.012)
        fc.block((xm - 1.5, yc0, max(pa[0], pb[0]), yc1))
        fc.empty("MOMA_LINK_F%02d" % n, (xm + 1.0, (yc0 + yc1) / 2, Fz), kind="moma_link")
    fc.light_grid(spacing=3.6, strip=(2.0, 0.2), holes=[C.CORE])


def fitness_f03(fc):
    Fz = fc.Fz
    finish_default(fc, "Floor_Rubber", extra_stone=[(14.0, 19.0, 28.0, 23.0)])
    fc.block((13.0, 18.8, 29.0, 23.2))
    # changing rooms east
    p = fc.to_edge((33.0, 19.0), (0, -1))
    fc.wall(p, (33.0, 19.0), openings=[(4.0 - p[1], 5.2 - p[1]), (15.0 - p[1], 16.2 - p[1])])
    fc.wall((33.0, 19.0), fc.to_edge((33.0, 19.0), (1, 0)))
    fc.wall((33.0, 10.0), fc.to_edge((33.0, 10.0), (1, 0)))
    for r, pref in (((33, 0.6, 46, 10), (38, 2)), ((33, 10, 46, 19), (39, 18))):
        fc.kit(K.wardrobe(3.0), r, pref, rot=0, clear=0.2)
        fc.kit(K.bench(2.4), r, (pref[0], (r[1] + r[3]) / 2), rot=0, clear=0.6)
    # yoga studio behind glass (north)
    fc.wall((12.0, 24.0), (30.0, 24.0), openings=[(8.0, 9.2)], mat="Glass_Partition", sink="glass_partitions",
            th=0.06)
    fc.kit(K.mat_row(5), (12, 24.2, 30, 30), (17, 26.5), rot=0, clear=0.3)
    fc.kit(K.mat_row(5), (12, 24.2, 30, 30), (25, 26.5), rot=0, clear=0.3)
    # mirror wall on core west face
    fc.sink("decor").box("Glass_Curtain", 13.94, 9.5, Fz + 0.2, 14.0, 18.5, Fz + 2.6)
    # gym west
    for i in range(5):
        fc.kit(K.treadmill(), (-3, 3, 9, 24), (1.5, 6 + i * 2.6), rot=1, clear=0.35, step=0.2)
    for i in range(3):
        fc.kit(K.weight_bench(), (3, 4, 12, 22), (8.5, 7 + i * 4.5), rot=1, clear=0.6)
    # spa loungers south
    for i in range(6):
        fc.kit(K.lounger(), (12, 0.6, 33, 8.6), (14 + i * 3.0, 4.5), rot=0, clear=0.4, step=0.2)
    fc.kit(K.plant(), (30, 19, 46, 30), (34, 22))
    fc.light_grid(spacing=4.0, size=0.6, holes=[C.CORE])


def pool_f06(fc):
    Fz = fc.Fz
    P = (8.0, 2.4, 28.0, 6.4)                    # 20 m x 4 m lap pool
    deck = (6.0, 0.6, 30.0, 8.6)
    holes = core_holes(fc.n) + [deck]
    fl = fc.sink("floor")
    G.finish_floor(fl, "Floor_Stone", fc.slab_poly, holes, Fz + 0.005)
    dpoly = G.clip_rect(fc.slab_poly, *deck)
    G.finish_floor(fl, "Wood_Teak", dpoly, [P], Fz + 0.005)
    # basin (below the slab, tiled), with entry steps at the west end
    pl = fc.sink("pool")
    t, zb = 0.25, Fz - 1.4
    zf = Fz - 1.2
    x0, y0, x1, y1 = P
    pl.box("Pool_Tile", x0 - t, y0 - t, zb, x1 + t, y0, Fz)
    pl.box("Pool_Tile", x0 - t, y1, zb, x1 + t, y1 + t, Fz)
    pl.box("Pool_Tile", x0 - t, y0, zb, x0, y1, Fz)
    pl.box("Pool_Tile", x1, y0, zb, x1 + t, y1, Fz)
    pl.box("Pool_Tile", x0, y0, zb, x1, y1, zf)
    nst = 7
    r = 1.2 / nst
    for i in range(1, nst):
        pl.box("Pool_Tile", x0, y0, zf, x0 + i * 0.3, y0 + 1.3, Fz - i * r)
    for yy in (3.4, 4.4, 5.4):
        fc.sink("decor").box("Art_Blue", x0 + 2.2, yy - 0.08, zf, x1 - 0.5, yy + 0.08, zf + 0.004)
    for e in ((x0 - t - 0.05, y0 - t - 0.05, x1 + t + 0.05, y0 - t + 0.25),
              (x0 - t - 0.05, y1 + t - 0.25, x1 + t + 0.05, y1 + t + 0.05)):
        fc.sink("decor").box("Marble_White", e[0], e[1], Fz, e[2], e[3], Fz + 0.02)
    fc.sink("water").hface("Water_Pool", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], Fz - 0.12)
    fc.sink("rail").beam("Metal_Dark", (x1 - 0.3, y1 - 0.2, Fz + 0.8), (x1 - 0.3, y1 - 0.2, Fz - 1.0), 0.05)
    fc.block((x0 - 0.6, y0 - 0.6, x1 + 0.6, y1 + 0.6))
    fc.block((13.0, 18.8, 29.0, 23.2))
    for i in range(6):
        fc.kit(K.lounger(), (6.0, 7.0, 30.0, 8.6), (9.0 + i * 3.3, 7.8), rot=1, clear=0.25, step=0.2)
    # hot tub (raised) east of the pool
    ht = (33.0, 2.5, 36.0, 5.5)
    pl.box("Pool_Tile", *ht[:2], Fz, *ht[2:], Fz + 0.55)
    fc.sink("water").hface("Water_Pool", [(ht[0] + 0.15, ht[1] + 0.15), (ht[2] - 0.15, ht[1] + 0.15),
                                          (ht[2] - 0.15, ht[3] - 0.15), (ht[0] + 0.15, ht[3] - 0.15)], Fz + 0.56)
    fc.block(ht)
    # sauna (teak box) north-west
    sa = (1.5, 12.5, 7.0, 17.5)
    fc.wall((sa[0], sa[1]), (sa[2], sa[1]), mat="Wood_Teak")
    fc.wall((sa[0], sa[3]), (sa[2], sa[3]), mat="Wood_Teak")
    fc.wall((sa[0], sa[1]), (sa[0], sa[3]), mat="Wood_Teak")
    fc.wall((sa[2], sa[1]), (sa[2], sa[3]), openings=[(1.5, 2.5)], mat="Wood_Teak")
    fc.sink("furniture").box("Wood_Teak", sa[0] + 0.1, sa[1] + 0.1, Fz, sa[0] + 0.7, sa[3] - 0.1, Fz + 0.45)
    fc.block((sa[0] - 0.3, sa[1] - 0.3, sa[2] + 0.3, sa[3] + 0.3))
    for pref in ((36, 15), (36, 22), (6, 22)):
        fc.kit(K.armchair_pair(), (-3, 9, 46, 30), pref, rot=0)
    for pref in ((31, 1.5), (5, 2), (40, 20), (12, 26)):
        fc.kit(K.plant(), (pref[0] - 2, pref[1] - 2, pref[0] + 2, pref[1] + 2), pref, clear=0.2)
    fc.light_grid(spacing=4.0, size=0.6, holes=[C.CORE])


def amenity_f07(fc):
    Fz = fc.Fz
    finish_default(fc, "Floor_Oak", extra_stone=[(14.0, 19.0, 28.0, 22.5)])
    fc.block((13.0, 18.8, 29.0, 22.8))
    # screening room (east)
    fc.wall((31.0, 8.0), (31.0, 18.0), openings=[(8.0, 9.1)])
    fc.wall((31.0, 8.0), fc.to_edge((31.0, 8.0), (1, 0)))
    fc.wall((31.0, 18.0), fc.to_edge((31.0, 18.0), (1, 0)))
    fc.sink("decor").box("Screen_White", 33.5, 8.08, Fz + 0.8, 41.5, 8.12, Fz + 3.0)
    fc.block((31.0, 8.0, 46.0, 9.6))
    fc.kit(K.screening_rows(7.0, 3), (31.2, 9.6, 46, 18), (37.5, 13.6), rot=2, clear=0.2)
    # library (west)
    fc.wall((11.0, 8.0), (11.0, 20.0), openings=[(10.0, 11.1)])
    fc.wall((11.0, 8.0), fc.to_edge((11.0, 8.0), (-1, 0)))
    fc.wall((11.0, 20.0), fc.to_edge((11.0, 20.0), (-1, 0)))
    for pref, rot in (((4.0, 8.35), 0), ((8.0, 8.35), 0), ((4.0, 19.65), 2), ((8.0, 19.65), 2)):
        fc.kit(K.bookshelf(3.0, 2.6), (-3, 8.05, 11, 19.95), pref, rot=rot, clear=0.0, step=0.1)
    fc.kit(K.armchair_pair(), (-3, 9, 11, 19), (5, 12), rot=0, clear=0.3)
    fc.kit(K.armchair_pair(), (-3, 9, 11, 19), (5, 16), rot=2, clear=0.3)
    # dining + bar (north)
    fc.kit(K.dining(5), (-3, 22.8, 46, 30), (16.5, 25.8), rot=0)
    fc.kit(K.dining(4), (-3, 22.8, 46, 30), (25.5, 25.8), rot=0)
    fc.kit(K.bar_counter(4.8), (29, 19, 46, 30), (36.0, 22.5), rot=0, clear=0.3)
    # lounge (south)
    fc.kit(K.living_set(2.6), (-3, 0.6, 46, 8.6), (6.0, 4.5), rot=0)
    fc.kit(K.living_set(2.6), (-3, 0.6, 46, 8.6), (21.0, 4.5), rot=0)
    fc.kit(K.piano(), (-3, 0.6, 46, 8.6), (33.0, 4.5), rot=0)
    for pref in ((12, 1.5), (29, 1.5), (2, 22), (41, 26)):
        fc.kit(K.plant(), (pref[0] - 2, pref[1] - 2, pref[0] + 2, pref[1] + 2), pref, clear=0.2)
    fc.light_grid(spacing=4.0, size=0.6, holes=[C.CORE])


def bath(fc, x0, y0, x1, y1, door_side, mirror=False):
    """Small bathroom enclosure against the core; door in the wall at x=door_side."""
    Fz = fc.Fz
    xo = x0 if not mirror else x1          # free (non-core) side
    fc.wall((xo, y0), (xo, y1), openings=[(0.45, 1.35)])
    fc.wall((x0, y0), (x1, y0))
    fc.wall((x0, y1), (x1, y1))
    f, d = fc.sink("furniture"), fc.sink("decor")
    xc = x1 - 0.1 if not mirror else x0 + 0.1      # core side
    sgn = -1 if not mirror else 1
    f.box("Marble_White", xc, y1 - 0.85, Fz, xc + sgn * 1.8, y1 - 0.1, Fz + 0.55)      # tub
    f.box("Marble_White", xc, y0 + 0.1, Fz, xc + sgn * 0.55, y0 + 1.3, Fz + 0.85)      # vanity
    d.box("Glass_Curtain", xc - sgn * 0.04, y0 + 0.15, Fz + 1.1, xc, y0 + 1.25, Fz + 2.0)  # mirror
    d.box("Marble_White", xc, y0 + 1.6, Fz, xc + sgn * 0.65, y0 + 2.0, Fz + 0.42)      # wc
    fc.block((min(x0, x1) - 0.1, y0 - 0.1, max(x0, x1) + 0.1, y1 + 0.1))


def apt_rooms(fc, side, region_north):
    """Furnish a wrap-around apartment on the west (side=-1) or east (+1)."""
    rng = fc.rng
    if side < 0:
        kit_room, kit_pref, kit_rot = (5.0, 11.6, 14.0, 15.43), (12.45, 13.5), 1
        living = (-3, 11.6, 11.3, 30)
        liv_pref = (3.0, 16.0 + rng.uniform(-1, 2))
        din_pref = (5.0 + rng.uniform(-1, 1), 22.0)
        bed1 = (-3, -1, 7.5, 11.43)
        bed1_pref = (3.5, 10.3)
        bed2 = (7.5, -1, 21.0, 9.0)
        bed2_pref = (14.0 + rng.uniform(-2, 2), 7.9)
        liv_rot = 1
    else:
        kit_room, kit_pref, kit_rot = (28.0, 11.6, 37.0, 15.43), (29.55, 13.5), 3
        living = (30.7, 11.6, 46, 30)
        liv_pref = (38.5, 16.0 + rng.uniform(-1, 2))
        din_pref = (36.0 + rng.uniform(-1, 1), 21.5)
        bed1 = (34.5, -1, 46, 11.43)
        bed1_pref = (40.0, 10.3)
        bed2 = (21.0, -1, 34.5, 9.0)
        bed2_pref = (28.0 + rng.uniform(-2, 2), 7.9)
        liv_rot = 3
    fc.kit(K.kitchen(3.6), kit_room, kit_pref, rot=kit_rot, clear=0.0, step=0.1)
    fc.kit(K.living_set(rng.choice([2.4, 2.8])), living, liv_pref, rot=liv_rot)
    fc.kit(K.dining(rng.choice([2, 3])), living, din_pref, rot=rng.choice([0, 1]))
    if region_north:
        fc.kit(K.armchair_pair(), region_north, ((region_north[0] + region_north[2]) / 2, 25.0), rot=0)
        fc.kit(K.desk(), region_north, ((region_north[0] + region_north[2]) / 2, 27.0), rot=2)
    fc.kit(K.plant(), living, (liv_pref[0], 28.0), clear=0.2)
    fc.kit(K.tv_wall(2.4), living, (liv_pref[0] - 2.5 * (1 if side < 0 else -1), liv_pref[1]),
           rot=3 if side < 0 else 1, clear=0.3)
    fc.kit(K.bed(1.8), bed1, bed1_pref, rot=2, clear=0.35, step=0.15)
    fc.kit(K.wardrobe(2.0), bed1, (bed1_pref[0], 1.0), rot=2, clear=0.3)
    fc.kit(K.bed(1.6), bed2, bed2_pref, rot=2, clear=0.35, step=0.15)
    fc.kit(K.desk(), bed2, (bed2_pref[0] + 4.0 * (-side), 2.0), rot=0, clear=0.3)
    fc.kit(K.wardrobe(2.0), bed2, (bed2_pref[0] - 4.5 * (-side), 2.0), rot=0, clear=0.3)


def residential(fc):
    """Typical floors 8-59: 2 or 3 apartments around the full core."""
    n, Fz = fc.n, fc.Fz
    three = n % 3 != 0
    lobby = (14.0, 19.0, 28.0, 22.5)
    finish_default(fc, "Floor_Oak", extra_stone=[lobby])
    fc.block((14.0, 19.0, 28.0, 22.4))
    # lift lobby walls
    fc.wall((14.0, 19.0), (14.0, 22.5), openings=[(1.2, 2.2)])
    fc.wall((28.0, 19.0), (28.0, 22.5), openings=[(1.2, 2.2)])
    fc.wall((14.0, 22.5), (28.0, 22.5), openings=[(6.4, 7.4)] if three else [])
    fc.sink("furniture").box("Wood_Walnut", 17.2, 22.0, Fz, 19.2, 22.42, Fz + 0.85)
    fc.sink("decor").box("Art_Ivory", 17.4, 22.36, Fz + 1.2, 19.0, 22.42, Fz + 2.2)
    if three:
        for x in (14.0, 28.0):
            fc.wall((x, 22.5), fc.to_edge((x, 22.5), (0, 1)))
    else:
        fc.wall((21.0, 22.5), fc.to_edge((21.0, 22.5), (0, 1)))
    fc.wall((21.0, 9.0), fc.to_edge((21.0, 9.0), (0, -1)))
    # bedroom partitions + bathrooms in W and E apartments
    pw = fc.to_edge((14.0, 11.5), (-1, 0))
    if pw:
        fc.wall((14.0, 11.5), pw, openings=[(1.4, 2.4)])
        ps = fc.to_edge((7.5, 11.5), (0, -1))
        if ps:
            fc.wall((7.5, 11.5), ps, openings=[(0.9, 1.9)])
    pe = fc.to_edge((28.0, 11.5), (1, 0))
    if pe:
        fc.wall((28.0, 11.5), pe, openings=[(1.4, 2.4)])
        ps = fc.to_edge((34.5, 11.5), (0, -1))
        if ps:
            fc.wall((34.5, 11.5), ps, openings=[(0.9, 1.9)])
    bath(fc, 11.4, 15.5, 14.0, 19.0, 11.4)
    bath(fc, 28.0, 15.5, 30.6, 19.0, 30.6, mirror=True)
    # apartment entries stay clear
    fc.block((12.0, 19.0, 14.0, 22.6))
    fc.block((28.0, 19.0, 30.0, 22.6))
    if three:
        apt_rooms(fc, -1, None)
        apt_rooms(fc, +1, None)
        # north studio: glass partition, bed east, living/kitchen west
        top = fc.to_edge((23.5, 22.5), (0, 1))
        if top and top[1] - 22.5 > 3.0:
            fc.wall((23.5, 22.5), top, openings=[(0.3, 1.4)], mat="Glass_Partition", sink="glass_partitions",
                    th=0.06)
            fc.kit(K.bed(1.6, nightstands=False), (23.6, 22.6, 28.2, 31), (25.8, 23.8), rot=0, clear=0.15,
                   step=0.1)
            fc.kit(K.kitchen(3.0), (14.1, 22.6, 23.4, 31), (16.0, 24.2), rot=0, clear=0.1, step=0.1)
            fc.kit(K.sofa(2.0), (14.1, 22.6, 23.4, 31), (21.0, 26.0), rot=2, clear=0.2, step=0.15)
    else:
        apt_rooms(fc, -1, (14.0, 22.6, 21.0, 31))
        apt_rooms(fc, +1, (21.0, 22.6, 28.0, 31))
    fc.light_grid(spacing=4.2, size=0.5, holes=[C.CORE])
    if n == 30:                                    # sample floor with real lights
        for i, (x, y) in enumerate(((3, 16), (5, 23), (39, 16), (37, 23), (21, 26), (14, 5), (28, 5))):
            fc.point_light("F30_Light_%d" % i, (x, y, fc.zc - 0.3), energy=120.0)


def full_floor(fc):
    """Floors 60-76: one full-floor apartment around the compact core."""
    n, Fz = fc.n, fc.Fz
    rng = fc.rng
    foyer = (18.5, 16.8, 25.5, 19.6)
    finish_default(fc, "Floor_Oak", extra_stone=[foyer])
    fc.block(foyer)
    if n == FIRST_SMALL:
        fc.block((14.0, 16.6, 26.0, 21.2))            # transfer route full -> compact stair
    xw = 13.5 if n == FIRST_SMALL else 17.0
    xe = 27.0
    parts = False
    if n < 73:
        ee = fc.to_edge((xe, 19.0), (1, 0))
        es = fc.to_edge((xe, 19.0), (0, -1))
        if ee and es and ee[0] - xe > 3.5:
            fc.wall((xe, 19.0), es)
            fc.wall((xe, 19.0), ee, openings=[(1.0, 2.0)])
            fc.kit(K.bed(1.8), (xe, -1, 50, 19), (xe + 1.2, 14.0), rot=3, clear=0.3, step=0.15)
            fc.kit(K.wardrobe(2.2), (xe, -1, 50, 19), (xe + 4.0, 18.6), rot=2, clear=0.3)
            fc.kit(K.desk(), (xe, -1, 50, 19), (xe + 4.0, 9.0), rot=0, clear=0.3)
            parts = True
        we = fc.to_edge((xw, 19.0), (-1, 0))
        ws = fc.to_edge((xw, 19.0), (0, -1))
        if we and ws and xw - we[0] > 3.5:
            fc.wall((xw, 19.0), ws)
            fc.wall((xw, 19.0), we, openings=[(1.0, 2.0)])
            fc.kit(K.bed(1.6), (-5, -1, xw, 19), (xw - 1.2, 14.0), rot=1, clear=0.3, step=0.15)
            fc.kit(K.wardrobe(2.0), (-5, -1, xw, 19), (xw - 3.5, 18.6), rot=2, clear=0.3)
    liv = (-5, 19.1, 50, 32)
    fc.kit(K.living_set(rng.choice([2.6, 3.0])), liv, (21.5 + rng.uniform(-3, 3), 24.0), rot=0)
    fc.kit(K.kitchen(3.6), liv, (xw - 1.5, 21.2), rot=0, clear=0.1, step=0.15)
    fc.kit(K.dining(3), liv, (30.5, 21.8), rot=0)
    if n % 3 == 0:
        fc.kit(K.piano(), liv, (33.0, 24.0), rot=1)
    fc.kit(K.bookshelf(2.4, 2.2), (17.0, 9.0, 19.0, 19.0), (17.9, 14.0), rot=3, clear=0.0, step=0.1)
    if not parts:
        fc.kit(K.bed(1.8), (-5, -1, 50, 19), (28.5, 13.0), rot=3, clear=0.3, step=0.15)
        fc.kit(K.armchair_pair(), (-5, -1, 50, 19), (15.0, 13.0), rot=1, clear=0.3)
    for pref in ((24.0, 27.5), (12.0, 22.0), (35.0, 12.0)):
        fc.kit(K.plant(), (pref[0] - 2.5, pref[1] - 2.5, pref[0] + 2.5, pref[1] + 2.5), pref, clear=0.2)
    fc.light_grid(spacing=3.8, size=0.5, holes=core_holes(n))


def penthouse(fc):
    """Floor 77: open plan under the spire (no ceiling slab above)."""
    Fz = fc.Fz
    finish_default(fc, "Floor_Stone")
    foyer = (18.5, 16.8, 25.5, 19.4)
    fc.block(foyer)
    liv = (-5, 11.0, 50, 32)
    fc.kit(K.living_set(3.0), liv, (22.0, 21.5), rot=0, clear=0.4)
    fc.kit(K.piano(), liv, (17.0, 14.0), rot=1, clear=0.4)
    fc.kit(K.dining(2), liv, (27.5, 14.0), rot=1, clear=0.35)
    fc.kit(K.bed(1.8, nightstands=False), liv, (23.0, 24.5), rot=2, clear=0.3, step=0.1)
    # glass screen behind the bed
    fc.wall((20.5, 23.2), (25.5, 23.2), mat="Glass_Partition", sink="glass_partitions", th=0.05,
            top=Fz + 2.2, block=False)
    for pref in ((16.8, 12.3), (29.0, 12.3), (23.0, 19.8)):
        fc.kit(K.plant(), (pref[0] - 1.5, pref[1] - 1.5, pref[0] + 1.5, pref[1] + 1.5), pref, clear=0.1)
    # floor lamps (emissive shades) instead of ceiling panels
    d = fc.sink("decor")
    for x, y in ((19.0, 19.8), (27.0, 17.5), (17.5, 17.0)):
        if G.contains(fc.inner, x, y, 0.2):
            d.box("Metal_Dark", x - 0.02, y - 0.02, Fz, x + 0.02, y + 0.02, Fz + 1.5)
            d.box("Light_Emit", x - 0.2, y - 0.2, Fz + 1.5, x + 0.2, y + 0.2, Fz + 1.8)


# ---------------------------------------------------------------- build
def floor_kind(n):
    if n == 1:
        return lobby_f01
    if n in C.MOMA_FLOORS:
        return gallery
    if n == 3:
        return fitness_f03
    if n == 6:
        return pool_f06
    if n == 7:
        return amenity_f07
    if n == C.PENTHOUSE_FLOOR:
        return penthouse
    if C.core_is_small(n):
        return full_floor
    return residential


def build(ctx):
    t0 = time.time()
    ensure_materials()
    root = C.collection("Interiors", ctx.get("root") if isinstance(ctx, dict) else None)
    total = 0
    nobj = 0
    nlights = 0
    for n in range(1, C.NUM_FLOORS + 1):
        fc = FloorCtx(n, root)
        if n == 6:
            fc.extra_holes = [(8.0, 2.4, 28.0, 6.4)]
        build_structure(fc)
        floor_kind(n)(fc)
        total += fc.tris()
        nobj += len(fc.finish())
        nlights += len(fc.lights)
    print("[interiors] floors=%d objects=%d lights=%d tris=%d time=%.1fs"
          % (C.NUM_FLOORS, nobj, nlights, total, time.time() - t0))
    return {"tris": total}
