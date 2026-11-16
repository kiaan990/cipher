"""Build the 53 West 53 model.

Run headless:   blender -b -P build.py -- [--only exterior,site] [--no-render]
or in this repo: python3 build.py [--only ...]   (with `pip install bpy`)
or in Blender:  open the Scripting tab, open build.py, press Run Script.

Outputs go to ./out/: 53W53.blend, 53W53.glb (for the web walkthrough) and
preview PNGs.
"""
import os
import sys
import time
import importlib

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
sys.path.insert(0, HERE)

import bpy  # noqa: E402
import config  # noqa: E402

MODULES = ["exterior", "interiors", "site", "walk"]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    only, render, glb = None, True, True
    i = 0
    while i < len(argv):
        if argv[i] == "--only":
            only = argv[i + 1].split(",")
            i += 1
        elif argv[i] == "--no-render":
            render = False
        elif argv[i] == "--no-glb":
            glb = False
        i += 1
    return only, render, glb


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "53W53"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def main():
    only, render, glb = parse_args()
    reset_scene()
    importlib.reload(config)
    ctx = {"root": bpy.context.scene.collection, "out": os.path.join(HERE, "out")}
    os.makedirs(ctx["out"], exist_ok=True)
    for name in MODULES:
        if only and name not in only:
            continue
        t = time.time()
        mod = importlib.import_module("modules." + name)
        importlib.reload(mod)
        mod.build(ctx)
        print(f"[build] {name}: {time.time() - t:.1f}s, objects={len(bpy.data.objects)}")
    tag = "" if not only else "_" + "-".join(only)
    blend = os.path.join(ctx["out"], f"53W53{tag}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    print("[build] saved", blend)
    if glb and not only:
        from modules import export
        export.export_glb(ctx)
    if render:
        from modules import preview
        preview.render_previews(ctx, tag)


if __name__ == "__main__":
    main()
