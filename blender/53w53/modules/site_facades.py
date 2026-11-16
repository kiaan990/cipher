"""Real-geometry facades for the Midtown context buildings.

Replaces the old 'flat dark rectangles' look: the building body carries the
window glass, and piers, spandrels, cornices, sills, storefront piers, sign
fascias and awnings are modelled as shallow relief boxes in front of it, so
every window is a genuinely recessed opening with reveals that catch light
and cast shadows.  Cost is kept low (relief elements run the full height or
width of a facade instead of being modelled per window).

Level of detail (`detail`):
  0  plain prism (far context)
  1  relief piers + spandrels on every face, storefronts on street faces
  2  + window frames (mullion + transom per bay), sills, cornice, awnings
"""
import math
import random

import config as C

PIER_D = 0.24        # pier projection in front of the window glass
BAND_D = 0.17        # spandrel projection
CORNICE_D = 0.55


def _edges(poly):
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        ux, uy = dx / L, dy / L
        yield i, a, (ux, uy), (uy, -ux), L


class Face:
    """One planar wall: point(s, off, z) = a + u*s + n*off + z."""

    def __init__(self, kit, a, u, n, L):
        self.kit, self.a, self.u, self.n, self.L = kit, a, u, n, L

    def P(self, s, off, z):
        return (self.a[0] + self.u[0] * s + self.n[0] * off,
                self.a[1] + self.u[1] * s + self.n[1] * off, z)

    def quad(self, mat, s0, s1, z0, z1, off=0.0, group="Bldg", collide=False):
        P = self.P
        self.kit.quad(mat, P(s0, off, z0), P(s1, off, z0), P(s1, off, z1), P(s0, off, z1),
                      group, collide)

    def relief(self, mat, s0, s1, z0, z1, d, off0=0.0, top=True, bottom=True, sides=True):
        """Box projecting from off0 to off0+d in front of the wall (no back)."""
        s0, s1 = max(0.0, s0), min(self.L, s1)
        if s1 - s0 < 1e-3 or z1 - z0 < 1e-3:
            return
        P, q = self.P, self.kit.quad
        o1 = off0 + d
        q(mat, P(s0, o1, z0), P(s1, o1, z0), P(s1, o1, z1), P(s0, o1, z1))
        if sides:
            q(mat, P(s0, off0, z0), P(s0, o1, z0), P(s0, o1, z1), P(s0, off0, z1))
            q(mat, P(s1, o1, z0), P(s1, off0, z0), P(s1, off0, z1), P(s1, o1, z1))
        if top:
            q(mat, P(s0, off0, z1), P(s0, o1, z1), P(s1, o1, z1), P(s1, off0, z1))
        if bottom:
            q(mat, P(s1, off0, z0), P(s1, o1, z0), P(s0, o1, z0), P(s0, off0, z0))


def _roof(kit, poly, z, mat):
    kit.ngon(mat, [(x, y, z) for x, y in poly], group="Bldg", collide=False)


def _bays(L, pitch, margin=0.0):
    """Pier centre positions along a face of length L, symmetric."""
    cnt = max(1, int((L - 2 * margin) / pitch))
    s0 = (L - cnt * pitch) / 2
    return [s0 + k * pitch for k in range(cnt + 1)]


def _seed(poly):
    return int(abs(sum(p[0] * 13.1 + p[1] * 7.7 for p in poly)) * 10) & 0xFFFFFF


# ----------------------------------------------------------------- masonry
def _punched_tier(kit, rng, poly, z0, z1, wall, glass, floor_h, ground_h, detail,
                  pier_pitch, pier_w, street, store, frame, base_tier, top_tier, blind=()):
    """One tier of a masonry building between z0 and z1."""
    win_lo = ground_h if base_tier else z0
    awning_mat = rng.choice(("Awning_Green", "Awning_Black", "Awning_Burgundy", "Awning_Black"))
    for i, a, u, n, L in _edges(poly):
        f = Face(kit, a, u, n, L)
        if i in blind:      # party wall / wall facing the tower: flush, no relief
            f.quad(wall, 0, L, 0.0 if base_tier else z0, z1, collide=True)
            continue
        is_street = street is None or i in street
        if base_tier and not is_street:
            # lot-line (party) wall: blank masonry, as on real Midtown lots
            f.quad(wall, 0, L, 0.0, z1, collide=True)
            if detail >= 2 and top_tier and L > 4.0:
                f.relief(wall, 0.0, L, z1 - 0.5, z1, 0.12, sides=False)   # coping
            continue
        # body: glass behind the relief grid, solid wall for the storefront zone
        if base_tier:
            if is_street and store:
                f.quad("Storefront", 0, L, 0.0, ground_h, collide=True)
            else:
                f.quad(wall, 0, L, 0.0, ground_h, collide=True)
        if L < 4.0 or detail <= 0:
            f.quad(wall, 0, L, win_lo, z1, collide=True)
            continue
        f.quad(glass, 0, L, win_lo, z1, collide=True)
        top = z1 - (1.1 if top_tier else 0.0)
        # piers (full height of the window zone)
        pitch = pier_pitch if L > 2 * pier_pitch else L / 2
        centres = _bays(L, pitch)
        for c in centres:
            w = pier_w * (1.6 if c in (centres[0], centres[-1]) else 1.0)
            f.relief(wall, c - w / 2, c + w / 2, win_lo, z1, PIER_D, top=False, bottom=False)
        # corner returns so bands/piers never show open ends at the corners
        f.relief(wall, 0.0, pier_w * 0.6, win_lo, z1, PIER_D + 0.02, top=False, bottom=False)
        f.relief(wall, L - pier_w * 0.6, L, win_lo, z1, PIER_D + 0.02, top=False, bottom=False)
        # spandrels: window from zf+0.85 (sill) to zf+floor_h-0.45 (head)
        zf = win_lo
        first = True
        while zf < top - 0.5:
            head = min(top, zf + floor_h - 0.45)
            sill = zf + 0.85
            lo = zf if first else zf - 0.45
            if sill > lo:
                f.relief(wall, 0.0, L, lo, sill, BAND_D, sides=True)
                if detail >= 2:   # projecting stone sill
                    f.relief(wall, 0.0, L, sill - 0.08, sill, BAND_D + 0.06, sides=False)
            if detail >= 2 and head - sill > 1.2:
                # window frame: transom + horizontal head frame (full width;
                # piers hide it between bays)
                f.quad(frame, 0, L, head - 0.55, head - 0.49, off=0.03)
                f.quad(frame, 0, L, sill + 0.0, sill + 0.06, off=0.03)
            first = False
            zf += floor_h
        if top < z1:   # parapet band above the last window head
            f.relief(wall, 0.0, L, max(win_lo, zf - 0.45), z1, BAND_D)
        if detail >= 2:
            # vertical window frames: a mullion in the middle of each bay and
            # jamb frames each side of the opening
            for c0, c1 in zip(centres, centres[1:]):
                m = (c0 + c1) / 2
                f.quad(frame, m - 0.035, m + 0.035, win_lo, top, off=0.03)
                for s in (c0 + pier_w / 2 + 0.03, c1 - pier_w / 2 - 0.09):
                    f.quad(frame, s, s + 0.06, win_lo, top, off=0.03)
        if top_tier and detail >= 2:
            # cornice: deep projecting slab + frieze course below it
            f.relief(wall, -CORNICE_D, L + CORNICE_D, z1 - 0.75, z1 - 0.2, CORNICE_D + PIER_D)
            f.relief(wall, 0.0, L, z1 - 1.25, z1 - 0.95, PIER_D + 0.12)
        elif not top_tier:
            # setback ledge: belt course
            f.relief(wall, 0.0, L, z1 - 0.6, z1, PIER_D + 0.15)
        # storefronts
        if base_tier and is_street and store:
            _storefront(f, rng, L, ground_h, wall, awning_mat, detail)


def _storefront(f, rng, L, gh, wall, awning_mat, detail):
    bay = rng.uniform(5.0, 7.5)
    cs = _bays(L, bay)
    fascia0 = gh - 1.1
    for c in cs:
        f.relief(wall, c - 0.45, c + 0.45, 0.0, gh, 0.32, top=False, bottom=False)
    f.relief(wall, 0.0, L, fascia0, gh, 0.30)          # sign fascia (left blank)
    f.relief(wall, 0.0, L, 0.0, 0.45, 0.12, bottom=False)  # bulkhead / kick plate
    if detail < 2:
        return
    for c0, c1 in zip(cs, cs[1:]):
        # storefront mullions + transom + door in some bays
        n = max(1, int((c1 - c0 - 0.9) / 1.6))
        for k in range(1, n + 1):
            s = c0 + 0.45 + k * (c1 - c0 - 0.9) / (n + 1)
            f.quad("Mullion_Storefront", s - 0.04, s + 0.04, 0.45, fascia0, off=0.05)
        f.quad("Mullion_Storefront", c0 + 0.45, c1 - 0.45, fascia0 - 0.85, fascia0 - 0.77, off=0.05)
        if rng.random() < 0.4:
            # fabric awning: sloped canopy + valance
            s0, s1 = c0 + 0.5, c1 - 0.5
            z_hi, z_lo, dep = fascia0 - 0.05, fascia0 - 0.75, 1.3
            P, q = f.P, f.kit.quad
            q(awning_mat, P(s0, 0.32, z_hi), P(s0, dep, z_lo), P(s1, dep, z_lo), P(s1, 0.32, z_hi),
              "Furn", False)
            q(awning_mat, P(s1, 0.32, z_hi), P(s1, dep, z_lo), P(s0, dep, z_lo), P(s0, 0.32, z_hi),
              "Furn", False)
            q(awning_mat, P(s0, dep, z_lo - 0.3), P(s1, dep, z_lo - 0.3), P(s1, dep, z_lo),
              P(s0, dep, z_lo), "Furn", False)


# ----------------------------------------------------------------- glass
def _glass_tier(kit, rng, poly, z0, z1, glass, spandrel, floor_h, ground_h, detail,
                pier_pitch, street, store, base_tier, blind=()):
    win_lo = ground_h if base_tier else z0
    fin = "Mullion_Neighbor"
    for i, a, u, n, L in _edges(poly):
        f = Face(kit, a, u, n, L)
        is_street = street is None or i in street
        if i in blind:
            f.quad(glass, 0, L, 0.0 if base_tier else z0, z1, collide=True)
            continue
        f.quad(glass, 0, L, 0.0 if base_tier else z0, z1, collide=True)
        if detail <= 0 or L < 4.0:
            continue
        # spandrel bands (slab edge + dark spandrel glass/metal)
        zf = win_lo
        while zf + floor_h <= z1 + 1e-6:
            f.relief(spandrel, 0.0, L, zf + floor_h - 0.95, zf + floor_h, 0.06, sides=False)
            zf += floor_h
        # vertical mullion fins
        p = max(1.2, pier_pitch * 0.5)
        for c in _bays(L, p):
            f.relief(fin, c - 0.04, c + 0.04, win_lo, z1, 0.14 if detail >= 2 else 0.1,
                     top=False, bottom=False, sides=detail >= 2)
        # corner posts
        f.relief(fin, 0.0, 0.25, 0.0, z1, 0.16, top=False, bottom=False)
        f.relief(fin, L - 0.25, L, 0.0, z1, 0.16, top=False, bottom=False)
        if base_tier:
            # lobby: tall glass, heavy stone/metal transfer band above
            f.relief(spandrel, 0.0, L, ground_h - 1.0, ground_h, 0.25)
            if is_street and detail >= 1:
                for c in _bays(L, 3.0):
                    f.relief("Mullion_Storefront", c - 0.05, c + 0.05, 0.0, ground_h - 1.0, 0.12,
                             top=False, bottom=False)


# ----------------------------------------------------------------- entry
def building(kit, poly, h, wall, win="Window_Dark", floor_h=3.4, ground_h=4.6,
             detail=2, pier_pitch=3.2, pier_w=0.9, store=True, street_edges=None,
             roof="Roof_Grey", style="punched", setback=None, blind=()):
    rng = random.Random(_seed(poly) + int(h * 10))
    if detail <= 0:
        kit.prism(wall, poly, 0.0, h)
        return
    # Midtown "wedding cake": tall masonry buildings step back
    tiers = [(poly, 0.0, h)]
    if setback is None:
        setback = style != "glass" and h > 60 and rng.random() < 0.7
    if setback:
        z_s = round(h * rng.uniform(0.45, 0.7) / floor_h) * floor_h + ground_h * 0.0
        inner = C.inset(poly, rng.uniform(2.5, 4.5))
        if inner and len(inner) >= 3 and z_s > ground_h + 2 * floor_h:
            tiers = [(poly, 0.0, z_s), (inner, z_s, h)]
            if h > 110 and rng.random() < 0.6:
                inner2 = C.inset(inner, rng.uniform(2.5, 4.0))
                z_s2 = z_s + round((h - z_s) * 0.55 / floor_h) * floor_h
                if inner2 and len(inner2) >= 3 and h - z_s2 > 3 * floor_h:
                    tiers = [(poly, 0.0, z_s), (inner, z_s, z_s2), (inner2, z_s2, h)]
    frame = rng.choice(("Window_Frame", "Window_Frame", "Window_Frame_Dark"))
    for k, (p, z0, z1) in enumerate(tiers):
        base, top = k == 0, k == len(tiers) - 1
        if style == "glass":
            _glass_tier(kit, rng, p, z0, z1, wall, win, floor_h, ground_h, detail, pier_pitch,
                        street_edges, store, base, blind if base else ())
        else:
            glass = win if win in ("Window_Glass", "Window_Dark") else "Window_Glass"
            _punched_tier(kit, rng, p, z0, z1, wall, glass, floor_h, ground_h, detail,
                          pier_pitch, pier_w, street_edges, store, frame, base, top,
                          blind if base else ())
        _roof(kit, p, z1, roof if top else wall)
    # rooftop mechanical bulkhead / water tank
    top_poly = tiers[-1][0]
    if h > 30:
        cx, cy = C.centroid(top_poly)
        area = abs(_area(top_poly))
        s = min(6.0, 0.15 * math.sqrt(area))
        kit.box(roof, cx - s, cy - s * 0.7, h, cx + s, cy + s * 0.7, h + 4.0)
        if style != "glass" and h < 120 and rng.random() < 0.55 and detail >= 2:
            tx, ty = cx + s * 0.4, cy - s * 0.2
            kit.cyl("Wood_Tank", tx, ty, h + 4.0, h + 7.2, 1.7, 1.7, n=10, group="Bldg")
            kit.cyl("Roof_Slate", tx, ty, h + 7.2, h + 8.3, 1.8, 0.1, n=10, group="Bldg")


def _area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))
