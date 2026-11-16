"""Render-time far context for exterior hero shots (not saved in the build).

The modelled Midtown site ends a few hundred metres from the tower; beyond
it, aerial views would see an empty ground plane. ensure(scene) adds, only
where the site has no geometry (occupancy grid of existing Site_* objects):
  * low-poly Manhattan-grid filler blocks (towers/walk-ups, few materials
    that already exist: Window_Dark / Stone_Neighbor / Brick_Neighbor /
    Glass_Neighbor / Roof_Grey) out to ~2.6 km,
  * Central Park (59th-110th St, 5th-8th Ave) as a lawn + tree-canopy slab,
  * the Hudson and East rivers,
  * a 12 km ground disc below everything.
All objects live in collection "RenderContext" and are deterministic.
Distances use the model frame (+Y = Manhattan north, blocks 83 m N-S,
avenues ~280-310 m E-W, W 53rd St at y = -11).
"""
import math
import random
import bpy

COL = "RenderContext"
CELL = 40.0


def _occupancy():
    occ = set()
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.name.startswith("Site_"):
            continue
        if any(k in ob.name for k in ("Ground", "Street", "Asphalt")):
            continue
        mw = ob.matrix_world
        me = ob.data
        for v in me.vertices:
            p = mw @ v.co
            occ.add((int(math.floor(p.x / CELL)), int(math.floor(p.y / CELL))))
    # the tower and Ext_ objects
    for ob in bpy.data.objects:
        if ob.type == "MESH" and ob.name.startswith("Ext_"):
            for c in ob.bound_box:
                p = ob.matrix_world @ __import__("mathutils").Vector(c)
                occ.add((int(math.floor(p.x / CELL)), int(math.floor(p.y / CELL))))
    return occ


def _free(occ, x0, y0, x1, y1, pad=1):
    for i in range(int(math.floor(x0 / CELL)) - pad, int(math.floor(x1 / CELL)) + 1 + pad):
        for j in range(int(math.floor(y0 / CELL)) - pad, int(math.floor(y1 / CELL)) + 1 + pad):
            if (i, j) in occ:
                return False
    return True


class _MB:
    def __init__(self):
        self.v, self.f = [], []

    def box(self, x0, y0, z0, x1, y1, z1, top=True):
        b = len(self.v)
        self.v += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        if top:
            self.f.append((b + 4, b + 5, b + 6, b + 7))
        for i in range(4):
            j = (i + 1) % 4
            self.f.append((b + i, b + j, b + 4 + j, b + 4 + i))

    def blob(self, cx, cy, cz, r, rz, rot):
        """Low-poly tree crown: hexagonal bipyramid with a raised waist."""
        b = len(self.v)
        self.v.append((cx, cy, cz - rz * 0.6))
        for i in range(6):
            a = rot + i * math.pi / 3
            self.v.append((cx + r * math.cos(a), cy + r * math.sin(a), cz + rz * (0.1 if i % 2 else -0.1)))
        self.v.append((cx, cy, cz + rz))
        for i in range(6):
            j = (i + 1) % 6
            self.f.append((b, b + 1 + j, b + 1 + i))
            self.f.append((b + 1 + i, b + 1 + j, b + 7))

    def quad(self, x0, y0, x1, y1, z):
        b = len(self.v)
        self.v += [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        self.f.append((b, b + 1, b + 2, b + 3))


def _mat(name, color):
    import config as C
    return C.mat(name, color=color)


def _finish(col, name, mb, mat):
    if not mb.f:
        return None
    me = bpy.data.meshes.new(name)
    me.from_pydata(mb.v, [], mb.f)
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    me.materials.append(mat)
    ob["collide"] = False
    return ob


# Manhattan grid in model coords
AVE_X = [-1600, -1300, -1000, -700, -445, -135, 175, 354, 510, 760, 1010, 1260]  # west building lines
AVE_W = 30.0
STREET_PITCH = 83.0
STREET_W = 22.0
STREET0 = -22.0          # W 53rd St south building line


def ensure(scene=None, radius=2600.0, seed=53):
    if bpy.data.collections.get(COL):
        return bpy.data.collections[COL]
    scene = scene or bpy.context.scene
    col = bpy.data.collections.new(COL)
    scene.collection.children.link(col)
    occ = _occupancy()
    rng = random.Random(seed)
    mats = {
        "Window_Dark": _mat("Window_Dark", (0.10, 0.12, 0.14, 1)),
        "Stone_Neighbor": _mat("Stone_Neighbor", (0.66, 0.62, 0.55, 1)),
        "Brick_Neighbor": _mat("Brick_Neighbor", (0.42, 0.26, 0.20, 1)),
        "Glass_Neighbor": _mat("Glass_Neighbor", (0.18, 0.24, 0.30, 1)),
        "Stone_Light": _mat("Stone_Light", (0.78, 0.75, 0.68, 1)),
        "Roof_Grey": _mat("Roof_Grey", (0.38, 0.38, 0.38, 1)),
    }
    mbs = {k: _MB() for k in mats}
    roofs = _MB()
    park_x0, park_x1 = -700.0 + AVE_W, 175.0          # 8th Ave .. 5th Ave
    park_y0 = STREET0 + 7 * STREET_PITCH               # Central Park South (59th St)
    park_y1 = park_y0 + 4000.0
    hudson_x = -1650.0
    east_x = 1500.0
    for ai in range(len(AVE_X) - 1):
        bx0, bx1 = AVE_X[ai] + AVE_W, AVE_X[ai + 1]
        for k in range(-40, 50):
            by0 = STREET0 + k * STREET_PITCH + STREET_W
            by1 = by0 + STREET_PITCH - STREET_W
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            dist = math.hypot(cx - 20, cy - 10)
            if dist > radius or bx0 < hudson_x or bx1 > east_x:
                continue
            if park_x0 - 5 < cx < park_x1 + 5 and by1 > park_y0:
                continue
            if not _free(occ, bx0, by0, bx1, by1, pad=0):
                continue
            # downtown/midtown density falls off with distance; avenue frontage taller
            x = bx0
            while x < bx1 - 6:
                w = min(bx1 - x, rng.uniform(18, 60))
                for (y0, y1) in ((by0, by0 + (by1 - by0) * 0.5), (by0 + (by1 - by0) * 0.5, by1)):
                    # Midtown core is tall; the Upper West/East Sides and
                    # Hell's Kitchen are mostly 5-20 storeys.
                    core = max(0.0, 1.0 - dist / 1400.0)
                    tall = rng.random() < 0.05 + 0.12 * core
                    h = rng.uniform(60, 120 + 120 * core) if tall else \
                        rng.lognormvariate(math.log(18 + 22 * core), 0.45)
                    if (x - bx0) < 40 or (bx1 - x - w) < 40:
                        h *= 1.3
                    kind = rng.choices(list(mats), weights=(3, 2, 4, 1, 2, 0))[0] if not tall else \
                        rng.choice(["Glass_Neighbor", "Window_Dark", "Glass_Neighbor", "Stone_Neighbor"])
                    if kind == "Roof_Grey":
                        kind = "Stone_Neighbor"
                    mbs[kind].box(x + 0.5, y0 + 0.5, 0.0, x + w - 0.5, y1 - 0.5, h, top=False)
                    roofs.quad(x + 0.5, y0 + 0.5, x + w - 0.5, y1 - 0.5, h)
                    if tall and rng.random() < 0.6:  # setback crown
                        ins = min(w, y1 - y0) * 0.2
                        h2 = h + rng.uniform(8, 30)
                        mbs[kind].box(x + ins, y0 + ins, h, x + w - ins, y1 - ins, h2, top=False)
                        roofs.quad(x + ins, y0 + ins, x + w - ins, y1 - ins, h2)
                x += w
    for k, mb in mbs.items():
        _finish(col, "Ctx_" + k, mb, mats[k])
    _finish(col, "Ctx_Roofs", roofs, mats["Roof_Grey"])
    # Central Park: lawn + canopy slab (foliage material, bumpy)
    park = _MB()
    park.quad(park_x0, park_y0, park_x1, park_y1, 0.05)
    _finish(col, "Ctx_Park_Lawn", park, _mat("Grass_Park", (0.10, 0.20, 0.06, 1)))
    canopy = _MB()
    gy = park_y0 + 15
    while gy < park_y1 - 15:
        gx = park_x0 + 15
        while gx < park_x1 - 15:
            if rng.random() < 0.55:
                s = rng.uniform(8, 18)
                h = rng.uniform(10, 18)
                canopy.blob(gx + rng.uniform(-5, 5), gy + rng.uniform(-5, 5), h - s * 0.35, s / 2,
                            s * 0.35, rng.uniform(0, math.pi))
            gx += 22
        gy += 22
    _finish(col, "Ctx_Park_Trees", canopy, _mat("Foliage", (0.10, 0.25, 0.08, 1)))
    # rivers + ground disc
    water = _MB()
    water.quad(hudson_x - 1300, -8000, hudson_x - 150, 8000, -0.5)    # Hudson ~1.2 km wide
    water.quad(east_x + 100, -8000, east_x + 450, 8000, -0.5)        # East River
    _finish(col, "Ctx_Rivers", water, _mat("River_Water", (0.04, 0.07, 0.08, 1)))
    ground = _MB()
    for (x0, y0, x1, y1) in ((-8000, -8000, 8000, -1200), (-8000, 1200, 8000, 8000),
                             (-8000, -1200, -1200, 1200), (1200, -1200, 8000, 1200)):
        ground.quad(x0, y0, x1, y1, -0.2)
    _finish(col, "Ctx_Ground", ground, _mat("Asphalt", (0.06, 0.06, 0.065, 1)))
    # boroughs across the rivers: low, dense, hazy (Queens / New Jersey)
    far = _MB()
    for x_lo, x_hi in ((-9000, hudson_x - 1300), (east_x + 450, 9000)):
        x = x_lo
        while x < x_hi:
            y = -6000.0
            while y < 6000:
                if rng.random() < 0.7:
                    h = rng.lognormvariate(math.log(14), 0.5) * (2.5 if rng.random() < 0.05 else 1)
                    far.box(x, y, 0, x + rng.uniform(30, 70), y + rng.uniform(30, 70), h)
                y += 90
            x += 90
    _finish(col, "Ctx_Far_Boroughs", far, mats["Brick_Neighbor"])
    from modules import materials
    for m in ("Grass_Park", "River_Water"):
        materials.build_material(bpy.data.materials[m], force=True)
    print(f"[context] far city: {sum(len(mb.f) for mb in mbs.values())} faces, park + rivers")
    return col


def remove():
    col = bpy.data.collections.get(COL)
    if col is None:
        return
    for ob in list(col.objects):
        me = ob.data
        bpy.data.objects.remove(ob)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
    bpy.data.collections.remove(col)
