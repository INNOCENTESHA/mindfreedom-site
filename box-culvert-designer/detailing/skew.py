"""
Skewed culverts: plan geometry and the effect of skew on the wing walls and on the reinforcement.

Convention (as on the drawings): SKEW is the angle between the culvert axis and the road centre line,
90 deg = square crossing.  The barrel ends are cut parallel to the road, so at a skewed crossing the end
faces are oblique and the two wing walls of one end have different lengths.
Plan coordinates: x along the culvert axis (outward from the barrel end), y across; units as given.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


def _cot(a): return math.cos(a) / math.sin(a)


@dataclass
class End:
    left: dict
    right: dict
    apron_edge: float           # length of the apron end (free) edge
    apron_area: float
    corner_left: tuple
    corner_right: tuple


def barrel(width: float, length_cl: float, skew_deg: float) -> dict:
    """Barrel in plan.  width: overall width normal to the axis; length_cl: length on the axis."""
    th = math.radians(skew_deg); off = width / 2.0 * _cot(th)      # how far an edge runs ahead of / behind the axis
    return dict(skew=skew_deg, offset=off, length_cl=length_cl,
                wall_lengths=(length_cl, length_cl),               # each wall is as long as the axis (parallelogram)
                end_face_length=width / math.sin(th), plan_area=width * length_cl,
                acute_corner_angle=min(skew_deg, 180 - skew_deg), obtuse_corner_angle=max(skew_deg, 180 - skew_deg))


def wing_walls(width: float, apron_length: float, flare_deg: float, skew_deg: float, flare_right_deg: float | None = None) -> End:
    """One end of the culvert.  The apron runs apron_length along the axis and ends on a line parallel to the
    (skewed) end face; each wing wall starts at a barrel corner and flares outward by its flare angle
    (measured from the culvert axis) until it meets that line.

        left  wall (y > 0): length = A / (cos b - sin b cot S)
        right wall (y < 0): length = A / (cos b + sin b cot S)

    Square crossing (S = 90 deg): both A / cos b."""
    th = math.radians(skew_deg); ct = _cot(th); A = apron_length; out = {}
    corners = {}
    for side, sgn, fl in (("left", 1.0, flare_deg), ("right", -1.0, flare_right_deg if flare_right_deg is not None else flare_deg)):
        b = math.radians(fl); den = math.cos(b) - sgn * math.sin(b) * ct
        y0 = sgn * width / 2.0; x0 = y0 * ct                         # barrel corner on the skewed end face
        if den <= 1e-6:
            out[side] = dict(ok=False, reason=f"flare {fl:g} deg runs parallel to or away from the apron edge at skew {skew_deg:g} deg",
                             length=float("inf"), flare=fl, start=(x0, y0), end=None, angle_to_face=None)
            corners[side] = (x0, y0); continue
        t = A / den
        end = (x0 + t * math.cos(b), y0 + sgn * t * math.sin(b))
        # angle between the wall and the end face (the corner the wall makes with the barrel end)
        face = (ct, 1.0); fm = math.hypot(*face); wall = (math.cos(b), sgn * math.sin(b))
        ang = math.degrees(math.acos(max(-1, min(1, (wall[0] * face[0] * sgn + wall[1] * face[1] * sgn) / fm))))
        out[side] = dict(ok=True, length=t, flare=fl, start=(x0, y0), end=end, angle_to_face=ang, splay=abs(end[1] - y0))
        corners[side] = end
    L, R = out["left"], out["right"]
    if L["ok"] and R["ok"]:
        edge = math.dist(L["end"], R["end"])
        pts = [L["start"], L["end"], R["end"], R["start"]]
        area = 0.5 * abs(sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4)))
    else:
        edge = area = float("nan")
    return End(L, R, edge, area, corners.get("left"), corners.get("right"))


def slab_effects(clear_span: float, skew_deg: float) -> dict:
    """How skew changes the top / base slab design.

    The slabs span between the walls (square span).  Along a skewed free end the slab edge spans obliquely:
    the edge strip spans  clear_span / sin S  and its moment grows with the square of that ratio, so the
    transverse steel in the end zones is increased by 1 / sin^2 S (same depth), and bars placed parallel to
    the skewed edge are longer by 1 / sin S.  The triangular end zone needing these bars extends
    width x |cot S| along the axis.  Reactions concentrate at the obtuse corners, which get extra top steel.
    Up to about 20 deg off square the square-span design with edge bars is normally sufficient."""
    th = math.radians(skew_deg); s = math.sin(th)
    off_square = abs(90.0 - skew_deg)
    return dict(skew_span=clear_span / s, span_factor=1.0 / s, moment_factor=1.0 / s ** 2, As_factor_end_zone=1.0 / s ** 2,
                bar_length_factor=1.0 / s, off_square=off_square,
                treatment="square" if off_square < 1e-6 else ("square span + skew edge bars" if off_square <= 20 else
                                                              "skew end zones designed on the skew span; obtuse-corner top steel"))


def end_zone_bars(width: float, skew_deg: float, spacing: float, cover: float = 50.0) -> dict:
    """Transverse bars in the triangular zone at a skewed end, laid parallel to the end face (a 'fan' is avoided:
    constant spacing measured normal to the bars).  Returns the number of bars, their lengths and the zone length."""
    th = math.radians(skew_deg); ct = abs(_cot(th))
    zone = width * ct                                  # length of the triangular zone along the axis
    if zone < 1e-9: return dict(zone=0.0, n=0, lengths=[], full_length=width - 2 * cover)
    full = (width - 2 * cover) / math.sin(th)
    sp_axis = spacing / math.sin(th)                   # spacing measured along the axis
    n = int(zone / sp_axis)
    lengths = [full * (1 - (i * sp_axis) / zone) for i in range(1, n + 1)]      # bars shorten toward the acute corner
    return dict(zone=zone, n=n, lengths=[x for x in lengths if x > 300.0], full_length=full, spacing_along_axis=sp_axis)


# ------------------------------------------------------------------ plan layout, road horizontal
PIVOTS = {"centre": 0.0, "inlet": -0.5, "outlet": 0.5}


def layout(width: float, length: float, apron: float, flare_deg: float, skew_deg: float, pivot: str = "centre",
           wall_t: float = 250.0, inner_walls: tuple = (), wing_t: float = 250.0) -> dict:
    """Plan of the culvert with the road along X (always horizontal) and the square crossing as the starting point.

    Square layout (skew 90): barrel axis along Y, barrel ends at y = -L/2 (inlet) and +L/2 (outlet), wing walls from the
    barrel corners out to the apron outer edges at y = -(L/2 + A) and L/2 + A.

    Skew: the barrel axis is turned about the pivot until it makes the skew angle with the road.  Everything that
    belongs to the road stays put: the barrel end faces stay parallel to the road at the same distance from it, and
    the apron outer edges, with the points where the wing walls meet them, do not move.  So
      * the barrel becomes a parallelogram: each wall is L / sin(skew) long, the cross-section normal to the axis is
        unchanged (wall thickness and clear spans are true), and the end faces are W / sin(skew) long;
      * every barrel corner slides along its end face by (y_end - y_pivot) cot(skew);
      * each wing wall still runs from its barrel corner to its unmoved end on the apron edge, so it is stretched on
        one side and shortened on the other.
    pivot: 'centre' (road centre line), 'inlet' or 'outlet' (the barrel / wing wall junction line of that end).
    width: overall width normal to the axis; inner_walls: offsets of pier centre lines from the axis (normal to it).
    Lengths in the units given; angles in degrees."""
    th = math.radians(skew_deg); s = math.sin(th); ct = math.cos(th) / s
    L, A, W = length, apron, width; yp = PIVOTS[pivot] * L; b = math.radians(flare_deg)
    axis_x = lambda y: (y - yp) * ct                                  # the culvert axis at distance y from the road centre
    half = W / 2.0 / s                                                # half width measured along the road
    ends = {}
    for name, sg in (("inlet", -1.0), ("outlet", 1.0)):
        ye = sg * L / 2.0; xc = axis_x(ye); walls = {}
        for side, sd in (("left", -1.0), ("right", 1.0)):
            corner = (xc + sd * half, ye)
            tip0 = (sd * (W / 2.0 + A * math.tan(b)), ye + sg * A)   # where this wall met the apron edge at the square crossing
            sq_corner = (sd * W / 2.0, ye)
            v = (tip0[0] - corner[0], tip0[1] - corner[1]); ln = math.hypot(*v); l_sq = math.dist(sq_corner, tip0)
            flare_now = math.degrees(math.atan2(sd * v[0], sg * v[1]))               # from the road normal, outward positive
            wall_dir = (sg * math.cos(th), sg * math.sin(th))                        # barrel wall direction, outward at this end
            ang_barrel = math.degrees(math.acos(max(-1.0, min(1.0, (v[0] * wall_dir[0] + v[1] * wall_dir[1]) / ln))))
            ang_apron = math.degrees(math.atan2(abs(v[1]), sd * v[0])) if ln else 90.0   # interior angle with the apron outer edge
            walls[side] = dict(start=corner, end=tip0, length=ln, square_length=l_sq, change=ln - l_sq, flare=flare_now,
                               angle_to_barrel_wall=ang_barrel, angle_to_apron_edge=ang_apron, slide=corner[0] - sq_corner[0],
                               ok=sd * v[0] > -1e-9 and ln > 0.25 * l_sq,
                               reason="" if sd * v[0] > -1e-9 else "the barrel corner has slid past the wing wall end: reduce the skew, lengthen the apron or move the pivot")
        ends[name] = dict(y=ye, axis_x=xc, walls=walls, apron_edge=(walls["left"]["end"], walls["right"]["end"]),
                          apron_poly=[walls["left"]["start"], walls["right"]["start"], walls["right"]["end"], walls["left"]["end"]])
    def line(off):                                                    # a line parallel to the axis, off normal to it
        return [(axis_x(-L / 2.0) + off / s, -L / 2.0), (axis_x(L / 2.0) + off / s, L / 2.0)]
    outline = [line(-W / 2.0)[0], line(W / 2.0)[0], line(W / 2.0)[1], line(-W / 2.0)[1]]
    wall_polys = []
    for c, t in [(-W / 2.0 + wall_t / 2.0, wall_t), (W / 2.0 - wall_t / 2.0, wall_t)] + [(c, t) for c, t in inner_walls]:
        p, q = line(c - t / 2.0), line(c + t / 2.0); wall_polys.append([p[0], q[0], q[1], p[1]])
    return dict(skew=skew_deg, pivot=pivot, pivot_point=(0.0, yp), ends=ends, outline=outline, walls=wall_polys, axis=[(axis_x(-L / 2.0 - A), -L / 2.0 - A), (axis_x(L / 2.0 + A), L / 2.0 + A)],
                wall_length=L / s, end_face_length=W / s, slide=(L / 2.0) * abs(ct), plan_area=W * L / s,
                ok=all(w["ok"] for e in ends.values() for w in e["walls"].values()))


def simulate(width: float, length: float, apron: float, flare_deg: float, angles=(45, 60, 75, 90, 105, 120, 135), pivot: str = "centre") -> list:
    """Wing wall lengths and orientations over a range of skews: one row per angle."""
    rows = []
    for a in angles:
        g = layout(width, length, apron, flare_deg, a, pivot); r = dict(skew=a, wall_length=g["wall_length"], end_face=g["end_face_length"], ok=g["ok"])
        for e in ("inlet", "outlet"):
            for sd in ("left", "right"):
                w = g["ends"][e]["walls"][sd]; r[f"{e}_{sd}"] = w["length"]; r[f"{e}_{sd}_flare"] = w["flare"]
        rows.append(r)
    return rows
