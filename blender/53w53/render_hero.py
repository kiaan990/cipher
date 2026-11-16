"""Photoreal Cycles hero renders of the 53 West 53 model -> out/hero/.

    python3 render_hero.py [--shots a,d] [--res 1600x900] [--samples N]
                           [--preset day|dusk] [--blend out/53W53.blend]
                           [--rebuild] [--no-auto-exposure] [--exr]

Shots (key: name)
  a street      W 53rd St sidewalk, 24 mm at eye height looking up the tower
  b aerial      three-quarter view from the SW above Midtown
  c aerial_dusk (b) at blue hour (always uses the dusk preset)
  d lobby       F01 lobby
  e pool        F06 pool
  f apartment   typical apartment ~F30 looking out of the window
  g penthouse   F77 penthouse
  h street_dusk (a) at blue hour

Opens out/53W53.blend (or rebuilds with --rebuild / when missing), re-applies
the materials pass (cheap, so material edits show up without a rebuild) and
the lighting preset, then renders each shot with Cycles (CPU, adaptive
sampling, light tree, OIDN denoising with albedo+normal passes).

Exposure: a quick 8-sample proxy render measures the log-average scene
luminance and sets view exposure so it lands on a per-shot key value
(manual offsets on top). Disable with --no-auto-exposure.
"""
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bpy  # noqa: E402
import mathutils  # noqa: E402

OUT = os.path.join(HERE, "out")
HERO = os.path.join(OUT, "hero")
EYE = 1.65


def _z(n, add=EYE):
    import config as C
    return C.floor_z(n) + add


# key: dict(name, cam=(loc, target, lens) | view=<camera name>, preset, key, ev,
#           samples (multiplier of --samples), guiding, shift_y)
def shots():
    """Cameras coordinated with the exterior/interiors modules (floor z from
    config at the time they were chosen). Interior shots can instead use
    the automatic ray-cast camera picker: --auto-cams (keys with `auto`)."""
    street = ((-14.0, -20.0, 1.6), (24.0, 6.0, 120.0), 18.0)
    aerial = ((-420.0, -520.0, 420.0), (30.0, 40.0, 120.0), 35.0)
    I = dict(samples=0.75, guiding=False, hl=16.0)   # interior defaults (OIDN does the rest)
    return {
        "a": dict(name="street", cam=street, key=0.12, samples=1.0),
        "b": dict(name="aerial", cam=aerial, key=0.11, samples=0.8),
        "c": dict(name="aerial_dusk", cam=aerial, preset="dusk", fixed_ev=-1.6, samples=1.2),
        "d": dict(name="lobby", cam=((40.0, 3.0, 1.9), (12.0, 18.0, 3.3), 16.0),
                  auto=(1, "deep", 18.0, math.radians(90)), key=0.12, wb=4600, **I),
        "e": dict(name="pool", cam=((33.5, 4.8, 30.7), (5.0, 4.5, 31.0), 16.0),
                  auto=(6, "water", 18.0, None), key=0.14, wb=4500, **I),
        "f": dict(name="apartment_f30", cam=((6.5, 23.0, 118.9), (6.0, 4.0, 118.3), 16.0),
                  auto=(30, "view", 20.0, math.radians(225)), key=0.16, wb=5000, **I),
        "g": dict(name="penthouse_f77", cam=((22.9, 25.2, 288.1), (23.0, 14.0, 287.9), 16.0),
                  auto=(77, "view", 18.0, math.radians(270)), key=0.16, wb=5000, **I),
        "h": dict(name="street_dusk", cam=street, preset="dusk", fixed_ev=-1.2, samples=1.2),
        "i": dict(name="library", cam=((9.6, 21.5, 1.7), (3.8, 10.5, 1.6), 16.0), key=0.14, wb=4000, **I),
        "j": dict(name="wine_room_f07", cam=((10.2, 18.7, 36.1), (5.0, 10.5, 35.8), 16.0), key=0.12,
                  wb=3800, **I),
        "k": dict(name="crown", cam=((5.0, 620.0, 110.0), (22.0, 16.0, 292.0), 200.0), key=0.12, ev=1.5,
                  samples=0.8),  # north side is in shade: sky dominates the meter
        "m": dict(name="crown_close", cam=((-60.0, 120.0, 300.0), (21.0, 14.0, 300.0), 50.0), key=0.12,
                  samples=0.8),
        "l": dict(name="lobby_entrance", cam=((21.0, 1.2, 1.6), (21.0, 12.0, 3.2), 18.0), key=0.12,
                  wb=4300, **I),
    }


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = dict(shots="a,b,c,d,e,f,g,i,k", res=(1600, 900), samples=64, preset="day",
             blend=os.path.join(OUT, "53W53.blend"), rebuild=False, auto=True, exr=False)
    i = 0
    while i < len(argv):
        k = argv[i]
        if k == "--shots":
            a["shots"] = argv[i + 1]; i += 1
        elif k == "--res":
            w, h = argv[i + 1].lower().split("x"); a["res"] = (int(w), int(h)); i += 1
        elif k == "--samples":
            a["samples"] = int(argv[i + 1]); i += 1
        elif k == "--preset":
            a["preset"] = argv[i + 1]; i += 1
        elif k == "--blend":
            a["blend"] = argv[i + 1]; i += 1
        elif k == "--rebuild":
            a["rebuild"] = True
        elif k == "--no-auto-exposure":
            a["auto"] = False
        elif k == "--cam":   # x,y,z,tx,ty,tz,lens[,shift_y] overrides the shot camera
            a["cam"] = [float(v) for v in argv[i + 1].split(",")]; i += 1
        elif k == "--tag":
            a["tag"] = argv[i + 1]; i += 1
        elif k == "--auto-cams":
            a["auto_cams"] = True
        elif k == "--no-guiding":
            a["no_guiding"] = True
        elif k == "--exr":
            a["exr"] = True
        i += 1
    return a


def load_scene(args):
    if args["rebuild"] or not os.path.exists(args["blend"]):
        import build
        sys.argv = [sys.argv[0], "--no-glb", "--no-render"]
        build.main()
    else:
        bpy.ops.wm.open_mainfile(filepath=args["blend"])
    import importlib
    from modules import materials, lighting
    importlib.reload(materials)
    importlib.reload(lighting)
    materials.apply(force=True)
    from modules import render_context
    importlib.reload(render_context)
    render_context.ensure(bpy.context.scene)
    return bpy.context.scene, lighting


def camera(scene, spec):
    cam = bpy.data.objects.get("HeroCam")
    if cam is None:
        cam = bpy.data.objects.new("HeroCam", bpy.data.cameras.new("HeroCam"))
        scene.collection.objects.link(cam)
    cd = cam.data
    cd.clip_start, cd.clip_end = 0.05, 6000.0
    cd.sensor_width = 36.0
    cd.shift_x = cd.shift_y = 0.0
    if "auto" in spec and (spec.get("auto_cams") or "cam" not in spec):
        from modules import render_cams
        floor, goal, lens, prefer = spec["auto"]
        res = render_cams.best_interior_cam(floor, goal, lens=lens, prefer=prefer)
        if res is not None:
            cam.location, cam.rotation_euler, cd.lens = res
            scene.camera = cam
            return cam
    if "view" in spec and bpy.data.objects.get(spec["view"]):
        src = bpy.data.objects[spec["view"]]
        cam.matrix_world = src.matrix_world.copy()
        cd.lens = spec.get("lens", src.data.lens)
    else:
        loc, tgt, lens = spec["cam"]
        cam.location = loc
        d = mathutils.Vector(tgt) - mathutils.Vector(loc)
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cd.lens = lens
    cd.shift_y = spec.get("shift_y", 0.0)
    scene.camera = cam
    return cam


def _read_exr(path, w, h):
    import numpy as np
    img = bpy.data.images.load(path, check_existing=False)
    try:
        a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[..., :3]
    finally:
        bpy.data.images.remove(img)
    return a


def auto_exposure(scene, key, tmpdir, hl=12.0):
    """Proxy render (tiny, few samples) -> exposure so the log-average
    luminance maps to `key` (scene-linear, before the view transform)."""
    import numpy as np
    r = scene.render
    saved = (r.resolution_x, r.resolution_y, r.resolution_percentage, scene.cycles.samples,
             scene.cycles.use_denoising, r.image_settings.file_format, r.filepath,
             scene.view_settings.exposure)
    w = 160
    h = max(2, int(round(w * saved[1] / saved[0])))
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    scene.cycles.samples = 8
    scene.cycles.use_denoising = False
    r.image_settings.file_format = "OPEN_EXR"
    r.image_settings.color_depth = "32"
    path = os.path.join(tmpdir, "_ae.exr")
    r.filepath = path
    bpy.ops.render.render(write_still=True)
    a = _read_exr(path, w, h)
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    lum = np.clip(lum, 1e-5, None)
    # ignore the brightest 2% (light fixtures, sun glints) and darkest 2 %
    lo, hi, p99 = np.percentile(lum, [2, 98, 99.0])
    sel = lum[(lum >= lo) & (lum <= hi)]
    logavg = float(np.exp(np.log(sel).mean()))
    ev = math.log2(key / logavg)
    # highlight guard: keep the 99th percentile below `hl` (scene-linear) after
    # exposure so windows/fixtures in dark rooms do not blow out entirely
    ev = min(ev, math.log2(hl / max(float(p99), 1e-5)))
    (r.resolution_x, r.resolution_y, r.resolution_percentage, scene.cycles.samples,
     scene.cycles.use_denoising, r.image_settings.file_format, r.filepath, _) = saved
    return max(-6.0, min(8.0, ev)), logavg


def render_shot(scene, lighting, key, spec, args):
    preset = spec.get("preset", args["preset"])
    lighting.PRESETS[preset](scene)
    if spec.get("wb"):
        lighting.color_management(scene, 0.0, "Medium High Contrast", white_k=spec["wb"])
    guiding = spec.get("guiding", False) and not args.get("no_guiding")
    lighting.cycles_settings(scene, samples=max(16, int(args["samples"] * spec.get("samples", 1.0))),
                             threshold=0.015, guiding=guiding)
    r = scene.render
    r.resolution_x, r.resolution_y = args["res"]
    r.resolution_percentage = 100
    camera(scene, spec)
    t0 = time.time()
    ev = 0.0
    if "fixed_ev" in spec:
        ev = spec["fixed_ev"]
    elif args["auto"]:
        ev, la = auto_exposure(scene, spec.get("key", 0.18), HERO, spec.get("hl", 12.0))
        print(f"[hero] {key} auto-exposure: log-avg {la:.4f} -> {ev:+.2f} EV")
    scene.view_settings.exposure = ev + spec.get("ev", 0.0)
    name = f"{key}_{spec['name']}" + ("" if preset == "day" or "dusk" in spec["name"] else "_" + preset)
    fmt = r.image_settings
    if args["exr"]:
        fmt.file_format = "OPEN_EXR"
        fmt.color_depth = "16"
        bpy.ops.render.render()
        bpy.data.images["Render Result"].save_render(os.path.join(HERO, name + ".exr"))
    fmt.file_format = "PNG"
    fmt.color_mode = "RGB"
    fmt.color_depth = "8"
    path = os.path.join(HERO, name + ".png")
    r.filepath = path
    t1 = time.time()
    if args["exr"]:
        bpy.data.images["Render Result"].save_render(path)
    else:
        bpy.ops.render.render(write_still=True)
    dt = time.time() - t1
    print(f"[hero] {key} {spec['name']} ({preset}) {r.resolution_x}x{r.resolution_y} "
          f"{scene.cycles.samples} spp: render {dt:.0f}s (+{t1 - t0:.0f}s exposure probe) -> {path}")
    return path, dt


def main():
    args = parse_args()
    os.makedirs(HERO, exist_ok=True)
    scene, lighting = load_scene(args)
    table = shots()
    done = []
    for key in [k.strip() for k in args["shots"].split(",") if k.strip()]:
        if key not in table:
            print(f"[hero] unknown shot {key!r}; known: {', '.join(table)}")
            continue
        spec = dict(table[key])
        spec["auto_cams"] = args.get("auto_cams", False)
        if args.get("cam"):
            c = args["cam"]
            spec.pop("view", None)
            spec.pop("auto", None)
            spec["cam"] = (tuple(c[0:3]), tuple(c[3:6]), c[6])
            spec["shift_y"] = c[7] if len(c) > 7 else 0.0
        if args.get("tag"):
            spec["name"] += "_" + args["tag"]
        done.append(render_shot(scene, lighting, key, spec, args))
    for p, dt in done:
        print(f"[hero] {dt:6.0f}s  {p}")


if __name__ == "__main__":
    main()
