"""Photoreal PBR materials pass (Cycles).

`apply(ctx)` rebuilds the node tree of every material in the file from a
recipe chosen by material NAME (see RULES below). Unknown names get a generic
treatment derived from their base colour (micro roughness variation + subtle
bump), so materials added later by other modules still look physical.

Everything is procedural (no image files). Objects are built at the world
origin without UVs, so textures use Object coordinates (== world metres);
directional patterns (planks, bricks, panels, grain) use a cheap normal-based
"box projection": u = x*|Ny| + y*|Nx| on walls, (x, y) on floors.

Material.diffuse_color is kept = base colour so Workbench previews still work.
Nodes whose label starts with "CTRL_" are knobs that lighting presets tweak
(see lighting.set_controls): CTRL_CITY_GLOW (lit neighbour windows),
CTRL_INT_LIGHT (interior emissive panels), CTRL_STREET (street/shop glow).

Runs on Blender 4.2 - 5.x (socket names resolved defensively).
"""
import colorsys
import bpy

VERSION = 3  # bump to force a rebuild of materials already processed

# ------------------------------------------------------------------ helpers


def _first(sockets, *names):
    for n in names:
        s = sockets.get(n)
        if s is not None:
            return s
    return None


class T:
    """Tiny node-tree DSL."""

    def __init__(self, mat):
        mat.use_nodes = True
        self.mat = mat
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.x = 0
        self.out = self.n("ShaderNodeOutputMaterial")
        self.out.location = (1400, 0)
        self._tc = None

    # node creation / linking ------------------------------------------------
    def n(self, kind, label=None, **props):
        node = self.nt.nodes.new(kind)
        node.location = (self.x, -len(self.nt.nodes) * 40)
        self.x = (self.x + 180) % 1200
        if label:
            node.label = label
        for k, v in props.items():
            try:
                setattr(node, k, v)
            except Exception:
                pass
        return node

    def sock(self, node, name, out=False):
        if not hasattr(node, "inputs"):
            return node
        coll = node.outputs if out else node.inputs
        if isinstance(name, int):
            return coll[name]
        s = coll.get(name)
        if s is None:
            # ShaderNodeMix style identifiers (A_Color, Result_Float, ...)
            for c in coll:
                if c.identifier == name or (c.name == name and c.enabled):
                    return c
        return s

    def set(self, node, name, value):
        """Set an input: value may be a constant or an output socket."""
        names = name if isinstance(name, (list, tuple)) and not isinstance(name, str) else [name]
        for nm in names:
            s = self.sock(node, nm)
            if s is None:
                continue
            if isinstance(value, bpy.types.NodeSocket):
                self.nt.links.new(value, s)
            else:
                try:
                    s.default_value = value
                except Exception:
                    try:
                        s.default_value = value[:len(s.default_value)]
                    except Exception:
                        pass
            return s
        return None

    def o(self, node, name=0):
        return self.sock(node, name, out=True)

    # common building blocks --------------------------------------------------
    def tc(self):
        if self._tc is None:
            self._tc = self.n("ShaderNodeTexCoord")
        return self._tc

    def obj(self):
        return self.o(self.tc(), "Object")

    def geo(self):
        if not hasattr(self, "_geo"):
            self._geo = self.n("ShaderNodeNewGeometry")
        return self._geo

    def math(self, op, a, b=0.0, clamp=False):
        m = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(m, 0, a)
        self.set(m, 1, b)
        return self.o(m)

    def vmath(self, op, a, b=(0, 0, 0)):
        m = self.n("ShaderNodeVectorMath", operation=op)
        self.set(m, 0, a)
        self.set(m, 1, b)
        return self.o(m, "Value" if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else "Vector")

    def scale_vec(self, v, s):
        return self.vmath("MULTIPLY", v, s)

    def sep(self, v):
        n = self.n("ShaderNodeSeparateXYZ")
        self.set(n, 0, v)
        return self.o(n, "X"), self.o(n, "Y"), self.o(n, "Z")

    def comb(self, x, y, z):
        n = self.n("ShaderNodeCombineXYZ")
        self.set(n, "X", x)
        self.set(n, "Y", y)
        self.set(n, "Z", z)
        return self.o(n)

    def noise(self, vec, scale, detail=4.0, rough=0.5, distortion=0.0, dims="3D", out="Fac"):
        n = self.n("ShaderNodeTexNoise", noise_dimensions=dims)
        if vec is not None:
            self.set(n, "Vector", vec)
        self.set(n, "Scale", scale)
        self.set(n, "Detail", detail)
        self.set(n, "Roughness", rough)
        self.set(n, "Distortion", distortion)
        return self.o(n, out)

    def voronoi(self, vec, scale, feature="F1", out="Distance", rnd=1.0):
        n = self.n("ShaderNodeTexVoronoi", feature=feature)
        if vec is not None:
            self.set(n, "Vector", vec)
        self.set(n, "Scale", scale)
        self.set(n, "Randomness", rnd)
        return self.o(n, out)

    def white(self, vec, out="Value"):
        n = self.n("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
        self.set(n, "Vector", vec)
        return self.o(n, out)

    def ramp(self, fac, stops):
        """stops: [(pos, (r,g,b,a)) | (pos, v)] -> colour output."""
        r = self.n("ShaderNodeValToRGB")
        self.set(r, "Fac", fac)
        els = r.color_ramp.elements
        while len(els) > 1:
            els.remove(els[-1])
        for i, (p, c) in enumerate(stops):
            if not isinstance(c, (tuple, list)):
                c = (c, c, c, 1.0)
            elif len(c) == 3:
                c = (*c, 1.0)
            e = els[0] if i == 0 else els.new(p)
            e.position = p
            e.color = c
        return self.o(r, "Color")

    def mix(self, fac, a, b, blend="MIX", kind="RGBA"):
        m = self.n("ShaderNodeMix", data_type=kind, blend_type=blend)
        suffix = {"RGBA": "Color", "FLOAT": "Float", "VECTOR": "Vector"}[kind]
        self.set(m, "Factor", fac)
        for ident, val in (("A_" + suffix, a), ("B_" + suffix, b)):
            s = next((s for s in m.inputs if s.identifier == ident), None)
            if isinstance(val, bpy.types.NodeSocket):
                self.nt.links.new(val, s)
            else:
                s.default_value = val
        return next(s for s in m.outputs if s.identifier == "Result_" + suffix)

    def maprange(self, v, a0, a1, b0, b1, clamp=True):
        m = self.n("ShaderNodeMapRange", clamp=clamp)
        self.set(m, "Value", v)
        self.set(m, "From Min", a0)
        self.set(m, "From Max", a1)
        self.set(m, "To Min", b0)
        self.set(m, "To Max", b1)
        return self.o(m, "Result")

    def hsv(self, col, h=0.5, s=1.0, v=1.0):
        n = self.n("ShaderNodeHueSaturation")
        self.set(n, "Color", col)
        self.set(n, "Hue", h)
        self.set(n, "Saturation", s)
        self.set(n, "Value", v)
        return self.o(n)

    def value(self, v, label=None):
        n = self.n("ShaderNodeValue", label=label)
        n.outputs[0].default_value = v
        return n.outputs[0]

    def bump(self, height, strength=0.1, distance=0.01, normal=None):
        b = self.n("ShaderNodeBump")
        self.set(b, "Height", height)
        self.set(b, "Strength", strength)
        self.set(b, "Distance", distance)
        if normal is not None:
            self.set(b, "Normal", normal)
        return self.o(b, "Normal")

    def blackbody(self, kelvin):
        b = self.n("ShaderNodeBlackbody")
        self.set(b, "Temperature", kelvin)
        return self.o(b)

    def facemap(self):
        """Normal-based planar coords: (u, v) on walls / floors, metres.
        Returns (u, v, is_floor) where is_floor = |Nz| > 0.5."""
        p = self.obj()
        x, y, z = self.sep(p)
        nx, ny, nz = self.sep(self.o(self.geo(), "Normal"))
        ax = self.math("ABSOLUTE", nx)
        ay = self.math("ABSOLUTE", ny)
        az = self.math("ABSOLUTE", nz)
        flo = self.math("GREATER_THAN", az, 0.5)
        # walls: u along the wall, v = z
        wu = self.math("ADD", self.math("MULTIPLY", x, self.math("GREATER_THAN", ay, ax)),
                       self.math("MULTIPLY", y, self.math("GREATER_THAN", ax, ay)))
        u = self.mix(flo, wu, x, kind="FLOAT")
        v = self.mix(flo, z, y, kind="FLOAT")
        return u, v, flo

    # BSDF ----------------------------------------------------------------------
    def principled(self, **kw):
        b = self.n("ShaderNodeBsdfPrincipled")
        try:
            b.subsurface_method = "RANDOM_WALK"
        except Exception:
            pass
        names = {
            "base": ("Base Color",), "metal": ("Metallic",), "rough": ("Roughness",),
            "ior": ("IOR",), "spec": ("Specular IOR Level", "Specular"),
            "trans": ("Transmission Weight", "Transmission"),
            "coat": ("Coat Weight", "Clearcoat"), "coat_rough": ("Coat Roughness", "Clearcoat Roughness"),
            "sheen": ("Sheen Weight", "Sheen"), "sheen_rough": ("Sheen Roughness",),
            "sheen_tint": ("Sheen Tint",),
            "aniso": ("Anisotropic",), "aniso_rot": ("Anisotropic Rotation",),
            "sss": ("Subsurface Weight", "Subsurface"), "sss_radius": ("Subsurface Radius",),
            "sss_scale": ("Subsurface Scale",),
            "emit": ("Emission Color", "Emission"), "emit_str": ("Emission Strength",),
            "alpha": ("Alpha",), "normal": ("Normal",), "coat_normal": ("Coat Normal",),
            "tangent": ("Tangent",), "thin_film": ("Thin Film Thickness",),
        }
        for k, v in kw.items():
            if v is None:
                continue
            self.set(b, names[k], v)
        return b

    def output(self, shader):
        self.nt.links.new(shader if isinstance(shader, bpy.types.NodeSocket) else self.o(shader, 0),
                          self.out.inputs["Surface"])


def _base_color(mat):
    # once processed, the authoring colour is kept in mat["pbr_base"]
    # (our own node trees link Base Color, so its default value is meaningless)
    if "pbr_base" in mat:
        return tuple(mat["pbr_base"])
    if mat.get("pbr_recipe"):
        return tuple(mat.diffuse_color)
    try:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None:
            c = tuple(bsdf.inputs["Base Color"].default_value)
            if sum(c[:3]) > 0:
                return c
    except Exception:
        pass
    return tuple(mat.diffuse_color)


def _lin(c, k=1.0):
    return (c[0] * k, c[1] * k, c[2] * k, 1.0)


def _set_opaque(mat):
    for attr, val in (("blend_method", "OPAQUE"), ("surface_render_method", "DITHERED"),
                      ("shadow_method", "OPAQUE")):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, val)
            except Exception:
                pass


# ------------------------------------------------------------------ recipes
# Each recipe(t, base_rgba, **params) builds a shader and wires the output.

def color_var(t, base, scale=1.5, amount=0.12, hue=0.01, vec=None):
    """Base colour with low-frequency value/hue mottling."""
    n = t.noise(vec or t.obj(), scale, 3.0, 0.55)
    v = t.maprange(n, 0.3, 0.7, 1.0 - amount, 1.0 + amount)
    hh = t.maprange(t.noise(vec or t.obj(), scale * 0.37, 2.0, 0.5), 0.3, 0.7, 0.5 - hue, 0.5 + hue)
    return t.hsv(base, hh, 1.0, v)


def rough_var(t, r, amount=0.15, scale=4.0):
    n = t.noise(t.obj(), scale, 6.0, 0.6)
    return t.maprange(n, 0.25, 0.75, max(0.0, r - amount), min(1.0, r + amount))


def micro_bump(t, scale=60.0, strength=0.05, normal=None):
    n = t.noise(t.obj(), scale, 8.0, 0.65)
    return t.bump(n, strength, 0.004, normal)


def r_generic(t, base, rough=0.55, metal=0.0, bump=0.04, amount=0.08):
    col = color_var(t, base, 1.2, amount)
    b = t.principled(base=col, metal=metal, rough=rough_var(t, rough, 0.12),
                     normal=micro_bump(t, 40.0, bump))
    t.output(b)


def r_paint(t, base, rough=0.75):
    """Matte painted plaster: barely visible roller texture."""
    col = color_var(t, base, 0.6, 0.025, 0.002)
    b = t.principled(base=col, rough=rough_var(t, rough, 0.08, 8.0),
                     normal=micro_bump(t, 120.0, 0.025))
    t.output(b)


def r_concrete(t, base, rough=0.82, stain=0.25, pores=0.12, boardform=False):
    p = t.obj()
    big = t.noise(p, 0.35, 4.0, 0.6)
    mid = t.noise(p, 3.0, 6.0, 0.6)
    # vertical rain streaks: noise stretched along Z
    streak = t.noise(t.vmath("MULTIPLY", p, (2.5, 2.5, 0.12)), 1.0, 5.0, 0.6)
    tone = t.mix(0.5, big, mid, kind="FLOAT")
    col = t.hsv(base, 0.5, 0.95, t.maprange(tone, 0.3, 0.7, 0.86, 1.10))
    dirt = t.maprange(streak, 0.45, 0.75, 0.0, stain)
    col = t.mix(dirt, col, _lin(base, 0.55), blend="MULTIPLY")
    pore = t.voronoi(p, 90.0, "F1", "Distance")
    pore_h = t.maprange(pore, 0.0, 0.18, 0.0, 1.0)
    h = t.math("ADD", t.math("MULTIPLY", mid, 0.6), t.math("MULTIPLY", pore_h, pores))
    if boardform:
        u, v, flo = t.facemap()
        board = t.math("FRACT", t.math("MULTIPLY", v, 1 / 0.15))
        h = t.math("ADD", h, t.math("MULTIPLY", t.maprange(board, 0.0, 0.06, 0.0, 0.3), 1.0))
    r = t.maprange(t.math("ADD", tone, t.math("MULTIPLY", dirt, -0.5)), 0.2, 0.8, rough - 0.12, min(1, rough + 0.1))
    b = t.principled(base=col, rough=r, normal=t.bump(h, 0.18, 0.01))
    t.output(b)


def r_wood(t, base, rough=0.45, plank_w=0.19, plank_l=2.2, coat=0.15, cerused=0.0, ring_scale=6.0):
    """Oak/walnut: planks (floors) or vertical panels (walls), grain via wave+noise."""
    fu, fv, flo = t.facemap()
    # floors: boards run along x, rows across y; walls: boards/panels run
    # vertically (along z) with vertical seams every plank_w along the wall
    u = t.mix(flo, fv, fu, kind="FLOAT")
    v = t.mix(flo, fu, fv, kind="FLOAT")
    # plank index: rows across plank_w, staggered joints along plank_l
    row = t.math("FLOOR", t.math("DIVIDE", v, plank_w))
    off = t.math("MULTIPLY", t.white(t.comb(row, 0.0, 3.1)), plank_l)
    along = t.math("ADD", u, off)
    col_i = t.math("FLOOR", t.math("DIVIDE", along, plank_l))
    pid = t.comb(row, col_i, 0.0)
    rnd = t.white(pid)
    rnd2 = t.white(t.comb(col_i, row, 7.0))
    # local grain coords: long along u
    gx = along
    gy = t.math("ADD", t.math("MULTIPLY", v, 1.0), t.math("MULTIPLY", rnd, 37.0))
    gz = t.math("ADD", t.math("MULTIPLY", rnd2, 11.0), 0.0)
    g = t.comb(t.math("MULTIPLY", gx, 0.04), gy, gz)
    warp = t.noise(g, 3.0, 4.0, 0.55)
    wave = t.n("ShaderNodeTexWave", wave_type="RINGS", rings_direction="X")
    t.set(wave, "Vector", t.vmath("ADD", g, t.comb(0, warp, 0)))
    t.set(wave, "Scale", ring_scale)
    t.set(wave, "Distortion", 6.0)
    t.set(wave, "Detail", 3.0)
    t.set(wave, "Detail Scale", 1.5)
    grain = t.o(wave, "Fac")
    fine = t.noise(t.comb(t.math("MULTIPLY", gx, 0.6), t.math("MULTIPLY", gy, 40.0), gz), 4.0, 8.0, 0.6)
    lines = t.math("MULTIPLY", grain, t.maprange(fine, 0.3, 0.7, 0.7, 1.0))
    dark = _lin(base, 0.62)
    light = _lin(base, 1.25)
    col = t.mix(lines, dark, light)
    # per plank tone
    col = t.hsv(col, t.maprange(rnd2, 0, 1, 0.48, 0.52), t.maprange(rnd, 0, 1, 0.9, 1.1),
                t.maprange(rnd, 0, 1, 0.82, 1.15))
    if cerused:
        # whitewash settles in open pores (dark grain lines)
        pores = t.maprange(lines, 0.0, 0.45, 1.0, 0.0)
        col = t.mix(t.math("MULTIPLY", pores, cerused), col, (0.86, 0.84, 0.79, 1.0))
        col = t.mix(cerused * 0.45, col, (0.80, 0.77, 0.70, 1.0))
    # gaps between planks (dark seam + bump)
    fr_v = t.math("FRACT", t.math("DIVIDE", v, plank_w))
    fr_u = t.math("FRACT", t.math("DIVIDE", along, plank_l))
    seam = t.math("MAXIMUM",
                  t.maprange(t.math("MINIMUM", fr_v, t.math("SUBTRACT", 1.0, fr_v)), 0.0, 0.012, 1.0, 0.0),
                  t.maprange(t.math("MINIMUM", fr_u, t.math("SUBTRACT", 1.0, fr_u)), 0.0, 0.003, 1.0, 0.0))
    col = t.mix(t.math("MULTIPLY", seam, 0.7), col, (0.02, 0.015, 0.01, 1.0))
    r = t.maprange(lines, 0.0, 1.0, rough + 0.12, rough - 0.08)
    r = t.math("ADD", r, t.maprange(rnd, 0, 1, -0.06, 0.06))
    h = t.math("SUBTRACT", t.math("MULTIPLY", lines, 0.3), seam)
    nrm = t.bump(h, 0.12, 0.003)
    b = t.principled(base=col, rough=r, coat=coat, coat_rough=0.12, normal=nrm, spec=0.5)
    t.output(b)


def r_marble(t, base, vein=(0.35, 0.35, 0.36, 1), vein2=None, scale=1.2, polish=0.08,
             coat=0.6, vein_width=0.035, slab=1.6):
    """Polished marble: warped-noise veins (+ secondary gold/white), slab tiling."""
    u, v, flo = t.facemap()
    p = t.obj()
    # slab seams: rotate pattern per slab via random offset
    sid = t.comb(t.math("FLOOR", t.math("DIVIDE", u, slab)), t.math("FLOOR", t.math("DIVIDE", v, slab * 0.6)), 0)
    rnd = t.white(sid, "Color")
    q = t.vmath("ADD", p, t.vmath("MULTIPLY", rnd, (9.0, 9.0, 9.0)))
    warp = t.noise(q, scale * 0.7, 6.0, 0.62, out="Color")
    q2 = t.vmath("ADD", q, t.vmath("MULTIPLY", warp, (1.6, 1.6, 1.6)))
    n = t.noise(q2, scale, 4.0, 0.55)
    # thin veins where noise crosses 0.5
    d = t.math("ABSOLUTE", t.math("SUBTRACT", n, 0.5))
    veins = t.maprange(d, 0.0, vein_width, 1.0, 0.0)
    fine_n = t.noise(t.vmath("ADD", q2, (3, 1, 2)), scale * 4.0, 5.0, 0.6)
    fine = t.maprange(t.math("ABSOLUTE", t.math("SUBTRACT", fine_n, 0.5)), 0.0, vein_width * 0.6, 0.55, 0.0)
    cloud = t.noise(q, scale * 2.5, 6.0, 0.6)
    col = t.hsv(base, 0.5, 1.0, t.maprange(cloud, 0.3, 0.7, 0.93, 1.05))
    col = t.mix(t.math("MAXIMUM", veins, fine), col, vein)
    if vein2 is not None:
        n2 = t.noise(t.vmath("ADD", q2, (11, 5, 3)), scale * 0.8, 3.0, 0.5)
        v2 = t.maprange(t.math("ABSOLUTE", t.math("SUBTRACT", n2, 0.5)), 0.0, vein_width * 0.5, 1.0, 0.0)
        col = t.mix(v2, col, vein2)
    fr_u = t.math("FRACT", t.math("DIVIDE", u, slab))
    fr_v = t.math("FRACT", t.math("DIVIDE", v, slab * 0.6))
    seam = t.math("MAXIMUM",
                  t.maprange(t.math("MINIMUM", fr_u, t.math("SUBTRACT", 1.0, fr_u)), 0.0, 0.0015, 1.0, 0.0),
                  t.maprange(t.math("MINIMUM", fr_v, t.math("SUBTRACT", 1.0, fr_v)), 0.0, 0.0025, 1.0, 0.0))
    col = t.mix(t.math("MULTIPLY", seam, 0.5), col, _lin(base, 0.4))
    r = t.maprange(cloud, 0.3, 0.7, polish * 0.6, polish * 1.6)
    b = t.principled(base=col, rough=r, coat=coat, coat_rough=0.03, sss=0.05,
                     sss_radius=(0.4, 0.3, 0.2), sss_scale=0.01, normal=t.bump(seam, 0.3, 0.002))
    t.output(b)


def r_stone(t, base, rough=0.6, honed=False, joints=(1.2, 0.6), grain=200.0):
    """Limestone / granite / paving: fine speckle, mottling, joints."""
    u, v, flo = t.facemap()
    p = t.obj()
    speck = t.voronoi(p, grain, "F1", "Color")
    sp = t.maprange(t.sep(speck)[0], 0, 1, 0.9, 1.1)
    mott = t.noise(p, 0.8, 5.0, 0.6)
    col = t.hsv(base, 0.5, 1.0, t.math("MULTIPLY", sp, t.maprange(mott, 0.3, 0.7, 0.9, 1.08)))
    seam = None
    if joints:
        bw, bh = joints
        fr_u = t.math("FRACT", t.math("DIVIDE", u, bw))
        fr_v = t.math("FRACT", t.math("DIVIDE", v, bh))
        seam = t.math("MAXIMUM",
                      t.maprange(t.math("MINIMUM", fr_u, t.math("SUBTRACT", 1.0, fr_u)), 0.0, 0.004, 1.0, 0.0),
                      t.maprange(t.math("MINIMUM", fr_v, t.math("SUBTRACT", 1.0, fr_v)), 0.0, 0.008, 1.0, 0.0))
        col = t.mix(t.math("MULTIPLY", seam, 0.6), col, _lin(base, 0.45))
        tile = t.white(t.comb(t.math("FLOOR", t.math("DIVIDE", u, bw)), t.math("FLOOR", t.math("DIVIDE", v, bh)), 0))
        col = t.hsv(col, 0.5, 1.0, t.maprange(tile, 0, 1, 0.94, 1.06))
    r = rough_var(t, rough, 0.1, 3.0)
    h = t.math("MULTIPLY", mott, 0.3)
    if seam is not None:
        h = t.math("SUBTRACT", h, seam)
    b = t.principled(base=col, rough=r, coat=0.3 if honed else 0.0, coat_rough=0.15,
                     normal=t.bump(h, 0.15, 0.004))
    t.output(b)


def r_metal(t, base, rough=0.3, aniso=0.6, brushed=True, patina=0.0, scale=1.0):
    """Brushed / burnished metal: stretched noise along the dominant direction."""
    p = t.obj()
    stretch = t.vmath("MULTIPLY", p, (60.0 * scale, 60.0 * scale, 1.5 * scale)) if brushed else p
    br = t.noise(stretch, 6.0, 8.0, 0.65)
    smudge = t.noise(p, 2.0, 4.0, 0.5)
    r = t.math("ADD", t.maprange(br, 0.3, 0.7, rough - 0.06, rough + 0.06),
               t.maprange(smudge, 0.3, 0.7, -0.05, 0.08))
    col = t.hsv(base, 0.5, 1.0, t.maprange(smudge, 0.3, 0.7, 0.92, 1.05))
    if patina:
        pat = t.maprange(t.noise(p, 3.0, 6.0, 0.7), 0.55, 0.75, 0.0, patina)
        col = t.mix(pat, col, (0.08, 0.06, 0.04, 1.0))
    b = t.principled(base=col, metal=1.0, rough=r, aniso=aniso if brushed else 0.0,
                     normal=t.bump(br, 0.03, 0.002))
    t.output(b)


def r_fabric(t, base, rough=0.9, sheen=0.6, weave=420.0):
    p = t.obj()
    w1 = t.math("SINE", t.math("MULTIPLY", t.sep(p)[0], weave))
    w2 = t.math("SINE", t.math("MULTIPLY", t.math("ADD", t.sep(p)[1], t.sep(p)[2]), weave))
    weave_h = t.math("MULTIPLY", t.math("ADD", w1, w2), 0.25)
    fuzz = t.noise(p, 25.0, 6.0, 0.7)
    col = color_var(t, base, 3.0, 0.07)
    col = t.hsv(col, 0.5, 1.0, t.maprange(fuzz, 0.3, 0.7, 0.92, 1.06))
    b = t.principled(base=col, rough=rough, sheen=sheen, sheen_rough=0.4, sheen_tint=(1, 1, 1, 1),
                     normal=t.bump(t.math("ADD", weave_h, fuzz), 0.15, 0.002))
    t.output(b)


def r_rug(t, base):
    p = t.obj()
    pile = t.noise(p, 180.0, 4.0, 0.7)
    stripes = t.math("SINE", t.math("MULTIPLY", t.sep(p)[0], 30.0))
    col = color_var(t, base, 4.0, 0.08)
    col = t.hsv(col, 0.5, 1.0, t.maprange(t.math("ADD", pile, t.math("MULTIPLY", stripes, 0.05)), 0.2, 0.8, 0.85, 1.1))
    b = t.principled(base=col, rough=0.95, sheen=1.0, sheen_rough=0.5, normal=t.bump(pile, 0.35, 0.004))
    t.output(b)


def r_leather(t, base, rough=0.45):
    p = t.obj()
    cells = t.voronoi(p, 260.0, "F1", "Distance")
    crease = t.noise(p, 9.0, 6.0, 0.6)
    col = color_var(t, base, 6.0, 0.10, 0.01)
    col = t.hsv(col, 0.5, 1.0, t.maprange(crease, 0.3, 0.7, 0.85, 1.1))
    r = t.maprange(crease, 0.3, 0.7, rough - 0.1, rough + 0.12)
    b = t.principled(base=col, rough=r, coat=0.2, coat_rough=0.3, sheen=0.15,
                     normal=t.bump(t.math("ADD", cells, t.math("MULTIPLY", crease, 0.3)), 0.25, 0.002))
    t.output(b)


def r_thin_glass(t, base, tint=(0.85, 0.93, 0.92, 1), refl=0.0, rough=0.02, ior=1.52, shadow_tint=None):
    """Architectural single-sheet glass: Fresnel mix of tinted Transparent and
    Glossy (no refraction offset, no caustics noise, cheap & correct for
    single-skin glazing). refl adds a low-e coating reflectance floor."""
    # two-sided Schlick Fresnel: thin sheets reflect identically from both
    # sides (the Fresnel node would do total internal reflection on backfaces)
    f0 = ((ior - 1.0) / (ior + 1.0)) ** 2
    cosi = t.math("ABSOLUTE", t.vmath("DOT_PRODUCT", t.o(t.geo(), "Normal"), t.o(t.geo(), "Incoming")))
    k = t.math("POWER", t.math("SUBTRACT", 1.0, t.math("MINIMUM", cosi, 1.0)), 5.0)
    fres_v = t.math("ADD", f0, t.math("MULTIPLY", k, 1.0 - f0))
    fac = t.maprange(fres_v, 0.0, 1.0, refl, 1.0)
    tr = t.n("ShaderNodeBsdfTransparent")
    t.set(tr, "Color", tint)
    gl = t.n("ShaderNodeBsdfGlossy", distribution="GGX")
    t.set(gl, "Roughness", rough)
    t.set(gl, "Color", (1.0, 1.0, 1.0, 1))
    m = t.n("ShaderNodeMixShader")
    t.set(m, "Fac", fac)
    t.nt.links.new(t.o(tr), m.inputs[1])
    t.nt.links.new(t.o(gl), m.inputs[2])
    # shadows: tinted transparency only (sun reaches interiors)
    lp = t.n("ShaderNodeLightPath")
    tr2 = t.n("ShaderNodeBsdfTransparent")
    t.set(tr2, "Color", shadow_tint or tint)
    m2 = t.n("ShaderNodeMixShader")
    t.nt.links.new(t.o(lp, "Is Shadow Ray"), m2.inputs[0])
    t.nt.links.new(t.o(m), m2.inputs[1])
    t.nt.links.new(t.o(tr2), m2.inputs[2])
    t.output(t.o(m2))


def r_solid_glass(t, base, rough=0.0):
    """Real refractive glass for thick objects (vases, tables)."""
    tint = base if max(base[:3]) > 0.2 else tuple(min(1.0, c * 8.0) for c in base[:3]) + (1.0,)
    b = t.principled(base=tint, rough=rough, ior=1.52, trans=1.0)
    t.output(b)


def r_facade_glazing(t, base, cell=(1.5, 1.5, 3.6), lit=0.18, rough=0.04, warm=True, ground_glow=0.0):
    """Opaque glazing on context buildings: dark reflective glass, per-window
    blind/curtain variation and a fraction of lit rooms (CTRL_CITY_GLOW)."""
    u, v, flo = t.facemap()
    cx, cy, cz = cell
    ci = t.comb(t.math("FLOOR", t.math("DIVIDE", u, cx)), t.math("FLOOR", t.math("DIVIDE", v, cz)), 0.0)
    r1 = t.white(ci)
    r2 = t.white(t.vmath("ADD", ci, (5.3, 1.7, 2.9)))
    # per building block hue/value (buildings are merged per material)
    blk = t.white(t.vmath("SNAP", t.obj(), (30.0, 30.0, 1000.0)), "Color")
    col = t.hsv(base, t.maprange(t.sep(blk)[0], 0, 1, 0.47, 0.53), t.maprange(t.sep(blk)[1], 0, 1, 0.7, 1.2),
                t.maprange(t.sep(blk)[2], 0, 1, 0.75, 1.3))
    blind = t.maprange(r2, 0.6, 1.0, 0.0, 1.0)
    col = t.mix(t.math("MULTIPLY", blind, 0.35), col, (0.20, 0.19, 0.18, 1))
    rr = t.math("ADD", rough, t.math("MULTIPLY", blind, 0.25))
    # slight pane waviness -> broken reflections
    wav = t.noise(t.obj(), 0.4, 2.0, 0.5)
    nrm = t.bump(wav, 0.04, 0.05)
    glow_mask = t.math("LESS_THAN", r1, lit)
    temp = t.blackbody(3000.0 if warm else 4200.0)
    tone = t.maprange(r2, 0, 1, 0.4, 1.2)
    ctrl = t.value(0.0, "CTRL_CITY_GLOW")
    strength = t.math("MULTIPLY", t.math("MULTIPLY", glow_mask, tone), ctrl)
    if ground_glow:
        z = t.sep(t.obj())[2]
        street = t.math("MULTIPLY", t.math("LESS_THAN", z, 6.0), t.value(0.0, "CTRL_STREET"))
        strength = t.math("ADD", strength, t.math("MULTIPLY", street, ground_glow))
    b = t.principled(base=col, metal=0.0, rough=rr, spec=1.0, ior=1.52, normal=nrm,
                     emit=temp, emit_str=strength)
    t.output(b)


def r_water(t, base, depth_tint=(0.55, 0.85, 0.85, 1)):
    p = t.obj()
    w1 = t.noise(t.vmath("MULTIPLY", p, (1.0, 2.2, 1.0)), 1.6, 3.0, 0.5)
    w2 = t.noise(p, 7.0, 2.0, 0.5)
    h = t.math("ADD", w1, t.math("MULTIPLY", w2, 0.25))
    b = t.principled(base=depth_tint, rough=0.01, ior=1.333, trans=1.0, normal=t.bump(h, 0.12, 0.02))
    t.output(b)


def r_river(t, base):
    """Opaque open water seen from afar: dark, glossy, wind ripples."""
    p = t.obj()
    w1 = t.noise(t.vmath("MULTIPLY", p, (0.3, 1.0, 1.0)), 0.6, 4.0, 0.6)
    w2 = t.noise(p, 3.0, 3.0, 0.5)
    h = t.math("ADD", w1, t.math("MULTIPLY", w2, 0.3))
    col = t.hsv(base, 0.5, 1.0, t.maprange(w1, 0.3, 0.7, 0.8, 1.2))
    b = t.principled(base=col, rough=t.maprange(w2, 0.3, 0.7, 0.02, 0.12), ior=1.333, spec=0.5,
                     normal=t.bump(h, 0.15, 0.3))
    t.output(b)


def r_emissive(t, base, kelvin=3200.0, strength=12.0, ctrl="CTRL_INT_LIGHT"):
    """Diffuser panel / lamp shade. Emission in Cycles units (W/m2-ish);
    multiplied by the preset's control value."""
    temp = t.blackbody(kelvin)
    k = t.value(1.0, ctrl)
    s = t.math("MULTIPLY", k, strength)
    em = t.n("ShaderNodeEmission")
    t.set(em, "Color", temp)
    t.set(em, "Strength", s)
    t.output(t.o(em))


def r_emit_color(t, base, strength=6.0, ctrl="CTRL_INT_LIGHT", glass=False):
    """Emitter that keeps its own (non-blackbody) colour: coloured coves,
    pool lights, signals, car lamps. Optional glossy lens on top."""
    k = t.value(1.0, ctrl) if ctrl else None
    em = t.n("ShaderNodeEmission")
    t.set(em, "Color", base)
    t.set(em, "Strength", t.math("MULTIPLY", k, strength) if k else strength)
    if not glass:
        t.output(t.o(em))
        return
    g = t.principled(base=_lin(base, 0.3), rough=0.05, coat=1.0, coat_rough=0.02)
    add = t.n("ShaderNodeAddShader")
    t.nt.links.new(t.o(em), add.inputs[0])
    t.nt.links.new(t.o(g), add.inputs[1])
    t.output(t.o(add))


def r_lacquer(t, base, rough=0.25, coat=1.0):
    b = t.principled(base=color_var(t, base, 2.0, 0.03), rough=rough, coat=coat, coat_rough=0.04,
                     normal=micro_bump(t, 30.0, 0.02))
    t.output(b)


def r_wax(t, base):
    b = t.principled(base=base, rough=0.4, sss=1.0, sss_radius=(1.0, 0.6, 0.3), sss_scale=0.02)
    t.output(b)


def r_alabaster(t, base):
    p = t.obj()
    n = t.noise(t.vmath("ADD", p, t.vmath("MULTIPLY", t.noise(p, 1.5, 4, 0.6, out="Color"), (1.2, 1.2, 1.2))),
                2.5, 5.0, 0.6)
    col = t.mix(t.maprange(n, 0.35, 0.65, 0.0, 1.0), _lin(base, 0.8), (0.97, 0.90, 0.78, 1))
    b = t.principled(base=col, rough=0.25, sss=1.0, sss_radius=(1.0, 0.7, 0.45), sss_scale=0.05,
                     coat=0.3, coat_rough=0.1, emit=t.blackbody(2700.0),
                     emit_str=t.math("MULTIPLY", t.value(1.0, "CTRL_INT_LIGHT"),
                                     t.maprange(n, 0.2, 0.8, 0.6, 2.0)))
    t.output(b)


def r_foliage(t, base, wall=False):
    p = t.obj()
    leaves = t.voronoi(p, 35.0 if wall else 18.0, "F1", "Color")
    lv = t.voronoi(p, 35.0 if wall else 18.0, "F1", "Distance")
    lr, lg, lb = t.sep(leaves)
    col = t.hsv(base, t.maprange(lr, 0, 1, 0.44, 0.56), t.maprange(lg, 0, 1, 0.8, 1.25),
                t.maprange(lb, 0, 1, 0.55, 1.5))
    if wall:
        flowers = t.math("GREATER_THAN", lr, 0.94)
        col = t.mix(t.math("MULTIPLY", flowers, 0.8), col, (0.55, 0.12, 0.10, 1))
    b = t.principled(base=col, rough=t.maprange(lb, 0, 1, 0.35, 0.7), sss=0.25,
                     sss_radius=(0.3, 0.6, 0.15), sss_scale=0.02, sheen=0.2,
                     normal=t.bump(lv, 0.6, 0.02))
    # thin leaves transmit light: mix in translucent
    tl = t.n("ShaderNodeBsdfTranslucent")
    t.set(tl, "Color", t.hsv(col, 0.48, 1.3, 1.2))
    m = t.n("ShaderNodeMixShader")
    t.set(m, "Fac", 0.25)
    t.nt.links.new(t.o(b), m.inputs[1])
    t.nt.links.new(t.o(tl), m.inputs[2])
    t.output(t.o(m))


def r_asphalt(t, base):
    p = t.obj()
    agg = t.voronoi(p, 300.0, "F1", "Color")
    a = t.sep(agg)[0]
    patch = t.noise(p, 0.08, 4.0, 0.6)
    wear = t.noise(t.vmath("MULTIPLY", p, (1.0, 0.15, 1.0)), 0.6, 3.0, 0.5)  # tyre tracks along x
    col = t.hsv(base, 0.5, 0.9, t.math("MULTIPLY", t.maprange(a, 0, 1, 0.7, 1.5),
                                       t.maprange(patch, 0.3, 0.7, 0.75, 1.35)))
    col = t.mix(t.maprange(wear, 0.5, 0.7, 0.0, 0.25), col, (0.12, 0.12, 0.12, 1))
    oil = t.maprange(t.noise(p, 0.5, 3.0, 0.5), 0.6, 0.7, 0.0, 1.0)
    r = t.maprange(oil, 0, 1, 0.9, 0.55)
    b = t.principled(base=col, rough=r, normal=t.bump(a, 0.25, 0.005))
    t.output(b)


def r_paint_marking(t, base):
    p = t.obj()
    wear = t.noise(p, 3.0, 6.0, 0.6)
    col = t.mix(t.maprange(wear, 0.55, 0.75, 0.0, 0.7), base, (0.1, 0.1, 0.1, 1))
    b = t.principled(base=col, rough=0.6, normal=micro_bump(t, 200.0, 0.1))
    t.output(b)


def r_brick(t, base, mortar=(0.55, 0.53, 0.50, 1), windows=True):
    u, v, flo = t.facemap()
    br = t.n("ShaderNodeTexBrick", offset=0.5, offset_frequency=2)
    t.set(br, "Vector", t.comb(u, v, 0.0))
    t.set(br, "Color1", _lin(base, 1.1))
    t.set(br, "Color2", _lin(base, 0.75))
    t.set(br, "Mortar", mortar)
    t.set(br, "Scale", 1.0)
    t.set(br, "Mortar Size", 0.01)
    t.set(br, "Brick Width", 0.205)
    t.set(br, "Row Height", 0.068)
    t.set(br, "Bias", 0.0)
    col = t.o(br, "Color")
    blk = t.white(t.vmath("SNAP", t.obj(), (25.0, 25.0, 1000.0)), "Color")
    col = t.hsv(col, t.maprange(t.sep(blk)[0], 0, 1, 0.48, 0.52), 1.0, t.maprange(t.sep(blk)[1], 0, 1, 0.8, 1.2))
    col = t.mix(t.maprange(t.noise(t.obj(), 1.0, 4, 0.6), 0.4, 0.7, 0, 0.3), col, (0.1, 0.09, 0.08, 1),
                blend="MULTIPLY")
    b = t.principled(base=col, rough=0.85, normal=t.bump(t.o(br, "Fac"), 0.4, 0.01))
    if windows:
        b = _with_windows(t, b, u, v, flo, blk, cell_w=2.2, floor_h=3.2, base_z=4.5)
    t.output(b)


def _punched_windows(t, u, v, flo, blk, cell_w=1.7, floor_h=3.5, base_z=5.0):
    """Mask + shader of punched windows for blank context facades."""
    cw = t.maprange(t.sep(blk)[2], 0, 1, cell_w * 0.8, cell_w * 1.3)
    fu = t.math("FRACT", t.math("DIVIDE", u, cw))
    fv = t.math("FRACT", t.math("DIVIDE", t.math("SUBTRACT", v, base_z), floor_h))
    mu = t.math("LESS_THAN", t.math("ABSOLUTE", t.math("SUBTRACT", fu, 0.5)), 0.3)
    mv = t.math("MULTIPLY", t.math("GREATER_THAN", fv, 0.28), t.math("LESS_THAN", fv, 0.88))
    above = t.math("GREATER_THAN", v, base_z)
    walls = t.math("SUBTRACT", 1.0, flo)
    m = t.math("MULTIPLY", t.math("MULTIPLY", mu, mv), t.math("MULTIPLY", above, walls))
    ci = t.comb(t.math("FLOOR", t.math("DIVIDE", u, cw)),
                t.math("FLOOR", t.math("DIVIDE", t.math("SUBTRACT", v, base_z), floor_h)), 0.0)
    r1 = t.white(ci)
    r2 = t.white(t.vmath("ADD", ci, (3.1, 7.7, 1.3)))
    gcol = t.mix(t.math("MULTIPLY", t.math("GREATER_THAN", r2, 0.7), 0.5), (0.035, 0.042, 0.05, 1),
                 (0.25, 0.23, 0.2, 1))
    glow = t.math("MULTIPLY", t.math("MULTIPLY", t.math("LESS_THAN", r1, 0.2),
                                     t.maprange(r2, 0, 1, 0.4, 1.2)), t.value(0.0, "CTRL_CITY_GLOW"))
    g = t.principled(base=gcol, rough=0.05, spec=1.0, ior=1.52, emit=t.blackbody(3000.0), emit_str=glow)
    return m, g


def _with_windows(t, b, u, v, flo, blk, **kw):
    m, g = _punched_windows(t, u, v, flo, blk, **kw)
    mx = t.n("ShaderNodeMixShader")
    t.set(mx, "Fac", m)
    t.nt.links.new(t.o(b), mx.inputs[1])
    t.nt.links.new(t.o(g), mx.inputs[2])
    return mx


def r_facade_panel(t, base, rough=0.6, metal=0.0, panel=(1.5, 3.6), stain=0.25, windows=False):
    """Generic context-building facade: per-building colour jitter, panel
    joints and vertical weathering streaks so flat colours read as material."""
    u, v, flo = t.facemap()
    blk = t.white(t.vmath("SNAP", t.obj(), (28.0, 28.0, 1000.0)), "Color")
    br, bg, bb = t.sep(blk)
    # per-building palette: hue +-4 %, saturation and value widely varied
    col = t.hsv(base, t.maprange(br, 0, 1, 0.46, 0.54), t.maprange(bg, 0, 1, 0.45, 1.5),
                t.maprange(bb, 0, 1, 0.55, 1.3))
    p = t.obj()
    streak = t.noise(t.vmath("MULTIPLY", p, (3.0, 3.0, 0.08)), 1.0, 5.0, 0.6)
    col = t.mix(t.maprange(streak, 0.45, 0.8, 0.0, stain), col, _lin(base, 0.5), blend="MULTIPLY")
    mott = t.noise(p, 0.5, 4, 0.6)
    col = t.hsv(col, 0.5, 1.0, t.maprange(mott, 0.3, 0.7, 0.9, 1.08))
    pw, ph = panel
    fr_u = t.math("FRACT", t.math("DIVIDE", u, pw))
    fr_v = t.math("FRACT", t.math("DIVIDE", v, ph))
    seam = t.math("MAXIMUM",
                  t.maprange(t.math("MINIMUM", fr_u, t.math("SUBTRACT", 1.0, fr_u)), 0.0, 0.006, 1.0, 0.0),
                  t.maprange(t.math("MINIMUM", fr_v, t.math("SUBTRACT", 1.0, fr_v)), 0.0, 0.006, 1.0, 0.0))
    col = t.mix(t.math("MULTIPLY", seam, 0.5), col, _lin(base, 0.35))
    b = t.principled(base=col, metal=metal, rough=rough_var(t, rough, 0.12, 0.5),
                     normal=t.bump(t.math("SUBTRACT", t.math("MULTIPLY", mott, 0.2), seam), 0.2, 0.01))
    if windows:
        b = _with_windows(t, b, u, v, flo, blk)
    t.output(b)


def r_tile(t, base, size=0.3, grout=(0.6, 0.62, 0.62, 1), rough=0.12):
    u, v, flo = t.facemap()
    fr_u = t.math("FRACT", t.math("DIVIDE", u, size))
    fr_v = t.math("FRACT", t.math("DIVIDE", v, size))
    seam = t.math("MAXIMUM",
                  t.maprange(t.math("MINIMUM", fr_u, t.math("SUBTRACT", 1.0, fr_u)), 0.0, 0.01, 1.0, 0.0),
                  t.maprange(t.math("MINIMUM", fr_v, t.math("SUBTRACT", 1.0, fr_v)), 0.0, 0.01, 1.0, 0.0))
    tid = t.white(t.comb(t.math("FLOOR", t.math("DIVIDE", u, size)), t.math("FLOOR", t.math("DIVIDE", v, size)), 1))
    col = t.hsv(base, 0.5, 1.0, t.maprange(tid, 0, 1, 0.93, 1.05))
    col = t.mix(seam, col, grout)
    b = t.principled(base=col, rough=t.maprange(seam, 0, 1, rough, 0.8), normal=t.bump(t.math("SUBTRACT", 0, seam), 0.3, 0.003))
    t.output(b)


def r_car_paint(t, base):
    b = t.principled(base=color_var(t, base, 2.0, 0.04), metal=0.3, rough=0.3, coat=1.0, coat_rough=0.03)
    t.output(b)


def r_gold_leaf(t, base):
    p = t.obj()
    leaf = t.voronoi(p, 9.0, "F1", "Color")
    lr = t.sep(leaf)[0]
    col = t.hsv((0.95, 0.70, 0.32, 1), t.maprange(lr, 0, 1, 0.49, 0.51), 1.0, t.maprange(lr, 0, 1, 0.85, 1.1))
    crack = t.voronoi(p, 9.0, "DISTANCE_TO_EDGE", "Distance")
    r = t.maprange(lr, 0, 1, 0.12, 0.3)
    b = t.principled(base=col, metal=1.0, rough=r, normal=t.bump(t.maprange(crack, 0, 0.03, 0, 1), 0.2, 0.002))
    t.output(b)


def r_rubber(t, base, rough=0.75):
    b = t.principled(base=color_var(t, base, 4.0, 0.06), rough=rough, normal=micro_bump(t, 150.0, 0.15))
    t.output(b)


def r_translucent_panel(t, base):
    """Thermolux / frosted glass: diffuse transmission, soft glow at night."""
    b = t.principled(base=base, rough=0.5, trans=0.6, ior=1.5, emit=t.blackbody(4000),
                     emit_str=t.math("MULTIPLY", t.value(0.0, "CTRL_STREET"), 1.5))
    t.output(b)


# ------------------------------------------------------------------ rules
# (predicate on lowercase name, recipe, kwargs). First match wins.

def _has(*keys):
    return lambda n: any(k in n for k in keys)


def _eq(*keys):
    return lambda n: n in keys


RULES = [
    # crown louvres read near-black in photos: matte backing, dark anodised slats
    (_has("louvre_backing"), r_generic, dict(rough=0.9, bump=0.05, amount=0.04, override=(0.03, 0.03, 0.032))),
    (_has("louvre_metal"), r_metal, dict(rough=0.5, aniso=0.2, override=(0.08, 0.08, 0.085))),
    # --- exact-ish names that would otherwise be caught by broader patterns
    (_has("gold_leaf", "gilt", "gilded"), r_gold_leaf, {}),
    (_eq("glass_black", "black_glass"), r_lacquer, dict(rough=0.03, coat=1.0)),
    (_has("light_skylight", "skylight"), r_emit_color, dict(strength=6.0, ctrl="CTRL_INT_LIGHT")),
    (_has("light_cove", "light_downlight", "light_wine", "light_strip", "light_led"), r_emit_color,
     dict(strength=8.0, ctrl="CTRL_INT_LIGHT")),
    (_has("pool_light", "fire_glow", "fire"), r_emit_color, dict(strength=5.0, ctrl="CTRL_INT_LIGHT")),
    (_has("lamp_shade", "lampshade"), r_emissive, dict(kelvin=2800, strength=3.0)),
    (_has("car_lights", "signal_lens", "tail_light", "head_light"), r_emit_color,
     dict(strength=4.0, ctrl=None, glass=True)),
    (_has("wine_bottle", "bottle", "vase_glass"), r_solid_glass, dict(rough=0.02)),
    (_has("candle", "wax"), r_wax, {}),
    (_has("lacquer", "piano"), r_lacquer, dict(rough=0.15)),
    (_has("ceramic", "porcelain", "glaze"), r_lacquer, dict(rough=0.1, coat=0.6)),
    (_has("bus_", "signal_", "sign"), r_car_paint, {}),
    (_has("wheel_rim", "rim"), r_metal, dict(rough=0.25, aniso=0.2)),
    (_has("_distant"), r_facade_panel, dict(rough=0.8, stain=0.1)),
    (_has("fruit", "flower"), r_lacquer, dict(rough=0.45, coat=0.3)),
    # --- emissive (before metals: "Lamp_Grey" is a pole, so match exact names)
    (_eq("light_emit"), r_emissive, dict(kelvin=3200, strength=12.0)),
    (_has("emit", "led_strip", "lightpanel", "light_panel", "cove_light"), r_emissive, dict(kelvin=3000, strength=10.0)),
    (_has("lampshade", "shade_lamp"), r_emissive, dict(kelvin=2900, strength=4.0)),
    (_has("alabaster", "onyx"), r_alabaster, {}),
    # --- glass
    (_eq("glass_curtain"), r_thin_glass,
     dict(tint=(0.42, 0.50, 0.50, 1), refl=0.10, rough=0.012, shadow_tint=(0.50, 0.58, 0.57, 1))),
    (_has("glass_partition", "glass_clear", "glass_rail", "mirror_glass"), r_thin_glass,
     dict(tint=(0.92, 0.97, 0.96, 1), refl=0.02, rough=0.01)),
    (_eq("car_glass"), r_facade_glazing, dict(cell=(50, 50, 50), lit=0.0, rough=0.02)),
    (_eq("storefront"), r_facade_glazing, dict(cell=(3.0, 3.0, 5.0), lit=0.6, rough=0.02, ground_glow=3.0)),
    (_eq("window_dark"), r_facade_glazing, dict(cell=(1.5, 1.5, 3.4), lit=0.22)),
    (_has("glass_neighbor", "glass_blue", "glass_green", "glass_dark", "glass_tower"), r_facade_glazing,
     dict(cell=(1.5, 1.5, 4.0), lit=0.14, warm=False)),
    (_has("spandrel"), r_facade_glazing, dict(cell=(1.5, 1.5, 3.6), lit=0.0, rough=0.08)),
    (_has("mirror"), lambda t, b: t.output(t.principled(base=(0.9, 0.9, 0.9, 1), metal=1.0, rough=0.02)), {}),
    (_has("glass"), r_thin_glass, dict(tint=(0.9, 0.95, 0.94, 1), refl=0.03)),
    (_has("thermolux", "frosted", "translucent"), r_translucent_panel, {}),
    # --- water
    (_has("river", "harbor", "pool_dark", "water_distant"), r_river, {}),
    (_has("water"), r_water, {}),
    # --- plants
    (_has("green_wall", "plant_wall", "living_wall"), r_foliage, dict(wall=True)),
    (_has("foliage", "leaf", "leaves", "grass", "hedge", "plant", "tree_crown", "ivy"), r_foliage, {}),
    # --- stone / marble
    (_has("noir", "marble_black", "nero", "laurent"), r_marble,
     dict(vein=(0.70, 0.68, 0.64, 1), vein2=(0.65, 0.48, 0.22, 1), polish=0.05, scale=1.6, vein_width=0.010)),
    (_has("statuary", "calacatta", "carrara", "marble"), r_marble,
     dict(vein=(0.42, 0.42, 0.43, 1), polish=0.08, scale=1.1)),
    (_has("travertine", "limestone", "verona"), r_stone, dict(rough=0.45, honed=True, joints=(1.2, 0.6), grain=120.0)),
    (_has("granite_black"), r_stone, dict(rough=0.18, honed=True, joints=(1.5, 1.0), grain=300.0)),
    (_has("granite", "curb"), r_stone, dict(rough=0.55, joints=(2.0, 0.3), grain=300.0)),
    (_has("sidewalk"), r_concrete, dict(rough=0.85, stain=0.35, pores=0.25)),
    (_has("paving", "floor_stone", "terrazzo"), r_stone, dict(rough=0.35, honed=True, joints=(0.9, 0.9))),
    (_has("panel_podium"), r_facade_panel, dict(rough=0.6, panel=(1.6, 0.8), stain=0.1)),
    (_has("stone_neighbor", "stone_light", "limestone_neighbor", "facade_"), r_facade_panel,
     dict(rough=0.7, panel=(1.6, 0.8), windows=True)),
    (_has("stone", "slate_floor"), r_stone, dict(rough=0.6)),
    # --- tiles
    (_has("pool_tile", "tile", "mosaic"), r_tile, dict(size=0.05, rough=0.08)),
    # --- concrete
    (_eq("concrete_diagrid"), r_concrete, dict(rough=0.6, stain=0.18, pores=0.06, boardform=False)),
    (_has("concrete", "slab", "core_wall", "cement", "plaster_raw"), r_concrete, dict(rough=0.82, stain=0.12)),
    # --- wood
    (_has("cerused",), r_wood, dict(rough=0.55, plank_w=0.6, plank_l=3.6, coat=0.05, cerused=0.8,
                                    ring_scale=9.0)),
    (_has("oak_dark", "dark_floor"), r_wood, dict(rough=0.35, plank_w=0.22, plank_l=2.4, coat=0.3)),
    (_has("floor_oak", "floor_gallery", "parquet"), r_wood, dict(rough=0.4, plank_w=0.2, plank_l=2.2, coat=0.25)),
    (_has("walnut",), r_wood, dict(rough=0.35, plank_w=0.3, plank_l=2.4, coat=0.35, ring_scale=8.0)),
    (_has("teak", "oak", "wood", "maple", "cherry", "ash_", "timber"), r_wood, dict(rough=0.45, coat=0.2)),
    (_has("bark"), r_generic, dict(rough=0.9, bump=0.4, amount=0.3)),
    (_has("soil", "earth", "mulch"), r_generic, dict(rough=0.95, bump=0.4, amount=0.3)),
    # --- metals
    (_has("gold_leaf", "gilt", "gilded"), r_gold_leaf, {}),
    (_has("bronze", "brass"), r_metal, dict(rough=0.32, aniso=0.5, patina=0.4)),
    (_has("copper"), r_metal, dict(rough=0.3, aniso=0.4, patina=0.3)),
    (_has("gold"), r_metal, dict(rough=0.2, aniso=0.3)),
    (_has("mullion", "window_frame", "alu", "steel", "chrome", "nickel", "louvre", "lift_", "metal_light", "lamp_grey"),
     r_metal, dict(rough=0.28, aniso=0.6)),
    (_has("metal_dark", "nosing", "blackened", "iron", "metal"), r_metal, dict(rough=0.4, aniso=0.3)),
    # --- soft
    (_has("leather"), r_leather, {}),
    (_has("rug", "carpet", "wool"), r_rug, {}),
    (_has("fabric", "awning", "linen", "velvet", "boucle", "cushion", "curtain_", "drape", "upholster", "bed_"),
     r_fabric, {}),
    (_has("yoga", "rubber", "tire", "tyre"), r_rubber, dict(rough=0.8)),
    # --- street
    (_has("asphalt", "road_surface"), r_asphalt, {}),
    (_has("road_marking", "road_yellow", "marking"), r_paint_marking, {}),
    (_has("taxi", "hydrant", "kiosk", "car_paint", "car_body"), r_car_paint, {}),
    # --- context buildings
    (_has("brick"), r_brick, {}),
    (_has("moma_charcoal"), r_facade_panel, dict(rough=0.35, panel=(1.5, 1.2), stain=0.1)),
    (_has("limestone_church"), r_stone, dict(rough=0.7, joints=(0.9, 0.45), grain=150.0)),
    (_has("roof"), r_concrete, dict(rough=0.9, stain=0.3)),
    (_has("pot_clay", "terracotta", "clay"), r_generic, dict(rough=0.8, bump=0.15, amount=0.12)),
    # --- painted / paper / art
    (_has("wall_white", "gallery_wall", "frame_white", "paint", "plaster", "ceiling", "screen_white"),
     r_paint, dict(rough=0.8)),
    (_has("art_"), r_paint, dict(rough=0.55)),
    (_has("book"), r_fabric, dict(rough=0.75, sheen=0.2)),
]


def recipe_for(name):
    low = name.lower()
    for pred, fn, kw in RULES:
        if pred(low):
            return fn, kw
    return None, None


def _generic_for(base):
    """Unknown material: pick roughness/metal heuristics from the colour."""
    h, s, v = colorsys.rgb_to_hsv(*base[:3])
    return dict(rough=0.55 if v > 0.2 else 0.45, bump=0.05, amount=0.08)


def haze_group():
    """Shared node group: mixes the surface toward a haze colour for camera
    rays by 1 - exp(-distance / CTRL_HAZE_DIST) (aerial perspective).
    Interiors (short distances) are unaffected. Tuned by lighting presets."""
    ng = bpy.data.node_groups.get("AerialHaze")
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new("AerialHaze", "ShaderNodeTree")
    try:
        ng.interface.new_socket("Shader", in_out="INPUT", socket_type="NodeSocketShader")
        ng.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    except AttributeError:  # very old API
        ng.inputs.new("NodeSocketShader", "Shader")
        ng.outputs.new("NodeSocketShader", "Shader")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    lp = N.new("ShaderNodeLightPath")
    dist = N.new("ShaderNodeValue")
    dist.label = "CTRL_HAZE_DIST"
    dist.outputs[0].default_value = 9000.0
    col = N.new("ShaderNodeRGB")
    col.label = "CTRL_HAZE_COLOR"
    col.outputs[0].default_value = (0.10, 0.12, 0.15, 1.0)
    amt = N.new("ShaderNodeValue")
    amt.label = "CTRL_HAZE_MAX"
    amt.outputs[0].default_value = 0.85
    div = N.new("ShaderNodeMath"); div.operation = "DIVIDE"
    L.new(lp.outputs["Ray Length"], div.inputs[0]); L.new(dist.outputs[0], div.inputs[1])
    neg = N.new("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0
    L.new(div.outputs[0], neg.inputs[0])
    ex = N.new("ShaderNodeMath"); ex.operation = "EXPONENT"
    L.new(neg.outputs[0], ex.inputs[0])
    one = N.new("ShaderNodeMath"); one.operation = "SUBTRACT"; one.inputs[0].default_value = 1.0
    L.new(ex.outputs[0], one.inputs[1])
    cap = N.new("ShaderNodeMath"); cap.operation = "MULTIPLY"
    L.new(one.outputs[0], cap.inputs[0]); L.new(amt.outputs[0], cap.inputs[1])
    gate = N.new("ShaderNodeMath"); gate.operation = "MULTIPLY"
    L.new(cap.outputs[0], gate.inputs[0]); L.new(lp.outputs["Is Camera Ray"], gate.inputs[1])
    em = N.new("ShaderNodeEmission")
    L.new(col.outputs[0], em.inputs["Color"])
    mix = N.new("ShaderNodeMixShader")
    L.new(gate.outputs[0], mix.inputs[0])
    L.new(gi.outputs[0], mix.inputs[1])
    L.new(em.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], go.inputs[0])
    return ng


def _wrap_haze(t):
    out_sock = t.out.inputs["Surface"]
    if not out_sock.is_linked:
        return
    src = out_sock.links[0].from_socket
    g = t.nt.nodes.new("ShaderNodeGroup")
    g.node_tree = haze_group()
    g.location = (1250, 0)
    t.nt.links.new(src, g.inputs[0])
    t.nt.links.new(g.outputs[0], out_sock)


def build_material(mat, force=False):
    # materials hand-built and stamped by another module (e.g. interiors'
    # coloured emitters, pbr_recipe="interiors_emissive") are never touched
    rec = mat.get("pbr_recipe")
    if rec is not None and not (str(rec).startswith("r_") or rec == "generic"):
        return False
    if mat.get("pbr_version") == VERSION and not force:
        return False
    if mat.library is not None:
        return False
    base = _base_color(mat)
    base = (base[0], base[1], base[2], 1.0)
    mat["pbr_base"] = list(base)
    fn, kw = recipe_for(mat.name)
    t = T(mat)
    if fn is None:
        r_generic(t, base, **_generic_for(base))
        kind = "generic"
    else:
        kw = dict(kw)
        ov = kw.pop("override", None)
        if ov is not None:
            base = (*ov[:3], 1.0)
        fn(t, base, **kw)
        kind = fn.__name__
    if kind not in ("r_thin_glass",):
        _wrap_haze(t)
    mat.diffuse_color = (base[0], base[1], base[2], mat.diffuse_color[3])
    if kind not in ("r_thin_glass",):
        _set_opaque(mat)
    else:
        for attr, val in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
            if hasattr(mat, attr):
                try:
                    setattr(mat, attr, val)
                except Exception:
                    pass
    # Cycles: displacement via bump only (fast)
    try:
        mat.cycles.displacement_method = "BUMP"
    except Exception:
        pass
    mat["pbr_version"] = VERSION
    mat["pbr_recipe"] = kind
    return True


def apply(ctx=None, force=False):
    n = 0
    stats = {}
    for mat in list(bpy.data.materials):
        if mat.is_grease_pencil if hasattr(mat, "is_grease_pencil") else False:
            continue
        try:
            if build_material(mat, force):
                n += 1
                stats[mat["pbr_recipe"]] = stats.get(mat["pbr_recipe"], 0) + 1
        except Exception as exc:  # never break the build
            print(f"[materials] {mat.name}: {exc!r}")
    print(f"[materials] rebuilt {n} materials:",
          ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    return n
