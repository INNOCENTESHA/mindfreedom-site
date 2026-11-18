# CBC Parametric Designer — architecture (captured from user's own package)

Source: CBC_Box_Culvert_Parametric_Designer.xlsm + CBC01_Designer_Package.zip
(Road 221, CBC01, SMZ Zanzibar). This is the user's own IP; captured here to
calibrate/rebuild a clean-room equivalent.

## Pipeline
PARAMETERS sheet ──▶ modFrame (VBA direct-stiffness solver) ──▶ RESULTS (118 cases)
   │                                                               │
   ├─▶ ANALYSIS sheet (frame model echo)                           ▼
   ├─▶ MIDAS .mct export (independent verification, 1/4-cell)   DESIGN (EC2 checks)
   └─▶ EXPORT sheet ─▶ CBC_EXPORT.txt ─▶ CBC01_Drawing_Generator.lsp (AutoCAD) ─▶ DWG + sheet set

## Frame model (modFrame ≡ our frame.py)
- 2D centreline plane frame, 1.0 m longitudinal strip, BEAM elements.
- Members discretised at HB_STEP = 225 mm (10 div / 2.25 m c/l span).
- Winkler vertical springs under base: k = KS * trib (30000*0.225 = 6750 interior,
  3375 at ends). Node 1 also restrains horizontal (remove sway).
- E = 31000 MPa (C25/30, Ecm).

## Loading — BS 5400 HB 37.5 (abnormal vehicle) + at-rest earth
- SW  self weight (gamma_conc 25)
- EV  vertical fill on top slab (gamma_soil 20 x fill)
- EH  lateral earth, AT-REST K0 = 0.5, triangular with depth
- LS  surcharge 16.67 kPa -> lateral both walls; LS1 one wall only (asymmetry)
- HB  wheel = HB_UNITS*10/4 = 37.5*10/4 = 93.75 kN; contact pressure 1.1 N/mm2;
      axle spacing 1800 mm; wheel spacing 1000 mm; dispersed through fill 2V:1H
      over HB_DISP; moved across top slab in 225 mm steps.
      HB1 = single axle @ x ; HB2 = two axles @ x and x+1800. 11 positions each.
- Partial factors: gamma_G 1.35 (1.0 min), gamma_Q 1.35.

## RC design — EN 1992-1-1 (hybrid: EC2 member design, BS bond/lap)
- fcd = 0.85 fck/1.5 ; fyd = fyk/1.15 ; fctm = 0.3 fck^(2/3)
- Flexure: K = M/(b d^2 fck), K<=0.167, z = d(0.5+sqrt(0.25-K/1.134))<=0.95d
- Shear: VRd,c (cl 6.2.2, no links), rho from tension bars, vmin floor
- Crack width: cl 7.3.4 (kt 0.4), sigma_s <= 0.8 fyk, wk <= 0.3 mm (XC2)
- Min steel 0.26 fctm/fyk b d ; slenderness check on outer walls (cl 5.8.3.1)
- Lap/anchorage: employer rule fy460/grade30 -> 50x dia lap, 40x anchorage
  (else 0.95 fy/(4 beta sqrt fcu))

## Secondary elements
Wing walls (flared 30deg, stem flexure Mk=K0 g H^3/6 + K0 q H^2/2),
aprons (in/out), cut-off walls, haunches (150), blinding (75), chamfer 20.

## Target outputs for THIS structure (4-cell 1500x1500) — calibration checkpoints
- DESIGN_STATUS = PASS ; MAXUTIL = 0.84 ; GOVERN = "Shear - Top slab at d"
- Bearing: SLS 119.3 kPa, ULS 161.4 kPa (allow 210)
- Main bars: BARREL outer T16@150, top-inner T16@200, base-inner T16@200,
  wall-inner T12@200, pier T12@200, dist T12@200, haunch T12@200
- Concrete 98.62 m3 ; steel 11,115 kg (112.7 kg/m3)
- BBS: 15 bar marks, BS 8666 shape codes (21, 99, 11, 00)

## Drawing generator (AutoLISP chain)
CBC01_Drawing_Generator.lsp loads: RC_Extension(1/2/3), Paging, Packing,
Anchorage, Laps. Reads CBC_EXPORT.txt (P|KEY|TYPE|VALUE and B|mark|... rows).
Produces A3 sheets, title block w/ logos, BBS table, SGR-style views,
mleaders, range dims, staggered-lap table. Plot style CBC_A3.ctb.
