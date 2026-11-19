"""Text and image measurements (the generator's packing engine asks AutoCAD for extents)."""
from __future__ import annotations
import os, re, functools

_FONT_DIRS = ["/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts",
              "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
# typeface -> candidate files (regular, bold); Liberation Sans Narrow is metric-compatible with Arial Narrow
_FACES = {
    "ARIAL NARROW": (["ARIALN.TTF", "arialn.ttf", "Arial Narrow.ttf", "LiberationSansNarrow-Regular.ttf"],
                     ["ARIALNB.TTF", "arialnb.ttf", "Arial Narrow Bold.ttf", "LiberationSansNarrow-Bold.ttf"]),
    "ARIAL": (["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
              ["arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"]),
}


def font_file(typeface="Arial Narrow", bold=False):
    reg, bld = _FACES.get(str(typeface).upper(), _FACES["ARIAL NARROW"])
    for name in (bld if bold else reg):
        for d in _FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p): return p
    return None


@functools.lru_cache(maxsize=None)
def _font(typeface, bold):
    path = font_file(typeface, bold)
    if not path: return None
    from fontTools.ttLib import TTFont
    f = TTFont(path, lazy=True)
    cmap = f.getBestCmap(); hmtx = f["hmtx"].metrics; upm = f["head"].unitsPerEm
    os2 = f["OS/2"]; cap = getattr(os2, "sCapHeight", 0) or int(0.716 * upm)
    desc = abs(f["hhea"].descent); capy = cap             # capy scales glyph outlines vertically
    if str(typeface).upper() == "ARIAL NARROW":
        # AutoCAD sizes TrueType text by the capital height of the real font (Arial Narrow: 1466 / 2048 em).
        # The metric-compatible substitute has the same advances but declares a different cap height;
        # checked against the 202 measurable texts of the reference drawing (ratio constant to 4 digits).
        cap = round(upm * 1466 / 2048); desc = round(0.294 * cap)
    adv = {cp: hmtx[g][0] for cp, g in cmap.items() if g in hmtx}
    # glyphs the face lacks (Greek, maths) come from a fallback font in AutoCAD: an average advance, not .notdef
    return dict(adv=adv, upm=upm, cap=cap, capy=capy, desc=desc, default=round(0.55 * upm),
                glyf=f["glyf"] if "glyf" in f else None, cmap=cmap, ink={},
                ul_pos=f["post"].underlinePosition, ul_thk=f["post"].underlineThickness)


def _glyph_box(f, cp):
    """(xMin, xMax, yMin, yMax) of a glyph outline in font units, None for blank glyphs."""
    if cp in f["ink"]: return f["ink"][cp]
    b = None
    g = f["cmap"].get(cp)
    if g is not None and f["glyf"] is not None:
        gl = f["glyf"][g]
        if getattr(gl, "numberOfContours", 0) != 0 and hasattr(gl, "xMin"):
            b = (gl.xMin + _LSB_FIX.get(cp, 0) * f["upm"], gl.xMax, gl.yMin, gl.yMax)
    elif g is None and not chr(cp).isspace():
        b = (round(0.05 * f["upm"]), round(0.50 * f["upm"]), 0, f["capy"])       # fallback-font glyph
    f["ink"][cp] = b
    return b


# side-bearing differences between Arial Narrow and the substitute outlines, in em (fitted on the reference leaders)
_LSB_FIX = {ord("1"): 0.034}


def ink_box(s: str, height: float, typeface="Arial Narrow", bold=False, width_factor=1.0):
    """Extents of the drawn glyphs relative to the start of the baseline: (x0, x1, y0, y1).
    AutoCAD's GetBoundingBox reports these, not the advance box."""
    f = _font(typeface, bool(bold))
    underline = bool(re.search(r"%%[uU]", s))
    t = plain(s)
    if f is None:
        w = 0.62 * height * len(t) * width_factor
        return (0.0, w, 0.0, height)
    k = height / f["cap"]; ky = height / f["capy"]; pen = 0; x0 = x1 = y0 = y1 = None
    for ch in t:
        b = _glyph_box(f, ord(ch))
        if b:
            a, c, lo, hi = pen + b[0], pen + b[1], b[2], b[3]
            x0 = a if x0 is None else min(x0, a); x1 = c if x1 is None else max(x1, c)
            y0 = lo if y0 is None else min(y0, lo); y1 = hi if y1 is None else max(y1, hi)
        pen += f["adv"].get(ord(ch), f["default"])
    if x0 is None: return (0.0, 0.0, 0.0, 0.0)
    if underline:
        x0 = min(x0, 0); x1 = max(x1, pen); y0 = min(y0, f["ul_pos"] - f["ul_thk"])
    return (x0 * k * width_factor, x1 * k * width_factor, y0 * ky, y1 * ky)


def text_extents(s: str, height: float, typeface="Arial Narrow", bold=False, width_factor=1.0):
    """Box AutoCAD reports for a line of TEXT, relative to the start of the baseline: (x0, x1, y0, y1).
    Measured on the reference drawing: the advance box horizontally, the drawn glyphs vertically."""
    x0, x1, y0, y1 = ink_box(s, height, typeface, bold, width_factor)
    return (0.0, text_width(s, height, typeface, bold, width_factor), y0, y1)


_CTRL = re.compile(r"%%[uUoOkK]")
_SPECIAL = {"%%d": "\u00b0", "%%D": "\u00b0", "%%p": "\u00b1", "%%P": "\u00b1", "%%c": "\u00d8", "%%C": "\u00d8", "%%%": "%"}


_UNI = re.compile(r"\\U\+([0-9A-Fa-f]{4})")


def plain(s: str) -> str:
    """Single-line TEXT content with the %% control codes and \\U+XXXX escapes resolved."""
    s = _UNI.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = _CTRL.sub("", s)
    for k, v in _SPECIAL.items(): s = s.replace(k, v)
    return s


def text_width(s: str, height: float, typeface="Arial Narrow", bold=False, width_factor=1.0) -> float:
    """Drawn width of a line of text whose capital height is `height`."""
    f = _font(typeface, bool(bold))
    s = plain(s)
    if f is None:
        return 0.62 * height * len(s) * width_factor
    units = sum(f["adv"].get(ord(c), f["default"]) for c in s)
    return units / f["cap"] * height * width_factor


def descent(height: float, typeface="Arial Narrow") -> float:
    f = _font(typeface, False)
    return 0.29 * height if f is None else f["desc"] / f["cap"] * height


_MT_FMT = re.compile(r"\\[fFHhCcTtQqWwAa][^;]*;|\\[LlOoKk]|\\S[^;]*;|[{}]")


def mtext_lines(s: str):
    """MTEXT content -> list of plain lines (paragraph breaks only; wrapping is done by the caller)."""
    s = s.replace("\\\\P", "\\P")
    s = _UNI.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = _MT_FMT.sub("", s).replace("\\~", " ")
    return [plain(x) for x in re.split(r"\\P|\n", s)]


def wrap(lines, height, width, typeface="Arial Narrow", bold=False):
    """Word-wrap lines to `width` (0 = no wrapping)."""
    if not width or width <= 0: return list(lines)
    out = []
    for ln in lines:
        words = ln.split(" "); cur = ""
        for w in words:
            t = w if not cur else cur + " " + w
            if cur and text_width(t, height, typeface, bold) > width:
                out.append(cur); cur = w
            else: cur = t
        out.append(cur)
    return out


@functools.lru_cache(maxsize=None)
def image_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def has_fallback(s: str, typeface="Arial Narrow", bold=False) -> bool:
    """True when the line carries Greek / mathematical symbols.  AutoCAD draws those from a taller
    fallback face, which makes that line of a paragraph higher (seen on the general notes: beta, root)."""
    return any(ord(c) > 0x1FFF and not c.isspace() for c in plain(s))      # the root sign; beta is in the face
