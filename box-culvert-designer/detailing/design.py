"""
Member design of the box to EN 1992-1-1, from the frame analysis.

For each member (top slab, base slab, outer walls, pier walls) and each face:
  flexure (6.1) -> minimum steel (9.2.1.1) -> spacing limits (8.2, 9.3.1.1, 9.6) -> crack width (7.3.4)
then shear at d from the support face (6.2.1(8), 6.2.2).  A shear failure is resolved the way a designer
would: more tension steel first (it raises VRd,c), then links (6.2.3) where the member is deep enough.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from . import ec2

NAMES = {"top": "Top slab", "base": "Base slab", "walls": "Outer walls", "piers": "Inner (pier) walls"}


@dataclass
class Face:
    member: str; face: str            # 'inner' / 'outer'
    M_uls: float; M_sls: float        # kNm/m
    d: float; As_req: float; As_min: float
    dia: int; spacing: int; As: float
    wk: float; sigma_s: float
    s_max: float; s_clear_min: float
    util_M: float; util_wk: float
    notes: list = field(default_factory=list)


@dataclass
class Shear:
    member: str; V_d: float; V_face: float; VRd_c: float; util: float
    links: dict | None = None          # {'dia','legs_per_m','s_long','s_trans','Asw_s','VRd_s','VRd_max','extent'}
    note: str = ""


@dataclass
class Result:
    faces: dict; shear: dict; dist: dict; cover: dict; lengths: dict
    params: dict
    def max_util(self):
        u = [(f.util_M, f"Flexure - {NAMES[f.member]} {f.face} face") for f in self.faces.values()]
        u += [(f.util_wk, f"Crack width - {NAMES[f.member]} {f.face} face") for f in self.faces.values()]
        u += [(s.util if not s.links else s.V_d / max(s.links["VRd_s"], 1e-9), f"Shear - {NAMES[s.member]} at d") for s in self.shear.values()]
        return max(u)


def _face(conc, fyk, member, face, M_uls, M_sls, h, cover, wk_lim, is_wall, dist_dia, prefer=None):
    b = 1000.0
    smax = ec2.max_spacing_wall(h) if is_wall else ec2.max_spacing_slab(h, principal=True, concentrated=True)
    best = None; notes = []
    for dia in (12, 16, 20, 25, 32):
        if prefer and dia < prefer: continue
        d = h - cover - dia / 2.0
        fl = ec2.flexure(conc, fyk, M_uls * 1e6, b, d)
        As_min = ec2.As_min_flexure(conc, fyk, b, d)
        if is_wall: As_min = max(As_min, ec2.wall_vertical_limits(h)[0] / 2.0)       # 9.6.2: half the wall minimum on each face
        need = max(fl["As"], As_min)
        clear = ec2.min_clear_spacing(dia, conc.dg)
        for sp in (250, 225, 200, 175, 150, 125, 100):
            if sp > smax or sp - dia < clear: continue
            As = ec2.As_per_m(dia, sp)
            if As < need: continue
            cw = ec2.crack_width(conc, M_sls * 1e6, b, h, d, As, dia, sp, cover) if M_sls > 0 else dict(wk=0.0, sigma_s=0.0)
            if cw["wk"] > wk_lim or cw["sigma_s"] > 0.8 * fyk: continue
            cand = Face(member, face, M_uls, M_sls, d, fl["As"], As_min, dia, sp, As, cw["wk"], cw["sigma_s"], smax, clear,
                        need / As, cw["wk"] / wk_lim if wk_lim else 0.0)
            if best is None or cand.As < best.As - 1e-9: best = cand
            break
    if best is None:                                               # nothing satisfies: report the heaviest arrangement
        dia, sp = 32, 100; d = h - cover - dia / 2.0; As = ec2.As_per_m(dia, sp)
        fl = ec2.flexure(conc, fyk, M_uls * 1e6, b, d); cw = ec2.crack_width(conc, M_sls * 1e6, b, h, d, As, dia, sp, cover)
        best = Face(member, face, M_uls, M_sls, d, fl["As"], ec2.As_min_flexure(conc, fyk, b, d), dia, sp, As, cw["wk"], cw["sigma_s"], smax,
                    ec2.min_clear_spacing(dia, conc.dg), fl["As"] / As, cw["wk"] / wk_lim, ["section too thin: increase the thickness"])
    return best


def design(box, fck=25.0, fyk=460.0, exposure="XC2", wk_lim=0.3, dg=20.0, cover=None, dist=(12, 200), link_dia=10) -> Result:
    """box: an analysed engine.Box.  Returns the reinforcement of every member with its code checks."""
    p = box.p; conc = ec2.Concrete(fck, dg=dg)
    cov = ec2.nominal_cover(exposure, 16.0, cast_against="blinding")
    c = cover * 1000.0 if cover else max(cov["cnom"], 40.0)
    uls, sls = box.uls_combos(), box.sls_combos()
    thick = {"top": p.t_top * 1000, "base": p.t_base * 1000, "walls": p.t_wall * 1000, "piers": p.t_pier * 1000}
    faces = {}; shear = {}
    members = ["top", "base", "walls"] + (["piers"] if p.n_cells > 1 else [])
    for m in members:
        h = thick[m]; d0 = (h - c - 8.0) / 1000.0
        au = box.design_actions(m, uls, d0); asl = box.design_actions(m, sls, d0)
        wall = m in ("walls", "piers")
        fi = _face(conc, fyk, m, "inner", au["M_in"], asl["M_in"], h, c, wk_lim, wall, dist[0])
        fo = _face(conc, fyk, m, "outer", au["M_out"], asl["M_out"], h, c, wk_lim, wall, dist[0])
        if m == "piers":                                     # both faces alike
            hv = fi if fi.As >= fo.As else fo; fi = fo = hv
        # ---- shear at d from the support face; tension steel there is on the face the support moment puts in tension
        def vrd(f): return ec2.VRd_c(conc, 1000.0, f.d, f.As) / 1e3
        sup = fo if m in ("top", "walls") else fi            # top slab hogs over the walls; base slab hogs upward (top face)
        if m == "base": sup = fi
        d = sup.d / 1000.0; au = box.design_actions(m, uls, d)
        V = au["V_d"]; note = ""; links = None
        if V > vrd(sup):                                     # 1) more tension steel
            for dia, sp in ((sup.dia, 150), (sup.dia, 125), (sup.dia, 100), (20, 150), (20, 125), (20, 100), (25, 125), (25, 100)):
                if dia < sup.dia or sp > sup.spacing or sp - dia < sup.s_clear_min: continue
                As = ec2.As_per_m(dia, sp); dd = thick[m] - c - dia / 2.0
                if ec2.VRd_c(conc, 1000.0, dd, As) / 1e3 >= V and As <= ec2.As_max(1000.0, thick[m]):
                    cw = ec2.crack_width(conc, sup.M_sls * 1e6, 1000.0, thick[m], dd, As, dia, sp, c) if sup.M_sls > 0 else dict(wk=0.0, sigma_s=0.0)
                    new = Face(m, sup.face, sup.M_uls, sup.M_sls, dd, sup.As_req, sup.As_min, dia, sp, As, cw["wk"], cw["sigma_s"], sup.s_max,
                               sup.s_clear_min, max(sup.As_req, sup.As_min) / As, cw["wk"] / wk_lim, ["tension steel increased for shear (6.2.2)"])
                    if sup is fi: fi = new
                    if sup is fo: fo = new
                    if m == "piers": fi = fo = new
                    sup = new; note = "resolved by more tension steel"; break
        if V > vrd(sup):                                     # 2) links
            if ec2.slab_may_have_links(thick[m]) or wall:
                L = ec2.shear_links(conc, fyk, V * 1e3, 1000.0, sup.d)
                s_long = max(75, int(min(L["s_long_max"], 200) // 25 * 25)); s_tr = max(100, int(min(L["s_trans_max"], 400) // 50 * 50))
                legs_per_m = 1000.0 / s_tr; need = L["Asw_s"] * s_long            # mm2 per metre width per row
                dia = next((dd for dd in (8, 10, 12, 16) if dd >= link_dia - 2 and legs_per_m * ec2.area(dd) >= need), 16)
                Asw_s = legs_per_m * ec2.area(dia) / s_long
                VRd_s = Asw_s * L["z"] * ec2.fyd(fyk) * L["cot_theta"] / 1e3
                # links are needed where V > VRd,c: distance from the face along the span
                links = dict(dia=dia, s_long=s_long, s_trans=s_tr, legs_per_m=legs_per_m, Asw_s=Asw_s, VRd_s=VRd_s, VRd_max=L["VRd_max"] / 1e3,
                             cot_theta=L["cot_theta"], ok=L["ok_strut"] and VRd_s >= V)
                note = "links provided (6.2.3)"
            else:
                note = "FAILS: slab thinner than 200 mm cannot take links (9.3.2(1)) - increase the thickness"
        faces[(m, "inner")] = fi; faces[(m, "outer")] = fo
        shear[m] = Shear(m, V, au["V_face"], vrd(sup), V / vrd(sup), links, note)
    # ---- distribution steel (9.3.1.1(2), 9.6.3) and lengths
    dist_out = {}
    for m in members:
        h = thick[m]; main = max(faces[(m, "inner")].As, faces[(m, "outer")].As)
        need = ec2.As_secondary_min(main)
        if m in ("walls", "piers"): need = max(need, ec2.wall_horizontal_min(faces[(m, "inner")].As + faces[(m, "outer")].As, h) / 2.0)
        smax = ec2.max_spacing_wall(h, vertical=False) if m in ("walls", "piers") else ec2.max_spacing_slab(h, principal=False)
        dia, sp, As = ec2.choose_bars(need, min(smax, 250), bars=(10, 12, 16), prefer_dia=dist[0])
        dist_out[m] = dict(dia=dia, spacing=sp, As=As, As_req=need, s_max=smax)
    lengths = {}
    for dia in sorted({f.dia for f in faces.values()} | {d["dia"] for d in dist_out.values()} | {10, 12, 16}):
        sig = ec2.fyd(fyk)
        cd = min(c, 50.0)
        lengths[dia] = dict(anchorage=ec2.anchorage_length(conc, dia, sig, cd=cd), anchorage_bent=ec2.anchorage_length(conc, dia, sig, bent=True, cd=cd),
                            lap50=ec2.lap_length(conc, dia, sig, 50.0, cd=cd), lap100=ec2.lap_length(conc, dia, sig, 100.0, cd=cd),
                            mandrel=ec2.mandrel_diameter(dia), former_radius=ec2.bs8666_former_radius(dia), end_projection=ec2.bs8666_min_end_projection(dia))
    return Result(faces, shear, dist_out, dict(cov, used=c, exposure=exposure), lengths,
                  dict(fck=fck, fyk=fyk, wk_lim=wk_lim, dg=dg, conc=conc))
