"""Automatic interior camera placement for hero renders.

Interior layouts change while the model evolves, so fixed cameras end up
facing walls. best_interior_cam(floor, goal) samples eye-height positions
on the floor plate and headings, casts a fan of rays (scene.ray_cast) and
scores each view:
  goal "view"  : looks out of the curtain wall across a deep room
  goal "water" : sees the pool water (pool floor)
  goal "deep"  : longest unobstructed view (lobby)
Returns (location, rotation_euler, lens).
"""
import math
import bpy
import mathutils

import config as C


def _mat_name(ob, face_index):
    try:
        me = ob.data
        mi = me.polygons[face_index].material_index
        m = me.materials[mi] if mi < len(me.materials) else None
        return m.name if m else ""
    except Exception:
        return ""


def _cast(scene, dg, origin, d, maxd=120.0, through_glass=1):
    """Ray -> (distance, material name of first non-thin-glass hit, saw_glass)."""
    o = mathutils.Vector(origin)
    total = 0.0
    saw_glass = False
    for _ in range(through_glass + 1):
        hit, loc, nrm, idx, ob, _m = scene.ray_cast(dg, o, d, distance=maxd - total)
        if not hit:
            return maxd, "", saw_glass
        dist = (loc - o).length
        total += dist
        name = _mat_name(ob, idx)
        if name.startswith("Glass_Curtain"):
            saw_glass = True
            o = loc + d * 0.02
            continue
        return total, name, saw_glass
    return total, "", saw_glass


def _inside(poly, x, y):
    n = len(poly)
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < 0:
            return False
    return True


def best_interior_cam(floor, goal="view", eye=1.6, lens=18.0, step=1.5, headings=16, prefer=None):
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    z0 = C.floor_z(floor)
    zc = z0 + eye
    plate = C.inset(C.plate(floor), 1.2)
    if len(plate) < 3:
        plate = C.plate(floor)
    xs = [p[0] for p in plate]
    ys = [p[1] for p in plate]
    core = C.core_rect(floor)
    hfov = 2 * math.atan(18.0 / lens)
    pts = []
    x = min(xs)
    while x <= max(xs):
        y = min(ys)
        while y <= max(ys):
            if _inside(plate, x, y) and not (core[0] - 0.6 < x < core[2] + 0.6 and core[1] - 0.6 < y < core[3] + 0.6):
                p = mathutils.Vector((x, y, zc))
                # must stand on this floor, under its ceiling, not inside furniture
                dn, _, _ = _cast(scene, dg, p, mathutils.Vector((0, 0, -1)), 3.0, 0)
                up, _, _ = _cast(scene, dg, p, mathutils.Vector((0, 0, 1)), 12.0, 0)
                if 1.2 < dn < eye + 0.25 and up > 0.8:
                    ds = [_cast(scene, dg, p, mathutils.Vector((math.cos(a), math.sin(a), 0)), 20.0, 0)[0]
                          for a in [i * math.pi / 4 for i in range(8)]]
                    if min(ds) > 0.7:
                        pts.append((sum(ds), p))
            y += step
        x += step
    # phase 2: full view scoring only for the most open positions
    pts.sort(key=lambda t: -t[0])
    best = None
    for _, p in pts[:30]:
        for h in range(headings):
            yaw = h * 2 * math.pi / headings
            sc = _score(scene, dg, p, yaw, hfov, goal, prefer)
            if best is None or sc > best[0]:
                best = (sc, p.copy(), yaw)
    if best is None:
        return None
    s, p, yaw = best
    pitch = {"view": -4.0, "water": -12.0, "deep": 2.0}.get(goal, 0.0)
    d = mathutils.Vector((math.cos(yaw), math.sin(yaw), math.tan(math.radians(pitch))))
    rot = d.to_track_quat("-Z", "Y").to_euler()
    print(f"[cams] F{floor:02d} {goal}: score {s:.2f} at ({p.x:.1f}, {p.y:.1f}) yaw {math.degrees(yaw):.0f}")
    return p, rot, lens


def _score(scene, dg, p, yaw, hfov, goal, prefer):
    n_h, pitches = 9, (-14.0, -4.0, 6.0)
    dsum = glass = water = near = 0.0
    gdist, gn = 0.0, 0
    n = 0
    for i in range(n_h):
        a = yaw + (i / (n_h - 1) - 0.5) * hfov * 0.9
        for pt in pitches:
            pr = math.radians(pt)
            d = mathutils.Vector((math.cos(a) * math.cos(pr), math.sin(a) * math.cos(pr), math.sin(pr)))
            dist, name, sg = _cast(scene, dg, p, d)
            if sg:
                gd = _cast(scene, dg, p, d, 60.0, 0)[0]
                gdist += gd
                gn += 1
            n += 1
            inner = dist
            dsum += min(dist, 30.0)
            glass += sg
            water += name.startswith(("Water", "Pool"))
            near += inner < 2.0
    depth = dsum / n / 30.0
    gf, wf, nf = glass / n, water / n, near / n
    if goal == "view":
        # windows in frame, but stand back in the room (glass >= ~5 m away)
        s = 1.0 * min(gf, 0.5) + 0.8 * depth - 1.5 * nf + 0.6 * min(gdist / gn, 9.0) / 9.0 if gn else -1.0
    elif goal == "water":
        s = 1.5 * min(wf, 0.35) + 0.4 * min(gf, 0.5) + 0.6 * depth - 1.5 * nf
    else:
        s = depth - 1.5 * nf + 0.2 * min(gf, 0.3)
    if prefer is not None:  # preferred heading (radians): gentle bias
        s += 0.15 * math.cos(yaw - prefer)
    return s
