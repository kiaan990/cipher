"""Lighting / colour management / Cycles settings for photoreal renders.

apply(ctx)        -> "day" preset (build.py calls this; saved in the .blend)
preset_day(scene) -> late-afternoon sun from the SW over W 53rd St
preset_dusk(scene)-> blue hour, interiors and city windows glowing

World = physical multiple-scattering (Nishita) sky with the sun disc OFF;
the sun is a real Sun lamp (0.53 deg) aimed and coloured to match the sky's
own sun (table measured from the sky model), so shadows are clean and the
light tree samples it directly. All radiometry is scaled by K so a sunlit
white wall renders ~1.0 at exposure 0 (emission strengths stay intuitive).

Frame: model +Y is "Manhattan north", which is true bearing 29 deg (the
street grid is rotated). Sun azimuths below are TRUE bearings and are
converted to the model frame.
"""
import math
import bpy

LAT, LON = 40.7614, -73.9776     # 53 W 53rd St
GRID_ROT = 29.0                   # Manhattan grid: model +Y = true bearing 29
K = 1.0 / 16.0                    # physical sky -> display-friendly units

# Sun irradiance (W/m2 per channel, normal incidence) of the
# MULTIPLE_SCATTERING sky with sun disc, measured per elevation (deg).
_SUN_TABLE = [
    (0, (0.0, 0.0, 0.0)), (3, (48.8, 19.3, 1.9)), (6, (82.1, 45.7, 13.4)),
    (10, (108.6, 72.7, 33.1)), (15, (127.0, 94.1, 53.6)), (20, (137.6, 107.4, 68.5)),
    (25, (144.5, 116.3, 79.3)), (35, (152.6, 127.1, 93.6)), (50, (158.5, 135.4, 105.1)),
    (70, (161.9, 140.1, 112.1)), (90, (162.5, 141.0, 113.0)),
]


def sun_irradiance(el_deg):
    if el_deg <= 0:
        return (0.0, 0.0, 0.0)
    for (e0, c0), (e1, c1) in zip(_SUN_TABLE, _SUN_TABLE[1:]):
        if e0 <= el_deg <= e1:
            f = (el_deg - e0) / (e1 - e0)
            return tuple(a + (b - a) * f for a, b in zip(c0, c1))
    return _SUN_TABLE[-1][1]


_SKY_TABLE = [  # horizontal irradiance of the sky dome alone (no sun), per elevation
    (-8, (0.0006, 0.0047, 0.0214)), (-6, (0.0018, 0.0093, 0.0402)), (-4, (0.0157, 0.0271, 0.0876)),
    (-2, (0.118, 0.124, 0.242)), (0, (0.391, 0.414, 0.605)), (3, (0.83, 1.09, 1.52)),
    (6, (1.15, 1.72, 2.59)), (10, (1.46, 2.34, 3.80)), (15, (1.73, 2.86, 4.81)),
    (20, (1.92, 3.23, 5.50)), (25, (2.08, 3.52, 6.05)), (35, (2.32, 3.96, 6.89)),
    (50, (2.59, 4.46, 7.82)), (70, (2.80, 4.87, 8.60)), (90, (2.85, 4.95, 8.75)),
]


def _interp(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (e0, c0), (e1, c1) in zip(table, table[1:]):
        if e0 <= x <= e1:
            f = (x - e0) / (e1 - e0)
            return tuple(a + (b - a) * f for a, b in zip(c0, c1))
    return table[-1][1]


def _sky_irr(el):
    return _interp(_SKY_TABLE, el)


def _whiten(c, amount):
    """Desaturate a colour toward its mean (haze is whiter than the zenith)."""
    m = sum(c) / 3.0
    return tuple(v + (m - v) * amount for v in c)


def solar_position(month, day, hour_local, utc_offset=-4.0, lat=LAT, lon=LON, year=2025):
    """Approximate solar (azimuth true bearing deg, elevation deg) (NOAA)."""
    import datetime
    doy = datetime.date(year, month, day).timetuple().tm_yday
    g = 2 * math.pi / 365.0 * (doy - 1 + (hour_local - utc_offset - 12) / 24.0)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = (hour_local - utc_offset) * 60.0 + eqt + 4.0 * lon
    ha = math.radians(tst / 4.0 - 180.0)
    la = math.radians(lat)
    cz = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    zen = math.acos(max(-1.0, min(1.0, cz)))
    el = 90.0 - math.degrees(zen)
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(decl) * math.cos(la))) + 180.0
    return az % 360.0, el


# ------------------------------------------------------------------ helpers

def _try(obj, attr, val):
    if obj is None or not hasattr(obj, attr):
        return False
    try:
        setattr(obj, attr, val)
        return True
    except Exception:
        return False


def _world(scene):
    world = bpy.data.worlds.get("Sky_53W53") or bpy.data.worlds.new("Sky_53W53")
    scene.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    nt = world.node_tree
    nodes = {n.name: n for n in nt.nodes}
    if "SKY" not in nodes or "CTRL_HORIZON_GLOW" not in nodes:
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        out.location = (600, 0)
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.name = "SKY"
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.name = "BG"
        bg.location = (300, 0)
        # Below the horizon: the physical sky is black; blend to a hazy
        # "distant city" colour (CTRL_GROUND_COLOR) so aerial views past the
        # modelled site and bounce light from below look right.
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = 0.0
        mr.inputs["From Max"].default_value = -0.18
        mr.inputs["To Min"].default_value = 0.0
        mr.inputs["To Max"].default_value = 1.0
        nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
        gcol = nt.nodes.new("ShaderNodeRGB")
        gcol.name = gcol.label = "CTRL_GROUND_COLOR"
        hcol = nt.nodes.new("ShaderNodeRGB")
        hcol.name = hcol.label = "CTRL_HORIZON_COLOR"
        grad = nt.nodes.new("ShaderNodeMix")
        grad.data_type = "RGBA"
        nt.links.new(mr.outputs["Result"], grad.inputs["Factor"])
        nt.links.new(hcol.outputs[0], next(s for s in grad.inputs if s.identifier == "A_Color"))
        nt.links.new(gcol.outputs[0], next(s for s in grad.inputs if s.identifier == "B_Color"))
        below = nt.nodes.new("ShaderNodeMath")
        below.operation = "LESS_THAN"
        below.inputs[1].default_value = 0.0
        nt.links.new(sep.outputs["Z"], below.inputs[0])
        # soft transition over ~1 deg so the horizon line isn't hard
        soft = nt.nodes.new("ShaderNodeMapRange")
        soft.inputs["From Min"].default_value = 0.004
        soft.inputs["From Max"].default_value = -0.012
        nt.links.new(sep.outputs["Z"], soft.inputs["Value"])
        # above the horizon: aerial haze brightens the lowest ~12 deg of sky
        # toward the horizon colour (factor (1 - z/0.2)^2 * 0.85)
        above = nt.nodes.new("ShaderNodeMapRange")
        above.inputs["From Min"].default_value = 0.2
        above.inputs["From Max"].default_value = 0.0
        nt.links.new(sep.outputs["Z"], above.inputs["Value"])
        sq = nt.nodes.new("ShaderNodeMath")
        sq.operation = "POWER"
        sq.inputs[1].default_value = 2.0
        nt.links.new(above.outputs["Result"], sq.inputs[0])
        amt = nt.nodes.new("ShaderNodeMath")
        amt.operation = "MULTIPLY"
        amt.name = amt.label = "CTRL_HORIZON_GLOW"
        amt.inputs[1].default_value = 0.85
        nt.links.new(sq.outputs[0], amt.inputs[0])
        mx = nt.nodes.new("ShaderNodeMath")
        mx.operation = "MAXIMUM"
        nt.links.new(amt.outputs[0], mx.inputs[0])
        nt.links.new(soft.outputs["Result"], mx.inputs[1])
        soft = type("S", (), {"outputs": {"Result": mx.outputs[0]}})()
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(soft.outputs["Result"], mix.inputs["Factor"])
        nt.links.new(sky.outputs[0], next(s for s in mix.inputs if s.identifier == "A_Color"))
        nt.links.new(next(s for s in grad.outputs if s.identifier == "Result_Color"),
                     next(s for s in mix.inputs if s.identifier == "B_Color"))
        nt.links.new(next(s for s in mix.outputs if s.identifier == "Result_Color"), bg.inputs["Color"])
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
        for t in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING", "HOSEK_WILKIE"):
            if _try(sky, "sky_type", t):
                break
    return world, nt.nodes["SKY"], nt.nodes["BG"]


def _sun(scene):
    ob = bpy.data.objects.get("Sun_Key")
    if ob is None:
        ld = bpy.data.lights.new("Sun_Key", "SUN")
        ob = bpy.data.objects.new("Sun_Key", ld)
        scene.collection.objects.link(ob)
    return ob


def set_sky(scene, az_true, el, air=1.0, aerosol=1.2, ozone=1.0, sky_scale=1.0, sun_scale=1.0):
    """Point sky + sun lamp at true bearing az_true / elevation el (deg)."""
    world, sky, bg = _world(scene)
    az_model = (az_true - GRID_ROT) % 360.0          # sky rotation = bearing from model +Y
    _try(sky, "sun_disc", False)
    _try(sky, "sun_elevation", math.radians(el))
    _try(sky, "sun_rotation", math.radians(az_model))
    _try(sky, "altitude", 60.0)
    _try(sky, "air_density", air)
    _try(sky, "aerosol_density", aerosol) or _try(sky, "dust_density", aerosol)
    _try(sky, "ozone_density", ozone)
    bg.inputs["Strength"].default_value = K * sky_scale
    # horizon/ground in physical units (x K via Background strength); derived
    # from the measured horizontal sky irradiance so it tracks sun elevation
    sk = _sky_irr(el)
    world.node_tree.nodes["CTRL_HORIZON_COLOR"].outputs[0].default_value = (
        *(c * 9.0 / math.pi for c in _whiten(sk, 0.5)), 1.0)
    world.node_tree.nodes["CTRL_GROUND_COLOR"].outputs[0].default_value = (
        *(c * 7.5 / math.pi for c in _whiten(sk, 0.5)), 1.0)
    sun = _sun(scene)
    irr = sun_irradiance(el)
    peak = max(irr) if max(irr) > 0 else 1.0
    sun.data.color = tuple(c / peak for c in irr)
    sun.data.energy = peak * K * sun_scale
    _try(sun.data, "angle", math.radians(0.53))
    sun.hide_render = el <= 0.3
    # Sun lamp points along its local -Z: direction FROM the sun.
    a = math.radians(az_model)
    e = math.radians(el)
    to_sun = (math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))
    import mathutils
    d = -mathutils.Vector(to_sun)
    sun.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    _try(sun.data, "use_shadow", True)
    try:
        sun.data.cycles.max_bounces = 1024
    except Exception:
        pass
    # world sampling
    try:
        world.cycles.sampling_method = "MANUAL"
        world.cycles.sample_map_resolution = 1024
    except Exception:
        pass
    _try(getattr(world, "cycles_visibility", None), "camera", True)
    return sun


def color_management(scene, exposure=0.0, look_contrast="Medium High Contrast", white_k=None):
    vs = scene.view_settings
    for vt in ("AgX", "Filmic", "Standard"):
        if _try(vs, "view_transform", vt):
            break
    for lk in ((("AgX - " + look_contrast) if vs.view_transform == "AgX" else look_contrast),
               look_contrast, "None"):
        if _try(vs, "look", lk):
            break
    vs.exposure = exposure
    vs.gamma = 1.0
    if white_k is not None:
        if _try(vs, "use_white_balance", True):
            _try(vs, "white_balance_temperature", white_k)
            _try(vs, "white_balance_tint", 0.0)
    else:
        _try(vs, "use_white_balance", False)
    _try(scene.display_settings, "display_device", "sRGB")
    _try(scene.sequencer_colorspace_settings, "name", "sRGB")


def cycles_settings(scene, samples=256, threshold=0.02, guiding=False):
    scene.render.engine = "CYCLES"
    cy = scene.cycles
    _try(cy, "device", "CPU")
    _try(cy, "feature_set", "SUPPORTED")
    _try(cy, "samples", samples)
    _try(cy, "use_adaptive_sampling", True)
    _try(cy, "adaptive_threshold", threshold)
    _try(cy, "adaptive_min_samples", 0)
    _try(cy, "use_light_tree", True)
    _try(cy, "light_sampling_threshold", 0.01)
    for a, v in (("max_bounces", 10), ("diffuse_bounces", 4), ("glossy_bounces", 4),
                 ("transmission_bounces", 8), ("volume_bounces", 0), ("transparent_max_bounces", 24)):
        _try(cy, a, v)
    _try(cy, "caustics_reflective", False)
    _try(cy, "caustics_refractive", False)
    _try(cy, "blur_glossy", 1.0)
    _try(cy, "sample_clamp_direct", 0.0)
    _try(cy, "sample_clamp_indirect", 6.0)
    _try(cy, "use_denoising", True)
    _try(cy, "denoiser", "OPENIMAGEDENOISE")
    _try(cy, "denoising_input_passes", "RGB_ALBEDO_NORMAL")
    _try(cy, "denoising_prefilter", "ACCURATE")
    _try(cy, "denoising_quality", "HIGH")
    _try(cy, "denoising_use_gpu", False)
    _try(cy, "use_guiding", guiding)
    _try(cy, "use_surface_guiding", guiding)
    _try(cy, "use_volume_guiding", False)
    _try(cy, "tile_size", 2048)
    _try(cy, "use_auto_tile", True)
    _try(cy, "seed", 7)
    _try(cy, "film_exposure", 1.0)
    _try(cy, "pixel_filter_type", "BLACKMAN_HARRIS")
    _try(cy, "filter_width", 1.5)
    scene.render.use_persistent_data = False
    _try(scene.render, "threads_mode", "AUTO")
    scene.render.film_transparent = False


def set_controls(values):
    """Set CTRL_* value nodes (see materials.py) in every material."""
    trees = [m.node_tree for m in bpy.data.materials if m.node_tree is not None]
    trees += [g for g in bpy.data.node_groups if g.bl_idname == "ShaderNodeTree"]
    for nt in trees:
        for n in nt.nodes:
            if n.label in values and n.type in ("VALUE", "RGB"):
                v = values[n.label]
                n.outputs[0].default_value = v if n.type == "VALUE" else (*v[:3], 1.0)


def scale_lamps(factor, kelvin=3000):
    """Interior lamps from other modules: store their original energy once,
    then scale (and give them a consistent warm colour temperature)."""
    for ob in bpy.data.objects:
        if ob.type != "LIGHT" or ob.name == "Sun_Key":
            continue
        ld = ob.data
        if "base_energy" not in ld:
            ld["base_energy"] = ld.energy
        ld.energy = ld["base_energy"] * factor
        if not _try(ld, "use_temperature", True) or not _try(ld, "temperature", kelvin):
            pass
        _try(ld, "shadow_soft_size", max(getattr(ld, "shadow_soft_size", 0.1), 0.08))


def haze_color(scene):
    """Aerial-perspective colour = world horizon colour x Background strength
    so distant geometry melts into the below-horizon world seamlessly."""
    w = scene.world
    c = w.node_tree.nodes["CTRL_HORIZON_COLOR"].outputs[0].default_value
    k = w.node_tree.nodes["BG"].inputs["Strength"].default_value
    return tuple(v * k for v in c[:3])


# ------------------------------------------------------------------ presets

DAY_DATE = (10, 1, 16.25)    # Oct 1, 4:15 pm EDT -> sun WSW ~241 deg true, ~25 deg up


def preset_day(scene=None, exposure=0.0):
    scene = scene or bpy.context.scene
    az, el = solar_position(*DAY_DATE)
    set_sky(scene, az, el, air=1.0, aerosol=1.5, ozone=1.0, sky_scale=2.0)
    color_management(scene, exposure, "Medium High Contrast", white_k=6000)
    cycles_settings(scene)
    set_controls({"CTRL_CITY_GLOW": 0.0, "CTRL_INT_LIGHT": 1.0, "CTRL_STREET": 0.0,
                  "CTRL_HAZE_DIST": 3500.0, "CTRL_HAZE_MAX": 0.9,
                  "CTRL_HAZE_COLOR": haze_color(scene)})
    scale_lamps(K * 2.0)
    scene["light_preset"] = "day"
    scene["sun_az_el"] = (round(az, 1), round(el, 1))
    return az, el


def preset_dusk(scene=None, exposure=0.0):
    """Blue hour: sun 4 deg below the horizon in the WSW, sky boosted so the
    exposure stays sane; interiors, neighbour windows and storefronts glow."""
    scene = scene or bpy.context.scene
    az, _ = solar_position(*DAY_DATE)
    el = -3.5
    set_sky(scene, az + 15.0, el, air=1.0, aerosol=1.0, ozone=1.5, sky_scale=60.0)
    nodes = scene.world.node_tree.nodes   # darker city below the twilight horizon
    for nm, k in (("CTRL_HORIZON_COLOR", 0.3), ("CTRL_GROUND_COLOR", 0.3)):
        c = nodes[nm].outputs[0].default_value
        nodes[nm].outputs[0].default_value = (c[0] * k, c[1] * k, c[2] * k, 1.0)
    color_management(scene, exposure, "Medium High Contrast", white_k=5200)
    cycles_settings(scene)
    set_controls({"CTRL_CITY_GLOW": 0.5, "CTRL_INT_LIGHT": 4.0, "CTRL_STREET": 1.5,
                  "CTRL_HAZE_DIST": 4500.0, "CTRL_HAZE_MAX": 0.9,
                  "CTRL_HAZE_COLOR": haze_color(scene)})
    scale_lamps(K * 6.0)
    scene["light_preset"] = "dusk"
    return az, el


PRESETS = {"day": preset_day, "dusk": preset_dusk}


def apply(ctx=None):
    scene = bpy.context.scene
    az, el = preset_day(scene)
    print(f"[lighting] day preset: sun az {az:.0f} true ({(az - GRID_ROT) % 360:.0f} model), "
          f"el {el:.1f}, view {scene.view_settings.view_transform}/{scene.view_settings.look}")
