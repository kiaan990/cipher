"""Site: Midtown Manhattan context around 53 West 53.

Street grid (metres, +X east along W 53rd St, +Y north, ground z = 0):
  W 53rd St   building lines y = -22 .. 0, curbs y = -6 / -16 (roadway z = -0.15)
  6th Ave     building lines x = -135 .. -105, curbs x = -129 / -111
  5th Ave     building lines x = 175 .. 205,   curbs x = 181 / 199
  Blocks are 61 m deep, streets 22 m wide (6 m sidewalks), so W 54th St is
  y = 61 .. 83 and W 52nd St is y = -105 .. -83.
Sidewalks/lots are flush at z = 0 (the lobby level); roadways sit at -0.15
behind a 0.3 m granite curb.  The tower footprint (C.FOOTPRINT) is left
empty with 0.5 m clearance (0 m along its 53rd St street wall).
"""
import math
import random
import bpy
import config as C
from modules import site_kit as K
from modules import site_buildings as SB
from modules import site_street as ST
from modules import site_city as CITY

FILLED = set()      # block keys (x0, y0) built here (site_city skips them)

ROAD_Z = -0.15
SIDEWALK = 6.0
CURB_W = 0.3

# avenues: (name, west building line, east building line, sidewalk width, lanes)
AVENUES = [
    ("7th", -445.0, -415.0, 6.0, 5),
    ("6th", -135.0, -105.0, 6.0, 5),
    ("5th", 175.0, 205.0, 6.0, 5),
    ("Madison", 330.0, 354.0, 5.0, 4),
    ("Park", 480.0, 510.0, 6.0, 5),
]
# streets: (name, south building line, north building line)
STREETS = [
    ("W 50th", -271.0, -249.0), ("W 51st", -188.0, -166.0), ("W 52nd", -105.0, -83.0),
    ("W 53rd", -22.0, 0.0), ("W 54th", 61.0, 83.0), ("W 55th", 144.0, 166.0),
    ("W 56th", 227.0, 249.0),
]
COLS = [(AVENUES[i][2], AVENUES[i + 1][1]) for i in range(len(AVENUES) - 1)]
ROWS = [(-332.0, -271.0)] + [(STREETS[i][2], STREETS[i + 1][1]) for i in range(len(STREETS) - 1)] + [(249.0, 310.0)]

CENTER = (30.0, -8.0)        # middle of the 53rd St scene, for level of detail
RADIUS = 430.0
TOWER_BLOCK = (-105.0, 0.0, 175.0, 61.0)
SOUTH_BLOCK = (-105.0, -83.0, 175.0, -22.0)


def _dist(x, y):
    return math.hypot(x - CENTER[0], y - CENTER[1])


# ======================================================================= ground
def _rect_slab(kit, x0, y0, x1, y1):
    kit.box("Sidewalk", x0, y0, ROAD_Z - 0.01, x1, y1, 0.0, group="Ground", bottom=False)


def block_slab(kit, bx0, by0, bx1, by1, hole=None):
    """Sidewalk ring + lot surface for one block, with a granite curb.
    hole = (x0, y0, x1, y1) rectangle left open (filled by tower_pad)."""
    swx0 = _side_w(bx0, "W")
    swx1 = _side_w(bx1, "E")
    ox0, oy0, ox1, oy1 = bx0 - swx0, by0 - SIDEWALK, bx1 + swx1, by1 + SIDEWALK
    ix0, iy0, ix1, iy1 = ox0 + CURB_W, oy0 + CURB_W, ox1 - CURB_W, oy1 - CURB_W
    # curb ring
    for r in ((ox0, oy0, ox1, iy0), (ox0, iy1, ox1, oy1), (ox0, iy0, ix0, iy1), (ix1, iy0, ox1, iy1)):
        kit.box("Curb_Granite", r[0], r[1], ROAD_Z - 0.01, r[2], r[3], 0.0, group="Ground")
    if hole is None:
        _rect_slab(kit, ix0, iy0, ix1, iy1)
    else:
        hx0, hy0, hx1, hy1 = hole
        _rect_slab(kit, ix0, iy0, hx0, iy1)
        _rect_slab(kit, hx1, iy0, ix1, iy1)
        _rect_slab(kit, hx0, iy0, hx1, hy0)
        _rect_slab(kit, hx0, hy1, hx1, iy1)


def _side_w(x, side):
    for name, a0, a1, sw, _ in AVENUES:
        if side == "W" and abs(a1 - x) < 0.1:
            return sw
        if side == "E" and abs(a0 - x) < 0.1:
            return sw
    return SIDEWALK


def _line_isect(l1, l2):
    (n1, c1), (n2, c2) = l1, l2
    det = n1[0] * n2[1] - n1[1] * n2[0]
    return ((c1 * n2[1] - c2 * n1[1]) / det, (n1[0] * c2 - n2[0] * c1) / det)


def _ray_hit(poly, c, d):
    best = None
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        den = d[0] * ey - d[1] * ex
        if abs(den) < 1e-12:
            continue
        wx, wy = a[0] - c[0], a[1] - c[1]
        t = (wx * ey - wy * ex) / den
        u = (wx * d[1] - wy * d[0]) / den
        if t > 1e-9 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
            best = t
    return (c[0] + d[0] * best, c[1] + d[1] * best)


def tower_pad(kit, hole):
    """Ground (z = 0) between the hole rectangle and the tower footprint grown
    by 0.5 m (0 m on the 53rd St wall), so nothing touches the footprint."""
    fp = C.FOOTPRINT
    n = len(fp)
    lines = []
    for i in range(n):
        a, b = fp[i], fp[(i + 1) % n]
        (nx, ny), L = K.edge_normal(a, b)
        off = 0.0 if abs(a[1]) < 1e-6 and abs(b[1]) < 1e-6 else 0.5
        lines.append(((nx, ny), nx * a[0] + ny * a[1] + off))
    grown = [_line_isect(lines[i - 1], lines[i]) for i in range(n)]
    hx0, hy0, hx1, hy1 = hole
    outer = [(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)]
    c = C.centroid(fp)
    angs = sorted({math.atan2(p[1] - c[1], p[0] - c[0]) for p in grown + outer})
    mb = kit.b("Sidewalk", "Ground", True)
    for k in range(len(angs)):
        a0, a1 = angs[k], angs[(k + 1) % len(angs)]
        d0, d1 = (math.cos(a0), math.sin(a0)), (math.cos(a1), math.sin(a1))
        i0, o0 = _ray_hit(grown, c, d0), _ray_hit(outer, c, d0)
        i1, o1 = _ray_hit(grown, c, d1), _ray_hit(outer, c, d1)
        pts = [i0, o0, o1, i1]
        area = 0.5 * sum(pts[j][0] * pts[(j + 1) % 4][1] - pts[(j + 1) % 4][0] * pts[j][1] for j in range(4))
        if area < 1e-4:
            continue
        mb.add_quad(*[(p[0], p[1], 0.0) for p in pts])
    # skirt down to road level along the grown outline (except the street wall)
    for i in range(n):
        a, b = grown[i], grown[(i + 1) % n]
        if abs(a[1]) < 1e-6 and abs(b[1]) < 1e-6:
            continue
        mb.add_quad((b[0], b[1], ROAD_Z), (a[0], a[1], ROAD_Z), (a[0], a[1], 0.0), (b[0], b[1], 0.0))
    return grown


def ground(kit):
    kit.hquad("Asphalt", -1200.0, -1200.0, 1200.0, 1200.0, ROAD_Z, group="Ground", collide=True)
    hole = (-4.0, 0.0, 47.0, 31.0)
    for (cx0, cx1) in COLS:
        for (ry0, ry1) in ROWS:
            if (cx0, ry0, cx1, ry1) == TOWER_BLOCK:
                block_slab(kit, cx0, ry0, cx1, ry1, hole=hole)
            else:
                block_slab(kit, cx0, ry0, cx1, ry1)
    tower_pad(kit, hole)


# ======================================================================= markings
MZ = ROAD_Z + 0.008


def _dashes_y(kit, x, y0, y1, w=0.13, dash=3.0, gap=6.0):
    y = y0
    while y + dash <= y1:
        kit.hquad("Road_Marking", x - w / 2, y, x + w / 2, y + dash, MZ)
        y += dash + gap


def _dashes_x(kit, y, x0, x1, w=0.13, dash=3.0, gap=6.0, mat="Road_Marking"):
    x = x0
    while x + dash <= x1:
        kit.hquad(mat, x, y - w / 2, x + dash, y + w / 2, MZ)
        x += dash + gap


def _zebra_across_street(kit, xc, ry0, ry1):
    """Ladder crosswalk crossing an E-W roadway (ry0..ry1) centred on x=xc."""
    y = ry0 + 0.4
    while y + 0.6 <= ry1 - 0.3:
        kit.hquad("Road_Marking", xc - 2.0, y, xc + 2.0, y + 0.6, MZ)
        y += 1.2


def _zebra_across_avenue(kit, yc, rx0, rx1):
    x = rx0 + 0.4
    while x + 0.6 <= rx1 - 0.3:
        kit.hquad("Road_Marking", x, yc - 2.0, x + 0.6, yc + 2.0, MZ)
        x += 1.2


def markings(kit):
    lim_x = (-420.0, 485.0)
    lim_y = (-330.0, 305.0)
    for sname, sy0, sy1 in STREETS:
        ry0, ry1 = sy0 + SIDEWALK, sy1 - SIDEWALK
        for (cx0, cx1) in COLS:
            if _dist((cx0 + cx1) / 2, sy0) > RADIUS + 200:
                continue
            # crosswalks in the line of the avenue sidewalks
            _zebra_across_street(kit, cx0 - 3.0, ry0, ry1)
            _zebra_across_street(kit, cx1 + 3.0, ry0, ry1)
            kit.hquad("Road_Marking", cx0 + 5.5, ry0 + 0.2, cx0 + 6.0, ry1 - 0.2, MZ)   # stop bar (one-way)
            kit.hquad("Road_Marking", cx1 - 6.0, ry0 + 0.2, cx1 - 5.5, ry1 - 0.2, MZ)
            _dashes_x(kit, (ry0 + ry1) / 2, cx0 + 9.0, cx1 - 9.0)
            # parking lane edges
            _dashes_x(kit, ry0 + 2.5, cx0 + 9.0, cx1 - 9.0, w=0.1, dash=6.0, gap=1.0)
            _dashes_x(kit, ry1 - 2.5, cx0 + 9.0, cx1 - 9.0, w=0.1, dash=6.0, gap=1.0)
    for aname, ax0, ax1, sw, lanes in AVENUES:
        if ax1 < lim_x[0] or ax0 > lim_x[1]:
            continue
        rx0, rx1 = ax0 + sw, ax1 - sw
        lw = (rx1 - rx0) / lanes
        for (ry0b, ry1b) in ROWS:
            if _dist((ax0 + ax1) / 2, (ry0b + ry1b) / 2) > RADIUS + 200:
                continue
            _zebra_across_avenue(kit, ry0b - 3.0, rx0, rx1)
            _zebra_across_avenue(kit, ry1b + 3.0, rx0, rx1)
            for k in range(1, lanes):
                _dashes_y(kit, rx0 + k * lw, ry0b + 8.0, ry1b - 8.0)
            # bus lane / curbside lane solid lines
            kit.hquad("Road_Marking", rx0 + 3.2, ry0b + 6.0, rx0 + 3.35, ry1b - 6.0, MZ)
            kit.hquad("Road_Yellow", rx1 - 0.35, ry0b + 6.0, rx1 - 0.2, ry1b - 6.0, MZ)
            kit.hquad("Road_Marking", rx0 + 0.2, ry0b + 5.5, rx1 - 0.2, ry0b + 6.0, MZ)


# ======================================================================= blocks
NEIGH_MATS = [("Brick_Neighbor", 3), ("Limestone_Neighbor", 3), ("Stone_Light", 2), ("Brick_Light", 2)]
GLASS_MATS = ["Glass_Neighbor", "Glass_Blue", "Glass_Green"]


def _pick(rng, items):
    tot = sum(w for _, w in items)
    r = rng.uniform(0, tot)
    for it, w in items:
        r -= w
        if r <= 0:
            return it
    return items[-1][0]


def _lod(x, y):
    d = _dist(x, y)
    return 2 if d < 160 else (1 if d < 280 else 0)


def lot_building(kit, rng, poly, h, street_edges, tall_glass=0.6):
    cx, cy = C.centroid(poly)
    det = _lod(cx, cy) if _dist(cx, cy) <= RADIUS else 0
    if h > 85 and rng.random() < tall_glass:
        m = rng.choice(GLASS_MATS)
        win = rng.choice(["Window_Dark", "Alu_Panel", "Granite_Black"])
        K.building(kit, poly, h, m, win=win, style="glass", floor_h=rng.uniform(3.8, 4.2),
                   ground_h=6.0, detail=det, street_edges=street_edges)
    else:
        m = _pick(rng, NEIGH_MATS)
        K.building(kit, poly, h, m, floor_h=rng.uniform(3.1, 3.6), ground_h=4.6, detail=det,
                   pier_pitch=rng.uniform(2.4, 3.6), pier_w=rng.uniform(0.6, 1.1),
                   street_edges=street_edges)


def fill_row(kit, rng, xa, xb, yf, facing, dmin, dmax, hmin, hmax, tall_p=0.1, wmin=8.0, wmax=28.0,
             open_w=False, open_e=False):
    """Row of lots along an E-W street between xa and xb. facing 'S' puts the
    street on the south side of the lots (front line y=yf)."""
    x = xa
    while x < xb - 4.0:
        w = min(rng.uniform(wmin, wmax), xb - x)
        if xb - (x + w) < wmin * 0.6:
            w = xb - x
        d = rng.uniform(dmin, dmax)
        h = rng.uniform(hmin, hmax)
        if rng.random() < tall_p:
            h = rng.uniform(hmax, hmax * 2.5)
        if facing == "S":
            poly, e = K.rect(x, yf, x + w, yf + d), [0]
        else:
            poly, e = K.rect(x, yf - d, x + w, yf), [2]
        if open_w and x == xa:
            e.append(3)            # side facing an open plaza / gap
        if open_e and x + w >= xb - 1e-6:
            e.append(1)
        lot_building(kit, rng, poly, h, e)
        x += w


def fill_col(kit, rng, ya, yb, xf, facing, dmin, dmax, hmin, hmax, wmin=18.0, wmax=40.0):
    """Lots along an avenue between ya and yb; facing 'W' = avenue on west."""
    y = ya
    while y < yb - 4.0:
        w = min(rng.uniform(wmin, wmax), yb - y)
        if yb - (y + w) < wmin * 0.6:
            w = yb - y
        d = rng.uniform(dmin, dmax)
        h = rng.uniform(hmin, hmax)
        if facing == "W":
            poly = K.rect(xf, y, xf + d, y + w)
            e = [3] + ([0] if y == ya else []) + ([2] if y + w >= yb else [])
        else:
            poly = K.rect(xf - d, y, xf, y + w)
            e = [1] + ([0] if y == ya else []) + ([2] if y + w >= yb else [])
        lot_building(kit, rng, poly, h, e, tall_glass=0.7)
        y += w


def fill_block(kit, bx0, by0, bx1, by1, skip=()):
    rng = random.Random(int(bx0 * 7 + by0 * 13))
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    if _dist(cx, cy) > RADIUS + 60:
        return
    FILLED.add((round(bx0), round(by0)))
    ew = rng.uniform(26.0, 40.0)
    ee = rng.uniform(26.0, 40.0)
    if bx1 - bx0 < 140:
        ew = ee = rng.uniform(22.0, 30.0)
    if "W" not in skip:
        fill_col(kit, rng, by0, by1, bx0, "W", ew * 0.85, ew, 40.0, 160.0)
    if "E" not in skip:
        fill_col(kit, rng, by0, by1, bx1, "E", ee * 0.85, ee, 40.0, 160.0)
    if "S" not in skip:
        fill_row(kit, rng, bx0 + ew, bx1 - ee, by0, "S", 20.0, 29.0, 15.0, 55.0, tall_p=0.12)
    if "N" not in skip:
        fill_row(kit, rng, bx0 + ew, bx1 - ee, by1, "N", 20.0, 29.0, 15.0, 55.0, tall_p=0.12)


def context_blocks(kit):
    for (cx0, cx1) in COLS:
        for (ry0, ry1) in ROWS:
            blk = (cx0, ry0, cx1, ry1)
            if blk in (TOWER_BLOCK, SOUTH_BLOCK):
                continue
            if blk == (-415.0, 0.0, -135.0, 61.0):        # Hilton
                fill_block(kit, *blk, skip=("E",))
            elif blk == (-415.0, -83.0, -135.0, -22.0):   # 1301 6th Ave
                fill_block(kit, *blk, skip=("E",))
            elif blk == (-415.0, 83.0, -135.0, 144.0):    # 1345 6th Ave
                fill_block(kit, *blk, skip=("E",))
            else:
                fill_block(kit, *blk)


def main_blocks(kit):
    rng = random.Random(53)
    # --- north side of 53rd St (the tower's block)
    SB.tower_neighbours(kit)
    SB.moma(kit)
    SB.st_thomas(kit)
    K.building(kit, K.rect(135.0, 33.0, 175.0, 61.0), 42.0, "Limestone_Neighbor", floor_h=4.6,
               ground_h=6.0, pier_pitch=3.4, pier_w=1.4, street_edges=[1, 2])      # University Club
    # 54th St brownstones / mid-rise behind the tower
    fill_row(kit, rng, -80.0, 46.5, 61.0, "N", 15.0, 19.0, 13.0, 24.0, tall_p=0.12, wmin=6.0, wmax=14.0)
    # --- south side of 53rd St
    SB.cbs(kit)
    # pocket plaza opposite the tower (keeps the view up to the spire open)
    fill_row(kit, rng, -55.0, -48.0, -22.0, "N", 20.0, 28.0, 22.0, 60.0, tall_p=0.0, wmin=7.0, wmax=7.0,
             open_e=True)
    fill_row(kit, rng, -6.0, 70.0, -22.0, "N", 20.0, 28.0, 22.0, 75.0, tall_p=0.2, wmin=10.0, wmax=24.0,
             open_w=True)
    K.building(kit, K.rect(-48.0, -83.0, -6.0, -58.0), 112.0, "Glass_Green", win="Alu_Panel",
               style="glass", floor_h=4.0, ground_h=7.0, street_edges=[0, 2])
    for x, y in ((-42.0, -30.0), (-30.0, -36.0), (-17.0, -29.0), (-12.0, -44.0), (-46.0, -52.0)):
        SB.tree(kit, x, y, h=7.0, r=2.4, seed=x)
    for x0 in (-44.0, -26.0, -14.0):
        kit.box("Stone_Light", x0, -40.5, 0.0, x0 + 5.0, -39.5, 0.45, group="Furn")   # benches
    SB.baccarat(kit)
    fill_row(kit, rng, 100.0, 127.0, -22.0, "N", 20.0, 28.0, 30.0, 60.0, tall_p=0.0, wmin=12.0, wmax=16.0)
    fill_row(kit, rng, -6.0, 127.0, -83.0, "S", 18.0, 26.0, 18.0, 70.0, tall_p=0.2, wmin=10.0, wmax=26.0)
    SB.six66(kit)
    # --- across the avenues
    SB.hilton(kit)
    SB.sixth_ave_towers(kit)


# ======================================================================= furniture
def street_lamp(kit, x, y, facing):
    ST.street_lamp(kit, x, y, facing)


def bollard(kit, x, y):
    kit.cyl("Metal_Dark", x, y, 0.0, 0.95, 0.13, 0.12, n=8)


def hydrant(kit, x, y):
    kit.cyl("Hydrant_Red", x, y, 0.0, 0.62, 0.14, 0.14, n=8)
    kit.cyl("Hydrant_Red", x, y, 0.62, 0.82, 0.17, 0.05, n=8)
    kit.beam("Hydrant_Red", (x - 0.26, y, 0.42), (x + 0.26, y, 0.42), 0.09)
    kit.beam("Hydrant_Red", (x, y - 0.24, 0.42), (x, y, 0.42), 0.11)


def taxi(kit, x, y, rot, kind="taxi", paint=None):
    ST.vehicle(kit, kind, x, y, rot, paint)


def kiosk(kit, x0, y0, x1, y1):
    kit.box("Kiosk_Green", x0, y0, 0.0, x1, y1, 2.6, group="Furn")
    kit.box("Kiosk_Green", x0 - 0.3, y0 - 0.3, 2.6, x1 + 0.3, y1 + 0.3, 2.8, group="Furn")


def furniture(kit):
    north_y, south_y = -4.9, -17.1
    lamps_n = [-92.0, -58.0, -24.0, 36.0, 66.0, 96.0, 128.0, 162.0]
    lamps_s = [-78.0, -44.0, -10.0, 22.0, 52.0, 84.0, 116.0, 150.0]
    for x in lamps_n:
        street_lamp(kit, x, -5.55, (0, -1))
    for x in lamps_s:
        street_lamp(kit, x, -16.45, (0, 1))
    entrance_clear = (12.0, 30.0)     # keep the tower's forecourt open
    moma_entry = (99.0, 119.0)

    def ok(x, lamps, zones):
        if any(abs(x - lx) < 3.0 for lx in lamps):
            return False
        return not any(a <= x <= b for a, b in zones)
    x = -97.0
    k = 0
    while x < 172.0:
        if ok(x, lamps_n, [entrance_clear, moma_entry, (4.0, 10.0), (138.0, 176.0)]):
            ST.tree(kit, x, north_y, h=7.4 + (k % 3) * 0.6, r=2.3, seed=k, guard=True)
        if ok(x, lamps_s, [(-100.0, -52.0), (56.0, 62.0)]):
            ST.tree(kit, x, south_y, h=7.8 - (k % 2) * 0.7, r=2.4, seed=k + 3, guard=True)
        x += 9.5
        k += 1
    # trees on the far sides of 54th / 52nd St and along the avenues (sparser)
    for x in range(-90, 170, 13):
        ST.tree(kit, x + 0.5, 65.9, h=7.0, r=2.2, seed=x, lod=1)
        ST.tree(kit, x + 4.0, -87.9, h=7.0, r=2.2, seed=x + 1, lod=1)
    # bollards at the MoMA entrance and Goodwin-Stone marquee
    bx = moma_entry[0] + 1.0
    while bx <= moma_entry[1] - 1.0:
        bollard(kit, bx, -5.35)
        bx += 1.7
    for bx in (-60.0, -58.0, -56.0):
        bollard(kit, bx, -21.0)
    hydrant(kit, 6.0, -5.35)
    hydrant(kit, 58.0, -16.65)
    hydrant(kit, -100.0, -5.4)
    kiosk(kit, -110.4, 7.0, -108.8, 10.5)     # newsstand, 6th Ave NE of 53rd
    vehicles(kit)
    street_details(kit)


def vehicles(kit):
    """W 53rd St is one-way EASTBOUND (+x); 6th Ave runs north (+y), 5th Ave
    south (-y).  Parking lane along the south curb, travel lanes north of it."""
    E, N, S = 0.0, math.pi / 2, -math.pi / 2
    # parked along the south curb (y ~ -14.9), avoiding hydrant / crosswalks
    parked = [(-88.0, "suv", "Car_Paint_Black"), (-82.0, "sedan", "Car_Paint_Silver"),
              (-68.0, "sedan", "Car_Paint_White"), (-30.0, "suv", "Car_Paint_Blue"),
              (-23.5, "sedan", "Car_Paint_Black"), (36.0, "suv", "Car_Paint_Black"),
              (42.5, "suv", "Car_Paint_Black"), (76.0, "sedan", "Car_Paint_Red"),
              (82.5, "sedan", "Car_Paint_Silver"), (124.0, "suv", "Car_Paint_White"),
              (150.0, "van", None)]
    for x, kind, paint in parked:
        taxi(kit, x, -14.85, E, kind, paint)
    # moving traffic, eastbound
    taxi(kit, -48.0, -11.9, E, "taxi")
    taxi(kit, 8.0, -9.1, E, "taxi")                 # passing the tower entrance
    taxi(kit, 15.0, -11.9, E, "sedan", "Car_Paint_Black")
    taxi(kit, 62.0, -9.1, E, "van")
    taxi(kit, 104.0, -11.9, E, "taxi")
    taxi(kit, 158.0, -9.1, E, "suv", "Car_Paint_Silver")
    # black livery car waiting at the tower canopy (north curb, y ~ -7)
    taxi(kit, 26.5, -7.05, E, "suv", "Car_Paint_Black")
    # 6th Ave northbound, 5th Ave southbound (buses in the curb lane)
    taxi(kit, -125.5, -40.0, N, "bus")
    taxi(kit, -119.0, -52.0, N, "taxi")
    taxi(kit, -115.0, 22.0, N, "taxi")
    taxi(kit, -122.0, 40.0, N, "sedan", "Car_Paint_Silver")
    taxi(kit, -115.0, -95.0, N, "van")
    taxi(kit, 184.5, 40.0, S, "bus")
    taxi(kit, 191.0, 18.0, S, "taxi")
    taxi(kit, 195.0, -55.0, S, "suv", "Car_Paint_Black")
    taxi(kit, 188.0, -70.0, S, "taxi")


def street_details(kit):
    # traffic signals at the four corners of 53rd St & 6th / 5th Ave
    for ax0, ax1 in ((-135.0, -105.0), (175.0, 205.0)):
        cw, ce = ax0 + 6.0, ax1 - 6.0          # avenue curbs
        # NE + SW corners: mast arms over the avenue; NW + SE: over 53rd St
        ST.traffic_signal(kit, ce + 0.5, -5.5, (-1.0, 0.0), arm_len=8.0)
        ST.traffic_signal(kit, cw - 0.5, -16.5, (1.0, 0.0), arm_len=8.0)
        ST.traffic_signal(kit, cw - 0.5, -5.5, (0.0, -1.0), arm_len=6.0)
        ST.traffic_signal(kit, ce + 0.5, -16.5, (0.0, 1.0), arm_len=6.0)
        # curb ramps at the 53rd St crosswalks (both sides)
        for x in (ax0 - 3.0, ax1 + 3.0):
            ST.curb_ramp_ns(kit, x, -6.0, 1)
            ST.curb_ramp_ns(kit, x, -16.0, -1)
    # manholes / utility covers on 53rd St and the avenues
    for x in (-95.0, -61.0, -27.0, 4.0, 33.0, 71.0, 109.0, 147.0):
        ST.manhole(kit, x, -11.0 + (1.6 if int(x) % 2 else -0.8))
    for y in (-60.0, -35.0, 20.0, 45.0):
        ST.manhole(kit, -120.0, y)
        ST.manhole(kit, 190.0, y)
    # scored sidewalk joints along 53rd St (both sides) - the hero frontage
    ST.sidewalk_joints(kit, -104.0, 174.0, 0.0, -6.0)
    ST.sidewalk_joints(kit, -104.0, 174.0, -22.0, -16.0)


# ======================================================================= world
SKY = (0.68, 0.74, 0.80, 1.0)


def world(scene):
    w = scene.world or bpy.data.worlds.new("World")
    scene.world = w
    w.color = SKY[:3]
    try:
        w.use_nodes = True
        bg = w.node_tree.nodes.get("Background")
        if bg:
            bg.inputs[0].default_value = SKY
            bg.inputs[1].default_value = 1.0
    except Exception:
        pass


def build(ctx):
    FILLED.clear()
    col = C.collection("Site")
    kit = K.Kit(col)
    ground(kit)
    markings(kit)
    main_blocks(kit)
    context_blocks(kit)
    furniture(kit)
    for blk in (TOWER_BLOCK, SOUTH_BLOCK):
        FILLED.add((round(blk[0]), round(blk[1])))
    slabbed = {(round(cx0), round(ry0)) for (cx0, cx1) in COLS for (ry0, ry1) in ROWS}
    CITY.build(kit, CENTER, filled=FILLED, slabbed=slabbed)
    objs = kit.finish()
    world(bpy.context.scene)
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
    print(f"[site] {len(objs)} objects, ~{tris} triangles")
    ctx["site"] = {"objects": [o.name for o in objs], "tris": tris,
                   "curb_north_y": -6.0, "curb_south_y": -16.0, "road_z": ROAD_Z,
                   "moma_west_x": 46.51}
