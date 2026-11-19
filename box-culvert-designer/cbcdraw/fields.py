"""Evaluate the AutoCAD field codes the generator writes into title-block cells."""
from __future__ import annotations
import re, datetime

_INNER = re.compile(r"%<\\(_ObjId|AcVar|AcObjProp|AcExpr)\s*((?:(?!%<|>%).)*)>%", re.S)
_DATE = [("yyyy", "%Y"), ("yy", "%y"), ("MMMM", "%B"), ("MMM", "%b"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M")]


def _fmt_date(fmt, when):
    out = fmt
    for a, b in _DATE: out = out.replace(a, b)
    return when.strftime(out)


def resolve(text: str, rec, when=None) -> str:
    """Replace %<\\AcVar ..>%, %<\\AcObjProp ..>%, %<\\AcExpr ..>% (innermost first) by their values."""
    if not text or "%<" not in text: return text
    when = when or datetime.datetime.now()
    from .acad import Obj

    def one(m):
        kind, body = m.group(1), m.group(2).strip()
        fm = re.search(r'\\f\s*"([^"]*)"', body); fmt = fm.group(1) if fm else None
        if fm: body = body[:fm.start()].strip()
        if kind == "_ObjId": return "\x00" + body + "\x00"                  # marker consumed by AcObjProp
        if kind == "AcVar":
            if body.startswith("CustomDP."): return str(rec.summary.custom.get(body[9:], ""))
            if body == "SaveDate" or body == "Date" or body == "CreateDate": return _fmt_date(fmt or "dd.MM.yy", when)
            return ""
        if kind == "AcObjProp":
            mm = re.match(r"Object\(\x00(\d+)\x00\)\.(\w+)", body)
            if not mm: return ""
            o = Obj.registry.get(int(mm.group(1)))
            if o is None: return ""
            try: v = o.get(mm.group(2))
            except Exception: return ""
            return str(v)
        if kind == "AcExpr":
            expr = body.strip()
            if not re.fullmatch(r"[\d\s+\-*/().]+", expr): return ""
            try: v = eval(expr, {"__builtins__": {}}, {})            # digits and arithmetic operators only
            except Exception: return ""
            pr = re.search(r"%pr(\d+)", fmt or ""); n = int(pr.group(1)) if pr else 0
            return f"{v:.{n}f}"
        return ""
    for _ in range(6):
        new = _INNER.sub(one, text)
        if new == text: break
        text = new
    return text.replace("\x00", "")
