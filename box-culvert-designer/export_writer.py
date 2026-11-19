"""
Write a complete CBC_EXPORT.txt from the application's own analysis, design and schedule, so that the
AutoCAD drawing generator produces the full sheet set for the structure the user designed in the app -
without the Excel workbook.

The workbook's PARAMETERS / DERIVED / EXPORT sheets are reproduced here: every key the generator reads
(100 of them) is computed from the primary inputs, the member design and the bar schedule.  The derived
geometry and levels were checked against the reference export to the millimetre (see tests/test_export.py).

build_export(prim, levels, design, sched, meta) -> dict of P-keys
write_export(path, keys, bbs)                    -> writes the P| and B| lines
from_app(main)                                   -> keys, bbs  (reads the running application)
"""
from __future__ import annotations
import math, time

# ---- keys that are plain text in the title block / notes; everything else is numeric
TEXT_KEYS = {
    "STATUS", "OUT_DWG", "LSP_PATH", "AUTO_PUSH", "PROJECT_NAME", "CONTRACT_NO", "CLIENT", "CLIENT_DEPT",
    "SUPERVISOR", "CONTRACTOR", "CONTRACTOR_ROLE", "LOGO_CLIENT", "LOGO_SUPERVISOR", "LOGO_CONTRACTOR",
    "ROAD_NAME", "ISLAND", "STRUCTURE_ID", "ALIGNMENT", "DWG_PREFIX", "REVISION", "REV_DATE", "REV_DESC",
    "DRAWN", "DESIGNED", "CHECKED", "APPROVED", "DOC_STATUS", "PROJECT_STAGE", "COORD_SYS", "FLOW_SIDE",
    "CONC_GRADE", "BLIND_GRADE", "STEEL_GRADE", "LOADING", "DESIGN_REPORT", "SHEET_SIZE", "CH_OUT",
    "CHAINAGE_TXT", "CHECK_FILL", "DESIGN_STATUS", "DESIGN_GOVERN", "DESIGN_TIME", "DWG_PAGING", "DWG_SCALE_MODE",
}

# ---- title-block / project text: blank defaults, filled from the app or a loaded export
META_DEFAULTS = dict(
    STATUS="READY", PROJECT_NAME="", CONTRACT_NO="", CLIENT="", CLIENT_DEPT="", SUPERVISOR="", CONTRACTOR="",
    CONTRACTOR_ROLE="CONTRACTOR", LOGO_CLIENT="", LOGO_SUPERVISOR="", LOGO_CONTRACTOR="", ROAD_NAME="",
    ISLAND="", STRUCTURE_ID="CBC 01", ALIGNMENT="", DWG_PREFIX="CBC-DWG-", REVISION="01", REV_DATE="",
    REV_DESC="FIRST ISSUE", DRAWN="", DESIGNED="", CHECKED="", APPROVED="", DOC_STATUS="FOR APPROVAL",
    PROJECT_STAGE="DETAILED DESIGN", COORD_SYS="", FLOW_SIDE="OUT", ALIGN_CHAINAGE=0.0, CHAINAGE=0.0,
    CL_EASTING=0.0, CL_NORTHING=0.0, SHEET_SIZE="A3", DWG_PAGING="AUTO DETECT", DWG_VIEW_GAP=5,
    DWG_SCALE_MODE="FIXED", SC_GA=50, SC_SEC=25, SC_RC=20,
)

# ---- primary geometry the designer sets (mm, except skew/flare degrees)
PRIMARY_DEFAULTS = dict(
    DIST_S=200, OUT_D=16, OUT_S=150, LAP_MULT=50, ANCH_MULT=40, HCH_D=12, HCH_S=200,
    N_CELLS=4, SPAN_W=1500, SPAN_H=1500, T_TOP=250, T_BASE=250, T_WALL=250, T_INWALL=250,
    HAUNCH=150, BARREL_L=10500, CHAMFER=20, BLINDING_T=75, SKEW_DEG=90,
    APRON_OUT_L=4750, APRON_IN_L=4750, APRON_T=250, APRON_TOE=300,
    WW_FLARE_DEG=30, WW_T_TOP=300, WW_T_BASE=400, WW_END_H=600,
    CUTOFF_D=600, CUTOFF_T=250, CW_WIDTH=6500, ROAD_CL_POS=10000, EMB_SLOPE=2,
    COVER=50, FYK=460, FILL_DESIGN=1000, BEARING_REQ=210,
)


def grade_pct(inv_out, inv_in, barrel_l):
    return 0.0 if barrel_l <= 0 else (inv_in - inv_out) / (barrel_l / 1000.0) * 100.0


def derive(prim: dict, levels: dict) -> dict:
    """Derived geometry, levels and quantities (the workbook DERIVED sheet).  All lengths mm, levels m."""
    P = dict(prim); g = lambda k: float(P[k]); nc = int(round(g("N_CELLS")))
    sw, sh, tt, tb, tw, ti = (g(k) for k in ("SPAN_W", "SPAN_H", "T_TOP", "T_BASE", "T_WALL", "T_INWALL"))
    wwtb, flare = g("WW_T_BASE"), math.radians(g("WW_FLARE_DEG"))
    wc = nc * sw + (nc - 1) * ti; wt = wc + 2 * tw; htot = sh + tt + tb
    D = dict(P)
    D["W_CLEAR"] = wc; D["W_TOT"] = wt; D["H_TOT"] = htot
    # aprons: the apron carries the barrel and a wing-wall base each side; it splays out with the wing walls
    D["W_APRON"] = wt + 2 * wwtb
    D["SPLAY_OUT"] = g("APRON_OUT_L") * math.tan(flare); D["SPLAY_IN"] = g("APRON_IN_L") * math.tan(flare)
    D["W_APRON_END_OUT"] = D["W_APRON"] + 2 * D["SPLAY_OUT"]; D["W_APRON_END_IN"] = D["W_APRON"] + 2 * D["SPLAY_IN"]
    cf = math.cos(flare) or 1.0
    D["L_WW_OUT"] = g("APRON_OUT_L") / cf; D["L_WW_IN"] = g("APRON_IN_L") / cf
    D["L_TOT"] = g("BARREL_L") + g("APRON_OUT_L") + g("APRON_IN_L")
    D["WATERWAY"] = nc * sw * sh / 1e6
    # levels (m): invert, soffit, top of slab, underside of base, apron top, wing wall top, cut-off bottom
    io, ii = g("INV_OUT"), g("INV_IN"); cutoff = g("CUTOFF_D") / 1000.0; wwh = g("WW_END_H") / 1000.0
    D["GRADE_PCT"] = grade_pct(io, ii, g("BARREL_L"))
    for tag, inv in (("OUT", io), ("IN", ii)):
        D[f"SOF_{tag}"] = inv + sh / 1000.0; D[f"TOS_{tag}"] = inv + (sh + tt) / 1000.0
        D[f"USB_{tag}"] = inv - tb / 1000.0; D[f"APR_TOP_{tag}"] = inv
        D[f"WW_TOP_{tag}_END"] = inv + wwh; D[f"CUTOFF_BOT_{tag}"] = inv - tb / 1000.0 - cutoff
    D["TOS_CL"] = (D["TOS_OUT"] + D["TOS_IN"]) / 2.0
    D["FILL_CL"] = levels.get("ROAD_FGL", D["TOS_CL"]) * 1000.0 - D["TOS_CL"] * 1000.0
    D["ROAD_FGL"] = levels.get("ROAD_FGL", D["TOS_CL"] + 1.0)
    D["OGL_OUT"] = levels.get("OGL_OUT", io - 0.3); D["OGL_IN"] = levels.get("OGL_IN", ii - 0.3)
    D["CH_OUT"] = "0+000.00"; D["CHAINAGE_TXT"] = levels.get("CHAINAGE_TXT", "0+000.00")
    D["N_ACROSS_BARREL"] = int(g("BARREL_L") / max(g("OUT_S"), 1))   # transverse slab bars along the barrel
    D["LAP_OUT"] = g("LAP_MULT") * g("OUT_D")
    design_fill = g("FILL_DESIGN"); actual = D["FILL_CL"]
    D["CHECK_FILL"] = "OK" if actual <= design_fill + 1e-6 else "CHECK - actual cover exceeds design fill"
    # concrete volumes (m3), nominal
    m = 1e-9
    vb = (wt * (tt + tb) + (nc + 1) * tw * sh + (g("HAUNCH") ** 2) * nc * 2 * 0.5) * g("BARREL_L") * m
    va = D["W_APRON"] * g("APRON_T") * (g("APRON_OUT_L") + g("APRON_IN_L")) * m
    vw = 4 * 0.5 * (g("WW_T_TOP") + wwtb) * (htot) * ((D["L_WW_OUT"] + D["L_WW_IN"]) / 2.0) * m
    vcut = 2 * g("CUTOFF_T") * g("CUTOFF_D") * D["W_APRON_END_OUT"] * m
    D["VOL_BARREL"] = vb; D["VOL_APRONS"] = va; D["VOL_WINGS"] = vw; D["VOL_CUTOFF"] = vcut
    D["VOL_TOTAL"] = vb + va + vw + vcut
    D["VOL_BLIND"] = (wt + 2 * wwtb) * g("BLINDING_T") * D["L_TOT"] * m
    return D


def build_export(prim: dict, levels: dict, design: dict, sched: list, meta: dict | None = None) -> dict:
    """Assemble every P-key the generator reads from the primary inputs, the design and the schedule."""
    keys = dict(META_DEFAULTS); keys.update(meta or {})
    P = dict(PRIMARY_DEFAULTS); P.update(design); P.update(prim)      # design supplies DIST_S, OUT_D, LAP_MULT for the derived keys
    # design outputs: bar sizes/spacings, cover, lap and anchorage multiples, materials, loading, status
    # secondary-element reinforcement (apron, wing walls, cut-off): default to the distribution bar until designed
    dd, ds = design.get("DIST_D", 12), design.get("DIST_S", 200)
    for k, dv in (("APR_D", dd), ("APR_S", ds), ("WWV_D", dd), ("WWV_S", ds), ("WWH_D", dd), ("WWH_S", ds), ("CUT_D", dd), ("CUT_S", ds)):
        keys.setdefault(k, dv)
    for k, dv in (("OUT_DWG", ""), ("LSP_PATH", ""), ("AUTO_PUSH", "NO"), ("DESIGN_REPORT", ""),
                  ("GAMMA_SOIL", 20), ("K0", 0.5), ("KS", 30000), ("HB_WHEEL", 112.5), ("HB_PRESS", 1.1),
                  ("HB_AXLE_SP", 1800), ("HB_WHEEL_SP", 1000), ("SURCHARGE", 16.67),
                  ("CONC_GRADE", "C25/30"), ("BLIND_GRADE", "C15"), ("STEEL_GRADE", "GRADE 460"), ("EXPOSURE", "XC2"),
                  ("LOADING", "BS 5400 HB"), ("DESIGN_STATUS", "PASS"), ("DESIGN_MAXUTIL", 0.0), ("DESIGN_GOVERN", ""),
                  ("BEARING_SLS", 0.0), ("BEARING_ULS", 0.0)):
        keys.setdefault(k, dv)
    keys.update(design)
    keys.update(derive(P, levels))
    keys["ECM"] = design.get("ECM", 31000); keys["GAMMA_CONC"] = design.get("GAMMA_CONC", 25)
    keys["WK_LIM"] = design.get("WK_LIM", 0.3)
    for gk, dv in (("GAMMA_G", 1.35), ("GAMMA_G_MIN", 1.0), ("GAMMA_Q", 1.35)): keys.setdefault(gk, dv)
    # steel: from the schedule mass and the concrete volume
    total = sum(r["mass"] for r in sched) if sched else 0.0
    keys["STEEL_TOTAL"] = total; keys["BBS_ROWS"] = len(sched)
    keys["STEEL_RATE"] = total / keys["VOL_TOTAL"] if keys.get("VOL_TOTAL") else 0.0
    keys["DESIGN_TIME"] = time.strftime("%d.%m.%y %H:%M")
    return keys


def schedule_rows(sched: list) -> list:
    """B| rows for the generator / BBS sheet: mark, member, bar, dia, spacing, n_members, n_each, n_total,
    shape, A, B, C, L, kg/m, mass, note.  Built from the application's own bar schedule."""
    rows = []
    for r in sched:
        legs = r.get("legs", []); a = legs[0] if legs else 0; b = legs[1] if len(legs) > 1 else 0; c = legs[2] if len(legs) > 2 else 0
        L = int(round(r["length"]))
        rows.append([r["mark"], r.get("group", "BARREL"), f"T{int(r['dia'])}-{int(r['spacing'])}", int(r["dia"]), int(r["spacing"]),
                     1, r["no"], r["no"], r["shape"], int(a), int(b), int(c), L,
                     round(math.pi * r["dia"] ** 2 / 4 * 7850e-9, 3), round(r["mass"], 1), str(L), r.get("member", "") or r.get("base", "")])
    return rows


def write_export(path: str, keys: dict, bbs: list | None = None):
    """Write CBC_EXPORT.txt: a P| line per key and a B| line per schedule row."""
    with open(path, "w", encoding="utf-8") as f:
        for k in sorted(keys):
            v = keys[k]
            if k in TEXT_KEYS or isinstance(v, str): f.write(f"P|{k}|S|{v}\n")
            else: f.write(f"P|{k}|N|{_num(v)}\n")
        for row in (bbs or []):
            f.write("B|" + "|".join(str(x) for x in row) + "\n")


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:.6g}"


def from_app(main) -> tuple:
    """Read the running application: primary geometry, levels, design outputs and schedule -> (keys, bbs)."""
    p = main.p; R = main.R; sb = main
    mm = lambda v: round(v * 1000.0)
    F = R.faces; out = max((F[(m, "outer")] for m in ("top", "base", "walls")), key=lambda f: f.As)
    prim = dict(
        N_CELLS=p.n_cells, SPAN_W=mm(p.span), SPAN_H=mm(p.height), T_TOP=mm(p.t_top), T_BASE=mm(p.t_base),
        T_WALL=mm(p.t_wall), T_INWALL=mm(p.t_pier), COVER=mm(p.cover), FYK=p.fyk,
        BARREL_L=mm(main.i_barrel.value()), SKEW_DEG=main.i_skew.value(), WW_FLARE_DEG=main.i_flare.value(),
        APRON_OUT_L=mm(main.i_apron.value()), APRON_IN_L=mm(main.i_apron.value()), TOE=main.i_toe.value(),
        INV_OUT=main.i_inv_out.value(), INV_IN=main.i_inv_in.value(), HAUNCH=int(main.i_haunch.value()),
        CUTOFF_D=int(main.i_cutoff.value()), WW_T_TOP=int(main.i_wwtop.value()), WW_T_BASE=int(main.i_wwbase.value()), WW_END_H=int(main.i_wwend.value()),
    )
    design = dict(
        LAP_MULT=main.lap_mult, ANCH_MULT=main.anch_mult, FCK=p.fck, ECM=round(p.Ecm), GAMMA_CONC=round(p.gamma_conc),
        WK_LIM=main.i_wk.value(), EXPOSURE=main.i_expo.currentText(), CONC_GRADE=f"C{int(p.fck)}/{int(p.fck)+5}",
        STEEL_GRADE=f"GRADE {int(p.fyk)}" + (" (BS 4449)" if p.fyk == 460 else " / B500"), LOADING=f"BS 5400 HB {p.hb_units:g} UNITS",
        FILL_DESIGN=round(p.fill * 1000), BEARING_REQ=210, DESIGN_STATUS="PASS" if main.maxutil <= 1.0 else "REVIEW",
        DESIGN_MAXUTIL=round(main.maxutil, 2), DESIGN_GOVERN=main.govern, BEARING_SLS=round(main.bearing_sls, 1), BEARING_ULS=round(main.bearing_uls, 1),
        OUT_D=out.dia, OUT_S=out.spacing, TOPIN_D=F[("top", "inner")].dia, TOPIN_S=F[("top", "inner")].spacing,
        BOTIN_D=F[("base", "inner")].dia, BOTIN_S=F[("base", "inner")].spacing, WALLIN_D=F[("walls", "inner")].dia, WALLIN_S=F[("walls", "inner")].spacing,
        DIST_D=R.dist["top"]["dia"], DIST_S=R.dist["top"]["spacing"], HCH_D=12, HCH_S=200,
    )
    if p.n_cells > 1: design.update(PIER_D=F[("piers", "inner")].dia, PIER_S=F[("piers", "inner")].spacing)
    if getattr(main, "secondary", None) is not None: design.update(main.secondary.export_keys())
    levels = dict(ROAD_FGL=main.i_road_fgl.value())
    for k in ("OGL_OUT", "OGL_IN", "CHAINAGE_TXT"):
        if main.export and main.export.get(k) is not None: levels[k] = main.export[k]
    meta = {k: main.export[k] for k in META_DEFAULTS if main.export and k in main.export} if main.export else {}
    keys = build_export(prim, levels, design, main.sched, meta)
    return keys, schedule_rows(main.sched)
