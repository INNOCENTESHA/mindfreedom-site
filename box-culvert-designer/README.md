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
