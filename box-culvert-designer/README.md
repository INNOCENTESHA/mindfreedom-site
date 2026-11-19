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

## Run
```bash
pip install numpy ezdxf
python run.py   # writes outputs/box_culvert.dxf + report
```

## Requirements
numpy, ezdxf (matplotlib optional, for PNG preview).

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
