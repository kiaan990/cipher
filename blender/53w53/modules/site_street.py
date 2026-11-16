"""Street-level props for the 53rd St scene: trees, NYC lamps, traffic
signals, vehicles, manholes, curb ramps and sidewalk joints.

All props go through the site Kit (material-merged builders), local shapes
are authored with length along local +x and placed with kit.part().
"""
import math
import random

from modules import site_kit as K

ROAD_Z = -0.15


# ================================================================== trees
def _blob(rng, level=0):
    """Low-poly leaf cluster: icosahedron with jittered radius."""
    v, f = K.ico_vf(level)
    out = []
    for p in v:
        r = rng.uniform(0.78, 1.12)
        out.append((p[0] * r, p[1] * r, p[2] * r))
    return out, f


def tree(kit, x, y, h=7.5, r=2.4, pit=True, seed=0.0, guard=False, lod=2):
    """Street tree (honey locust / London plane): slightly leaning tapered
    trunk forking into 3-4 limbs, each splitting into twigs; a loose,
    irregular crown made of many small leaf clusters (not one blob)."""
    rng = random.Random(int(seed * 1000) + int(x * 31 + y * 17))
    trunk_h = h * rng.uniform(0.30, 0.38)
    lean = (rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25))
    tx, ty = x + lean[0], y + lean[1]
    kit.cyl("Bark", x, y, 0.0, 0.25, 0.2, 0.16, n=6, group="Trees", collide=True)
    kit.beam("Bark", (x, y, 0.2), (tx, ty, trunk_h), 0.2, group="Trees", collide=True)
    nlimb = rng.choice((3, 4, 4)) if lod >= 2 else 3
    a0 = rng.uniform(0, 2 * math.pi)
    tips = []
    for k in range(nlimb):
        a = a0 + 2 * math.pi * k / nlimb + rng.uniform(-0.35, 0.35)
        reach = r * rng.uniform(0.35, 0.55)
        p0 = (tx, ty, trunk_h - 0.1)
        p1 = (tx + math.cos(a) * reach, ty + math.sin(a) * reach, trunk_h + h * rng.uniform(0.2, 0.3))
        kit.beam("Bark", p0, p1, 0.11, group="Trees", collide=False)
        nsub = 2 if lod >= 2 else 1
        for t in range(nsub):
            b = a + (t - 0.5) * 0.9 + rng.uniform(-0.25, 0.25)
            rr = r * rng.uniform(0.3, 0.45)
            p2 = (p1[0] + math.cos(b) * rr, p1[1] + math.sin(b) * rr, p1[2] + h * rng.uniform(0.1, 0.2))
            kit.beam("Bark", p1, p2, 0.055, group="Trees", collide=False)
            tips.append(p2)
        tips.append(p1)
    # leaf clusters: on every tip + random fill of the crown volume
    cc = (tx, ty, trunk_h + h * 0.33)
    pts = list(tips)
    nfill = 5 if lod >= 2 else 2
    for _ in range(nfill):
        a = rng.uniform(0, 2 * math.pi)
        d = r * rng.uniform(0.2, 0.75)
        pts.append((cc[0] + math.cos(a) * d, cc[1] + math.sin(a) * d, cc[2] + rng.uniform(-0.2, 0.35) * h))
    mb = kit.b("Leaves", "Trees", False)
    for (cx, cy, cz) in pts:
        v, f = _blob(rng)
        s = r * rng.uniform(0.3, 0.42)
        sz = s * rng.uniform(0.6, 0.78)
        rot = rng.uniform(0, math.pi)
        c, si = math.cos(rot), math.sin(rot)
        mb.extend([(cx + (p[0] * c - p[1] * si) * s, cy + (p[0] * si + p[1] * c) * s,
                    cz + 0.25 * sz + p[2] * sz) for p in v], f)
    if pit:
        kit.hquad("Soil", x - 0.75, y - 0.75, x + 0.75, y + 0.75, 0.005, group="Trees")
        if guard:   # low iron tree-pit guard
            g = 0.78
            for (ax, ay), (bx, by) in (((-g, -g), (g, -g)), ((g, -g), (g, g)), ((g, g), (-g, g)), ((-g, g), (-g, -g))):
                kit.beam("Metal_Dark", (x + ax, y + ay, 0.45), (x + bx, y + by, 0.45), 0.03,
                         group="Furn", collide=False)
            for (ax, ay) in ((-g, -g), (g, -g), (g, g), (-g, g)):
                kit.beam("Metal_Dark", (x + ax, y + ay, 0.0), (x + ax, y + ay, 0.47), 0.04,
                         group="Furn", collide=True)


# ================================================================== lamps
def street_lamp(kit, x, y, facing):
    """NYC 'cobra head' on an octagonal Type-M pole with a curved davit arm."""
    fx, fy = facing
    kit.cyl("Lamp_Grey", x, y, 0.0, 0.7, 0.21, 0.19, n=8)         # base flange
    kit.cyl("Lamp_Grey", x, y, 0.7, 1.2, 0.17, 0.13, n=8)          # base collar
    kit.cyl("Lamp_Grey", x, y, 1.2, 8.0, 0.11, 0.075, n=8)         # tapered shaft
    # davit arm: three segments curving out over the roadway
    pts = [(0.0, 7.9), (0.35, 8.55), (1.1, 8.95), (2.6, 9.1)]
    P = [(x + fx * d, y + fy * d, z) for d, z in pts]
    for a, b in zip(P, P[1:]):
        kit.beam("Lamp_Grey", a, b, 0.08, group="Furn", collide=False)
    # cobra-head luminaire (local x along the arm)
    rot = math.atan2(fy, fx)
    prof = [(0.0, -0.02), (0.85, -0.10), (1.0, 0.0), (0.9, 0.12), (0.2, 0.16), (-0.05, 0.08)]
    head = K.xz_prism_vf(prof, -0.22, 0.22)
    kit.part("Lamp_Grey", *head, (P[-1][0], P[-1][1], 9.0), rot, collide=False)
    lens = K.xz_prism_vf([(0.08, -0.06), (0.8, -0.13), (0.8, -0.10), (0.08, -0.03)], -0.16, 0.16)
    kit.part("Light_Emit", *lens, (P[-1][0], P[-1][1], 9.0), rot, collide=False)


# ================================================================== signals
def _signal_head(kit, x, y, z, rot, n=3):
    """Yellow NYC signal head (3 lenses) facing local -x."""
    body = K.box_vf(-0.15, -0.17, 0.0, 0.15, 0.17, 0.34 * n + 0.06)
    kit.part("Signal_Yellow", *body, (x, y, z), rot, collide=False)
    for k, m in enumerate(("Signal_Lens_Green", "Signal_Black", "Signal_Lens_Red")[:n]):
        cz = 0.2 + k * 0.34
        lens = K.box_vf(-0.17, -0.12, cz - 0.12, -0.15, 0.12, cz + 0.12)
        kit.part(m, *lens, (x, y, z), rot, collide=False)
        visor = K.box_vf(-0.42, -0.14, cz + 0.12, -0.15, 0.14, cz + 0.15)
        kit.part("Signal_Yellow", *visor, (x, y, z), rot, collide=False)


def traffic_signal(kit, x, y, arm_dir, arm_len=6.5, face=None):
    """Pole + mast arm over the roadway carrying two signal heads, plus a
    pedestrian head on the pole.  arm_dir: unit (dx, dy) over the road;
    signals face `face` (unit vector toward oncoming traffic)."""
    dx, dy = arm_dir
    kit.cyl("Lamp_Grey", x, y, 0.0, 0.6, 0.2, 0.18, n=8)
    kit.cyl("Lamp_Grey", x, y, 0.6, 6.6, 0.13, 0.11, n=8)
    kit.beam("Lamp_Grey", (x, y, 6.2), (x + dx * arm_len, y + dy * arm_len, 6.3), 0.1,
             group="Furn", collide=False)
    kit.beam("Lamp_Grey", (x, y, 5.4), (x + dx * 2.0, y + dy * 2.0, 6.2), 0.06,
             group="Furn", collide=False)
    fx, fy = face if face else (-dy, dx)
    rot = math.atan2(-fy, -fx)     # local -x faces traffic
    for d in (arm_len * 0.55, arm_len * 0.95):
        _signal_head(kit, x + dx * d, y + dy * d, 5.15, rot)
    # pedestrian signal box on the pole
    ped = K.box_vf(-0.2, -0.2, 2.6, 0.2, 0.2, 3.05)
    kit.part("Signal_Yellow", *ped, (x, y, 0.0), rot, collide=False)
    # street name blade
    kit.beam("Road_Green_Sign", (x, y, 6.75), (x + dx * 1.2, y + dy * 1.2, 6.75), 0.04, 0.3,
             group="Furn", collide=False)


# ================================================================== vehicles
def _wheels(kit, xs, half_w, r, loc, rot, tw=0.24):
    for wx in xs:
        for side in (-1, 1):
            y0 = side * half_w
            y1 = side * (half_w - tw)
            v, f = K.wheel_vf(wx, min(y0, y1), max(y0, y1), r, r, n=12)
            kit.part("Tire_Black", v, f, loc, rot, collide=False)
            yr = side * (half_w + 0.004)
            v, f = K.wheel_vf(wx, min(yr, side * half_w), max(yr, side * half_w), r * 0.62, r, n=10)
            kit.part("Wheel_Rim", v, f, loc, rot, collide=False)


def vehicle(kit, kind, x, y, rot, paint=None):
    """kind: sedan | taxi | suv | van | bus.  Local +x = forward."""
    loc = (x, y, ROAD_Z)
    if kind == "bus":
        _bus(kit, loc, rot)
        return
    spec = {
        # L, W, wheel r, wheelbase half, body profile (x/L, z), cabin (x/L, z)
        "sedan": (4.85, 1.84, 0.33, 1.42,
                  [(-0.5, 0.28), (0.5, 0.28), (0.505, 0.52), (0.48, 0.74), (0.24, 0.86), (-0.32, 0.92),
                   (-0.49, 0.86), (-0.51, 0.55)],
                  [(0.22, 0.86), (-0.31, 0.92), (-0.21, 1.40), (0.05, 1.42)]),
        "suv": (4.9, 1.95, 0.37, 1.45,
                [(-0.5, 0.36), (0.5, 0.36), (0.505, 0.68), (0.47, 0.98), (0.27, 1.06), (-0.5, 1.08),
                 (-0.51, 0.70)],
                [(0.26, 1.06), (-0.49, 1.08), (-0.46, 1.76), (0.06, 1.78)]),
        "van": (4.4, 1.70, 0.31, 1.32,   # Nissan NV200 'Taxi of Tomorrow'
                [(-0.5, 0.30), (0.5, 0.30), (0.5, 0.58), (0.46, 0.84), (0.33, 0.95), (-0.5, 0.97),
                 (-0.5, 0.58)],
                [(0.32, 0.95), (-0.49, 0.97), (-0.49, 1.80), (0.14, 1.82)]),
    }
    k2 = "sedan" if kind == "taxi" else kind
    L, W, r, wb, body, cab = spec[k2]
    if paint is None:
        paint = "Car_Paint_Yellow" if kind in ("taxi", "van") else "Car_Paint_Silver"
    bp = [(px * L, pz) for px, pz in body]
    kit.part(paint, *K.xz_prism_vf(bp, -W / 2, W / 2), loc, rot, collide=True)
    cp = [(px * L, pz) for px, pz in cab]
    kit.part("Car_Glass", *K.xz_prism_vf(cp, -W / 2 + 0.1, W / 2 - 0.1), loc, rot, collide=False)
    # roof skin + pillars in body colour
    top = max(pz for _, pz in cab)
    xs = sorted(px * L for px, pz in cab if pz > top - 0.05)
    kit.part(paint, *K.box_vf(xs[0] - 0.05, -W / 2 + 0.12, top - 0.02, xs[-1] + 0.05, W / 2 - 0.12, top + 0.04),
             loc, rot, collide=False)
    lo = [(px * L, pz) for px, pz in cab if pz < top - 0.2]
    for side in (-1, 1):
        yv = side * (W / 2 - 0.095)
        for (bx, bz) in lo:
            tx = min(xs, key=lambda t: abs(t - bx))
            kit.part(paint, *_strut(bx, bz, tx, top, yv), loc, rot, collide=False)
    # lights + grille + mirrors
    fx = max(px for px, _ in bp)
    rx = min(px for px, _ in bp)
    zl = 0.68 if k2 == "sedan" else (0.82 if k2 == "suv" else 0.72)
    for s in (-1, 1):
        kit.part("Car_Lights_Front", *K.box_vf(fx - 0.06, s * W * 0.32 - 0.16, zl - 0.05, fx + 0.01,
                                               s * W * 0.32 + 0.16, zl + 0.05), loc, rot, collide=False)
        kit.part("Car_Lights_Rear", *K.box_vf(rx - 0.01, s * W * 0.36 - 0.14, zl, rx + 0.05,
                                              s * W * 0.36 + 0.14, zl + 0.1), loc, rot, collide=False)
        kit.part(paint, *K.box_vf(0.2 * L - 0.1, s * (W / 2 + 0.12) - 0.07, 0.95, 0.2 * L + 0.05,
                                  s * (W / 2 + 0.12) + 0.07, 1.08), loc, rot, collide=False)
    kit.part("Signal_Black", *K.box_vf(fx - 0.04, -W * 0.22, 0.38, fx + 0.02, W * 0.22, 0.56),
             loc, rot, collide=False)
    if kind in ("taxi", "van"):
        kit.part("Road_Marking", *K.box_vf(-0.3 if k2 == "van" else -0.6, -0.32, top + 0.04,
                                           0.0 if k2 == "van" else -0.3, 0.32, top + 0.28),
                 loc, rot, collide=False)          # roof medallion light
        kit.part("Signal_Black", *K.box_vf(-0.6 * L / 2, -W / 2 - 0.004, 0.62, 0.45 * L / 2, W / 2 + 0.004, 0.66),
                 loc, rot, collide=False)          # checker / stripe band
    _wheels(kit, (-wb, wb), W / 2 + 0.01, r, loc, rot)


def _strut(x0, z0, x1, z1, y, w=0.07):
    """Slanted window pillar (A/B/C post) as a thin parallelogram slab."""
    return K.xz_prism_vf([(x0 - w, z0), (x0 + w, z0), (x1 + w, z1), (x1 - w, z1)], y - 0.03, y + 0.03)


def _bus(kit, loc, rot):
    """MTA 40-ft low-floor bus (12.2 x 2.6 x 3.2 m): white with blue band."""
    L, W, H = 12.2, 2.59, 3.15
    prof = [(-L / 2, 0.30), (L / 2, 0.30), (L / 2 + 0.05, 1.0), (L / 2, H - 0.1), (L / 2 - 0.2, H),
            (-L / 2 + 0.15, H), (-L / 2, H - 0.15)]
    kit.part("Bus_White", *K.xz_prism_vf(prof, -W / 2, W / 2), loc, rot, collide=True)
    # window band + windscreen + blue livery stripe (just proud of the body)
    for s in (-1, 1):
        y0, y1 = (s * W / 2, s * (W / 2 + 0.02))
        ya, yb = min(y0, y1), max(y0, y1)
        kit.part("Car_Glass", *K.box_vf(-L / 2 + 0.6, ya, 1.55, L / 2 - 1.2, yb, 2.75), loc, rot, collide=False)
        kit.part("Bus_Blue", *K.box_vf(-L / 2 + 0.1, ya, 1.05, L / 2 - 0.05, yb, 1.35), loc, rot, collide=False)
    kit.part("Car_Glass", *K.box_vf(L / 2, -W / 2 + 0.12, 1.1, L / 2 + 0.06, W / 2 - 0.12, H - 0.25),
             loc, rot, collide=False)
    kit.part("Signal_Black", *K.box_vf(L / 2 - 0.05, -0.8, H - 0.45, L / 2 + 0.08, 0.8, H - 0.2),
             loc, rot, collide=False)   # destination sign
    kit.part("Roof_Grey", *K.box_vf(-2.5, -0.9, H, 1.5, 0.9, H + 0.35), loc, rot, collide=False)  # HVAC pod
    for s in (-1, 1):
        kit.part("Car_Lights_Rear", *K.box_vf(-L / 2 - 0.02, s * 1.05 - 0.12, 0.9, -L / 2 + 0.02,
                                              s * 1.05 + 0.12, 1.4), loc, rot, collide=False)
    _wheels(kit, (-L / 2 + 2.6, L / 2 - 2.45), W / 2 + 0.01, 0.5, loc, rot, tw=0.3)


# ================================================================== street
def manhole(kit, x, y):
    kit.cyl("Manhole_Iron", x, y, ROAD_Z, ROAD_Z + 0.012, 0.42, 0.42, n=12, group="Street",
            collide=False)


def curb_ramp_ns(kit, x, y_curb, toward, w=2.4):
    """Curb ramp at a crosswalk on an E-W street. y_curb: curb line, toward:
    +1 if the sidewalk is at larger y.  Sloped apron + yellow tactile pad."""
    d = 1.5
    ys, ye = y_curb, y_curb + toward * d
    z_lo, z_hi = ROAD_Z + 0.012, 0.012
    a, b = x - w / 2, x + w / 2
    if toward > 0:
        kit.quad("Sidewalk", (a, ys, z_lo), (b, ys, z_lo), (b, ye, z_hi), (a, ye, z_hi), group="Street")
        kit.quad("Tactile_Yellow", (a + 0.1, ys + 0.02, z_lo + 0.006), (b - 0.1, ys + 0.02, z_lo + 0.006),
                 (b - 0.1, ys + 0.62, z_lo + 0.006 + 0.62 / d * 0.15),
                 (a + 0.1, ys + 0.62, z_lo + 0.006 + 0.62 / d * 0.15), group="Street")
    else:
        kit.quad("Sidewalk", (a, ye, z_hi), (b, ye, z_hi), (b, ys, z_lo), (a, ys, z_lo), group="Street")
        kit.quad("Tactile_Yellow", (a + 0.1, ys - 0.62, z_lo + 0.006 + 0.62 / d * 0.15),
                 (b - 0.1, ys - 0.62, z_lo + 0.006 + 0.62 / d * 0.15),
                 (b - 0.1, ys - 0.02, z_lo + 0.006), (a + 0.1, ys - 0.02, z_lo + 0.006), group="Street")
    # flared side wings
    for xx, sgn in ((a, -1), (b, 1)):
        kit.quad("Sidewalk", (xx, ys, z_lo), (xx, ye, z_hi), (xx + sgn * 0.6, ye, z_hi),
                 (xx + sgn * 0.6, ys, z_hi), group="Street") if toward > 0 else \
            kit.quad("Sidewalk", (xx, ye, z_hi), (xx, ys, z_lo), (xx + sgn * 0.6, ys, z_hi),
                     (xx + sgn * 0.6, ye, z_hi), group="Street")


def sidewalk_joints(kit, x0, x1, y_bldg, y_curb, pitch=1.52):
    """Scored joints on a concrete sidewalk running E-W (5-ft flags)."""
    lo, hi = min(y_bldg, y_curb), max(y_bldg, y_curb)
    z = 0.004
    x = x0
    while x <= x1:
        kit.hquad("Sidewalk_Joint", x - 0.012, lo + 0.35, x + 0.012, hi - 0.35, z, group="Street")
        x += pitch
    y = lo + 0.35 + pitch
    while y < hi - 0.4:
        kit.hquad("Sidewalk_Joint", x0, y - 0.012, x1, y + 0.012, z, group="Street")
        y += pitch
