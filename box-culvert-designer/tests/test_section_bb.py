"""
Section B-B barrel reinforcement: the Python port must reproduce the AutoLISP generator.

test_formula_values   - always runs; expected vertices worked by hand from the LISP formulas
test_against_reference_dwg - runs when the reference fixtures extracted from the original
                             AutoCAD drawing are present (kept out of the repository)
"""
import json, math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from section_bb import build, read_export, leader_landing, to_dxf

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "..", "_reference", "fixtures")
EXPORT = os.path.join(HERE, "..", "_reference", "zip", "DRAWINGS", "CBC_EXPORT.txt")


def near(a, b, tol=0.11):
    return len(a) == len(b) and all(math.dist(p, q) <= tol for p, q in zip(a, b))


def has(bars, pts):
    return any(near(b, pts) or near(b, pts[::-1]) for b in bars)


def test_formula_values():
    D = build({})                                   # 4 cell 1500 x 1500, 250 members, haunch 150, T16-150 / T12-200
    bars = [list(p[0]) for p in D.bars()]
    assert len(bars) == 28 and len(D.dots) == 210 and len(D.leaders) == 9 and len(D.dims) == 8
    assert has(bars, [(-3567, -108), (-3567, 1692), (3567, 1692), (3567, 792)])            # 01 top U-bar, lap staggered
    assert has(bars, [(-3551, 708), (-3551, -192), (3551, -192), (3551, 1608)])            # 02 base U-bar
    assert has(bars, [(-3551, 1098), (-3551, 1558), (3551, 1558), (3551, 1098)])           # 03 legs 460 down
    assert has(bars, [(-3551, 402), (-3551, -58), (3551, -58), (3551, 402)])               # 04 legs 460 up
    assert has(bars, [(3131, -176), (3431, -176), (3431, 1676), (3131, 1676)])             # 05 legs 300 into slabs
    assert has(bars, [(-2119, -176), (-1819, -176), (-1819, 1676), (-2119, 1676)])         # 06 pier bar
    assert has(bars, [(-2658.2, -166), (-3138.2, -166), (-3541, 236.8), (-3541, 716.8)])   # 07 haunch bar
    texts = sorted(s for _, _, s, _ in D.leaders)
    assert "01/01a-T16-150" in texts and "02/02a-T16-150" in texts and "08-T12-200 (PIER FACES)" in texts
    assert not D.warnings


def test_twelve_metre_warning():
    D = build({"N_CELLS": 8})                       # 14.25 m wide: U-bars exceed the 12 m stock length
    assert any("stock length" in w for w in D.warnings)


def test_dxf_is_valid(tmp_path=None):
    import ezdxf, tempfile
    path = os.path.join(tempfile.mkdtemp(), "bb.dxf")
    to_dxf(build({}), path)
    doc = ezdxf.readfile(path)
    assert len(doc.audit().errors) == 0
    lay = {e.dxf.layer for e in doc.modelspace()}
    assert {"CBC_CONC", "CBC_REBAR", "CBC_DIM", "CBC_RTXT", "CBC_TITLE", "CBC_HATCH"} <= lay
    h = doc.modelspace().query("HATCH")[0]
    assert h.dxf.pattern_name == "AR-SAND" and abs(h.dxf.pattern_scale - 0.025) < 1e-9          # blinding
    dims = doc.modelspace().query("DIMENSION")
    assert sorted(round(d.get_measurement() * 20) for d in dims) == [250, 250, 250, 250, 800, 800, 1500, 6750]
    for d in dims:                                    # each dimension: dimension line + 2 extension lines + 2 arrows + text
        kinds = [e.dxftype() for e in doc.blocks.get(d.dxf.geometry)]
        assert kinds.count("LINE") == 3 and kinds.count("INSERT") + kinds.count("SOLID") == 2 and "MTEXT" in kinds
    ds = doc.dimstyles.get("CBC_DIM").dxf
    assert (ds.dimtxt, ds.dimasz, ds.dimclrd, ds.dimclre, ds.dimclrt) == (3.0, 2.5, 4, 4, 7)


def test_against_reference_dwg():
    if not (os.path.exists(os.path.join(FIX, "ref_BB.json")) and os.path.exists(EXPORT)):
        print("   (reference fixtures not present - skipped)"); return
    ref = json.load(open(os.path.join(FIX, "ref_BB.json")))
    lab = {o["text"]: o for o in json.load(open(os.path.join(FIX, "ref_BB_labels.json")))}
    D = build(read_export(EXPORT))
    mine = [list(p[0]) for p in D.bars()]; theirs = [[tuple(v) for v in b] for b in ref["bars"]]
    assert len(mine) == len(theirs) == 28
    for b in mine:
        assert has(theirs, b), f"bar not in reference drawing: {b}"
    rd = [tuple(d) for d in ref["dots"]]
    assert len(D.dots) == len(rd)
    for x, y, *_ in D.dots:
        assert min(math.dist((x, y), r) for r in rd) <= 0.11
    key = lambda pts: sorted((round(x), round(y)) for x, y in pts)
    rc = [key(c) for c in ref["conc"]]
    for pts, closed, layer, *_ in D.pl:
        if layer == "CBC_CONC":
            assert key(pts) in rc
    assert len(D.leaders) == len(lab)
    for p, q, s, _ in D.leaders:
        assert s in lab, f"label text not in reference drawing: {s}"
        assert math.dist(p, lab[s]["arrow"]) <= 1.0
        assert math.dist(leader_landing(D, p, q, s), lab[s]["landing"]) <= 10.0     # 0.5 mm on paper


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"{n} tests passed")
