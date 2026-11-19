"""python -m cbcdraw CBC_EXPORT.txt --lisp DIR [--logos DIR] [--dxf out.dxf] [--pdf out.pdf] [--png-dir DIR]"""
import argparse, os, sys
from .run import generate


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cbcdraw", description="Produce the CBC detailed drawings without AutoCAD")
    ap.add_argument("export", help="CBC_EXPORT.txt written by the designer")
    ap.add_argument("--lisp", required=True, help="folder holding CBC01_Drawing_Generator.lsp and its extensions")
    ap.add_argument("--logos", action="append", default=[], help="folder(s) holding the title-block logos")
    ap.add_argument("--dxf"); ap.add_argument("--pdf"); ap.add_argument("--png-dir")
    ap.add_argument("--images", default="relative", choices=("relative", "original", "local"), help="how logo paths are written in the DXF")
    a = ap.parse_args(argv)
    rec, I, log, status = generate(a.export, a.lisp, a.logos or [os.path.join(a.lisp, "LOGO_FLAT")])
    for ln in log: print(ln)
    if status != "ok":
        print("generator stopped before drawing - see the log above"); return 1
    if a.dxf:
        from .export import to_dxf
        to_dxf(rec, a.dxf, image_paths=a.images); print("DXF:", a.dxf)
    if a.pdf or a.png_dir:
        import matplotlib; matplotlib.use("Agg")
        from . import render
        doc = render.build_doc(rec); names = render.sheet_names(rec)
        if a.png_dir:
            os.makedirs(a.png_dir, exist_ok=True)
            for n in names: print("PNG:", render.sheet_png(doc, n, os.path.join(a.png_dir, n + ".png")))
        if a.pdf: print("PDF:", render.sheets_pdf(doc, names, a.pdf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
