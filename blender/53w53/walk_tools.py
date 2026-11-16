"""53W53 walk tools: first-person walking helpers for the 53 West 53 model.

Embedded in 53W53.blend as the Text datablock "walk_tools.py" (Register
ticked, so it runs on file load when "Auto Run Python Scripts" is allowed).
You can also run it by hand: Scripting tab > Text Editor > open this file
(or pick the embedded text) > Run Script.

Adds a "53W53" tab to the 3D viewport sidebar (press N):
  * Floor number + "Take Lift"  - jump WalkCam / the view to that floor's
    lift lobby (LIFT_STOP_F## empties, else points stored by the build).
  * Viewpoint buttons            - look through View_* cameras.
  * "Start Walk"                 - look through WalkCam and start Blender's
    walk navigation (WASD + mouse, Tab = gravity, Space = teleport).
Works on Blender 4.2 - 5.x. Needs no other project files.
"""
import json

import bpy
from mathutils import Euler, Matrix, Vector

EYE = 1.65
VIEW_PREFIX = "View_"
LIFT_PREFIX = "LIFT_STOP_F"


# ------------------------------------------------------------------ helpers
def _floor_table(scene):
    """[{n, z, lift: [x, y]}] written by modules/walk.py at build time."""
    raw = scene.get("walk53_floors")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _num_floors(scene):
    return len(_floor_table(scene)) or 77


def lift_point(scene, n):
    """World-space eye position + yaw (radians, 0 = facing +Y/north) for
    floor n's lift lobby. Prefers the interiors' LIFT_STOP_F## empties."""
    ob = bpy.data.objects.get("%s%02d" % (LIFT_PREFIX, n))
    if ob is not None:
        p = ob.matrix_world.translation
        yaw = ob.matrix_world.to_euler().z
        return Vector((p.x, p.y, p.z + EYE)), yaw
    for f in _floor_table(scene):
        if f.get("n") == n:
            x, y = f["lift"]
            return Vector((x, y, f["z"] + EYE)), 0.0
    return None, 0.0


def _view3d(context):
    """(window, area, region, space) of a 3D viewport, preferring context's."""
    area = context.area if context.area and context.area.type == "VIEW_3D" else None
    win = context.window
    if area is None:
        wm = context.window_manager
        for w in (wm.windows if wm else []):
            for a in w.screen.areas:
                if a.type == "VIEW_3D":
                    win, area = w, a
                    break
            if area:
                break
    if area is None:
        return None, None, None, None
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    return win, area, region, area.spaces.active


def _walkcam(scene):
    cam = bpy.data.objects.get("WalkCam")
    if cam is None:
        data = bpy.data.cameras.new("WalkCam")
        data.lens, data.clip_end = 20, 3000
        cam = bpy.data.objects.new("WalkCam", data)
        scene.collection.objects.link(cam)
    return cam


def _look_through(context, cam):
    scene = context.scene
    scene.camera = cam
    _w, _a, _r, space = _view3d(context)
    if space is not None:
        space.region_3d.view_perspective = "CAMERA"
        space.clip_end = max(space.clip_end, 3000)
        space.clip_start = min(space.clip_start, 0.05)


def apply_walk_prefs():
    """Comfortable human-scale walk navigation defaults (session only)."""
    try:
        wn = bpy.context.preferences.inputs.walk_navigation
    except Exception:
        return
    for attr, val in (("use_gravity", True), ("view_height", EYE), ("walk_speed", 1.8),
                      ("walk_speed_factor", 3.0), ("jump_height", 0.5),
                      ("teleport_time", 0.4), ("mouse_speed", 1.0)):
        if hasattr(wn, attr):
            try:
                setattr(wn, attr, val)
            except Exception:
                pass


# ---------------------------------------------------------------- operators
class WALK53_OT_take_lift(bpy.types.Operator):
    """Ride the lift: move WalkCam (and the view) to the chosen floor's lift lobby"""
    bl_idname = "walk53.take_lift"
    bl_label = "Take Lift"
    bl_options = {"REGISTER", "UNDO"}

    floor: bpy.props.IntProperty(name="Floor", default=0, min=0, max=200)

    def execute(self, context):
        scene = context.scene
        n = self.floor or scene.walk53_floor
        n = max(1, min(n, _num_floors(scene)))
        pos, yaw = lift_point(scene, n)
        if pos is None:
            self.report({"WARNING"}, "No lift stop for floor %d" % n)
            return {"CANCELLED"}
        cam = _walkcam(scene)
        cam.location = pos
        cam.rotation_euler = Euler((1.5708, 0.0, yaw), "XYZ")  # level, facing yaw
        _look_through(context, cam)
        scene.walk53_floor = n
        self.report({"INFO"}, "Floor %d  (%.1f m)" % (n, pos.z - EYE))
        return {"FINISHED"}


class WALK53_OT_view(bpy.types.Operator):
    """Look through a viewpoint camera"""
    bl_idname = "walk53.view"
    bl_label = "Viewpoint"

    camera: bpy.props.StringProperty()

    def execute(self, context):
        cam = bpy.data.objects.get(self.camera)
        if cam is None or cam.type != "CAMERA":
            self.report({"WARNING"}, "Camera %s not found" % self.camera)
            return {"CANCELLED"}
        _look_through(context, cam)
        return {"FINISHED"}


class WALK53_OT_start_walk(bpy.types.Operator):
    """Look through WalkCam and start walk navigation (from the current viewpoint camera if one is active)"""
    bl_idname = "walk53.start_walk"
    bl_label = "Start Walk"

    def execute(self, context):
        scene = context.scene
        apply_walk_prefs()
        cam = _walkcam(scene)
        active = scene.camera
        if active is not None and active is not cam and active.name.startswith(VIEW_PREFIX):
            # Start walking where the viewpoint is, levelled out.
            m = active.matrix_world
            cam.location = m.translation
            e = m.to_euler()
            cam.rotation_euler = Euler((1.5708, 0.0, e.z), "XYZ")
        _look_through(context, cam)
        win, area, region, _space = _view3d(context)
        if area is None:
            self.report({"WARNING"}, "Open a 3D Viewport first")
            return {"CANCELLED"}
        try:
            with context.temp_override(window=win, area=area, region=region):
                bpy.ops.view3d.walk("INVOKE_DEFAULT")
        except Exception as exc:  # e.g. run from a non-3D area without a window
            self.report({"WARNING"}, "Hover the 3D view and press Shift+` (%s)" % exc)
        return {"FINISHED"}


# -------------------------------------------------------------------- panel
class WALK53_PT_panel(bpy.types.Panel):
    bl_label = "53 West 53 Walk"
    bl_idname = "WALK53_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "53W53"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("walk53.start_walk", icon="PLAY")
        layout.label(text="Shift+` walk  |  Tab gravity  |  Esc stop")

        box = layout.box()
        box.label(text="Lift", icon="SORT_ASC")
        row = box.row(align=True)
        row.prop(scene, "walk53_floor", text="Floor")
        row.operator("walk53.take_lift", text="Take Lift").floor = 0
        grid = box.grid_flow(columns=3, align=True)
        for label, n in (("Lobby", 1), ("MoMA 2", 2), ("MoMA 4", 4), ("MoMA 5", 5),
                         ("Pool 6", 6), ("Amenity 7", 7), ("30", 30), ("60", 60),
                         ("Penthouse", _num_floors(scene))):
            grid.operator("walk53.take_lift", text=label).floor = n

        box = layout.box()
        box.label(text="Viewpoints", icon="OUTLINER_OB_CAMERA")
        cams = sorted(o.name for o in bpy.data.objects
                      if o.type == "CAMERA" and o.name.startswith(VIEW_PREFIX))
        col = box.column(align=True)
        for name in cams:
            col.operator("walk53.view", text=name[len(VIEW_PREFIX):].replace("_", " ")).camera = name
        if "WalkCam" in bpy.data.objects:
            col.operator("walk53.view", text="WalkCam").camera = "WalkCam"


CLASSES = (WALK53_OT_take_lift, WALK53_OT_view, WALK53_OT_start_walk, WALK53_PT_panel)


def register():
    unregister()  # allow re-running from the Text Editor
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.walk53_floor = bpy.props.IntProperty(
        name="Floor", description="Floor to ride the lift to", default=1, min=1, max=77)
    apply_walk_prefs()


def unregister():
    for cls in reversed(CLASSES):
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception:
                pass
    if hasattr(bpy.types.Scene, "walk53_floor"):
        try:
            del bpy.types.Scene.walk53_floor
        except Exception:
            pass


# Registered text modules are executed with a module __name__, scripts run from
# the Text Editor with "__main__": register in both cases.
register()
