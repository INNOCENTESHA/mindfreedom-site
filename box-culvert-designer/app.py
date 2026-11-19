"""
CBC — Box Culvert Parametric Designer (desktop GUI, PySide6).
Parametric inputs -> plane-frame analysis (BS5400 HB) -> EN 1992-1-1 design.
Tabs: Model & Design | Analysis (BMD) | Detailing | Schedule (BBS) | Report.
"""
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.patches as mpatches
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
from PySide6 import QtCore, QtGui, QtWidgets as W

from engine import Box, P
from design import design_flexure, check_shear, bar_area
import section_bb, math
from detailing import design as ddesign, checks as dchecks, soil as dsoil, skew as dskew, ec2
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavBar

BLUE="#1b3a5c"; ACC="#2d7dd2"; OK="#1e8449"; BAD="#c0392b"; LIGHT="#f4f6f9"; CARD="#ffffff"; RED="#c0392b"

def find_generator():
    """Folder holding the AutoLISP drawing generator (CBC01_Drawing_Generator.lsp and its extensions)."""
    here=os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("CBC_GENERATOR_DIR"), os.path.join(here,"generator"), os.path.join(here,"_reference","zip","DRAWINGS")):
        if d and os.path.exists(os.path.join(d,"CBC01_Drawing_Generator.lsp")): return d
    return None

def spin(val, lo, hi, step, dec=0):
    s=W.QDoubleSpinBox() if dec else W.QSpinBox()
    s.setRange(lo,hi); s.setValue(val)
    if dec: s.setDecimals(dec); s.setSingleStep(step)
    else: s.setSingleStep(int(step))
    s.setFixedHeight(26); return s

def pdui(): 
    a=W.QApplication.instance()
    if a: a.processEvents()

class Main(W.QMainWindow):
    def __init__(self, export=None, export_path=None):
        super().__init__()
        self.export=export            # dict read from a CBC_EXPORT.txt, or None
        self.export_path=export_path  # that file: input of the drawing generator
        self.gen_dir=find_generator(); self.drawset=None; self.sheet_cache={}
        self.setWindowTitle("CBC — Box Culvert Parametric Designer  v0.1")
        self.resize(1380, 880); self.setStyleSheet(f"QMainWindow{{background:{LIGHT};}}")
        self._build_header()
        central=W.QWidget(); self.setCentralWidget(central)
        root=W.QHBoxLayout(central); root.setContentsMargins(10,8,10,10); root.setSpacing(10)
        root.addWidget(self._input_panel(),0); root.addWidget(self._view_panel(),1)
        self.statusBar().showMessage("Ready"); self._apply_export(); self.run()

    # ---------------- header ----------------
    def _build_header(self):
        bar=W.QWidget(); bar.setFixedHeight(58); bar.setSizePolicy(W.QSizePolicy.Expanding,W.QSizePolicy.Fixed); bar.setStyleSheet(f"background:{BLUE};")
        h=W.QHBoxLayout(bar); h.setContentsMargins(16,0,16,0)
        t=W.QLabel("CBC   ·   Parametric Box Culvert Designer"); t.setStyleSheet("color:white;font:600 18px 'DejaVu Sans';")
        sub=W.QLabel("BS 5400 HB · EN 1992-1-1 · 2D frame on elastic foundation"); sub.setStyleSheet("color:#aecbed;font:12px 'DejaVu Sans';")
        col=W.QVBoxLayout(); col.setSpacing(0); col.addWidget(t); col.addWidget(sub); h.addLayout(col); h.addStretch(1)
        for name,slot in [("Analyse && Design",self.run),("Export DXF",self.export_dxf)]:
            b=W.QPushButton(name); b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{ACC};color:white;border:none;padding:8px 16px;border-radius:5px;font:600 13px;}}QPushButton:hover{{background:#3b8ee0;}}")
            b.clicked.connect(slot); h.addWidget(b)
        tb=W.QToolBar(); tb.setMovable(False); tb.addWidget(bar); tb.setStyleSheet(f"QToolBar{{border:none;padding:0;background:{BLUE};}}")
        self.addToolBar(QtCore.Qt.TopToolBarArea, tb)

    def _card(self,title):
        box=W.QGroupBox(title)
        box.setStyleSheet(f"QGroupBox{{background:{CARD};border:1px solid #dde3ea;border-radius:7px;margin-top:10px;font:600 12px;color:{BLUE};}}QGroupBox::title{{subcontrol-origin:margin;left:12px;padding:0 5px;}}")
        return box

    # ---------------- input panel ----------------
    def _input_panel(self):
        panel=W.QWidget(); panel.setFixedWidth(320); v=W.QVBoxLayout(panel); v.setContentsMargins(0,0,0,0); v.setSpacing(8)
        g=self._card("Geometry"); gl=W.QFormLayout(g); gl.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_cells=spin(4,1,8,1); self.i_span=spin(1.5,0.5,6,0.1,2); self.i_height=spin(1.5,0.5,6,0.1,2)
        self.i_ttop=spin(0.25,0.15,0.6,0.025,3); self.i_tbase=spin(0.25,0.15,0.6,0.025,3)
        self.i_twall=spin(0.25,0.15,0.6,0.025,3); self.i_fill=spin(1.0,0.0,8,0.1,2)
        for lab,wdg in [("No. of cells",self.i_cells),("Clear span (m)",self.i_span),("Clear height (m)",self.i_height),
            ("Top slab t (m)",self.i_ttop),("Base slab t (m)",self.i_tbase),("Wall t (m)",self.i_twall),("Fill depth (m)",self.i_fill)]:
            gl.addRow(lab,wdg)
        v.addWidget(g)
        m=self._card("Materials"); ml=W.QFormLayout(m); ml.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_fck=spin(25,20,60,5); self.i_fyk=spin(460,250,600,10); self.i_cover=spin(0.05,0.03,0.09,0.005,3)
        for lab,wdg in [("fck (MPa)",self.i_fck),("fyk (MPa)",self.i_fyk),("Cover (m)",self.i_cover)]: ml.addRow(lab,wdg)
        v.addWidget(m)
        l=self._card("Loading — BS 5400"); ll=W.QFormLayout(l); ll.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_hb=spin(37.5,0,45,2.5,1); self.i_soil=spin(20,14,24,1); self.i_k0=spin(0.5,0.3,1.0,0.05,2)
        self.i_sur=spin(16.67,0,40,1,2); self.i_ks=spin(30000,5000,120000,5000)
        for lab,wdg in [("HB units",self.i_hb),("γ soil (kN/m³)",self.i_soil),("K₀ at-rest",self.i_k0),("Surcharge (kPa)",self.i_sur),("Subgrade kₛ (kN/m³)",self.i_ks)]:
            ll.addRow(lab,wdg)
        v.addWidget(l)
        st=self._card("Site and detailing"); sl=W.QFormLayout(st); sl.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_toe=spin(0,0,1500,50); self.i_skew=spin(90.0,45.0,135.0,5.0,1); self.i_flare=spin(30.0,0.0,60.0,5.0,1)
        self.i_barrel=spin(10.5,2.0,120.0,0.5,2); self.i_apron=spin(4.75,0.0,15.0,0.25,2); self.i_joint=spin(15.0,5.0,40.0,1.0,1)
        self.i_expo=W.QComboBox(); self.i_expo.addItems(["XC2","XC3","XC4","XD1","XD2","XS1","XS2","XC1"]); self.i_expo.setFixedHeight(26)
        self.i_wk=spin(0.30,0.10,0.40,0.05,2)
        for lab,wdg in [("Toe, walls + wing walls (mm)",self.i_toe),("Skew of axis to road (°)",self.i_skew),("Wing wall flare (°)",self.i_flare),
            ("Barrel length (m)",self.i_barrel),("Apron length (m)",self.i_apron),("Max joint spacing (m)",self.i_joint),
            ("Exposure class",self.i_expo),("Crack width limit (mm)",self.i_wk)]:
            sl.addRow(lab,wdg)
        v.addWidget(st); v.addStretch(1)
        sc=W.QScrollArea(); sc.setWidget(panel); sc.setWidgetResizable(True); sc.setFixedWidth(345)
        sc.setFrameShape(W.QFrame.NoFrame); sc.setStyleSheet(f"QScrollArea{{background:{LIGHT};}}")
        return sc

    # ---------------- view panel (tabs) ----------------
    def _view_panel(self):
        panel=W.QWidget(); v=W.QVBoxLayout(panel); v.setContentsMargins(0,0,0,0); v.setSpacing(8)
        self.banner=W.QLabel("—"); self.banner.setFixedHeight(54); self.banner.setAlignment(QtCore.Qt.AlignVCenter); v.addWidget(self.banner)
        self.tabs=W.QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab{padding:8px 18px;font:600 12px;color:#4a627a;background:#e7edf3;border:1px solid #dde3ea;border-bottom:none;border-top-left-radius:6px;border-top-right-radius:6px;margin-right:2px;}" "QTabBar::tab:selected{background:#ffffff;color:#1b3a5c;}" "QTabWidget::pane{border:1px solid #dde3ea;border-radius:0 7px 7px 7px;background:#ffffff;}")
        # Tab 1 — Model & Design
        t1=W.QWidget(); l1=W.QVBoxLayout(t1)
        self.fig1=Figure(figsize=(8,3.5),facecolor="white"); self.cv1=Canvas(self.fig1); l1.addWidget(self.cv1,3)
        self.table=W.QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["Check","Location","Action","Required","Provided","Util.","Status"])
        self.table.horizontalHeader().setStretchLastSection(True); self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("QTableWidget{font:12px 'DejaVu Sans';gridline-color:#e3e8ee;}QHeaderView::section{background:#eef2f7;padding:5px;border:none;font:600 12px;color:#30506f;}")
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers); l1.addWidget(self.table,2)
        self.tabs.addTab(t1,"Model · Design")
        # Tab 2 — Analysis
        t2=W.QWidget(); l2=W.QVBoxLayout(t2); self.fig2=Figure(figsize=(8,6),facecolor="white"); self.cv2=Canvas(self.fig2); l2.addWidget(self.cv2)
        self.tabs.addTab(t2,"Analysis")
        # Tab 3 — Detailing
        t3=W.QWidget(); l3=W.QVBoxLayout(t3); l3.setContentsMargins(4,4,4,4); l3.setSpacing(2)
        self.fig3=Figure(figsize=(8,6),facecolor="black"); self.cv3=Canvas(self.fig3)
        nb=NavBar(self.cv3,t3); nb.setStyleSheet("QToolBar{border:none;}"); l3.addWidget(nb); l3.addWidget(self.cv3,1)
        self.lb_det=W.QLabel(""); self.lb_det.setStyleSheet("color:#4a627a;font:11px;"); l3.addWidget(self.lb_det)
        self.tabs.addTab(t3,"Detailing")
        # Tab 4 — Schedule
        t4=W.QWidget(); l4=W.QVBoxLayout(t4)
        self.bbs=W.QTableWidget(0,8); self.bbs.setHorizontalHeaderLabels(["Mark","Member","Bar","No.","Shape (BS 8666)","A (mm)","Length (mm)","Mass (kg)"])
        self.bbs.horizontalHeader().setStretchLastSection(True); self.bbs.verticalHeader().setVisible(False)
        self.bbs.setStyleSheet(self.table.styleSheet()); self.bbs.setEditTriggers(W.QAbstractItemView.NoEditTriggers); l4.addWidget(self.bbs)
        self.tabs.addTab(t4,"Schedule (BBS)")
        # Tab 5 — Report
        t5=W.QWidget(); l5=W.QVBoxLayout(t5); self.report=W.QTextEdit(); self.report.setReadOnly(True)
        self.report.setStyleSheet(f"QTextEdit{{background:{CARD};border:none;font:13px 'DejaVu Sans';}}"); l5.addWidget(self.report)
        self.tabs.addTab(t5,"Report")
        # Code checks: every clause that governs the design and detailing
        tc=W.QWidget(); lc=W.QVBoxLayout(tc); self.lb_chk=W.QLabel(""); self.lb_chk.setStyleSheet(f"font:600 13px;color:{BLUE};padding:4px;"); lc.addWidget(self.lb_chk)
        self.chk=W.QTableWidget(0,7); self.chk.setHorizontalHeaderLabels(["Group","Clause","Item","Value","Limit","Status","Basis / note"])
        self.chk.horizontalHeader().setStretchLastSection(True); self.chk.verticalHeader().setVisible(False)
        self.chk.setStyleSheet(self.table.styleSheet()); self.chk.setEditTriggers(W.QAbstractItemView.NoEditTriggers); lc.addWidget(self.chk)
        self.tabs.addTab(tc,"Code checks")
        # Ground and plan: soil strata, water, skewed plan with the wing walls
        tg=W.QWidget(); lg=W.QHBoxLayout(tg); lft=W.QVBoxLayout()
        self.use_ground=W.QCheckBox("Use the layered ground below (earth pressure, water, subgrade stiffness, bearing)"); self.use_ground.setChecked(False)
        lft.addWidget(self.use_ground)
        self.soil=W.QTableWidget(4,8); self.soil.setHorizontalHeaderLabels(["Layer","Thickness m","γ kN/m³","γsat kN/m³","φ′ °","c′ kPa","cu kPa","E′ MPa"])
        for r,rowv in enumerate([("Fill / embankment",1.5,19,20,30,0,"",20),("Firm to stiff clay",3.0,19,20,26,5,90,25),("Dense sand",10.0,20,21,36,0,"",60),("",0,"","","","","","")]):
            for c,val in enumerate(rowv): self.soil.setItem(r,c,W.QTableWidgetItem(str(val)))
        self.soil.setStyleSheet(self.table.styleSheet()); self.soil.resizeColumnsToContents(); self.soil.setMaximumHeight(170); lft.addWidget(self.soil)
        wr=W.QHBoxLayout(); wr.addWidget(W.QLabel("Water table below ground (m, 0 = none)")); self.i_water=spin(0.0,0.0,30.0,0.5,2); wr.addWidget(self.i_water); wr.addStretch(1); lft.addLayout(wr)
        self.ground_txt=W.QTextEdit(); self.ground_txt.setReadOnly(True); self.ground_txt.setStyleSheet(f"QTextEdit{{background:{CARD};border:none;font:12px 'DejaVu Sans';}}"); lft.addWidget(self.ground_txt,1)
        lg.addLayout(lft,5)
        self.figg=Figure(figsize=(5,6),facecolor="white"); self.cvg=Canvas(self.figg); lg.addWidget(self.cvg,6)
        self.tabs.addTab(tg,"Ground · Plan")
        # Tab 6 — Drawings: the full sheet set produced by the drawing generator
        t6=W.QWidget(); l6=W.QVBoxLayout(t6); bar=W.QHBoxLayout()
        self.cb_sheet=W.QComboBox(); self.cb_sheet.setMinimumWidth(150); self.cb_sheet.currentTextChanged.connect(self.show_sheet)
        bar.addWidget(W.QLabel("Sheet")); bar.addWidget(self.cb_sheet)
        for name,slot in [("Export all sheets to DXF",self.export_set_dxf),("Export all sheets to PDF",self.export_set_pdf)]:
            b=W.QPushButton(name); b.clicked.connect(slot); b.setStyleSheet(f"QPushButton{{background:{ACC};color:white;border:none;padding:6px 12px;border-radius:4px;font:600 12px;}}"); bar.addWidget(b)
        self.lb_set=W.QLabel(""); self.lb_set.setStyleSheet("color:#4a627a;font:12px;"); bar.addWidget(self.lb_set,1); l6.addLayout(bar)
        self.sheet_view=W.QLabel("Open this tab to generate the drawings."); self.sheet_view.setAlignment(QtCore.Qt.AlignCenter)
        self.sheet_view.setStyleSheet("background:#ffffff;color:#4a627a;font:13px;")
        sc=W.QScrollArea(); sc.setWidget(self.sheet_view); sc.setWidgetResizable(True); l6.addWidget(sc,1)
        self.tabs.addTab(t6,"Drawings")
        self.tabs.currentChanged.connect(lambda i: self.open_drawings() if self.tabs.tabText(i)=="Drawings" else None)
        v.addWidget(self.tabs,1); return panel

    def _apply_export(self):
        """Set the input panel from a loaded CBC_EXPORT.txt so the analysis uses the same structure."""
        E=self.export
        if not E: return
        g=lambda k,dv: float(E.get(k,dv))
        self.i_cells.setValue(int(round(g("N_CELLS",4)))); self.i_span.setValue(g("SPAN_W",1500)/1000); self.i_height.setValue(g("SPAN_H",1500)/1000)
        self.i_ttop.setValue(g("T_TOP",250)/1000); self.i_tbase.setValue(g("T_BASE",250)/1000); self.i_twall.setValue(g("T_WALL",250)/1000)
        self.i_fill.setValue(g("FILL_DESIGN",1000)/1000); self.i_fck.setValue(int(g("FCK",25))); self.i_fyk.setValue(int(g("FYK",460)))
        self.i_cover.setValue(g("COVER",50)/1000); self.i_soil.setValue(int(g("GAMMA_SOIL",20))); self.i_k0.setValue(g("K0",0.5))
        self.i_sur.setValue(g("SURCHARGE",16.67)); self.i_ks.setValue(int(g("KS",30000)))

    def params(self):
        p=P(); p.n_cells=self.i_cells.value(); p.span=self.i_span.value(); p.height=self.i_height.value()
        p.t_top=self.i_ttop.value(); p.t_base=self.i_tbase.value(); p.t_wall=self.i_twall.value(); p.t_pier=self.i_twall.value()
        p.fill=self.i_fill.value(); p.fck=self.i_fck.value(); p.fyk=self.i_fyk.value(); p.cover=self.i_cover.value()
        p.hb_units=self.i_hb.value(); p.hb_wheel=self.i_hb.value()*10/4
        p.gamma_soil=self.i_soil.value(); p.K0=self.i_k0.value(); p.surcharge=self.i_sur.value(); p.ks=self.i_ks.value()
        p.toe=self.i_toe.value()/1000.0; p.profile=self.ground_profile() if self.use_ground.isChecked() else None
        return p

    def ground_profile(self):
        """Soil profile from the table of the Ground tab (None when it holds no valid layer)."""
        def num(r,c,default=None):
            it=self.soil.item(r,c); t=it.text().strip() if it else ""
            try: return float(t)
            except ValueError: return default
        layers=[]
        for r in range(self.soil.rowCount()):
            th=num(r,1,0.0)
            if not th or th<=0: continue
            nm=self.soil.item(r,0).text() if self.soil.item(r,0) else f"Layer {r+1}"
            layers.append(dsoil.Layer(nm or f"Layer {r+1}",th,num(r,2,19.0),num(r,3,None),num(r,4,30.0),num(r,5,0.0) or 0.0,num(r,6,None),(num(r,7,30.0) or 30.0)*1000.0))
        if not layers: return None
        w=self.i_water.value()
        return dsoil.Profile(layers,w if w>0 else None)

    def site(self):
        p=self.p
        return dict(toe=self.i_toe.value(),skew=self.i_skew.value(),flare=self.i_flare.value(),apron=self.i_apron.value()*1000.0,
                    inner_width=(p.n_cells*p.span+(p.n_cells-1)*p.t_pier)*1000.0,barrel_length=self.i_barrel.value()*1000.0,
                    joint_spacing=self.i_joint.value()*1000.0,stock=12000.0,anch_mult=self.anch_mult,lap_mult=self.lap_mult)

    # ---------------- run ----------------
    def run(self):
        self.statusBar().showMessage("Analysing…"); pdui()
        p=self.params(); self.box=Box(p).analyse(); self.p=p
        self.uls=self.box.uls_combos(); self.sls=self.box.sls_combos()
        self.bearing_sls=max(self.box.bearing(c)[0] for c in self.sls)
        self.bearing_uls=max(self.box.bearing(c)[0] for c in self.uls)
        # member design to EN 1992-1-1: flexure, minimum steel, spacing, crack width, shear at d (links when needed)
        R=self.R=ddesign.design(self.box,fck=p.fck,fyk=p.fyk,exposure=self.i_expo.currentText(),wk_lim=self.i_wk.value(),cover=p.cover)
        self.anch_mult=math.ceil(max(v["anchorage_bent"]["multiple"] for v in R.lengths.values()))
        self.lap_mult=math.ceil(max(v["lap50"]["multiple"] for v in R.lengths.values()))
        class FD: pass
        rows=[]; self.design={}
        for m in ['top','base','walls','piers']:
            if m=='piers' and p.n_cells<2: continue
            fi,fo=R.faces[(m,'inner')],R.faces[(m,'outer')]; sh=R.shear[m]
            g=fi if fi.As>=fo.As else fo
            fd=FD(); fd.dia=g.dia; fd.spacing=g.spacing; fd.As_prov=g.As; fd.As_req=max(g.As_req,g.As_min); fd.util=g.util_M
            self.design[m]=dict(fd=fd,inner=fi,outer=fo,sh=sh,name=ddesign.NAMES[m])
            for tag,fc in (("inner",fi),("outer",fo)):
                if m=='piers' and tag=='outer': continue
                rows.append(("Flexure",f"{ddesign.NAMES[m]}, {tag if m!='piers' else 'each'} face",f"{fc.M_uls:,.1f} kNm/m",f"As {max(fc.As_req,fc.As_min):,.0f} mm²/m",
                             f"T{fc.dia}-{fc.spacing} ({fc.As:,.0f}), wk {fc.wk:.2f}",max(fc.util_M,fc.util_wk),fc.util_M<=1 and fc.util_wk<=1))
            if sh.links:
                L=sh.links; rows.append(("Shear",ddesign.NAMES[m]+" at d",f"{sh.V_d:,.1f} kN/m",f"VRd,s {L['VRd_s']:,.1f}",f"links T{L['dia']} {L['s_long']}×{L['s_trans']}",sh.V_d/max(L['VRd_s'],1e-9),L['ok']))
            else:
                rows.append(("Shear",ddesign.NAMES[m]+" at d",f"{sh.V_d:,.1f} kN/m",f"VRd,c {sh.VRd_c:,.1f}",sh.note or "no links needed",sh.util,sh.util<=1))
        allow=210.0
        rows.append(("Bearing","Founding, SLS",f"{self.bearing_sls:,.1f} kPa",f"≤ {allow:.0f} kPa","site investigation",self.bearing_sls/allow,self.bearing_sls<=allow))
        self.maxutil,self.govern=R.max_util()
        self._fill_checks(rows)
        self.checks=dchecks.run(self.box,R,self.site(),p.profile)
        nbad=sum(1 for r in self.checks if not r["ok"])
        self._fill_code_checks()
        ok=all(r[6] for r in rows) and nbad==0
        status="PASS" if ok else "REVIEW"; col=OK if ok else BAD
        self.banner.setStyleSheet(f"background:{col};color:white;border-radius:7px;padding:0 18px;font:600 15px 'DejaVu Sans';")
        self.banner.setText(f"  DESIGN {status}     ·     Max utilisation {self.maxutil:.2f}     ·     Governing: {self.govern}     ·     Bearing SLS {self.bearing_sls:.0f} / ULS {self.bearing_uls:.0f} kPa     ·     {len(self.checks)-nbad}/{len(self.checks)} code checks")
        self._draw_bb(self.fig1,p,False); self._draw_bmd(p); self._draw_bb(self.fig3,p,True); self._fill_bbs(p); self._fill_report(p); self._fill_ground(p)
        self.statusBar().showMessage(f"{p.n_cells}-cell {p.span:.2f}×{p.height:.2f} m · {len(self.box.u)} load cases · governing {self.govern}")

    def _fill_code_checks(self):
        rows=self.checks; self.chk.setRowCount(len(rows)); nbad=0
        for r,ck in enumerate(rows):
            if not ck["ok"]: nbad+=1
            for c,val in enumerate([ck["group"],ck["clause"],ck["item"],ck["value"],ck["limit"],"OK" if ck["ok"] else "FAIL",ck["note"]]):
                it=W.QTableWidgetItem(str(val))
                if c==5:
                    it.setTextAlignment(QtCore.Qt.AlignCenter); it.setForeground(QtGui.QBrush(QtGui.QColor(OK if ck["ok"] else BAD))); f=it.font(); f.setBold(True); it.setFont(f)
                self.chk.setItem(r,c,it)
        self.chk.resizeColumnsToContents()
        self.lb_chk.setText(f"EN 1992-1-1 / EN 1997-1 / BS 8666 — {len(rows)-nbad} of {len(rows)} checks satisfied"+("" if not nbad else f"   ·   {nbad} to resolve"))

    def _fill_ground(self,p):
        st=self.site(); pr=p.profile; b=self.box; H=[]
        H.append(f"<h3 style='color:{BLUE};margin:2px 0;'>Ground</h3>")
        if pr is None:
            H.append(f"<p>Uniform ground from the input panel: γ {p.gamma_soil:.0f} kN/m³, K₀ {p.K0:.2f}, kₛ {p.ks:,.0f} kN/m³.<br>Tick the box above to design on the soil strata.</p>")
        else:
            bq=pr.bearing(self.bearing_uls,b.base_width,b.founding_depth); g=bq["governing"]
            net=self.bearing_sls-pr.sigma_v(b.founding_depth)[0]; se=pr.settlement(net,b.base_width,b.founding_depth)
            H.append(f"<p>Founding level {b.founding_depth:.2f} m below ground, base {b.base_width:.2f} m wide.<br>"
                     f"Subgrade modulus from the strata: <b>{b.ks:,.0f} kN/m³</b> (used in the frame model).<br>"
                     f"Bearing: q<sub>Ed</sub> {g['q_ed']:.0f} kPa ≤ q<sub>Rd</sub> {g['qRd']:.0f} kPa — {g['governs']}, {g['layer']} (utilisation {bq['util']:.2f}).<br>"
                     f"Settlement under the net SLS pressure {net:.0f} kPa: <b>{1000*se['s']:.0f} mm</b>.</p>")
            H.append("<table cellpadding='3' style='font-size:12px;'><tr><td><b>Layer</b></td><td><b>from–to m</b></td><td><b>K₀</b></td><td><b>settlement mm</b></td></tr>")
            z=0.0; smap={}
            for nm,a,bb,ds in se["parts"]: smap[nm]=smap.get(nm,0.0)+ds
            for L in pr.layers:
                H.append(f"<tr><td>{L.name}</td><td>{z:.1f}–{z+L.thickness:.1f}</td><td>{L.k0:.2f}</td><td>{1000*smap.get(L.name,0.0):.1f}</td></tr>"); z+=L.thickness
            H.append("</table>")
        e=dskew.wing_walls(st["inner_width"],st["apron"],st["flare"],st["skew"]); se2=dskew.slab_effects(p.span*1000,st["skew"])
        H.append(f"<h3 style='color:{BLUE};margin:8px 0 2px;'>Plan — skew {st['skew']:g}°</h3>")
        if e.left["ok"] and e.right["ok"]:
            H.append(f"<p>Wing walls: left <b>{e.left['length']:,.0f} mm</b>, right <b>{e.right['length']:,.0f} mm</b> (flare {st['flare']:g}°, apron {st['apron']:,.0f} mm).<br>"
                     f"Apron end edge {e.apron_edge:,.0f} mm; apron area {e.apron_area/1e6:.1f} m² per end.<br>"
                     f"Slab end zones: skew span {se2['skew_span']:,.0f} mm, transverse steel × {se2['As_factor_end_zone']:.2f}, bars × {se2['bar_length_factor']:.2f} long — {se2['treatment']}.</p>")
        else:
            H.append(f"<p style='color:{BAD};'>{e.left.get('reason') or e.right.get('reason')}</p>")
        self.ground_txt.setHtml("".join(H))
        # ---- figure: earth pressure on the wall (left) and the plan with the wing walls (right)
        self.figg.clear(); ax=self.figg.add_axes([0.11,0.09,0.25,0.83]); zt=p.fill+p.t_top/2; zb=b.founding_depth
        px=lambda n:n*72.0/self.figg.dpi
        zs=[zt+(zb-zt)*k/60 for k in range(61)]
        if pr is not None:
            pe=[pr.lateral_at_rest(z)['earth'] for z in zs]; pw=[pr.lateral_at_rest(z)['water'] for z in zs]; ps=[pr.layer_at(z).k0*p.surcharge for z in zs]
            zz=0.0
            for L in pr.layers:
                ax.axhline(zz,color="#9fb3c8",lw=0.6); ax.text(0.5,zz+0.05,L.name,fontsize=px(10),color="#4a627a",va="top",transform=ax.get_yaxis_transform(),ha="center"); zz+=L.thickness
            if pr.water_depth: ax.axhline(pr.water_depth,color=ACC,lw=1,ls="--")
        else:
            pe=[p.K0*p.gamma_soil*z for z in zs]; pw=[0.0]*len(zs); ps=[p.K0*p.surcharge]*len(zs)
        tot=[a+c+d for a,c,d in zip(pe,pw,ps)]
        ax.fill_betweenx(zs,0,pe,color="#c9a66b",alpha=0.6,label="earth"); ax.fill_betweenx(zs,pe,[a+c for a,c in zip(pe,pw)],color=ACC,alpha=0.5,label="water")
        ax.plot(tot,zs,color=BLUE,lw=1.4,label="+ surcharge"); ax.axhspan(zt,zb,xmin=0,xmax=0.02,color=BLUE)
        ax.set_ylim(max(zb+1.0,(pr.depth() if pr is not None else zb)*0+zb+1.0),0); ax.set_xlabel("kPa",fontsize=px(11)); ax.set_ylabel("depth below ground (m)",fontsize=px(11))
        ax.set_title("At-rest pressure on the outer wall",fontsize=px(12),color=BLUE); ax.tick_params(labelsize=px(10)); ax.legend(fontsize=px(10),loc="lower right")
        ax2=self.figg.add_axes([0.44,0.04,0.54,0.92]); ax2.set_aspect("equal"); ax2.axis("off")
        Wo=p.W_ext*1000; Lb=st["barrel_length"]; th=math.radians(st["skew"]); ct=math.cos(th)/math.sin(th)
        def end(sign):
            # barrel end at x = sign*Lb/2 ; outward direction = sign
            pts=[]
            for side in (1,-1):
                y=side*Wo/2; pts.append((sign*Lb/2+ y*ct, y))
            return pts
        a1,a2=end(1); b1,b2=end(-1)
        ax2.fill([a1[1],a2[1],b2[1],b1[1]],[a1[0],a2[0],b2[0],b1[0]],color="#d9e2ec",ec=BLUE,lw=1.2)
        for sign in (1,-1):
            if not (e.left["ok"] and e.right["ok"]): break
            for w in (e.left,e.right):
                x0,y0=w["start"]; x1,y1=w["end"]
                # local end coordinates (x outward, y across) -> plan; inner width is centred on the axis
                X0=sign*(Lb/2+x0); X1=sign*(Lb/2+x1); Y0=y0*sign; Y1=y1*sign
                ax2.plot([Y0,Y1],[X0,X1],color=BAD,lw=2)
                ax2.text((Y0+Y1)/2,(X0+X1)/2,f" {w['length']:,.0f}",fontsize=px(11),color=BAD)
            xl,yl=e.left["end"]; xr,yr=e.right["end"]
            ax2.plot([yl*sign,yr*sign],[sign*(Lb/2+xl),sign*(Lb/2+xr)],color="#4a627a",lw=1,ls="--")
        ax2.plot([0,0],[-Lb/2-st["apron"]*1.15,Lb/2+st["apron"]*1.15],color=ACC,lw=0.8,ls="-.")
        r=Wo*1.6; ax2.plot([-r,r],[-r*ct,r*ct],color="#7a8b9a",lw=3,alpha=0.35); ax2.text(r*0.98,r*ct,"  road",fontsize=px(10),color="#4a627a",va="center")
        ax2.set_title(f"Plan: barrel {Lb/1000:.1f} m, skew {st['skew']:g}°, wing walls left / right",fontsize=px(12),color=BLUE)
        self.cvg.draw_idle()

    def _fill_checks(self,rows):
        self.table.setRowCount(len(rows))
        for r,(chk,loc,act,req,prov,util,ok) in enumerate(rows):
            for c,val in enumerate([chk,loc,act,req,prov,f"{util:.2f}","OK" if ok else "FAIL"]):
                it=W.QTableWidgetItem(val)
                if c in (5,6): it.setTextAlignment(QtCore.Qt.AlignCenter)
                if c==6:
                    it.setForeground(QtGui.QBrush(QtGui.QColor(OK if ok else BAD))); f=it.font(); f.setBold(True); it.setFont(f)
                self.table.setItem(r,c,it)
        self.table.resizeColumnsToContents()

    # ---------------- geometry helper ----------------
    def _wallxs(self,p):
        left=-p.t_wall/2; xs=[left+p.t_wall/2]; x=left+p.t_wall
        for i in range(p.n_cells):
            x+=p.span
            if i<p.n_cells-1: xs.append(x+p.t_pier/2); x+=p.t_pier
        xs.append(x+p.t_wall/2); return left,xs,(x+p.t_wall)-left

    def detail_params(self,p):
        """Parameters of the reinforcement drawing, with the keys of CBC_EXPORT.txt."""
        if self.export:
            Q=dict(self.export); Q["TOE"]=self.i_toe.value(); return Q
        R=self.R; mm=lambda v:round(v*1000.0); F=R.faces
        out=max((F[(m,'outer')] for m in ('top','base','walls')),key=lambda f:f.As)     # outer mat: one bar serves slab and wall faces
        Q=dict(N_CELLS=p.n_cells,SPAN_W=mm(p.span),SPAN_H=mm(p.height),T_TOP=mm(p.t_top),T_BASE=mm(p.t_base),
               T_WALL=mm(p.t_wall),T_INWALL=mm(p.t_pier),COVER=mm(p.cover),TOE=self.i_toe.value(),
               LAP_MULT=self.lap_mult,ANCH_MULT=self.anch_mult,
               OUT_D=out.dia,OUT_S=out.spacing,TOPIN_D=F[('top','inner')].dia,TOPIN_S=F[('top','inner')].spacing,
               BOTIN_D=F[('base','inner')].dia,BOTIN_S=F[('base','inner')].spacing,
               WALLIN_D=F[('walls','inner')].dia,WALLIN_S=F[('walls','inner')].spacing,
               DIST_D=R.dist['top']['dia'],DIST_S=R.dist['top']['spacing'])
        if p.n_cells>1: Q.update(PIER_D=F[('piers','inner')].dia,PIER_S=F[('piers','inner')].spacing)
        return Q

    def _draw_bb(self,fig,p,dark):
        """SECTION B-B - BARREL REINFORCEMENT, drawn exactly as the AutoCAD generator does."""
        self.bb=section_bb.build(self.detail_params(p))
        self._render_bb(fig,dark)
        if not getattr(fig,"_cbc_resize",None):          # text / line sizes follow the paper scale: redraw when resized
            fig._cbc_resize=fig.canvas.mpl_connect("resize_event",lambda ev,fg=fig,dk=dark:self._render_bb(fg,dk))

    def _render_bb(self,fig,dark):
        if getattr(fig,"_cbc_busy",False) or not hasattr(self,"bb"): return
        fig._cbc_busy=True
        try:
            fig.clear(); fig.set_facecolor("#000000" if dark else "#ffffff")
            if not dark:
                ax=fig.add_axes([0.005,0.005,0.99,0.99]); section_bb.to_mpl(self.bb,ax,dark=False,by_mark=True)
            else:
                P=section_bb.complete(self.detail_params(self.p)); a=P["W_TOT"]/2.0; toe=float(P.get("TOE",0) or 0); tb=P["T_BASE"]; hw=P["SPAN_H"]+P["T_TOP"]; sw=P["SPAN_W"]
                ax=fig.add_axes([0.005,0.47,0.99,0.525]); section_bb.to_mpl(self.bb,ax,dark=True,by_mark=True,legend=True)
                x1=-a+tb+P["T_WALL"]+min(900.0,sw*0.6)
                wins=[((-a-toe-120,x1,-tb-140,P["HAUNCH"]+520),"DETAIL A — base slab / outer wall"+(" / toe" if toe>0 else "")),
                      ((-a-120,x1,hw-P["T_TOP"]-P["HAUNCH"]-520,hw+90),"DETAIL B — top slab / outer wall")]
                if P["N_CELLS"]>1:
                    xp=-P["W_CLEAR"]/2.0+sw+P["T_INWALL"]/2.0
                    wins.append(((xp-650,xp+650,-tb-140,P["HAUNCH"]+520),"DETAIL C — base slab / pier wall"))
                n=len(wins)
                for k,(win,ttl) in enumerate(wins):
                    axd=fig.add_axes([0.01+k*(0.98/n),0.015,0.98/n-0.012,0.385]); section_bb.to_mpl(self.bb,axd,dark=True,window=win,annotate=False,by_mark=True,title=ttl)
                if hasattr(self,"lb_det"):
                    self.lb_det.setText(f"Bars at true diameter, one colour per bar mark · anchorage {self.anch_mult}ø and lap {self.lap_mult}ø from EN 1992-1-1 8.4 / 8.7 · zoom and pan with the toolbar"
                                        +("" if not self.bb.warnings else "   ·   "+self.bb.warnings[0]))
            fig.canvas.draw_idle()
        finally:
            fig._cbc_busy=False

    def _draw_section(self,fig,p,detailed):
        fig.clear(); ax=fig.add_subplot(111); ax.set_aspect("equal"); ax.axis("off")
        tw=p.t_wall; tp=p.t_pier; tt=p.t_top; tb=p.t_base; S=p.span; H=p.height
        left,xwalls,Wext=self._wallxs(p); OH=H+tt+tb
        ax.add_patch(mpatches.Rectangle((left,0),Wext,OH,facecolor="#d9e2ec",edgecolor=BLUE,lw=1.8,zorder=1))
        cx=left+tw
        for i in range(p.n_cells):
            ax.add_patch(mpatches.Rectangle((cx,tb),S,H,facecolor="white",edgecolor=BLUE,lw=1.2,zorder=2))
            if detailed:
                ax.add_patch(mpatches.Polygon([(cx,tb+H),(cx+0.15,tb+H),(cx,tb+H-0.15)],closed=True,facecolor="#eef2f7",edgecolor="#9fb3c8",lw=0.6,zorder=2))
                ax.add_patch(mpatches.Polygon([(cx+S,tb+H),(cx+S-0.15,tb+H),(cx+S,tb+H-0.15)],closed=True,facecolor="#eef2f7",edgecolor="#9fb3c8",lw=0.6,zorder=2))
            cx+=S+(tp if i<p.n_cells-1 else 0)
        c=p.cover; xr0=left+c; xr1=left+Wext-c
        ax.plot([xr0,xr1],[OH-c,OH-c],color=RED,lw=1.5,zorder=4)
        ax.plot([xr0,xr1],[c,c],color=RED,lw=1.5,zorder=4)
        if detailed:
            ax.plot([xr0,xr1],[tb+H-c+tb*0,tb+H-c],color=RED,lw=1.0,ls=(0,(4,2)),zorder=4)
            ax.plot([xr0,xr1],[tb+c,tb+c],color=RED,lw=1.0,ls=(0,(4,2)),zorder=4)
        for xw in xwalls:
            ax.plot([xw,xw],[c,OH-c],color=RED,lw=1.2,zorder=4)
        # dims
        ax.annotate("",(left,-0.5),(left+Wext,-0.5),arrowprops=dict(arrowstyle="<->",color=BLUE,lw=1.2))
        ax.text(left+Wext/2,-0.8,f"{Wext:.2f} m overall",ha="center",color=BLUE,fontsize=10)
        ax.annotate("",(left+Wext+0.55,0),(left+Wext+0.55,OH),arrowprops=dict(arrowstyle="<->",color=BLUE,lw=1.2))
        ax.text(left+Wext+0.8,OH/2,f"{OH:.2f} m",va="center",rotation=90,color=BLUE,fontsize=10)
        if detailed:
            cx=left+tw
            for i in range(p.n_cells):
                ax.annotate("",(cx,OH+0.35),(cx+S,OH+0.35),arrowprops=dict(arrowstyle="<->",color="#4a627a",lw=0.9))
                ax.text(cx+S/2,OH+0.5,f"{S:.2f}",ha="center",color="#4a627a",fontsize=8); cx+=S+tp
            # callouts
            ax.annotate(f"T{self.design['top']['fd'].dia}@{self.design['top']['fd'].spacing} — top slab",
                        (left+Wext*0.5,OH-c),(left+Wext*0.5,OH+0.95),ha="center",fontsize=8,color=RED,
                        arrowprops=dict(arrowstyle="->",color=RED,lw=0.8))
            ax.annotate(f"T{self.design['base']['fd'].dia}@{self.design['base']['fd'].spacing} — base slab",
                        (left+Wext*0.5,c),(left+Wext*0.5,-1.25),ha="center",fontsize=8,color=RED,
                        arrowprops=dict(arrowstyle="->",color=RED,lw=0.8))
            wtxt=f"T{self.design['walls']['fd'].dia}@{self.design['walls']['fd'].spacing} — walls (V)"
            ax.annotate(wtxt,(xwalls[0],OH*0.5),(left-1.5,OH*0.5),ha="right",fontsize=8,color=RED,va="center",
                        arrowprops=dict(arrowstyle="->",color=RED,lw=0.8))
            title=f"TYPICAL CROSS-SECTION — {p.n_cells} CELL {S*1000:.0f} × {H*1000:.0f}"
            ax.text(left-0.3,OH+1.3,title,color=BLUE,fontsize=11,fontweight="bold")
            ax.set_xlim(left-2.8,left+Wext+1.6); ax.set_ylim(-1.8,OH+1.7)
        else:
            ax.text(left+tw,OH+0.2,f"{p.n_cells} cell × {S:.2f} m clear × {H:.2f} m",color=BLUE,fontsize=10)
            ax.set_xlim(left-1.2,left+Wext+1.3); ax.set_ylim(-1.1,OH+0.6)
        fig.tight_layout(); fig.canvas.draw()

    # ---------------- BMD ----------------
    def _chain_moments(self,nodes,els,fmap):
        F=self.box.combine_F(fmap); xs=[];zs=[];Ms=[]
        for k,e in enumerate(els):
            el=self.box.fr.elements[e]; ni=self.box.fr.nodes[el.ni]
            xs.append(ni.x); zs.append(ni.y); Ms.append(F[e][2])
        last=self.box.fr.elements[els[-1]]; nj=self.box.fr.nodes[last.nj]
        xs.append(nj.x); zs.append(nj.y); Ms.append(-F[els[-1]][5])
        return np.array(xs),np.array(zs),np.array(Ms)

    def _gov_combo(self):
        best=None;bestv=-1
        for c in self.uls:
            F=self.box.combine_F(c); v=max(abs(F[e][2]) for e in self.box.members['top'])
            if v>bestv: bestv=v;best=c
        return best

    def _draw_bmd(self,p):
        self.fig2.clear(); ax=self.fig2.add_subplot(111); ax.set_aspect("equal"); ax.axis("off")
        fmap=self._gov_combo()
        left,xwalls,Wext=self._wallxs(p); OH=p.height+p.t_top+p.t_base
        # frame geometry (grey)
        for m,col in [('top','#8aa0b6'),('base','#8aa0b6')]:
            el0=self.box.members[m]
            for e in el0:
                el=self.box.fr.elements[e]; a=self.box.fr.nodes[el.ni]; b=self.box.fr.nodes[el.nj]
                ax.plot([a.x,b.x],[a.y,b.y],color=col,lw=2,zorder=2)
        for wc in self.box.wall_chains:
            ids=wc['ids']
            for k in range(len(ids)-1):
                a=self.box.fr.nodes[ids[k]]; b=self.box.fr.nodes[ids[k+1]]; ax.plot([a.x,b.x],[a.y,b.y],color='#8aa0b6',lw=2,zorder=2)
        # springs
        for nid in self.box.base_nodes:
            nx=self.box.fr.nodes[nid].x
            ax.plot([nx,nx],[0,-0.18],color='#b0bcc9',lw=0.7,zorder=1)
        ax.plot([left,left+Wext],[-0.18,-0.18],color='#b0bcc9',lw=0.7)
        # moment ordinates
        allM=[]
        series=[]
        series.append((*self._chain_moments([self.box.top_nodes],self.box.members['top'],fmap),'h'))
        series.append((*self._chain_moments([self.box.base_nodes],self.box.members['base'],fmap),'h'))
        for wc in self.box.wall_chains:
            xs=[];zs=[];Ms=[];F=self.box.combine_F(fmap)
            for k,e in enumerate(wc['els']):
                el=self.box.fr.elements[e]; ni=self.box.fr.nodes[el.ni]; xs.append(ni.x);zs.append(ni.y);Ms.append(F[e][2])
            last=self.box.fr.elements[wc['els'][-1]]; nj=self.box.fr.nodes[last.nj]; xs.append(nj.x);zs.append(nj.y);Ms.append(-F[wc['els'][-1]][5])
            series.append((np.array(xs),np.array(zs),np.array(Ms),'v'))
        for xs,zs,Ms,ori in series: allM.extend(np.abs(Ms))
        mmax=max(allM) or 1.0; scale=0.55/mmax
        for xs,zs,Ms,ori in series:
            if ori=='h':
                ax.fill_between(xs, zs, zs - Ms*scale, color=ACC, alpha=0.35, zorder=3)
                ax.plot(xs, zs - Ms*scale, color=ACC, lw=1.3, zorder=3)
            else:
                ax.fill_betweenx(zs, xs, xs + Ms*scale, color=ACC, alpha=0.35, zorder=3)
                ax.plot(xs + Ms*scale, zs, color=ACC, lw=1.3, zorder=3)
        # annotate peak
        ipk=int(np.argmax(np.abs(series[0][2]))); 
        ax.text(series[0][0][ipk], series[0][1][ipk]-series[0][2][ipk]*scale-0.15,
                f"{series[0][2][ipk]:.0f}", color=BLUE, fontsize=10*72.0/self.fig2.dpi, ha="center")
        ax.set_title(f"Bending moment envelope  ·  ULS, governing HB position  ·  max |M| = {mmax:.0f} kNm/m", color=BLUE, fontsize=12*72.0/self.fig2.dpi, loc="center", pad=8)
        ax.set_xlim(left-1.0,left+Wext+1.0); ax.set_ylim(-1.0,OH+1.0)
        self.fig2.tight_layout(); self.fig2.canvas.draw()

    # ---------------- BBS ----------------
    def _fill_bbs(self,p):
        if self.export and self.export.get("BBS"):
            rows=self.export["BBS"]; self.bbs.setRowCount(len(rows)); tot=0.0
            for r,b in enumerate(rows):     # mark, member, bar, dia, sp, nm, ne, total, shape, A, B, C, L, kg/m, weight, ...
                tot+=float(b[14])
                for c,val in enumerate([b[0],b[1],b[2],b[7],b[8],b[9],b[12],b[14]]):
                    it=W.QTableWidgetItem(str(val))
                    if c in (3,4,5,6,7): it.setTextAlignment(QtCore.Qt.AlignCenter)
                    self.bbs.setItem(r,c,it)
            self.bbs.resizeColumnsToContents(); self.bbs_total=tot; return
        left,xwalls,Wext=self._wallxs(p); OH=p.height+p.t_top+p.t_base
        d=lambda m:self.design[m]['fd'].dia; s=lambda m:self.design[m]['fd'].spacing
        def mass(dia,L,n): return bar_area(dia)/1e6*7850*(L/1000)*n
        bend=lambda dia:max(5*dia,90)
        Wmm=Wext*1000; OHmm=OH*1000; Hmm=p.height*1000
        n_across=int(Wmm/150)  # along barrel per metre-ish count placeholder
        rows=[]
        rows.append(("01","Top slab (U-bar)",f"T{d('top')}",1,"21",bend(d('top')),int(Wmm+2*Hmm*0.5),0))
        rows.append(("02","Base slab (U-bar)",f"T{d('base')}",1,"21",bend(d('base')),int(Wmm+2*Hmm*0.5),0))
        rows.append(("03","Top slab transverse",f"T{d('top')}",1,"21",bend(d('top')),int(Wmm-2*p.cover*1000),0))
        rows.append(("04","Base slab transverse",f"T{d('base')}",1,"21",bend(d('base')),int(Wmm-2*p.cover*1000),0))
        rows.append(("05","Outer wall vertical",f"T{d('walls')}",2,"21",bend(d('walls')),int(Hmm+2*300),0))
        if p.n_cells>1:
            rows.append(("06","Pier wall (both faces)",f"T{d('piers')}",2*(p.n_cells-1),"21",bend(d('piers')),int(Hmm+2*300),0))
        rows.append(("07","Haunch bars",f"T{d('piers') if p.n_cells>1 else d('walls')}",2*p.n_cells,"99",bend(12),int(2*220+480),0))
        rows.append(("08","Longitudinal distribution",f"T12",1,"00",0,10500,0))
        # fill masses
        out=[]
        for mk,mem,bar,no,shp,A,L,_ in rows:
            dia=int(bar[1:]); out.append((mk,mem,bar,no,shp,A,L,mass(dia,L,no)))
        self.bbs.setRowCount(len(out)); tot=0
        for r,(mk,mem,bar,no,shp,A,L,ms) in enumerate(out):
            tot+=ms
            for c,val in enumerate([mk,mem,bar,str(no),shp,f"{A:.0f}" if A else "—",f"{L:,}",f"{ms:,.1f}"]):
                it=W.QTableWidgetItem(val)
                if c in (3,5,6,7): it.setTextAlignment(QtCore.Qt.AlignCenter)
                self.bbs.setItem(r,c,it)
        self.bbs.resizeColumnsToContents()
        self.bbs_total=tot

    # ---------------- report ----------------
    def _fill_report(self,p):
        d=self.design
        def face(m): fd=d[m]['fd']; return f"T{fd.dia}@{fd.spacing} (As {fd.As_prov:,.0f} mm²/m, util {fd.util:.2f})"
        status="PASS" if self.maxutil<=1 and self.bearing_sls<=210 else "REVIEW"
        html=f"""
        <h2 style='color:{BLUE};margin-bottom:2px;'>Box Culvert — Structural Design Summary</h2>
        <p style='color:#5a6b7b;margin-top:0;'>BS 5400 HB {p.hb_units:.0f} loading · EN 1992-1-1 member design · 2D plane frame on Winkler foundation</p>
        <table cellpadding='5' style='font-size:13px;'>
        <tr><td><b>Configuration</b></td><td>{p.n_cells}-cell box, {p.span:.2f} m clear span × {p.height:.2f} m clear height</td></tr>
        <tr><td><b>Sections</b></td><td>Top {p.t_top*1000:.0f} · Base {p.t_base*1000:.0f} · Walls {p.t_wall*1000:.0f} mm</td></tr>
        <tr><td><b>Materials</b></td><td>Concrete C{p.fck:.0f}/{p.fck+8:.0f}, steel fyk {p.fyk:.0f} MPa, cover {p.cover*1000:.0f} mm</td></tr>
        <tr><td><b>Fill / earth</b></td><td>{p.fill:.2f} m fill · γsoil {p.gamma_soil:.0f} kN/m³ · K₀ {p.K0:.2f} · surcharge {p.surcharge:.1f} kPa</td></tr>
        <tr><td><b>Analysis</b></td><td>{len(self.box.u)} load cases incl. {len(self.box.hb_keys)} HB positions; Winkler kₛ {p.ks:,.0f} kN/m³</td></tr>
        </table>
        <h3 style='color:{BLUE};margin-bottom:2px;'>Reinforcement</h3>
        <table cellpadding='5' style='font-size:13px;'>
        <tr><td><b>Top slab</b></td><td>{face('top')}</td></tr>
        <tr><td><b>Base slab</b></td><td>{face('base')}</td></tr>
        <tr><td><b>Outer walls</b></td><td>{face('walls')}</td></tr>
        {('<tr><td><b>Pier walls</b></td><td>'+face('piers')+'</td></tr>') if p.n_cells>1 else ''}
        </table>
        <h3 style='color:{BLUE};margin-bottom:2px;'>Verification</h3>
        <table cellpadding='5' style='font-size:13px;'>
        <tr><td><b>Design result</b></td><td style='color:{OK if status=="PASS" else BAD};'><b>{status}</b></td></tr>
        <tr><td><b>Max utilisation</b></td><td>{self.maxutil:.2f}</td></tr>
        <tr><td><b>Governing check</b></td><td>{self.govern}</td></tr>
        <tr><td><b>Ground bearing</b></td><td>SLS {self.bearing_sls:.1f} kPa · ULS {self.bearing_uls:.1f} kPa (allow 210)</td></tr>
        <tr><td><b>Steel (barrel est.)</b></td><td>{getattr(self,'bbs_total',0):,.0f} kg per metre run of schedule marks</td></tr>
        </table>
        <p style='color:#90a0b0;font-size:11px;'>Prototype — figures recalculated live from the frame model. Not for construction.</p>
        """
        self.report.setHtml(html)

    def export_dxf(self, path=None):
        if not path:
            path,_=W.QFileDialog.getSaveFileName(self,"Export reinforcement drawing","SECTION_B-B_BARREL_REINFORCEMENT.dxf","AutoCAD DXF (*.dxf)")
        if not path: return
        section_bb.to_dxf(self.bb,path)
        self.statusBar().showMessage(f"DXF written: {path}  ({len(self.bb.bars())} bars, {len(self.bb.dots)} distribution bars)")

# ---------------------------------------------------------------- drawing set (added to Main below)
def _open_drawings(self):
    """Run the drawing generator once and list its sheets."""
    if self.drawset is not None: return
    if not self.gen_dir:
        self.sheet_view.setText("Drawing generator not found.\nPut CBC01_Drawing_Generator.lsp and its extension files in a 'generator' folder next to the app,\nor set CBC_GENERATOR_DIR."); return
    if not self.export_path:
        self.sheet_view.setText("No parameter export loaded.\nStart the app with  --export CBC_EXPORT.txt  to produce the drawings for that structure."); return
    self.statusBar().showMessage("Running the drawing generator…"); pdui()
    from cbcdraw.run import generate
    from cbcdraw import render
    rec,I,log,status=generate(self.export_path,self.gen_dir,[os.path.join(self.gen_dir,"LOGO_FLAT")])
    if status!="ok":
        self.sheet_view.setText("The generator stopped:\n"+"\n".join(log[-6:])); return
    self.drawset=dict(rec=rec,log=log,doc=None,names=render.sheet_names(rec))
    n=sum(1 for _ in rec.all_ents())
    self.lb_set.setText(f"   {len(self.drawset['names'])} sheets · {n:,} drawing objects · {log[-2] if len(log)>1 else ''}")
    self.cb_sheet.blockSignals(True); self.cb_sheet.addItems(self.drawset["names"]); self.cb_sheet.blockSignals(False)
    want=getattr(self,"start_sheet",None) or (self.drawset["names"][1] if len(self.drawset["names"])>1 else self.drawset["names"][0])
    self.cb_sheet.setCurrentText(want); self.show_sheet(want)

def _show_sheet(self,name):
    if not name or self.drawset is None: return
    from cbcdraw import render
    if name not in self.sheet_cache:
        self.statusBar().showMessage(f"Rendering sheet {name}…"); pdui()
        if self.drawset["doc"] is None: self.drawset["doc"]=render.build_doc(self.drawset["rec"])
        import tempfile
        path=os.path.join(tempfile.gettempdir(),f"cbc_sheet_{os.getpid()}_{name}.png")
        render.sheet_png(self.drawset["doc"],name,path,dpi=110); self.sheet_cache[name]=path
    pm=QtGui.QPixmap(self.sheet_cache[name])
    w=max(600,self.tabs.width()-60)
    self.sheet_view.setPixmap(pm.scaledToWidth(w,QtCore.Qt.SmoothTransformation))
    self.statusBar().showMessage(f"Sheet {name} - produced by the drawing generator, no AutoCAD involved")

def _export_set_dxf(self,path=None):
    self.open_drawings()
    if self.drawset is None: return
    if not path: path,_=W.QFileDialog.getSaveFileName(self,"Export the drawing set","DETAILED_DRAWINGS.dxf","AutoCAD DXF (*.dxf)")
    if not path: return
    from cbcdraw.export import to_dxf
    to_dxf(self.drawset["rec"],path,image_paths="relative")
    self.statusBar().showMessage(f"DXF written: {path}  (model space + {len(self.drawset['names'])} layouts)")

def _export_set_pdf(self,path=None):
    self.open_drawings()
    if self.drawset is None: return
    if not path: path,_=W.QFileDialog.getSaveFileName(self,"Export the drawing set","DETAILED_DRAWINGS.pdf","PDF (*.pdf)")
    if not path: return
    from cbcdraw import render
    if self.drawset["doc"] is None: self.drawset["doc"]=render.build_doc(self.drawset["rec"])
    self.statusBar().showMessage("Writing PDF…"); pdui()
    render.sheets_pdf(self.drawset["doc"],self.drawset["names"],path)
    self.statusBar().showMessage(f"PDF written: {path}")

Main.open_drawings=_open_drawings; Main.show_sheet=_show_sheet; Main.export_set_dxf=_export_set_dxf; Main.export_set_pdf=_export_set_pdf

def main():
    shot=None; tab=0
    if "--shot" in sys.argv: shot=sys.argv[sys.argv.index("--shot")+1]
    if "--tab" in sys.argv: tab=int(sys.argv[sys.argv.index("--tab")+1])
    export=None; epath=None
    if "--export" in sys.argv: epath=sys.argv[sys.argv.index("--export")+1]; export=section_bb.read_export(epath)
    app=W.QApplication(sys.argv); app.setStyle("Fusion"); win=Main(export,epath)
    if "--sheet" in sys.argv: win.start_sheet=sys.argv[sys.argv.index("--sheet")+1]
    redo=False
    for flag,wdg in (("--toe",win.i_toe),("--skew",win.i_skew),("--water",win.i_water),("--cells",win.i_cells)):
        if flag in sys.argv: wdg.setValue(type(wdg.value())(float(sys.argv[sys.argv.index(flag)+1]))); redo=True
    if "--ground" in sys.argv: win.use_ground.setChecked(True); redo=True
    if redo: win.run()
    win.show(); win.tabs.setCurrentIndex(tab)
    if shot:
        def grab():
            if "--dxf" in sys.argv: win.export_dxf(sys.argv[sys.argv.index("--dxf")+1])
            win.grab().save(shot); app.quit()
        QtCore.QTimer.singleShot(1000, grab)
    sys.exit(app.exec())

if __name__=="__main__":
    main()
