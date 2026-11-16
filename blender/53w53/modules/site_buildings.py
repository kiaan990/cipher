"""Hand-authored landmark buildings around 53 West 53 (interpretive massing)."""
import math
from modules.site_kit import (building, facade_bands, facade_piers, rect, edge_normal,
                              ico_vf, xz_prism_vf)

COLORS_EXTRA = {"Pool_Dark": (0.10, 0.20, 0.24, 1)}


# ---------------------------------------------------------------- wall helpers
def wall_ngon(kit, mat, face, c, pts, off=0.04, group="Bldg"):
    """Flat polygon on an axis-aligned facade. pts are (u, z) where u is the
    world x (faces S/N) or world y (faces E/W). face in 'S','N','E','W', c is
    the wall coordinate. The polygon is lifted `off` off the wall."""
    if face == "S":
        v = [(u, c - off, z) for u, z in pts]
    elif face == "N":
        v = [(u, c + off, z) for u, z in reversed(pts)]
    elif face == "E":
        v = [(c + off, u, z) for u, z in pts]
    else:
        v = [(c - off, u, z) for u, z in reversed(pts)]
    kit.ngon(mat, v, group)


def wall_rect(kit, mat, face, c, u0, u1, z0, z1, off=0.04):
    wall_ngon(kit, mat, face, c, [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], off)


def lancet(u0, u1, z0, zs, n=5):
    """Pointed (equilateral) gothic arch outline in (u, z), CCW."""
    w = u1 - u0
    pts = [(u0, z0), (u1, z0), (u1, zs)]
    # right arc: centre (u0, zs), from angle 0 to 60 deg
    for k in range(1, n):
        a = math.radians(60.0 * k / n)
        pts.append((u0 + w * math.cos(a), zs + w * math.sin(a)))
    pts.append(((u0 + u1) / 2, zs + w * math.sin(math.radians(60))))
    for k in range(n - 1, 0, -1):
        a = math.radians(60.0 * k / n)
        pts.append((u1 - w * math.cos(a), zs + w * math.sin(a)))
    pts.append((u0, zs))
    return pts


def yz_prism(kit, mat, profile, x0, x1, collide=True):
    """Extrude a (y, z) profile (CCW seen from +x) along x from x0 to x1."""
    n = len(profile)
    v = [(x0, y, z) for y, z in profile] + [(x1, y, z) for y, z in profile]
    f = [tuple(reversed(range(n))), tuple(n + i for i in range(n))]
    for i in range(n):
        j = (i + 1) % n
        f.append((i, j, n + j, n + i))
    kit.b(mat, "Bldg", collide).extend(v, f)


def pyramid(kit, mat, cx, cy, z0, z1, r):
    v = [(cx - r, cy - r, z0), (cx + r, cy - r, z0), (cx + r, cy + r, z0), (cx - r, cy + r, z0), (cx, cy, z1)]
    f = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    kit.b(mat, "Bldg", True).extend(v, f)


def octagon_down(kit, mat, cx, cy, z, r, n=8):
    v = [(cx + r * math.cos(-2 * math.pi * k / n), cy + r * math.sin(-2 * math.pi * k / n), z) for k in range(n)]
    kit.ngon(mat, v)


# ---------------------------------------------------------------- trees
def tree(kit, x, y, h=7.5, r=2.4, pit=True, seed=0.0):
    kit.cyl("Bark", x, y, 0.0, h * 0.55, 0.16, 0.11, n=6, group="Trees", collide=True)
    v, f = ico_vf()
    for (dx, dy, dz, s) in ((0, 0, 0.72, 1.0), (0.35 * math.cos(seed), 0.35 * math.sin(seed), 0.88, 0.7)):
        cx, cy, cz = x + dx * r, y + dy * r, h * dz
        vv = [(cx + p[0] * r * s, cy + p[1] * r * s, cz + p[2] * r * s * 0.8) for p in v]
        kit.b("Foliage", "Trees", False).extend(vv, f)
    if pit:
        kit.hquad("Soil", x - 0.75, y - 0.75, x + 0.75, y + 0.75, 0.005, group="Trees")


# ---------------------------------------------------------------- MoMA
def moma(kit):
    # --- 2019 Diller Scofidio + Renfro Geffen Wing, flush against the tower's
    # east wall (follows its slanted edge, 0.5 m clear), west wall x = 46.51
    poly = [(42.51, 0.0), (62.0, 0.0), (62.0, 32.0), (46.51, 32.0), (46.51, 22.0)]
    kit.prism("Glass_Blue", poly, 0.0, 34.0)
    facade_bands(kit, poly, 7.0, 34.0, "MoMA_Charcoal", 0.04, 4.7, 5.5, 5.5)   # slab edges
    facade_piers(kit, poly, 0.0, 33.0, "MoMA_Charcoal", 0.06, 1.6, 0.14, edges=[0, 1])
    kit.box("MoMA_Charcoal", 42.6, -0.4, 33.0, 62.0, 32.0, 34.6)              # parapet
    wall_rect(kit, "Marble_White", "S", 0.0, 50.0, 61.0, 7.6, 8.4, off=0.08)   # signage band
    # --- Taniguchi (2004) gallery building: charcoal frame, big glazed panel
    p = rect(62.0, 0.0, 100.0, 24.0)
    kit.prism("MoMA_Charcoal", p, 0.0, 36.0)
    kit.prism("MoMA_Charcoal", rect(62.0, 24.0, 78.0, 61.0), 0.0, 36.0)
    kit.prism("MoMA_Charcoal", rect(78.0, 46.0, 100.0, 61.0), 0.0, 28.0)
    wall_rect(kit, "Storefront", "S", 0.0, 63.0, 99.0, 0.2, 5.6)
    wall_rect(kit, "Glass_Neighbor", "S", 0.0, 66.0, 97.0, 7.0, 32.0)
    facade_piers(kit, [(66.0, 0.0), (97.0, 0.0), (97.0, 1.0), (66.0, 1.0)], 7.0, 32.0,
                 "MoMA_Charcoal", 0.07, 1.55, 0.12, edges=[0])
    for z in (12.0, 17.0, 22.0, 27.0):
        wall_rect(kit, "MoMA_Charcoal", "S", 0.0, 66.0, 97.0, z - 0.15, z + 0.15, off=0.08)
    wall_rect(kit, "Thermolux", "S", 0.0, 62.0, 100.0, 33.4, 35.6, off=0.06)  # white glass top band
    wall_rect(kit, "Thermolux", "S", 0.0, 62.5, 65.2, 6.0, 33.0, off=0.06)    # white glass edge
    # 54th St side of the Taniguchi buildings
    facade_bands(kit, rect(62.0, 24.0, 78.0, 61.0), 0.0, 36.0, "Glass_Neighbor", 0.04, 1.0, 4.0, 4.5, edges=[2])
    facade_bands(kit, rect(78.0, 46.0, 100.0, 61.0), 0.0, 28.0, "Glass_Neighbor", 0.04, 1.0, 4.0, 4.5, edges=[2])
    # --- Museum Tower (Cesar Pelli, 1984) rising behind
    mt = rect(78.0, 25.0, 100.0, 45.0)
    kit.prism("Glass_Blue", mt, 36.0, 192.0)
    facade_bands(kit, mt, 36.0, 190.0, "Glass_Green", 0.03, 0.0, 3.2, 6.4)
    facade_bands(kit, mt, 38.6, 190.0, "Window_Dark", 0.035, 0.0, 0.5, 9.6)
    kit.box("Roof_Grey", 84.0, 30.0, 192.0, 94.0, 40.0, 197.0)
    # --- Goodwin & Stone 1939 building
    kit.prism("Marble_White", rect(100.0, 2.6, 118.0, 28.0), 0.0, 4.8)
    wall_rect(kit, "Storefront", "S", 2.6, 100.2, 117.8, 0.0, 4.6)
    kit.prism("Marble_White", rect(100.0, 0.0, 118.0, 28.0), 4.8, 22.6, bottom=True)
    wall_rect(kit, "Thermolux", "S", 0.0, 100.6, 117.4, 5.4, 13.2)
    for k in range(15):
        u = 100.6 + k * (16.8 / 14)
        wall_rect(kit, "Mullion_Alu", "S", 0.0, u - 0.05, u + 0.05, 5.4, 13.2, off=0.07)
    for zz in (8.0, 10.6):
        wall_rect(kit, "Mullion_Alu", "S", 0.0, 100.6, 117.4, zz - 0.05, zz + 0.05, off=0.07)
    for row, z in enumerate((14.4, 18.4)):
        for k in range(9):
            u = 101.2 + k * 1.9
            wall_rect(kit, "Window_Dark", "S", 0.0, u, u + 1.1, z, z + 1.9)
    kit.prism("Marble_White", rect(100.0, 3.5, 118.0, 28.0), 22.6, 26.0)
    wall_rect(kit, "Storefront", "S", 3.5, 100.4, 117.6, 22.8, 25.6)
    kit.box("Marble_White", 99.6, -0.6, 26.0, 118.4, 28.0, 26.6, bottom=True)  # roof canopy
    for k in range(6):
        octagon_down(kit, "Window_Dark", 102.5 + k * 2.6, 1.6, 25.99, 0.55)
    arc = [(103.0, 2.6)]
    for k in range(9):
        a = math.pi * k / 8
        arc.append((109.0 + 6.0 * math.cos(math.pi - a), 2.6 - 4.2 * math.sin(a) - 0.2))
    arc += [(115.0, 2.6)]
    arc = arc[:1] + [p for p in arc[1:-1]] + arc[-1:]
    kit.prism("Marble_White", [arc[0]] + arc[1:-1][::1] + [arc[-1]], 4.3, 4.7, bottom=True)
    # vertical museum sign blade
    kit.box("MoMA_Charcoal", 99.7, -1.2, 6.0, 100.0, 0.0, 20.0)
    # --- Philip Johnson 1964 east wing: black steel grid on dark glass
    jw = rect(118.0, 0.0, 140.0, 26.0)
    kit.prism("Window_Dark", jw, 0.0, 30.0)
    for k in range(9):
        x = 118.4 + k * 2.65
        kit.box("Metal_Dark", x - 0.15, -0.25, 0.0, x + 0.15, 0.0, 30.0)
    for z in (5.5, 11.0, 16.0, 21.0, 26.0, 29.4):
        kit.box("Metal_Dark", 118.0, -0.3, z - 0.3, 140.0, 0.0, z + 0.3)
    kit.box("MoMA_Charcoal", 118.0, 26.0, 0.0, 140.0, 32.0, 24.0)
    # --- Abby Aldrich Rockefeller Sculpture Garden
    kit.hquad("Garden_Paving", 100.0, 28.0, 135.0, 55.0, 0.01, group="Garden")
    kit.hquad("Pool_Dark", 108.0, 38.0, 128.0, 42.0, 0.02, group="Garden")
    kit.box("MoMA_Charcoal", 100.0, 55.0, 0.0, 135.0, 61.0, 6.0)             # 54th St wall
    kit.box("MoMA_Charcoal", 135.0, 32.0, 0.0, 140.0, 61.0, 8.0)
    for i, (x, y) in enumerate(((103, 31), (106, 33), (104, 51), (110, 52), (126, 51), (131, 47), (122, 31), (131, 34))):
        tree(kit, x, y, h=8.0, r=2.0, pit=False, seed=i)
    for (x, y, h) in ((114, 34, 2.4), (119, 47, 3.0), (127, 44, 1.8)):
        kit.box("Metal_Dark", x - 0.5, y - 0.5, 0.0, x + 0.5, y + 0.5, h)
    kit.cyl("Granite_Black", 112.0, 47.0, 0.0, 0.6, 1.2, 1.2, n=10, group="Bldg")


# ---------------------------------------------------------------- St Thomas
def st_thomas(kit):
    L = "Limestone_Church"
    # south aisle along 53rd St with lean-to roof
    kit.prism(L, rect(140.0, 0.0, 162.0, 13.0), 0.0, 15.0)
    yz_prism(kit, "Roof_Slate", [(0.0, 15.0), (13.0, 15.0), (13.0, 21.0)], 140.0, 162.0)
    # nave with steep gable, entrance front on 5th Ave (x = 175)
    kit.prism(L, rect(140.0, 13.0, 175.0, 33.0), 0.0, 30.0)
    yz_prism(kit, "Roof_Slate", [(13.0, 30.0), (33.0, 30.0), (23.0, 42.0)], 140.0, 172.0)
    yz_prism(kit, L, [(13.0, 30.0), (33.0, 30.0), (23.0, 43.0)], 172.0, 175.0)  # front gable
    # buttresses + lancets along 53rd St
    for k in range(5):
        x = 141.0 + k * 5.2
        kit.box(L, x - 0.5, -0.6, 0.0, x + 0.5, 0.0, 14.0)
        if k < 4:
            wall_ngon(kit, "Window_Dark", "S", 0.0, lancet(x + 1.4, x + 3.8, 3.5, 9.5))
            wall_ngon(kit, "Window_Dark", "S", 13.0, lancet(x + 1.4, x + 3.8, 21.5, 26.0))
    # tower at the 5th Ave / 53rd St corner
    kit.prism(L, rect(162.0, 0.0, 175.0, 13.0), 0.0, 54.0)
    kit.prism(L, rect(162.8, 0.8, 174.2, 12.2), 54.0, 74.0)
    kit.box(L, 162.4, 0.4, 73.5, 174.6, 12.6, 75.0)
    for (cx, cy) in ((163.2, 1.2), (173.8, 1.2), (173.8, 11.8), (163.2, 11.8)):
        kit.box(L, cx - 0.8, cy - 0.8, 54.0, cx + 0.8, cy + 0.8, 75.0)
        pyramid(kit, L, cx, cy, 75.0, 82.0, 0.8)
    for face, c, u0, u1 in (("S", 0.8, 164.8, 172.2), ("E", 174.2, 2.8, 10.2)):
        wall_ngon(kit, "Window_Dark", face, c, lancet(u0, u0 + 3.0, 57.0, 66.0))
        wall_ngon(kit, "Window_Dark", face, c, lancet(u1 - 3.0, u1, 57.0, 66.0))
    for face, c, u0 in (("S", 0.0, 166.0), ("E", 175.0, 4.0)):
        wall_ngon(kit, "Window_Dark", face, c, lancet(u0, u0 + 5.0, 18.0, 36.0))
    # 5th Ave front: great window + portal
    wall_ngon(kit, "Window_Dark", "E", 175.0, lancet(16.5, 29.5, 10.0, 18.0, n=7))
    wall_ngon(kit, "Wood_Walnut", "E", 175.0, lancet(20.5, 25.5, 0.0, 5.0))
    for y in (13.6, 32.4):
        kit.box(L, 175.0, y - 0.6, 0.0, 175.8, y + 0.6, 36.0)
        pyramid(kit, L, 175.4, y, 36.0, 40.0, 0.6)


# ---------------------------------------------------------------- others
def cbs(kit):
    """CBS 'Black Rock' (Saarinen 1965): dark granite triangular piers."""
    p = rect(-93.0, -72.0, -57.0, -32.0)
    kit.prism("Window_Dark", p, 0.0, 150.0)
    kit.box("Granite_Black", -92.9, -71.9, 150.0, -57.1, -32.1, 151.0)
    for i in range(4):
        a, b = p[i], p[(i + 1) % 4]
        (nx, ny), L = edge_normal(a, b)
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        cnt = int(L / 1.52)
        s0 = (L - cnt * 1.52) / 2
        for k in range(cnt + 1):
            s = s0 + k * 1.52
            p0 = (a[0] + ux * (s - 0.5), a[1] + uy * (s - 0.5))
            p1 = (a[0] + ux * (s + 0.5), a[1] + uy * (s + 0.5))
            pm = (a[0] + ux * s + nx * 0.55, a[1] + uy * s + ny * 0.55)
            for q0, q1 in ((p0, pm), (pm, p1)):
                kit.quad("Granite_Black", (q0[0], q0[1], 0.0), (q1[0], q1[1], 0.0),
                         (q1[0], q1[1], 151.0), (q0[0], q0[1], 151.0), collide=True)
            kit.ngon("Granite_Black", [(p0[0], p0[1], 151.0), (p1[0], p1[1], 151.0), (pm[0], pm[1], 151.0)])
    kit.box("Roof_Grey", -80.0, -58.0, 151.0, -70.0, -46.0, 155.0)


def tower_neighbours(kit):
    """53rd St frontage west of the tower (x -105 .. -3.5): hotels/offices."""
    # corner tower at 6th Ave
    building(kit, rect(-105.0, 0.0, -72.0, 38.0), 128.0, "Glass_Neighbor", win="Alu_Panel",
             style="glass", floor_h=3.9, ground_h=6.0, street_edges=[0, 3])
    building(kit, rect(-105.0, 38.0, -80.0, 61.0), 64.0, "Stone_Neighbor", street_edges=[2, 3])
    building(kit, rect(-72.0, 0.0, -46.0, 30.0), 82.0, "Stone_Light", floor_h=3.2, street_edges=[0])
    building(kit, rect(-46.0, 0.0, -24.0, 26.0), 46.0, "Brick_Neighbor", floor_h=3.3, street_edges=[0])
    # hotel abutting the tower: its east wall follows the tower's slanted
    # west edge 0.5 m clear (tower vertex (0,0)->(-3,19))
    p1 = [(-24.0, 0.0), (-0.506, 0.0), (-3.506, 19.0), (-24.0, 19.0)]
    p2 = rect(-24.0, 19.0, -4.0, 30.0)
    for p, e in ((p1, [0]), (p2, [])):
        building(kit, p, 66.0, "Stone_Neighbor", floor_h=3.25, pier_pitch=2.6, street_edges=e,
                 detail=2 if e else 1)


def baccarat(kit):
    p = rect(70.0, -50.0, 100.0, -22.0)
    building(kit, rect(70.0, -50.0, 100.0, -22.0), 24.0, "Stone_Light", floor_h=4.0,
             ground_h=6.0, street_edges=[2])
    kit.prism("Window_Dark", rect(72.0, -48.0, 98.0, -26.0), 24.0, 182.0)
    facade_piers(kit, rect(72.0, -48.0, 98.0, -26.0), 24.0, 181.0, "Glass_Neighbor", 0.04, 2.2, 1.2)
    facade_bands(kit, rect(72.0, -48.0, 98.0, -26.0), 24.0, 181.0, "Granite_Black", 0.06, 0.0, 0.35, 3.6)
    kit.box("Roof_Grey", 78.0, -42.0, 182.0, 92.0, -32.0, 186.0)
    del p


def six66(kit):
    """666 Fifth Ave (1957), embossed aluminium panels."""
    p = rect(127.0, -83.0, 175.0, -22.0)
    building(kit, p, 22.0, "Alu_Panel", floor_h=4.2, ground_h=5.5, street_edges=[0, 1, 2])
    q = rect(132.0, -76.0, 172.0, -28.0)
    kit.prism("Alu_Panel", q, 22.0, 148.0)
    facade_bands(kit, q, 22.0, 147.0, "Window_Dark", 0.03, 1.0, 2.6, 3.6)
    kit.box("Roof_Grey", 142.0, -60.0, 148.0, 160.0, -44.0, 154.0)


def hilton(kit):
    """New York Hilton Midtown: low podium + tall slab along 6th Ave."""
    building(kit, rect(-190.0, 0.0, -135.0, 61.0), 18.0, "Stone_Light", floor_h=4.5, ground_h=6.0,
             street_edges=[0, 1, 2], detail=1)
    slab = rect(-176.0, 6.0, -154.0, 56.0)
    kit.prism("Glass_Blue", slab, 18.0, 150.0)
    facade_piers(kit, slab, 18.0, 149.0, "Stone_Light", 0.05, 1.9, 0.9)
    facade_bands(kit, slab, 18.0, 149.0, "Stone_Light", 0.04, 0.0, 0.6, 2.9)
    kit.box("Roof_Grey", -170.0, 20.0, 150.0, -160.0, 42.0, 156.0)


def sixth_ave_towers(kit):
    # 1301 Avenue of the Americas (W side, 52nd-53rd)
    building(kit, rect(-190.0, -78.0, -142.0, -28.0), 186.0, "Glass_Neighbor", win="Granite_Black",
             style="glass", floor_h=4.0, ground_h=7.0, street_edges=[1])
    # 1345 Avenue of the Americas (W side, 54th-55th)
    building(kit, rect(-185.0, 92.0, -142.0, 136.0), 168.0, "Stone_Light", win="Window_Dark",
             floor_h=3.9, pier_pitch=1.6, pier_w=0.6, street_edges=[1])
