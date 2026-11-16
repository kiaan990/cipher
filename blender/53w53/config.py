"""Shared constants and helpers for the 53 West 53 model.

Every module imports from here so the facade, floors, site and walk system
agree on one geometry. Units are metres. Axes:
  +X = east along W 53rd St, +Y = north (away from the street), +Z = up.
The 53rd St curb line is y = -6, the building's street wall is y = 0.

This is an interpretive model of Jean Nouvel's tower (completed 2019):
~320 m (1,050 ft) tall, 77 storeys, a slender faceted spire wrapped in an
exposed concrete diagrid, with MoMA galleries on podium floors 2, 4 and 5.
"""
import math
import bpy
import bmesh

# ---------------------------------------------------------------- dimensions
HEIGHT = 320.0             # roof tip
NUM_FLOORS = 77            # occupied storeys (floor 1 = ground)
GROUND_FLOOR_H = 7.0       # double-height lobby / gallery
PODIUM_FLOOR_H = 5.5       # floors 2-6 (MoMA galleries on 2, 4, 5)
TYPICAL_FLOOR_H = 3.6      # residential floors
SLAB_T = 0.30              # structural slab thickness
MOMA_FLOORS = (2, 4, 5)
AMENITY_FLOORS = (1, 6, 7)   # lobby, pool, amenity (approximation)
PENTHOUSE_FLOOR = 77

# Footprint at grade: a convex pentagon (counter-clockwise), ~46 x 30 m.
FOOTPRINT = [(0.0, 0.0), (42.0, 0.0), (46.0, 22.0), (19.0, 30.0), (-3.0, 19.0)]

# The spire: each sloped facet is a half-plane n.(x,y) <= d - k*(z - z0),
# active above z0.  Section at height z = FOOTPRINT clipped by all of them.
# (nx, ny) is a unit vector, d its offset at z0, k the inward slope (m per m).
# The three facets are solved so their planes meet in a single point: the
# spire tip at (SPIRE_TIP_X, SPIRE_TIP_Y, SPIRE_TIP_Z).
SPIRE_TIP_X, SPIRE_TIP_Y, SPIRE_TIP_Z = 21.0, 14.0, 325.0


def _facet(nx, ny, d, z0):
    k = (d - (nx * SPIRE_TIP_X + ny * SPIRE_TIP_Y)) / (SPIRE_TIP_Z - z0)
    return ((nx, ny), d, z0, k)


_SPIRE_FACETS = [
    _facet(0.0, -1.0, 0.0, 170.0),       # south face (53rd St) leans north
    _facet(0.894, 0.447, 51.0, 205.0),   # east face leans west
    _facet(-0.894, 0.447, 9.0, 140.0),   # west face leans east
]


def floor_z(n):
    """Elevation of the top of slab for floor n (1-based). floor_z(1) == 0."""
    if n <= 1:
        return 0.0
    z = GROUND_FLOOR_H
    for i in range(2, n):
        z += PODIUM_FLOOR_H if i <= 6 else TYPICAL_FLOOR_H
    return z


def floor_height(n):
    if n == 1:
        return GROUND_FLOOR_H
    return PODIUM_FLOOR_H if n <= 6 else TYPICAL_FLOOR_H


def roof_z():
    """Top of the last occupied floor's ceiling (the spire continues above)."""
    return floor_z(NUM_FLOORS) + floor_height(NUM_FLOORS)


def _clip(poly, nx, ny, d):
    """Sutherland-Hodgman clip of a polygon by half-plane nx*x + ny*y <= d."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da = nx * a[0] + ny * a[1] - d
        db = nx * b[0] + ny * b[1] - d
        if da <= 0:
            out.append(a)
        if (da < 0) != (db < 0) and da != db:
            t = da / (da - db)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return out


def section(z):
    """Footprint polygon (list of (x, y), CCW, convex) at height z.

    Returns [] above the spire tip. Shared by facade, slabs and walk system.
    """
    poly = list(FOOTPRINT)
    for (nx, ny), d, z0, k in _SPIRE_FACETS:
        if z > z0:
            poly = _clip(poly, nx, ny, d - k * (z - z0))
            if len(poly) < 3:
                return []
    return _dedupe(poly, 0.6)


def _dedupe(poly, tol):
    """Drop vertices closer than tol to the previous kept one (no slivers)."""
    out = []
    for p in poly:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol:
            out.append(p)
    while len(out) > 3 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < tol:
        out.pop()
    return out if len(out) >= 3 else []


def inset(poly, dist):
    """Inset a convex CCW polygon by dist (dist must be >= 0). Robust: clips
    the polygon by every edge's offset half-plane. Returns [] if it vanishes."""
    n = len(poly)
    out = list(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        nx, ny = dy / L, -dx / L          # outward normal for CCW
        out = _clip(out, nx, ny, nx * x1 + ny * y1 - dist)
        if len(out) < 3:
            return []
    return _dedupe(out, 0.05) if dist > 0 else out


def centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


# Central core (elevators + scissor stairs), constant all the way up to
# floor CORE_TOP_FLOOR.  Axis-aligned rectangle (xmin, ymin, xmax, ymax).
CORE = (14.0, 9.0, 28.0, 19.0)
STAIR = (14.0, 9.0, 19.0, 19.0)       # west part of core: stair shaft (switchback)
ELEVATORS = (19.0, 9.0, 28.0, 19.0)   # east part of core: 3 cars, doors face north
# Near the tip the plate is too small for the full core; those floors use a
# compact core (one stair + one lift).  Use core_rect(n) / stair_rect(n) /
# elevator_rect(n) rather than the constants above.
CORE_SMALL = (19.0, 11.8, 25.0, 16.8)
STAIR_SMALL = (19.0, 11.8, 22.0, 16.8)
ELEVATOR_SMALL = (22.0, 11.8, 25.0, 16.8)


def _rect_inside(rect, poly, margin):
    x0, y0, x1, y1 = rect
    ip = inset(poly, margin) if poly else []
    if len(ip) < 3:
        return False
    for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        for i in range(len(ip)):
            (ax, ay), (bx, by) = ip[i], ip[(i + 1) % len(ip)]
            if (bx - ax) * (py - ay) - (by - ay) * (px - ax) < 0:
                return False
    return True


def plate(n):
    """Floor-plate polygon for floor n (section at the floor's ceiling, so
    walls never poke through the sloping facade)."""
    return section(floor_z(n) + floor_height(n))


def core_is_small(n):
    return not _rect_inside(CORE, plate(n), 3.0)


def core_rect(n):
    return CORE_SMALL if core_is_small(n) else CORE


def stair_rect(n):
    return STAIR_SMALL if core_is_small(n) else STAIR


def elevator_rect(n):
    return ELEVATOR_SMALL if core_is_small(n) else ELEVATORS
ENTRANCE = (21.0, 0.0)                # main door on 53rd St (lobby)

# ---------------------------------------------------------------- scene helpers
def collection(name, parent=None):
    """Get or create a collection linked under parent (or scene root)."""
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


_MATS = {
    # name: (base colour RGBA, metallic, roughness, transmission, alpha)
    "Concrete_Diagrid": ((0.62, 0.60, 0.56, 1), 0.0, 0.75, 0.0, 1.0),
    "Glass_Curtain":    ((0.30, 0.38, 0.42, 1), 0.0, 0.05, 0.9, 0.35),
    "Mullion_Alu":      ((0.55, 0.56, 0.58, 1), 0.9, 0.35, 0.0, 1.0),
    "Slab_Concrete":    ((0.70, 0.69, 0.66, 1), 0.0, 0.80, 0.0, 1.0),
    "Floor_Oak":        ((0.55, 0.40, 0.26, 1), 0.0, 0.45, 0.0, 1.0),
    "Floor_Stone":      ((0.82, 0.80, 0.76, 1), 0.0, 0.30, 0.0, 1.0),
    "Wall_White":       ((0.90, 0.89, 0.86, 1), 0.0, 0.85, 0.0, 1.0),
    "Core_Wall":        ((0.48, 0.47, 0.45, 1), 0.0, 0.80, 0.0, 1.0),
    "Metal_Dark":       ((0.08, 0.08, 0.09, 1), 0.8, 0.35, 0.0, 1.0),
    "Fabric_Grey":      ((0.35, 0.35, 0.36, 1), 0.0, 0.95, 0.0, 1.0),
    "Wood_Walnut":      ((0.25, 0.15, 0.09, 1), 0.0, 0.50, 0.0, 1.0),
    "Asphalt":          ((0.06, 0.06, 0.065, 1), 0.0, 0.90, 0.0, 1.0),
    "Sidewalk":         ((0.55, 0.54, 0.52, 1), 0.0, 0.85, 0.0, 1.0),
    "Brick_Neighbor":   ((0.42, 0.26, 0.20, 1), 0.0, 0.85, 0.0, 1.0),
    "Stone_Neighbor":   ((0.66, 0.62, 0.55, 1), 0.0, 0.80, 0.0, 1.0),
    "Glass_Neighbor":   ((0.18, 0.24, 0.30, 1), 0.3, 0.15, 0.0, 1.0),
    "Foliage":          ((0.10, 0.25, 0.08, 1), 0.0, 0.80, 0.0, 1.0),
    "Water_Pool":       ((0.10, 0.45, 0.55, 1), 0.0, 0.05, 0.5, 0.8),
    "Light_Emit":       ((1.00, 0.92, 0.80, 1), 0.0, 0.50, 0.0, 1.0),
    "Gallery_Wall":     ((0.96, 0.96, 0.95, 1), 0.0, 0.90, 0.0, 1.0),
}


def mat(name, color=None):
    """Get or create a Principled BSDF material. Unknown names need color."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    spec = _MATS.get(name) or (color or (0.8, 0.8, 0.8, 1), 0.0, 0.6, 0.0, 1.0)
    rgba, metal, rough, trans, alpha = spec
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = rgba
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
        for key in ("Transmission Weight", "Transmission"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = trans
                break
        bsdf.inputs["Alpha"].default_value = alpha
        if name == "Light_Emit":
            for key in ("Emission Color", "Emission"):
                if key in bsdf.inputs:
                    bsdf.inputs[key].default_value = rgba
                    break
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 6.0
    if alpha < 1.0:
        for attr, val in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
            if hasattr(m, attr):
                try:
                    setattr(m, attr, val)
                except Exception:
                    pass
    return m


def mesh_object(name, verts, faces, material=None, col=None, smooth=False):
    """Create a mesh object from raw verts/faces (faces = index tuples)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.validate(clean_customdata=False)
    me.update()
    ob = bpy.data.objects.new(name, me)
    (col or bpy.context.scene.collection).objects.link(ob)
    if material is not None:
        me.materials.append(material if not isinstance(material, str) else mat(material))
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return ob


def prism(name, poly, z0, z1, material=None, col=None):
    """Extrude a 2D polygon (CCW) from z0 to z1 into a closed solid."""
    n = len(poly)
    verts = [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    return mesh_object(name, verts, faces, material, col)


def box(name, x0, y0, z0, x1, y1, z1, material=None, col=None):
    return prism(name, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, material, col)


class MeshBuilder:
    """Accumulate many boxes/prisms into ONE mesh (keeps object count sane).

    Use one builder per material group, then .finish() to create the object.
    """

    def __init__(self, name, material=None, col=None):
        self.name, self.material, self.col = name, material, col
        self.verts, self.faces = [], []

    def add_prism(self, poly, z0, z1):
        b = len(self.verts)
        n = len(poly)
        self.verts += [(x, y, z0) for x, y in poly] + [(x, y, z1) for x, y in poly]
        self.faces.append(tuple(b + i for i in reversed(range(n))))
        self.faces.append(tuple(b + n + i for i in range(n)))
        for i in range(n):
            j = (i + 1) % n
            self.faces.append((b + i, b + j, b + n + j, b + n + i))

    def add_box(self, x0, y0, z0, x1, y1, z1):
        self.add_prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1)

    def add_quad(self, a, b, c, d):
        base = len(self.verts)
        self.verts += [a, b, c, d]
        self.faces.append((base, base + 1, base + 2, base + 3))

    def add_beam(self, p0, p1, w, h=None):
        """Square-ish bar from 3D point p0 to p1 with width w (depth h)."""
        import mathutils
        h = h or w
        a, b = mathutils.Vector(p0), mathutils.Vector(p1)
        axis = b - a
        if axis.length < 1e-6:
            return
        axis.normalize()
        up = mathutils.Vector((0, 0, 1)) if abs(axis.z) < 0.95 else mathutils.Vector((1, 0, 0))
        u = axis.cross(up).normalized() * (w / 2)
        v = axis.cross(u).normalized() * (h / 2)
        corners = [-u - v, u - v, u + v, -u + v]
        base = len(self.verts)
        self.verts += [tuple(a + c) for c in corners] + [tuple(b + c) for c in corners]
        self.faces += [(base + 3, base + 2, base + 1, base), (base + 4, base + 5, base + 6, base + 7)]
        for i in range(4):
            j = (i + 1) % 4
            self.faces.append((base + i, base + j, base + 4 + j, base + 4 + i))

    def extend(self, verts, faces):
        b = len(self.verts)
        self.verts += [tuple(v) for v in verts]
        self.faces += [tuple(b + i for i in f) for f in faces]

    def finish(self):
        if not self.faces:
            return None
        return mesh_object(self.name, self.verts, self.faces, self.material, self.col)


def eevee_engine():
    """Engine id that works on Blender 4.2-4.x and 5.x."""
    items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in items else "BLENDER_EEVEE"
