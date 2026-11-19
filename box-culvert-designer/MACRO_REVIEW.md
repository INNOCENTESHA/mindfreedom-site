# How the original AutoCAD drawings are generated — review and corrections

You asked whether I could read the whole macro set and work out how the drawings were produced, copy the *style*
but not the *mistakes*, and in particular make the toe uniform. I read all of it: **4,828 lines of VBA** in the
workbook and **3,640 lines of AutoLISP** in the eight `CBC01_*.lsp` files. This is what it does and what I changed.

## Two layers

**1. The Excel workbook (VBA) — analysis and the parameter hand-off.**

| Sub | Role |
|---|---|
| `BuildModel` | builds the plane-frame nodes and elements of the box |
| `BuildLoads` / `BuildCases` | self weight, earth pressure, surcharge, the HB vehicle at each position, and the load combinations |
| `Solve` / `RunFrame` | the direct-stiffness solver (this is what I reimplemented in `engine.py` / `frame.py`) |
| `WriteExportTxt` | writes `CBC_EXPORT.txt` — ~166 `P|KEY|type|value` lines and the `B|` bar-schedule rows (reimplemented in `export_writer.py`) |
| `ExportMCTTo` | **writes a MIDAS `.mct` text file** — so a MIDAS export already exists in the VBA and can be ported (I had wrongly listed this as missing) |

**2. The AutoLISP generator — the drawings.** `cbc:drawtxt` → `cbc:main` reads the export and draws into AutoCAD
model space with `entmake` / ActiveX (`vla-*`) calls. The sheets:

- `cbc:sheet1` — **General Arrangement**: plan, longitudinal section A-A, cross-section B-B, the *setting-out and
  hydraulic data* table, and the general notes.
- `cbc:sheet2` … and `CBC01_RC_Extension.lsp / 2 / 3` — the **reinforcement detail** sheets (barrel section, slab
  plans, side-wall and wing-wall elevations, apron and cut-off details, typical bar details).
- `cbc:sheet4` (+ `CBC01_Packing.lsp`) — the **bar bending schedule** table.
- `CBC01_Paging.lsp` / `CBC01_Packing.lsp` — lay the views out on A3 sheets and rescale a view that is too big
  (this is the "one view at 1:nn" logic).
- `CBC01_Anchorage.lsp` / `CBC01_Laps.lsp` — draw the bent bar ends, lap ticks and lap notes.

Geometry is built by a few shared helpers: `cbc:geom` (reads every parameter into globals), `cbc:cellpoly` (a cell
opening), and **`cbc:outerpoly` (the barrel concrete outline)**. Because `cbc:outerpoly` is used by *all eight*
section drawings, it is the single place that controls the barrel's outer shape.

My `cbcdraw/` package is a from-scratch AutoLISP interpreter plus an AutoCAD object-model stand-in, so I can run
their generator headlessly and reproduce the reference drawing to 0.3 mm. Running their generator verbatim is why
the first drawings carried their faults — which is what you objected to.

## The faults, and what I did

### 1. The toe was on the wing walls but not the box barrel — **fixed**

The wing-wall base (`WW_T_BASE`) projects beyond the wing-wall stem, but `cbc:outerpoly` drew the barrel base
**flush** with the outer walls (base from `-tb`, outer faces at `±W_TOT/2`, no projection). So the barrel exterior
(side) walls had no toe while the wings did — the inconsistency you saw.

I rewrote `cbc:outerpoly` to project the base by the **`TOE`** parameter beyond *both* outer walls, as a free-edge
step at invert level, exactly mirroring the wing-wall toe. It is identical to the original when `TOE = 0` (so the
0.3 mm reference reproduction still passes), and the blinding under the section was widened to match. The app's
`Toe` input now drives the toe on the barrel section **and** the wings uniformly, and the native reinforcement
section (`section_bb.py`) already drew the barrel toe. The corrected generator file is delivered alongside this note.

### 2. The bar type letter was hard-coded `T` (grade 460) — **fixed**

The labels and the legend read `T16-150` and *"T = HIGH YIELD BAR GRADE 460"* regardless of the steel grade. Under
BS 8666 the type letter is by grade: **R** (250), **T** (460, BS 4449:1997), **H** (500, BS 4449:2005), **G** (600).
So designing with fyk = 500 and still printing `T` is wrong. The native drawing and schedule now pick the letter from
the grade (`bars.bar_prefix`), e.g. `H16-150` at grade 500. *Note:* the legend text inside the LISP title block still
says "GRADE 460"; if you issue grade-500 drawings through the LISP, that one note needs the same change.

### 3. My own bar marks had collided with the scheme — **fixed**

When I added bars I had reused marks 11 and 12, which in the established scheme are the inlet-apron and wing-wall
vertical bars. I renumbered: the secondary elements now follow the generator's scheme (09 apron transverse, 10 apron
longitudinal, 12 wing-wall vertical, 13 wing-wall horizontal, 14 cut-off), and my additions use free marks (15 the
lapped outer-wall bar, 17 the toe U-cap, 21 the starters — as the generator does).

## Still carried from the original (not yet changed)

- The **cross-section is still drawn square at a skew** (plan, lengths, counts and the schedule are skew-aware; the
  section outline is not rotated). This is on the list.
- The LISP **title-block legend** text is fixed English/grade-460 wording.
- The generator remains **your proprietary LISP**, run through my interpreter. For a product you own outright, the
  section/elevation drawing should be reimplemented natively (as `section_bb.py` already is for the barrel RC
  section); until then the full sheet set needs the generator files.

## Opportunity found

`ExportMCTTo` in the VBA is a working **MIDAS `.mct` exporter**. I can port it to Python so the app writes a MIDAS
model directly — closing the "no MIDAS export" gap with your own proven mapping rather than a guess. Say the word.
