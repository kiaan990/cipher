"""Walk module: first-person walking inside Blender.

Creates collection "Walk" with WalkCam (scene camera, on the 53rd St sidewalk
looking at the entrance) and named viewpoint cameras, embeds the walk_tools.py
panel script (auto-registers on load) and README_WALK, and sets EEVEE, world
sky and viewport defaults. Runs last, so it can read the interiors' empties.
"""
import json
import math
import os

import bpy
import mathutils

import config as C

EYE = 1.65
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKY = (0.53, 0.68, 0.86, 1.0)

README = """53 WEST 53 - WALKING THROUGH THE MODEL
======================================

Quick start
-----------
1. Allow scripts: Preferences > Save & Load > Auto Run Python Scripts, or
   Text Editor > walk_tools.py > Run Script (registers the panel now).
2. In a 3D Viewport press N and open the "53W53" tab.
3. Click "Start Walk". You start on the 53rd St sidewalk facing the door.

Walk mode controls (Blender's built-in walk navigation)
------------------------------------------------------
  Shift + `  (grave/backtick)  enter walk mode in the hovered 3D view
  W A S D          move            Mouse            look
  Shift (hold)     run             Alt (hold)       slow
  Tab              toggle gravity (off = fly)
  E / Q            up / down (when gravity is off)
  Space            teleport to the point under the cursor
  V                jump            Wheel / + -      change speed
  Left click / Enter  stop here     Right click / Esc  cancel (go back)

If you are looking through a camera (Numpad 0) walk mode moves that camera.

The 53W53 panel
---------------
  Start Walk     look through WalkCam (or from the active View_* camera)
                 and start walk mode.
  Floor + Take Lift  jump to that floor's lift lobby (eye height 1.65 m).
  Shortcut buttons   Lobby, MoMA galleries 2/4/5, Pool 6, Amenity 7, 30,
                     60, Penthouse 77.
  Viewpoints     look through View_Street, View_Lobby, View_Gallery_F04,
                 View_Pool_F06, View_Apartment_F30, View_Penthouse_F77,
                 View_Aerial.

Tips
----
* Blender's walk-mode gravity climbs stairs poorly (it can snag on risers).
  "Take Lift" is the reliable way between floors; or press Tab to fly up
  the stair shaft.
* Switch the viewport to Material Preview (Z > Material Preview) to see the
  glass and materials. Render engine is EEVEE.
* The web walkthrough (web/index.html, loading 53W53.glb + walkdata.json
  from the same folder) has collision, stairs and a lift picker. Serve it
  locally with:  cd web && python3 -m http.server 8000
"""


def _look(cam, target):
    d = mathutils.Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def _camera(name, loc, target, lens, col):
    data = bpy.data.cameras.get(name) or bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_start = 0.05
    data.clip_end = 3000
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, data)
        col.objects.link(cam)
    cam.location = loc
    _look(cam, target)
    return cam


def _inside(poly, x, y, margin=0.0):
    ip = C.inset(poly, margin) if margin > 0 else poly
    if len(ip) < 3:
        return False
    for i in range(len(ip)):
        (ax, ay), (bx, by) = ip[i], ip[(i + 1) % len(ip)]
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < 0:
            return False
    return True


def lift_stop_xy(n):
    """Lift-lobby point in plan, in front of the (north-facing) lift doors.

    Uses the interiors' LIFT_STOP_F## empty when present."""
    ob = bpy.data.objects.get("LIFT_STOP_F%02d" % n)
    if ob is not None:
        p = ob.matrix_world.translation
        return (round(p.x, 3), round(p.y, 3))
    x0, y0, x1, y1 = C.elevator_rect(n)
    poly = C.plate(n)
    for dy in (1.5, 1.0, 0.7):
        p = ((x0 + x1) / 2, y1 + dy)
        if poly and _inside(poly, p[0], p[1], 0.6):
            return p
    cx, cy = C.centroid(poly) if poly else ((x0 + x1) / 2, y1)
    return (cx, cy)


def floor_table():
    rows = []
    for n in range(1, C.NUM_FLOORS + 1):
        rows.append({"n": n, "z": round(C.floor_z(n), 3), "h": round(C.floor_height(n), 3),
                     "lift": [round(v, 3) for v in lift_stop_xy(n)]})
    return rows


def _make_cameras(col):
    cams = {}
    cams["WalkCam"] = _camera("WalkCam", (C.ENTRANCE[0], -4.0, EYE),
                              (C.ENTRANCE[0], 10.0, EYE + 0.4), 20, col)
    cams["WalkCam"].rotation_euler = mathutils.Euler((math.radians(93), 0, 0), "XYZ")
    tz = C.roof_z() * 0.35
    _camera("View_Street", (-8.0, -19.0, 1.7), (22.0, 12.0, tz), 16, col)
    _camera("View_Lobby", (C.ENTRANCE[0], 3.0, EYE), (C.ENTRANCE[0] + 4, 20.0, 2.6), 18, col)
    # Gallery: west side looking east across the open plate.
    z4 = C.floor_z(4) + EYE
    _camera("View_Gallery_F04", (4.0, 5.0, z4), (40.0, 12.0, z4 + 0.3), 18, col)
    z6 = C.floor_z(6) + EYE
    _camera("View_Pool_F06", (38.0, 4.0, z6), (2.0, 10.0, z6 - 0.4), 18, col)
    # Apartment: north-east, looking south-west out over Midtown.
    z30 = C.floor_z(30) + EYE
    _camera("View_Apartment_F30", (37.0, 18.0, z30), (0.0, -20.0, z30 - 6.0), 18, col)
    n = C.NUM_FLOORS
    z = C.floor_z(n) + EYE
    poly = C.plate(n)
    cx, cy = C.centroid(poly)
    # look out through the nearest facet, slightly down
    _camera("View_Penthouse_F77", (cx, cy + 3.0, z), (cx - 10.0, cy - 40.0, z - 12.0), 16, col)
    _camera("View_Aerial", (-260.0, -330.0, 260.0), (21.0, 14.0, 150.0), 35, col)
    return cams


def _world(scene):
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.color = SKY[:3]
    try:
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = SKY
            bg.inputs["Strength"].default_value = 1.0
    except Exception:
        pass


def _render_settings(scene):
    try:
        scene.render.engine = C.eevee_engine()
    except Exception:
        pass
    ee = scene.eevee
    for attr, val in (("taa_render_samples", 32), ("taa_samples", 8),
                      ("use_gtao", True), ("use_raytracing", False),
                      ("shadow_ray_count", 1), ("shadow_step_count", 4),
                      ("use_shadows", True)):
        if hasattr(ee, attr):
            try:
                setattr(ee, attr, val)
            except Exception:
                pass
    scene.render.resolution_x, scene.render.resolution_y = 1600, 900
    try:
        scene.view_settings.view_transform = "AgX" if "AgX" in [
            i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    except Exception:
        pass
    # Workbench / solid shading defaults (persist in the .blend)
    sh = scene.display.shading
    for attr, val in (("light", "STUDIO"), ("color_type", "MATERIAL"),
                      ("show_shadows", True), ("show_cavity", True)):
        try:
            setattr(sh, attr, val)
        except Exception:
            pass


def _viewports(cam):
    """Configure any 3D viewports in the saved screens (none when headless
    from factory-empty, harmless then)."""
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.clip_start, space.clip_end = 0.05, 3000
                try:
                    space.shading.type = "MATERIAL"
                except Exception:
                    pass
                try:
                    space.region_3d.view_perspective = "CAMERA"
                except Exception:
                    pass


def _texts(scene):
    path = os.path.join(HERE, "walk_tools.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    for name, body, module in (("walk_tools.py", src, True), ("README_WALK", README, False)):
        txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        txt.clear()
        txt.write(body)
        txt.use_module = module


def _panel_now():
    """Register the panel in this session too (harmless headless)."""
    try:
        ns = {"__name__": "walk_tools"}
        exec(compile(bpy.data.texts["walk_tools.py"].as_string(), "walk_tools.py", "exec"), ns)
    except Exception as exc:
        print("[walk] panel registration skipped:", exc)


def build(ctx):
    scene = bpy.context.scene
    col = C.collection("Walk", ctx.get("root"))
    cams = _make_cameras(col)
    scene.camera = cams["WalkCam"]
    scene["walk53_floors"] = json.dumps(floor_table())
    _world(scene)
    _render_settings(scene)
    _viewports(cams["WalkCam"])
    _texts(scene)
    _panel_now()
    found = sum(1 for n in range(1, C.NUM_FLOORS + 1) if bpy.data.objects.get("LIFT_STOP_F%02d" % n))
    print("[walk] cameras:", ", ".join(o.name for o in col.objects),
          "| LIFT_STOP empties found: %d/%d" % (found, C.NUM_FLOORS))
