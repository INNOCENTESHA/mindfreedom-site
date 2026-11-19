"""Execute the CBC AutoLISP drawing generator on a CBC_EXPORT.txt and return the recorded document."""
from __future__ import annotations
import os
from .lisp import Interp, LispExit, LispError
from .acad import Host

MAIN = "CBC01_Drawing_Generator.lsp"


def generate(export_txt: str, lisp_dir: str, logo_dirs=(), log=None):
    """Run (cbc:drawtxt export_txt).  Returns (document, interpreter, log lines)."""
    lines = []
    host = Host()
    I = Interp(host, search_dirs=[lisp_dir, os.path.dirname(os.path.abspath(export_txt)), *logo_dirs],
               log=lambda s: (lines.append(s), log and log(s)))
    # the generator locates its extension files next to the workbook path held in *cbc-xl*
    I.globals["*CBC-XL*"] = "C:\\CBC\\CBC_Box_Culvert_Parametric_Designer.xlsm"
    I.load_file(os.path.join(lisp_dir, MAIN))
    status = "ok"
    try:
        I.call(I.lookup("CBC:DRAWTXT"), [export_txt])
    except LispExit:
        status = "exit"
    return host.doc, I, lines, status
