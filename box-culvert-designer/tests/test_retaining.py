"""Wing wall, apron and cut-off design (EN 1992 + EN 1997) and their schedule."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from detailing import retaining, ec2, bars


def _design(**kw):
    base = dict(barrel_height=2.0, t_top=0.25, t_base=0.25, wall_top=0.3, wall_base=0.4, end_height=0.6, cover=0.05,
                apron_width=8.0, apron_length=4.75, apron_t=0.25, cutoff_depth=0.8, cutoff_t=0.25,
                gamma_soil=19.0, K0=0.5, surcharge=10.0, bearing_allow=210.0, scour_depth=0.6)
    base.update(kw)
    return retaining.design(ec2.Concrete(30), 460, **base)


@pytest.mark.parametrize("H,gamma,sur,bear", [(1.5, 18, 10, 200), (2.5, 19, 16.67, 210), (4.0, 20, 20, 150), (3.0, 21, 30, 120), (5.0, 20, 10, 250)])
def test_wing_wall_is_stable_after_sizing(H, gamma, sur, bear):
    S = _design(barrel_height=H, gamma_soil=gamma, surcharge=sur, bearing_allow=bear)
    oks = {c[0]: c[3] for c in S.wing.checks}
    assert oks["Overturning (EQU)"] and oks["Sliding (GEO)"] and oks["Bearing (GEO)"] and oks["Base contact"]
    assert oks["Stem flexure, earth face"]                     # the stem steel satisfies flexure and crack width
    g = S.wing.geometry
    assert g["base_width"] >= g["toe"] + g["t_base"] / 1000.0 + g["heel"] - 1e-6
    # a taller wall needs more steel and a wider base
    assert 0 < S.wing.face["wk"] <= 0.30 + 1e-6


def test_taller_wall_needs_more():
    a = _design(barrel_height=2.0); b = _design(barrel_height=4.0)
    assert ec2.area(b.wing.face["dia"]) * 1000 / b.wing.face["spacing"] > ec2.area(a.wing.face["dia"]) * 1000 / a.wing.face["spacing"]
    assert b.wing.geometry["base_width"] > a.wing.geometry["base_width"]


def test_water_table_increases_the_wall_moment():
    dry = _design(barrel_height=3.0); wet = _design(barrel_height=3.0, water_depth=0.5)
    assert wet.wing.face["M"] > dry.wing.face["M"]


def test_scour_and_flotation_are_flagged():
    S = _design(cutoff_depth=0.4, scour_depth=1.0)
    assert any(c[0].startswith("Depth against scour") and not c[3] for c in S.cutoff.checks)
    W = _design(apron_t=0.2, water_depth=0.0, scour_depth=1.0)   # shallow apron, high water: uplift
    fl = [c for c in W.apron.checks if c[0] == "Flotation"]
    assert fl and not fl[0][3]


def test_apron_and_cutoff_have_minimum_steel():
    S = _design()
    for e in (S.apron, S.cutoff):
        assert e.face["As"] >= e.face["As_min"] - 1e-6
        assert e.face["dia"] in bars.SIZES and e.face["spacing"] <= 250


def test_export_keys_and_schedule():
    S = _design()
    k = S.export_keys()
    for key in ("WWV_D", "WWV_S", "WWH_D", "WWH_S", "APR_D", "APR_S", "CUT_D", "CUT_S", "WW_T_TOP", "WW_T_BASE"):
        assert key in k
    geom = dict(W_APRON=8050, L_WW_OUT=5485, L_WW_IN=5485, APRON_OUT_L=4750, APRON_IN_L=4750, H_TOT=2500, CUTOFF_D=800, W_APRON_END_OUT=13534)
    rows = bars.secondary_schedule(S, geom)
    assert {r["base"] for r in rows} == {"W1", "W2", "A1", "A2", "C1"}
    for r in rows:
        assert r["length"] <= 12000 + 1e-6 and r["no"] > 0 and r["mass"] > 0
        assert int(r["dia"]) in bars.SIZES
    assert sum(r["mass"] for r in rows) > 500        # a real tonnage of secondary steel
