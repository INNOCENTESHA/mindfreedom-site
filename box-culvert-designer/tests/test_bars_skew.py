"""Bars as supplied (stock length, sizes, laps) and the skewed plan with the road horizontal."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
import section_bb
from detailing import bars, skew, ec2

BASE = dict(SPAN_H=2000, T_TOP=300, T_BASE=300, T_WALL=300, T_INWALL=250, COVER=50, OUT_D=16, OUT_S=150, TOPIN_D=16, BOTIN_D=16,
            WALLIN_D=12, DIST_D=12, LAP_MULT=37, ANCH_MULT=26)


@pytest.mark.parametrize("nc,sw,toe", [(4, 1500, 0), (6, 2500, 0), (8, 3000, 0), (5, 4000, 0), (3, 6000, 0), (8, 1500, 0), (6, 2500, 600), (8, 4000, 300), (2, 6000, 0)])
def test_no_piece_longer_than_stock_and_laps_staggered(nc, sw, toe):
    Q = dict(BASE, N_CELLS=nc, SPAN_W=sw, TOE=toe); D = section_bb.build(Q); P = section_bb.complete(Q)
    assert not D.warnings
    for pc in D.pieces: assert bars.plen(pc["pts"]) <= 12000 + 1e-6, pc["mark"]
    for item in D.pl:
        if item[2] == "CBC_REBAR": assert bars.plen(item[0]) <= 12000 + 1e-6
    # the pieces of each family rebuild the whole bar: sum of pieces = run + laps
    by = {}
    for pc in D.pieces:
        if pc["split"]: by.setdefault((pc["mark"], pc["fam"]), []).append(pc)
    for (mark, fam), pcs in by.items():
        l0 = pcs[0]["lap"]["l0"]; assert l0 == 37 * pcs[0]["dia"]
        other = by[(mark, "B" if fam == "A" else "A")]
        assert abs(sum(bars.plen(p["pts"]) for p in pcs) - (len(pcs) - 1) * l0 - (sum(bars.plen(p["pts"]) for p in other) - (len(other) - 1) * l0)) < 1.0
        assert pcs[0]["lap"]["stagger"] >= 1.3 * l0 - 1e-6                    # 8.7.2(3)
    for a in D.laps:                                                          # measured on the drawing itself
        for b in D.laps:
            if a["mark"] == b["mark"] and a["fam"] != b["fam"]: assert abs(a["at"][0] - b["at"][0]) >= 1.3 * a["l0"] - 1e-6
    # laps sit in the low-stress zones: outer mats at mid-span, inner mats over the piers
    for lp in D.laps:
        face = "outer" if lp["mark"] in ("01", "02") else "inner"
        assert any(abs(lp["at"][0] - x) <= hw + 1e-6 for x, hw in bars.zones(P, face)), lp


@pytest.mark.parametrize("length,skew_deg", [(10500, 90), (30000, 90), (30000, 60), (120000, 75), (12050, 90)])
def test_schedule_limits(length, skew_deg):
    Q = dict(BASE, N_CELLS=6, SPAN_W=2500); D = section_bb.build(Q); P = section_bb.complete(Q)
    rows = bars.schedule(D, P, length, skew_deg)
    assert max(r["length"] for r in rows) <= 12000
    assert all(int(r["dia"]) in bars.SIZES and r["no"] > 0 and r["mass"] > 0 for r in rows)
    lim = bars.limits(rows, 460); assert all(ok for *_, ok, _ in lim), [l for l in lim if not l[3]]
    assert not all(ok for *_, ok, _ in bars.limits(rows, 700))               # a grade nobody supplies is refused
    # distribution bars: total length supplied covers the barrel plus the laps
    dist = [r for r in rows if r["base"] == "08"]; run = length / math.sin(math.radians(skew_deg)) - 100
    per_bar = sum(r["length"] * r["no"] for r in dist) / len(D.dots)
    assert per_bar >= run - 1e-6


def test_split_matches_hand_case():
    # straight 20 m run, T20, lap 1000: two pieces per bar, families cut 1.3 m or more apart
    sp = bars.split([(0, 0), (20000, 0)], 1000.0, 12000.0, prefer=[(9000, 600), (11000, 600), (7000, 600), (13000, 600)])
    assert sp["ok"] and len(sp["A"]) == len(sp["B"]) == 1 and abs(sp["A"][0] - sp["B"][0]) >= 1300
    for s0, s1 in sp["pieces_A"] + sp["pieces_B"]: assert s1 - s0 <= 12000
    assert sum(e - s for s, e in sp["pieces_A"]) == pytest.approx(21000)
    assert bars.split([(0, 0), (11900, 0)], 1000.0) is None


def test_wall_lap_rule():
    w = bars.wall_lap(2600, 50, 16, 592, 640); assert w["staggered"] and 2 * w["stagger"] >= 1.3 * 592
    w = bars.wall_lap(1500, 50, 16, 592, 640); assert not w["staggered"] and w["lap"] == 640 and w["percent"] == 100


def test_developed_length_and_shape():
    u = [(0, 1000), (0, 0), (3000, 0), (3000, 1000)]
    assert bars.shape_code(u) == "21" and bars.shape_code(u[:3]) == "11" and bars.shape_code(u[:2]) == "00"
    r = ec2.bs8666_former_radius(16) + 8
    assert bars.developed(u, 16) == math.ceil((5000 - 2 * (2 * r - r * math.pi / 2)) / 25) * 25


# ------------------------------------------------------------------ skew
W, L, A, FL = 7250.0, 10500.0, 4750.0, 30.0


def test_square_layout():
    g = skew.layout(W, L, A, FL, 90)
    for e in g["ends"].values():
        for w in e["walls"].values():
            assert w["length"] == pytest.approx(A / math.cos(math.radians(FL))) and w["change"] == pytest.approx(0) and w["flare"] == pytest.approx(FL)
    assert g["wall_length"] == pytest.approx(L) and g["end_face_length"] == pytest.approx(W)


@pytest.mark.parametrize("S", [50, 60, 70, 75, 80, 85, 95, 100, 110, 120, 130])
@pytest.mark.parametrize("pivot", ["centre", "inlet", "outlet"])
def test_skew_layout_invariants(S, pivot):
    g = skew.layout(W, L, A, FL, S, pivot); sq = skew.layout(W, L, A, FL, 90, pivot); s = math.sin(math.radians(S))
    o = g["outline"]
    # barrel: ends parallel to the road at the same distance, walls stretched, true width normal to the axis
    assert o[0][1] == o[1][1] == -L / 2 and o[2][1] == o[3][1] == L / 2
    assert math.dist(o[0], o[3]) == pytest.approx(L / s) and math.dist(o[1], o[2]) == pytest.approx(L / s)
    ax = (o[3][0] - o[0][0], o[3][1] - o[0][1]); n = math.hypot(*ax)
    assert abs((o[1][0] - o[0][0]) * ax[1] - (o[1][1] - o[0][1]) * ax[0]) / n == pytest.approx(W)
    assert math.degrees(math.atan2(ax[1], ax[0])) == pytest.approx(S)                      # the axis makes the skew angle with the road
    for poly in g["walls"]:                                                               # walls stay solid, thickness true
        a2 = (poly[3][0] - poly[0][0], poly[3][1] - poly[0][1])
        assert abs((poly[1][0] - poly[0][0]) * a2[1] - (poly[1][1] - poly[0][1]) * a2[0]) / math.hypot(*a2) == pytest.approx(250.0)
    for en, e in g["ends"].items():
        for sd, w in e["walls"].items():
            assert w["end"] == pytest.approx(sq["ends"][en]["walls"][sd]["end"])            # wing wall ends on the apron edge did not move
            assert w["start"][1] == pytest.approx(e["y"])
            assert w["length"] == pytest.approx(math.dist(w["start"], w["end"]))
        assert e["apron_edge"][0][1] == e["apron_edge"][1][1]                               # apron outer edge parallel to the road
    # the pivot does not move
    yp = g["pivot_point"][1]; t = (yp + L / 2) / L
    assert o[0][0] + (o[3][0] - o[0][0]) * t + W / 2 / s == pytest.approx(0.0, abs=1e-6)
    # mirror crossing swaps left and right
    m = skew.layout(W, L, A, FL, 180 - S, pivot)
    for en in ("inlet", "outlet"):
        assert m["ends"][en]["walls"]["left"]["length"] == pytest.approx(g["ends"][en]["walls"]["right"]["length"])
    if pivot == "centre":                                                                  # point symmetry about the road centre
        assert g["ends"]["inlet"]["walls"]["left"]["length"] == pytest.approx(g["ends"]["outlet"]["walls"]["right"]["length"])
        assert g["ends"]["inlet"]["walls"]["right"]["length"] == pytest.approx(g["ends"]["outlet"]["walls"]["left"]["length"])
    else:                                                                                  # the pivot end keeps two equal walls
        e = g["ends"][pivot]["walls"]; assert e["left"]["length"] == pytest.approx(e["right"]["length"])
    # one wall of each moving end is stretched and the other shortened
    far = g["ends"]["outlet" if pivot != "outlet" else "inlet"]["walls"]
    assert (far["left"]["length"] - far["right"]["length"]) != pytest.approx(0)


def test_skew_simulation_flags_impossible_walls():
    rows = skew.simulate(W, L, A, FL)
    ok = {r["skew"]: r["ok"] for r in rows}
    assert ok[90] and ok[75] and ok[105] and not ok[45] and not ok[135]
    # a longer apron or wider flare restores a steeper skew
    assert skew.layout(W, L, 9000.0, 45.0, 55)["ok"]
