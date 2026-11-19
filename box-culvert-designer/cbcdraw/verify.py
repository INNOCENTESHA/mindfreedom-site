"""Compare a generated drawing with entity data extracted from a reference AutoCAD DWG."""
from __future__ import annotations
import math
from . import geom

d = math.dist


def _pts(a, b, tol):
    return len(a) == len(b) and all(d(x, y) <= tol for x, y in zip(a, b))


def _cyc(a, b, tol):
    n = len(a)
    if n != len(b): return False
    return any(all(d(a[i], seq[(i + k) % n]) <= tol for i in range(n)) for seq in (b, b[::-1]) for k in range(n))


def _match(A, B, eq):
    left = list(B); miss = 0
    for a in A:
        hit = next((b for b in left if eq(a, b)), None)
        if hit is None: miss += 1
        else: left.remove(hit)
    return dict(mine=len(A), ref=len(B), matched=len(A) - miss, mine_only=miss, ref_only=len(left))


def model_records(rec):
    out = []
    for e in rec.model.live():
        p = e.p; t = e.t; r = dict(t=t, layer=p.get("LAYER"))
        if t == "LINE": r.update(p=[p["P1"][:2], p["P2"][:2]])
        elif t == "LWPOLYLINE": r.update(p=[v["p"] for v in p["VERTS"]], closed=p["CLOSED"])
        elif t == "CIRCLE": r.update(p=[p["CENTER"][:2]], r=p["RADIUS"])
        elif t == "TEXT": r.update(s=p["TEXTSTRING"], al=(p["TEXTALIGNMENTPOINT"] if (p.get("JH") or p.get("JV")) else p["INSERTIONPOINT"])[:2], h=p["HEIGHT"])
        elif t == "MTEXT": r.update(s=p["TEXTSTRING"], ins=p["INSERTIONPOINT"][:2], h=p["HEIGHT"])
        elif t == "MULTILEADER":
            g = geom.mleader_geometry(e); r.update(s=p["TEXTSTRING"], arrow=list(g["arrow"]), land=list(g["land"]))
        elif t == "HATCH": r.update(p=[list(p["LOOPS"][0][1][0][0])] if p.get("LOOPS") else [])
        elif t == "INSERT": r.update(name=p["NAME"], p=[p["INSERTIONPOINT"][:2]])
        elif t == "DIMENSION":
            g = geom.dim_geometry(e); r.update(p=[p["P1"][:2], p["P2"][:2]], meas=g["meas"] * p.get("LINEARSCALEFACTOR", 1.0))
        out.append(r)
    return out


def compare_model(rec, ref, tol=0.3):
    """ref: list of records as written by the DWG extraction (see tests).  Returns {type: counts}."""
    M = model_records(rec); res = {}
    sel = lambda L, t: [x for x in L if x["t"] == t]
    res["LINE"] = _match(sel(M, "LINE"), sel(ref, "LINE"), lambda a, b: a["layer"] == b["layer"] and (_pts(a["p"], b["p"], tol) or _pts(a["p"], b["p"][::-1], tol)))
    res["LWPOLYLINE"] = _match(sel(M, "LWPOLYLINE"), sel(ref, "LWPOLYLINE"), lambda a, b: a["layer"] == b["layer"] and a["closed"] == b["closed"] and
                               (_cyc(a["p"], b["p"], tol) if a["closed"] else (_pts(a["p"], b["p"], tol) or _pts(a["p"], b["p"][::-1], tol))))
    res["CIRCLE"] = _match(sel(M, "CIRCLE"), sel(ref, "CIRCLE"), lambda a, b: a["layer"] == b["layer"] and d(a["p"][0], b["p"][0]) <= tol and abs(a["r"] - b["r"]) <= tol)
    res["TEXT"] = _match(sel(M, "TEXT"), sel(ref, "TEXT"), lambda a, b: a["layer"] == b["layer"] and a["s"] == b["s"] and abs(a["h"] - b["h"]) < 1e-6 and
                         d(a["al"], b["al"] if (b["ha"] or b["va"]) else b["ins"]) <= tol)
    res["MTEXT"] = _match(sel(M, "MTEXT"), sel(ref, "MTEXT"), lambda a, b: a["s"] == b["s"] and d(a["ins"], b["ins"]) <= tol and abs(a["h"] - b["h"]) < 1e-6)
    res["MULTILEADER"] = _match(sel(M, "MULTILEADER"), sel(ref, "MULTILEADER"), lambda a, b: a["s"] == b["s"] and d(a["arrow"], b["arrow"]) <= tol and d(a["land"], b["land"]) <= tol + 0.3)
    res["INSERT"] = _match(sel(M, "INSERT"), sel(ref, "INSERT"), lambda a, b: a["name"] == b["name"] and d(a["p"][0], b["p"][0]) <= tol)
    res["DIMENSION"] = _match(sel(M, "DIMENSION"), sel(ref, "DIMENSION"), lambda a, b: a["layer"] == b["layer"] and abs(a["meas"] - b["meas"]) <= 0.6 and
                              ((d(a["p"][0], b["p"][0]) <= tol and d(a["p"][1], b["p"][1]) <= tol) or (d(a["p"][0], b["p"][1]) <= tol and d(a["p"][1], b["p"][0]) <= tol)))
    res["HATCH"] = _match(sel(M, "HATCH"), sel(ref, "HATCH"), lambda a, b: a["layer"] == b["layer"] and a["p"] and b["p"] and d(a["p"][0], b["p"][0]) <= tol)
    return res


def compare_paper(rec, ref, tol=0.05):
    M = []
    for lay in rec.layouts:
        if lay.p["NAME"].upper() == "MODEL": continue
        for e in lay.block.live():
            p = e.p; t = e.t; r = dict(t=t)
            if t == "LINE": r.update(p=[p["P1"][:2], p["P2"][:2]])
            elif t == "CIRCLE": r.update(p=[p["CENTER"][:2]], r=p["RADIUS"])
            elif t == "TEXT":
                al = p.get("JH") or p.get("JV") or p.get("ALIGNMENT")
                r.update(s=p["TEXTSTRING"], al=(p["TEXTALIGNMENTPOINT"] if al else p["INSERTIONPOINT"])[:2], h=p["HEIGHT"])
            elif t == "VIEWPORT": r.update(c=p["CENTER"][:2], w=p["WIDTH"], h=p["HEIGHT"], mc=[p["TARGET"][0] + p["VIEWCENTER"][0], p["TARGET"][1] + p["VIEWCENTER"][1]])
            elif t == "IMAGE": r.update(o=p["ORIGIN"][:2], w=p["IMAGEWIDTH"], hh=p["IMAGEHEIGHT"])
            M.append(r)
    sel = lambda L, t: [x for x in L if x["t"] == t]; res = {}
    res["LINE"] = _match(sel(M, "LINE"), sel(ref, "LINE"), lambda a, b: _pts(a["p"], b["p"], tol) or _pts(a["p"], b["p"][::-1], tol))
    res["CIRCLE"] = _match(sel(M, "CIRCLE"), sel(ref, "CIRCLE"), lambda a, b: d(a["p"][0], b["p"][0]) <= tol and abs(a["r"] - b["r"]) <= tol)
    res["TEXT"] = _match(sel(M, "TEXT"), sel(ref, "TEXT"), lambda a, b: a["s"] == b["s"] and abs(a["h"] - b["h"]) < 1e-6 and d(a["al"], b["al"] if (b["ha"] or b["va"]) else b["ins"]) <= tol)
    views = [x for x in sel(ref, "VIEWPORT") if abs(x["vh"] / x["h"] - 2.0) < 1e-6]      # not the layouts' own overall viewport
    res["VIEWPORT"] = _match(sel(M, "VIEWPORT"), views, lambda a, b: d(a["c"], b["c"]) <= 0.2 and abs(a["w"] - b["w"]) <= 0.2 and abs(a["h"] - b["h"]) <= 0.2 and d(a["mc"], b["mc"]) <= 0.3)
    res["IMAGE"] = _match(sel(M, "IMAGE"), sel(ref, "IMAGE"), lambda a, b: d(a["o"], b["d"]["insert"][:2]) <= tol and
                          abs(a["w"] - b["d"]["u_vector"][0] * b["d"]["size"][0]) <= tol and abs(a["hh"] - b["d"]["v_vector"][1] * b["d"]["size"][1]) <= tol)
    return res


def all_matched(res):
    return all(v["mine_only"] == 0 and v["ref_only"] == 0 for v in res.values())
