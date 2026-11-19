"""
Write the recorded drawing (acad.Document) to DXF: model space, every paper-space layout with its
viewports, layers, text and dimension styles, blocks, hatches, leaders, tables and logo images.
"""
from __future__ import annotations
import math, os
import ezdxf
from ezdxf.math import Vec2
from ezdxf.enums import TextEntityAlignment as TA
from . import geom, metrics, fields

JUST = {(0, 0): TA.LEFT, (1, 0): TA.CENTER, (2, 0): TA.RIGHT,
        (0, 1): TA.BOTTOM_LEFT, (1, 1): TA.BOTTOM_CENTER, (2, 1): TA.BOTTOM_RIGHT,
        (0, 2): TA.MIDDLE_LEFT, (1, 2): TA.MIDDLE_CENTER, (2, 2): TA.MIDDLE_RIGHT,
        (0, 3): TA.TOP_LEFT, (1, 3): TA.TOP_CENTER, (2, 3): TA.TOP_RIGHT, (4, 0): TA.MIDDLE}
AX_ALIGN = {0: (0, 0), 1: (1, 0), 2: (2, 0), 4: (1, 2), 6: (0, 3), 7: (1, 3), 8: (2, 3), 9: (0, 2), 10: (1, 2), 11: (2, 2),
            12: (0, 1), 13: (1, 1), 14: (2, 1)}
FONT_FILE = {"ARIAL NARROW": "ARIALN.TTF", "ARIAL": "arial.ttf"}


def _attr(e, **extra):
    a = {"layer": e.p.get("LAYER", "0")}
    if "COLOR" in e.p and isinstance(e.p["COLOR"], (int, float)): a["color"] = int(e.p["COLOR"])
    if e.p.get("LINETYPE"): a["linetype"] = e.p["LINETYPE"]
    a.update(extra); return a


def _num(v, d=0.0):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else d


class Exporter:
    def __init__(self, rec, image_paths="original", leaders="mleader", dxfversion="R2018"):
        self.rec = rec; self.image_paths = image_paths; self.leaders = leaders
        self.doc = ezdxf.new(dxfversion, setup=True)
        self.doc.header["$INSUNITS"] = 4; self.doc.header["$MEASUREMENT"] = 1
        self.doc.header["$LTSCALE"] = _num(rec.interp.sysvars.get("LTSCALE"), 1.0)
        self.doc.header["$LWDISPLAY"] = 1
        self.imgdefs = {}
        self.stats = {}

    # ------------------------------------------------------------------ tables of the drawing
    def setup(self):
        d = self.doc; r = self.rec
        for name in ("HIDDEN", "CENTER", "DASHED"):
            if name not in d.linetypes: d.linetypes.add(name, pattern=[0.5, 0.25, -0.25])
        for L in r.layers:
            n = L.p["NAME"]
            lay = d.layers.get(n) if n in d.layers else d.layers.add(n)
            lay.color = int(_num(L.p.get("COLOR"), 7)) or 7
            lt = L.p.get("LINETYPE")
            lay.dxf.linetype = lt if isinstance(lt, str) and lt in d.linetypes else "Continuous"
            lw = int(_num(L.p.get("LINEWEIGHT"), -3)); lay.dxf.lineweight = lw
            if L.p.get("PLOTTABLE") is False: lay.dxf.plot = 0
        for S in r.textstyles:
            n = S.p["NAME"]; face = str(S.p.get("TYPEFACE", "Arial"))
            if n in d.styles: st = d.styles.get(n); st.dxf.font = FONT_FILE.get(face.upper(), "arial.ttf")
            else: st = d.styles.add(n, font=FONT_FILE.get(face.upper(), "arial.ttf"))
            st.dxf.height = _num(S.p.get("HEIGHT"), 0.0); st.dxf.width = _num(S.p.get("WIDTH"), 1.0) or 1.0
        for DS in r.dimstyles:
            n = DS.p["NAME"]; V = DS.p.get("VARS", {}) or {}
            if n in d.dimstyles: continue
            attrs = {}
            for k, v in V.items():
                kk = k.lower()
                if kk in ("dimstyle",): continue
                if kk == "dimblk":
                    continue
                if isinstance(v, (int, float, str)) and not isinstance(v, bool): attrs[kk] = v
            try:
                d.dimstyles.new(n, dxfattribs=attrs)
            except Exception:                       # unknown variable for this DXF version: fall back to the essentials
                d.dimstyles.new(n, dxfattribs={k: attrs[k] for k in ("dimtxt", "dimasz", "dimexo", "dimexe", "dimgap", "dimdec", "dimtad",
                                                                       "dimclrd", "dimclre", "dimclrt", "dimtxsty") if k in attrs})
        for name, blk in r.blocks.items():
            b = d.blocks.new(blk.p["NAME"])
            for e in blk.live(): self.entity(b, e)

    # ------------------------------------------------------------------ entities
    def entity(self, sp, e):
        t = e.t; p = e.p
        self.stats[t] = self.stats.get(t, 0) + 1
        if t == "LINE":
            sp.add_line(p["P1"][:2], p["P2"][:2], dxfattribs=_attr(e))
        elif t == "LWPOLYLINE":
            cw = p.get("CONSTWIDTH") or 0.0
            pts = [(v["p"][0], v["p"][1], v["sw"] if v["sw"] is not None else cw, v["ew"] if v["ew"] is not None else cw, v["b"]) for v in p["VERTS"]]
            pl = sp.add_lwpolyline(pts, format="xyseb", close=p["CLOSED"], dxfattribs=_attr(e))
            if cw: pl.dxf.const_width = cw
        elif t == "CIRCLE":
            sp.add_circle(p["CENTER"][:2], p["RADIUS"], dxfattribs=_attr(e))
        elif t == "ARC":
            sp.add_arc(p["CENTER"][:2], p["RADIUS"], math.degrees(p["A0"]), math.degrees(p["A1"]), dxfattribs=_attr(e))
        elif t == "SOLID":
            sp.add_solid([q[:2] for q in p["PTS"]], dxfattribs=_attr(e))
        elif t == "POINT":
            sp.add_point(p["P1"][:2], dxfattribs=_attr(e))
        elif t == "TEXT":
            self.text(sp, e)
        elif t == "MTEXT":
            m = sp.add_mtext(p["TEXTSTRING"], dxfattribs=_attr(e, style=p.get("STYLENAME", "Standard"), char_height=float(p["HEIGHT"]),
                                                             attachment_point=int(_num(p.get("ATTACHMENTPOINT"), 1)) or 1))
            m.dxf.insert = p["INSERTIONPOINT"][:2]
            if _num(p.get("WIDTH")) > 0: m.dxf.width = float(p["WIDTH"])
            if _num(p.get("ROTATION")): m.dxf.rotation = math.degrees(p["ROTATION"])
        elif t == "INSERT":
            sp.add_blockref(p["NAME"], p["INSERTIONPOINT"][:2], dxfattribs=_attr(e, xscale=p.get("XSCALE", 1.0), yscale=p.get("YSCALE", 1.0),
                                                                              rotation=math.degrees(_num(p.get("ROTATION")))))
        elif t == "DIMENSION":
            self.dimension(sp, e)
        elif t == "MULTILEADER":
            self.mleader(sp, e)
        elif t == "HATCH":
            self.hatch(sp, e)
        elif t == "ACAD_TABLE":
            self.table(sp, e)
        elif t == "IMAGE":
            self.image(sp, e)
        elif t == "VIEWPORT":
            self.viewport(sp, e)
        else:
            raise ValueError(f"export: unsupported entity {t}")

    def text(self, sp, e):
        p = e.p; jh, jv = int(_num(p.get("JH"))), int(_num(p.get("JV")))
        if not (jh or jv) and p.get("ALIGNMENT") is not None:
            jh, jv = AX_ALIGN.get(int(_num(p.get("ALIGNMENT"))), (0, 0))
        tx = sp.add_text(p["TEXTSTRING"], height=float(p["HEIGHT"]), dxfattribs=_attr(e, style=p.get("STYLENAME", "Standard"),
                         rotation=math.degrees(_num(p.get("ROTATION"))), width=_num(p.get("SCALEFACTOR"), 1.0) or 1.0))
        pt = (p["TEXTALIGNMENTPOINT"] if (jh or jv) else p["INSERTIONPOINT"])[:2]
        tx.set_placement(pt, align=JUST.get((jh, jv), TA.LEFT))

    def dimension(self, sp, e):
        p = e.p; a, b, loc = p["P1"][:2], p["P2"][:2], p["LOC"][:2]
        ov = {"dimlfac": float(p.get("LINEARSCALEFACTOR", 1.0) or 1.0)}
        if p.get("EXTLINE1SUPPRESS"): ov["dimse1"] = 1
        if p.get("EXTLINE2SUPPRESS"): ov["dimse2"] = 1
        if "ARROWHEADSIZE" in p: ov["dimasz"] = float(p["ARROWHEADSIZE"])
        text = p.get("TEXTOVERRIDE") or "<>"
        style = p.get("STYLENAME", "Standard")
        if style not in self.doc.dimstyles: style = "Standard"
        if p.get("DIMKIND") == "rotated":
            dm = sp.add_linear_dim(base=loc, p1=a, p2=b, angle=math.degrees(p.get("ROTATION", 0.0)), dimstyle=style, text=text,
                                   override=ov, dxfattribs=_attr(e))
        else:
            g = geom.dim_geometry(e)
            dm = sp.add_aligned_dim(p1=a, p2=b, distance=g["da"], dimstyle=style, text=text, override=ov, dxfattribs=_attr(e))
        dm.render()
        d = dm.dimension
        if d.dxf.get("text_midpoint") is None:               # blank-text range marks: the group is still required
            d.dxf.text_midpoint = tuple(geom.dim_text_position(e))

    def mleader(self, sp, e):
        g = geom.mleader_geometry(e); p = e.p; text = p.get("TEXTSTRING", "") or ""
        style = p.get("TEXTSTYLENAME", "Standard")
        if self.leaders == "mleader":
            try:
                from ezdxf.render import mleader as ML
                bld = sp.add_multileader_mtext("Standard")
                bld.set_content(text, style=style if style in self.doc.styles else "Standard", char_height=g["th"])
                bld.set_connection_properties(landing_gap=g["gap"], dogleg_length=g["dog"])
                bld.set_arrow_properties(size=g["asz"])
                bld.set_connection_types(left=ML.HorizontalConnection.middle_of_text, right=ML.HorizontalConnection.middle_of_text)
                side = ML.ConnectionSide.left if g["dr"] > 0 else ML.ConnectionSide.right
                bld.add_leader_line(side, [Vec2(g["arrow"])] + [Vec2(m) for m in g["mid"]])
                # content insert = top-left of the text; the landing must fall on g["land"]
                bld.build(insert=Vec2(g["tx0"], g["land"][1] + g["th"] * 0.5))
                ml = bld.multileader; ml.dxf.layer = p.get("LAYER", "0")
                # the builder estimates the text width itself; store the geometry AutoCAD produces instead
                from ezdxf.math import Vec3
                L = ml.context.leaders[0]
                L.last_leader_point = Vec3(g["land"][0], g["land"][1], 0.0)
                L.dogleg_vector = Vec3(g["dr"], 0.0, 0.0); L.dogleg_length = g["dog"]
                L.lines[0].vertices = [Vec3(g["arrow"][0], g["arrow"][1], 0.0)] + [Vec3(m[0], m[1], 0.0) for m in g["mid"]]
                ml.context.base_point = Vec3(g["land"][0] + g["dr"] * g["dog"], g["land"][1], 0.0)
                ml.context.mtext.insert = Vec3(g["tx0"], g["land"][1] + g["ht"] / 2.0, 0.0)
                return
            except Exception:                                   # fall through to plain geometry
                self.stats["MLEADER_AS_GEOMETRY"] = self.stats.get("MLEADER_AS_GEOMETRY", 0) + 1
        la = {"layer": p.get("LAYER", "0")}
        pts = [g["arrow"]] + g["mid"] + [g["land"]]
        for a, b in zip(pts, pts[1:]): sp.add_line(a, b, dxfattribs=la)
        sp.add_line(g["land"], (g["land"][0] + g["dr"] * g["dog"], g["land"][1]), dxfattribs=la)
        ax, ay = g["arrow"]; nx, ny = pts[1]; d = math.hypot(nx - ax, ny - ay) or 1.0; ux, uy = (nx - ax) / d, (ny - ay) / d
        s = g["asz"]; bx, by = ax + ux * s, ay + uy * s; hw = s / 6.0
        sp.add_solid([(ax, ay), (bx - uy * hw, by + ux * hw), (bx + uy * hw, by - ux * hw)], dxfattribs=la)
        if text.strip():
            m = sp.add_mtext(text, dxfattribs=dict(la, style=style, char_height=g["th"], attachment_point=4))
            m.dxf.insert = (g["tx0"], g["land"][1])

    def hatch(self, sp, e):
        p = e.p; name = str(p.get("PATTERNNAME", "SOLID")).upper()
        h = sp.add_hatch(dxfattribs=_attr(e))
        if name == "SOLID": h.set_solid_fill()
        else:
            try: h.set_pattern_fill(name, scale=float(p.get("PATTERNSCALE", 1.0) or 1.0), angle=math.degrees(_num(p.get("PATTERNANGLE"))))
            except Exception: h.set_pattern_fill("ANSI31", scale=float(p.get("PATTERNSCALE", 1.0) or 1.0))
        for kind, loops in p.get("LOOPS", []):
            for loop in loops:
                h.paths.add_polyline_path([(x, y) for x, y in loop], is_closed=True, flags=1 if kind == "outer" else 16)

    def table(self, sp, e):
        """TABLE objects are written as their grid and cell texts (same geometry AutoCAD lays out)."""
        p = e.p; rows = geom.table_rows(e); cols = p["COLW"]; ip = p["INSERTIONPOINT"]; la = {"layer": p.get("LAYER", "0")}
        xs = [ip[0]]; ys = [ip[1]]
        for w in cols: xs.append(xs[-1] + w)
        for h in rows: ys.append(ys[-1] - h)
        nr, nc = len(rows), len(cols); seen = set()
        hm = float(p.get("HORZCELLMARGIN", 1.5)); vm = float(p.get("VERTCELLMARGIN", 1.5))
        edges = set()
        for r in range(nr):
            for c in range(nc):
                r0, r1, c0, c1 = geom.table_cell_span(e, r, c)
                if (r0, c0) in seen: continue
                seen.add((r0, c0))
                x0, x1, y0, y1 = xs[c0], xs[c1 + 1], ys[r1 + 1], ys[r0]
                for seg in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                    k = tuple(sorted((tuple(round(v, 4) for v in seg[0]), tuple(round(v, 4) for v in seg[1]))))
                    edges.add(k)
                cell = p["CELLS"].get((r0, c0), {}); txt = fields.resolve(cell.get("text", "") or "", self.rec)
                if not txt.strip(): continue
                h = float(cell.get("height", p.get("DEFTEXTH", 6.0 if r0 == 0 else 4.5)))
                al = int(_num(cell.get("align"), 5)) or 5
                col, row = (al - 1) % 3, (al - 1) // 3
                px = (x0 + hm, (x0 + x1) / 2, x1 - hm)[col]; py = (y1 - vm, (y0 + y1) / 2, y0 + vm)[row]
                sty = cell.get("style", "Standard")
                m = sp.add_mtext(txt, dxfattribs=dict(la, style=sty if sty in self.doc.styles else "Standard", char_height=h, attachment_point=al))
                m.dxf.insert = (px, py); m.dxf.width = max(x1 - x0 - 2 * hm, 0.1)
        # merge collinear grid segments are not needed: each edge once
        for a, b in sorted(edges): sp.add_line(a, b, dxfattribs=la)

    def image(self, sp, e):
        p = e.p
        path = p["LOCALFILE"] if self.image_paths == "local" else p["IMAGEFILE"]
        if self.image_paths == "relative": path = os.path.join("LOGO_FLAT", os.path.basename(p["LOCALFILE"])).replace("/", "\\")
        idef = self.imgdefs.get(path)
        if idef is None:
            idef = self.doc.add_image_def(filename=path, size_in_pixel=p["PIXELS"]); self.imgdefs[path] = idef
        sp.add_image(idef, insert=p["ORIGIN"][:2], size_in_units=(p["IMAGEWIDTH"], p["IMAGEHEIGHT"]), rotation=math.degrees(_num(p.get("ROTATION"))),
                     dxfattribs={"layer": p.get("LAYER", "0")})

    def viewport(self, layout, e):
        p = e.p; sc = float(p.get("CUSTOMSCALE", 1.0) or 1.0)
        mc = (p["TARGET"][0] + p["VIEWCENTER"][0], p["TARGET"][1] + p["VIEWCENTER"][1])
        vp = layout.add_viewport(center=p["CENTER"][:2], size=(p["WIDTH"], p["HEIGHT"]), view_center_point=mc, view_height=p["HEIGHT"] / sc,
                                 dxfattribs={"layer": p.get("LAYER", "0")})
        if p.get("DISPLAYLOCKED"): vp.dxf.flags = vp.dxf.flags | 16384
        return vp

    # ------------------------------------------------------------------ whole drawing
    def run(self):
        self.setup(); msp = self.doc.modelspace()
        for e in self.rec.model.live(): self.entity(msp, e)
        lays = sorted((L for L in self.rec.layouts if L.p["NAME"].upper() != "MODEL"), key=lambda L: _num(L.p.get("TABORDER"), 0))
        for L in lays:
            n = L.p["NAME"]
            lay = self.doc.layouts.get(n) if n in self.doc.layouts.names() else self.doc.layouts.new(n)
            lay.page_setup(size=(420, 297), margins=(0, 0, 0, 0), units="mm")
            lay.dxf.plot_layout_flags = lay.dxf.plot_layout_flags | 32      # plot styles on
            if L.p.get("STYLESHEET"): lay.dxf.current_style_sheet = str(L.p["STYLESHEET"])
            for e in L.block.live(): self.entity(lay, e)
        keep = {L.p["NAME"] for L in lays}
        for name in [n for n in self.doc.layouts.names() if n != "Model" and n not in keep]:
            self.doc.layouts.delete(name)                    # the template "Layout1" is not part of the set
        if lays: self.doc.layouts.set_active_layout(lays[0].p["NAME"]) if hasattr(self.doc.layouts, "set_active_layout") else None
        return self.doc


def to_dxf(rec, path, **kw):
    ex = Exporter(rec, **kw); doc = ex.run(); doc.saveas(path)
    return ex
