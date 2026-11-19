"""
What-if sweep: many culverts through analysis, design, code checks and the reinforcement drawing,
each tested against invariants that must hold whatever the input.

    python tests/scenarios.py [n]        # n random cases on top of the fixed grid (default 150)
"""
import math, os, random, sys, time, collections, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engine import Box, P
from detailing import design, checks, soil, skew, ec2, bars
import section_bb
from matplotlib.path import Path

PROFILES = {
    None: None,
    "clay over sand": lambda w: soil.Profile([soil.Layer("Fill", 1.5, 19, phi=30, E=20000), soil.Layer("Stiff clay", 3.0, 19, gamma_sat=20, phi=26, c=5, cu=90, E=25000),
                                             soil.Layer("Dense sand", 15, 20, gamma_sat=21, phi=36, E=60000)], water_depth=w),
    "soft clay": lambda w: soil.Profile([soil.Layer("Fill", 1.0, 18, phi=28, E=12000), soil.Layer("Soft clay", 6.0, 17, gamma_sat=18, phi=22, c=2, cu=30, E=6000),
                                        soil.Layer("Firm clay", 20, 19, gamma_sat=20, phi=25, c=5, cu=75, E=20000)], water_depth=w),
    "dense gravel": lambda w: soil.Profile([soil.Layer("Gravel", 30, 20, gamma_sat=22, phi=38, E=90000)], water_depth=w),
}


def scenario(rng):
    span = rng.choice([1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]); height = rng.choice([1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5])
    t = max(0.20, round(max(span, height) / rng.choice([8, 10, 12]) / 0.025) * 0.025)
    return dict(n_cells=rng.choice([1, 1, 2, 3, 4, 5, 6, 8]), barrel=rng.choice([6.0, 10.5, 18.0, 30.0, 60.0]), pivot=rng.choice(['centre', 'centre', 'inlet', 'outlet']), span=span, height=height, t_top=t, t_base=t + rng.choice([0, 0, 0.05]), t_wall=max(0.2, t - rng.choice([0, 0, 0.05])),
                fill=rng.choice([0.3, 0.6, 1.0, 1.5, 2.5, 4.0, 6.0]), hb=rng.choice([30.0, 37.5, 45.0]), toe=rng.choice([0, 0, 0.3, 0.6]),
                fck=rng.choice([25, 30, 35, 40]), fyk=rng.choice([460, 500]), cover=rng.choice([0.04, 0.05, 0.06]), exposure=rng.choice(["XC2", "XC4", "XD2"]),
                profile=rng.choice([None, None, "clay over sand", "soft clay", "dense gravel"]), water=rng.choice([None, None, 2.0, 5.0]),
                skew=rng.choice([90, 90, 60, 75, 105, 120]), flare=rng.choice([0, 15, 30, 45]), surcharge=rng.choice([10.0, 16.67, 20.0]))


GRID = [dict(n_cells=n, span=s, height=h, t_top=t, t_base=t, t_wall=t, fill=f, hb=37.5, toe=toe, fck=25, fyk=460, cover=0.05, exposure="XC2", profile=None,
             water=None, skew=90, flare=30, surcharge=16.67, barrel=10.5, pivot='centre')
        for n in (1, 2, 4, 6) for (s, h, t) in ((1.5, 1.5, 0.25), (2.0, 2.0, 0.25), (3.0, 2.5, 0.35), (4.0, 3.0, 0.45)) for f in (0.6, 1.0, 3.0) for toe in (0, 0.3)]


def build(sc):
    p = P(); p.n_cells = sc["n_cells"]; p.span = sc["span"]; p.height = sc["height"]; p.t_top = sc["t_top"]; p.t_base = sc["t_base"]
    p.t_wall = p.t_pier = sc["t_wall"]; p.fill = sc["fill"]; p.hb_units = sc["hb"]; p.hb_wheel = sc["hb"] * 10 / 4; p.toe = sc["toe"]
    p.fck = sc["fck"]; p.fyk = sc["fyk"]; p.cover = sc["cover"]; p.surcharge = sc["surcharge"]
    p.Ecm = ec2.Concrete(sc["fck"]).Ecm
    mk = PROFILES[sc["profile"]]; p.profile = mk(sc["water"]) if mk else None
    return p


def _dist_to_poly(pt, poly):
    best = 1e18; n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]; dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / L2))
        best = min(best, math.hypot(pt[0] - x1 - t * dx, pt[1] - y1 - t * dy))
    return best


def check_drawing(D, cover, fails, tag):
    """Every bar and dot lies in concrete with at least the cover (bar surface to concrete face)."""
    conc = [list(pts) for pts, closed, la, *_ in D.pl if la == "CBC_CONC"]
    outer = max(conc, key=lambda c: max(p[0] for p in c) - min(p[0] for p in c)); cells = [c for c in conc if c is not outer]
    po = Path(outer); pcs = [Path(c) for c in cells]
    def test(pt, dia, what):
        if not po.contains_point(pt): fails[f"drawing: {what} outside the concrete"] += 1; return
        if any(pc.contains_point(pt) for pc in pcs): fails[f"drawing: {what} inside a cell opening"] += 1; return
        clear = min(_dist_to_poly(pt, c) for c in conc) - dia / 2.0
        if clear < cover - 3.0: fails[f"drawing: {what} cover {max(0, round(clear / 5) * 5):.0f} < {cover:.0f} mm"] += 1
    for item in D.pl:
        if item[2] != "CBC_REBAR": continue
        pts = item[0]; dia = item[4] if len(item) > 4 and item[4] else 12.0
        for a, b in zip(pts, pts[1:]):
            L = math.dist(a, b); n = max(1, int(L / 40.0))
            for k in range(n + 1):
                test((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n), dia, f"bar {item[3]}")
    for x, y, d, _ in D.dots: test((x, y), d, "distribution bar")


def run_one(sc, fails, stats, dxf=False):
    p = build(sc); t0 = time.time()
    b = Box(p).analyse(); uls, sls = b.uls_combos(), b.sls_combos()
    # ---- statics
    u = b.combine_u({"SW": 1.0})
    applied = p.gamma_conc * (p.t_top * b.W_cl + p.t_base * (b.W_cl + 2 * b.toe_len) + sum(w["t"] * p.Hc for w in b.wall_chains))
    R = sum(b.fr.nodes[n].ky * u[3 * n + 1] for n in b.base_nodes)
    if abs(R - applied) > 1e-6 * max(1, applied): fails["statics: self weight not in equilibrium"] += 1
    for case in ("EH", "LS"):
        u = b.combine_u({case: 1.0}); R = sum(b.fr.nodes[n].ky * u[3 * n + 1] for n in b.base_nodes)
        want = p.surcharge * 2 * b.toe_len if case == "LS" else 0.0        # the surcharge also stands on the toes
        if abs(R - want) > 1e-6 * applied: fails[f"statics: case {case} vertical reaction is not the load applied"] += 1
    k = b.hb_keys[len(b.hb_keys) // 4]; u = b.combine_u({k: 1.0}); R = sum(b.fr.nodes[n].ky * u[3 * n + 1] for n in b.base_nodes)
    if not (0 < R <= p.hb_wheel * 2 * (1 + 1e-9)): fails["statics: HB reaction not between 0 and the axle load"] += 1
    # symmetric loads -> symmetric top slab diagram
    F = b.combine_F({"SW": 1.35, "EV": 1.35, "EH": 1.35, "LS": 1.35}); dg = b.diagram(b.members["top"], F)
    ms = [m for _, m, _, _ in dg]
    if max(abs(x - y) for x, y in zip(ms, ms[::-1])) > 1e-4 * max(1.0, max(abs(m) for m in ms)): fails["statics: symmetric loading gives an unsymmetric diagram"] += 1
    if min(b.bearing(c)[1] for c in sls) < -1e-6 and p.toe <= 0: stats["uplift at an SLS combination"] += 1
    # ---- design
    Rz = design.design(b, fck=sc["fck"], fyk=sc["fyk"], exposure=sc["exposure"], cover=sc["cover"])
    thick = {"top": p.t_top, "base": p.t_base, "walls": p.t_wall, "piers": p.t_pier}
    for (m, fc), f in Rz.faces.items():
        thin = any("too thin" in n for n in f.notes)
        if f.As < max(f.As_req, f.As_min) - 1e-6 and not thin: fails["design: steel below requirement without a flag"] += 1
        if f.spacing > f.s_max + 1e-6: fails["design: spacing above the code maximum"] += 1
        if f.spacing - f.dia < f.s_clear_min - 1e-6: fails["design: clear spacing below the code minimum"] += 1
        if f.wk > 0.3 + 1e-9 and not thin: fails["design: crack width above the limit without a flag"] += 1
        if f.As > ec2.As_max(1000, thick[m] * 1000) + 1e-6: fails["design: steel above 4 %"] += 1
        if thin: stats["section flagged too thin"] += 1
    for m, s in Rz.shear.items():
        # the ground reaction acts at the spring nodes, so base shear can creep up ~1 % between the face and the first node
        if s.V_d > s.V_face * (1.02 if m == "base" else 1.001) + 1e-3: fails["design: shear at d exceeds shear at the face"] += 1
        if s.util > 1.0 + 1e-9:
            if s.links:
                stats["shear resolved with links"] += 1
                if not s.links["ok"]: stats["links provided but the strut / link capacity is exceeded (flagged)"] += 1
                if s.links["s_long"] > 0.75 * Rz.faces[(m, "outer")].d + 30: fails["design: link spacing above 0.75 d"] += 1
            elif "FAILS" in s.note: stats["shear failure flagged (member too thin for links)"] += 1
            else: fails["design: shear failure neither resolved nor flagged"] += 1
        elif "more tension steel" in s.note: stats["shear resolved with more tension steel"] += 1
    mu = bars.multiples(Rz, (p.height + p.t_top + p.t_base) * 1000); am, lm = mu["anch_mult"], mu["lap_mult"]
    inner = (p.n_cells * p.span + (p.n_cells - 1) * p.t_pier) * 1000
    # ---- drawing and schedule
    F_ = Rz.faces; out = max((F_[(m, "outer")] for m in ("top", "base", "walls")), key=lambda f: f.As)
    Q = dict(N_CELLS=p.n_cells, SPAN_W=p.span * 1000, SPAN_H=p.height * 1000, T_TOP=p.t_top * 1000, T_BASE=p.t_base * 1000, T_WALL=p.t_wall * 1000, T_INWALL=p.t_pier * 1000,
             COVER=p.cover * 1000, TOE=p.toe * 1000, LAP_MULT=lm, ANCH_MULT=am, OUT_D=out.dia, OUT_S=out.spacing,
             TOPIN_D=F_[("top", "inner")].dia, TOPIN_S=F_[("top", "inner")].spacing, BOTIN_D=F_[("base", "inner")].dia, BOTIN_S=F_[("base", "inner")].spacing,
             WALLIN_D=F_[("walls", "inner")].dia, WALLIN_S=F_[("walls", "inner")].spacing, DIST_D=Rz.dist["top"]["dia"], DIST_S=Rz.dist["top"]["spacing"])
    if p.n_cells > 1: Q.update(PIER_D=F_[("piers", "inner")].dia, PIER_S=F_[("piers", "inner")].spacing)
    D = section_bb.build(Q); sched = bars.schedule(D, section_bb.complete(Q), sc["barrel"] * 1000, sc["skew"])
    if max(r["length"] for r in sched) > 12000 + 1e-6: fails["bars: a scheduled bar is longer than the 12 m stock"] += 1
    if any(bars.plen(pc["pts"]) > 12000 + 1e-6 for pc in D.pieces): fails["bars: a drawn piece is longer than the 12 m stock"] += 1
    if any(int(r["dia"]) not in bars.SIZES for r in sched): fails["bars: a size that is not supplied"] += 1
    for x in D.laps:
        for y in D.laps:
            if x["mark"] == y["mark"] and x["fam"] != y["fam"] and abs(x["at"][0] - y["at"][0]) < 1.3 * x["l0"] - 1e-6: fails["bars: laps of alternate bars closer than 1.3 l0"] += 1
    if D.laps: stats["bars: transverse bars cut at the stock length and lapped"] += 1
    if any(pc["lap"] and not pc["lap"]["preferred"] for pc in D.pieces): stats["bars: a lap outside the low-stress zones (flagged)"] += 1
    if mu["wall"].get("wall_bar"): stats["bars: tall wall, U-bars with short legs and a lapped wall bar"] += 1
    if any(pc["mark"] == "12" for pc in D.pieces): stats["bars: toe hairpin too tight for the main bar, separate U-cap"] += 1
    if not mu["wall"]["staggered"]: stats["bars: wall too short to stagger the U-bar laps, 100 % lap length used"] += 1
    site = dict(toe=p.toe * 1000, skew=sc["skew"], flare=sc["flare"], apron=4750.0, inner_width=inner, outer_width=p.W_ext * 1000, barrel_length=sc["barrel"] * 1000, joint_spacing=15000.0,
                anch_mult=am, lap_mult=lm, pivot=sc["pivot"], schedule=sched, wall_lap=mu["wall"])
    rows = checks.run(b, Rz, site, p.profile)
    for r in rows:
        if not r["ok"]: stats[f"check not satisfied: {r['group']} - {r['clause']}"] += 1
    check_drawing(D, p.cover * 1000, fails, "")
    for w in D.warnings: fails["drawing: " + w.split(":")[0] + " not resolved"] += 1; break
    for item in D.pl:
        if item[2] == "CBC_REBAR" and any(math.dist(a, c) < 1e-6 for a, c in zip(item[0], item[0][1:])): fails["drawing: zero-length bar segment"] += 1
    if dxf:
        import ezdxf
        path = os.path.join(tempfile.gettempdir(), "scenario.dxf"); section_bb.to_dxf(D, path)
        if len(ezdxf.readfile(path).audit().errors): fails["drawing: DXF audit errors"] += 1
    # ---- skew: road horizontal, barrel turned about the pivot, wing wall ends fixed on the apron edges
    Wo = p.W_ext * 1000; Lb = sc["barrel"] * 1000; g = skew.layout(Wo, Lb, 4750.0, sc["flare"], sc["skew"], sc["pivot"]); sq = skew.layout(Wo, Lb, 4750.0, sc["flare"], 90, sc["pivot"])
    sn = math.sin(math.radians(sc["skew"])); o = g["outline"]
    if abs(math.dist(o[0], o[3]) - Lb / sn) > 1e-6 * Lb: fails["skew: barrel wall is not L / sin(skew)"] += 1
    if any(abs(q[1]) - Lb / 2 > 1e-6 for q in o): fails["skew: barrel end not parallel to the road"] += 1
    for en in ("inlet", "outlet"):
        for sd in ("left", "right"):
            w = g["ends"][en]["walls"][sd]
            if math.dist(w["end"], sq["ends"][en]["walls"][sd]["end"]) > 1e-6: fails["skew: wing wall end moved off the apron edge"] += 1
            if abs(w["length"] - math.dist(w["start"], w["end"])) > 1e-6: fails["skew: wing wall length is not its plan length"] += 1
    m = skew.layout(Wo, Lb, 4750.0, sc["flare"], 180 - sc["skew"], sc["pivot"])
    if abs(m["ends"]["inlet"]["walls"]["left"]["length"] - g["ends"]["inlet"]["walls"]["right"]["length"]) > 1e-6: fails["skew: mirror crossing does not swap the walls"] += 1
    if not g["ok"]: stats["skew: a barrel corner slides past a wing wall end (flagged)"] += 1
    stats["_time"] += time.time() - t0
    return Rz.max_util()[0]


def main(n_random=150, seed=20261119):
    rng = random.Random(seed); cases = list(GRID) + [scenario(rng) for _ in range(n_random)]
    fails = collections.Counter(); stats = collections.Counter(); crashed = []; utils = []
    for i, sc in enumerate(cases):
        try:
            utils.append(run_one(sc, fails, stats, dxf=(i % 12 == 0)))
        except Exception as ex:                                # a crash is a failure of the software, with the case that caused it
            crashed.append((type(ex).__name__ + ": " + str(ex)[:120], {k: v for k, v in sc.items()}))
    t = stats.pop("_time", 0.0)
    print(f"{len(cases)} scenarios ({len(GRID)} grid + {n_random} random), {t:.0f} s")
    print(f"crashes: {len(crashed)}")
    seen = collections.Counter(c[0] for c in crashed)
    for msg, k in seen.most_common(8): print(f"   {k:4d} x {msg}")
    for msg, sc in crashed[:3]: print("      e.g.", sc)
    print(f"invariant violations: {sum(fails.values())} in {len(fails)} kinds")
    for kdesc, k in fails.most_common(25): print(f"   {k:5d} x {kdesc}")
    print("outcomes (expected behaviour, counted):")
    for kdesc, k in stats.most_common(30): print(f"   {k:5d} x {kdesc}")
    if utils: print(f"utilisation: min {min(utils):.2f}  median {sorted(utils)[len(utils)//2]:.2f}  max {max(utils):.2f}")
    return len(crashed), sum(fails.values())


if __name__ == "__main__":
    c, f = main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
    sys.exit(1 if (c or f) else 0)
