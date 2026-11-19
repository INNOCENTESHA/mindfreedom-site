"""
The drawing runtime: an AutoLISP interpreter and AutoCAD stand-in that execute the CBC generator.

test_lisp_*            - language semantics the generator depends on (always run)
test_generator_*       - run the real generator and compare every entity with the reference DWG;
                         need the generator sources and DWG fixtures (kept out of the repository)
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cbcdraw.lisp import Interp, parse, Dotted, to_str
from cbcdraw.acad import Host

HERE = os.path.dirname(__file__)
REF = os.path.join(HERE, "..", "_reference")
LISP = os.path.join(REF, "zip", "DRAWINGS")
FIX = os.path.join(REF, "fixtures")
HAVE = os.path.exists(os.path.join(LISP, "CBC01_Drawing_Generator.lsp")) and os.path.exists(os.path.join(FIX, "ref_model.json"))


def ev(src, host=None):
    return Interp(host).run(src)


def test_lisp_arithmetic():
    assert ev("(/ 7 2)") == 3 and ev("(/ 7 2.0)") == 3.5 and ev("(/ -7 2)") == -3
    assert ev("(fix 2.9)") == 2 and ev("(fix -2.9)") == -2
    assert ev("(max 1 2.0)") == 2.0 and isinstance(ev("(max 1 2.0)"), float)
    assert ev("(1+ 4)") == 5 and ev("(rem 7 3)") == 1


def test_lisp_dynamic_scope():
    # a callee sees and can change the caller's local variables
    assert ev("(defun callee () (setq x (+ x 1))) (defun caller (/ x) (setq x 10) (callee) x) (caller)") == 11
    assert ev("(setq g 1) (defun f (/ g) (setq g 5)) (f) g") == 1


def test_lisp_lists_and_pairs():
    assert ev("(cdr (assoc \"B\" (list (cons \"A\" 1) (cons \"B\" 2))))") == 2
    assert isinstance(ev("(cons 8 \"LAYER\")"), Dotted) and ev("(cdr '(0 . \"LINE\"))") == "LINE"
    assert ev("(cdr '(1))") is None and ev("(append nil '(1) nil '(2 3))") == [1, 2, 3]
    assert ev("(mapcar '(lambda (a b) (+ a b)) '(1 2 3) '(10 20 30))") == [11, 22, 33]
    assert ev("(cadr '(1 2 3))") == 2 and ev("(nth 5 '(1 2))") is None


def test_lisp_strings_and_numbers():
    I = Interp()
    assert I.run('(rtos 2.5 2 2)') == "2.50"
    I.sysvars["DIMZIN"] = 8                               # trailing zeros suppressed, as the generator sets it
    assert I.run('(rtos 2.5 2 2)') == "2.5" and I.run('(rtos 34.7 2 3)') == "34.7" and I.run('(rtos 12.0 2 1)') == "12"
    assert I.run('(substr "ABCDEF" 2 3)') == "BCD" and I.run('(strcat "A" "B")') == "AB" and I.run('(atof "12.5x")') == 12.5
    assert I.run('(wcmatch "CBC-04" "CBC-##*")') is not None and I.run('(wcmatch "LAYOUT1" "CBC-##*")') is None
    assert I.run('(vl-string-search "|" "P|KEY")') == 1 and I.run('(itoa 7)') == "7"


def test_lisp_sort_ties_as_autocad():
    assert ev("(vl-sort-i '(1 1 1) '<)") == [2, 1, 0]      # equal elements come back in reverse order
    assert ev("(vl-sort-i '(3 1 2) '<)") == [1, 2, 0] and ev("(vl-sort '(3 1 2) '<)") == [1, 2, 3]


def test_lisp_entities():
    I = Interp(Host())
    I.run('(entmake (list \'(0 . "LINE") (cons 8 "L1") \'(10 0.0 0.0 0.0) \'(11 5.0 0.0 0.0)))')
    assert to_str(I.run("(type (entlast))")) == "ENAME" and to_str(I.run("(type (vlax-ename->vla-object (entlast)))")) == "VLA-OBJECT"
    assert I.run('(cdr (assoc 8 (entget (entlast))))') == "L1"
    I.run("(entdel (entlast))")
    assert I.run("(ssget \"_X\" '((8 . \"L*\")))") is None


def _generate():
    from cbcdraw.run import generate
    return generate(os.path.join(LISP, "CBC_EXPORT.txt"), LISP, [os.path.join(LISP, "LOGO_FLAT")])


def test_generator_matches_reference_dwg():
    if not HAVE:
        print("   (generator sources / DWG fixtures not present - skipped)"); return
    from cbcdraw import verify
    rec, I, log, status = _generate()
    assert status == "ok"
    assert not rec.unknown, f"AutoCAD calls the stand-in does not implement: {sorted(rec.unknown)}"
    assert {n for n, _ in I.caught} <= {"VLA-ITEM"}, f"errors swallowed by the generator: {set(I.caught)}"
    model = verify.compare_model(rec, json.load(open(os.path.join(FIX, "ref_model.json")))["Model"], tol=0.3)
    paper = verify.compare_paper(rec, json.load(open(os.path.join(FIX, "ref_paper.json"))), tol=0.05)
    for name, res in (("model", model), ("paper", paper)):
        for t, v in res.items():
            assert v["mine_only"] == 0 and v["ref_only"] == 0, f"{name} {t}: {v}"
    assert sum(v["matched"] for v in model.values()) == 1639 and sum(v["matched"] for v in paper.values()) == 1267
    names = sorted(L.p["NAME"] for L in rec.layouts)
    assert names == ["CBC-00", "CBC-01", "CBC-02", "CBC-03", "CBC-04", "CBC-05", "CBC-06", "CBC-07", "CBC-08", "Model"]


def test_generator_dxf_is_valid():
    if not HAVE:
        print("   (generator sources / DWG fixtures not present - skipped)"); return
    import ezdxf
    from cbcdraw import export, geom
    rec, I, log, status = _generate()
    path = os.path.join(tempfile.mkdtemp(), "set.dxf")
    ex = export.to_dxf(rec, path)
    doc = ezdxf.readfile(path)
    assert len(doc.audit().errors) == 0 and ex.stats.get("MLEADER_AS_GEOMETRY", 0) == 0
    assert [n for n in doc.layouts.names() if n != "Model"] == [f"CBC-0{i}" for i in range(9)]
    assert len(doc.modelspace().query("MULTILEADER")) == 84 and len(doc.modelspace().query("DIMENSION")) == 159
    assert sum(len(doc.layouts.get(n).query("VIEWPORT")) for n in doc.layouts.names() if n != "Model") >= 52
    tb = [e for e in rec.layouts.items["CBC-01"].block.live() if e.t == "ACAD_TABLE"][0]
    assert abs(sum(geom.table_rows(tb)) - 28.0) < 1e-6           # title block stays 384 x 28 mm


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"{n} tests passed")
