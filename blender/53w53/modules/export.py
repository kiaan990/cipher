"""GLB + walkdata.json export for the web walkthrough (owned by the walk agent).

out/53W53.glb      exterior + interiors + site, modifiers applied, custom
                   properties as glTF extras (floor, collide, group, ...).
out/walkdata.json  floor table from config.py for collision / lift / HUD.
Both are also copied to web/ so that folder is self-contained.

Size budget: 14 MB per file (web artifact limit is 15 MB; this bpy has no
Draco/meshopt). If the full export is too big it retries without UVs/normals
(the viewer uses flat shading then), and as a last resort splits interior
floors into extra files 53W53_floors_AA-BB.glb that the viewer streams in.

Axes: Blender is Z-up (x east, y north, z up). glTF / three.js is Y-up:
Blender (x, y, z) -> glTF (x, z, -y). walkdata.json keeps plan data in
Blender coordinates; see its "axes" field.
"""
import json
import os
import shutil

import bpy

import config as C

BUDGET = 14 * 1024 * 1024
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
GROUPS = ("Exterior", "Interiors", "Site")
# Floors always kept in the main file when splitting (lobby, MoMA, amenity, PH)
KEY_FLOORS = (1, 2, 3, 4, 5, 6, 7, C.NUM_FLOORS)


# ------------------------------------------------------------------ helpers
def _top_group(ob):
    """Name of the top-level collection (Exterior / Interiors / Site / ...)."""
    root = bpy.context.scene.collection
    parents = {}

    def walk(col):
        for ch in col.children:
            parents[ch.name] = col
            walk(ch)
    walk(root)
    for col in ob.users_collection:
        c = col
        while c.name in parents and parents[c.name] is not root:
            c = parents[c.name]
        return c.name
    return ""


def _exportable():
    obs = []
    for ob in bpy.context.scene.objects:
        if ob.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT", "EMPTY"}:
            continue
        g = _top_group(ob)
        if g == "Walk":
            continue
        if ob.type == "EMPTY" and not ob.name.startswith(("LIFT_STOP_F", "STAIR_DOOR_F")):
            continue  # keep only the walk-relevant markers
        obs.append((ob, g))
    return obs


def _tag(obs):
    """Make sure every exported object carries a usable `group` extra (and a
    floor when it can be inferred) so the viewer can filter collision."""
    for ob, g in obs:
        if ob.get("group") != g:
            ob["group"] = g
        if "floor" not in ob:
            if g == "Site":
                ob["floor"] = 0
            elif g == "Interiors":
                for col in ob.users_collection:
                    if col.name[:1] == "F" and col.name[1:].isdigit():
                        ob["floor"] = int(col.name[1:])
                        break


def _uses_images():
    for m in bpy.data.materials:
        if m.use_nodes and m.node_tree:
            if any(n.type == "TEX_IMAGE" and n.image for n in m.node_tree.nodes):
                return True
    return False


def _export(path, objects, lean):
    vl = bpy.context.view_layer
    for ob in vl.objects:
        try:
            ob.select_set(False)
        except RuntimeError:
            pass
    n = 0
    for ob in objects:
        try:
            ob.select_set(True)
            n += 1
        except RuntimeError:  # not in view layer (excluded collection)
            pass
    if n == 0:
        return 0
    kw = dict(filepath=path, export_format="GLB", use_selection=True,
              export_apply=True, export_extras=True, export_yup=True,
              export_cameras=False, export_lights=False,
              export_texcoords=_uses_images(), export_normals=not lean,
              export_tangents=False, export_materials="EXPORT",
              export_animations=False)
    rna = bpy.ops.export_scene.gltf.get_rna_type().properties
    kw = {k: v for k, v in kw.items() if k in rna}
    bpy.ops.export_scene.gltf(**kw)
    for ob in objects:
        try:
            ob.select_set(False)
        except RuntimeError:
            pass
    return os.path.getsize(path)


def _mb(b):
    return "%.2f MB" % (b / 1048576.0)


# ------------------------------------------------------------- walk data
def _r(v):
    return round(v, 3)


def _poly(p):
    return [[_r(x), _r(y)] for x, y in p]


def _rect(r):
    return [_r(v) for v in r]


def walkdata(files):
    from modules import walk as W  # lift points (prefers LIFT_STOP empties)
    floors = []
    for n in range(1, C.NUM_FLOORS + 1):
        pl = C.plate(n)
        lift = W.lift_stop_xy(n)
        stair_ob = bpy.data.objects.get("STAIR_DOOR_F%02d" % n)
        floors.append({
            "n": n,
            "z": _r(C.floor_z(n)),
            "height": _r(C.floor_height(n)),
            "slab": _poly(pl),
            "plate": _poly(C.inset(pl, 0.6)),
            "core": _rect(C.core_rect(n)),
            "stair": _rect(C.stair_rect(n)),
            "elevator": _rect(C.elevator_rect(n)),
            "lift": [_r(lift[0]), _r(lift[1])],
            "lift_from_empty": bpy.data.objects.get("LIFT_STOP_F%02d" % n) is not None,
            "stair_door": ([_r(stair_ob.matrix_world.translation.x), _r(stair_ob.matrix_world.translation.y)]
                           if stair_ob else None),
            "use": ("lobby" if n == 1 else "moma" if n in C.MOMA_FLOORS else
                    "pool" if n == 6 else "amenity" if n == 7 else
                    "penthouse" if n == C.PENTHOUSE_FLOOR else "residential"),
        })
    return {
        "name": "53 West 53",
        "units": "metres",
        "axes": ("Plan data (x, y) and z are Blender coordinates: +x east along W 53rd St, "
                 "+y north, +z up; street wall y=0, curb y=-6. glTF/three.js is Y-up: "
                 "Blender (x, y, z) -> three (x, z, -y). So a plan point (x, y) at "
                 "elevation z is three.Vector3(x, z, -y)."),
        "num_floors": C.NUM_FLOORS,
        "height": C.HEIGHT,
        "roof_z": _r(C.roof_z()),
        "eye_height": 1.65,
        "footprint": _poly(C.FOOTPRINT),
        "entrance": {"x": C.ENTRANCE[0], "y": C.ENTRANCE[1], "z": 0.0,
                     "opening_x": [19.4, 22.6], "width": 3.2},
        "spawn": {"x": C.ENTRANCE[0], "y": -4.0, "z": 0.0, "heading_deg": 0,
                  "note": "on the 53rd St sidewalk facing north at the entrance"},
        "site": {"sidewalk": {"y": [-6, 0], "z": 0.0}, "roadway": {"y": [-16, -6], "z": -0.15},
                 "south_sidewalk": {"y": [-22, -16], "z": 0.0}},
        "stops": [
            {"label": "Lobby", "floor": 1}, {"label": "MoMA gallery", "floor": 2},
            {"label": "MoMA gallery", "floor": 4}, {"label": "MoMA gallery", "floor": 5},
            {"label": "Pool", "floor": 6}, {"label": "Amenity", "floor": 7},
            {"label": "Penthouse", "floor": C.PENTHOUSE_FLOOR},
        ],
        "files": files,
        "floors": floors,
    }


# ----------------------------------------------------------------- export
def export_glb(ctx):
    out = ctx["out"]
    obs = _exportable()
    _tag(obs)
    every = [ob for ob, _g in obs]
    main = os.path.join(out, "53W53.glb")
    for old in os.listdir(out):
        if old.startswith("53W53_floors_") and old.endswith(".glb"):
            os.remove(os.path.join(out, old))

    files = [{"file": "53W53.glb", "floors": "all"}]
    lean = False
    size = _export(main, every, lean=False)
    print("[export] full:", _mb(size))
    if size > BUDGET:
        lean = True
        size = _export(main, every, lean=True)
        print("[export] lean (no normals/UVs):", _mb(size))
    if size > BUDGET:
        files = _split(out, obs)
    else:
        files[0].update(bytes=size, lean=lean)

    data = walkdata(files)
    jpath = os.path.join(out, "walkdata.json")
    with open(jpath, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    _copy_to_web(out, [f["file"] for f in files] + ["walkdata.json"])
    for f in files:
        print("[export] %s %s" % (f["file"], _mb(os.path.getsize(os.path.join(out, f["file"])))))
    print("[export] walkdata.json", os.path.getsize(jpath) // 1024, "KB")
    make_artifact_bundle(out, files, data)
    return files


def glb_to_gltf_json(glb_path):
    """Convert a GLB to a self-contained glTF JSON (buffer as base64 data URI).

    Web hosts that refuse .glb can still serve this as .json; three.js'
    GLTFLoader parses either form, whatever the file extension.
    """
    import base64
    import struct
    with open(glb_path, "rb") as fh:
        raw = fh.read()
    magic, _ver, _length = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67, "not a GLB"
    off, doc, binchunk = 12, None, b""
    while off < len(raw):
        clen, ctype = struct.unpack_from("<II", raw, off)
        chunk = raw[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            binchunk = chunk
        off += 8 + clen
    if doc.get("buffers"):
        doc["buffers"][0]["uri"] = ("data:application/octet-stream;base64,"
                                    + base64.b64encode(binchunk).decode("ascii"))
    return doc


def make_artifact_bundle(out, files, data):
    """out/artifact/: index.html + walkdata.json + models as .json, ready to
    publish where only web-safe file types are served."""
    dest = os.path.join(out, "artifact")
    os.makedirs(dest, exist_ok=True)
    for old in os.listdir(dest):
        os.remove(os.path.join(dest, old))
    bundle = json.loads(json.dumps(data))
    for f in bundle.get("files", []):
        name = f["file"][:-4] + "_model.json"
        doc = glb_to_gltf_json(os.path.join(out, f["file"]))
        with open(os.path.join(dest, name), "w") as fh:
            json.dump(doc, fh, separators=(",", ":"))
        f["file"] = name
        f["bytes"] = os.path.getsize(os.path.join(dest, name))
    with open(os.path.join(dest, "walkdata.json"), "w") as fh:
        json.dump(bundle, fh, separators=(",", ":"))
    if os.path.isfile(os.path.join(WEB, "index.html")):
        shutil.copy2(os.path.join(WEB, "index.html"), os.path.join(dest, "index.html"))
    print("[export] artifact bundle:", ", ".join(
        "%s %s" % (n, _mb(os.path.getsize(os.path.join(dest, n)))) for n in sorted(os.listdir(dest))))


def _split(out, obs):
    """Main file = exterior + site + key floors; the rest of the interiors in
    floor-range chunks sized to fit the budget."""
    def floor_of(ob):
        try:
            return int(ob.get("floor", -1))
        except (TypeError, ValueError):
            return -1

    interior = {}
    main_obs = []
    for ob, g in obs:
        f = floor_of(ob)
        if g == "Interiors" and f >= 1 and f not in KEY_FLOORS:
            interior.setdefault(f, []).append(ob)
        else:
            main_obs.append(ob)
    main = os.path.join(out, "53W53.glb")
    size = _export(main, main_obs, lean=True)
    files = [{"file": "53W53.glb", "floors": list(KEY_FLOORS), "bytes": size, "lean": True}]
    print("[export] split main:", _mb(size))
    if size > BUDGET:
        print("[export] WARNING: main file still over budget (%s)" % _mb(size))
    floors = sorted(interior)
    # estimate per-floor cost from a sample chunk, then pack greedily
    i = 0
    chunk = 12
    while i < len(floors):
        while True:
            sel = floors[i:i + chunk]
            name = "53W53_floors_%02d-%02d.glb" % (sel[0], sel[-1])
            path = os.path.join(out, name)
            size = _export(path, [o for f in sel for o in interior[f]], lean=True)
            if size <= BUDGET or chunk == 1:
                break
            os.remove(path)
            chunk = max(1, chunk // 2)
        files.append({"file": name, "floors": sel, "bytes": size, "lean": True})
        print("[export] chunk", name, _mb(size))
        i += len(sel)
    return files


def _copy_to_web(out, names):
    if not os.path.isdir(WEB):
        return
    for old in os.listdir(WEB):
        if old.startswith("53W53") and old.endswith(".glb"):
            os.remove(os.path.join(WEB, old))
    for n in names:
        shutil.copy2(os.path.join(out, n), os.path.join(WEB, n))
