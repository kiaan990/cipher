"""Amenity showcase spaces.

pool(fc)       F06 wellness floor after the developer renderings: 20 m (65 ft)
               lap pool with a glowing basin, dark Noir St. Laurent deck,
               floor-to-ceiling glass along the south side, two Patrick Blanc
               vertical gardens (west end wall + the core's south face),
               white beams crossing in a coffered ceiling with lit
               skylight-like panels, white loungers, hot tub and sauna.
wine_room(fc)  F07 private dining / wine room: backlit wine walls, dark wood
               diagrid-patterned ceiling with warm uplight, round table.
"""
import math
import random

import mathutils

import config as C
from modules import interiors_geom as G
from modules import interiors_prims as P
from modules import interiors_furn as FU
from modules import interiors_details as DT

NOIR, STAT, BRZ = DT.NOIR, DT.STAT, DT.BRZ
POOL = (8.0, 3.0, 28.0, 7.0)                 # 20 m x 4 m lap pool
HALL = (5.15, 0.0, 31.0, 9.0)                # pool hall (dark deck, coffers)
DEPTH = 1.3


def aim(loc, target):
    d = mathutils.Vector(target) - mathutils.Vector(loc)
    return d.to_track_quat("-Z", "Y").to_euler()


# ------------------------------------------------------------------ pool
def pool(fc):
    from modules import interiors as I
    Fz, zc = fc.Fz, fc.zc
    fc.kit_lights = 0
    fl = fc.sink("floor")
    holes = I.core_holes(fc.n) + [HALL]
    G.finish_floor(fl, "Limestone_Verona", fc.slab_poly, holes, Fz + 0.005)
    hall = G.clip_rect(fc.slab_poly, *HALL)
    G.finish_floor(fl, NOIR, hall, [POOL], Fz + 0.005)
    x0, y0, x1, y1 = POOL
    pl = fc.sink("pool")
    t, zb = 0.25, Fz - DEPTH
    zf = zb + 0.2
    for a, b, c, d in ((x0 - t, y0 - t, x1 + t, y0), (x0 - t, y1, x1 + t, y1 + t), (x0 - t, y0, x0, y1),
                       (x1, y0, x1 + t, y1)):
        pl.box(NOIR, a, b, zb, c, d, Fz - 0.3)
        pl.box("Pool_Tile", a, b, Fz - 0.3, c, d, Fz)
    pl.box("Pool_Tile", x0, y0, zb, x1, y1, zf)
    nst = 6
    r = (Fz - zf) / nst
    for i in range(1, nst):                                    # entry steps (west end)
        pl.box("Pool_Tile", x0, y0, zf, x0 + i * 0.32, y1, Fz - i * r)
    d = fc.sink("decor")
    for yy in (y0 + 1.0, (y0 + y1) / 2, y1 - 1.0):              # lane lines
        d.box("Art_Black", x0 + 2.4, yy - 0.1, zf, x1 - 0.8, yy + 0.1, zf + 0.004)
        d.box("Art_Black", x1 - 1.2, yy - 0.5, zf, x1 - 0.8, yy + 0.5, zf + 0.004)
    lit = fc.sink("lights")
    for yy, sgn in ((y0 + 0.002, 1), (y1 - 0.002, -1)):         # underwater light lines
        lit.face("Pool_Light", [(x0 + 1.0, yy, Fz - 0.42), (x1 - 0.3, yy, Fz - 0.42), (x1 - 0.3, yy, Fz - 0.36),
                                (x0 + 1.0, yy, Fz - 0.36)][::sgn])
    # coping: dark stone with a bronze nosing, slightly proud
    tr = fc.sink("trim")
    for a, b, c, e in ((x0 - 0.35, y0 - 0.35, x1 + 0.35, y0), (x0 - 0.35, y1, x1 + 0.35, y1 + 0.35),
                       (x0 - 0.35, y0, x0, y1), (x1, y0, x1 + 0.35, y1)):
        d.mesh(NOIR, *P.cbox(a, b, Fz, c, e, Fz + 0.02, 0.006))
    for yy in (y0, y1):
        tr.mesh(BRZ, *P.box(x0, yy - 0.012, Fz - 0.04, x1, yy + 0.012, Fz + 0.022))
    fc.sink("water").hface("Water_Pool", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], Fz - 0.1)
    for xx in (x1 - 0.45, x1 - 0.95):                           # ladder rails
        fc.sink("rail").mesh("Steel_Brushed", *P.merge(
            P.beam((xx, y1 + 0.35, Fz + 0.85), (xx, y1 - 0.02, Fz + 0.85), 0.045),
            P.beam((xx, y1 - 0.02, Fz + 0.85), (xx, y1 - 0.18, Fz - 0.9), 0.045)))
    fc.block((x0 - 0.6, y0 - 0.6, x1 + 0.6, y1 + 0.6))
    fc.block((13.0, 18.8, 29.0, 23.2))
    # walls: west garden wall, short north wall with a door, garden on the core face
    fc.wall((5.0, 0.3), (5.0, 9.0), mat="Wall_White", th=0.3)
    fc.wall((5.15, 9.0), (14.0, 9.0), openings=[(4.6, 6.0)], mat="Wall_White", th=0.3, door_h=2.6)
    DT.green_wall(fc, (5.15, 0.35), (5.15, 8.85), Fz, zc, (1, 0), density=42, seed=61)
    DT.green_wall(fc, (14.0, 9.0), (28.0, 9.0), Fz, zc, (0, -1), density=42, seed=62)
    DT.panel_wall(tr, (5.15, 9.0 - 0.15), (14.0, 9.0 - 0.15), (0, -1), Fz, zc, openings=[(4.6, 6.0, 2.6)],
                  panel="Limestone_Verona", base=NOIR, rail_z=2.6, fields=False, module=1.5)
    # ceiling: white beams crossing in a coffered grid with skylight panels
    hp = G.clip_rect(fc.slab_poly, 5.3, 0.0, 31.0, 8.85)
    xs = [5.3 + (31.0 - 5.3) * i / 7 for i in range(8)]
    ys = [0.25, 3.1, 6.0, 8.85]
    cells = DT.coffers(fc, hp, [], zc, xs, ys, bw=0.5, bd=0.75, step=0, downlights=False,
                       beam_mat="Lacquer_White", inlay=None)
    for cx, cy, w, h in cells:
        lit.hface("Light_Skylight", [(cx - w / 2 + 0.25, cy - h / 2 + 0.25), (cx + w / 2 - 0.25, cy - h / 2 + 0.25),
                                     (cx + w / 2 - 0.25, cy + h / 2 - 0.25), (cx - w / 2 + 0.25, cy + h / 2 - 0.25)],
                  zc - 0.006, up=False)
    cs = fc.sink("ceiling")
    south = [5.3, 13.87, 22.43, 31.0]
    north = [9.6, 18.15, 26.7]
    pts = []
    for i in range(3):
        pts += [(south[i], 0.3), (north[i], 8.8)]
    pts.append((south[3], 0.3))
    for a, b in zip(pts, pts[1:]):
        cs.mesh("Lacquer_White", *P.obeam((a[0], a[1], zc - 0.55), (b[0], b[1], zc - 0.55), (0, 0, 1),
                                          P._norm(P._cross((b[0] - a[0], b[1] - a[1], 0), (0, 0, 1))), 0.6, 0.5))
    # lights (Cycles): skylight areas, garden grazers, underwater
    for i, x in enumerate((10.0, 18.0, 26.0)):
        fc.point_light("Pool_Sky_%d" % i, (x, 4.6, zc - 0.3), 450.0, "AREA", 3.0, color=(0.88, 0.94, 1.0))
    for i, (loc, tgt) in enumerate((((8.2, 4.6, zc - 0.4), (5.2, 4.6, Fz + 1.8)),
                                    ((21.0, 6.0, zc - 0.4), (21.0, 9.0, Fz + 1.8)))):
        fc.point_light("Pool_Garden_%d" % i, loc, 900.0, "SPOT", 0.3, color=(1.0, 0.93, 0.8),
                       rot=aim(loc, tgt), spot=math.radians(75))
    ob = fc.point_light("Pool_Underwater", ((x0 + x1) / 2, (y0 + y1) / 2, zf + 0.05), 600.0, "AREA", 18.0,
                        color=(0.5, 0.85, 1.0), rot=(math.pi, 0.0, 0.0))
    if ob is not None:
        ob.data.shape = "RECTANGLE"
        ob.data.size, ob.data.size_y = x1 - x0 - 0.5, y1 - y0 - 0.5
    # loungers along the glass, facing the pool, white side tables between
    for i in range(6):
        x = 9.4 + i * 3.1
        fc.put(FU.lounger(), x, 1.55, 0)
        if i < 5:
            fc.put(FU.side_table(top=FU.LACW, base=FU.LACW, h=0.42, r=0.2), x + 1.55, 1.2, 0)
    for x in (29.6, ):
        fc.put(FU.lounger(), x, 4.6, 0)
    fc.put(FU.plant("palm", 2.4, random.Random(66)), 30.2, 1.2, 0)
    fc.put(FU.plant("fig", 2.0, random.Random(67)), 30.2, 7.9, 0)
    # hot tub (raised) east of the hall
    ht = (32.4, 2.0, 35.6, 5.2)
    pl.mesh(NOIR, *P.cbox(ht[0], ht[1], Fz, ht[2], ht[3], Fz + 0.55, 0.02))
    fc.sink("water").hface("Water_Pool", [(ht[0] + 0.2, ht[1] + 0.2), (ht[2] - 0.2, ht[1] + 0.2),
                                          (ht[2] - 0.2, ht[3] - 0.2), (ht[0] + 0.2, ht[3] - 0.2)], Fz + 0.5)
    lit.hface("Pool_Light", [(ht[0] + 0.25, ht[1] + 0.25), (ht[2] - 0.25, ht[1] + 0.25),
                             (ht[2] - 0.25, ht[3] - 0.25), (ht[0] + 0.25, ht[3] - 0.25)], Fz + 0.2)
    fc.block(ht)
    # sauna (teak box) north-west
    sa = (1.5, 12.5, 7.0, 17.5)
    fc.wall((sa[0], sa[1]), (sa[2], sa[1]), mat="Wood_Teak")
    fc.wall((sa[0], sa[3]), (sa[2], sa[3]), mat="Wood_Teak")
    fc.wall((sa[0], sa[1]), (sa[0], sa[3]), mat="Wood_Teak")
    fc.wall((sa[2], sa[1]), (sa[2], sa[3]), openings=[(1.5, 2.5)], mat="Wood_Teak")
    f = fc.sink("furniture")
    for i, (h, w) in enumerate(((0.45, 0.6), (0.9, 0.5))):
        f.mesh("Wood_Teak", *P.cbox(sa[0] + 0.1 + i * 0.6, sa[1] + 0.1, Fz + h - 0.05, sa[0] + 0.1 + i * 0.6 + w,
                                    sa[3] - 0.1, Fz + h, 0.01))
    fc.block((sa[0] - 0.3, sa[1] - 0.3, sa[2] + 0.3, sa[3] + 0.3))
    for pref in ((36, 15), (36, 22), (6, 22)):
        fc.kit(fc.K.armchair_pair(), (-3, 9, 46, 30), pref, rot=0)
    for pref in ((40, 20), (12, 26)):
        fc.kit(fc.K.plant(), (pref[0] - 2, pref[1] - 2, pref[0] + 2, pref[1] + 2), pref, clear=0.2)
    fc.light_grid(spacing=4.0, size=0.6, holes=[C.CORE, HALL])


# ------------------------------------------------------------------ wine room
def wine_wall(fc, p0, p1, nrm, z0, z1, rng):
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 0.8:
        return
    u = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
    fu, dc, lit = fc.sink("millwork"), fc.sink("decor"), fc.sink("lights")

    def add(sink, mat, vf):
        sink.mesh(mat, *DT.map_wall(vf, p0, u, nrm))

    D = 0.36
    add(lit, "Light_Wine", ([(0.0, 0.03, z0 + 0.3), (L, 0.03, z0 + 0.3), (L, 0.03, z1), (0.0, 0.03, z1)],
                            [(0, 1, 2, 3)]))
    add(fu, "Walnut", P.cbox(0.0, 0.0, z0, L, D + 0.04, z0 + 0.3, 0.01))           # plinth/cabinet
    add(fu, "Walnut", P.cbox(-0.02, 0.0, z1, L + 0.02, D + 0.06, z1 + 0.12, 0.01))   # cornice
    add(lit, "Light_Cove", ([(0.0, D, z1 + 0.121), (L, D, z1 + 0.121), (L, 0.05, z1 + 0.121),
                             (0.0, 0.05, z1 + 0.121)], [(0, 1, 2, 3)]))
    ncol = max(1, int(round(L / 0.62)))
    cw = L / ncol
    rows = max(1, int(round((z1 - z0 - 0.3) / 0.42)))
    rh = (z1 - z0 - 0.3) / rows
    for i in range(ncol + 1):
        s = i * cw
        add(fu, "Walnut", P.box(s - 0.025, 0.0, z0 + 0.3, s + 0.025, D, z1))
    for j in range(rows + 1):
        z = z0 + 0.3 + j * rh
        add(fu, "Walnut", P.box(0.0, 0.0, z - 0.02, L, D, z + 0.02))
    bott = P.disc(0.0, 0.0, 0.0, 0.042, 6)
    for i in range(ncol):
        for j in range(rows):
            if rng.random() < 0.08:
                continue
            for a in range(3):
                for b in range(1):
                    s = i * cw + cw * (a + 0.5) / 3
                    z = z0 + 0.3 + j * rh + rh * 0.36
                    v, f = bott
                    v = [(s + x, D - 0.06, z + y) for x, y, _ in v]
                    f = [tuple(reversed(ff)) for ff in f]
                    add(dc, "Wine_Bottle", (v, f))


def wine_room(fc):
    Fz, zc = fc.Fz, fc.zc
    rng = random.Random(707)
    x0, y0, x1, y1 = 4.2, 10.4, 10.85, 19.85
    fc.wall((x0, y0 - 0.075), (x0, y1), mat="Walnut", th=0.15)
    fc.wall((x0, y0 - 0.075), (x1 + 0.15, y0 - 0.075), mat="Walnut", th=0.15)
    zt = Fz + 2.45
    wine_wall(fc, (x0 + 0.1, y0), (x1, y0), (0, 1), Fz, zt, rng)
    wine_wall(fc, (x1, y1), (x0 + 0.1, y1), (0, -1), Fz, zt, rng)
    wine_wall(fc, (x0 + 0.08, y1 - 0.4), (x0 + 0.08, y0 + 0.4), (1, 0), Fz, zt, rng)
    wine_wall(fc, (x1, y0 + 0.4), (x1, 17.6), (-1, 0), Fz, zt, rng)
    fc.block((x0, y0, x1, y0 + 0.5))
    fc.block((x0, y1 - 0.5, x1, y1))
    fc.block((x0, y0, x0 + 0.5, y1))
    fc.block((x1 - 0.5, y0, x1, 17.6))
    # walnut panelling above the racks
    tr = fc.sink("trim")
    for p0, p1, n in (((x0 + 0.08, y0 + 0.01), (x1, y0 + 0.01), (0, 1)), ((x1, y1 - 0.01), (x0 + 0.08, y1 - 0.01), (0, -1)),
                      ((x0 + 0.09, y1), (x0 + 0.09, y0), (1, 0)), ((x1 - 0.01, y0), (x1 - 0.01, y1), (-1, 0))):
        DT.panel_wall(tr, p0, p1, n, zt + 0.12, zc, panel="Walnut", trim=BRZ, base=None, rail_z=zc, fields=False,
                      module=0.8)
    # amber ceiling with a dark-wood diagrid (three directions, 1.9 m)
    cs = fc.sink("ceiling")
    cs.hface("Ceiling_Amber", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], zc - 0.003, up=False)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for ang in (90.0, 30.0, 150.0):
        a = math.radians(ang)
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        for k in range(-7, 8):
            off = k * 1.9
            px, py = cx + nx * off, cy + ny * off
            seg = _clip_line((px, py), (dx, dy), (x0 + 0.1, y0 + 0.1, x1 - 0.1, y1 - 0.1))
            if seg:
                (ax, ay), (bx, by) = seg
                cs.mesh("Walnut", *P.obeam((ax, ay, zc - 0.13), (bx, by, zc - 0.13), (nx, ny, 0.0), (0, 0, 1),
                                           0.14, 0.26))
    for p, q in (((x0, y0), (x1, y0)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)), ((x1, y0), (x1, y1))):
        cs.mesh("Walnut", *P.beam((p[0], p[1], zc - 0.15), (q[0], q[1], zc - 0.15), 0.3, 0.3))
    # round table, velvet chairs, candles, bottles
    fc.put(FU.rug(3.6, 3.6, "Rug_Border", "Fabric_Charcoal"), cx, cy, 45, block=False)
    fc.put(FU.round_table(0.95, "Walnut", chairs=6, chair_kw={"wood": "Walnut", "fab": "Fabric_Velvet_Green"}),
           cx, cy, 0)
    fc.put(FU.sideboard(2.0, rng=random.Random(2)), cx, y1 - 0.75, 180)
    fc.point_light("Wine_Table", (cx, cy, zc - 0.5), 60.0, "POINT", 0.2, color=(1.0, 0.75, 0.45))
    fc.point_light("Wine_Uplight", (cx, cy, Fz + 2.6), 120.0, "AREA", 5.0, color=(1.0, 0.7, 0.4),
                   rot=(math.pi, 0.0, 0.0))


def _clip_line(p, d, r):
    """Clip the infinite line p + t d to rect r -> (a, b) or None."""
    t0, t1 = -1e9, 1e9
    for k, (lo, hi) in enumerate(((r[0], r[2]), (r[1], r[3]))):
        if abs(d[k]) < 1e-9:
            if not lo <= p[k] <= hi:
                return None
            continue
        ta, tb = (lo - p[k]) / d[k], (hi - p[k]) / d[k]
        t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
    if t1 - t0 < 0.3:
        return None
    return (p[0] + d[0] * t0, p[1] + d[1] * t0), (p[0] + d[0] * t1, p[1] + d[1] * t1)
