"""Architectural detail generators shared by the showcase floors.

  panel_wall     cerused-oak raised panels with bronze reveals, rail, skirting
  coffers        real coffered ceiling: beams, bronze inlays, moulded cells,
                 recessed downlights; returns the cell centres
  cove_ceiling   perimeter soffit with an LED cove (apartments)
  casings        white-cased slanted diagrid columns inside the glass, from
                 ctx["diagrid_members"] (exterior agent); skipped if absent
  green_wall     Patrick Blanc style planted wall (thousands of leaves)
"""
import math
import random

import config as C
from modules import interiors_geom as G
from modules import interiors_prims as P

NOIR, STAT, OAKC, BRZ = "Marble_Noir_StLaurent", "Marble_Statuary", "Oak_Cerused", "Bronze_Trim"


# ------------------------------------------------------------------ helpers
def map_wall(vf, p0, u, n):
    """Map local (s along u, t along n, z) to world; keeps outward winding."""
    verts, faces = vf
    out = [(p0[0] + u[0] * s + n[0] * t, p0[1] + u[1] * s + n[1] * t, z) for s, t, z in verts]
    if u[0] * n[1] - u[1] * n[0] < 0:
        faces = [tuple(reversed(f)) for f in faces]
    return out, faces


def span(poly, axis, val, half=0.0):
    """Range of the other coordinate along the line coord[axis] = val that is
    inside poly for the whole strip val +- half. None if empty."""
    lo, hi = -1e9, 1e9
    for v in (val - half, val + half):
        if axis == 0:
            pc = G.clip_rect(poly, v - 1e-3, -1e4, v + 1e-3, 1e4)
            k = 1
        else:
            pc = G.clip_rect(poly, -1e4, v - 1e-3, 1e4, v + 1e-3)
            k = 0
        if not pc:
            return None
        lo = max(lo, min(p[k] for p in pc))
        hi = min(hi, max(p[k] for p in pc))
    return (lo, hi) if hi - lo > 0.05 else None


def cut_intervals(a, b, cuts):
    """[a, b] minus the list of (c0, c1) intervals."""
    out = [(a, b)]
    for c0, c1 in cuts:
        nxt = []
        for x0, x1 in out:
            if c1 <= x0 or c0 >= x1:
                nxt.append((x0, x1))
                continue
            if c0 > x0:
                nxt.append((x0, c0))
            if c1 < x1:
                nxt.append((c1, x1))
        out = nxt
    return [(x0, x1) for x0, x1 in out if x1 - x0 > 0.05]


# ------------------------------------------------------------------ panelling
def panel_wall(mm, p0, p1, nrm, z0, z1, openings=(), module=1.25, rail_z=3.4, panel=OAKC, trim=BRZ,
               base=NOIR, fields=True, frame_openings=True):
    """Raised cerused-oak panels on the wall face p0->p1 (2D), facing nrm.
    openings: (s0, s1, ztop) along the wall from p0 (doors, lift portals)."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 0.2:
        return
    u = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)

    def add(mat, vf):
        mm.mesh(mat, *map_wall(vf, p0, u, nrm))

    g = 0.012
    ops = sorted((max(0.0, a), min(L, b), t) for a, b, t in openings)
    solid = cut_intervals(0.0, L, [(a, b) for a, b, _ in ops])
    zb0 = z0 + (0.16 if base else 0.0)
    regs = [(zb0, rail_z)] + ([(rail_z + 0.08, z1)] if z1 - rail_z > 0.6 else [])
    if z1 - rail_z <= 0.6 or rail_z <= zb0 + 0.3:
        regs = [(zb0, z1)]
    # bronze backing visible in the reveals (one quad per run)
    for a, b in solid:
        add(trim, ([(a, 0.006, z0 + 0.15), (b, 0.006, z0 + 0.15), (b, 0.006, z1), (a, 0.006, z1)], [(0, 1, 2, 3)]))
        if base:
            add(base, P.cbox(a, 0.0, z0, b, 0.035, z0 + 0.16, 0.006))
        if len(regs) > 1:
            add(trim, P.cbox(a, 0.0, rail_z, b, 0.05, rail_z + 0.08, 0.008))
        for za, zb in regs:
            _panels(add, a, b, za, zb, module, g, panel, fields and zb - za < 4.0)
    for a, b, top in ops:
        if top < z1 - 0.3:
            zb = z1
            za = top + 0.12
            if len(regs) > 1 and top < rail_z:
                add(trim, P.cbox(a, 0.0, rail_z, b, 0.05, rail_z + 0.08, 0.008))
                _panels(add, a, b, za, rail_z, module, g, panel, fields)
                za = rail_z + 0.08
            add(trim, ([(a, 0.006, top), (b, 0.006, top), (b, 0.006, z1), (a, 0.006, z1)], [(0, 1, 2, 3)]))
            _panels(add, a, b, za, zb, module, g, panel, False)
        if frame_openings:                         # bronze architrave
            fw = 0.09
            add(trim, P.cbox(a - fw, 0.0, z0, a, 0.07, top + fw, 0.01))
            add(trim, P.cbox(b, 0.0, z0, b + fw, 0.07, top + fw, 0.01))
            add(trim, P.cbox(a, 0.0, top, b, 0.07, top + fw, 0.01))


def _panels(add, a, b, za, zb, module, g, mat, fields):
    if zb - za < 0.1:
        return
    n = max(1, int(round((b - a) / module)))
    pw = (b - a) / n
    for i in range(n):
        s0, s1 = a + i * pw + g / 2, a + (i + 1) * pw - g / 2
        add(mat, P.cbox(s0, 0.0, za + g / 2, s1, 0.04, zb - g / 2, 0.01))
        if fields and s1 - s0 > 0.4 and zb - za > 0.6:
            add(mat, P.cbox(s0 + 0.11, 0.035, za + 0.12, s1 - 0.11, 0.052, zb - 0.12, 0.012))


# ------------------------------------------------------------------ coffers
def coffers(fc, poly, exclude, zc, xs, ys, bw=0.36, bd=0.5, step=1, downlights=True, beam_mat="Wall_White",
            inlay=BRZ, ceil_mat="Wall_White", sink="ceiling"):
    """Coffered ceiling under zc over convex `poly` minus `exclude` rects."""
    mm = fc.sink(sink)
    lit = fc.sink("lights")
    for pc in G.poly_minus_rects(poly, exclude):
        mm.hface(ceil_mat, pc, zc - 0.002, up=False)
    zb = zc - bd

    def beams(axis, lines):
        for X in lines:
            sp = span(poly, axis, X, bw / 2)
            if not sp:
                continue
            cuts = []
            for r in exclude:
                lo, hi = (r[0], r[2]) if axis == 0 else (r[1], r[3])
                if lo - bw / 2 < X < hi + bw / 2:
                    cuts.append((r[1], r[3]) if axis == 0 else (r[0], r[2]))
            for a, b in cut_intervals(sp[0], sp[1], cuts):
                if axis == 0:
                    mm.mesh(beam_mat, *P.cbox(X - bw / 2, a, zb, X + bw / 2, b, zc, 0.02))
                    if inlay:
                        mm.mesh(inlay, *P.box(X - 0.035, a + 0.05, zb - 0.006, X + 0.035, b - 0.05, zb + 0.001))
                else:
                    mm.mesh(beam_mat, *P.cbox(a, X - bw / 2, zb, b, X + bw / 2, zc - 0.001, 0.02))
                    if inlay:
                        mm.mesh(inlay, *P.box(a + 0.05, X - 0.035, zb - 0.006, b - 0.05, X + 0.035, zb + 0.001))

    beams(0, xs)
    beams(1, ys)
    cells = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            x0, x1 = xs[i] + bw / 2, xs[i + 1] - bw / 2
            y0, y1 = ys[j] + bw / 2, ys[j + 1] - bw / 2
            r = (x0, y0, x1, y1)
            if not G.rect_inside(poly, r, 0.0) or any(G.rects_overlap(r, e, 0.0) for e in exclude):
                continue
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            cells.append((cx, cy, x1 - x0, y1 - y0))
            if step:
                # stepped inner moulding (cyma-like two steps)
                for k, (ins, dep) in enumerate(((0.0, min(0.16, bd * 0.4)), (0.12, min(0.08, bd * 0.2)))[:step]):
                    a0, b0, a1, b1 = x0 + ins, y0 + ins, x1 - ins, y1 - ins
                    w = 0.12
                    for q in ((a0, b0, a1, b0 + w), (a0, b1 - w, a1, b1), (a0, b0 + w, a0 + w, b1 - w),
                              (a1 - w, b0 + w, a1, b1 - w)):
                        mm.mesh(beam_mat, *P.cbox(q[0], q[1], zc - dep, q[2], q[3], zc - 0.001, 0.01))
                if inlay:
                    a0, b0, a1, b1 = x0 + 0.24, y0 + 0.24, x1 - 0.24, y1 - 0.24
                    mm.mesh(inlay, *P.box(a0, b0, zc - 0.085, a1, b0 + 0.02, zc - 0.075))
                    mm.mesh(inlay, *P.box(a0, b1 - 0.02, zc - 0.085, a1, b1, zc - 0.075))
                    mm.mesh(inlay, *P.box(a0, b0, zc - 0.085, a0 + 0.02, b1, zc - 0.075))
                    mm.mesh(inlay, *P.box(a1 - 0.02, b0, zc - 0.085, a1, b1, zc - 0.075))
            if downlights:
                fc.sink("trim").mesh(BRZ, *P.lathe([(0.11, zc - 0.012), (0.075, zc - 0.006), (0.075, zc)], 12, cx, cy,
                                                   cap0=False, cap1=False))
                lit.mesh("Light_Downlight", *P.disc(cx, cy, zc - 0.008, 0.075, 12, up=False))
    return cells


# ------------------------------------------------------------------ cove ceiling
def cove_ceiling(fc, poly, band=0.9, drop=0.28, downlights=True, spacing=1.6):
    """Perimeter soffit (band wide, drop deep) with an LED cove on its inner
    edge washing the recessed central ceiling (cf. apartment renderings)."""
    inner = C.inset(poly, band)
    if len(inner) < 3 or len(inner) != len(poly):
        return
    zc = fc.zc
    zb = zc - drop
    mm = fc.sink("ceiling")
    lit = fc.sink("lights")
    n = len(poly)
    # match each outer vertex with the nearest inner vertex
    match = []
    for p in poly:
        match.append(min(range(n), key=lambda k: (inner[k][0] - p[0]) ** 2 + (inner[k][1] - p[1]) ** 2))
    if sorted(match) != list(range(n)):
        return
    back = C.inset(poly, band - 0.22)
    if len(back) != n:
        return
    bm = [min(range(n), key=lambda k: (back[k][0] - p[0]) ** 2 + (back[k][1] - p[1]) ** 2) for p in poly]
    for i in range(n):
        j = (i + 1) % n
        o0, o1 = poly[i], poly[j]
        i0, i1 = inner[match[i]], inner[match[j]]
        b0, b1 = back[bm[i]], back[bm[j]]
        mm.face("Wall_White", [(o0[0], o0[1], zb), (i0[0], i0[1], zb), (i1[0], i1[1], zb), (o1[0], o1[1], zb)])
        # inner lip (faces the room centre)
        mm.face("Wall_White", [(i0[0], i0[1], zb), (i0[0], i0[1], zb + 0.12), (i1[0], i1[1], zb + 0.12),
                               (i1[0], i1[1], zb)])
        # trough floor with the LED strip, back face up to the ceiling
        mm.face("Wall_White", [(i0[0], i0[1], zb + 0.03), (b0[0], b0[1], zb + 0.03), (b1[0], b1[1], zb + 0.03),
                               (i1[0], i1[1], zb + 0.03)][::-1])
        mid0 = ((i0[0] * 0.6 + b0[0] * 0.4), (i0[1] * 0.6 + b0[1] * 0.4))
        mid1 = ((i1[0] * 0.6 + b1[0] * 0.4), (i1[1] * 0.6 + b1[1] * 0.4))
        m0 = ((i0[0] * 0.4 + b0[0] * 0.6), (i0[1] * 0.4 + b0[1] * 0.6))
        m1 = ((i1[0] * 0.4 + b1[0] * 0.6), (i1[1] * 0.4 + b1[1] * 0.6))
        lit.face("Light_Cove", [(mid0[0], mid0[1], zb + 0.035), (m0[0], m0[1], zb + 0.035),
                                (m1[0], m1[1], zb + 0.035), (mid1[0], mid1[1], zb + 0.035)][::-1])
        mm.face("Wall_White", [(b1[0], b1[1], zb + 0.03), (b1[0], b1[1], zc), (b0[0], b0[1], zc),
                               (b0[0], b0[1], zb + 0.03)])
        if downlights:
            L = math.hypot(o1[0] - o0[0], o1[1] - o0[1])
            k = int(L / spacing)
            for q in range(1, k):
                t = q / k
                ox, oy = o0[0] + (o1[0] - o0[0]) * t, o0[1] + (o1[1] - o0[1]) * t
                ix, iy = i0[0] + (i1[0] - i0[0]) * t, i0[1] + (i1[1] - i0[1]) * t
                cx, cy = ox * 0.45 + ix * 0.55, oy * 0.45 + iy * 0.55
                if G.contains(fc.inner, cx, cy, -0.4):
                    lit.mesh("Light_Downlight", *P.disc(cx, cy, zb - 0.002, 0.04, 10, up=False))


# ------------------------------------------------------------------ diagrid casings
def prep_members(members):
    out = []
    for m in members or []:
        try:
            p0, p1 = tuple(m["p0"]), tuple(m["p1"])
            N = tuple(m.get("facet_normal", (0, 0, 0)))
        except (KeyError, TypeError):
            continue
        if p0[2] > p1[2]:
            p0, p1 = p1, p0
        d = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        L = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
        if L < 0.5 or d[2] < 0.45 * L:          # skip belts / near-horizontal bars
            continue
        nl = math.sqrt(N[0] ** 2 + N[1] ** 2 + N[2] ** 2)
        if nl < 1e-6:
            continue
        N = (N[0] / nl, N[1] / nl, N[2] / nl)
        ridge = m.get("kind") == "ridge"
        w = 0.9 if ridge else max(0.6, min(0.9, float(m.get("width", 1.0)) * 0.72))
        dep = 0.55 if ridge else 0.42
        off = (0.62 if ridge else 0.58) + 0.03 + dep / 2
        ax = (d[0] / L, d[1] / L, d[2] / L)
        n = P._norm(P._sub(N, tuple(ax[k] * P._dot(N, ax) for k in range(3))))
        side = P._norm(P._cross(ax, n))
        c0 = tuple(p0[k] - N[k] * off for k in range(3))
        c1 = tuple(p1[k] - N[k] * off for k in range(3))
        out.append(dict(c0=c0, c1=c1, n=n, side=side, w=w, d=dep, z0=c0[2] - 1.0, z1=c1[2] + 1.0, ridge=ridge))
    return out


def casings(fc, members, chamfer=0.035, mat="Wall_White", skip=None):
    """White-cased slanted columns where the diagrid crosses this floor."""
    z0, z1 = fc.Fz, fc.zc
    mm = fc.sink("casing")
    poly = fc.slab_poly
    core = C.core_rect(fc.n)
    count = 0
    for m in members:
        if m["z1"] < z0 + 0.3 or m["z0"] > z1 - 0.3:
            continue
        w, d = m["w"], m["d"]
        if chamfer:
            c = chamfer
            sec = [(w / 2 - c, d / 2), (-w / 2 + c, d / 2), (-w / 2, d / 2 - c), (-w / 2, -d / 2 + c),
                   (-w / 2 + c, -d / 2), (w / 2 - c, -d / 2), (w / 2, -d / 2 + c), (w / 2, d / 2 - c)]
        else:
            sec = [(w / 2, d / 2), (-w / 2, d / 2), (-w / 2, -d / 2), (w / 2, -d / 2)]
        c0, c1 = m["c0"], m["c1"]
        dz = c1[2] - c0[2]
        bot, top = [], []
        ok = True
        for a, b in sec:
            o = tuple(m["side"][k] * a + m["n"][k] * b for k in range(3))
            pa = tuple(c0[k] + o[k] for k in range(3))
            pb = tuple(c1[k] + o[k] for k in range(3))
            ta = (z0 - pa[2]) / dz
            tb = (z1 - pa[2]) / dz
            ta, tb = max(0.0, ta), min(1.0, tb)
            if tb - ta < 1e-3:
                ok = False
                break
            bot.append(tuple(pa[k] + (pb[k] - pa[k]) * ta for k in range(3)))
            top.append(tuple(pa[k] + (pb[k] - pa[k]) * tb for k in range(3)))
        if not ok:
            continue
        if max(p[2] for p in top) - min(p[2] for p in bot) < 0.6:
            continue
        mx = sum(p[0] for p in bot + top) / (2 * len(sec))
        my = sum(p[1] for p in bot + top) / (2 * len(sec))
        if not G.contains(poly, mx, my, 0.05):
            continue
        if core[0] - 0.3 < mx < core[2] + 0.3 and core[1] - 0.3 < my < core[3] + 0.3:
            continue
        if skip and any(r[0] < mx < r[2] and r[1] < my < r[3] for r in skip):
            continue
        k = len(sec)
        verts = bot + top
        faces = [tuple(reversed(range(k))), tuple(range(k, 2 * k))]
        for i in range(k):
            j = (i + 1) % k
            faces.append((i, j, k + j, k + i))
        cen = (mx, my, sum(p[2] for p in verts) / len(verts))
        mm.mesh(mat, verts, P.orient(verts, faces, cen))
        # keep furniture away from the column
        for t in (0.0, 0.5, 1.0):
            px = bot[0][0] + (top[0][0] - bot[0][0]) * t
            py = bot[0][1] + (top[0][1] - bot[0][1]) * t
            fc.block((px - w / 2 - 0.1, py - w / 2 - 0.1, px + w / 2 + 0.1, py + w / 2 + 0.1))
        count += 1
    return count


# ------------------------------------------------------------------ vertical garden
LEAF_MATS = ("Green_Wall", "Foliage", "Foliage_Light", "Green_Wall", "Foliage", "Foliage_Dark",
             "Foliage_Yellow", "Foliage_Red")


def green_wall(fc, p0, p1, z0, z1, nrm, density=70.0, seed=7, sink="plants"):
    """Planted wall on the face p0->p1 facing nrm (2D)."""
    rng = random.Random(seed)
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    u = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
    mm = fc.sink(sink)
    mm.mesh("Soil", *map_wall(P.box(0.0, 0.0, z0, L, 0.06, z1, False), p0, u, nrm))
    # bronze frame around the garden
    fr = fc.sink("trim")
    for vf in (P.cbox(-0.08, 0.0, z0, 0.0, 0.3, z1, 0.01), P.cbox(L, 0.0, z0, L + 0.08, 0.3, z1, 0.01),
               P.cbox(-0.08, 0.0, z0, L + 0.08, 0.32, z0 + 0.25, 0.01)):
        fr.mesh(BRZ, *map_wall(vf, p0, u, nrm))
    n = int(L * (z1 - z0 - 0.25) * density)
    # patches: Blanc's walls are drifts of species -> mats chosen by region
    patches = [(rng.uniform(0, L), rng.uniform(z0, z1), rng.uniform(0.6, 2.2), rng.choice(LEAF_MATS))
               for _ in range(int(L * (z1 - z0) / 2.5) + 3)]
    for i in range(n):
        s = rng.uniform(0.05, L - 0.05)
        z = rng.uniform(z0 + 0.3, z1 - 0.05)
        best = min(patches, key=lambda p: ((p[0] - s) ** 2 + (p[1] - z) ** 2) / p[2])
        mat = best[3] if rng.random() < 0.8 else rng.choice(LEAF_MATS)
        t = rng.uniform(0.05, 0.2)
        a = rng.uniform(-math.pi, math.pi)
        out = rng.uniform(0.3, 1.0)
        dl = (math.cos(a) * 0.8, out, math.sin(a) * 0.9 - 0.25)
        size = rng.uniform(0.16, 0.38) * (1.4 if mat in ("Foliage_Dark", "Green_Wall") else 1.0)
        base = (s, t, z)
        vf = P.leaf(base, dl, size, size * rng.uniform(0.35, 0.6), rng.uniform(0.1, 0.5), rng.uniform(-0.8, 0.8))
        mm.mesh(mat, *map_wall(vf, p0, u, nrm))
