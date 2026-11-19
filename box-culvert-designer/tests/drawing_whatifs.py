"""
What-ifs through the drawing generator: the parameter export is altered (structure size, bar sizes, cover, skew ...),
the generator is executed on each variant, and the result must be a complete, valid drawing set.

    python tests/drawing_whatifs.py CBC_EXPORT.txt generator_folder
Needs the generator files, which are not part of this repository.
"""
import os, sys, tempfile, time, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def variant(lines, changes):
    """Apply {KEY: value} and recompute the derived sizes that follow from the structure."""
    P = {}
    for ln in lines:
        f = ln.rstrip("\n").split("|")
        if f[0] == "P": P[f[1]] = f
    num = lambda k: float(P[k][3])
    for k, v in changes.items(): P[k][3] = str(v)
    n = int(num("N_CELLS")); clear = n * num("SPAN_W") + (n - 1) * num("T_INWALL")
    P["W_CLEAR"][3] = str(clear); P["W_TOT"][3] = str(clear + 2 * num("T_WALL")); P["H_TOT"][3] = str(num("SPAN_H") + num("T_TOP") + num("T_BASE"))
    if "WATERWAY" in P: P["WATERWAY"][3] = str(round(n * num("SPAN_W") * num("SPAN_H") / 1e6, 3))
    for k in ("SOF_OUT", "SOF_IN"): P[k][3] = str(round(num("INV_" + k[4:]) + num("SPAN_H") / 1000.0, 3))      # soffit = invert + clear height
    for k in ("TOS_OUT", "TOS_IN"): P[k][3] = str(round(num("SOF_" + k[4:]) + num("T_TOP") / 1000.0, 3))
    for k in ("USB_OUT", "USB_IN"): P[k][3] = str(round(num("INV_" + k[4:]) - num("T_BASE") / 1000.0, 3))
    out = []
    for ln in lines:
        f = ln.rstrip("\n").split("|")
        out.append("|".join(P[f[1]]) if f[0] == "P" else ln.rstrip("\n"))
    return "\n".join(out) + "\n"


CASES = [
    ("reference", {}),
    ("1 cell 2000 x 2000", dict(N_CELLS=1, SPAN_W=2000, SPAN_H=2000)),
    ("2 cells 3000 x 2500, 350 thick", dict(N_CELLS=2, SPAN_W=3000, SPAN_H=2500, T_TOP=350, T_BASE=350, T_WALL=350, T_INWALL=300)),
    ("3 cells 1200 x 1000", dict(N_CELLS=3, SPAN_W=1200, SPAN_H=1000)),
    ("6 cells 2500 x 2000", dict(N_CELLS=6, SPAN_W=2500, SPAN_H=2000, T_TOP=300, T_BASE=300, T_WALL=300, T_INWALL=250)),
    ("8 cells 1500 x 1500", dict(N_CELLS=8)),
    ("tall narrow 1000 x 3500", dict(N_CELLS=2, SPAN_W=1000, SPAN_H=3500, T_WALL=300)),
    ("wide flat 4000 x 1200", dict(N_CELLS=2, SPAN_W=4000, SPAN_H=1200, T_TOP=450, T_BASE=450)),
    ("heavy bars T25-125 / T20-150", dict(OUT_D=25, OUT_S=125, TOPIN_D=20, TOPIN_S=150, BOTIN_D=20, BOTIN_S=150, WALLIN_D=16, WALLIN_S=150, DIST_D=16, DIST_S=200)),
    ("light bars T10-300", dict(OUT_D=10, OUT_S=300, TOPIN_D=10, TOPIN_S=300, BOTIN_D=10, BOTIN_S=300, WALLIN_D=10, WALLIN_S=300, PIER_D=10, PIER_S=300, DIST_D=10, DIST_S=300)),
    ("cover 75, lap 60 d, anchorage 45 d", dict(COVER=75, LAP_MULT=60, ANCH_MULT=45)),
    ("cover 30, no haunch", dict(COVER=30, HAUNCH=0)),
    ("large haunch 300", dict(HAUNCH=300)),
    ("skew 60, flare 45", dict(SKEW_DEG=60, WW_FLARE_DEG=45)),
    ("skew 120, flare 15", dict(SKEW_DEG=120, WW_FLARE_DEG=15)),
    ("long barrel 30 m", dict(BARREL_L=30000)),
    ("short barrel 4 m, long aprons", dict(BARREL_L=4000, APRON_OUT_L=8000, APRON_IN_L=8000)),
    ("no aprons toe, deep cut-off", dict(APRON_TOE=0, CUTOFF_D=2000)),
]


def main(export, gen):
    import ezdxf
    from cbcdraw.run import generate
    from cbcdraw.export import to_dxf
    from cbcdraw import render
    lines = open(export, encoding="utf-8", errors="replace").read().splitlines(True)
    tmp = tempfile.mkdtemp(); bad = 0
    print(f"{'case':40s} {'status':8s} {'objects':>8s} {'sheets':>6s} {'audit':>6s} {'time':>6s}  notes")
    for name, ch in CASES:
        t0 = time.time(); path = os.path.join(tmp, "CBC_EXPORT.txt"); notes = []
        try:
            open(path, "w", encoding="utf-8").write(variant(lines, ch))
            rec, I, log, status = generate(path, gen, [os.path.join(gen, "LOGO_FLAT")])
            n = sum(1 for _ in rec.all_ents()); sheets = render.sheet_names(rec)
            unknown = sorted(getattr(I, "unknown", []) or [])
            if unknown: notes.append("unknown calls: " + ", ".join(unknown[:4]))
            notes += [l for l in log if "error" in l.lower() or "; error" in l.lower()][:2]
            dxf = os.path.join(tmp, "out.dxf"); to_dxf(rec, dxf, image_paths="relative")
            errs = len(ezdxf.readfile(dxf).audit().errors)
            ok = status == "ok" and errs == 0 and len(sheets) >= 9 and not notes
            print(f"{name:40s} {status:8s} {n:8d} {len(sheets):6d} {errs:6d} {time.time() - t0:5.0f}s  {'; '.join(notes)[:110]}")
        except Exception as ex:
            ok = False; print(f"{name:40s} CRASH    {type(ex).__name__}: {str(ex)[:120]}")
        bad += not ok
    print(f"\n{len(CASES) - bad} of {len(CASES)} variants produced a complete, valid drawing set")
    return bad


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1], sys.argv[2]) else 0)
