"""Distant Manhattan out to the horizon (cheap LOD-0 massing).

Continues the street grid beyond the detailed scene so aerial views never
see the edge of the ground: plain building prisms on every block out to
~1.6 km, Central Park north of 59th St, the Hudson and East rivers, and a
large neutral ground plane beyond.  Everything here is collide=False.
"""
import math
import random

ROAD_Z = -0.15

# Avenue building-line pairs (x0, x1) west -> east (local frame, approx.)
AVES = [(-1985.0, -1955.0), (-1700.0, -1670.0), (-1365.0, -1335.0), (-1060.0, -1030.0),
        (-755.0, -725.0), (-445.0, -415.0), (-135.0, -105.0), (175.0, 205.0),
        (330.0, 354.0), (480.0, 510.0), (630.0, 660.0), (780.0, 810.0), (930.0, 960.0),
        (1080.0, 1110.0), (1230.0, 1260.0), (1380.0, 1410.0)]
STREET_PERIOD = 83.0          # 61 m block + 22 m street
STREET_W = 22.0
PARK = (-719.0, 504.0, 181.0, 4600.0)        # Central Park, curb to curb
HUDSON_X = -2050.0
EAST_RIVER_X = 1520.0


def _street_rows(y0, y1):
    """Blocks (south, north) between y0 and y1: block k spans k*83 .. k*83+61
    (53rd St's north building line is y = 0)."""
    out = []
    k = math.floor(y0 / STREET_PERIOD) - 1
    while k * STREET_PERIOD <= y1:
        b0 = k * STREET_PERIOD
        if b0 + 61.0 > y0:
            out.append((b0, b0 + 61.0))
        k += 1
    return out


def build(kit, center=(30.0, -8.0), filled=(), slabbed=()):
    """filled/slabbed: sets of (x0, y0) block keys already built by site.py."""
    rng = random.Random(5353)
    # ---- ground beyond the detailed asphalt square (ring of 4 quads)
    R0, R1 = 1200.0, 9000.0
    z = ROAD_Z - 0.02
    for (a0, b0, a1, b1) in ((-R1, -R1, R1, -R0), (-R1, R0, R1, R1), (-R1, -R0, -R0, R0), (R0, -R0, R1, R0)):
        kit.hquad("Ground_Distant", a0, b0, a1, b1, z, group="Distant")
    # ---- rivers
    kit.hquad("Water_Distant", -R1, -R1, HUDSON_X, R1, ROAD_Z + 0.02, group="Distant")
    kit.hquad("Water_Distant", EAST_RIVER_X, -R1, R1, R1, ROAD_Z + 0.02, group="Distant")
    # far shores (New Jersey / Queens) - low massing strips
    for x0, x1 in ((-R1 * 0.6, HUDSON_X - 1300.0), (EAST_RIVER_X + 650.0, R1 * 0.6)):
        y = -3000.0
        while y < 4000.0:
            w = rng.uniform(60, 200)
            h = rng.uniform(8, 40) if rng.random() < 0.85 else rng.uniform(60, 160)
            xa = rng.uniform(x0, x1 - 120)
            kit.box("Concrete_Distant", xa, y, ROAD_Z, xa + rng.uniform(40, 120), y + w, h,
                    group="Distant", collide=False)
            y += w + rng.uniform(20, 120)
    # ---- Central Park
    px0, py0, px1, py1 = PARK
    kit.hquad("Grass_Park", px0, py0, px1, py1, 0.0, group="Distant")
    kit.box("Limestone_Neighbor", px0, py0 - 0.4, 0.0, px1, py0, 0.9, group="Distant", collide=False)
    for _ in range(420):          # tree canopy clumps
        cx, cy = rng.uniform(px0 + 15, px1 - 15), rng.uniform(py0 + 15, min(py1, 2400.0))
        r = rng.uniform(6, 16)
        h = rng.uniform(9, 16)
        kit.cyl("Leaves", cx, cy, h * 0.35, h, r, r * 0.55, n=6, group="Distant", collide=False)
    kit.hquad("Water_Distant", -420.0, 1300.0, -60.0, 1700.0, 0.02, group="Distant")   # reservoir-ish
    # ---- city blocks between avenues
    for i in range(len(AVES) - 1):
        bx0, bx1 = AVES[i][1], AVES[i + 1][0]
        if bx1 > EAST_RIVER_X - 30 or bx0 < HUDSON_X + 30:
            continue
        for (by0, by1) in _street_rows(-1700.0, 3200.0):
            key = (round(bx0), round(by0))
            if key in filled:
                continue
            if bx1 > PARK[0] and bx0 < PARK[2] and by1 > PARK[1]:
                continue
            d = math.hypot((bx0 + bx1) / 2 - center[0], (by0 + by1) / 2 - center[1])
            if d > 3200:
                continue
            if key not in slabbed:
                kit.hquad("Sidewalk", bx0 - 5.0, by0 - 5.0, bx1 + 5.0, by1 + 5.0, 0.0,
                        group="Distant", collide=False)
            _fill(kit, rng, bx0, by0, bx1, by1, d)


MATS = ["Limestone_Neighbor", "Brick_Neighbor", "Stone_Light", "Brick_Light", "Glass_Neighbor",
        "Glass_Blue", "Concrete_Distant", "Limestone_Neighbor", "Glass_Neighbor"]


def _fill(kit, rng, bx0, by0, bx1, by1, d):
    """A few prisms per block; Midtown is tall, everything else mid-rise."""
    midtown = -1300 < by0 < 700 and -900 < bx0 < 1100
    big = (bx1 - bx0) > 200
    n_x = max(2, int((bx1 - bx0) / (rng.uniform(35, 60) if d < 1500 else 90)))
    xs = sorted([bx0, bx1] + [rng.uniform(bx0 + 10, bx1 - 10) for _ in range(n_x - 1)])
    for xa, xb in zip(xs, xs[1:]):
        if xb - xa < 8:
            continue
        for (ya, yb) in ((by0, by0 + 30.5), (by0 + 30.5, by1)) if d < 1800 else ((by0, by1),):
            if midtown:
                h = rng.uniform(25, 85) if rng.random() < 0.72 else rng.uniform(85, 230)
            else:
                h = rng.uniform(12, 45) if rng.random() < 0.85 else rng.uniform(45, 130)
            if big and rng.random() < 0.15:
                h *= 0.4
            m = rng.choice(MATS)
            x0, y0, x1, y1 = xa + 0.5, ya + 0.5, xb - 0.5, yb - 0.5
            if h > 100:
                # towers are slender: podium + shaft on part of the lot
                kit.box(m, x0, y0, 0.0, x1, y1, rng.uniform(18, 35), group="Distant", collide=False)
                w = min(x1 - x0, rng.uniform(24, 40))
                cx = rng.uniform(x0 + w / 2, x1 - w / 2)
                x0, x1 = cx - w / 2, cx + w / 2
                y0 = max(y0, ya + 4.0) if ya == by0 else y0
            kit.box(m, x0, y0, 0.0, x1, y1, h, group="Distant", collide=False)
            if h > 120 and rng.random() < 0.6:   # setback crown
                inset = min(x1 - x0, y1 - y0) * 0.22
                kit.box(m, x0 + inset, y0 + inset, h, x1 - inset, y1 - inset, h * rng.uniform(1.06, 1.18),
                        group="Distant", collide=False)
