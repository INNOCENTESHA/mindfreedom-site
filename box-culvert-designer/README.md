# Box Culvert Parametric Designer

Parametric single-cell RC box culvert tool: plane-frame analysis (MIDAS/STAAD
style) on a Winkler soil mat, Eurocode 2 limit-state RC design, and AutoCAD
**DXF** detail export (section, reinforcement, dimensions, bar bending schedule).

## Modules
- `frame.py`  – 2D direct-stiffness plane-frame solver (validated vs. closed-form beams)
- `culvert.py`– parametric geometry, load cases (SW/EV/EH/SUR/LL/WA), combinations
- `design.py` – EC2 flexure, shear, min-steel, bar selection
- `dxf_export.py` – AutoCAD DXF generator (ezdxf)
- `run.py`    – end-to-end: analyse -> design -> DXF + calc report

## Starting the program

**Windows** — install Python 3.11 or newer from python.org (tick *Add python.exe to PATH*), then double-click
`CBC_Designer.bat`. The first start creates a private environment in `.venv` and installs the libraries of
`requirements.txt` (internet needed once); later starts open the window directly. A `CBC_EXPORT.txt` placed next to
the program is loaded automatically, or drag one onto the `.bat` file.

`build_exe.bat` builds a stand-alone `dist\CBC_Designer\CBC_Designer.exe` with PyInstaller, for computers without Python.

**Any system, from a terminal**

    pip install -r requirements.txt
    python app.py                              # default 4-cell culvert
    python app.py --export CBC_EXPORT.txt      # structure and drawing set of a parameter export

The drawing sheets need the generator files in a `generator` folder next to `app.py` (or `CBC_GENERATOR_DIR`).

## Workspace

- **Ribbon** — File, Structure, Properties, Boundary, Load, Analysis, Results, Design, Detailing, Drawings, View.
- **Tree Menu** — *Parameters* (all inputs) and *Works* (structure, properties, boundaries, load cases, combinations,
  results; every entry opens its table, view or input).
- **Model View** — model, loads, deformed shape, reactions, and moment / shear / axial diagrams with a banded legend,
  for any load case, the governing combination or the envelope; node and element numbers on demand.
- **Tables** — nodes, elements, load cases, combinations, displacements, reactions, beam forces (copy to Excel).
- **Message Window** — command and analysis messages, with every unsatisfied check listed.
- `F5` analyse and design, `Ctrl+S` / `Ctrl+O` save and open a project (`.cbc`), `Ctrl+N` new.

## Bars as supplied, and skew

- No scheduled bar exceeds the 12 m stock length, the preferred sizes, a supplied steel grade, the 2750 mm transport
  width of bent shapes or the BS 8666 minimum legs (`detailing/bars.py`). Longer transverse bars are cut and lapped in
  two alternating families with lap centres at least 1.3 l0 apart. Lap positions follow one rule in both slabs:
  **top bars are never lapped at or near a support** (laps at mid-span of the cells) and **bottom bars are never lapped
  at or near mid-span** (laps over the piers). U-bars too tall to travel get short legs and a lapped wall bar
  (mark 11); a toe hairpin too tight to bend becomes a separate U-cap (mark 12).
- Skew (`detailing/skew.py`): the plan is drawn with the road horizontal. Barrel ends and apron ends are parallel to
  the road, the walls are L / sin(skew) long with the true cross-section, and each wing wall flares from the culvert
  axis to the apron end: length = A / (cos b -/+ sin b cot S), so the two walls of one end differ.
  `python tests/skew_simulation.py out.png` draws the plan at eight skews and tabulates the wall lengths.

## Secondary elements (wing walls, aprons, cut-off walls)

`detailing/retaining.py` designs each secondary element to EN 1992-1-1 and EN 1997-1: the wing wall as a cantilever
retaining wall (stem flexure and crack width; base auto-sized for overturning, sliding, bearing and the middle-third
rule), the apron as a ground slab (nominal mesh, flotation check), and the cut-off wall (U-bars, scour depth). Their
reinforcement is scheduled (`bars.secondary_schedule`) and their checks appear in the Code checks tab.

## Drawings from the app's own design

`export_writer.py` writes a complete `CBC_EXPORT.txt` (100+ parameters and the bar schedule) from the app's analysis,
design and schedule, so the AutoCAD sheet set is produced for the structure designed in the app, with no workbook.
Derived geometry and levels were checked against the reference export to the millimetre (`tests/test_export.py`).
The Drawings tab uses this automatically when no workbook export is loaded; add inverts and the road level under
"Levels and secondary geometry".

## Licensing and protection

The app requires a signed licence (`licence.cbclic`); without one it runs in evaluation mode (analysis and design
work, drawing export is disabled). Licences are Ed25519-signed by the vendor; the app carries only the public key and
verifies with a dependency-free verifier. A signed `manifest.cbcsig` lets the app detect tampering at start-up.
Issue licences and sign builds with `tools/licence_admin.py`. **Read `PROTECTION.md`** for the workflow and the honest
limits, and `LICENSE_AGREEMENT.md` for the end-user licence (a template to have a lawyer complete).

    python tools/licence_admin.py keypair                        # once: make your signing keys
    python tools/licence_admin.py issue PRIV "Customer" 183      # a half-year licence -> licence.cbclic
    python tools/licence_admin.py sign-manifest PRIV > manifest.cbcsig

## Verification

    python -m pytest tests                     # closed-form frames, workbook comparison, detailing rules, GUI, drawing runtime
    python tests/scenarios.py 500              # what-if sweep with invariants (statics, code limits, bars inside the concrete)
    python tests/drawing_whatifs.py CBC_EXPORT.txt generator   # altered structures through the drawing generator

## Drawing set without AutoCAD (`cbcdraw/`)

`cbcdraw` runs the AutoLISP drawing generator (CBC01_Drawing_Generator.lsp and its
extension files) unchanged, outside AutoCAD, and records everything it draws:

- `lisp.py`   – AutoLISP interpreter (dynamic scoping, integer/real arithmetic, dotted pairs)
- `acad.py`   – stand-in for the AutoCAD object model (entmake/ssget, ActiveX objects, layouts, tables)
- `geom.py`, `metrics.py` – entity extents as AutoCAD reports them (the generator's packing engine measures its views)
- `fields.py` – title-block field codes
- `export.py` – DXF with model space, all layouts and viewports, leaders, dimensions, hatches, logos
- `render.py` – sheets to PNG / PDF
- `verify.py` – entity-by-entity comparison with data extracted from a reference DWG

```bash
python -m cbcdraw CBC_EXPORT.txt --lisp <generator folder> --dxf set.dxf --pdf set.pdf
python app.py --export CBC_EXPORT.txt          # Drawings tab shows the sheets
```

The generator sources, logos and produced drawings are project material and are not part of
this repository; put the generator in `generator/` or point `CBC_GENERATOR_DIR` at it.
Needs `fonttools`, `Pillow`, `ezdxf`, `matplotlib`; Arial Narrow or Liberation Sans Narrow for text metrics.

Tests: `python tests/test_cbcdraw.py` and `python tests/test_section_bb.py`.
