"""
Design and detailing rules of EN 1992-1-1:2004 + A1:2014 (recommended values; a National Annex may differ).

Every function names the clause it implements.  Units: N, mm, MPa unless stated.
Bars are scheduled to BS 8666:2020; steel to BS 4449 (B460 / B500).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

ES = 200_000.0
GAMMA_C = 1.5
GAMMA_S = 1.15
STOCK_BARS = (8, 10, 12, 16, 20, 25, 32, 40)


# --------------------------------------------------------------------------- materials (3.1, 3.2)
@dataclass
class Concrete:
    fck: float
    alpha_cc: float = 0.85          # 3.1.6(1); 0.85 used for bridges / long-term effects
    alpha_ct: float = 1.0
    dg: float = 20.0                # maximum aggregate size

    @property
    def fcm(self): return self.fck + 8.0
    @property
    def fctm(self): return 0.30 * self.fck ** (2.0 / 3.0) if self.fck <= 50 else 2.12 * math.log(1 + self.fcm / 10.0)   # Table 3.1
    @property
    def fctk005(self): return 0.7 * self.fctm
    @property
    def fcd(self): return self.alpha_cc * self.fck / GAMMA_C
    @property
    def fctd(self): return self.alpha_ct * self.fctk005 / GAMMA_C
    @property
    def Ecm(self): return 22_000.0 * (self.fcm / 10.0) ** 0.3


def fyd(fyk): return fyk / GAMMA_S


def area(dia): return math.pi * dia * dia / 4.0


def As_per_m(dia, spacing): return area(dia) * 1000.0 / spacing


# --------------------------------------------------------------------------- cover (4.4.1)
CMIN_DUR_S4 = {"X0": 10, "XC1": 15, "XC2": 25, "XC3": 25, "XC4": 30, "XD1": 35, "XS1": 35, "XD2": 40, "XS2": 40, "XD3": 45, "XS3": 45}


def nominal_cover(exposure: str, dia: float, dcdev: float = 10.0, cast_against: str | None = None) -> dict:
    """4.4.1.1-4.4.1.3: c_nom = c_min + dc_dev, c_min = max(c_min,b ; c_min,dur ; 10).
    cast_against: 'blinding' -> c_nom >= 40 mm, 'soil' -> c_nom >= 75 mm (4.4.1.3(4), k1 / k2)."""
    cmin_b = dia
    cmin_dur = CMIN_DUR_S4[exposure.upper()]
    cmin = max(cmin_b, cmin_dur, 10.0)
    cnom = cmin + dcdev
    if cast_against == "blinding": cnom = max(cnom, 40.0)
    if cast_against == "soil": cnom = max(cnom, 75.0)
    return dict(cmin_b=cmin_b, cmin_dur=cmin_dur, cmin=cmin, cnom=cnom)


# --------------------------------------------------------------------------- spacing of bars (8.2, 9.3.1.1, 9.6)
def min_clear_spacing(dia: float, dg: float = 20.0) -> float:
    """8.2(2): clear distance >= max(k1 x dia, dg + k2, 20 mm), k1 = 1, k2 = 5 mm."""
    return max(dia, dg + 5.0, 20.0)


def max_spacing_slab(h: float, principal=True, concentrated=False) -> float:
    """9.3.1.1(3): principal 3h <= 400 (2h <= 250 at concentrated loads / maximum moment); secondary 3.5h <= 450 (3h <= 400)."""
    if principal: return min(2 * h, 250.0) if concentrated else min(3 * h, 400.0)
    return min(3 * h, 400.0) if concentrated else min(3.5 * h, 450.0)


def max_spacing_wall(t: float, vertical=True) -> float:
    """9.6.2(3) vertical bars: min(3t, 400); 9.6.3(2) horizontal bars: 400."""
    return min(3 * t, 400.0) if vertical else 400.0


# --------------------------------------------------------------------------- minimum / maximum reinforcement
def As_min_flexure(conc: Concrete, fyk: float, b: float, d: float) -> float:
    """9.2.1.1(1) (9.1N): As,min = 0.26 fctm/fyk bt d >= 0.0013 bt d."""
    return max(0.26 * conc.fctm / fyk * b * d, 0.0013 * b * d)


def As_max(b: float, h: float) -> float:
    """9.2.1.1(3): As,max = 0.04 Ac outside laps."""
    return 0.04 * b * h


def As_secondary_min(As_principal: float) -> float:
    """9.3.1.1(2): secondary (distribution) reinforcement >= 20 % of the principal reinforcement."""
    return 0.20 * As_principal


def wall_vertical_limits(t: float, b: float = 1000.0) -> tuple:
    """9.6.2(1): As,vmin = 0.002 Ac, As,vmax = 0.04 Ac (total, both faces)."""
    return 0.002 * b * t, 0.04 * b * t


def wall_horizontal_min(As_vertical_total: float, t: float, b: float = 1000.0) -> float:
    """9.6.3(1): horizontal >= max(25 % of the vertical reinforcement, 0.001 Ac), each face in proportion."""
    return max(0.25 * As_vertical_total, 0.001 * b * t)


# --------------------------------------------------------------------------- flexure (6.1)
def flexure(conc: Concrete, fyk: float, M: float, b: float, d: float) -> dict:
    """Singly reinforced rectangular section, rectangular stress block.  M in Nmm."""
    M = abs(M)
    K = M / (b * d * d * conc.fck)
    Klim = 0.167                                    # no redistribution
    z = d * min(0.95, 0.5 + math.sqrt(max(0.25 - K / 1.134, 0.0)))
    return dict(K=K, Klim=Klim, z=z, As=M / (fyd(fyk) * z) if M else 0.0, compression_steel=K > Klim)


# --------------------------------------------------------------------------- shear (6.2)
def VRd_c(conc: Concrete, b: float, d: float, Asl: float, NEd: float = 0.0, Ac: float | None = None) -> float:
    """6.2.2(1) (6.2.a / 6.2.b).  NEd > 0 compression.  Result in N."""
    k = min(1.0 + math.sqrt(200.0 / d), 2.0)
    rho = min(Asl / (b * d), 0.02)
    scp = min(NEd / Ac, 0.2 * conc.fcd) if (Ac and NEd) else 0.0
    vmin = 0.035 * k ** 1.5 * math.sqrt(conc.fck)
    v = max(0.18 / GAMMA_C * k * (100.0 * rho * conc.fck) ** (1.0 / 3.0), vmin) + 0.15 * scp
    return v * b * d


def shear_enhancement(av: float, d: float) -> float:
    """6.2.2(6): loads applied within 0.5d <= av <= 2d of the support face may be reduced by beta = av / 2d."""
    return min(1.0, max(av, 0.5 * d) / (2.0 * d))


def shear_links(conc: Concrete, fywk: float, VEd: float, b: float, d: float, cot_theta: float = 2.5) -> dict:
    """6.2.3 (vertical links) with the minimum of 9.2.2(5) and the spacing limits of 9.3.2(4) for slabs.
    Returns Asw/s (mm2/mm per width b), the strut check and limiting spacings."""
    z = 0.9 * d; fywd = fywk / GAMMA_S
    nu1 = 0.6 * (1.0 - conc.fck / 250.0)
    def vmax(cot): return 1.0 * b * z * nu1 * conc.fcd / (cot + 1.0 / cot)
    cot = cot_theta
    while cot > 1.0 and vmax(cot) < VEd: cot = round(cot - 0.1, 2)          # steeper strut until it carries the shear
    cot = max(cot, 1.0)
    asw_s = VEd / (z * fywd * cot)
    rho_min = 0.08 * math.sqrt(conc.fck) / fywk                               # (9.5N)
    asw_s_min = rho_min * b
    return dict(z=z, cot_theta=cot, VRd_max=vmax(cot), ok_strut=vmax(cot) >= VEd, Asw_s=max(asw_s, asw_s_min), Asw_s_calc=asw_s,
                Asw_s_min=asw_s_min, s_long_max=0.75 * d, s_trans_max=1.5 * d)


def slab_may_have_links(h: float) -> bool:
    """9.3.2(1): a slab in which shear reinforcement is provided should be at least 200 mm deep."""
    return h >= 200.0


# --------------------------------------------------------------------------- crack width (7.3.4)
def cracked_stress(conc: Concrete, M: float, b: float, d: float, As: float, alpha_e: float | None = None) -> dict:
    """Steel stress in a cracked rectangular section under the SLS moment M (Nmm)."""
    ae = alpha_e if alpha_e is not None else ES / conc.Ecm
    rho = As / (b * d)
    x = d * (-ae * rho + math.sqrt((ae * rho) ** 2 + 2 * ae * rho))
    z = d - x / 3.0
    return dict(x=x, z=z, sigma_s=abs(M) / (As * z) if As else 0.0, alpha_e=ae)


def crack_width(conc: Concrete, M: float, b: float, h: float, d: float, As: float, dia: float, spacing: float, cover: float,
                long_term=True, alpha_e: float | None = None) -> dict:
    """7.3.4 (7.8)-(7.11).  wk = sr,max (eps_sm - eps_cm)."""
    st = cracked_stress(conc, M, b, d, As, alpha_e); x, ss, ae = st["x"], st["sigma_s"], st["alpha_e"]
    hc_eff = min(2.5 * (h - d), (h - x) / 3.0, h / 2.0)
    rho_eff = As / (b * hc_eff)
    kt = 0.4 if long_term else 0.6
    fct = conc.fctm
    eps = max((ss - kt * fct / rho_eff * (1 + ae * rho_eff)) / ES, 0.6 * ss / ES)
    if spacing <= 5.0 * (cover + dia / 2.0):
        sr = 3.4 * cover + 0.8 * 0.5 * 0.425 * dia / rho_eff                    # (7.11): k1 0.8 high bond, k2 0.5 bending
    else:
        sr = 1.3 * (h - x)                                                     # (7.14)
    return dict(wk=sr * eps, sr_max=sr, eps=eps, sigma_s=ss, x=x, hc_eff=hc_eff, rho_eff=rho_eff)


def stress_limits(conc: Concrete, fyk: float) -> dict:
    """7.2: concrete 0.6 fck (characteristic), steel 0.8 fyk (characteristic)."""
    return dict(sigma_c=0.6 * conc.fck, sigma_s=0.8 * fyk)


# --------------------------------------------------------------------------- bond, anchorage, laps (8.4, 8.7)
def fbd(conc: Concrete, dia: float, good_bond=True) -> float:
    """8.4.2(2): fbd = 2.25 eta1 eta2 fctd."""
    eta1 = 1.0 if good_bond else 0.7
    eta2 = 1.0 if dia <= 32 else (132.0 - dia) / 100.0
    return 2.25 * eta1 * eta2 * min(conc.fctd, 0.7 * (0.30 * 60 ** (2 / 3)) / GAMMA_C)       # fctd limited to C60/75


def lb_rqd(conc: Concrete, dia: float, sigma_sd: float, good_bond=True) -> float:
    """8.4.3(2): basic required anchorage length (dia / 4)(sigma_sd / fbd)."""
    return dia / 4.0 * sigma_sd / fbd(conc, dia, good_bond)


def anchorage_length(conc: Concrete, dia: float, sigma_sd: float, good_bond=True, tension=True, bent=False, cd: float | None = None) -> dict:
    """8.4.4: lbd = a1 a2 a3 a4 a5 lb,rqd >= lb,min.  a3 = a4 = a5 = 1 (no credit taken for transverse steel / pressure).
    cd per Figure 8.3 (min of half the clear spacing and the cover); a1 0.7 for bent bars when cd > 3 dia."""
    lrq = lb_rqd(conc, dia, sigma_sd, good_bond)
    a1 = a2 = 1.0
    if tension and cd is not None:
        if bent:
            a1 = 0.7 if cd > 3 * dia else 1.0
            a2 = min(1.0, max(0.7, 1.0 - 0.15 * (cd - 3 * dia) / dia))
        else:
            a2 = min(1.0, max(0.7, 1.0 - 0.15 * (cd - dia) / dia))
    if not tension: a1 = a2 = 1.0
    a = max(a1 * a2, 0.7)
    lmin = max((0.3 if tension else 0.6) * lrq, 10.0 * dia, 100.0)
    return dict(lb_rqd=lrq, alpha1=a1, alpha2=a2, lbd=max(a * lrq, lmin), lb_min=lmin, multiple=max(a * lrq, lmin) / dia)


def alpha6(percent_lapped: float) -> float:
    """Table 8.3: a6 = sqrt(rho1 / 25), 1.0 <= a6 <= 1.5 (rho1 = % of bars lapped within 0.65 l0 of the lap centre)."""
    return min(1.5, max(1.0, math.sqrt(percent_lapped / 25.0)))


def lap_length(conc: Concrete, dia: float, sigma_sd: float, percent_lapped: float = 50.0, good_bond=True, cd: float | None = None) -> dict:
    """8.7.3: l0 = a1 a2 a3 a5 a6 lb,rqd >= l0,min = max(0.3 a6 lb,rqd, 15 dia, 200)."""
    an = anchorage_length(conc, dia, sigma_sd, good_bond, True, False, cd)
    a6 = alpha6(percent_lapped)
    l0 = an["alpha1"] * an["alpha2"] * a6 * an["lb_rqd"]
    lmin = max(0.3 * a6 * an["lb_rqd"], 15.0 * dia, 200.0)
    return dict(l0=max(l0, lmin), l0_min=lmin, alpha6=a6, lb_rqd=an["lb_rqd"], multiple=max(l0, lmin) / dia)


def lap_rules(dia: float, l0: float) -> dict:
    """8.7.2(3)-(4): clear distance between lapped bars <= max(4 dia, 50 mm); adjacent laps staggered so that their
    centres are at least 1.3 l0 apart, otherwise they count as lapped at one section (window 0.65 l0 either side)."""
    return dict(clear_between_lapped_max=max(4 * dia, 50.0), stagger_centres_min=1.3 * l0, clear_between_laps_min=0.3 * l0,
                section_window=0.65 * l0)


def lap_transverse_steel(dia: float, As_lapped_bar: float, percent_lapped: float) -> dict:
    """8.7.4.1: for dia < 20 or < 25 % lapped the transverse steel present for other reasons suffices;
    otherwise sum(Ast) >= As of one lapped bar, placed in the outer thirds of the lap."""
    need = dia >= 20 and percent_lapped >= 25
    return dict(required=need, Ast_total=As_lapped_bar if need else 0.0)


def mandrel_diameter(dia: float) -> float:
    """8.3 Table 8.1N (bends, hooks, loops): 4 dia for dia <= 16, 7 dia above."""
    return 4.0 * dia if dia <= 16 else 7.0 * dia


def bs8666_former_radius(dia: float) -> float:
    """BS 8666:2020 Table 2: minimum former radius 2 dia (<= 16 mm), 3.5 dia (>= 20 mm)."""
    return 2.0 * dia if dia <= 16 else 3.5 * dia


_BS8666_P = {6: 110, 8: 115, 10: 120, 12: 125, 16: 130, 20: 190, 25: 240, 32: 305, 40: 380, 50: 475}


def bs8666_min_end_projection(dia: float) -> float:
    """BS 8666:2020 Table 2: minimum end projection P measured from the outside of the bend."""
    return float(_BS8666_P.get(int(dia), 5 * dia + bs8666_former_radius(dia) + dia))


# --------------------------------------------------------------------------- staggered laps for bars longer than stock
def lap_layout(run: float, l0: float, stock: float = 12000.0, keep_out: list | None = None) -> dict:
    """Split a bar run into pieces not longer than the stock length, in two alternating families (A, B) whose
    lap centres are at least 1.3 l0 apart (8.7.2(3)), so not more than 50 % of the bars are lapped at any section.
    keep_out: [(x0, x1), ...] zones (e.g. of maximum moment) where no lap centre may fall.
    Returns lap centres and piece lengths per family, measured from the start of the run."""
    keep_out = keep_out or []
    if run <= stock:
        return dict(A=dict(centres=[], pieces=[run]), B=dict(centres=[], pieces=[run]), stagger=None, ok=True, n_laps=0)
    stag = 1.3 * l0

    def bad(c): return any(a - l0 / 2 < c < b + l0 / 2 for a, b in keep_out)

    def family(first):
        centres = []; start = 0.0; piece = first
        while True:
            end = start + piece                          # end of this piece
            if end >= run - 1e-6: break
            c = end - l0 / 2.0
            guard = 0
            while bad(c) and guard < 400: c -= 25.0; guard += 1
            centres.append(c); start = c - l0 / 2.0; piece = stock
        pcs = []; s = 0.0
        for c in centres:
            pcs.append(c + l0 / 2.0 - s); s = c - l0 / 2.0
        pcs.append(run - s)
        return centres, pcs
    ca, pa = family(stock)
    cb, pb = None, None
    first = stock - stag
    while first > l0 * 2:
        cb, pb = family(first)
        if all(abs(x - y) >= stag - 1e-6 for x in ca for y in cb) and all(p <= stock + 1e-6 for p in pb): break
        first -= 50.0
    ok = cb is not None and all(abs(x - y) >= stag - 1e-6 for x in ca for y in cb) and all(p <= stock + 1e-6 for p in pa + pb)
    mind = min((abs(x - y) for x in ca for y in cb), default=None)
    return dict(A=dict(centres=ca, pieces=pa), B=dict(centres=cb or [], pieces=pb or []), stagger=mind, ok=ok, n_laps=len(ca))


# --------------------------------------------------------------------------- free edges, corners, corbels
def free_edge_ubar(h: float) -> dict:
    """9.3.1.4: along a free (unsupported) edge a slab has longitudinal and transverse reinforcement,
    generally U-bars enclosing the edge with legs of at least 2h (Figure 9.8)."""
    return dict(leg_min=2.0 * h)


def frame_corner(As: float, b: float, h: float, opening: bool) -> dict:
    """Annex J.2.  Closing moments: J.2.2 (lapped L / U bars, strut check when the members differ).
    Opening moments: J.2.3 - loops / U-bars for moderate reinforcement (As / bh <= 2 %), diagonal bar and
    links enclosing the corner for larger."""
    rho = As / (b * h)
    if not opening: return dict(rho=rho, detail="J.2 fig. J.2: lapped L- or U-bars round the outside of the corner")
    if rho <= 0.02: return dict(rho=rho, detail="J.2.3 fig. J.3: looped (U) bars, with a diagonal bar across the inside of the corner")
    return dict(rho=rho, detail="J.2.3 fig. J.4: diagonal bar and links to prevent splitting")


def corbel(conc: Concrete, fyk: float, FEd: float, HEd: float, ac: float, hc: float, b: float, d: float) -> dict:
    """6.5 / Annex J.3 strut-and-tie corbel (ac < z0).  Forces in N, lengths in mm.
    Main tie Ft = FEd ac / z + HEd; links per J.3(2)-(3) (k1 = 0.25, k2 = 0.5)."""
    HEd = max(HEd, 0.0)
    nu = 1.0 - conc.fck / 250.0
    sig_rd = 0.85 * nu * conc.fcd                                 # 6.5.4(4b) node with one tie (k2 = 0.85)
    z = min(0.8 * d, max(0.2 * d + 0.4 * ac, 0.1 * d))            # internal lever arm, limited as usual for short corbels
    Ft = FEd * ac / z + HEd
    As_main = Ft / fyd(fyk)
    strut = FEd / math.sin(math.atan2(z, ac)) if ac else FEd
    bearing_len = FEd / (b * sig_rd)
    out = dict(z=z, Ft=Ft, As_main=As_main, sigma_Rd=sig_rd, min_bearing_length=bearing_len, strut_force=strut)
    if ac <= 0.5 * hc:
        out.update(links="horizontal / inclined closed links, J.3(2)", As_links=0.25 * As_main)
    else:
        out.update(links="vertical closed links, J.3(3)", As_links=0.5 * FEd / fyd(fyk))
    return out


# --------------------------------------------------------------------------- bar selection
def choose_bars(As_req: float, s_max: float, s_min_clear: float = 25.0, bars=(10, 12, 16, 20, 25, 32),
                spacings=(250, 225, 200, 175, 150, 125, 100), prefer_dia=None) -> tuple:
    """Smallest practical bar at the widest spacing that supplies As_req (mm2/m) within the spacing limits."""
    best = None
    for dia in bars:
        if prefer_dia and dia < prefer_dia: continue
        for sp in spacings:
            if sp > s_max or sp - dia < s_min_clear: continue
            if As_per_m(dia, sp) >= As_req:
                cand = (dia, sp, As_per_m(dia, sp))
                if best is None or cand[2] < best[2] - 1e-9: best = cand
                break
    if best is None:
        dia = bars[-1]; sp = spacings[-1]; best = (dia, sp, As_per_m(dia, sp))
    return best
