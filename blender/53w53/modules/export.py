"""GLB export for the web walkthrough (owned by the walk agent)."""
import os
import bpy


def export_glb(ctx):
    path = os.path.join(ctx["out"], "53W53.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True)
    print("[export]", path, os.path.getsize(path) // 1024, "KB")
