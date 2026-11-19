"""
SECTION B-B - BARREL REINFORCEMENT

Python port of the user's own AutoLISP generator (cbc:sheet3 in
CBC01_Drawing_Generator.lsp, with the cbc:hbar / cbc:stg / cbc:nlb / cbc:cjy
overrides of the RC extensions and cbc:leg of the paging module).

Geometry is produced in REAL millimetres, x = 0 on the barrel centre line,
y = 0 at the invert, exactly as the LISP does before its V (real -> paper)
transform.  Two renderers consume the same primitives:

    to_dxf(drawing, path)   AutoCAD DXF at paper scale, original layer names/colours
    to_mpl(drawing, ax)     matplotlib (used by the desktop app)

Parameters use the keys of CBC_EXPORT.txt (P|KEY|TYPE|VALUE).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

SQ2 = math.sqrt(2.0)
TXF = 2.0          # A3 text factor of the generator (TX h -> 2h on paper)

# layer -> (ACI colour, matplotlib colour on dark, matplotlib colour on light)
LAYERS = {
    "CBC_CONC":  (3,   "#00ff00", "#008a00"),
    "CBC_REBAR": (1,   "#ff2020", "#d00000"),
    "CBC_DIM":   (4,   "#00ffff", "#008c9e"),
    "CBC_TEXT":  (7,   "#ffffff", "#111111"),
    "CBC_RTXT":  (10,  "#ff2020", "#d00000"),
    "CBC_THIN":  (251, "#9a9a9a", "#555555"),
    "CBC_TITLE": (2,   "#ffff00", "#8a6d00"),
    "CBC_HATCH": (8,   "#808080", "#808080"),
}


# (cbc:setup) layer table: name, ACI colour, lineweight (1/100 mm)
SETUP_LAYERS = [("CBC_CONC", 3, 25), ("CBC_HID", 8, 18), ("CBC_CL", 6, 13), ("CBC_DIM", 4, 13), ("CBC_TEXT", 7, 18),
                ("CBC_TITLE", 2, 35), ("CBC_NOTES", 7, 18), ("CBC_HATCH", 8, 9), ("CBC_REBAR", 1, 35),
                ("CBC_REBAR_B", 1, 35), ("CBC_RTXT", 10, 18), ("CBC_THIN", 251, 13)]


def r10(x: float) -> float:
    """(cbc:r10 x) - round to the nearest 10 mm, AutoLISP fix() semantics."""
    return 10.0 * math.floor(0.5 + x / 10.0) if x >= 0 else 10.0 * math.ceil(x / 10.0 - 0.5)


def num(v: float) -> str:
    """(cbc:num v)"""
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.2f}"


# --------------------------------------------------------------------------- parameters
DEFAULTS = dict(
    N_CELLS=4, SPAN_W=1500, SPAN_H=1500, T_TOP=250, T_BASE=250, T_WALL=250, T_INWALL=250,
    HAUNCH=150, CHAMFER=20, BLINDING_T=75, COVER=50, LAP_MULT=50, ANCH_MULT=40,
    OUT_D=16, OUT_S=150, TOPIN_D=16, TOPIN_S=200, BOTIN_D=16, BOTIN_S=200,
    WALLIN_D=12, WALLIN_S=200, PIER_D=12, PIER_S=200, DIST_D=12, DIST_S=200,
    HCH_D=12, HCH_S=200, SC_RC=20, BAR_STOCK=12000,
    TOE=0,                      # base slab projection beyond the outer wall faces (same toe as the wing walls)
    FREE_EDGE_LEG=0,            # U-cap leg at the toe edge; 0 = max(2 x base thickness (EN 1992-1-1 9.3.1.4), anchorage)
)


def read_export(path: str) -> dict:
    """Read CBC_EXPORT.txt (P|KEY|N|value / P|KEY|S|text). 'B|' schedule rows -> key 'BBS'."""
    P, bbs = {}, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            parts = ln.rstrip("\r\n").split("|")
            if parts[0] == "P" and len(parts) >= 4:
                P[parts[1]] = float(parts[3]) if parts[2] == "N" else "|".join(parts[3:])
            elif parts[0] == "B":
                bbs.append(parts[1:])
    P["BBS"] = bbs
    return P


def complete(P: dict) -> dict:
    """Fill defaults and the derived widths the EXPORT sheet normally supplies."""
    Q = dict(DEFAULTS)
    Q.update({k: v for k, v in P.items() if v is not None})
    nc = int(round(Q["N_CELLS"]))
    Q.setdefault("W_CLEAR", nc * Q["SPAN_W"] + (nc - 1) * Q["T_INWALL"])
    Q.setdefault("W_TOT", Q["W_CLEAR"] + 2 * Q["T_WALL"])
    Q.setdefault("H_TOT", Q["SPAN_H"] + Q["T_TOP"] + Q["T_BASE"])
    return Q


# --------------------------------------------------------------------------- primitives
@dataclass
class Drawing:
    sc: float                                   # real mm per paper mm (SC_RC)
    pl: list = field(default_factory=list)      # (pts, closed, layer, mark)
    dots: list = field(default_factory=list)    # (x, y, bar_dia, layer)
    lines: list = field(default_factory=list)   # (p, q, layer)
    texts: list = field(default_factory=list)   # (p, h, s, jh, jv, layer)   h = generator height
    leaders: list = field(default_factory=list) # (p, q, s, layer)
    dims: list = field(default_factory=list)    # ('h'|'v', a, b, at, loc, override)
    hatches: list = field(default_factory=list) # (pts, pattern, layer)
    title: tuple | None = None                  # (p, text, scale)
    warnings: list = field(default_factory=list)

    def bars(self, mark=None):
        return [p for p in self.pl if p[2] == "CBC_REBAR" and (mark is None or p[3] == mark)]


def text_width(s: str, h: float) -> float:
    """Approximate drawn width of a single-line text of height h (AutoCAD simplex / CBC_ANNO style)."""
    w = 0.0
    for ch in s:                       # widths fitted to the MLeader landings of the reference drawing
        w += 0.55 if ch == " " else 0.45 if ch in "()" else 0.66 if ch.isalpha() else 0.69
    return w * h


def leader_landing(D: "Drawing", p, q, s):
    """Landing point (real mm) of a bar label, as AutoCAD places the MLeader of (LB p q s la)."""
    dr = 1.0 if q[0] >= p[0] else -1.0
    return q if dr > 0 else (q[0] + (text_width(s, 4.0) + 1.2 + 3.0) * D.sc, q[1])


def _fit_width(ax, t, width_data):
    """Scale a matplotlib text horizontally so its drawn width equals width_data (keeps labels where AutoCAD puts them)."""
    ax.figure.canvas.draw()
    bb = t.get_window_extent().transformed(ax.transData.inverted())
    if bb.width > 0:
        t.set_fontstretch("normal"); t.set_fontsize(t.get_fontsize() * min(1.0, width_data / bb.width))


def leg(P, d, th):
    """(cbc:leg d th) - 90 deg anchorage leg of a bar turned into a member of thickness th."""
    return max(12.0 * d, r10(P["ANCH_MULT"] * d - (th - P["COVER"] - P["OUT_D"])))


def cellpoly(P, j):
    wt, tw, sw, ti, shh, h = P["W_TOT"], P["T_WALL"], P["SPAN_W"], P["T_INWALL"], P["SPAN_H"], P["HAUNCH"]
    x0 = -wt / 2.0 + tw + j * (sw + ti); x1 = x0 + sw
    if h > 0:
        return [(x0 + h, 0), (x1 - h, 0), (x1, h), (x1, shh - h), (x1 - h, shh), (x0 + h, shh), (x0, shh - h), (x0, h)]
    return [(x0, 0), (x1, 0), (x1, shh), (x0, shh)]


def outerpoly(P):
    a, c = P["W_TOT"] / 2.0, P["CHAMFER"]; y0, y1 = -P["T_BASE"], P["SPAN_H"] + P["T_TOP"]
    return [(-a + c, y0), (a - c, y0), (a, y0 + c), (a, y1 - c), (a - c, y1), (-a + c, y1), (-a, y1 - c), (-a, y0 + c)]


def _dots(D, p1, p2, sp, d):
    """(cbc:dots p1 p2 sp d)"""
    L = math.dist(p1, p2)
    if L < 1.0:
        L = 1.0; p2 = (p1[0] + 1.0, p1[1])
    n = int(L / sp); dx = (p2[0] - p1[0]) / L; dy = (p2[1] - p1[1]) / L
    for i in range(n + 1):
        D.dots.append((p1[0] + dx * sp * i, p1[1] + dy * sp * i, d, "CBC_REBAR"))


def _plen(pts):
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def build(P_in: dict) -> Drawing:
    P = complete(P_in)
    nc = int(round(P["N_CELLS"]))
    sw, shh, tt, tb, tw, ti = P["SPAN_W"], P["SPAN_H"], P["T_TOP"], P["T_BASE"], P["T_WALL"], P["T_INWALL"]
    hh, cv, bl = P["HAUNCH"], P["COVER"], P["BLINDING_T"]
    wt, htot, wc = P["W_TOT"], P["H_TOT"], P["W_CLEAR"]
    hw = shh + tt
    BD = lambda k: P[k + "_D"]
    BS = lambda k: P[k + "_S"]
    # (MK m k) with the RC_Extension3 override: lapped bars that alternate read 01/01a, 02/02a
    MK = lambda m, k: (f"{m}/{m}a" if m in ("01", "02", "13") else m) + f"-T{num(BD(k))}-{num(BS(k))}"
    D = Drawing(sc=P["SC_RC"])

    def bar(pts, mark, dia=None):
        if _plen(pts) > P["BAR_STOCK"] + 0.5:
            D.warnings.append(f"bar {mark}: developed length {_plen(pts):.0f} mm exceeds the "
                              f"{P['BAR_STOCK']:.0f} mm stock length - lapped pieces not drawn yet")
        D.pl.append((pts, False, "CBC_REBAR", mark, dia))

    # concrete outline + cells
    toe = float(P.get("TOE", 0) or 0); A = wt / 2.0 + toe
    if toe > 0:
        ch = P["CHAMFER"]; a_ = wt / 2.0
        D.pl.append(([(-A + ch, -tb), (A - ch, -tb), (A, -tb + ch), (A, -ch), (A - ch, 0), (a_, 0), (a_, hw - ch), (a_ - ch, hw),
                      (-a_ + ch, hw), (-a_, hw - ch), (-a_, 0), (-A + ch, 0), (-A, -ch), (-A, -tb + ch)], True, "CBC_CONC", None))
    else:
        D.pl.append((outerpoly(P), True, "CBC_CONC", None))
    for j in range(nc):
        D.pl.append((cellpoly(P, j), True, "CBC_CONC", None))
    # blinding
    q = [(-A, -tb), (A, -tb), (A, -(tb + bl)), (-A, -(tb + bl))]
    D.hatches.append((q, "AR-SAND", "CBC_HATCH")); D.pl.append((q, True, "CBC_THIN", None))

    d1 = BD("OUT"); co = cv + d1 / 2.0; a = wt / 2.0; lap = P["LAP_MULT"] * d1
    lgA = (htot - 2 * cv) / 2.0 + lap / 2.0
    stg = min(0.65 * lap, (htot - 2 * cv) / 2.0 - lap / 2.0 - 100.0)          # (cbc:stg)
    # 01 top U-bar
    bar([(-a + co, hw - co - lgA - stg), (-a + co, hw - co), (a - co, hw - co), (a - co, hw - co - (lgA - stg))], "01", d1)
    if toe <= 0:
        # 02 base U-bar (legs inside 01)
        bar([(-a + co + d1, -tb + co + (lgA - stg)), (-a + co + d1, -tb + co), (a - co - d1, -tb + co),
             (a - co - d1, -tb + co + lgA + stg)], "02", d1)
    else:
        # with a toe the bottom bars run through to the toe edges and are capped there (free edge, 9.3.1.4);
        # the outer wall bars start from L-shaped starters anchored in the base (mark 21), lapped with 01 as before
        anch = P["ANCH_MULT"] * d1
        cap = P.get("FREE_EDGE_LEG") or max(2.0 * tb, anch)
        cap = min(cap, A - co - 50.0)
        bar([(-A + co + cap, -co), (-A + co, -co), (-A + co, -tb + co), (A - co, -tb + co), (A - co, -co), (A - co - cap, -co)], "02", d1)
        y0 = -tb + co + d1
        for sg, top in ((-1, -tb + co + (lgA - stg)), (1, -tb + co + lgA + stg)):
            x = sg * (a - co - d1)
            bar([(x - sg * anch, y0), (x, y0), (x, top)], "21", d1)
    c3, c4, d5, dd = BD("TOPIN"), BD("BOTIN"), BD("WALLIN"), BD("DIST")
    # 03 top slab bottom face, legs bent down into the outer walls
    y = shh + cv + c3 / 2.0; u = leg(P, c3, tw)
    bar([(-a + co + d1, y - u), (-a + co + d1, y), (a - co - d1, y), (a - co - d1, y - u)], "03", c3)
    # 04 base slab top face, legs bent up
    y = -(cv + c4 / 2.0); u = leg(P, c4, tw)
    bar([(-a + co + d1, y + u), (-a + co + d1, y), (a - co - d1, y), (a - co - d1, y + u)], "04", c4)
    # 05 outer wall inner face
    for sg in (-1, 1):
        x0 = sg * (wc / 2.0 + cv + d5 / 2.0); u = -sg * leg(P, d5, min(tt, tb))
        bar([(x0 + u, -tb + co + d1), (x0, -tb + co + d1), (x0, hw - co - d1), (x0 + u, hw - co - d1)], "05", d5)
    # 06 pier bars + 08 distribution on pier faces
    dp = BD("PIER")
    for j in range(1, nc):
        x1 = -wc / 2.0 + j * sw + (j - 1) * ti
        for x0, s in ((x1 + cv + dp / 2.0, -1.0), (x1 + ti - cv - dp / 2.0, 1.0)):
            u = s * leg(P, dp, min(tt, tb))
            bar([(x0 + u, -tb + co + d1), (x0, -tb + co + d1), (x0, hw - co - d1), (x0 + u, hw - co - d1)], "06", dp)
        for xx in (x1 + cv + dp + dd / 2.0, x1 + ti - cv - dp - dd / 2.0):
            _dots(D, (xx, cv + 100), (xx, shh - 100), BS("DIST"), dd)
        if j == 1:
            D.leaders.append(((x1 + cv + dp + dd / 2.0, cv + 100 + 2 * BS("DIST")), (x1 + 0.5 * sw, shh * 0.25),
                              MK("08", "DIST") + " (PIER FACES)", "CBC_RTXT"))
    # 07 haunch bars: diagonal parallel to the haunch face, carried to the outer mats, legs hl
    if hh > 0:
        nd = cv + BD("HCH") / 2.0
        nl = min(tt, tb, tw) - cv - d1 - dd - 6.0                              # (cbc:nlb)
        hl = P["ANCH_MULT"] * BD("HCH")
        k = hh - nd * SQ2
        for j in range(nc):
            x0 = -wt / 2.0 + tw + j * (sw + ti); x1 = x0 + sw
            for cx, cy, sx, sy in ((x0, 0, 1, 1), (x1, 0, -1, 1), (x1, shh, -1, -1), (x0, shh, 1, -1)):
                hp = lambda X, Y: (cx + sx * X, cy + sy * Y)
                bar([hp(k + nl + hl, -nl), hp(k + nl, -nl), hp(-nl, k + nl), hp(-nl, k + nl + hl)], "07", BD("HCH"))
    # 08 distribution dots
    y = hw - co - d1 / 2.0 - dd / 2.0; _dots(D, (-a + co + d1, y), (a - co - d1, y), BS("DIST"), dd)
    y = shh + cv + c3 + dd / 2.0;      _dots(D, (-wc / 2 + cv, y), (wc / 2 - cv, y), BS("DIST"), dd)
    y = -tb + co + d1 / 2.0 + dd / 2.0
    if toe > 0:
        _dots(D, (-A + co + d1, y), (A - co - d1, y), BS("DIST"), dd)
        for sg in (-1, 1):                                              # under the capped top face of each toe
            _dots(D, (sg * (A - co - d1), -co - d1 / 2.0 - dd / 2.0), (sg * (a + 60.0), -co - d1 / 2.0 - dd / 2.0), BS("DIST"), dd)
    else:
        _dots(D, (-a + co + d1, y), (a - co - d1, y), BS("DIST"), dd)
    y = -(cv + c4 + dd / 2.0);         _dots(D, (-wc / 2 + cv, y), (wc / 2 - cv, y), BS("DIST"), dd)
    for sg in (-1, 1):
        x = sg * (a - co - 1.5 * d1 - dd / 2.0); _dots(D, (x, cv + 100), (x, shh - 100), BS("DIST"), dd)
        x = sg * (wc / 2.0 + cv + d5 + dd / 2.0); _dots(D, (x, cv + 100), (x, shh - 100), BS("DIST"), dd)
    # labels
    L = D.leaders.append
    L(((0, hw - co), (a * 0.6, hw + 500), MK("01", "OUT"), "CBC_RTXT"))
    L(((0, -tb + co), (a * 0.6, -(tb + 500)), (MK("02", "OUT") if toe <= 0 else f"02-T{num(d1)}-{num(BS('OUT'))} (CAPPED AT TOE EDGES)"), "CBC_RTXT"))
    if toe > 0:
        L(((a - co - d1 - P["ANCH_MULT"] * d1 * 0.5, -tb + co + d1), (a * 0.82, shh * 0.12), f"21-T{num(d1)}-{num(BS('OUT'))} STARTERS", "CBC_RTXT"))
    L(((a * -0.3, shh + cv + c3 / 2.0), (a * -0.2, shh * 0.82), MK("03", "TOPIN"), "CBC_RTXT"))
    L(((a * -0.3, -(cv + c4 / 2.0)), (a * -0.2, shh * 0.18), MK("04", "BOTIN"), "CBC_RTXT"))
    L(((wc / 2.0 + cv + d5 / 2.0, shh * 0.55), (a * 0.25, shh * 0.63), MK("05", "WALLIN"), "CBC_RTXT"))
    if hh > 0:
        m = (hh - (cv + BD("HCH") / 2.0) * SQ2) / 2.0
        L(((-wc / 2.0 + m, shh - m), (a * -0.15, shh * 0.65), MK("07", "HCH"), "CBC_RTXT"))
    L(((wc / 2.0 + cv + d5 + dd / 2.0, shh * 0.35), (a * 0.25, shh * 0.27), MK("08", "DIST") + " (ALL FACES)", "CBC_RTXT"))
    if nc > 1:
        L(((-wc / 2.0 + sw + cv, shh * 0.45), (a * -0.1, shh * 0.45), MK("06", "PIER"), "CBC_RTXT"))
    # lap dimensions of the U-bars in the outer walls, C.J., LAP note
    D.dims.append(("v", htot / 2.0 - lap / 2.0 - tb - stg, htot / 2.0 + lap / 2.0 - tb - stg, -a, -(a + 350), None))
    D.dims.append(("v", htot / 2.0 - lap / 2.0 - tb + stg, htot / 2.0 + lap / 2.0 - tb + stg, a, a + 900, None))
    cjy = (hh if hh > 0 else 0.0) + 150.0                                      # (cbc:cjy)
    for sg in (-1, 1):
        D.lines.append(((sg * wc / 2.0, cjy), (sg * a, cjy), "CBC_THIN"))
    D.texts.append(((a + 60, cjy), 1.6, "C.J.", 0, 2, "CBC_TEXT"))
    D.texts.append(((-(a + 750), htot / 2.0 - tb - stg), 1.8, "LAP", 2, 2, "CBC_RTXT"))
    # overall dimensions
    xs = [-a, -wc / 2.0, wc / 2.0, a]
    for p, q2 in zip(xs, xs[1:]):
        D.dims.append(("h", p, q2, hw, hw + 900, None))
    if toe > 0:
        for p, q2 in ((-A, -a), (a, A)):
            D.dims.append(("h", p, q2, -(tb + bl), -(tb + bl + 300), None))
    ys = [-tb, 0, shh, hw]
    for p, q2 in zip(ys, ys[1:]):
        D.dims.append(("v", p, q2, a, a + 450, None))
    D.title = ((0.0, -(tb + 1100)), "SECTION B-B - BARREL REINFORCEMENT", int(round(2 * P["SC_RC"])))
    return D


# --------------------------------------------------------------------------- DXF renderer
def to_dxf(D: Drawing, path: str, origin=(200.0, 150.0)):
    import ezdxf
    from ezdxf.enums import TextEntityAlignment as TA
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    doc.header["$INSUNITS"] = 4; doc.header["$LTSCALE"] = 0.25; doc.header["$LWDISPLAY"] = 1
    for name, aci, lwt in SETUP_LAYERS:                       # (cbc:setup): colour and lineweight per layer
        doc.layers.add(name, color=aci, lineweight=lwt)
    doc.styles.add("CBC_ANNO", font="ARIALN.TTF")             # Arial Narrow
    sc = D.sc
    V = lambda p: (origin[0] + p[0] / sc, origin[1] + p[1] / sc)
    doc.dimstyles.new("CBC_DIM", dxfattribs=dict(              # the DIM* variables of (cbc:setup)
        dimtxsty="CBC_ANNO", dimtxt=3.0, dimasz=2.5, dimexo=1.0, dimexe=1.0, dimgap=0.8, dimdec=0, dimtad=1,
        dimtih=0, dimtoh=0, dimscale=1.0, dimlunit=2, dimzin=8, dimtofl=1, dimatfit=3, dimlfac=sc,
        dimclrd=4, dimclre=4, dimclrt=7, dimblk="", dimtsz=0.0))

    for pts, closed, layer, *_ in D.pl:
        msp.add_lwpolyline([V(p) for p in pts], close=closed, dxfattribs={"layer": layer})
    for pts, pat, layer in D.hatches:
        h = msp.add_hatch(dxfattribs={"layer": layer}); h.set_pattern_fill(pat, scale=0.025)      # (HT ... "AR-SAND" 0.01) x 2.5 override of RC_Extension3
        h.paths.add_polyline_path([V(p) for p in pts], is_closed=True)
    for x, y, d, layer in D.dots:                     # (DOT c d la): closed 2-vertex bulge polyline of width d/2
        c = V((x, y)); dp = max(0.8, d / sc)
        msp.add_lwpolyline([(c[0] - dp / 4, c[1], dp / 2, dp / 2, 1.0), (c[0] + dp / 4, c[1], dp / 2, dp / 2, 1.0)],
                           format="xyseb", close=True, dxfattribs={"layer": layer})
    for p, q, layer in D.lines:
        msp.add_line(V(p), V(q), dxfattribs={"layer": layer})
    JH = {0: "LEFT", 1: "CENTER", 2: "RIGHT"}; JV = {0: "", 1: "BOTTOM_", 2: "MIDDLE_", 3: "TOP_"}
    def text(p, h, s, jh, jv, layer, paper=False):
        t = msp.add_text(s, height=h * TXF, dxfattribs={"layer": layer, "style": "CBC_ANNO"})
        t.set_placement(p if paper else V(p), align=getattr(TA, (JV[jv] + JH[jh]) if jv else JH[jh]))
    for p, h, s, jh, jv, layer in D.texts:
        text(p, h, s, jh, jv, layer)
    for p, q, s, layer in D.leaders:                  # (LB p q s la): MLeader - arrow 3, dogleg 3, gap 1.2, text 4
        P0, Q0 = V(p), V(q); dr = 1.0 if Q0[0] >= P0[0] else -1.0
        tw_ = text_width(s, 4.0)
        land = Q0 if dr > 0 else (Q0[0] + tw_ + 1.2 + 3.0, Q0[1])          # landing point (end of the leader line)
        tx = (Q0[0] + 3.0 + 1.2, Q0[1]) if dr > 0 else Q0                   # text start (left, middle)
        ang = math.atan2(land[1] - P0[1], land[0] - P0[0]); e = (P0[0] + 3.0 * math.cos(ang), P0[1] + 3.0 * math.sin(ang))
        msp.add_line(P0, land, dxfattribs={"layer": layer})
        msp.add_lwpolyline([(P0[0], P0[1], 0.0, 1.0, 0.0), (e[0], e[1], 0.0, 0.0, 0.0)], format="xyseb", dxfattribs={"layer": layer})
        msp.add_line(land, (land[0] + dr * 3.0, land[1]), dxfattribs={"layer": layer})
        t = msp.add_text(s, height=4.0, dxfattribs={"layer": layer, "style": "CBC_ANNO"})
        t.set_placement(tx, align=TA.MIDDLE_LEFT)
    for kind, p, q, at, loc, ov in D.dims:
        if kind == "h":
            dm = msp.add_linear_dim(base=V(((p + q) / 2, loc)), p1=V((p, at)), p2=V((q, at)), angle=0, dimstyle="CBC_DIM",
                                    text=ov or "<>", dxfattribs={"layer": "CBC_DIM"})
        else:
            dm = msp.add_linear_dim(base=V((loc, (p + q) / 2)), p1=V((at, p)), p2=V((at, q)), angle=90, dimstyle="CBC_DIM",
                                    text=ov or "<>", dxfattribs={"layer": "CBC_DIM"})
        dm.render()
    if D.title:
        p, s, scale = D.title; pp = V(p)
        text(pp, 3.5, "%%U" + s, 1, 0, "CBC_TITLE", paper=True)
        text((pp[0], pp[1] - 9.0), 2.0, f"SCALE 1 : {scale} (A3)", 1, 0, "CBC_TEXT", paper=True)
    doc.saveas(path)
    return path


# --------------------------------------------------------------------------- matplotlib renderer
# colours of the bar marks on screen (the DXF keeps every bar on the red rebar layer, as on the drawings)
MARK_COLOURS = {"01": "#ff3b30", "02": "#ff9500", "03": "#ffd60a", "04": "#34c759", "05": "#00c7be", "06": "#32ade6",
                "07": "#bf5af2", "08": "#ff2d92", "21": "#a2845e", "22": "#ffffff"}
MARK_NAMES = {"01": "top U-bar", "02": "base bottom bar", "03": "top slab, inner face", "04": "base slab, inner face",
              "05": "outer wall, inner face", "06": "pier wall", "07": "haunch bar", "08": "distribution (dots)",
              "21": "outer wall starter", "22": "shear link"}


def to_mpl(D: Drawing, ax, dark=True, window=None, annotate=True, by_mark=False, fill=True, min_bar_pt=0.9, legend=False, title=None):
    """Draw in real mm.  Bars are drawn at their true diameter (never thinner than min_bar_pt) so the
    reinforcement reads at any zoom; by_mark colours each bar mark; window = (x0, x1, y0, y1) zooms on a detail."""
    import matplotlib.patches as mp
    from matplotlib.collections import LineCollection, PatchCollection
    from matplotlib.lines import Line2D
    sc = D.sc; ci = 1 if dark else 2
    col = lambda la: LAYERS[la][ci]
    bg = "#000000" if dark else "#ffffff"
    ax.set_facecolor(bg); ax.set_aspect("equal")
    for s in ax.spines.values(): s.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    # extents
    xs = [p[0] for pts, *_ in D.pl for p in pts]; ys = [p[1] for pts, *_ in D.pl for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if window: ax.set_xlim(window[0], window[1]); ax.set_ylim(window[2], window[3])
    elif annotate: ax.set_xlim(x0 - 58 * sc, x1 + 62 * sc); ax.set_ylim(y0 - 68 * sc, y1 + 56 * sc)
    else: ax.set_xlim(x0 - 8 * sc, x1 + 8 * sc); ax.set_ylim(y0 - 8 * sc, y1 + 8 * sc)
    ax.figure.canvas.draw()
    pt_per_mm = abs(ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0]) * 72.0 / ax.figure.dpi
    fs = lambda paper_h: max(3.0, paper_h * sc * pt_per_mm * 0.95)           # cap height ~ text height
    lw = lambda paper_w: max(0.35, paper_w * sc * pt_per_mm)
    px = lambda n: n * 72.0 / ax.figure.dpi                                  # interface text sized in screen pixels

    conc = [(pts, closed) for pts, closed, la, *_ in D.pl if la == "CBC_CONC"]
    if fill and conc:                                    # concrete shaded, openings cleared: the bars stand out
        big = max(conc, key=lambda c: max(p[0] for p in c[0]) - min(p[0] for p in c[0]))
        ax.add_patch(mp.Polygon(big[0], closed=True, facecolor="#2b3540" if dark else "#e3e8ee", edgecolor="none", zorder=0.5))
        for pts, closed in conc:
            if pts is not big[0]: ax.add_patch(mp.Polygon(pts, closed=True, facecolor=bg, edgecolor="none", zorder=0.6))
    for pts, pat, layer in D.hatches:
        ax.add_patch(mp.Polygon(pts, closed=True, facecolor="none", edgecolor=col(layer), hatch="....", lw=0, zorder=1))
    for layer in ("CBC_THIN", "CBC_CONC"):
        segs = [list(pts) + ([pts[0]] if closed else []) for pts, closed, la, *_ in D.pl if la == layer]
        w = {"CBC_CONC": 0.35, "CBC_THIN": 0.13}[layer]
        ax.add_collection(LineCollection(segs, colors=col(layer), linewidths=lw(w), zorder=2, capstyle="round", joinstyle="round"))
    seen = {}
    for item in D.pl:
        pts, closed, la, mark = item[0], item[1], item[2], item[3]; dia = item[4] if len(item) > 4 and item[4] else 12.0
        if la != "CBC_REBAR": continue
        c = MARK_COLOURS.get(str(mark)[:2], col(la)) if by_mark else col(la)
        ax.add_collection(LineCollection([list(pts)], colors=c, linewidths=max(min_bar_pt, dia * pt_per_mm), zorder=3,
                                         capstyle="round", joinstyle="round"))
        seen[str(mark)[:2]] = c
    rmin = min_bar_pt / pt_per_mm * 0.75                 # dots never smaller than a readable bar
    dc = MARK_COLOURS["08"] if by_mark else col("CBC_REBAR")
    ax.add_collection(PatchCollection([mp.Circle((x, y), max(d / 2.0, rmin)) for x, y, d, _ in D.dots],
                                      facecolor=dc, edgecolor="none", zorder=4))
    if D.dots: seen["08"] = dc
    if legend and by_mark:
        hs = [Line2D([0], [0], color=c, lw=3, label=f"{m}  {MARK_NAMES.get(m, '')}") for m, c in sorted(seen.items())]
        leg = ax.legend(handles=hs, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=min(9, len(hs)), frameon=False, fontsize=px(11),
                        labelcolor="#ffffff" if dark else "#111111", handlelength=1.4, columnspacing=1.0, borderaxespad=0.0)
    if title: ax.text(0.01, 0.985, title, transform=ax.transAxes, color="#ffff00" if dark else "#1b3a5c", fontsize=px(12), va="top", ha="left", zorder=9)
    if not annotate: return
    for p, q, layer in D.lines:
        ax.plot([p[0], q[0]], [p[1], q[1]], color=col(layer), lw=lw(0.13), zorder=2)
    HA = {0: "left", 1: "center", 2: "right"}; VA = {0: "baseline", 1: "bottom", 2: "center", 3: "top"}
    for p, h, s, jh, jv, layer in D.texts:
        ax.text(p[0], p[1], s, color=col(layer), fontsize=fs(h * TXF), ha=HA[jh], va=VA[jv], zorder=6)
    for p, q, s, layer in D.leaders:
        dr = 1.0 if q[0] >= p[0] else -1.0; c = col(layer)
        land = q if dr > 0 else (q[0] + (text_width(s, 4.0) + 1.2 + 3.0) * sc, q[1])
        tx = (q[0] + 4.2 * sc, q[1]) if dr > 0 else q
        ax.annotate("", xy=p, xytext=land, zorder=5,
                    arrowprops=dict(arrowstyle="-|>,head_length=%.2f,head_width=%.2f" % (fs(3.0) * 0.08, fs(3.0) * 0.03),
                                    color=c, lw=lw(0.13), shrinkA=0, shrinkB=0))
        ax.plot([land[0], land[0] + dr * 3.0 * sc], [land[1], land[1]], color=c, lw=lw(0.13), zorder=5)
        t = ax.text(tx[0], tx[1], s, color=c, fontsize=fs(4.0), ha="left", va="center", zorder=6)
        _fit_width(ax, t, text_width(s, 4.0) * sc)
    cd = col("CBC_DIM"); ct = col("CBC_TEXT"); ex = 1.0 * sc
    for kind, p, q, at, loc, ov in D.dims:
        s = ov or num(abs(q - p))
        if kind == "h":
            sg = 1 if loc >= at else -1
            for x in (p, q): ax.plot([x, x], [at + sg * ex, loc + sg * ex], color=cd, lw=lw(0.1), zorder=2)
            ax.annotate("", xy=(p, loc), xytext=(q, loc), arrowprops=dict(arrowstyle="<|-|>,head_length=0.25,head_width=0.09", color=cd, lw=lw(0.1), shrinkA=0, shrinkB=0))
            ax.text((p + q) / 2, loc + 0.8 * sc, s, color=ct, fontsize=fs(3.0), ha="center", va="bottom", zorder=6)
        else:
            sg = 1 if loc >= at else -1
            for y in (p, q): ax.plot([at + sg * ex, loc + sg * ex], [y, y], color=cd, lw=lw(0.1), zorder=2)
            ax.annotate("", xy=(loc, p), xytext=(loc, q), arrowprops=dict(arrowstyle="<|-|>,head_length=0.25,head_width=0.09", color=cd, lw=lw(0.1), shrinkA=0, shrinkB=0))
            ax.text(loc - 0.8 * sc, (p + q) / 2, s, color=ct, fontsize=fs(3.0), ha="right", va="center", rotation=90, zorder=6)
    if D.title:
        p, s, scale = D.title
        t = ax.text(p[0], p[1], s, color=col("CBC_TITLE"), fontsize=fs(3.5 * TXF), ha="center", va="baseline", zorder=6)
        ax.figure.canvas.draw()
        bb = t.get_window_extent().transformed(ax.transData.inverted())
        ax.plot([bb.x0, bb.x1], [p[1] - 1.2 * sc, p[1] - 1.2 * sc], color=col("CBC_TITLE"), lw=lw(0.25), zorder=6)
        ax.text(p[0], p[1] - 9.0 * sc, f"SCALE 1 : {scale} (A3)", color=ct, fontsize=fs(2.0 * TXF), ha="center", va="baseline", zorder=6)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Section B-B barrel reinforcement from CBC_EXPORT.txt")
    ap.add_argument("--export", help="CBC_EXPORT.txt (omit for the built-in 4-cell 1500x1500 defaults)")
    ap.add_argument("--dxf"); ap.add_argument("--png"); ap.add_argument("--light", action="store_true")
    a = ap.parse_args()
    D = build(read_export(a.export) if a.export else {})
    for w in D.warnings: print("WARNING:", w)
    print(f"{len(D.bars())} bars, {len(D.dots)} dots, {len(D.leaders)} labels, {len(D.dims)} dimensions")
    if a.dxf: print("DXF:", to_dxf(D, a.dxf))
    if a.png:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(16, 7.4), facecolor="#000000" if not a.light else "#ffffff")
        ax = fig.add_axes([0, 0, 1, 1]); to_mpl(D, ax, dark=not a.light); fig.savefig(a.png, dpi=120, facecolor=fig.get_facecolor())
        print("PNG:", a.png)
