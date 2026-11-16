"""Quick preview renders (Workbench, fast) from fixed viewpoints."""
import math
import os
import bpy
import mathutils
import config as C

VIEWS = {
    # name: (camera location, look-at target, lens mm)
    "street_53rd": ((-35.0, -45.0, 1.7), (21.0, 14.0, 120.0), 16),
    "aerial_sw": ((-260.0, -330.0, 260.0), (21.0, 14.0, 150.0), 35),
    "crown": ((120.0, -120.0, 330.0), (21.0, 14.0, 280.0), 28),
}


def _look(cam, target):
    d = mathutils.Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def render_previews(ctx, tag="", views=None, size=(960, 640), engine="BLENDER_WORKBENCH"):
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.image_settings.file_format = "PNG"
    if engine == "BLENDER_WORKBENCH":
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_shadows = True
        sh.show_cavity = True
        scene.display.shading.show_object_outline = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    cam_data = bpy.data.cameras.new("PreviewCam")
    cam = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(cam)
    cam_data.clip_end = 5000
    prev = scene.camera
    scene.camera = cam
    out = []
    for name, (loc, tgt, lens) in (views or VIEWS).items():
        cam.location = loc
        cam_data.lens = lens
        _look(cam, tgt)
        path = os.path.join(ctx["out"], f"preview_{name}{tag}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        out.append(path)
        print("[preview]", path)
    scene.camera = prev
    bpy.data.objects.remove(cam)
    return out
