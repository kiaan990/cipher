"""High-detail furniture kits for the showcase interiors.

A Kit holds local geometry (origin = centre of its footprint, z = 0 = floor,
'front' facing +y) as (category, material, (verts, faces), smooth) parts.
Categories: 'furn' (collidable) and 'decor' (not collidable).
Kits unpack as (w, d, kit) so interiors_geom.Planner can place them, and
FloorCtx.kit()/put() emit them with kit.emit(). Optional kit.lights are
(local xyz, energy W, kind, size, colour) - turned into real lights only on
showcase floors.

Dimensions follow real furniture: sofa seat 0.45-0.47 m, back 0.85 m,
dining table 0.75 m, chairs seat 0.46 m, beds 0.6 m mattress top, etc.
Edges are bevelled (chamfered boxes) and upholstery uses rounded pillows.
"""
import math
import random

from modules import interiors_prims as P

F, D = "furn", "decor"

# material names (the materials pass upgrades these by name)
OAKC, OAKD, NOIR, STAT = "Oak_Cerused", "Oak_Dark_Floor", "Marble_Noir_StLaurent", "Marble_Statuary"
BRZ, ALAB, GOLD, LIME = "Bronze_Trim", "Alabaster", "Gold_Leaf", "Limestone_Verona"
WAL, LEATH, LINEN, VELV = "Walnut", "Leather_Cognac", "Fabric_Linen", "Fabric_Velvet_Green"
LACW, LACB = "Lacquer_White", "Lacquer_Black"
LEAF, LEAF2 = "Foliage", "Foliage_Light"

FURN_MATS = {
    "Oak_Cerused": (0.78, 0.74, 0.66, 1), "Oak_Dark_Floor": (0.16, 0.10, 0.065, 1),
    "Marble_Noir_StLaurent": (0.035, 0.035, 0.04, 1), "Marble_Statuary": (0.92, 0.91, 0.89, 1),
    "Bronze_Trim": (0.42, 0.28, 0.14, 1), "Alabaster": (0.93, 0.88, 0.78, 1),
    "Gold_Leaf": (0.83, 0.64, 0.28, 1), "Limestone_Verona": (0.80, 0.74, 0.62, 1),
    "Green_Wall": (0.12, 0.30, 0.08, 1), "Walnut": (0.22, 0.13, 0.08, 1),
    "Leather_Cognac": (0.42, 0.20, 0.08, 1), "Fabric_Linen": (0.80, 0.76, 0.68, 1),
    "Fabric_Velvet_Green": (0.08, 0.20, 0.14, 1),
    "Lacquer_White": (0.90, 0.90, 0.88, 1), "Lacquer_Black": (0.02, 0.02, 0.022, 1),
    "Fabric_Cream": (0.86, 0.82, 0.74, 1), "Fabric_Charcoal": (0.16, 0.16, 0.17, 1),
    "Fabric_Blush": (0.78, 0.50, 0.46, 1), "Fabric_Navy": (0.08, 0.11, 0.22, 1),
    "Fabric_Sand": (0.70, 0.60, 0.46, 1), "Fabric_Rust": (0.55, 0.24, 0.12, 1),
    "Rug_Wool": (0.62, 0.58, 0.52, 1), "Rug_Border": (0.30, 0.26, 0.22, 1),
    "Rug_Sisal": (0.66, 0.56, 0.40, 1), "Sheepskin": (0.93, 0.92, 0.88, 1),
    "Lamp_Shade": (0.95, 0.90, 0.80, 1), "Ceramic_Glaze": (0.82, 0.80, 0.74, 1),
    "Ceramic_Dark": (0.12, 0.12, 0.12, 1), "Pot_Stone": (0.42, 0.40, 0.37, 1),
    "Soil": (0.08, 0.06, 0.05, 1), "Foliage": (0.10, 0.25, 0.08, 1), "Foliage_Light": (0.22, 0.40, 0.12, 1),
    "Foliage_Dark": (0.04, 0.14, 0.05, 1), "Foliage_Yellow": (0.45, 0.50, 0.12, 1),
    "Foliage_Red": (0.35, 0.10, 0.08, 1), "Ceiling_Amber": (0.62, 0.42, 0.22, 1),
    "Bark": (0.25, 0.20, 0.15, 1), "Flower_White": (0.95, 0.94, 0.90, 1), "Flower_Pink": (0.90, 0.55, 0.62, 1),
    "Steel_Brushed": (0.62, 0.62, 0.62, 1), "Glass_Black": (0.01, 0.01, 0.012, 1),
    "Piano_Keys": (0.93, 0.92, 0.88, 1), "Fruit_Red": (0.70, 0.08, 0.05, 1), "Fruit_Lemon": (0.90, 0.75, 0.15, 1),
    "Book_Red": (0.55, 0.12, 0.10, 1), "Book_Blue": (0.12, 0.20, 0.42, 1),
    "Book_Ochre": (0.70, 0.52, 0.18, 1), "Book_Green": (0.16, 0.32, 0.20, 1),
    "Book_Cream": (0.85, 0.80, 0.68, 1), "Book_Black": (0.05, 0.05, 0.05, 1),
    "Book_Tan": (0.58, 0.42, 0.28, 1), "Book_Grey": (0.45, 0.45, 0.46, 1),
    "Wine_Bottle": (0.03, 0.06, 0.03, 1), "Candle_Wax": (0.95, 0.93, 0.86, 1),
}
BOOKS = ["Book_Red", "Book_Blue", "Book_Ochre", "Book_Green", "Book_Cream", "Book_Black", "Book_Tan",
         "Book_Grey", "Book_Cream", "Book_Black"]


class Kit:
    def __init__(self, w, d):
        self.w, self.d = w, d
        self.parts = []
        self.lights = []

    def __iter__(self):
        return iter((self.w, self.d, self))

    def add(self, cat, mat, vf, smooth=False):
        self.parts.append((cat, mat, vf, smooth))
        return self

    def cb(self, cat, mat, x0, y0, z0, x1, y1, z1, b=0.01):
        return self.add(cat, mat, P.cbox(x0, y0, z0, x1, y1, z1, b))

    def bx(self, cat, mat, x0, y0, z0, x1, y1, z1, bottom=False):
        return self.add(cat, mat, P.box(x0, y0, z0, x1, y1, z1, bottom))

    def rb(self, cat, mat, x0, y0, z0, x1, y1, z1, e=0.3, rx=0.0, rz=0.0, ry=0.0, sag=0.0, nu=12, nv=7,
           pivot=None):
        vf = P.rbox(x0, y0, z0, x1, y1, z1, e, nu, nv, sag)
        if rx or rz or ry:
            pv = pivot or ((x0 + x1) / 2, (y0 + y1) / 2, min(z0, z1))
            vf = P.xf(vf, rz=rz, rx=rx, ry=ry, pivot=pv)
        return self.add(cat, mat, vf, smooth=True)

    def lathe(self, cat, mat, prof, seg=16, x=0.0, y=0.0, smooth=True, **kw):
        return self.add(cat, mat, P.lathe(prof, seg, x, y, **kw), smooth)

    def sub(self, kit, x=0.0, y=0.0, ang=0.0, z=0.0):
        a = math.radians(ang)
        for cat, mat, vf, sm in kit.parts:
            self.parts.append((cat, mat, P.xf(vf, rz=a, t=(x, y, z)), sm))
        for (lx, ly, lz), e, k, s, c in kit.lights:
            ca, sa = math.cos(a), math.sin(a)
            self.lights.append(((x + lx * ca - ly * sa, y + lx * sa + ly * ca, z + lz), e, k, s, c))
        return self

    def light(self, xyz, energy=30.0, kind="POINT", size=0.1, color=(1.0, 0.82, 0.62)):
        self.lights.append((xyz, energy, kind, size, color))

    def emit(self, sinks, cx, cy, z, ang_deg):
        a = math.radians(ang_deg)
        for cat, mat, vf, sm in self.parts:
            v, f = P.xf(vf, rz=a, t=(cx, cy, z))
            sinks[cat].mesh(mat, v, f, smooth=sm)

    def world_lights(self, cx, cy, z, ang_deg):
        a = math.radians(ang_deg)
        ca, sa = math.cos(a), math.sin(a)
        return [((cx + x * ca - y * sa, cy + x * sa + y * ca, z + zz), e, k, s, c)
                for (x, y, zz), e, k, s, c in self.lights]

    def tris(self):
        return sum(P.tris(vf) for _, _, vf, _ in self.parts)


def _legs(k, mat, x0, y0, x1, y1, h, s=0.045, inset=0.06, taper=True):
    for x, y in ((x0 + inset, y0 + inset), (x1 - inset, y0 + inset), (x1 - inset, y1 - inset),
                 (x0 + inset, y1 - inset)):
        if taper:
            k.add(F, mat, P.lathe([(s * 0.35, 0.0), (s * 0.5, h)], 6, x, y), smooth=False)
        else:
            k.cb(F, mat, x - s / 2, y - s / 2, 0.0, x + s / 2, y + s / 2, h, 0.004)


# ------------------------------------------------------------------ seating
def sofa(w=2.6, fab="Fabric_Linen", leg=WAL, seats=3, pillows=("Fabric_Rust", "Fabric_Sand"), d=0.98):
    k = Kit(w, d)
    hw, hd = w / 2, d / 2
    _legs(k, leg, -hw, -hd, hw, hd, 0.1, 0.05, 0.08, taper=False)
    k.cb(F, fab, -hw + 0.02, -hd + 0.02, 0.1, hw - 0.02, hd - 0.02, 0.3, 0.02)
    for s in (-1, 1):
        x0 = s * hw
        k.rb(F, fab, x0 - s * 0.2, -hd, 0.1, x0, hd, 0.62, e=0.22)
    k.rb(F, fab, -hw + 0.1, -hd, 0.22, hw - 0.1, -hd + 0.22, 0.8, e=0.22)
    inner = w - 0.4
    cw = inner / seats
    for i in range(seats):
        x = -hw + 0.2 + i * cw
        k.rb(D, fab, x + 0.005, -hd + 0.18, 0.28, x + cw - 0.005, hd - 0.0, 0.47, e=0.2, sag=0.012)
        k.rb(D, fab, x + 0.01, -hd + 0.12, 0.44, x + cw - 0.01, -hd + 0.34, 0.88, e=0.3, rx=0.16)
    for i, s in enumerate((-1, 1)):
        if not pillows:
            break
        x = s * (hw - 0.45)
        k.rb(D, pillows[i % len(pillows)], x - 0.22, -hd + 0.33, 0.45, x + 0.22, -hd + 0.47, 0.88,
             e=0.35, rx=0.3, rz=-s * 0.25)
    return k


def armchair(fab=LEATH, leg=WAL, w=0.86, d=0.9, back=0.82):
    k = Kit(w, d)
    hw, hd = w / 2, d / 2
    _legs(k, leg, -hw, -hd, hw, hd, 0.1, 0.045, 0.07)
    k.rb(F, fab, -hw + 0.02, -hd + 0.02, 0.1, hw - 0.02, hd - 0.02, 0.36, e=0.2)
    for s in (-1, 1):
        k.rb(F, fab, s * hw - s * 0.16, -hd, 0.1, s * hw, hd - 0.02, 0.62, e=0.25)
    k.rb(F, fab, -hw + 0.04, -hd, 0.2, hw - 0.04, -hd + 0.2, back, e=0.25)
    k.rb(D, fab, -hw + 0.16, -hd + 0.16, 0.33, hw - 0.16, hd - 0.03, 0.46, e=0.2, sag=0.01)
    k.rb(D, fab, -hw + 0.17, -hd + 0.12, 0.42, hw - 0.17, -hd + 0.3, back - 0.04, e=0.3, rx=0.15)
    return k


def lounge_chair(fab="Fabric_Blush", leg=BRZ):
    """Curved-back modern lounge chair (no arms), cf. the apartment renders."""
    k = Kit(0.82, 0.86)
    k.lathe(F, leg, [(0.02, 0.0), (0.24, 0.0), (0.24, 0.015), (0.03, 0.03), (0.03, 0.2), (0.0, 0.2)], 16)
    k.rb(F, fab, -0.38, -0.36, 0.2, 0.38, 0.4, 0.44, e=0.3, sag=0.015)
    seg = 7
    for i in range(seg):
        a0 = math.pi * (1.1 + 0.8 * i / seg)
        a1 = math.pi * (1.1 + 0.8 * (i + 1) / seg)
        am = (a0 + a1) / 2
        r = 0.36
        x, y = r * math.cos(am), r * math.sin(am) + 0.02
        hgt = 0.95 - 0.25 * abs(i - (seg - 1) / 2) / ((seg - 1) / 2)
        wseg = r * (a1 - a0) + 0.04
        part = P.rbox(-wseg / 2, -0.07, 0.3, wseg / 2, 0.07, hgt, 0.35, 10, 6)
        part = P.xf(part, rx=0.12, pivot=(0, 0, 0.3))
        part = P.xf(part, rz=am + math.pi / 2, t=(x, y, 0))
        k.add(F, fab, part, smooth=True)
    return k


def dining_chair(wood=WAL, fab="Fabric_Sand"):
    k = Kit(0.5, 0.52)
    for x, y in ((-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2)):
        top = (x * 0.95, y * 0.95, 0.44)
        bot = (x * 1.05, y * 1.05 + (0.02 if y < 0 else 0.0), 0.0)
        k.add(D, wood, P.beam(bot, top, 0.032))
    k.cb(D, wood, -0.23, -0.23, 0.4, 0.23, 0.23, 0.44, 0.008)
    k.rb(D, fab, -0.225, -0.21, 0.42, 0.225, 0.235, 0.48, e=0.25)
    for x in (-0.2, 0.2):
        k.add(D, wood, P.beam((x, -0.21, 0.44), (x * 0.98, -0.27, 0.86), 0.028))
    back = P.rbox(-0.23, -0.035, 0.0, 0.23, 0.035, 0.26, 0.3, 10, 6)
    k.add(D, fab, P.xf(back, rx=0.14, t=(0, -0.25, 0.58)), smooth=True)
    return k


def bench(w=2.0, top=LEATH, leg=BRZ):
    k = Kit(w, 0.5)
    k.rb(F, top, -w / 2, -0.23, 0.36, w / 2, 0.23, 0.46, e=0.18, sag=0.01)
    for s in (-1, 1):
        x = s * (w / 2 - 0.12)
        k.cb(F, leg, x - 0.02, -0.2, 0.0, x + 0.02, 0.2, 0.37, 0.005)
        k.cb(F, leg, x - 0.02, -0.2, 0.0, x + 0.02, 0.2, 0.37, 0.005)
    k.cb(F, leg, -w / 2 + 0.12, -0.01, 0.06, w / 2 - 0.12, 0.01, 0.09, 0.003)
    return k


# ------------------------------------------------------------------ tables
def coffee_round(r=0.55, top=STAT, base=BRZ, h=0.4):
    k = Kit(2 * r, 2 * r)
    k.lathe(F, base, [(r * 0.5, 0.0), (r * 0.5, 0.02), (r * 0.42, 0.04), (r * 0.42, h - 0.04), (0.0, h - 0.04)],
            24, cap0=True)
    k.lathe(F, top, [(0.0, h - 0.04), (r - 0.01, h - 0.04), (r, h - 0.03), (r, h - 0.005), (r - 0.005, h),
                     (0.0, h)], 32)
    return k


def coffee_rect(w=1.4, d=0.8, top=WAL, leg=BRZ, h=0.38):
    k = Kit(w, d)
    k.cb(F, top, -w / 2, -d / 2, h - 0.05, w / 2, d / 2, h, 0.01)
    k.cb(F, top, -w / 2 + 0.08, -d / 2 + 0.08, 0.06, w / 2 - 0.08, d / 2 - 0.08, 0.09, 0.005)
    _legs(k, leg, -w / 2, -d / 2, w / 2, d / 2, h - 0.05, 0.035, 0.06, taper=False)
    _tabletop_decor(k, 0.0, 0.0, h, random.Random(int(w * 100)))
    return k


def _tabletop_decor(k, x, y, z, rng):
    """Book stack + bowl / small vase on a table top."""
    zz = z
    for i in range(rng.randint(2, 3)):
        bw, bd = rng.uniform(0.22, 0.3), rng.uniform(0.28, 0.34)
        k.cb(D, rng.choice(BOOKS), x - 0.3 - bw / 2, y - bd / 2, zz, x - 0.3 + bw / 2, y + bd / 2, zz + 0.035,
             0.003)
        zz += 0.035
    k.lathe(D, "Ceramic_Glaze", [(0.0, z), (0.06, z), (0.12, z + 0.05), (0.13, z + 0.07), (0.12, z + 0.07),
                                 (0.05, z + 0.02), (0.0, z + 0.02)], 16, x + 0.25, y)


def side_table(top=NOIR, base=BRZ, h=0.55, r=0.24):
    k = Kit(2 * r, 2 * r)
    k.lathe(F, base, [(0.14, 0.0), (0.14, 0.015), (0.02, 0.03), (0.018, h - 0.03), (0.0, h - 0.03)], 12)
    k.lathe(F, top, [(0.0, h - 0.03), (r, h - 0.03), (r, h - 0.004), (r - 0.004, h), (0.0, h)], 24)
    return k


def dining_table(L=2.4, W=1.0, top=WAL, chairs=3, ends=True, chair_kw=None, centre=True):
    chair_kw = chair_kw or {}
    k = Kit(L + (1.3 if ends else 0.4), W + 1.3)
    h = 0.75
    k.cb(F, top, -L / 2, -W / 2, h - 0.045, L / 2, W / 2, h, 0.008)
    for s in (-1, 1):                         # trestle legs
        x = s * (L / 2 - 0.35)
        k.cb(F, top, x - 0.04, -W / 2 + 0.12, 0.0, x + 0.04, W / 2 - 0.12, 0.05, 0.006)
        k.cb(F, top, x - 0.03, -0.06, 0.05, x + 0.03, 0.06, h - 0.045, 0.006)
    k.cb(F, top, -L / 2 + 0.38, -0.03, h - 0.12, L / 2 - 0.38, 0.03, h - 0.045, 0.004)
    ch = dining_chair(**chair_kw)
    for i in range(chairs):
        x = -L / 2 + L * (i + 0.5) / chairs
        k.sub(ch, x, -W / 2 - 0.15, 0)
        k.sub(ch, x, W / 2 + 0.15, 180)
    if ends:
        k.sub(ch, -L / 2 - 0.2, 0, -90)
        k.sub(ch, L / 2 + 0.2, 0, 90)
    if centre:
        k.sub(vase_flowers(0.5, random.Random(int(L * 10))), 0, 0, 0, z=h)
    return k


def round_table(r=0.8, top=WAL, chairs=6, chair_kw=None, candles=True):
    chair_kw = chair_kw or {}
    k = Kit(2 * r + 1.2, 2 * r + 1.2)
    h = 0.75
    k.lathe(F, top, [(0.45, 0.0), (0.45, 0.03), (0.16, 0.08), (0.12, h - 0.15), (0.3, h - 0.05), (0.0, h - 0.05)],
            24)
    k.lathe(F, top, [(0.0, h - 0.05), (r - 0.015, h - 0.05), (r, h - 0.035), (r, h - 0.01), (r - 0.01, h),
                     (0.0, h)], 40)
    ch = dining_chair(**chair_kw)
    for i in range(chairs):
        a = 2 * math.pi * i / chairs
        x, y = (r + 0.12) * math.cos(a), (r + 0.12) * math.sin(a)
        k.sub(ch, x, y, math.degrees(a) + 90)
    if candles:
        for i, (cx, cy) in enumerate(((-0.1, 0.05), (0.08, -0.04), (0.02, 0.12))):
            k.lathe(D, BRZ, [(0.04, h), (0.04, h + 0.01), (0.012, h + 0.03), (0.012, h + 0.22 + 0.04 * i),
                             (0.025, h + 0.23 + 0.04 * i), (0.0, h + 0.23 + 0.04 * i)], 10, cx, cy)
            zc = h + 0.23 + 0.04 * i
            k.lathe(D, "Candle_Wax", [(0.0, zc), (0.011, zc), (0.011, zc + 0.12), (0.0, zc + 0.12)], 8, cx, cy)
            k.add(D, "Fire_Glow", P.rbox(cx - 0.007, cy - 0.007, zc + 0.125, cx + 0.007, cy + 0.007, zc + 0.16,
                                          0.8, 6, 4), smooth=True)
        for j, (bx, by) in enumerate(((0.3, 0.1), (-0.32, -0.15), (0.12, -0.35))):
            k.lathe(D, "Wine_Bottle", [(0.0, h), (0.037, h), (0.037, h + 0.2), (0.015, h + 0.25),
                                       (0.014, h + 0.31), (0.0, h + 0.31)], 10, bx, by)
            k.lathe(D, "Glass_Partition", [(0.0, h), (0.035, h), (0.006, h + 0.01), (0.006, h + 0.1),
                                           (0.04, h + 0.15), (0.045, h + 0.21)], 10, bx * 1.8, by * 1.8 + 0.1,
                    cap1=False)
    return k


# ------------------------------------------------------------------ lamps / decor
def floor_lamp(h=1.62, shade="Lamp_Shade", metal=BRZ, light=True):
    k = Kit(0.45, 0.45)
    k.lathe(D, metal, [(0.17, 0.0), (0.17, 0.015), (0.15, 0.025), (0.0, 0.025)], 20)
    k.add(D, metal, P.cyl(0, 0, 0.02, h - 0.25, 0.012, 8, False, False), smooth=True)
    k.lathe(D, shade, [(0.21, h - 0.32), (0.16, h)], 24, cap0=False, cap1=False, smooth=True)
    k.add(D, "Light_Emit", P.rbox(-0.035, -0.035, h - 0.24, 0.035, 0.035, h - 0.15, 0.7, 8, 5), smooth=True)
    if light:
        k.light((0, 0, h - 0.18), 25.0, "POINT", 0.08)
    return k


def table_lamp(z, shade="Lamp_Shade", base="Ceramic_Glaze", h=0.62):
    k = Kit(0.4, 0.4)
    k.lathe(D, base, [(0.0, z), (0.07, z), (0.11, z + 0.08), (0.12, z + 0.17), (0.08, z + 0.3), (0.025, z + 0.34),
                      (0.025, z + 0.37), (0.0, z + 0.37)], 16)
    k.add(D, BRZ, P.cyl(0, 0, z + 0.37, z + h - 0.12, 0.008, 6, False, False))
    k.lathe(D, shade, [(0.19, z + h - 0.24), (0.15, z + h)], 20, cap0=False, cap1=False)
    k.add(D, "Light_Emit", P.rbox(-0.03, -0.03, z + h - 0.18, 0.03, 0.03, z + h - 0.1, 0.7, 8, 5), smooth=True)
    return k


def rug(w, d, mat="Rug_Wool", border="Rug_Border", bw=0.18):
    k = Kit(w, d)
    k.cb(D, border, -w / 2, -d / 2, 0.0, w / 2, d / 2, 0.012, 0.004)
    if border:
        k.bx(D, mat, -w / 2 + bw, -d / 2 + bw, 0.0, w / 2 - bw, d / 2 - bw, 0.0135)
    return k


def vase_flowers(h=0.55, rng=None, vase="Ceramic_Glaze", bloom="Flower_White"):
    rng = rng or random.Random(5)
    k = Kit(0.5, 0.5)
    k.lathe(D, vase, [(0.0, 0.0), (0.07, 0.0), (0.11, 0.06), (0.12, 0.16), (0.07, 0.26), (0.06, 0.3),
                      (0.075, 0.32)], 16, cap1=False)
    for i in range(9):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.08, 0.22)
        top = (r * math.cos(a), r * math.sin(a), h + rng.uniform(-0.12, 0.15))
        k.add(D, LEAF, P.beam((0.0, 0.0, 0.25), top, 0.008))
        s = rng.uniform(0.04, 0.07)
        k.add(D, bloom, P.rbox(top[0] - s, top[1] - s, top[2] - s * 0.6, top[0] + s, top[1] + s, top[2] + s * 0.6,
                               0.7, 8, 5), smooth=True)
        for j in range(2):
            b = rng.uniform(0, 2 * math.pi)
            mid = tuple(top[q] * 0.6 + (0, 0, 0.25)[q] * 0.4 for q in range(3))
            k.add(D, LEAF, P.leaf(mid, (math.cos(b), math.sin(b), 0.3), 0.12, 0.05, 0.4))
    return k


def plant(kind="fig", h=1.8, rng=None, pot="Pot_Stone"):
    """Potted plant with real leaves. kind: fig | olive | palm | bush."""
    rng = rng or random.Random(hash(kind) & 0xffff)
    pr = 0.26 if h > 1.2 else 0.17
    ph = pr * 1.6
    k = Kit(2 * pr + 0.5, 2 * pr + 0.5)
    k.lathe(F, pot, [(0.0, 0.0), (pr * 0.82, 0.0), (pr, ph * 0.15), (pr, ph), (pr - 0.02, ph), (pr - 0.02,
                                                                                               ph - 0.04)], 20)
    k.add(D, "Soil", P.disc(0, 0, ph - 0.04, pr - 0.02, 20))
    mats = (LEAF, LEAF2)
    if kind == "fig":
        for s in range(3):
            a = 2 * math.pi * s / 3 + rng.uniform(-0.3, 0.3)
            top = (0.12 * math.cos(a), 0.12 * math.sin(a), h * rng.uniform(0.85, 1.0))
            k.add(D, "Bark", P.beam((0.0, 0.0, ph - 0.04), top, 0.025))
            for i in range(14):
                t = rng.uniform(0.35, 1.0)
                base = (top[0] * t, top[1] * t, ph + (top[2] - ph) * t)
                b = rng.uniform(0, 2 * math.pi)
                k.add(D, mats[i % 2], P.leaf(base, (math.cos(b), math.sin(b), rng.uniform(0.0, 0.6)),
                                             rng.uniform(0.22, 0.32), rng.uniform(0.15, 0.2), 0.25,
                                             rng.uniform(-0.4, 0.4)))
    elif kind == "olive":
        trunk_top = (0.0, 0.0, h * 0.55)
        k.add(D, "Bark", P.beam((0.0, 0.0, ph - 0.04), trunk_top, 0.05))
        for s in range(5):
            a = 2 * math.pi * s / 5 + rng.uniform(-0.3, 0.3)
            tip = (0.4 * math.cos(a), 0.4 * math.sin(a), h * rng.uniform(0.8, 1.0))
            k.add(D, "Bark", P.beam(trunk_top, tip, 0.025))
            for i in range(40):
                t = rng.uniform(0.2, 1.1)
                c = tuple(trunk_top[q] + (tip[q] - trunk_top[q]) * t for q in range(3))
                c = (c[0] + rng.uniform(-0.18, 0.18), c[1] + rng.uniform(-0.18, 0.18), c[2] + rng.uniform(-0.15, 0.15))
                b = rng.uniform(0, 2 * math.pi)
                k.add(D, mats[i % 2], P.leaf(c, (math.cos(b), math.sin(b), rng.uniform(-0.3, 0.5)), 0.09, 0.025,
                                             0.1, rng.uniform(-1, 1)))
    elif kind == "palm":
        for s in range(9):
            a = 2 * math.pi * s / 9 + rng.uniform(-0.2, 0.2)
            L = h * rng.uniform(0.6, 0.85)
            pts = []
            for i in range(7):
                t = i / 6
                rr = L * 0.55 * t
                pts.append((rr * math.cos(a), rr * math.sin(a), ph + L * (t * 1.2 - 0.6 * t * t) + 0.05))
            for p0, p1 in zip(pts, pts[1:]):
                k.add(D, LEAF, P.beam(p0, p1, 0.012))
            for i in range(2, 7):
                p = pts[i]
                for sgn in (-1, 1):
                    b = a + sgn * 1.2
                    k.add(D, mats[(i + s) % 2], P.leaf(p, (math.cos(b), math.sin(b), -0.4), 0.28 - 0.025 * i,
                                                       0.045, 0.45))
    else:                                       # bush / fern
        for i in range(45):
            b = rng.uniform(0, 2 * math.pi)
            base = (0.04 * math.cos(b), 0.04 * math.sin(b), ph - 0.03)
            k.add(D, mats[i % 2], P.leaf(base, (math.cos(b), math.sin(b), rng.uniform(0.4, 1.6)),
                                         rng.uniform(0.25, h - ph), rng.uniform(0.06, 0.12), 0.35,
                                         rng.uniform(-0.5, 0.5)))
    return k


def books_row(k, x0, x1, y_back, z, hmax, rng, depth=0.24, cat=D):
    """Fill a shelf from x0 to x1 with books whose spines face +y."""
    x = x0 + 0.01
    while x < x1 - 0.04:
        r = rng.random()
        if r < 0.07:                           # gap / ornament
            if x1 - x > 0.3:
                ow = rng.uniform(0.12, 0.2)
                oh = min(hmax - 0.02, rng.uniform(0.12, 0.26))
                xc = x + ow / 2 + 0.02
                yc = y_back + depth / 2
                if rng.random() < 0.5:
                    k.lathe(cat, rng.choice(("Ceramic_Glaze", "Ceramic_Dark", BRZ)),
                            [(0.0, z), (ow * 0.3, z), (ow * 0.5, z + oh * 0.4), (ow * 0.25, z + oh),
                             (0.0, z + oh)], 12, xc, yc)
                else:
                    k.add(cat, rng.choice(("Ceramic_Dark", ALAB, BRZ)),
                          P.rbox(xc - ow / 2, yc - ow / 2, z, xc + ow / 2, yc + ow / 2, z + ow * 0.7, 0.6, 10, 6),
                          smooth=True)
                x += ow + 0.06
            else:
                x += 0.05
            continue
        if r < 0.17 and x1 - x > 0.32:          # horizontal stack
            n = rng.randint(3, 6)
            bw = rng.uniform(0.2, 0.28)
            zz = z
            for i in range(n):
                t = rng.uniform(0.025, 0.045)
                if zz + t > z + hmax - 0.02:
                    break
                dx = rng.uniform(-0.01, 0.01)
                k.bx(cat, rng.choice(BOOKS), x + dx, y_back + 0.02, zz, x + dx + bw, y_back + depth - 0.01, zz + t)
                zz += t
            x += bw + 0.03
            continue
        bw = rng.uniform(0.018, 0.05)
        bh = min(hmax - 0.015, rng.uniform(0.18, 0.31))
        bd = rng.uniform(depth * 0.7, depth)
        mat = rng.choice(BOOKS)
        if rng.random() < 0.06 and x1 - x > 0.2:   # leaning book
            vf = P.box(0, 0, 0, bw, bd, bh, False)
            vf = P.xf(vf, ry=-0.25, t=(x + 0.07, y_back + depth - bd, z))
            k.add(cat, mat, vf)
            x += 0.07 + bw + 0.01
            continue
        k.bx(cat, mat, x, y_back + depth - bd, z, x + bw, y_back + depth, z + bh)
        x += bw + rng.uniform(0.0, 0.004)


def bookcase(w=1.2, h=2.4, rng=None, wood=WAL, shelf=0.36, d=0.36, plinth=0.1, cat_books=D):
    rng = rng or random.Random(int(w * 1000 + h * 10))
    k = Kit(w, d)
    hd = d / 2
    t = 0.03
    k.cb(F, wood, -w / 2, -hd, 0.0, w / 2, hd, plinth, 0.004)
    k.bx(F, wood, -w / 2, -hd, 0.0, w / 2, -hd + 0.02, h)
    for s in (-1, 1):
        k.cb(F, wood, s * w / 2 - (t if s > 0 else 0), -hd, 0.0, s * w / 2 + (t if s < 0 else 0), hd, h, 0.004)
    z = plinth
    shelves = []
    while z + shelf < h - 0.05:
        shelves.append(z)
        z += shelf
    for zz in shelves + [h - t]:
        k.cb(F, wood, -w / 2 + t, -hd + 0.02, zz, w / 2 - t, hd - 0.01, zz + t, 0.003)
    for zz in shelves:
        books_row(k, -w / 2 + t, w / 2 - t, -hd + 0.03, zz + t, shelf - t, rng, depth=d - 0.08, cat=cat_books)
    return k


def sideboard(w=2.0, wood=WAL, legs=BRZ, rng=None):
    rng = rng or random.Random(int(w * 77))
    k = Kit(w, 0.5)
    h0, h1 = 0.16, 0.78
    _legs(k, legs, -w / 2, -0.23, w / 2, 0.23, h0, 0.03, 0.08, taper=False)
    k.cb(F, wood, -w / 2, -0.23, h0, w / 2, 0.22, h1, 0.008)
    n = max(2, int(round(w / 0.5)))
    dw = (w - 0.04) / n
    for i in range(n):
        x = -w / 2 + 0.02 + i * dw
        k.cb(D, wood, x + 0.003, 0.22, h0 + 0.02, x + dw - 0.003, 0.24, h1 - 0.02, 0.003)
        k.cb(D, legs, x + dw / 2 - 0.08, 0.24, h1 - 0.1, x + dw / 2 + 0.08, 0.255, h1 - 0.09, 0.002)
    k.sub(table_lamp(h1), -w / 2 + 0.3, 0.0)
    _tabletop_decor(k, w * 0.15, 0.0, h1, rng)
    k.sub(vase_flowers(0.45, rng, vase="Ceramic_Dark"), w / 2 - 0.3, 0.0, z=h1)
    return k


# ------------------------------------------------------------------ bedroom
def bed(w=1.8, L=2.1, duvet="Fabric_Linen", throw="Fabric_Charcoal", head="Fabric_Sand", wood=WAL,
        nightstands=True):
    W = w + (1.3 if nightstands else 0.2)
    k = Kit(W, L + 0.2)
    b = -L / 2
    hw = w / 2
    k.cb(F, wood, -hw, b, 0.06, hw, L / 2, 0.32, 0.012)
    k.cb(F, "Lacquer_Black", -hw + 0.1, b + 0.1, 0.0, hw - 0.1, L / 2 - 0.1, 0.06, 0.004)
    k.rb(F, "Bed_Linen", -hw + 0.03, b + 0.06, 0.3, hw - 0.03, L / 2 - 0.03, 0.56, e=0.15)
    k.rb(D, duvet, -hw - 0.04, b + 0.62, 0.42, hw + 0.04, L / 2 + 0.03, 0.62, e=0.18, sag=0.02, nu=14)
    k.rb(D, throw, -hw - 0.06, L / 2 - 0.62, 0.5, hw + 0.06, L / 2 - 0.12, 0.65, e=0.2)
    nps = 2 if w < 1.7 else 2
    pw = (w - 0.2) / nps
    for i in range(nps):
        x = -hw + 0.1 + i * pw
        k.rb(D, "Bed_Linen", x + 0.02, b + 0.12, 0.54, x + pw - 0.02, b + 0.3, 0.86, e=0.4, rx=0.3)
        k.rb(D, "Bed_Linen", x + 0.05, b + 0.28, 0.54, x + pw - 0.05, b + 0.44, 0.78, e=0.4, rx=0.25)
    k.rb(D, "Fabric_Rust", -0.25, b + 0.42, 0.56, 0.25, b + 0.56, 0.8, e=0.4, rx=0.3)
    # channel-tufted headboard
    nch = 6
    hwid = w + 0.25
    for i in range(nch):
        x = -hwid / 2 + i * hwid / nch
        k.rb(F, head, x + 0.003, b - 0.1, 0.25, x + hwid / nch - 0.003, b + 0.02, 1.25, e=0.25, nu=10, nv=6)
    if nightstands:
        for s in (-1, 1):
            x = s * (hw + 0.38)
            k.cb(F, wood, x - 0.25, b - 0.06, 0.0, x + 0.25, b + 0.4, 0.52, 0.008)
            k.cb(D, wood, x - 0.23, b + 0.4, 0.3, x + 0.23, b + 0.415, 0.49, 0.003)
            k.cb(D, BRZ, x - 0.06, b + 0.415, 0.39, x + 0.06, b + 0.425, 0.4, 0.002)
            k.sub(table_lamp(0.52, h=0.6), x, b + 0.15)
            k.light((x, b + 0.15, 1.0), 12.0, "POINT", 0.08)
    return k


# ------------------------------------------------------------------ kitchen
def kitchen_island(w=3.4, d=1.1, body=LACW, top=STAT, rng=None):
    rng = rng or random.Random(3)
    k = Kit(w, d)
    hw, hd = w / 2, d / 2
    k.bx(F, "Lacquer_Black", -hw + 0.08, -hd + 0.08, 0.0, hw - 0.08, hd - 0.08, 0.1)
    k.cb(F, body, -hw + 0.02, -hd + 0.02, 0.1, hw - 0.02, hd - 0.02, 0.88, 0.004)
    for side in (-1, 1):                         # drawer fronts both sides
        y0 = side * (hd - 0.02)
        y1 = side * hd
        n = int(round(w / 0.6))
        dw = (w - 0.04) / n
        for i in range(n):
            x = -hw + 0.02 + i * dw
            for za, zb in ((0.1, 0.48), (0.48, 0.86)):
                k.cb(D, body, x + 0.002, min(y0, y1), za + 0.002, x + dw - 0.002, max(y0, y1), zb - 0.002, 0.002)
    for s in (-1, 1):                            # end panels
        k.cb(D, body, s * hw - (0.02 if s > 0 else 0), -hd, 0.0, s * hw + (0.02 if s < 0 else 0), hd, 0.88, 0.003)
    k.cb(F, top, -hw - 0.02, -hd - 0.02, 0.88, hw + 0.02, hd + 0.02, 0.92, 0.004)
    # cooktop + sink + tap
    k.bx(D, "Glass_Black", 0.55, -0.3, 0.92, 1.35, 0.22, 0.924)
    k.bx(D, "Steel_Brushed", -1.25, -0.25, 0.905, -0.6, 0.17, 0.921)
    k.add(D, "Steel_Brushed", P.merge(P.beam((-0.92, -0.38, 0.92), (-0.92, -0.38, 1.25), 0.025),
                                      P.beam((-0.92, -0.38, 1.25), (-0.92, -0.12, 1.25), 0.025)))
    # fruit bowl + kettle
    k.lathe(D, "Ceramic_Dark", [(0.0, 0.92), (0.08, 0.92), (0.16, 0.97), (0.17, 0.99), (0.0, 0.99)], 16, -0.2, 0.15)
    for i in range(5):
        a = i * 1.3
        k.add(D, rng.choice(("Fruit_Red", "Fruit_Lemon")),
              P.rbox(-0.2 + 0.07 * math.cos(a) - 0.04, 0.15 + 0.07 * math.sin(a) - 0.04, 0.96,
                     -0.2 + 0.07 * math.cos(a) + 0.04, 0.15 + 0.07 * math.sin(a) + 0.04, 1.04, 0.9, 8, 5),
              smooth=True)
    return k


def kitchen_run(w=4.2, body=LACW, top=STAT, tall=1.2, h=3.0):
    """Wall run (back at -y): base units, marble top + splash, tall units."""
    k = Kit(w, 0.66)
    hd = 0.33
    x0 = -w / 2 + tall
    k.bx(F, "Lacquer_Black", x0, -hd, 0.0, w / 2, hd - 0.08, 0.1)
    k.cb(F, body, x0, -hd, 0.1, w / 2, hd - 0.02, 0.88, 0.004)
    n = max(1, int(round((w / 2 - x0) / 0.6)))
    dw = (w / 2 - x0) / n
    for i in range(n):
        x = x0 + i * dw
        k.cb(D, body, x + 0.002, hd - 0.02, 0.102, x + dw - 0.002, hd, 0.86, 0.002)
    k.cb(F, top, x0, -hd, 0.88, w / 2, hd + 0.01, 0.91, 0.004)
    k.bx(D, top, x0, -hd, 0.91, w / 2, -hd + 0.02, 1.55)
    for i in range(2):                           # tall units (fridge / ovens)
        x = -w / 2 + i * tall / 2
        k.cb(F, body, x + 0.002, -hd, 0.0, x + tall / 2 - 0.002, hd, min(h - 0.05, 2.6), 0.004)
        k.cb(D, BRZ, x + tall / 2 - 0.06, hd, 0.9, x + tall / 2 - 0.045, hd + 0.02, 1.7, 0.003)
    k.bx(D, "Glass_Black", -w / 2 + tall / 2 + 0.05, hd, 0.95, -w / 2 + tall - 0.05, hd + 0.005, 1.55)
    # open shelf with ceramics
    k.cb(D, WAL, x0 + 0.3, -hd, 1.85, w / 2 - 0.2, -hd + 0.3, 1.89, 0.003)
    rng = random.Random(int(w * 31))
    x = x0 + 0.45
    while x < w / 2 - 0.4:
        k.lathe(D, rng.choice(("Ceramic_Glaze", "Ceramic_Dark")),
                [(0.0, 1.89), (0.05, 1.89), (0.07, 1.98), (0.04, 2.05), (0.0, 2.05)], 12, x, -hd + 0.15)
        x += rng.uniform(0.25, 0.45)
    return k


# ------------------------------------------------------------------ piano / pool / misc
PIANO_OUTLINE = [(-0.74, -0.72), (0.74, -0.72), (0.74, -0.25), (0.62, 0.12), (0.42, 0.42), (0.28, 0.72),
                 (0.12, 0.98), (-0.12, 1.12), (-0.42, 1.14), (-0.64, 1.04), (-0.74, 0.86)]


def grand_piano():
    k = Kit(1.6, 2.6)
    oy = 0.2
    poly = [(x, y + oy) for x, y in PIANO_OUTLINE]
    k.add(F, LACB, P.prism(poly, 0.6, 0.98))
    k.cb(F, LACB, -0.76, -0.97 + oy, 0.6, 0.76, -0.7 + oy, 0.78, 0.01)
    k.bx(D, "Piano_Keys", -0.68, -0.96 + oy, 0.78, 0.68, -0.8 + oy, 0.8)
    for i in range(36):
        if i % 7 in (2, 6):
            continue
        x = -0.66 + i * 0.0375
        k.bx(D, LACB, x + 0.008, -0.88 + oy, 0.8, x + 0.022, -0.8 + oy, 0.812)
    k.cb(D, LACB, -0.7, -0.79 + oy, 0.98, 0.7, -0.72 + oy, 1.25, 0.005)
    lid = P.prism(poly, 0.0, 0.02)
    lid = P.xf(lid, ry=-0.55, pivot=(-0.74, 0.0, 0.0), t=(0.0, 0.0, 0.98))
    k.add(D, LACB, lid)
    k.add(D, LACB, P.beam((0.35, 0.3 + oy, 0.98), (0.3, 0.3 + oy, 1.62), 0.015))
    for x, y in ((-0.6, -0.6), (0.6, -0.6), (-0.3, 0.95)):
        k.lathe(F, LACB, [(0.035, 0.0), (0.05, 0.03), (0.06, 0.6), (0.0, 0.6)], 10, x, y + oy)
    k.cb(F, LACB, -0.4, -1.55, 0.44, 0.4, -1.2, 0.5, 0.008)
    k.rb(D, LEATH, -0.38, -1.53, 0.47, 0.38, -1.22, 0.53, e=0.2)
    _legs(k, LACB, -0.4, -1.55, 0.4, -1.2, 0.44, 0.035, 0.03, taper=False)
    return k


def lounger(frame=LACW, pad="Fabric_Linen"):
    k = Kit(0.78, 2.05)
    for x in (-0.33, 0.33):
        for y in (-0.9, 0.9):
            k.cb(F, frame, x - 0.03, y - 0.03, 0.0, x + 0.03, y + 0.03, 0.12, 0.006)
    k.cb(F, frame, -0.38, -1.0, 0.12, 0.38, 1.0, 0.26, 0.02)
    k.rb(D, pad, -0.36, -0.2, 0.25, 0.36, 0.98, 0.36, e=0.15, sag=0.01)
    back = P.rbox(-0.36, 0.0, 0.0, 0.36, 0.78, 0.1, 0.15, 12, 7)
    back = P.xf(back, rx=-0.65, t=(0.0, -0.98, 0.27))
    k.add(D, pad, back, smooth=True)
    k.rb(D, "Fabric_Cream", -0.2, -0.88, 0.62, 0.2, -0.72, 0.72, e=0.5, rx=-0.6)
    k.rb(D, "Fabric_Cream", -0.28, 0.45, 0.35, 0.28, 0.75, 0.42, e=0.25)        # folded towel
    return k


def sconce(z=2.2, shade=ALAB, plate=BRZ, h=0.42, light=False):
    """Wall sconce mounted on a wall at y=0, protruding +y."""
    k = Kit(0.2, 0.16)
    k.cb(D, plate, -0.06, 0.0, z - h / 2 - 0.04, 0.06, 0.02, z + h / 2 + 0.04, 0.004)
    k.add(D, shade, P.lathe([(0.1, z - h / 2), (0.1, z + h / 2)], 10, 0.0, 0.02, cap0=True, cap1=True,
                            a0=0.0, a1=math.pi), smooth=True)
    k.bx(D, "Light_Emit", -0.06, 0.025, z - h / 2 + 0.03, 0.06, 0.07, z + h / 2 - 0.03)
    if light:
        k.light((0.0, 0.18, z), 18.0, "POINT", 0.1)
    return k


def artwork(w, h, z_center, rng, frame=BRZ, style="blocks", depth=0.06):
    """Framed canvas on a wall at y=0, facing +y."""
    k = Kit(w, depth)
    za, zb = z_center - h / 2, z_center + h / 2
    f = 0.06
    k.cb(D, frame, -w / 2, 0.0, za, w / 2, depth, za + f, 0.006)
    k.cb(D, frame, -w / 2, 0.0, zb - f, w / 2, depth, zb, 0.006)
    k.cb(D, frame, -w / 2, 0.0, za + f, -w / 2 + f, depth, zb - f, 0.006)
    k.cb(D, frame, w / 2 - f, 0.0, za + f, w / 2, depth, zb - f, 0.006)
    base = rng.choice(["Art_Ivory", "Art_Black", "Art_Blue", "Art_Teal"])
    k.bx(D, base, -w / 2 + f, 0.0, za + f, w / 2 - f, depth - 0.02, zb - f)
    pal = ["Art_Red", "Art_Blue", "Art_Yellow", "Art_Black", "Art_Teal", "Art_Orange", "Art_Pink", "Art_Ivory",
           GOLD]
    iw, ih = w - 2 * f - 0.1, h - 2 * f - 0.1
    if style == "blocks":                      # colour-field (Rothko-like) bands
        n = rng.randint(2, 3)
        zz = za + f + 0.08
        for i in range(n):
            bh = (ih - 0.08 * (n - 1)) / n * rng.uniform(0.8, 1.1)
            k.rb(D, rng.choice(pal), -iw / 2 + 0.05, depth - 0.03, zz, iw / 2 - 0.05, depth - 0.012,
                 min(zz + bh, zb - f - 0.06), e=0.15, nu=8, nv=4)
            zz += bh + 0.08
    else:                                      # scattered shapes (abstract)
        for i in range(rng.randint(6, 11)):
            cx = rng.uniform(-iw / 2 + 0.2, iw / 2 - 0.2)
            cz = rng.uniform(za + f + 0.2, zb - f - 0.2)
            s = rng.uniform(0.08, min(iw, ih) * 0.22)
            k.add(D, rng.choice(pal), P.rbox(cx - s, depth - 0.03, cz - s * rng.uniform(0.3, 1.0), cx + s,
                                             depth - 0.015 - 0.002 * i, cz + s * rng.uniform(0.3, 1.0),
                                             rng.uniform(0.3, 1.0), 10, 6), smooth=True)
    return k
