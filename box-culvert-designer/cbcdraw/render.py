"""Render the sheets (paper-space layouts with their viewports) to PNG / PDF, without AutoCAD."""
from __future__ import annotations
import os
from . import export, metrics


_fonts_ready = False


def _fonts():
    """Make sure the renderer's font cache knows the fonts installed on this machine."""
    global _fonts_ready
    if _fonts_ready: return
    try:
        from ezdxf.fonts import fonts
        name = os.path.basename(metrics.font_file("Arial Narrow") or "")
        if name and not fonts.font_manager.has_font(name): fonts.build_system_font_cache()
    except Exception:
        pass
    _fonts_ready = True


def build_doc(rec):
    """In-memory DXF document for rendering: local logo files and a locally available narrow font."""
    _fonts()
    ex = export.Exporter(rec, image_paths="local"); doc = ex.run()
    path = metrics.font_file("Arial Narrow")
    if path:
        for st in doc.styles:
            if str(st.dxf.font).upper() == "ARIALN.TTF": st.dxf.font = os.path.basename(path)
    return doc


def sheet_names(rec):
    lays = sorted((L for L in rec.layouts if L.p["NAME"].upper() != "MODEL"), key=lambda L: float(L.p.get("TABORDER", 0) or 0))
    return [L.p["NAME"] for L in lays]


def _figure(doc, name, dark=False):
    import matplotlib
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
    lay = doc.layouts.get(name)
    fig = plt.figure(figsize=(420 / 25.4, 297 / 25.4)); ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(background_policy=BackgroundPolicy.BLACK if dark else BackgroundPolicy.WHITE,
                        color_policy=ColorPolicy.COLOR if dark else ColorPolicy.BLACK)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(lay, finalize=False)
    # logo images: drawn here (the vector backend only outlines raster images)
    import matplotlib.image as mpimg
    for img in lay.query("IMAGE"):
        try:
            idef = img.image_def; path = idef.dxf.filename
            if not os.path.exists(path): continue
            a = mpimg.imread(path); o = img.dxf.insert; u = img.dxf.u_pixel; v = img.dxf.v_pixel; sz = img.dxf.image_size
            w = u.magnitude * sz.x; h = v.magnitude * sz.y
            ax.imshow(a, extent=(o.x, o.x + w, o.y, o.y + h), zorder=50, interpolation="bilinear", aspect="auto")
        except Exception:
            continue
    ax.set_xlim(0, 420); ax.set_ylim(0, 297); ax.set_aspect("equal"); ax.axis("off")
    return fig


def sheet_png(doc, name, path, dpi=150, dark=False):
    import matplotlib.pyplot as plt
    fig = _figure(doc, name, dark); fig.savefig(path, dpi=dpi, facecolor="black" if dark else "white"); plt.close(fig)
    return path


def sheets_pdf(doc, names, path):
    """One A3 page per sheet."""
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    with PdfPages(path) as pdf:
        for n in names:
            fig = _figure(doc, n); pdf.savefig(fig, facecolor="white"); plt.close(fig)
    return path
