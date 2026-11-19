"""
AutoCAD DXF generator for the box culvert detail. Units = mm (model space).
Draws: concrete outline (section), centre-line dims, reinforcement on each
face with bar callouts, a notes block and a bar-bending schedule table.
Opens natively in AutoCAD / BricsCAD / any DXF reader.
"""
from __future__ import annotations
import ezdxf
from ezdxf.enums import TextEntityAlignment

LAYERS = {
    "CONCRETE": 7, "REBAR": 1, "DIMS": 3, "TEXT": 2, "HATCH": 8,
    "TITLE": 5, "GRID": 8,
}

def _setup(doc):
    for name, col in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=col)
    try:
        doc.styles.add("ROMANS", font="romans.shx")
    except Exception:
        pass

def _text(msp, s, x, y, h, layer="TEXT", align="LEFT"):
    t = msp.add_text(s, height=h, dxfattribs={"layer": layer})
    amap = {"LEFT": TextEntityAlignment.LEFT, "CENTER": TextEntityAlignment.MIDDLE_CENTER,
            "RIGHT": TextEntityAlignment.RIGHT}
    t.set_placement((x, y), align=amap.get(align, TextEntityAlignment.LEFT))
    return t

def export_dxf(path, p, faces, title="BOX CULVERT - TYPICAL CROSS SECTION"):
    """faces: dict with keys top/bottom/left/right -> (dia, spacing) outer & inner."""
    doc = ezdxf.new("R2010", setup=True)
    _setup(doc); msp = doc.modelspace()
    mm = 1000.0
    Ls = p.clear_span*mm; H = p.clear_height*mm
    tt, tb, tw = p.t_top*mm, p.t_bot*mm, p.t_wall*mm
    # outer rectangle corners (origin at bottom-left OUTER)
    OW = Ls + 2*tw; OH = H + tt + tb
    # concrete outline: outer box
    msp.add_lwpolyline([(0,0),(OW,0),(OW,OH),(0,OH)], close=True,
                       dxfattribs={"layer":"CONCRETE"})
    # inner opening
    ix0, iy0 = tw, tb
    msp.add_lwpolyline([(ix0,iy0),(ix0+Ls,iy0),(ix0+Ls,iy0+H),(ix0,iy0+H)],
                       close=True, dxfattribs={"layer":"CONCRETE"})
    # concrete hatch between outer and inner
    h = msp.add_hatch(color=8, dxfattribs={"layer":"HATCH"})
    h.set_pattern_fill("ANSI31", scale=20)
    h.paths.add_polyline_path([(0,0),(OW,0),(OW,OH),(0,OH)], is_closed=True)
    h.paths.add_polyline_path([(ix0,iy0),(ix0+Ls,iy0),(ix0+Ls,iy0+H),(ix0,iy0+H)],
                              is_closed=True, flags=0)
    # ---- reinforcement (schematic lines offset by cover) ----
    cov = p.cover*mm
    def rebar_line(pts): msp.add_lwpolyline(pts, dxfattribs={"layer":"REBAR"})
    # top slab: bottom face (inner) + top face (outer)
    rebar_line([(tw+cov, OH-cov),(OW-tw-cov, OH-cov)])          # top face
    rebar_line([(tw+cov, iy0+H+cov),(OW-tw-cov, iy0+H+cov)])    # inner face
    # bottom slab
    rebar_line([(tw+cov, cov),(OW-tw-cov, cov)])                # bottom face
    rebar_line([(tw+cov, iy0-cov),(OW-tw-cov, iy0-cov)])        # inner face
    # walls (vertical bars) left & right, outer + inner
    rebar_line([(cov, cov),(cov, OH-cov)])
    rebar_line([(ix0-cov, tb),(ix0-cov, tb+H)])
    rebar_line([(OW-cov, cov),(OW-cov, OH-cov)])
    rebar_line([(ix0+Ls+cov, tb),(ix0+Ls+cov, tb+H)])
    # ---- bar callouts ----
    def callout(x, y, dia, sp, face):
        _text(msp, f"T{dia}-{sp} ({face})", x, y, 60, layer="TEXT")
    callout(OW/2, OH+120, *faces["top"][0], "top slab-outer")
    callout(OW/2, iy0+H+120, *faces["top"][1], "top slab-inner")
    callout(OW/2, -180, *faces["bottom"][0], "base-outer")
    callout(OW/2, iy0-200, *faces["bottom"][1], "base-inner")
    _text(msp, f"T{faces['left'][0][0]}-{faces['left'][0][1]} (walls V)",
          -cov-900, OH/2, 60, layer="TEXT")
    # ---- dimensions ----
    dim_off = 500
    d = msp.add_linear_dim(base=(0,-dim_off), p1=(0,0), p2=(OW,0),
                           dxfattribs={"layer":"DIMS"}); d.render()
    d = msp.add_linear_dim(base=(-dim_off,0), p1=(0,0), p2=(0,OH), angle=90,
                           dxfattribs={"layer":"DIMS"}); d.render()
    d = msp.add_linear_dim(base=(0,OH+dim_off), p1=(tw,OH), p2=(tw+Ls,OH),
                           dxfattribs={"layer":"DIMS"}); d.render()
    d = msp.add_linear_dim(base=(OW+dim_off,tb), p1=(OW,tb), p2=(OW,tb+H), angle=90,
                           dxfattribs={"layer":"DIMS"}); d.render()
    # ---- title + notes ----
    _text(msp, title, OW/2, -1200, 110, layer="TITLE", align="CENTER")
    notes = [
        f"Clear span x height : {p.clear_span:.2f} m x {p.clear_height:.2f} m",
        f"Slabs t_top/t_bot : {p.t_top*1000:.0f} / {p.t_bot*1000:.0f} mm",
        f"Walls : {p.t_wall*1000:.0f} mm   Cover : {p.cover*1000:.0f} mm",
        f"Concrete C{p.fck:.0f}/{p.fck+8:.0f}   Steel fyk {p.fyk:.0f} MPa",
        f"Earth cover : {p.cover_fill:.2f} m   Surcharge : {p.surcharge:.0f} kPa",
    ]
    for i, n in enumerate(notes):
        _text(msp, n, -dim_off-200, -1600 - i*180, 90, layer="TEXT")
    # ---- bar bending schedule table ----
    tx, ty = OW + 2500, OH
    _text(msp, "BAR BENDING SCHEDULE", tx, ty+200, 110, layer="TITLE")
    rows = [("Mark","Member","Bar","Spacing","Shape")]
    marks = ["01","02","03","04","05","06","07","08"]
    data = [("Top slab-outer",)+faces["top"][0],
            ("Top slab-inner",)+faces["top"][1],
            ("Base-outer",)+faces["bottom"][0],
            ("Base-inner",)+faces["bottom"][1],
            ("Wall-outer",)+faces["left"][0],
            ("Wall-inner",)+faces["left"][1]]
    for i,(mem,dia,sp) in enumerate(data):
        rows.append((marks[i], mem, f"T{dia}", f"{sp} c/c", "Straight/L"))
    cw = [500, 2600, 900, 1200, 1700]; rh = 300
    y = ty
    for r, row in enumerate(rows):
        x = tx
        for cexp, cell in zip(cw, row):
            msp.add_lwpolyline([(x,y),(x+cexp,y),(x+cexp,y-rh),(x,y-rh)],
                               close=True, dxfattribs={"layer":"GRID"})
            _text(msp, str(cell), x+60, y-rh/2, 85, layer="TEXT")
            x += cexp
        y -= rh
    doc.saveas(path)
    return path
