"""Ground-floor lobby (F01), after Thierry Despont's design for 53 W 53.

Block-through lobby: 53rd St entrance vestibule (low 3.5 m coffered ceiling,
bronze & glass inner screen) -> double-height (7 m) gallery wrapping the core
with cerused-oak panelling and bronze reveals, a coffered ceiling with bronze
inlays and recessed downlights, dark-stained oak floor with Noir St. Laurent
marble inlays, concierge desk, bronze-framed lift portals, a library with a
fireplace and floor-to-ceiling bookcases (NW), lounges, a large artwork facing
the entrance, alabaster sconces, and a doorway marked towards 54th Street.

Walking routes kept clear (stairtest.py): entrance (21, 0) -> y 7.5 ->
x 12.5 / x 29.5 -> y 20.5 -> lifts and stair door.
"""
import math
import random

import config as C
from modules import interiors_geom as G
from modules import interiors_prims as P
from modules import interiors_furn as FU
from modules import interiors_details as DT

NOIR, STAT, OAKC, OAKD, BRZ = DT.NOIR, DT.STAT, DT.OAKC, "Oak_Dark_Floor", DT.BRZ
VEST = (17.8, 0.0, 24.2, 4.8)                 # vestibule incl. side walls / header
VEST_IN = (17.95, 0.05, 24.05, 4.5)
LIFT_LOBBY = (14.0, 19.0, 28.0, 23.0)
LIB_X, LIB_Y = 11.0, 10.0                     # library east wall x, south wall y
XS = [1.75 + 3.5 * k for k in range(-2, 14)]  # coffer grid
YS = [1.0 + 3.5 * k for k in range(0, 9)]


def build(fc):
    from modules import interiors as I
    fc.kit_lights = 4
    rng = random.Random(5301)
    floors(fc, I)
    vestibule(fc)
    core_cladding(fc)
    concierge(fc)
    library(fc, rng)
    lounges(fc, rng)
    north(fc, rng)
    ceiling(fc)
    # keep the walking routes clear for later planner use
    for r in ((18.0, 0.0, 24.0, 8.8), (10.5, 6.5, 14.0, 24.0), (28.0, 6.5, 31.5, 24.0), (13.0, 18.8, 29.0, 24.0)):
        fc.block(r)


# ------------------------------------------------------------------ floors
def floors(fc, I):
    Fz = fc.Fz
    fl = fc.sink("floor")
    fc.sink("slab").box(NOIR, 19.4, -0.1, Fz - 0.3, 22.6, 0.3, Fz + 0.005)      # threshold
    special = [VEST_IN, LIFT_LOBBY]
    G.finish_floor(fl, OAKD, fc.slab_poly, I.core_holes(1) + special, Fz + 0.005)
    for r, bw in ((VEST_IN, 0.22), (LIFT_LOBBY, 0.3)):
        pc = G.clip_rect(fc.slab_poly, *r)
        if not pc:
            continue
        x0, y0, x1, y1 = r
        G.finish_floor(fl, STAT, pc, [(x0 + bw, y0 + bw, x1 - bw, y1 - bw)], Fz + 0.005)
        inner = G.clip_rect(fc.slab_poly, x0 + bw, y0 + bw, x1 - bw, y1 - bw)
        G.finish_floor(fl, NOIR, inner, [], Fz + 0.005)
        fl.mesh(BRZ, *P.box(x0 + bw - 0.02, y0 + bw - 0.02, Fz + 0.005, x1 - bw + 0.02, y0 + bw, Fz + 0.007))
    fl.box("Metal_Dark", 19.6, 0.5, Fz + 0.005, 22.4, 2.0, Fz + 0.009, sides=True)    # entry mat
    # Noir St. Laurent bands on the coffer grid + bronze diamonds at crossings
    excl = [C.CORE, VEST, LIFT_LOBBY, (-5.0, LIB_Y - 0.15, LIB_X + 0.15, 32.0)]
    poly = C.inset(fc.slab_poly, 0.35)
    bw = 0.14
    z = Fz + 0.007
    for axis, lines in ((0, XS), (1, YS)):
        for X in lines:
            sp = DT.span(poly, axis, X, bw / 2)
            if not sp:
                continue
            cuts = []
            for r in excl:
                lo, hi = (r[0], r[2]) if axis == 0 else (r[1], r[3])
                if lo - bw < X < hi + bw:
                    cuts.append((r[1] - 0.25, r[3] + 0.25) if axis == 0 else (r[0] - 0.25, r[2] + 0.25))
            for a, b in DT.cut_intervals(sp[0], sp[1], cuts):
                q = ([(X - bw / 2, a), (X + bw / 2, a), (X + bw / 2, b), (X - bw / 2, b)] if axis == 0 else
                     [(a, X - bw / 2), (b, X - bw / 2), (b, X + bw / 2), (a, X + bw / 2)])
                fl.hface(NOIR, q, z)
    for X in XS:
        for Y in YS:
            if not G.contains(poly, X, Y, 0.4) or any(r[0] - 0.3 < X < r[2] + 0.3 and r[1] - 0.3 < Y < r[3] + 0.3
                                                      for r in excl):
                continue
            s = 0.26
            fl.hface(BRZ, [(X, Y - s), (X + s, Y), (X, Y + s), (X - s, Y)], z + 0.001)


# ------------------------------------------------------------------ vestibule
def vestibule(fc):
    Fz, zc = fc.Fz, fc.zc
    w = fc.sink("walls")
    tr = fc.sink("trim")
    zl = 3.5                                                     # low ceiling
    for x in (17.8, 24.2):
        fc.wall((x, 0.05), (x, 4.8), mat=OAKC, th=0.3)
    w.box(OAKC, 17.95, 4.5, zl, 24.05, 4.8, zc)                  # header over the portal
    fc.sink("ceiling").box("Wall_White", 17.95, 0.05, zl, 24.05, 4.5, zl + 0.25)
    DT.coffers(fc, [(17.95, 0.05), (24.05, 0.05), (24.05, 4.5), (17.95, 4.5)], [], zl,
               [17.95, 19.475, 21.0, 22.525, 24.05], [0.05, 1.53, 3.02, 4.5], bw=0.16, bd=0.16, step=1)
    # panelling: inner faces (to 3.5 m), outer faces + header (to the ceiling)
    DT.panel_wall(tr, (17.95, 0.05), (17.95, 4.5), (1, 0), Fz, zl, rail_z=2.9)
    DT.panel_wall(tr, (24.05, 4.5), (24.05, 0.05), (-1, 0), Fz, zl, rail_z=2.9)
    DT.panel_wall(tr, (17.65, 4.8), (17.65, 0.05), (-1, 0), Fz, zc)
    DT.panel_wall(tr, (24.35, 0.05), (24.35, 4.8), (1, 0), Fz, zc)
    DT.panel_wall(tr, (17.65, 4.8), (24.35, 4.8), (0, 1), zl, zc, base=None, rail_z=zl + 0.05)
    # portal architrave + pilaster caps (bronze)
    tr.mesh(BRZ, *P.cbox(17.95, 4.78, zl - 0.12, 24.05, 4.9, zl + 0.04, 0.01))
    for x in (17.8, 24.2):
        tr.mesh(BRZ, *P.cbox(x - 0.17, 4.78, Fz, x + 0.17, 4.9, zl + 0.04, 0.012))
    # gilded "53" plaque above the portal
    tr.mesh("Gold_Leaf", *P.cbox(20.3, 4.8, zl + 1.2, 21.7, 4.86, zl + 1.6, 0.01))
    # inner bronze and glass screen with open leaves at y = 2.3
    ys = 2.3
    gp = fc.sink("glass_partitions")
    for a, b in ((17.95, 19.6), (22.4, 24.05)):
        gp.mesh("Glass_Partition", *P.box(a, ys - 0.012, Fz, b, ys + 0.012, 2.8))
    gp.mesh("Glass_Partition", *P.box(17.95, ys - 0.012, 2.92, 24.05, ys + 0.012, zl))
    for x in (17.99, 19.6, 22.4, 24.01):
        tr.mesh(BRZ, *P.cbox(x - 0.05, ys - 0.05, Fz, x + 0.05, ys + 0.05, zl, 0.008))
    tr.mesh(BRZ, *P.cbox(17.95, ys - 0.05, 2.8, 24.05, ys + 0.05, 2.92, 0.008))
    tr.mesh(BRZ, *P.cbox(17.95, ys - 0.05, Fz, 24.05, ys + 0.05, Fz + 0.04, 0.005))
    for x, sgn in ((19.68, 1), (22.32, -1)):                       # open leaves along the side
        gp.mesh("Glass_Partition", *P.box(x - 0.01, ys + 0.12, Fz + 0.1, x + 0.01, ys + 1.3, 2.7))
        for yy in (ys + 0.08, ys + 1.34):
            tr.mesh(BRZ, *P.cbox(x - 0.03, yy - 0.04, Fz + 0.02, x + 0.03, yy + 0.04, 2.76, 0.006))
        tr.mesh(BRZ, *P.cbox(x - 0.03, ys + 0.08, 2.7, x + 0.03, ys + 1.34, 2.76, 0.006))
        tr.mesh(BRZ, *P.cbox(x - 0.03, ys + 0.08, Fz + 0.02, x + 0.03, ys + 1.34, Fz + 0.12, 0.006))
        tr.mesh(BRZ, *P.cyl(x + sgn * 0.07, ys + 1.15, 0.8, 1.9, 0.016, 8))
    fc.block((17.6, 2.1, 19.75, 3.75))
    fc.block((22.25, 2.1, 24.4, 3.75))
    for x, ang in ((17.95, -90), (24.05, 90)):
        for y in (1.15, 3.45):
            fc.put(FU.sconce(2.1), x, y, ang, block=False)
    fc.point_light("Lobby_Vestibule", (21.0, 2.3, zl - 0.15), 120.0, "AREA", 2.0)


# ------------------------------------------------------------------ core
def core_cladding(fc):
    Fz, zc = fc.Fz, fc.zc
    tr = fc.sink("trim")
    x0, y0, x1, y1 = C.CORE
    DT.panel_wall(tr, (x1, y0 - 0.0), (x0, y0), (0, -1), Fz, zc)                    # south
    DT.panel_wall(tr, (x0, y0), (x0, y1), (-1, 0), Fz, zc)                         # west
    DT.panel_wall(tr, (x1, y1), (x1, y0), (1, 0), Fz, zc)                          # east
    ops = [(15.0 - x0, 16.2 - x0, 2.25)]
    for c in (20.55, 23.5, 26.45):
        ops.append((c - 0.6 - x0, c + 0.6 - x0, 2.3))
    DT.panel_wall(tr, (x0, y1), (x1, y1), (0, 1), Fz, zc, openings=ops)          # north (lifts)
    for c in (20.55, 23.5, 26.45):                                                 # floor indicators
        tr.mesh("Gold_Leaf", *P.cbox(c - 0.3, y1 + 0.07, 2.55, c + 0.3, y1 + 0.1, 2.68, 0.005))
    # artwork facing the entrance + flanking alabaster sconces
    fc.put(FU.artwork(6.0, 3.4, 3.7, random.Random(53), frame=BRZ, style="blocks"), 21.0, y0 - 0.05, 180,
           block=False)
    for x in (16.2, 25.8):
        fc.put(FU.sconce(2.6, h=0.5), x, y0 - 0.05, 180, block=False)
    for y in (11.5, 16.5):
        fc.put(FU.sconce(2.6, h=0.5), x0 - 0.05, y, 90, block=False)
        fc.put(FU.sconce(2.6, h=0.5), x1 + 0.05, y, -90, block=False)
    # picture lights on the big canvas
    for x in (19.3, 22.7):
        fc.point_light("Lobby_ArtSpot_%d" % (x > 21), (x, 6.0, 6.3), 400.0, "SPOT", 0.15,
                       rot=(math.radians(52), 0.0, 0.0), spot=math.radians(40))
    fc.block((13.7, 8.7, 28.3, 19.3))


# ------------------------------------------------------------------ concierge
def concierge(fc):
    L = 5.0
    k = FU.Kit(L + 0.2, 1.8)
    k.cb(FU.F, NOIR, -L / 2 + 0.04, -0.05, 0.0, L / 2 - 0.04, 0.4, 0.1, 0.008)
    k.cb(FU.F, OAKC, -L / 2, 0.0, 0.1, L / 2, 0.42, 1.0, 0.006)
    for s in (-1, 1):                                    # end returns
        k.cb(FU.F, OAKC, s * L / 2 - (0.08 if s > 0 else 0), -0.75, 0.1, s * L / 2 + (0.08 if s < 0 else 0), 0.42,
             1.0, 0.006)
        k.cb(FU.F, NOIR, s * L / 2 - (0.09 if s > 0 else -0.01), -0.75, 0.0, s * L / 2 + (0.09 if s < 0 else -0.01),
             0.42, 0.1, 0.006)
    x = -L / 2 + 0.16
    while x < L / 2 - 0.15:                              # reeded (fluted) front
        k.add(FU.D, OAKC, P.lathe([(0.021, 0.16), (0.021, 0.95)], 6, x, 0.42, cap0=False, cap1=False,
                                  a0=0.0, a1=math.pi), smooth=True)
        x += 0.046
    k.cb(FU.D, BRZ, -L / 2, 0.41, 0.95, L / 2, 0.47, 1.0, 0.006)
    k.cb(FU.D, BRZ, -L / 2, 0.41, 0.1, L / 2, 0.46, 0.16, 0.006)
    k.cb(FU.F, STAT, -L / 2 - 0.03, 0.02, 1.0, L / 2 + 0.03, 0.54, 1.05, 0.006)
    k.cb(FU.F, "Walnut", -L / 2 + 0.08, -0.75, 0.72, L / 2 - 0.08, 0.0, 0.76, 0.006)
    for x in (-1.5, 1.5):
        k.sub(FU.table_lamp(1.05, shade=FU.ALAB, base=BRZ, h=0.55), x, 0.28)
        k.light((x, 0.28, 1.5), 15.0, "POINT", 0.08)
        k.bx(FU.D, "Glass_Black", x * 0.6 - 0.28, -0.55, 0.76, x * 0.6 + 0.28, -0.53, 1.12)
    k.sub(FU.vase_flowers(0.8, random.Random(9), vase=BRZ, bloom="Flower_White"), 0.0, 0.28, z=1.05)
    for x in (-1.0, 1.0):
        k.sub(FU.dining_chair(BRZ, FU.LEATH), x, -1.05, 0)
    fc.put(k, 28.6, 2.55, 0, pad=0.2)


# ------------------------------------------------------------------ library
def library(fc, rng):
    Fz, zc = fc.Fz, fc.zc
    tr = fc.sink("trim")
    north = fc.to_edge((LIB_X, LIB_Y), (0, 1))
    west = fc.to_edge((LIB_X, LIB_Y), (-1, 0))
    door = (14.6, 17.0)
    fc.wall((LIB_X, LIB_Y - 0.15), north, openings=[(door[0] - LIB_Y + 0.15, door[1] - LIB_Y + 0.15)], mat=OAKC,
            th=0.3, door_h=3.3)
    fc.wall(west, (LIB_X + 0.15, LIB_Y), mat=OAKC, th=0.3)
    yN = north[1]
    # outer panelling (lobby side) with the bronze-cased doorway
    DT.panel_wall(tr, (LIB_X + 0.15, LIB_Y - 0.15), (LIB_X + 0.15, yN), (1, 0), Fz, zc,
                  openings=[(door[0] - LIB_Y + 0.15, door[1] - LIB_Y + 0.15, 3.3)])
    DT.panel_wall(tr, (LIB_X + 0.15, LIB_Y - 0.15), (west[0], LIB_Y - 0.15), (0, -1), Fz, zc)
    # inner side of the doorway: architrave
    DT.panel_wall(tr, (LIB_X - 0.15, door[1]), (LIB_X - 0.15, door[0]), (-1, 0), Fz, 3.4,
                  openings=[(0.0, door[1] - door[0], 3.3)], base=None)
    # -- fireplace on the south wall, chimney breast x 2.9..6.3
    xc = 4.6
    yw = LIB_Y + 0.15
    w = fc.sink("walls")
    dep = 0.6
    w.box(OAKC, 2.9, yw, Fz, 4.05, yw + dep, zc)
    w.box(OAKC, 5.15, yw, Fz, 6.3, yw + dep, zc)
    w.box(OAKC, 4.05, yw, 0.9, 5.15, yw + dep, zc)
    w.box("Lacquer_Black", 4.05, yw, Fz, 5.15, yw + 0.2, 0.9)
    d = fc.sink("decor")
    for vf in (P.box(4.04, yw + 0.2, Fz, 4.06, yw + dep, 0.9), P.box(5.14, yw + 0.2, Fz, 5.16, yw + dep, 0.9),
               P.box(4.05, yw + 0.2, 0.88, 5.15, yw + dep, 0.9)):
        d.mesh("Lacquer_Black", *vf)
    yf = yw + dep
    f = fc.sink("furniture")
    f.mesh(NOIR, *P.cbox(3.65, yf, Fz, 4.05, yf + 0.1, 1.3, 0.01))
    f.mesh(NOIR, *P.cbox(5.15, yf, Fz, 5.55, yf + 0.1, 1.3, 0.01))
    f.mesh(NOIR, *P.cbox(4.05, yf, 0.9, 5.15, yf + 0.1, 1.3, 0.01))
    f.mesh(NOIR, *P.cbox(3.45, yf - 0.05, 1.3, 5.75, yf + 0.26, 1.38, 0.012))         # mantel
    f.mesh(NOIR, *P.cbox(3.35, yf, Fz, 5.85, yf + 0.65, Fz + 0.04, 0.008))             # hearth
    tr.mesh(BRZ, *P.cbox(4.0, yf + 0.08, 0.86, 5.2, yf + 0.11, 0.9, 0.004))
    # logs, grate and flames
    for i, (x0, x1, h) in enumerate(((4.2, 5.0, 0.12), (4.25, 4.95, 0.2), (4.3, 5.05, 0.13))):
        y = yw + 0.35 + 0.08 * (i - 1)
        d.mesh("Bark", *P.beam((x0, y, h), (x1, y + 0.03, h + 0.01), 0.1))
    tr.mesh(BRZ, *P.cbox(4.15, yw + 0.25, Fz, 5.05, yw + 0.5, 0.06, 0.004))
    fr = random.Random(11)
    for i in range(14):
        bx, by = fr.uniform(4.25, 4.95), fr.uniform(yw + 0.28, yw + 0.45)
        vf = P.leaf((bx, by, 0.16), (fr.uniform(-0.2, 0.2), fr.uniform(-0.1, 0.1), 1.0), fr.uniform(0.15, 0.32),
                    fr.uniform(0.05, 0.1), 0.0, fr.uniform(0, 3))
        d.mesh("Fire_Glow", *vf)
    d.mesh("Fire_Glow", *P.box(4.15, yw + 0.22, 0.06, 5.05, yw + 0.5, 0.075))
    fc.point_light("Library_Fire", (xc, yw + 0.55, 0.45), 90.0, "POINT", 0.25, color=(1.0, 0.55, 0.22))
    DT.panel_wall(tr, (2.9, yf), (6.3, yf), (0, 1), 1.38, zc, base=None, rail_z=5.0)
    DT.panel_wall(tr, (2.9, yw), (2.9, yf), (-1, 0), Fz, zc, module=0.6)
    DT.panel_wall(tr, (6.3, yf), (6.3, yw), (1, 0), Fz, zc, module=0.6)
    fc.put(FU.artwork(1.5, 1.8, 2.75, random.Random(7), frame="Gold_Leaf", style="shapes"), xc, yf + 0.05, 0,
           block=False)
    for x in (3.2, 6.0):
        fc.put(FU.sconce(2.2), x, yf + 0.05, 0, block=False)
    fc.block((2.8, yw, 6.4, yf + 0.7))
    # -- bookcases: south wall either side of the breast, east wall either side of the door
    bk_h = 4.6

    def run(p0, p1, ang, nrm):
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        n = max(1, int(L / 1.15))
        uw = L / n
        ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
        for i in range(n):
            s = (i + 0.5) * uw
            x, y = p0[0] + ux * s + nrm[0] * 0.21, p0[1] + uy * s + nrm[1] * 0.21
            fc.put(FU.bookcase(uw - 0.01, bk_h, random.Random(rng.random()), wood="Walnut", shelf=0.4, d=0.42),
                   x, y, ang)
        # cornice + frieze above the run, rolling-ladder rail
        tr.mesh("Walnut", *DT.map_wall(P.cbox(0.0, 0.0, bk_h, L, 0.46, bk_h + 0.18, 0.02), p0, (ux, uy), nrm))
        tr.mesh(BRZ, *DT.map_wall(P.beam((0.05, 0.5, 3.1), (L - 0.05, 0.5, 3.1), 0.035), p0, (ux, uy), nrm))
        return L

    wx = west[0] + 0.25
    run((wx, yw), (2.85, yw), 0, (0, 1))
    run((6.35, yw), (LIB_X - 0.2, yw), 0, (0, 1))
    xi = LIB_X - 0.15
    run((xi, yw + 0.45), (xi, door[0] - 0.12), 90, (-1, 0))
    yN2 = fc.to_edge((xi - 0.45, door[1]), (0, 1))[1] - 0.1
    L2 = run((xi, door[1] + 0.12), (xi, yN2), 90, (-1, 0))
    # library ladder leaning on the east run
    lx, ly = xi - 0.95, door[1] + 0.12 + L2 * 0.5
    ld = fc.sink("decor")
    for dy in (-0.25, 0.25):
        ld.mesh(BRZ, *P.beam((lx, ly + dy, 0.0), (xi - 0.5, ly + dy, 3.12), 0.04))
    for i in range(1, 11):
        t = i / 11
        ld.mesh("Walnut", *P.beam((lx + (xi - 0.5 - lx) * t, ly - 0.25, 3.12 * t),
                                  (lx + (xi - 0.5 - lx) * t, ly + 0.25, 3.12 * t), 0.035, 0.02))
    # -- seating group facing the fire
    fc.put(FU.rug(4.6, 3.8, "Rug_Wool", "Rug_Border"), xc, 13.0, 0, block=False)
    fc.put(FU.sofa(2.6, "Fabric_Velvet_Green", seats=3, pillows=("Fabric_Rust", "Fabric_Sand")), xc, 14.6, 180)
    fc.put(FU.armchair(FU.LEATH), 2.55, 12.6, -90)
    fc.put(FU.armchair(FU.LEATH), 6.65, 12.6, 90)
    fc.put(FU.coffee_rect(1.3, 0.75, top="Walnut"), xc, 12.75, 0)
    for x in (2.95, 6.25):
        fc.put(FU.side_table(), x, 14.95, 0)
        fc.put(FU.table_lamp(0.55, h=0.6), x, 14.95, 0, block=False)
    fc.put(FU.floor_lamp(), 1.7, 13.9, 0)
    fc.put(FU.floor_lamp(), 7.5, 13.9, 0)
    # -- reading table under the window
    fc.put(FU.rug(4.4, 2.9, "Rug_Sisal", "Rug_Border"), 5.0, 19.0, 0, block=False)
    k = FU.dining_table(2.6, 1.05, "Walnut", 3, ends=True, chair_kw={"fab": FU.LEATH}, centre=False)
    for x in (-0.75, 0.75):
        k.sub(FU.table_lamp(0.75, shade="Fabric_Velvet_Green", base=BRZ, h=0.5), x, 0.0)
    fc.put(k, 5.0, 19.0, 0)
    # globe and plants
    g = FU.Kit(0.6, 0.6)
    g.lathe(FU.F, "Walnut", [(0.22, 0.0), (0.22, 0.03), (0.04, 0.06), (0.03, 0.62), (0.0, 0.62)], 12)
    g.add(FU.D, "Book_Tan", P.rbox(-0.26, -0.26, 0.62, 0.26, 0.26, 1.14, 1.0, 16, 10), smooth=True)
    g.add(FU.D, BRZ, P.xf(P.lathe([(0.29, -0.01), (0.29, 0.01)], 24, cap0=False, cap1=False), rx=1.3,
                          t=(0.0, 0.0, 0.88)))
    fc.put(g, 1.2, 16.6, 30)
    fc.put(FU.plant("olive", 2.1, random.Random(4)), 0.4, 11.4, 0)
    fc.point_light("Library_Area", (5.0, 16.5, zc - 0.25), 300.0, "AREA", 3.0, color=(1.0, 0.86, 0.7))


# ------------------------------------------------------------------ lounges / north
def lounges(fc, rng):
    from modules import interiors_hq as HQ
    HQ.reset(101)
    fc.put(HQ.living_set(3.0, fab="Fabric_Linen", rng=random.Random(2)), 5.6, 4.7, 0)
    fc.put(FU.sideboard(2.4, rng=random.Random(3)), 5.6, LIB_Y - 0.15 - 0.27, 180)
    fc.put(FU.artwork(2.6, 1.7, 2.9, random.Random(19), frame=BRZ, style="shapes"), 5.6, LIB_Y - 0.21, 180,
           block=False)
    fc.put(HQ.living_set(3.0, fab="Fabric_Cream", rng=random.Random(8)), 37.3, 12.8, 90)
    fc.put(FU.grand_piano(), 37.0, 4.4, 15)
    for (x, y), kind in (((1.6, 1.5), "fig"), ((12.6, 1.4), "palm"), ((41.0, 1.4), "fig"), ((43.6, 18.6), "palm"),
                         ((31.2, 21.0), "olive"), ((32.0, 8.0), "fig")):
        fc.put(FU.plant(kind, rng.uniform(1.8, 2.3), random.Random(int(x * 10 + y))), x, y, rng.uniform(0, 360))
    fc.put(FU.bench(2.2, top="Fabric_Velvet_Green"), 10.6, 4.4, 90)


def north(fc, rng):
    Fz, zc = fc.Fz, fc.zc
    # centre table with a big arrangement
    k = FU.round_table(0.85, "Walnut", chairs=0, candles=False)
    k.sub(FU.vase_flowers(1.25, random.Random(77), vase=BRZ, bloom="Flower_White"), 0, 0, z=0.75)
    fc.put(k, 21.0, 25.6, 0)
    fc.put(FU.bench(2.0, top="Fabric_Velvet_Green"), 16.6, 24.6, 90)
    fc.put(FU.bench(2.0, top="Fabric_Velvet_Green"), 25.4, 24.6, 90)
    # 54th Street doorway on the north-east facade
    a, b = (46.0, 22.0), (19.0, 30.0)
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    nrm = (-u[1], u[0])                      # pointing inward (south-west)
    s0 = 16.0                                # door centre along the edge
    p0 = (a[0] + u[0] * (s0 - 1.4) + nrm[0] * 0.3, a[1] + u[1] * (s0 - 1.4) + nrm[1] * 0.3)
    tr, gp = fc.sink("trim"), fc.sink("glass_partitions")
    W, H = 2.8, 3.3
    for vf in (P.cbox(-0.18, 0.0, Fz, 0.0, 0.2, H + 0.18, 0.012), P.cbox(W, 0.0, Fz, W + 0.18, 0.2, H + 0.18, 0.012),
               P.cbox(0.0, 0.0, H, W, 0.2, H + 0.18, 0.012), P.cbox(W / 2 - 0.04, 0.02, Fz, W / 2 + 0.04, 0.18, H, 0.006),
               P.cbox(0.0, 0.02, 2.75, W, 0.18, 2.83, 0.006),
               P.cbox(0.4, 0.2, H + 0.45, W - 0.4, 0.24, H + 0.8, 0.008)):
        tr.mesh(BRZ, *DT.map_wall(vf, p0, u, nrm))
    tr.mesh("Gold_Leaf", *DT.map_wall(P.box(0.55, 0.24, H + 0.53, W - 0.55, 0.25, H + 0.72), p0, u, nrm))
    for x0, x1 in ((0.0, W / 2 - 0.04), (W / 2 + 0.04, W)):
        gp.mesh("Glass_Partition", *DT.map_wall(P.box(x0, 0.09, Fz, x1, 0.11, 2.75), p0, u, nrm))
        hx = x1 - 0.12 if x0 == 0.0 else x0 + 0.12
        tr.mesh(BRZ, *DT.map_wall(P.cyl(hx, 0.2, 0.7, 1.8, 0.018, 8), p0, u, nrm))
    gp.mesh("Glass_Partition", *DT.map_wall(P.box(0.0, 0.09, 2.83, W, 0.11, H), p0, u, nrm))
    fc.sink("floor").mesh("Metal_Dark", *DT.map_wall(P.box(0.1, 0.2, Fz + 0.005, W - 0.1, 1.6, Fz + 0.009), p0, u,
                                                     nrm))
    cx, cy = p0[0] + u[0] * W / 2 + nrm[0] * 1.0, p0[1] + u[1] * W / 2 + nrm[1] * 1.0
    fc.empty("DOOR_54TH_ST", (cx, cy, Fz), kind="door", label="54th Street")
    fc.block((cx - 2.0, cy - 2.0, cx + 2.0, cy + 2.0))
    for s in (s0 - 3.2, s0 + 3.2):
        x, y = a[0] + u[0] * s + nrm[0] * 0.9, a[1] + u[1] * s + nrm[1] * 0.9
        fc.put(FU.plant("palm", 2.2, random.Random(int(s))), x, y, 0)
    fc.point_light("Lobby_LiftLobby", (21.0, 21.2, zc - 0.3), 350.0, "AREA", 2.5)


# ------------------------------------------------------------------ ceiling
def ceiling(fc):
    zc = fc.zc
    poly = fc.slab_poly
    cells = DT.coffers(fc, poly, [C.CORE, VEST], zc, XS, YS, bw=0.4, bd=0.55, step=1)
    picks = [(5.25, 4.5), (5.25, 15.0), (12.25, 4.5), (29.75, 4.5), (36.75, 11.5), (36.75, 4.5), (29.75, 22.0),
             (12.25, 22.0)]
    for i, (x, y) in enumerate(picks):
        best = min(cells, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2) if cells else None
        if best:
            fc.point_light("Lobby_Coffer_%d" % i, (best[0], best[1], zc - 0.25), 260.0, "AREA", 1.8)
