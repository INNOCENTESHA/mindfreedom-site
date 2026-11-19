"""Extents and simple transforms of recorded entities (GetBoundingBox, Move, ScaleEntity)."""
from __future__ import annotations
import math
from . import metrics

MTEXT_LINE = 5.0 / 3.0            # AutoCAD MTEXT line pitch = 5/3 x text height (leaders)
# Paragraph blocks of the reference drawing (7 notes blocks, 11-42 lines): height = h (1 + c) + (n - 1) p h
NOTE_PITCH = 1.6809; NOTE_TAIL = 0.0515; NOTE_FALLBACK_LINE = 0.367   # a line with fallback-font glyphs is taller


def _style(e, name_key="STYLENAME"):
    st = e.doc.textstyles.items.get(str(e.p.get(name_key, "Standard")).upper())
    if st is None: return "Arial", False, 1.0
    return st.p.get("TYPEFACE", "Arial"), st.p.get("BOLD", False), float(st.p.get("WIDTH", 1.0) or 1.0)


def _rot(pts, c, a):
    if not a: return pts
    ca, sa = math.cos(a), math.sin(a)
    return [(c[0] + (x - c[0]) * ca - (y - c[1]) * sa, c[1] + (x - c[0]) * sa + (y - c[1]) * ca) for x, y in pts]


def _bb(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def arc_points(p, q, bulge, n=8):
    """Intermediate points of a bulge arc from p to q."""
    if abs(bulge) < 1e-12: return []
    theta = 4 * math.atan(bulge); d = math.dist(p, q)
    if d < 1e-12: return []
    r = d / (2 * math.sin(abs(theta) / 2)); mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    h = r * math.cos(abs(theta) / 2); ux, uy = (q[0] - p[0]) / d, (q[1] - p[1]) / d
    sgn = 1 if bulge > 0 else -1
    cx, cy = mx - sgn * uy * h * (1 if abs(theta) <= math.pi else -1) * 1, my + sgn * ux * h * (1 if abs(theta) <= math.pi else -1)
    a0 = math.atan2(p[1] - cy, p[0] - cx)
    return [(cx + r * math.cos(a0 + theta * k / n), cy + r * math.sin(a0 + theta * k / n)) for k in range(1, n)]


def poly_points(e):
    V = e.p["VERTS"]; pts = []
    n = len(V)
    for i, v in enumerate(V):
        pts.append(tuple(v["p"]))
        j = i + 1
        if j >= n:
            if not e.p["CLOSED"]: break
            j = 0
        if v["b"]: pts.extend(arc_points(v["p"], V[j]["p"], v["b"]))
    return pts


def text_origin(e):
    """Start of the baseline of a TEXT entity, its advance width, height and rotation base point."""
    p = e.p; h = float(p["HEIGHT"]); face, bold, wf = _style(e)
    wf = wf * float(p.get("SCALEFACTOR", 1.0) or 1.0)
    w = metrics.text_width(p["TEXTSTRING"], h, face, bold, wf)
    jh, jv = int(p.get("JH", 0)), int(p.get("JV", 0))
    al = p.get("ALIGNMENT", None)
    if al is not None and not (jh or jv):                   # ActiveX alignment enum
        al = int(al) if isinstance(al, (int, float)) else 0
        jh, jv = {0: (0, 0), 1: (1, 0), 2: (2, 0), 4: (1, 2), 6: (0, 3), 7: (1, 3), 8: (2, 3), 9: (0, 2), 10: (1, 2), 11: (2, 2),
                  12: (0, 1), 13: (1, 1), 14: (2, 1)}.get(al, (0, 0))
    base = p["TEXTALIGNMENTPOINT"] if (jh or jv) else p["INSERTIONPOINT"]
    x = base[0] - (0 if jh == 0 else w / 2 if jh in (1, 4) else w)
    y = base[1] - (0 if jv in (0, 1) else h / 2 if jv == 2 else h)
    if jv == 1: y += metrics.descent(h, face)             # 'bottom' aligns the descender line; the baseline sits above it
    return x, y, w, h, base, face, bold, wf


def text_box(e):
    """Corner points of the drawn glyphs of a TEXT entity (rotation applied)."""
    x, y, w, h, base, face, bold, wf = text_origin(e)
    x0, x1, y0, y1 = metrics.text_extents(e.p["TEXTSTRING"], h, face, bold, wf)
    return _rot([(x + x0, y + y0), (x + x1, y + y0), (x + x1, y + y1), (x + x0, y + y1)], base, float(e.p.get("ROTATION", 0.0) or 0.0))


def mtext_size(e, text=None, height=None, width=None, style_key="STYLENAME"):
    """(width, height, lines) of an MTEXT block as AutoCAD measures it:
    the defined box width when there is one, first line one text height tall, 5/3 h pitch,
    and the bottom at the lowest drawn glyph of the last line."""
    p = e.p; h = float(height if height is not None else p["HEIGHT"]); face, bold, wf = _style(e, style_key)
    bw = float(width if width is not None else p.get("WIDTH", 0.0) or 0.0)
    lines = metrics.wrap(metrics.mtext_lines(text if text is not None else p["TEXTSTRING"]), h, bw, face, bold)
    w = bw if bw > 0 else max((metrics.text_width(ln, h, face, bold, wf) for ln in lines), default=0.0)
    if len(lines) <= 1:
        last = lines[0] if lines else ""
        return w, h - (metrics.ink_box(last, h, face, bold, wf)[2] if last.strip() else 0.0), lines
    tall = sum(1 for ln in lines if metrics.has_fallback(ln, face, bold))
    return w, h * (1 + NOTE_TAIL) + (len(lines) - 1) * NOTE_PITCH * h + tall * NOTE_FALLBACK_LINE * h, lines


def mtext_box(e):
    p = e.p; w, ht, _ = mtext_size(e); ap = int(p.get("ATTACHMENTPOINT", 1) or 1); ip = p["INSERTIONPOINT"]
    col = (ap - 1) % 3; row = (ap - 1) // 3
    x = ip[0] - (0, w / 2, w)[col]; y = ip[1] - (0, -ht / 2, -ht)[row]
    return _rot([(x, y - ht), (x + w, y - ht), (x + w, y), (x, y)], ip, float(p.get("ROTATION", 0.0) or 0.0))


def dim_geometry(e):
    """Dimension line end points, extension line ends and text anchor of a linear dimension (paper units)."""
    p = e.p; a, b, loc = p["P1"], p["P2"], p["LOC"]
    v = e.doc.dimstyles.items.get(str(p.get("STYLENAME", "")).upper())
    V = dict(v.p.get("VARS", {})) if v else {}
    exo, exe, gap, txt = float(V.get("DIMEXO", 0.625)), float(V.get("DIMEXE", 1.25)), float(V.get("DIMGAP", 0.625)), float(V.get("DIMTXT", 2.5))
    if p.get("DIMKIND") == "rotated": ang = float(p.get("ROTATION", 0.0))
    else: ang = math.atan2(b[1] - a[1], b[0] - a[0])
    ux, uy = math.cos(ang), math.sin(ang); nx, ny = -uy, ux
    da = (loc[0] - a[0]) * nx + (loc[1] - a[1]) * ny; db = (loc[0] - b[0]) * nx + (loc[1] - b[1]) * ny
    A = (a[0] + nx * da, a[1] + ny * da); B = (b[0] + nx * db, b[1] + ny * db)
    meas = abs((b[0] - a[0]) * ux + (b[1] - a[1]) * uy)
    return dict(A=A, B=B, a=a, b=b, ang=ang, n=(nx, ny), u=(ux, uy), da=da, db=db, exo=exo, exe=exe, gap=gap, txt=txt, meas=meas)


def dim_text(e):
    ov = e.p.get("TEXTOVERRIDE", "") or ""
    g = dim_geometry(e)
    val = g["meas"] * float(e.p.get("LINEARSCALEFACTOR", 1.0) or 1.0)
    from .lisp import rtos
    v = e.doc.dimstyles.items.get(str(e.p.get("STYLENAME", "")).upper()); V = dict(v.p.get("VARS", {})) if v else {}
    s = rtos(val, 2, int(V.get("DIMDEC", 4)), int(V.get("DIMZIN", 0)))
    return ov.replace("<>", s) if ov else s


def _dim_above(g):
    nx, ny = g["n"]
    # text above the dimension line (DIMTAD 1): "above" = left of the reading direction
    if nx > 1e-9 or (abs(nx) < 1e-9 and ny < 0): nx, ny = -nx, -ny
    return nx, ny


def dim_text_position(e):
    g = dim_geometry(e); mx, my = (g["A"][0] + g["B"][0]) / 2, (g["A"][1] + g["B"][1]) / 2
    nx, ny = _dim_above(g); off = g["gap"] + g["txt"] / 2 + 0.032 * g["txt"] / 3.0
    return [mx + nx * off, my + ny * off, 0.0]


def dim_box(e):
    g = dim_geometry(e); pts = [g["A"], g["B"], tuple(g["a"][:2]), tuple(g["b"][:2])]
    nx, ny = g["n"]
    for P, d in ((g["A"], g["da"]), (g["B"], g["db"])):
        s = 1 if d >= 0 else -1
        pts.append((P[0] + nx * s * g["exe"], P[1] + ny * s * g["exe"]))
    s = dim_text(e)
    if s.strip():
        ink = metrics.ink_box(s, g["txt"], "Arial Narrow"); w = metrics.text_width(s, g["txt"], "Arial Narrow")
        ax, ay = _dim_above(g); ux, uy = g["u"]; mx, my = (g["A"][0] + g["B"][0]) / 2, (g["A"][1] + g["B"][1]) / 2
        lo = g["gap"]; hi = g["gap"] + (ink[3] - ink[2])           # one gap off the line, as tall as the drawn digits
        for sx in (-1, 1):
            for d in (lo, hi):
                pts.append((mx + ux * sx * w / 2 + ax * d, my + uy * sx * w / 2 + ay * d))
    return pts


def mleader_geometry(e):
    """Arrow point, landing point, dogleg and text placement of an MLeader created by AddMLeader(p, q).

    Rules read off the reference drawing:
      right-running:  landing = q, dogleg to the right, text starts gap after the dogleg end
      left-running (SetDoglegDirection -x, then a shorter DoglegLength d1 set after the original d0):
                      text starts at q + 2 d0 - d1 + gap and the leader lands gap + d1 beyond its right end
    Text is vertically centred on the landing line; widths are those of the drawn glyphs."""
    p = e.p; P = p["POINTS"]; a, q = P[0], P[-1]
    sc = float(p.get("SCALEFACTOR", 1.0) or 1.0); th = float(p.get("TEXTHEIGHT", 4.0)) * sc
    dog = float(p.get("DOGLEGLENGTH", 0.0)) * sc; gap = float(p.get("LANDINGGAP", 0.0)) * sc
    face, bold, wf = _style(e, "TEXTSTYLENAME")
    lines = metrics.mtext_lines(p.get("TEXTSTRING", "") or "")
    boxes = [metrics.ink_box(ln, th, face, bold, wf) for ln in lines]
    w = max((b[1] - b[0] for b in boxes), default=0.0)
    top = boxes[0][3] if boxes else th; bot = boxes[-1][2] if boxes else 0.0
    ht = (len(lines) - 1) * MTEXT_LINE * th + top - bot       # drawn height, first cap line to the lowest glyph
    flipped = bool(p.get("DOGLEGDIR")) and p["DOGLEGDIR"][0] < 0
    if not flipped:
        dr = 1.0; land = (q[0], q[1]); tx0 = q[0] + dog + gap
    else:
        dr = -1.0; d0 = float(p.get("DOG0", dog)) * sc
        tx0 = q[0] + 2 * d0 - dog + gap; land = (tx0 + w + gap + dog, q[1])
    return dict(arrow=(a[0], a[1]), land=land, dr=dr, dog=dog, gap=gap, th=th, tx0=tx0, w=w, ht=ht, lines=lines,
                ylo=q[1] - ht / 2, yhi=q[1] + ht / 2, top=top, mid=[tuple(x[:2]) for x in P[1:-1]],
                asz=float(p.get("ARROWHEADSIZE", 0.0)) * sc)


def mleader_box(e):
    g = mleader_geometry(e); y = g["land"][1]
    pts = [g["arrow"], g["land"], (g["land"][0] + g["dr"] * g["dog"], y)] + g["mid"]
    # arrowhead (closed filled, 1:3) may reach beyond the leader line
    ax, ay = g["arrow"]; lx, ly = (g["mid"][0] if g["mid"] else g["land"]); d = math.hypot(lx - ax, ly - ay)
    if d > 1e-9 and g["asz"] > 0:
        ux, uy = (lx - ax) / d, (ly - ay) / d; bx, by = ax + ux * g["asz"], ay + uy * g["asz"]; hw = g["asz"] / 6.0
        pts += [(bx - uy * hw, by + ux * hw), (bx + uy * hw, by - ux * hw)]
    if g["w"] > 0:
        pts += [(g["tx0"] - g["gap"], g["ylo"]), (g["tx0"] + g["w"] + g["gap"], g["yhi"])]
    return pts


# ---- tables.  AutoCAD keeps the title row of the Standard table style (11 mm) and grows any row whose text wraps.
TABLE_TITLE_ROW = 11.0          # 6.0 title text x 4/3 + 2 x 1.5 margin, fixed at creation
TABLE_PAD = 1.0                 # on top of twice the vertical cell margin (fitted on 6 tables of the reference drawing)


def table_cell_span(e, r, c):
    for r0, r1, c0, c1 in e.p["MERGES"]:
        if r0 <= r <= r1 and c0 <= c <= c1:
            return (r0, r1, c0, c1)
    return (r, r, c, c)


def table_cell_lines(e, r, c):
    """Wrapped lines of a cell and its text height."""
    from .fields import resolve
    p = e.p; cell = p["CELLS"].get((r, c), {}); txt = resolve(cell.get("text", "") or "", e.doc)
    h = float(cell.get("height", p.get("DEFTEXTH", 6.0 if r == 0 else 4.5)))
    r0, r1, c0, c1 = table_cell_span(e, r, c)
    w = sum(p["COLW"][c0:c1 + 1]) - 2.0 * float(p.get("HORZCELLMARGIN", 1.5))
    sty = e.doc.textstyles.items.get(str(cell.get("style", "Standard")).upper())
    face = sty.p.get("TYPEFACE", "Arial") if sty else "Arial"
    return metrics.wrap(metrics.mtext_lines(txt), h, max(w, 0.1), face) if txt else [], h


def table_rows(e):
    """Row heights as AutoCAD lays the table out."""
    p = e.p; n = len(p["ROWH"]); nc = len(p["COLW"]); vm = float(p.get("VERTCELLMARGIN", 1.5))
    rows = list(p["ROWH"])
    if 0 not in p.get("ROWSET", ()) and not p.get("TITLESUPPRESSED"):
        rows[0] = max(rows[0], TABLE_TITLE_ROW)
    for r in range(n):
        for c in range(nc):
            r0, r1, c0, c1 = table_cell_span(e, r, c)
            if (r, c) != (r0, c0) or r1 != r0: continue              # merged continuation / multi-row cells
            lines, h = table_cell_lines(e, r, c)
            if len(lines) > 1:
                rows[r] = max(rows[r], h + (len(lines) - 1) * MTEXT_LINE * h + 2.0 * vm + TABLE_PAD)
    return rows


def outline(e):
    """Boundary polygon of an entity used as a hatch loop."""
    if e.t == "LWPOLYLINE": return poly_points(e)
    if e.t == "CIRCLE":
        c, r = e.p["CENTER"], e.p["RADIUS"]
        return [(c[0] + r * math.cos(2 * math.pi * k / 48), c[1] + r * math.sin(2 * math.pi * k / 48)) for k in range(48)]
    raise ValueError(f"hatch loop from {e.t}")


def points(e):
    """Extent-defining points of an entity (None when it has none)."""
    p = e.p; t = e.t
    if t == "LINE": return [tuple(p["P1"][:2]), tuple(p["P2"][:2])]
    if t == "POINT": return [tuple(p["P1"][:2])]
    if t == "LWPOLYLINE":
        pts = poly_points(e)
        ws = [w for v in p["VERTS"] for w in (v["sw"], v["ew"]) if w] + ([p["CONSTWIDTH"]] if p.get("CONSTWIDTH") else [])
        if ws:
            h = max(ws) / 2.0; pts = [(x + dx, y + dy) for x, y in pts for dx in (-h, h) for dy in (-h, h)]
        return pts
    if t == "CIRCLE":
        c, r = p["CENTER"], p["RADIUS"]; return [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    if t == "ARC":
        c, r = p["CENTER"], p["RADIUS"]; return [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    if t == "SOLID": return [tuple(q[:2]) for q in p["PTS"]]
    if t == "TEXT": return text_box(e) if p["TEXTSTRING"].strip() else None
    if t == "MTEXT": return mtext_box(e) if p["TEXTSTRING"].strip() else None
    if t == "DIMENSION": return dim_box(e)
    if t == "MULTILEADER": return mleader_box(e)
    if t == "HATCH":
        pts = [q for _, loops in p.get("LOOPS", []) for loop in loops for q in loop]
        return pts or None
    if t == "ACAD_TABLE":
        ip = p["INSERTIONPOINT"]; w = sum(p["COLW"]); h = sum(table_rows(e))
        return [(ip[0], ip[1] - h), (ip[0] + w, ip[1])]
    if t == "IMAGE":
        o = p["ORIGIN"]; return _rot([(o[0], o[1]), (o[0] + p["IMAGEWIDTH"], o[1] + p["IMAGEHEIGHT"])], o, 0.0)
    if t == "VIEWPORT":
        c = p["CENTER"]; return [(c[0] - p["WIDTH"] / 2, c[1] - p["HEIGHT"] / 2), (c[0] + p["WIDTH"] / 2, c[1] + p["HEIGHT"] / 2)]
    if t == "INSERT":
        blk = e.doc.blocks.get(str(p["NAME"]).upper())
        if blk is None: return [tuple(p["INSERTIONPOINT"][:2])]
        ip = p["INSERTIONPOINT"]; sx, sy, a = p.get("XSCALE", 1.0), p.get("YSCALE", 1.0), p.get("ROTATION", 0.0)
        out = []
        for s in blk.live():
            q = points(s)
            if q: out += [(ip[0] + x * sx, ip[1] + y * sy) for x, y in q]
        return _rot(out, ip, a) if out else [tuple(ip[:2])]
    return None


def bbox(e):
    pts = points(e)
    return _bb(pts) if pts else None


def _shift(pt, dx, dy):
    pt[0] += dx; pt[1] += dy


def move(e, dx, dy):
    p = e.p
    for k in ("P1", "P2", "LOC", "CENTER", "INSERTIONPOINT", "TEXTALIGNMENTPOINT", "ORIGIN"):
        if k in p and p[k] is not None:
            p[k] = [p[k][0] + dx, p[k][1] + dy] + list(p[k][2:])
    if "VERTS" in p:
        for v in p["VERTS"]: v["p"] = [v["p"][0] + dx, v["p"][1] + dy]
    if "PTS" in p: p["PTS"] = [[q[0] + dx, q[1] + dy] + list(q[2:]) for q in p["PTS"]]
    if "POINTS" in p: p["POINTS"] = [[q[0] + dx, q[1] + dy] + list(q[2:]) for q in p["POINTS"]]
    if "LOOPS" in p:
        p["LOOPS"] = [(k, [[(x + dx, y + dy) for x, y in loop] for loop in loops]) for k, loops in p["LOOPS"]]


def scale(e, base, f):
    bx, by = base[0], base[1]; S = lambda q: [bx + (q[0] - bx) * f, by + (q[1] - by) * f] + list(q[2:])
    p = e.p
    for k in ("P1", "P2", "LOC", "CENTER", "INSERTIONPOINT", "TEXTALIGNMENTPOINT", "ORIGIN"):
        if k in p and p[k] is not None: p[k] = S(p[k])
    for k in ("RADIUS", "HEIGHT", "WIDTH", "IMAGEWIDTH", "IMAGEHEIGHT", "TEXTHEIGHT"):
        if k in p and isinstance(p[k], (int, float)): p[k] = p[k] * f
    if "VERTS" in p:
        for v in p["VERTS"]:
            v["p"] = S(v["p"])
            for w in ("sw", "ew"):
                if v[w]: v[w] *= f
        if p.get("CONSTWIDTH"): p["CONSTWIDTH"] *= f
    if "PTS" in p: p["PTS"] = [S(q) for q in p["PTS"]]
    if "POINTS" in p: p["POINTS"] = [S(q) for q in p["POINTS"]]
    if "LOOPS" in p:
        p["LOOPS"] = [(k, [[tuple(S(q)) for q in loop] for loop in loops]) for k, loops in p["LOOPS"]]
    if e.t == "ACAD_TABLE":
        p["ROWH"] = [h * f for h in p["ROWH"]]; p["COLW"] = [w * f for w in p["COLW"]]
        for c in p["CELLS"].values():
            if "height" in c: c["height"] *= f
