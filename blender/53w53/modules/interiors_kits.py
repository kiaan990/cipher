"""Low-poly furniture kits for the interiors (boxes only).

Each kit is (width_x, depth_y, parts) centred on the origin, 'front' facing +y.
part = (category, material, x0, y0, z0, x1, y1, z1); category is
'furn' (collidable: sofas, beds, tables, counters) or 'decor' (not).
"""

F, D = "furn", "decor"

OAK, WAL, FAB, MET, STONE = "Floor_Oak", "Wood_Walnut", "Fabric_Grey", "Metal_Dark", "Floor_Stone"
LIN, MARBLE, RUG, LEATH, PLANT = "Bed_Linen", "Marble_White", "Rug_Wool", "Leather_Tan", "Foliage"


def _chair(x, y, facing, mat=FAB):
    """Dining chair at (x, y); facing +1 = faces +y, -1 = faces -y."""
    s = 0.22
    back_y0, back_y1 = (y - s, y - s + 0.06) if facing > 0 else (y + s - 0.06, y + s)
    return [(D, mat, x - s, y - s, 0.0, x + s, y + s, 0.46),
            (D, mat, x - s, back_y0, 0.46, x + s, back_y1, 0.9)]


def sofa(w=2.4, mat=FAB):
    d = 0.95
    return (w, d, [
        (F, mat, -w / 2, -d / 2, 0.0, w / 2, d / 2, 0.42),
        (F, mat, -w / 2, -d / 2, 0.42, w / 2, -d / 2 + 0.22, 0.82),
        (F, mat, -w / 2, -d / 2, 0.42, -w / 2 + 0.18, d / 2, 0.62),
        (F, mat, w / 2 - 0.18, -d / 2, 0.42, w / 2, d / 2, 0.62),
    ])


def living_set(w=2.6):
    """Sofa (back at -y), coffee table, rug, two lounge chairs facing it."""
    W, Dp = max(w, 2.6) + 1.6, 3.6
    s = sofa(w)[2]
    sy = -Dp / 2 + 0.5
    parts = [(c, m, x0, y0 + sy, z0, x1, y1 + sy, z1) for c, m, x0, y0, z0, x1, y1, z1 in s]
    parts += [
        (D, RUG, -W / 2 + 0.3, -Dp / 2 + 0.3, 0.0, W / 2 - 0.3, Dp / 2 - 0.2, 0.012),
        (F, WAL, -0.65, -0.25, 0.0, 0.65, 0.4, 0.38),
        (D, LEATH, -1.6, 0.9, 0.0, -0.85, 1.65, 0.42),
        (D, LEATH, -1.6, 1.5, 0.42, -0.85, 1.65, 0.78),
        (D, LEATH, 0.85, 0.9, 0.0, 1.6, 1.65, 0.42),
        (D, LEATH, 0.85, 1.5, 0.42, 1.6, 1.65, 0.78),
    ]
    return (W, Dp, parts)


def tv_wall(w=2.4):
    return (w, 0.5, [
        (F, WAL, -w / 2, -0.25, 0.0, w / 2, 0.2, 0.5),
        (D, MET, -0.8, -0.2, 0.9, 0.8, -0.16, 1.8),
    ])


def dining(n_side=3, mat=WAL):
    tw = 0.6 * n_side + 0.4
    W, Dp = tw + 1.0, 2.4
    parts = [(F, mat, -tw / 2, -0.48, 0.71, tw / 2, 0.48, 0.76),
             (F, mat, -tw / 2 + 0.3, -0.15, 0.0, tw / 2 - 0.3, 0.15, 0.71)]
    for i in range(n_side):
        x = -tw / 2 + 0.5 + i * 0.6
        parts += _chair(x, -0.82, +1) + _chair(x, 0.82, -1)
    return (W, Dp, parts)


def kitchen(w=3.6):
    """Counter run along the back (-y) with tall units, island in front."""
    Dp = 3.1
    b = -Dp / 2
    return (w, Dp, [
        (F, WAL, -w / 2, b, 0.0, w / 2, b + 0.65, 0.88),
        (D, MARBLE, -w / 2, b, 0.88, w / 2, b + 0.67, 0.92),
        (F, WAL, -w / 2, b, 0.0, -w / 2 + 0.7, b + 0.65, 2.3),
        (D, WAL, -w / 2 + 0.7, b, 1.5, w / 2, b + 0.35, 2.2),
        (F, WAL, -w / 2 + 0.6, 0.35, 0.0, w / 2 - 0.6, 1.3, 0.88),
        (D, MARBLE, -w / 2 + 0.55, 0.3, 0.88, w / 2 - 0.55, 1.35, 0.93),
        (D, MET, -w / 2 + 0.9, 1.35, 0.0, -w / 2 + 1.3, 1.55, 0.75),
        (D, MET, w / 2 - 1.3, 1.35, 0.0, w / 2 - 0.9, 1.55, 0.75),
    ])


def bed(w=1.8, nightstands=True):
    L = 2.15
    W = w + (1.2 if nightstands else 0.0)
    b = -L / 2
    parts = [
        (F, WAL, -w / 2, b, 0.0, w / 2, L / 2, 0.3),
        (F, LIN, -w / 2 + 0.03, b + 0.1, 0.3, w / 2 - 0.03, L / 2 - 0.03, 0.55),
        (D, LIN, -w / 2 + 0.15, b + 0.15, 0.55, w / 2 - 0.15, b + 0.55, 0.68),
        (F, WAL, -w / 2 - 0.05, b, 0.0, w / 2 + 0.05, b + 0.1, 1.15),
        (D, FAB, -w / 2 + 0.02, L / 2 - 0.7, 0.55, w / 2 - 0.02, L / 2 - 0.05, 0.58),
    ]
    if nightstands:
        for sx in (-1, 1):
            x = sx * (w / 2 + 0.3)
            parts.append((D, WAL, x - 0.25, b, 0.0, x + 0.25, b + 0.45, 0.5))
            parts.append((D, "Light_Emit", x - 0.08, b + 0.15, 0.5, x + 0.08, b + 0.3, 0.75))
    return (W, L, parts)


def wardrobe(w=2.0):
    return (w, 0.62, [(F, OAK, -w / 2, -0.31, 0.0, w / 2, 0.31, 2.3)])


def desk():
    return (1.6, 1.4, [
        (F, WAL, -0.8, -0.7, 0.72, 0.8, 0.0, 0.76),
        (F, WAL, -0.8, -0.7, 0.0, -0.75, 0.0, 0.72),
        (F, WAL, 0.75, -0.7, 0.0, 0.8, 0.0, 0.72),
        (D, MET, -0.35, -0.6, 0.76, 0.35, -0.55, 1.15),
        (D, FAB, -0.25, 0.1, 0.0, 0.25, 0.6, 0.48),
        (D, FAB, -0.25, 0.5, 0.48, 0.25, 0.6, 0.95),
    ])


def bookshelf(w=2.4, h=2.4):
    parts = [(F, WAL, -w / 2, -0.2, 0.0, w / 2, 0.2, h)]
    cols = ["Book_Red", "Book_Blue", "Book_Ochre", "Book_Green"]
    k = 0
    z = 0.35
    while z + 0.3 < h:
        x = -w / 2 + 0.05
        while x + 0.3 < w / 2:
            parts.append((D, cols[k % 4], x, 0.2, z, x + 0.28, 0.24, z + 0.26))
            x += 0.32
            k += 1
        z += 0.45
    return (w, 0.5, parts)


def plant():
    return (0.6, 0.6, [(D, "Pot_Clay", -0.22, -0.22, 0.0, 0.22, 0.22, 0.45),
                       (D, PLANT, -0.3, -0.3, 0.45, 0.3, 0.3, 1.4)])


def armchair_pair():
    return (2.4, 1.2, [
        (F, LEATH, -1.1, -0.45, 0.0, -0.3, 0.35, 0.42),
        (D, LEATH, -1.1, -0.45, 0.42, -0.3, -0.3, 0.85),
        (F, LEATH, 0.3, -0.45, 0.0, 1.1, 0.35, 0.42),
        (D, LEATH, 0.3, -0.45, 0.42, 1.1, -0.3, 0.85),
        (D, WAL, -0.2, -0.2, 0.0, 0.2, 0.2, 0.5),
    ])


def bench(w=2.0):
    return (w, 0.55, [(F, WAL, -w / 2, -0.25, 0.38, w / 2, 0.25, 0.46),
                      (F, MET, -w / 2 + 0.1, -0.2, 0.0, -w / 2 + 0.2, 0.2, 0.38),
                      (F, MET, w / 2 - 0.2, -0.2, 0.0, w / 2 - 0.1, 0.2, 0.38)])


def piano():
    return (1.6, 2.2, [
        (F, MET, -0.75, -1.05, 0.62, 0.75, 1.05, 1.0),
        (F, MET, -0.7, -1.0, 0.0, -0.6, -0.9, 0.62),
        (F, MET, 0.6, -1.0, 0.0, 0.7, -0.9, 0.62),
        (F, MET, -0.05, 0.9, 0.0, 0.05, 1.0, 0.62),
        (D, MARBLE, -0.7, -1.05, 0.72, 0.7, -0.9, 0.76),
        (D, LEATH, -0.4, -1.6, 0.0, 0.4, -1.25, 0.48),
    ])


def lounger():
    return (0.75, 2.0, [(F, "Wood_Teak", -0.35, -0.95, 0.0, 0.35, 0.95, 0.32),
                        (D, LIN, -0.32, -0.9, 0.32, 0.32, 0.4, 0.38),
                        (D, LIN, -0.32, 0.4, 0.32, 0.32, 0.9, 0.7)])


def treadmill():
    return (0.9, 2.0, [(F, MET, -0.4, -0.9, 0.0, 0.4, 0.9, 0.22),
                       (F, MET, -0.4, 0.75, 0.22, -0.34, 0.9, 1.2),
                       (F, MET, 0.34, 0.75, 0.22, 0.4, 0.9, 1.2),
                       (D, MET, -0.4, 0.75, 1.2, 0.4, 0.95, 1.35)])


def weight_bench():
    return (1.6, 1.6, [(F, LEATH, -0.15, -0.6, 0.0, 0.15, 0.6, 0.45),
                       (F, MET, -0.75, 0.45, 0.0, -0.65, 0.55, 1.6),
                       (F, MET, 0.65, 0.45, 0.0, 0.75, 0.55, 1.6),
                       (D, MET, -0.75, 0.45, 1.6, 0.75, 0.55, 1.66)])


def mat_row(n=4):
    w = n * 0.8
    parts = []
    for i in range(n):
        x = -w / 2 + i * 0.8 + 0.05
        parts.append((D, "Mat_Yoga", x, -0.95, 0.0, x + 0.65, 0.95, 0.012))
    return (w, 2.0, parts)


def bar_counter(w=4.0):
    return (w, 1.6, [(F, WAL, -w / 2, -0.8, 0.0, w / 2, -0.2, 1.05),
                     (D, MARBLE, -w / 2, -0.8, 1.05, w / 2, -0.15, 1.1)]
            + [p for i in range(int(w / 0.8)) for p in [
                (D, LEATH, -w / 2 + 0.4 + i * 0.8 - 0.18, 0.15, 0.0, -w / 2 + 0.4 + i * 0.8 + 0.18, 0.5, 0.75)]])


def screening_rows(w=6.0, rows=3):
    parts = []
    Dp = rows * 1.5
    for r in range(rows):
        y = -Dp / 2 + r * 1.5
        parts += [(F, "Fabric_Red", -w / 2, y, 0.0, w / 2, y + 0.9, 0.45),
                  (F, "Fabric_Red", -w / 2, y, 0.45, w / 2, y + 0.2, 0.95)]
    return (w, Dp, parts)


KIT_MATS = {
    "Bed_Linen": (0.88, 0.86, 0.82, 1),
    "Marble_White": (0.90, 0.89, 0.87, 1),
    "Rug_Wool": (0.62, 0.58, 0.52, 1),
    "Leather_Tan": (0.45, 0.28, 0.16, 1),
    "Book_Red": (0.55, 0.12, 0.10, 1),
    "Book_Blue": (0.12, 0.20, 0.42, 1),
    "Book_Ochre": (0.70, 0.52, 0.18, 1),
    "Book_Green": (0.16, 0.32, 0.20, 1),
    "Pot_Clay": (0.55, 0.36, 0.26, 1),
    "Wood_Teak": (0.48, 0.32, 0.18, 1),
    "Mat_Yoga": (0.30, 0.42, 0.40, 1),
    "Fabric_Red": (0.45, 0.06, 0.07, 1),
}
