"""Code-compliance schedule: every rule that governs the design and detailing, with value, limit and verdict."""
from __future__ import annotations
import math
from . import ec2, skew as skew_mod
from .design import NAMES


def row(group, clause, item, value, limit, ok, note=""):
    return dict(group=group, clause=clause, item=item, value=value, limit=limit, ok=ok, note=note)


def run(box, R, site=None, profile=None) -> list:
    """box: analysed engine.Box; R: design.Result; site: dict(toe, skew, flare, apron, barrel_length, joint_spacing,
    stock, lap_mult, anch_mult); profile: soil.Profile or None."""
    p = box.p; site = site or {}; conc = R.params["conc"]; fyk = R.params["fyk"]; out = []
    thick = {"top": p.t_top * 1000, "base": p.t_base * 1000, "walls": p.t_wall * 1000, "piers": p.t_pier * 1000}
    c = R.cover
    out.append(row("Durability", "4.4.1", f"Nominal cover, exposure {c['exposure']}", f"{c['used']:.0f} mm", f">= {c['cnom']:.0f} mm", c["used"] >= c["cnom"] - 1e-6,
                   f"c_min,dur {c['cmin_dur']:.0f} + dc_dev 10; cast on blinding >= 40"))
    for (m, fc), f in R.faces.items():
        if m == "piers" and fc == "outer": continue
        nm = f"{NAMES[m]}, {fc if m != 'piers' else 'each'} face  T{f.dia}-{f.spacing}"
        h = thick[m]
        out.append(row("Flexure", "6.1", nm, f"As {f.As:.0f} mm2/m", f">= {f.As_req:.0f} (M {f.M_uls:.1f} kNm/m)", f.As >= f.As_req - 1e-6))
        out.append(row("Minimum steel", "9.2.1.1 / 9.6.2", nm, f"As {f.As:.0f} mm2/m", f">= {f.As_min:.0f}", f.As >= f.As_min - 1e-6))
        out.append(row("Maximum steel", "9.2.1.1(3)", nm, f"{100 * f.As / (1000 * h):.2f} %", "<= 4 %", f.As <= ec2.As_max(1000, h)))
        out.append(row("Bar spacing", "8.2(2)", nm, f"clear {f.spacing - f.dia:.0f} mm", f">= {f.s_clear_min:.0f} mm", f.spacing - f.dia >= f.s_clear_min - 1e-6,
                       f"max(dia, dg + 5, 20), dg = {conc.dg:.0f}"))
        out.append(row("Bar spacing", "9.3.1.1(3) / 9.6.2(3)", nm, f"{f.spacing} mm c/c", f"<= {f.s_max:.0f} mm", f.spacing <= f.s_max + 1e-6))
        out.append(row("Cracking", "7.3.4", nm, f"wk {f.wk:.2f} mm", f"<= {R.params['wk_lim']:.2f} mm", f.wk <= R.params["wk_lim"] + 1e-9, f"M_sls {f.M_sls:.1f} kNm/m"))
        out.append(row("Stress", "7.2(5)", nm, f"steel {f.sigma_s:.0f} MPa", f"<= {0.8 * fyk:.0f} MPa", f.sigma_s <= 0.8 * fyk + 1e-6))
    for m, d in R.dist.items():
        out.append(row("Distribution steel", "9.3.1.1(2) / 9.6.3", f"{NAMES[m]}  T{d['dia']}-{d['spacing']}", f"As {d['As']:.0f} mm2/m", f">= {d['As_req']:.0f}; s <= {d['s_max']:.0f}",
                       d["As"] >= d["As_req"] - 1e-6 and d["spacing"] <= d["s_max"] + 1e-6, "20 % of the principal steel; walls also 25 % of vertical and 0.1 % Ac"))
    for m, s in R.shear.items():
        if s.links:
            L = s.links
            out.append(row("Shear", "6.2.3 / 9.3.2", f"{NAMES[m]} - links T{L['dia']} at {L['s_long']} x {L['s_trans']}", f"VEd {s.V_d:.1f} kN/m",
                           f"<= VRd,s {L['VRd_s']:.1f}; VRd,max {L['VRd_max']:.1f}", L["ok"], f"VRd,c {s.VRd_c:.1f} exceeded; cot(theta) {L['cot_theta']:.1f}"))
        else:
            out.append(row("Shear", "6.2.1(8) / 6.2.2", f"{NAMES[m]} at d from the support face", f"VEd {s.V_d:.1f} kN/m", f"<= VRd,c {s.VRd_c:.1f}", s.util <= 1.0 + 1e-9,
                           s.note or f"at the face {s.V_face:.1f} kN/m"))
    # ---- anchorage and laps actually used on the drawings
    main = max(f.dia for f in R.faces.values())
    for dia in sorted(R.lengths):
        Ln = R.lengths[dia]
        am = site.get("anch_mult"); lm = site.get("lap_mult")
        if am: out.append(row("Anchorage", "8.4.4", f"T{dia} straight anchorage on the drawings", f"{am:.0f} dia = {am * dia:.0f} mm", f">= lbd {Ln['anchorage']['lbd']:.0f} mm",
                              am * dia >= Ln["anchorage"]["lbd"] - 1e-6, f"lb,rqd {Ln['anchorage']['lb_rqd']:.0f}, alpha2 {Ln['anchorage']['alpha2']:.2f}"))
        if lm: out.append(row("Laps", "8.7.3", f"T{dia} lap, 50 % of bars lapped at a section", f"{lm:.0f} dia = {lm * dia:.0f} mm", f">= l0 {Ln['lap50']['l0']:.0f} mm",
                              lm * dia >= Ln["lap50"]["l0"] - 1e-6, f"alpha6 {Ln['lap50']['alpha6']:.2f}; 100 % lapped would need {Ln['lap100']['l0']:.0f}"))
        out.append(row("Bends", "8.3 / BS 8666", f"T{dia} bends", f"former radius {Ln['former_radius']:.0f} mm", f"mandrel >= {Ln['mandrel']:.0f} mm dia",
                       2 * Ln["former_radius"] >= Ln["mandrel"] - 1e-6, f"minimum end projection {Ln['end_projection']:.0f} mm"))
    # staggered laps of the outer U-bars in the walls
    lm = site.get("lap_mult")
    if lm:
        d1 = max(R.faces[("top", "outer")].dia, R.faces[("base", "outer")].dia, R.faces[("walls", "outer")].dia); lap = lm * d1
        htot = (p.height + p.t_top + p.t_base) * 1000; cv = R.cover["used"]
        stg = max(0.0, min(0.65 * lap, (htot - 2 * cv) / 2 - lap / 2 - 100, 2700.0 - ((htot - 2 * cv) / 2 + lap / 2)))
        wl = site.get("wall_lap") or {}
        if wl.get("wall_bar"):
            out.append(row("Bars as supplied", "BS 8666", "Outer walls: U-bar legs would exceed the transport width", "short legs + straight wall bar (mark 11)", "bent shapes <= 2750 mm", wl.get("fits", True),
                           "wall bar laps with the top and the base legs; " + ("alternate laps 1.3 l0 apart" if wl["staggered"] else "all lapped at one section, 100 % lap length")))
        elif 2 * stg >= 1.3 * lap - 1e-6:
            out.append(row("Laps", "8.7.2(3)", "Outer wall bars: centres of adjacent laps", f"{2 * stg:.0f} mm apart", f">= 1.3 l0 = {1.3 * lap:.0f} mm", True,
                           "alternate bars reversed so that not more than 50 % lap at one section"))
        else:                                       # wall too short to stagger: all bars lap at one section, lap at the 100 % value
            l100 = R.lengths[d1]["lap100"]["l0"]; room = htot - 2 * cv - 2 * ec2.bs8666_min_end_projection(d1)
            out.append(row("Laps", "8.7.3 Table 8.3", "Outer wall bars: wall too short to stagger the laps, all lapped at one section", f"lap {lap:.0f} mm", f">= l0 (100 %) {l100:.0f} mm, <= {room:.0f} mm available",
                           lap >= l100 - 1e-6 and lap <= room + 1e-6, "alpha6 = 1.5; transverse bars across the lap zone per 8.7.4.1"))
        out.append(row("Laps", "8.7.2(3)", "Clear distance between the two bars of a lap", "bars in contact", f"<= {max(4 * d1, 50):.0f} mm", True))
    # ---- stock length
    stock = site.get("stock", 12000.0)
    if site.get("schedule"):
        from . import bars as bars_mod
        for item, value, limit, ok, note in bars_mod.limits(site["schedule"], R.params["fyk"], stock):
            out.append(row("Bars as supplied", "BS 4449 / BS 8666" if "lap centres" not in item else "8.7.2(3)", item, value, limit, ok, note))
    else:
        wext = p.W_ext * 1000 + 2 * site.get("toe", 0.0)
        run_len = wext + (p.height + p.t_top + p.t_base) * 1000
        lay = ec2.lap_layout(run_len, (lm or 50) * main, stock)
        out.append(row("Bar lengths", "practice", "Longest transverse bar (developed)", f"{run_len:.0f} mm", f"<= stock {stock:.0f} mm, else lapped", True,
                       "no lap needed" if lay["n_laps"] == 0 else f"{lay['n_laps']} lap(s) per bar, families staggered {lay['stagger']:.0f} mm"))
    # ---- free edges, corners
    if site.get("toe", 0) > 0:
        leg = max(2 * thick["base"], (site.get("anch_mult") or 40) * main)
        out.append(row("Free edges", "9.3.1.4", "Toe edges: bottom bars capped (U) round the edge", f"leg {leg:.0f} mm", f">= 2h = {2 * thick['base']:.0f} mm", leg >= 2 * thick["base"] - 1e-6))
    out.append(row("Free edges", "9.3.1.4", "Barrel ends: slab edges closed with U-bars and edge bars", "U-caps scheduled", "required", True, "top and base slab at both ends"))
    for m in ("top", "base"):
        f = R.faces[(m, "outer")]
        fcn = ec2.frame_corner(f.As, 1000, thick[m], opening=False)
        out.append(row("Corners", "Annex J.2", f"{NAMES[m]} / outer wall corner (closing moment)", f"rho {100 * fcn['rho']:.2f} %", "detail", True, fcn["detail"]))
    # ---- joints and waterstops
    Lb = site.get("barrel_length"); js = site.get("joint_spacing")
    if Lb and js:
        nseg = max(1, math.ceil(Lb / js)); nj = nseg - 1
        perim = 2 * (p.W_ext * 1000 + (p.height + p.t_top + p.t_base) * 1000) / 1000.0
        out.append(row("Joints", "designer's rule", f"Movement joints at <= {js / 1000:.1f} m", f"{nseg} segment(s) of {Lb / nseg / 1000:.2f} m", f"{nj} movement joint(s)", True,
                       "EN 1992-1-1 2.3.3(3) allows 30 m between joints in buildings; buried culverts are normally jointed closer"))
        out.append(row("Joints", "practice", "Waterstops: every movement joint and the barrel / apron joints", f"{(nj + 2) * perim:.1f} m", "centre-bulb PVC, continuous", True,
                       f"{perim:.1f} m per joint round the section"))
    # ---- skew
    sk = site.get("skew", 90.0)
    if abs(sk - 90.0) > 1e-6 and site.get("apron"):
        g = skew_mod.layout(site.get("outer_width", p.W_ext * 1000), site.get("barrel_length", 10500.0), site["apron"], site.get("flare", 30.0), sk, site.get("pivot", "centre"))
        ws = [g["ends"][e]["walls"][s] for e in ("inlet", "outlet") for s in ("left", "right")]
        out.append(row("Skew", "geometry", f"Barrel at {sk:g} deg skew, pivot at the {g['pivot']}", f"walls {g['wall_length']:.0f} mm, end faces {g['end_face_length']:.0f} mm", "ends parallel to the road", True,
                       "walls stretched by 1 / sin(skew); the cross-section normal to the axis is unchanged"))
        out.append(row("Skew", "geometry", "Wing walls (inlet L / R, outlet L / R)", " / ".join(f"{w['length']:.0f}" for w in ws) + " mm", "every wall still flares outward", g["ok"],
                       "ends stay on the apron edges; each wall detailed for its own length" if g["ok"] else next(w["reason"] for w in ws if not w["ok"])))
        se = skew_mod.slab_effects(p.span * 1000, sk)
        out.append(row("Skew", "analysis", "Slab end zones", f"skew span {se['skew_span']:.0f} mm", f"As x {se['As_factor_end_zone']:.2f} in the end zones", True, se["treatment"]))
    # ---- ground
    if profile is not None:
        q_uls = max(box.bearing(cmb)[0] for cmb in box.uls_combos()); q_sls = max(box.bearing(cmb)[0] for cmb in box.sls_combos())
        b = profile.bearing(q_uls, box.base_width, box.founding_depth)
        g = b["governing"]
        out.append(row("Ground", "EN 1997-1 Annex D", f"Bearing resistance ({g['governs']}, {g['layer']})", f"q_Ed {g['q_ed']:.0f} kPa", f"<= q_Rd {g['qRd']:.0f} kPa", b["ok"],
                       f"checked at the base and on each layer within 2B; gamma_R 1.4"))
        s = profile.settlement(q_sls - profile.sigma_v(box.founding_depth)[0], box.base_width, box.founding_depth)
        out.append(row("Ground", "EN 1997-1 6.6", "Settlement under the net SLS pressure", f"{1000 * s['s']:.0f} mm", "<= 50 mm (typical limit)", 1000 * s["s"] <= 50.0,
                       f"net {q_sls - profile.sigma_v(box.founding_depth)[0]:.0f} kPa; ks used {box.ks:.0f} kN/m3"))
        gmin = min(box.bearing(cmb)[2] for cmb in box.sls_combos())
        out.append(row("Ground", "frame model", "No tension in the ground springs", f"least reaction {gmin:.1f} kN", ">= 0", gmin >= -1e-6))
    return out
