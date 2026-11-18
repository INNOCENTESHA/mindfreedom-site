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
