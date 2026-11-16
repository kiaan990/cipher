"""Residential showcase details: interior diagrid casings (every floor),
cove-lit ceilings, the penthouse fit-out (with a Calder-like mobile) and
gallery sculptures.
"""
import math
import random

import config as C
from modules import interiors_geom as G
from modules import interiors_prims as P
from modules import interiors_furn as FU
from modules import interiors_details as DT


def diagrid_casings(fc, members, skip=None):
    """White-cased slanted columns inside the glass (lean on typical floors)."""
    if not members:
        return 0
    return DT.casings(fc, members, chamfer=0.035 if fc.showcase else 0.0, skip=skip)


def apartment_ceiling(fc):
    """Showcase apartments: cove-lit perimeter soffit with downlights,
    replacing the flat emissive panels of the lean floors."""
    poly = C.inset(C.plate(fc.n), 0.05)
    if poly:
        DT.cove_ceiling(fc, poly, band=0.95, drop=0.3)


def mobile(rng, z_top, drop=1.6):
    """Calder-like hanging mobile: balanced wire arms with painted discs."""
    k = FU.Kit(2.4, 2.4)
    pal = ["Art_Red", "Art_Black", "Art_Black", "Art_Ivory", "Art_Yellow", "Art_Red"]

    def arm(x, y, z, length, depth, a):
        ca, sa = math.cos(a), math.sin(a)
        p0 = (x - ca * length * 0.35, y - sa * length * 0.35, z)
        p1 = (x + ca * length * 0.65, y + sa * length * 0.65, z)
        k.add(FU.D, "Metal_Dark", P.beam(p0, p1, 0.008))
        r = rng.uniform(0.09, 0.2)
        k.add(FU.D, rng.choice(pal), P.xf(P.disc(0, 0, 0, r, 10), rx=math.pi / 2, rz=a + rng.uniform(-0.5, 0.5),
                                          t=(p0[0], p0[1], p0[2] - r * 0.6)))
        if depth > 0:
            k.add(FU.D, "Metal_Dark", P.beam(p1, (p1[0], p1[1], p1[2] - 0.35), 0.006))
            arm(p1[0], p1[1], p1[2] - 0.35, length * 0.75, depth - 1, a + rng.uniform(1.0, 2.4))
        else:
            r = rng.uniform(0.12, 0.25)
            k.add(FU.D, rng.choice(pal), P.xf(P.disc(0, 0, 0, r, 12), rx=math.pi / 2, rz=a,
                                              t=(p1[0], p1[1], p1[2] - r * 0.5)))

    k.add(FU.D, "Metal_Dark", P.beam((0, 0, z_top), (0, 0, z_top - 0.5), 0.006))
    arm(0.0, 0.0, z_top - 0.5, 1.5, 3, rng.uniform(0, 6.28))
    return k


def penthouse(fc):
    """Floor 77: open plan at the tip of the spire."""
    Fz = fc.Fz
    from modules import interiors as I
    I.finish_default(fc, "Oak_Dark_Floor")
    fc.kit_lights = 5
    fc.block((18.5, 16.8, 25.5, 19.3))                          # lift / stair foyer
    rng = random.Random(77)
    # north lobe: living group under the mobile, looking at the apex windows
    fc.put(FU.rug(3.8, 2.8, "Rug_Wool", "Rug_Border"), 22.95, 21.3, 0, block=False)
    fc.put(FU.sofa(2.6, "Fabric_Cream", seats=3), 22.95, 20.25, 0)
    fc.put(FU.coffee_round(0.45, FU.NOIR), 22.95, 21.55, 0)
    fc.put(FU.lounge_chair("Fabric_Blush"), 22.95, 22.95, 180)
    fc.put(FU.side_table(), 25.0, 20.2, 0)
    fc.put(FU.floor_lamp(), 20.75, 20.25, 0)
    # east wing: grand piano + dining for four
    fc.put(FU.grand_piano(), 27.3, 13.05, 90)
    fc.put(FU.dining_table(1.5, 0.9, "Walnut", 2, ends=False), 27.0, 15.3, 90)
    fc.put(FU.floor_lamp(), 25.9, 17.4, 0)
    # west wing: bar cabinet + bookcase against the core, plants in the corners
    fc.put(FU.sideboard(1.8, rng=rng), 18.73, 14.3, 90)
    fc.put(FU.bookcase(1.2, 2.4, rng, d=0.36), 18.8, 12.6, 90)
    for (x, y), kind in (((16.0, 11.55), "olive"), ((29.8, 11.6), "fig"), ((22.95, 24.6), "palm")):
        fc.put(FU.plant(kind, 1.9, random.Random(int(x * 13))), x, y, 0)
    fc.put(mobile(random.Random(77), Fz + 3.55), 22.95, 21.6, 0, block=False)
    apartment_ceiling(fc)
    fc.point_light("PH_Area", (22.95, 17.5, Fz + 3.3), 250.0, "AREA", 2.5)


def sculpture(fc, x, y, z, rng):
    """Gallery sculpture on a plinth: turned vessel, stacked forms or bust."""
    d = fc.sink("decor")
    kind = rng.randrange(3)
    mat = rng.choice(["Bronze_Trim", "Art_Black", "Marble_Statuary", "Art_Red", "Metal_Dark"])
    if kind == 0:
        h = rng.uniform(0.5, 1.1)
        prof = [(0.0, z), (0.12, z), (0.2, z + h * 0.3), (0.16, z + h * 0.7), (0.07, z + h * 0.85),
                (0.1, z + h), (0.0, z + h)]
        d.mesh(mat, *P.lathe(prof, 20, x, y), smooth=True)
    elif kind == 1:
        zz = z
        for i in range(rng.randint(3, 6)):
            s = rng.uniform(0.1, 0.2)
            hh = rng.uniform(0.12, 0.25)
            d.mesh(mat, *P.rbox(x - s, y - s, zz, x + s, y + s, zz + hh, 0.5, 12, 6), smooth=True)
            zz += hh * 0.92
    else:
        h = rng.uniform(0.8, 1.4)
        d.mesh(mat, *P.xf(P.rbox(-0.08, -0.05, 0.0, 0.08, 0.05, h, 0.6, 12, 8), ry=rng.uniform(-0.2, 0.2),
                          t=(x, y, z)), smooth=True)
        d.mesh(mat, *P.rbox(x - 0.18, y - 0.18, z, x + 0.18, y + 0.18, z + 0.06, 0.3))
