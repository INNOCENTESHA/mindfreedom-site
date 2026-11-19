"""The application writes its own CBC_EXPORT.txt: derived keys match the reference, and the generator runs on it."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
import export_writer as X

REF = os.path.join(os.path.dirname(__file__), "..", "_reference", "zip", "DRAWINGS", "CBC_EXPORT.txt")


def _ref():
    import section_bb
    return section_bb.read_export(REF)


@pytest.mark.skipif(not os.path.exists(REF), reason="reference export not present")
def test_derived_geometry_matches_reference():
    P = _ref()
    prim = {k: P[k] for k in X.PRIMARY_DEFAULTS if k in P}
    prim.update({k: P[k] for k in ("INV_OUT", "INV_IN", "OUT_D", "OUT_S", "LAP_MULT", "DIST_S") if k in P})
    levels = {k: P[k] for k in ("ROAD_FGL", "OGL_OUT", "OGL_IN") if k in P}
    D = X.derive(prim, levels)
    for k, tol in (("W_CLEAR", 0.5), ("W_TOT", 0.5), ("H_TOT", 0.5), ("SPLAY_OUT", 1), ("SPLAY_IN", 1),
                   ("L_WW_OUT", 1), ("L_WW_IN", 1), ("L_TOT", 1), ("WATERWAY", 0.01), ("GRADE_PCT", 0.01),
                   ("SOF_OUT", 1e-3), ("TOS_OUT", 1e-3), ("USB_OUT", 1e-3), ("APR_TOP_OUT", 1e-3),
                   ("CUTOFF_BOT_OUT", 1e-3), ("WW_TOP_OUT_END", 1e-3), ("TOS_IN", 1e-3), ("TOS_CL", 1e-3),
                   ("FILL_CL", 1.0), ("N_ACROSS_BARREL", 1), ("LAP_OUT", 1)):
        assert abs(D[k] - float(P[k])) <= tol, (k, D[k], P[k])


@pytest.mark.skipif(not os.path.exists(REF), reason="reference export not present")
def test_self_written_export_drives_the_generator():
    import section_bb
    from detailing import design as ddesign, bars as dbars
    from engine import Box, P as EP
    gen = os.path.join(os.path.dirname(__file__), "..", "_reference", "zip", "DRAWINGS")
    if not os.path.exists(os.path.join(gen, "CBC01_Drawing_Generator.lsp")): pytest.skip("generator not present")
    from cbcdraw.run import generate
    from cbcdraw import render
    # design a fresh 3-cell structure and write its export from scratch
    p = EP(); p.n_cells = 3; p.span = 2.0; p.height = 2.0
    b = Box(p).analyse(); R = ddesign.design(b, fck=p.fck, fyk=p.fyk, exposure="XC2", cover=p.cover)
    mu = dbars.multiples(R, (p.height + p.t_top + p.t_base) * 1000)
    F = R.faces; out = max((F[(m, "outer")] for m in ("top", "base", "walls")), key=lambda f: f.As)
    prim = dict(N_CELLS=3, SPAN_W=2000, SPAN_H=2000, T_TOP=250, T_BASE=250, T_WALL=250, T_INWALL=250,
                INV_OUT=100.0, INV_IN=100.16, BARREL_L=12000)
    design = dict(LAP_MULT=mu["lap_mult"], ANCH_MULT=mu["anch_mult"], FCK=25, OUT_D=out.dia, OUT_S=out.spacing,
                  TOPIN_D=F[("top", "inner")].dia, TOPIN_S=F[("top", "inner")].spacing, BOTIN_D=F[("base", "inner")].dia,
                  BOTIN_S=F[("base", "inner")].spacing, WALLIN_D=F[("walls", "inner")].dia, WALLIN_S=F[("walls", "inner")].spacing,
                  PIER_D=F[("piers", "inner")].dia, PIER_S=F[("piers", "inner")].spacing, DIST_D=R.dist["top"]["dia"], DIST_S=R.dist["top"]["spacing"])
    Q = section_bb.complete(dict(N_CELLS=3, SPAN_W=2000, SPAN_H=2000, T_TOP=250, T_BASE=250, T_WALL=250, T_INWALL=250,
                                 COVER=50, LAP_MULT=mu["lap_mult"], ANCH_MULT=mu["anch_mult"], **{k: design[k] for k in design if k.endswith(("_D", "_S"))}))
    D = section_bb.build(Q); sched = dbars.schedule(D, Q, 12000, 90)
    keys = X.build_export(prim, {"ROAD_FGL": 103.5}, design, sched, {"STRUCTURE_ID": "CBC TEST"})
    path = os.path.join(tempfile.gettempdir(), "self_export.txt")
    X.write_export(path, keys, X.schedule_rows(sched))
    rec, I, log, status = generate(path, gen, [os.path.join(gen, "LOGO_FLAT")])
    assert status == "ok"
    names = render.sheet_names(rec)
    assert len(names) >= 9
    assert sum(1 for _ in rec.all_ents()) > 1000
