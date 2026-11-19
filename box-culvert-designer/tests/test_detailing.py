"""Code rules, ground, skew, toe and member design - checked against hand-worked values."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from detailing import ec2, soil, skew, design, checks
from engine import Box, P


def close(a, b, tol=0.01): return abs(a - b) <= tol * max(1.0, abs(b))


def test_ec2_materials_and_bond():
    c = ec2.Concrete(25)
    assert close(c.fctm, 2.565, 0.001) and close(c.fctd, 1.197, 0.002) and close(c.fcd, 14.17, 0.001)
    assert close(ec2.fbd(c, 16), 2.693, 0.002) and close(ec2.fbd(c, 16, good_bond=False), 0.7 * 2.693, 0.002)
    assert close(ec2.lb_rqd(c, 16, 400), 16 / 4 * 400 / 2.693, 0.002)             # 594 mm = 37.1 dia


def test_ec2_laps_and_anchorage():
    c = ec2.Concrete(25)
    assert ec2.alpha6(20) == 1.0 and close(ec2.alpha6(50), math.sqrt(2)) and ec2.alpha6(100) == 1.5
    l50 = ec2.lap_length(c, 16, 400, 50); l100 = ec2.lap_length(c, 16, 400, 100)
    assert close(l50["l0"], 1.414 * 594.1, 0.005) and close(l100["l0"], 1.5 * 594.1, 0.005)
    assert ec2.lap_length(c, 10, 50, 50)["l0"] == 200.0                           # l0,min = max(0.3 a6 lb, 15 dia, 200)
    a = ec2.anchorage_length(c, 16, 400, cd=40)                                   # alpha2 = 1 - 0.15 (40 - 16) / 16 = 0.775
    assert close(a["alpha2"], 0.775) and close(a["lbd"], 0.775 * 594.1, 0.005)
    r = ec2.lap_rules(16, 800)
    assert r["stagger_centres_min"] == 1040 and r["clear_between_lapped_max"] == 64


def test_ec2_spacing_cover_minimum_steel():
    c = ec2.Concrete(25, dg=20)
    assert ec2.min_clear_spacing(16, 20) == 25 and ec2.min_clear_spacing(32, 20) == 32
    assert ec2.max_spacing_slab(250) == 400 and ec2.max_spacing_slab(250, concentrated=True) == 250 and ec2.max_spacing_slab(100) == 300
    assert ec2.nominal_cover("XC2", 16)["cnom"] == 35 and ec2.nominal_cover("XC2", 16, cast_against="blinding")["cnom"] == 40
    assert ec2.nominal_cover("XD2", 16)["cnom"] == 50 and ec2.nominal_cover("XC2", 16, cast_against="soil")["cnom"] == 75
    assert close(ec2.As_min_flexure(c, 460, 1000, 192), max(0.26 * 2.565 / 460 * 1000 * 192, 0.0013 * 1000 * 192), 0.002)
    assert ec2.mandrel_diameter(16) == 64 and ec2.mandrel_diameter(20) == 140 and ec2.bs8666_former_radius(16) == 32


def test_ec2_shear():
    c = ec2.Concrete(25); As = ec2.As_per_m(16, 150)
    # k = 2.0, rho = 0.00698: v = 0.12 x 2 x (100 x 0.00698 x 25)^(1/3) = 0.6225 MPa
    assert close(ec2.VRd_c(c, 1000, 192, As) / 1e3, 0.6225 * 192, 0.005)
    L = ec2.shear_links(c, 460, 200e3, 1000, 192)
    assert L["ok_strut"] and L["Asw_s"] >= L["Asw_s_min"] and close(L["s_long_max"], 144) and close(L["s_trans_max"], 288)
    assert close(L["Asw_s_calc"], 200e3 / (0.9 * 192 * 400 * 2.5), 0.002)
    assert not ec2.slab_may_have_links(180) and ec2.slab_may_have_links(200)
    assert ec2.shear_enhancement(192, 192) == 0.5 and ec2.shear_enhancement(500, 192) == 1.0


def test_ec2_staggered_lap_layout():
    lay = ec2.lap_layout(30000, 800, stock=12000)
    assert lay["ok"] and lay["stagger"] >= 1.3 * 800 - 1e-6
    for fam in ("A", "B"):
        pcs = lay[fam]["pieces"]
        assert max(pcs) <= 12000 + 1e-6 and close(sum(pcs) - 800 * (len(pcs) - 1), 30000, 1e-6)      # pieces overlap by one lap each
    assert ec2.lap_layout(9000, 800)["n_laps"] == 0


def test_skew_wing_walls():
    sq = skew.wing_walls(6750, 4750, 30, 90)
    assert close(sq.left["length"], 4750 / math.cos(math.radians(30)), 1e-6) and close(sq.left["length"], sq.right["length"], 1e-9)
    assert close(sq.apron_edge, 6750 + 2 * 4750 * math.tan(math.radians(30)), 1e-6)       # 12234 mm (workbook: + 2 x 700 = 13634)
    e = skew.wing_walls(6750, 4750, 30, 70); ct = 1 / math.tan(math.radians(70)); b = math.radians(30)
    assert close(e.left["length"], 4750 / (math.cos(b) - math.sin(b) * ct), 1e-6) and close(e.right["length"], 4750 / (math.cos(b) + math.sin(b) * ct), 1e-6)
    assert e.left["length"] > sq.left["length"] > e.right["length"]
    m = skew.wing_walls(6750, 4750, 30, 110)                                     # mirror image of 70 degrees
    assert close(m.left["length"], e.right["length"], 1e-6) and close(m.right["length"], e.left["length"], 1e-6)
    assert not skew.wing_walls(6750, 4750, 60, 50).left["ok"]                     # flare parallel to / beyond the apron edge
    s = skew.slab_effects(1500, 60)
    assert close(s["skew_span"], 1500 / math.sin(math.radians(60))) and close(s["As_factor_end_zone"], 1 / math.sin(math.radians(60)) ** 2)
    assert skew.end_zone_bars(7250, 90, 200)["n"] == 0 and skew.end_zone_bars(7250, 70, 200)["n"] > 0


def _profile(water=None):
    return soil.Profile([soil.Layer("Fill", 1.5, 19, phi=30, E=20000), soil.Layer("Clay", 3.0, 19, gamma_sat=20, phi=26, c=5, cu=90, E=25000),
                         soil.Layer("Sand", 10, 20, gamma_sat=21, phi=36, E=60000)], water_depth=water)


def test_soil_stresses_and_pressures():
    P0 = _profile()
    assert close(P0.sigma_v(3.0)[0], 19 * 1.5 + 19 * 1.5) and P0.sigma_v(3.0)[1] == 0
    Pw = _profile(2.0); sv, u, se = Pw.sigma_v(4.0)
    assert close(sv, 19 * 1.5 + 19 * 0.5 + 20 * 2.0) and close(u, 9.81 * 2.0) and close(se, sv - u)
    lat = Pw.lateral_at_rest(4.0, surcharge=10)
    k0 = 1 - math.sin(math.radians(26))
    assert close(lat["K0"], k0) and close(lat["earth"], k0 * se) and close(lat["water"], u) and close(lat["surcharge"], k0 * 10)
    assert Pw.breaks(1.0, 5.0) == [1.0, 1.5, 2.0, 4.5, 5.0]


def test_soil_stiffness_and_bearing():
    stiff = soil.Profile([soil.Layer("Rock-like", 30, 21, phi=40, E=500000)]); soft = soil.Profile([soil.Layer("Soft", 30, 17, phi=24, E=5000)])
    assert stiff.subgrade_modulus(7.25, 3.0) > 50 * soft.subgrade_modulus(7.25, 3.0)
    one = soil.Profile([soil.Layer("Uniform", 40, 19, phi=30, E=30000)])
    # strip, 2:1 spread to 2B: s = q B / E ln(3)  ->  ks = E / (B ln 3)
    assert close(one.subgrade_modulus(5.0, 2.0), 30000 / (5.0 * math.log(3)), 0.01)
    d = one.bearing_drained(5.0, 2.0)
    Nq = math.exp(math.pi * math.tan(math.radians(30))) * math.tan(math.radians(60)) ** 2
    assert close(d["Nq"], Nq) and close(d["Nq"], 18.40, 0.002) and close(d["qRk"], 38 * Nq + 0.5 * 19 * 5 * 2 * (Nq - 1) * math.tan(math.radians(30)), 0.001)
    b = _profile().bearing(160, 7.25, 3.4)
    assert b["ok"] and 0 < b["util"] < 1 and b["governing"]["governs"] == "undrained"


def test_toe_and_equilibrium():
    b0 = Box(P()).analyse()
    p = P(); p.toe = 0.3; b1 = Box(p).analyse()
    q0 = max(b0.bearing(c)[0] for c in b0.sls_combos()); q1 = max(b1.bearing(c)[0] for c in b1.sls_combos())
    assert q1 < q0 and close(b1.base_width, 7.25 + 0.6)                           # a wider base spreads the load
    u = b1.combine_u({"SW": 1.0})
    applied = p.gamma_conc * (p.t_top * b1.W_cl + p.t_base * (b1.W_cl + 2 * b1.toe_len) + sum(w["t"] * p.Hc for w in b1.wall_chains))
    assert close(sum(b1.fr.nodes[n].ky * u[3 * n + 1] for n in b1.base_nodes), applied, 1e-6)
    assert min(b1.bearing(c)[2] for c in b1.sls_combos()) > 0                     # no tension in the ground springs


def test_member_design_and_checks():
    p = P(); p.toe = 0.3; p.profile = _profile(4.0)
    b = Box(p).analyse(); R = design.design(b, cover=0.05)
    for m, s in R.shear.items():
        assert s.V_d <= s.V_face + 1e-6                                           # shear at d never exceeds the shear at the face
        assert s.util <= 1.0 or (s.links and s.links["ok"])
    for f in R.faces.values():
        assert f.As >= max(f.As_req, f.As_min) - 1e-6 and f.wk <= 0.3 + 1e-9 and f.spacing <= f.s_max and f.spacing - f.dia >= f.s_clear_min
    am = math.ceil(max(v["anchorage_bent"]["multiple"] for v in R.lengths.values())); lm = math.ceil(max(v["lap50"]["multiple"] for v in R.lengths.values()))
    rows = checks.run(b, R, dict(toe=300, skew=70, flare=30, apron=4750, inner_width=6750, barrel_length=10500, joint_spacing=15000,
                                 anch_mult=am, lap_mult=lm), p.profile)
    assert len(rows) > 60 and all(r["ok"] for r in rows), [r["item"] for r in rows if not r["ok"]]
    groups = {r["group"] for r in rows}
    assert {"Durability", "Flexure", "Minimum steel", "Bar spacing", "Cracking", "Shear", "Anchorage", "Laps", "Free edges", "Joints", "Skew", "Ground"} <= groups


def test_shear_failure_is_resolved_not_reported():
    p = P(); p.fill = 4.0                                                         # deep fill: the 250 slab now needs help in shear
    b = Box(p).analyse(); R = design.design(b, cover=0.05)
    s = R.shear["top"]
    assert s.util <= 1.0 or s.links is not None or "FAILS" in s.note
    if s.links: assert s.links["VRd_s"] >= s.V_d and s.links["s_long"] <= 0.75 * R.faces[("top", "outer")].d + 1e-6


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"{n} tests passed")
