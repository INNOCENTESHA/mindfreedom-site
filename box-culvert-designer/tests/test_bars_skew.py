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
    # position rule: top bars (01 top slab, 04 base) lap at mid-span only; bottom bars (02 base, 03 top slab) over the piers only
    assert bars.LAYER == {"01": "top", "02": "bottom", "03": "bottom", "04": "top"}
    sw, ti, wc = P["SPAN_W"], P["T_INWALL"], P["W_CLEAR"]
    mids = [-wc / 2 + j * (sw + ti) + sw / 2 for j in range(nc)]; piers = [-wc / 2 + j * sw + (j - 1) * ti + ti / 2 for j in range(1, nc)]
    sups = piers + [-wc / 2 - P["T_WALL"] / 2, wc / 2 + P["T_WALL"] / 2]
    for lp in D.laps:
        x0, x1 = lp["at"][0] - lp["l0"] / 2, lp["at"][0] + lp["l0"] / 2
        if bars.LAYER[lp["mark"]] == "top":                                   # whole lap inside the middle of a cell, clear of every support
            assert any(abs(lp["at"][0] - m) <= 0.25 * sw - lp["l0"] / 2 + 1e-6 for m in mids), lp
            assert all(min(abs(x0 - s), abs(x1 - s)) >= 0.25 * sw - P["T_WALL"] / 2 - 1e-6 for s in sups), lp
        else:                                                                 # whole lap at a pier, clear of every mid-span
            assert any(abs(lp["at"][0] - q) <= ti / 2 + 0.30 * sw - lp["l0"] / 2 + 1e-6 for q in piers), lp
            assert all(min(abs(x0 - m), abs(x1 - m)) >= 0.20 * sw - 1e-6 for m in mids), lp


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


@pytest.mark.parametrize("S", [45, 50, 60, 70, 75, 80, 85, 95, 100, 110, 120, 130, 135])
@pytest.mark.parametrize("flare", [0.0, 15.0, 30.0, 40.0])
def test_skew_layout(S, flare):
    g = skew.layout(W, L, A, flare, S); th = math.radians(S); s = math.sin(th); ct = math.cos(th) / s; b = math.radians(flare); o = g["outline"]
    # the road is horizontal: barrel ends parallel to it, the axis at the skew angle, walls stretched, section true
    assert o[0][1] == o[1][1] == -L / 2 and o[2][1] == o[3][1] == L / 2
    ax = (o[3][0] - o[0][0], o[3][1] - o[0][1]); n = math.hypot(*ax)
    assert n == pytest.approx(L / s) and math.degrees(math.atan2(ax[1], ax[0])) == pytest.approx(S)
    assert abs((o[1][0] - o[0][0]) * ax[1] - (o[1][1] - o[0][1]) * ax[0]) / n == pytest.approx(W)
    for poly in g["walls"]:
        a2 = (poly[3][0] - poly[0][0], poly[3][1] - poly[0][1])
        assert abs((poly[1][0] - poly[0][0]) * a2[1] - (poly[1][1] - poly[0][1]) * a2[0]) / math.hypot(*a2) == pytest.approx(250.0)
    assert g["ok"]
    want = sorted(A / (math.cos(b) - sg * math.sin(b) * ct) for sg in (1, -1))
    for en, e in g["ends"].items():
        assert sorted(w["length"] for w in e["walls"].values()) == pytest.approx(want)
        assert e["apron_edge"][0][1] == pytest.approx(e["apron_edge"][1][1])                 # apron end parallel to the road
        d = abs(e["apron_edge"][0][1] - e["y"]); assert d == pytest.approx(A * s)             # apron runs A along the axis
        for sd, w in e["walls"].items():
            assert w["start"][1] == pytest.approx(e["y"]) and w["length"] == pytest.approx(math.dist(w["start"], w["end"]))
            v = (w["end"][0] - w["start"][0], w["end"][1] - w["start"][1]); sg = 1 if en == "outlet" else -1
            cosang = (v[0] * sg * ax[0] + v[1] * sg * ax[1]) / (n * w["length"])
            assert math.degrees(math.acos(max(-1, min(1, cosang)))) == pytest.approx(flare, abs=1e-4)   # flare measured from the culvert axis
    # mirror crossing swaps left and right; the two ends are each other turned half round
    m = skew.layout(W, L, A, flare, 180 - S)
    for en in ("inlet", "outlet"):
        assert m["ends"][en]["walls"]["left"]["length"] == pytest.approx(g["ends"][en]["walls"]["right"]["length"])
    assert g["ends"]["inlet"]["walls"]["left"]["length"] == pytest.approx(g["ends"]["outlet"]["walls"]["right"]["length"])
    if flare > 0 and S != 90: assert want[1] - want[0] > 1.0                                  # the two walls of an end differ


def test_skew_flags_a_flare_that_never_meets_the_apron():
    g = skew.layout(W, L, A, 50.0, 45)                 # cos b - sin b cot S < 0: that wall runs away from the apron end
    assert not g["ok"] and any(not w["ok"] and w["reason"] for e in g["ends"].values() for w in e["walls"].values())
    assert all(r["ok"] for r in skew.simulate(W, L, A, 30.0))
