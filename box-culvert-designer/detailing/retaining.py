"""
Design of the secondary elements of a box culvert - the wing walls, the aprons and the cut-off walls -
to EN 1992-1-1 (reinforced concrete) and EN 1997-1 (geotechnical stability).

These were not part of the box frame analysis: each is a stand-alone element with its own actions.

  * Wing wall  - a cantilever retaining wall, tallest at the barrel and tapering to the end height.
                 Stem: at-rest earth pressure + surcharge over its height -> vertical bars on the earth face.
                 Base: bearing, sliding and overturning (EN 1997-1, GEO/EQU).
  * Apron      - a ground-bearing slab; nominal top and bottom mesh (9.3), longitudinal bars anchored into the
                 barrel and turned down into the cut-off, checked for uplift when the water table is high.
  * Cut-off    - a shallow curtain wall at each apron end; nominal U-bars, depth set against scour.

All forces per metre run; lengths m; results in a Secondary dataclass carrying the bar sizes the drawing and
the schedule need (WWV, WWH, APR, CUT) and the stability check rows.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from . import ec2

GAMMA_W = 9.81


@dataclass
class Element:
    name: str
    face: dict                       # governing flexural face: dia, spacing, As, As_req, As_min, d, wk, util
    secondary: dict                  # distribution / horizontal bars
    checks: list = field(default_factory=list)   # (item, value, limit, ok, note)
    geometry: dict = field(default_factory=dict)


@dataclass
class Secondary:
    wing: Element
    apron: Element
    cutoff: Element
    def export_keys(self) -> dict:
        """Bar sizes for the generator: wing wall vertical/horizontal, apron, cut-off."""
        return dict(WWV_D=self.wing.face["dia"], WWV_S=self.wing.face["spacing"],
                    WWH_D=self.wing.secondary["dia"], WWH_S=self.wing.secondary["spacing"],
                    APR_D=self.apron.face["dia"], APR_S=self.apron.face["spacing"],
                    CUT_D=self.cutoff.face["dia"], CUT_S=self.cutoff.face["spacing"],
                    WW_T_TOP=self.wing.geometry["t_top"], WW_T_BASE=self.wing.geometry["t_base"])
    def rows(self) -> list:
        out = []
        for e in (self.wing, self.apron, self.cutoff):
            for c in e.checks: out.append(dict(group=e.name, clause=c[4] if len(c) > 4 and isinstance(c[4], str) and c[4][:2].isdigit() else "", item=c[0], value=c[1], limit=c[2], ok=c[3], note=c[4] if len(c) > 4 else ""))
        return out


def _flex_bars(conc, fyk, M_knm, h_m, cover_m, dia_main, exposure="XC2", wk_lim=0.3, bars=(12, 16, 20, 25), is_wall=False):
    """Choose bars for a moment M (kNm/m) in a section of thickness h (m): flexure, min steel, spacing, crack width.
    Follows the box design's unit convention: EC2 helpers take Nmm and mm."""
    b = 1000.0; h = h_m * 1000.0; cover = cover_m * 1000.0; M = M_knm * 1e6; best = None
    smax = min(ec2.max_spacing_wall(h) if is_wall else ec2.max_spacing_slab(h, principal=True), 250.0)
    for dia in bars:
        d = h - cover - dia / 2.0
        if d <= 0: continue
        As_req = ec2.flexure(conc, fyk, M, b, d)["As"]; As_min = ec2.As_min_flexure(conc, fyk, b, d)
        need = max(As_req, As_min); clear = ec2.min_clear_spacing(dia, conc.dg)
        for sp in (250, 225, 200, 175, 150, 125, 100):
            if sp > smax or sp - dia < clear: continue
            As = ec2.As_per_m(dia, sp)
            if As < need - 1e-6: continue
            cw = ec2.crack_width(conc, M, b, h, d, As, dia, sp, cover) if M > 0 else dict(wk=0.0, sigma_s=0.0)
            row = dict(dia=dia, spacing=sp, As=As, As_req=As_req, As_min=As_min, d=d / 1000.0, wk=cw["wk"], M=M_knm,
                       util=need / As, util_wk=cw["wk"] / wk_lim if wk_lim else 0.0, sigma_s=cw["sigma_s"])
            if cw["wk"] <= wk_lim + 1e-6 and cw["sigma_s"] <= 0.8 * fyk:
                return row
            if best is None or max(row["util"], row["util_wk"]) < max(best["util"], best["util_wk"]): best = row
    if best is None:
        dia, sp = bars[-1], 100; d = h - cover - dia / 2.0; As = ec2.As_per_m(dia, sp)
        cw = ec2.crack_width(conc, M, b, h, d, As, dia, sp, cover) if M > 0 else dict(wk=0.0, sigma_s=0.0)
        best = dict(dia=dia, spacing=sp, As=As, As_req=ec2.flexure(conc, fyk, M, b, d)["As"], As_min=ec2.As_min_flexure(conc, fyk, b, d),
                    d=d / 1000.0, wk=cw["wk"], M=M_knm, util=9.9, util_wk=cw["wk"] / wk_lim if wk_lim else 0.0, sigma_s=cw["sigma_s"])
    best["note"] = "crack width or steel limit not met - thicken the section"; return best


def wing_wall(conc, fyk, height: float, t_top: float, t_base: float, end_height: float, cover: float,
              gamma_soil=19.0, K0=0.5, surcharge=10.0, phi=30.0, bearing_allow=200.0, water_depth=None,
              base_width=None, toe=None, exposure="XC2", wk_lim=0.3) -> Element:
    """Cantilever wing wall, governing (tallest) section at the barrel.

    Earth pressure at rest over the retained height H, plus a surcharge; the stem is a vertical cantilever.
    The base is proportioned (if not given) and checked for bearing, sliding and overturning to EN 1997-1."""
    H = height                                                           # retained height at the barrel (m)
    ka = K0
    toe0 = toe if toe is not None else 0.3
    tb = t_base

    def stability(heel, toe_):
        gc = 25.0; W_stem = gc * (t_top + t_base) / 2.0 * H; x_stem = toe_ + t_base / 2.0
        W_base = gc * tb * (toe_ + t_base + heel); x_base = (toe_ + t_base + heel) / 2.0
        W_soil = gamma_soil * H * heel; x_soil = toe_ + t_base + heel / 2.0
        N = W_stem + W_base + W_soil; B = toe_ + t_base + heel
        Ph = ka * gamma_soil * H * H / 2.0 + ka * surcharge * H
        M_over = ka * gamma_soil * H * H / 2.0 * (H / 3.0) + ka * surcharge * H * (H / 2.0)
        M_res = W_stem * x_stem + W_base * x_base + W_soil * x_soil
        mu = math.tan(math.radians(phi)) * 0.8
        ecc = B / 2.0 - (M_res - M_over) / N; q_max = N / B * (1 + 6 * abs(ecc) / B)
        return dict(N=N, B=B, Ph=Ph, M_over=M_over, M_res=M_res, mu=mu, e=ecc, q_max=q_max,
                    fos_over=M_res / M_over if M_over else 99, fos_slide=mu * N / Ph if Ph else 99)
    # size the heel (and toe) so sliding, bearing and the middle-third rule are satisfied, if geometry allows
    heel = base_width if base_width else max(0.5, 0.6 * H); toe = toe0
    if base_width is None:
        for _ in range(40):
            s_ = stability(heel, toe)
            if s_["fos_slide"] >= 1.5 and s_["q_max"] <= bearing_allow and abs(s_["e"]) <= s_["B"] / 6 + 1e-9: break
            if abs(s_["e"]) > s_["B"] / 6 and toe < 0.5 * H: toe += 0.1       # a toe recentres the resultant
            else: heel += 0.1
            if heel > 1.6 * H: break
    # --- stem flexure at the base of the stem
    p_earth = ka * gamma_soil * H                                        # kPa at the base
    M_earth = p_earth * H / 2.0 * (H / 3.0)                              # triangular, per m
    M_sur = ka * surcharge * H * (H / 2.0)
    Mw = 0.0
    if water_depth is not None and water_depth < H:
        hw = H - water_depth; M_earth = ka * (gamma_soil - GAMMA_W) * H * H / 2.0 * (H / 3.0); Mw = GAMMA_W * hw * hw / 2.0 * (hw / 3.0)
    M = M_earth + M_sur + Mw
    face = _flex_bars(conc, fyk, M, t_base, cover, 16, exposure, wk_lim, bars=(12, 16, 20, 25), is_wall=True)
    face["M"] = M
    # --- horizontal distribution on the stem (9.6 / 9.3): >= 25% of vertical, min steel
    need_h = max(0.25 * face["As"], ec2.As_secondary_min(face["As"]))
    hd, hs, hAs = ec2.choose_bars(need_h, min(ec2.max_spacing_wall(t_top * 1000, vertical=False), 300.0), bars=(10, 12, 16), prefer_dia=12)
    secondary = dict(dia=hd, spacing=hs, As=hAs, As_req=need_h)
    # --- stability (per m run) at the chosen base
    st = stability(heel, toe); N = st["N"]; B = st["B"]; fos_over = st["fos_over"]; fos_slide = st["fos_slide"]; e = st["e"]; q_max = st["q_max"]
    checks = [
        ("Stem flexure, earth face", f"M {M:.1f} kNm/m, T{face['dia']}-{face['spacing']}", f"wk {face['wk']:.2f} <= {wk_lim}", face["wk"] <= wk_lim + 1e-6 and face["As"] >= max(face["As_req"], face["As_min"]) - 1e-6, "EN 1992-1-1 6.1 / 7.3"),
        ("Overturning (EQU)", f"FoS {fos_over:.2f}", ">= 1.5", fos_over >= 1.5, "EN 1997-1"),
        ("Sliding (GEO)", f"FoS {fos_slide:.2f}", ">= 1.5", fos_slide >= 1.5, "EN 1997-1, base friction 0.8 tan phi'"),
        ("Bearing (GEO)", f"q {q_max:.0f} kPa", f"<= {bearing_allow:.0f} kPa", q_max <= bearing_allow + 1e-6, "EN 1997-1; e = %.0f mm, B = %.0f mm" % (e * 1000, B * 1000)),
        ("Base contact", "no uplift" if abs(e) <= B / 6 + 1e-9 else f"e {e*1000:.0f} mm > B/6", f"e <= B/6 = {B/6*1000:.0f} mm", abs(e) <= B / 6 + 1e-9, "resultant within the middle third"),
    ]
    geom = dict(t_top=int(t_top * 1000), t_base=int(t_base * 1000), height=H, end_height=end_height, base_width=round(B, 2), toe=round(toe, 2), heel=round(heel, 2))
    return Element("Wing walls", face, secondary, checks, geom)


def apron(conc, fyk, width: float, length: float, thickness: float, cover: float, scour_depth=0.0,
          water_depth=None, gamma_soil=19.0, exposure="XC4", wk_lim=0.3) -> Element:
    """Apron ground slab: nominal top and bottom reinforcement (9.3.1.1), longitudinal bars anchored into the
    barrel and bent into the cut-off.  Checked for flotation when a high water table can lift it."""
    h = thickness
    # a ground slab carries only nominal moments; size the transverse bars to As,min with a modest design moment
    Mnom = max(5.0, 0.03 * gamma_soil * length ** 2)                     # a nominal span moment for a jointed slab
    face = _flex_bars(conc, fyk, Mnom, h, cover, 12, exposure, wk_lim, bars=(12, 16, 20))
    need_l = ec2.As_secondary_min(face["As"])
    ld, ls, lAs = ec2.choose_bars(need_l, min(ec2.max_spacing_slab(h * 1000, principal=False), 250.0), bars=(10, 12, 16), prefer_dia=12)
    secondary = dict(dia=ld, spacing=ls, As=lAs, As_req=need_l)
    checks = [("Transverse steel, both faces", f"T{face['dia']}-{face['spacing']}", f">= As,min {face['As_min']:.0f} mm2/m", face["As"] >= face["As_min"] - 1e-6, "EN 1992-1-1 9.3.1.1"),
              ("Longitudinal steel", f"T{ld}-{ls}", f">= {need_l:.0f} mm2/m", lAs >= need_l - 1e-6, "anchored into the barrel, bent into the cut-off")]
    if water_depth is not None:
        uplift = GAMMA_W * max(0.0, (h + scour_depth) - water_depth); weight = 25.0 * h
        checks.append(("Flotation", f"uplift {uplift:.1f} kPa", f"<= self weight {weight:.1f} kPa", uplift <= weight + 1e-6, "EN 1997-1 UPL; otherwise tie the apron to the barrel"))
    return Element("Aprons", face, secondary, checks, dict(width=width, length=length, thickness=int(h * 1000)))


def cutoff(conc, fyk, depth: float, thickness: float, cover: float, scour_depth=1.0, exposure="XC4", wk_lim=0.3) -> Element:
    """Cut-off (curtain) wall at each apron end: nominal U-bars; its depth must reach below the scour line."""
    face = _flex_bars(conc, fyk, 5.0, thickness, cover, 12, exposure, wk_lim, bars=(12, 16))
    secondary = dict(dia=face["dia"], spacing=face["spacing"], As=face["As"], As_req=face["As_min"])
    checks = [("U-bars, both faces", f"T{face['dia']}-{face['spacing']}", f">= As,min {face['As_min']:.0f} mm2/m", face["As"] >= face["As_min"] - 1e-6, "EN 1992-1-1 9.6"),
              ("Depth against scour", f"{depth*1000:.0f} mm", f">= scour {scour_depth*1000:.0f} mm", depth >= scour_depth - 1e-6, "cut-off toes in below the predicted scour")]
    return Element("Cut-off walls", face, secondary, checks, dict(depth=depth, thickness=int(thickness * 1000)))


def design(conc, fyk, *, barrel_height, t_top, t_base, wall_top, wall_base, end_height, cover,
           apron_width, apron_length, apron_t, cutoff_depth, cutoff_t, gamma_soil=19.0, K0=0.5,
           surcharge=10.0, phi=30.0, bearing_allow=200.0, water_depth=None, scour_depth=1.0,
           exposure="XC4", wk_lim=0.3) -> Secondary:
    """Design all secondary elements of the culvert and return their reinforcement and checks."""
    H = barrel_height + t_top + t_base                                   # wing wall retains the full box height at the barrel
    w = wing_wall(conc, fyk, H, wall_top, wall_base, end_height, cover, gamma_soil, K0, surcharge, phi,
                  bearing_allow, water_depth, exposure=exposure, wk_lim=wk_lim)
    a = apron(conc, fyk, apron_width, apron_length, apron_t, cover, scour_depth, water_depth, gamma_soil, exposure, wk_lim)
    c = cutoff(conc, fyk, cutoff_depth, cutoff_t, cover, scour_depth, exposure, wk_lim)
    return Secondary(w, a, c)
