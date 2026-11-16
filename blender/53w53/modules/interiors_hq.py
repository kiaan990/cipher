"""Showcase-quality versions of the interiors_kits API.

Same function names and (roughly) the same footprints as interiors_kits, so
the floor layouts can switch between lean kits (typical floors, keeps the GLB
small) and these detailed ones (lobby, amenity floors, showcase apartments)
via fc.K. Anything not overridden falls back to the lean kit.
"""
import random

from modules.interiors_kits import *  # noqa: F401,F403  (fallbacks: treadmill, mat_row, ...)
from modules import interiors_furn as FU

_SEED = [1]


def _rng():
    _SEED[0] += 1
    return random.Random(_SEED[0] * 7919)


def reset(seed):
    _SEED[0] = seed


def _fit(kit, w, d):
    kit.w, kit.d = w, d
    return kit


def living_set(w=2.6, fab=None, rng=None):
    rng = rng or _rng()
    W, Dp = max(w, 2.6) + 1.6, 3.6
    fab = fab or rng.choice(["Fabric_Linen", "Fabric_Cream", "Fabric_Sand"])
    k = FU.Kit(W, Dp)
    k.sub(FU.rug(W - 0.5, Dp - 0.45, rng.choice(["Rug_Wool", "Rug_Sisal"]), "Rug_Border"), 0, 0.1)
    k.sub(FU.sofa(w, fab, seats=3 if w >= 2.6 else 2), 0, -Dp / 2 + 0.5)
    if rng.random() < 0.5:
        k.sub(FU.coffee_round(0.5, rng.choice([FU.STAT, FU.NOIR, FU.WAL])), 0, 0.15)
    else:
        k.sub(FU.coffee_rect(1.3, 0.7), 0, 0.15)
    chair = rng.choice([lambda: FU.lounge_chair(rng.choice(["Fabric_Blush", "Fabric_Navy", "Fabric_Velvet_Green"])),
                        lambda: FU.armchair(FU.LEATH)])
    for s in (-1, 1):
        k.sub(chair(), s * 1.25, 1.25, 180 + s * 20)
    k.sub(FU.side_table(), w / 2 + 0.32, -Dp / 2 + 0.45)
    k.sub(FU.floor_lamp(), -w / 2 - 0.3, -Dp / 2 + 0.4)
    return k


def dining(n_side=3, mat="Walnut", rng=None):
    tw = 0.6 * n_side + 0.4
    k = FU.dining_table(tw + 0.2, 0.98, mat if mat != "Wood_Walnut" else "Walnut", n_side, ends=False)
    return _fit(k, tw + 1.0, 2.4)


def kitchen(w=3.6):
    Dp = 3.1
    k = FU.Kit(w, Dp)
    k.sub(FU.kitchen_run(w, tall=min(1.2, w * 0.3)), 0, -Dp / 2 + 0.33)
    k.sub(FU.kitchen_island(max(2.2, w - 0.9), 1.05), 0, 0.85)
    return k


def bed(w=1.8, nightstands=True):
    rng = _rng()
    k = FU.bed(w, 2.1, duvet=rng.choice(["Fabric_Linen", "Bed_Linen", "Fabric_Cream"]),
               throw=rng.choice(["Fabric_Charcoal", "Fabric_Velvet_Green", "Fabric_Navy"]),
               nightstands=nightstands)
    k.sub(FU.rug(w + 1.0, 1.6, "Rug_Wool", "Rug_Border"), 0, 0.55)
    return _fit(k, w + (1.3 if nightstands else 0.2), 2.3)


def wardrobe(w=2.0, h=2.6):
    k = FU.Kit(w, 0.62)
    k.cb(FU.F, FU.LACW, -w / 2, -0.31, 0.0, w / 2, 0.29, h, 0.004)
    n = max(2, int(round(w / 0.55)))
    dw = w / n
    for i in range(n):
        x = -w / 2 + i * dw
        k.cb(FU.D, FU.LACW, x + 0.002, 0.29, 0.06, x + dw - 0.002, 0.31, h - 0.01, 0.002)
        hx = x + (dw - 0.06 if i % 2 == 0 else 0.06)
        k.cb(FU.D, FU.BRZ, hx - 0.008, 0.31, 0.9, hx + 0.008, 0.33, 1.5, 0.003)
    return k


def desk():
    k = FU.Kit(1.6, 1.4)
    k.cb(FU.F, FU.WAL, -0.8, -0.7, 0.72, 0.8, -0.05, 0.75, 0.006)
    for x in (-0.76, 0.76):
        k.cb(FU.F, FU.BRZ, x - 0.015, -0.68, 0.0, x + 0.015, -0.07, 0.72, 0.004)
    k.sub(FU.table_lamp(0.75, h=0.5), 0.55, -0.45)
    k.bx(FU.D, "Glass_Black", -0.3, -0.6, 0.75, 0.15, -0.3, 0.765)
    k.cb(FU.D, "Lacquer_Black", -0.28, -0.6, 0.765, 0.13, -0.32, 0.768, 0.001)
    k.sub(FU.dining_chair(FU.WAL, "Leather_Cognac"), 0.0, 0.2, 180)
    return k


def bookshelf(w=2.4, h=2.4):
    k = FU.bookcase(w, h, d=0.4)
    return _fit(k, w, 0.5)


def plant():
    rng = _rng()
    kind = rng.choice(["fig", "olive", "palm", "fig"])
    k = FU.plant(kind, rng.uniform(1.5, 2.0), rng)
    return _fit(k, max(k.w, 0.6), max(k.d, 0.6))


def armchair_pair():
    k = FU.Kit(2.4, 1.2)
    rng = _rng()
    fab = rng.choice([FU.LEATH, "Fabric_Velvet_Green", "Fabric_Navy"])
    for s in (-1, 1):
        k.sub(FU.armchair(fab), s * 0.72, 0.0, -s * 8)
    k.sub(FU.side_table(), 0.0, 0.05)
    return k


def sofa(w=2.4, mat=None):
    return FU.sofa(w, mat or "Fabric_Linen", seats=3 if w >= 2.6 else 2)


def tv_wall(w=2.4):
    return _fit(FU.sideboard(w), w, 0.5)


def bench(w=2.0):
    return FU.bench(w)


def piano():
    return FU.grand_piano()


def lounger():
    return FU.lounger()
