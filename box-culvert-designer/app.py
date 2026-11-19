"""
CBC — Box Culvert Parametric Designer (desktop GUI, PySide6).
Parametric inputs -> plane-frame analysis (BS5400 HB) -> EN 1992-1-1 design.
Tabs: Model & Design | Analysis (BMD) | Detailing | Schedule (BBS) | Report.
"""
import sys, os
if sys.platform.startswith("linux"): os.environ.setdefault("QT_QPA_PLATFORM", "xcb")     # Windows and macOS use their own
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
from detailing import design as ddesign, checks as dchecks, soil as dsoil, skew as dskew, ec2, bars as dbars
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavBar
import ui_shell as ui, time

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
        self.setWindowTitle("CBC Designer — Parametric Box Culvert  [untitled]"); self.project_path=None; self.groups={}
        self.resize(1500, 940); self.setStyleSheet(ui.STYLE)
        self.setDockOptions(W.QMainWindow.AnimatedDocks|W.QMainWindow.AllowTabbedDocks)
        # message window (bottom), as analysis packages keep it
        self.messages=ui.Messages(); dm=W.QDockWidget("Message Window"); dm.setWidget(self.messages); dm.setObjectName("messages")
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,dm); self.dock_msg=dm; self.messages.setMinimumHeight(70)
        # tree menu (left): works tree of the model, and the parameters
        self.tree=W.QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.itemClicked.connect(self._tree_clicked); self.tree_slots={}
        self.left=W.QTabWidget(); self.left.setTabPosition(W.QTabWidget.South)
        self.left.addTab(self._input_panel(),"Parameters"); self.left.addTab(self.tree,"Works")
        dl=W.QDockWidget("Tree Menu"); dl.setWidget(self.left); dl.setObjectName("tree"); dl.setMinimumWidth(330); self.addDockWidget(QtCore.Qt.LeftDockWidgetArea,dl); self.dock_tree=dl
        self.setCentralWidget(self._view_panel())
        self._build_ribbon(); self.resizeDocks([dm],[130],QtCore.Qt.Vertical); self.resizeDocks([dl],[350],QtCore.Qt.Horizontal)
        sb=self.statusBar(); self.lb_xy=W.QLabel("X    -      Z    -   m"); self.lb_xy.setMinimumWidth(210); self.lb_size=W.QLabel(""); lu=W.QLabel("  kN, m  ")
        for wdg in (self.lb_size,self.lb_xy,lu): wdg.setStyleSheet("border-left:1px solid #c3c9d1;padding:0 8px;"); sb.addPermanentWidget(wdg)
        self.msg("CBC Designer started.  F5 = Perform Analysis and Design.","head")
        sb.showMessage("Ready"); self._apply_export(); self.run()
        for k,wdg in vars(self).items():                    # parameters edited after an analysis: results are out of date until F5
            if k.startswith("i_"): (wdg.currentTextChanged if isinstance(wdg,W.QComboBox) else wdg.valueChanged).connect(self._stale)

    def msg(self,text,kind="info",pane="cmd"): self.messages.add(text,kind,pane)

    def _stale(self,*_):
        if getattr(self,"_fresh_results",False):
            self._fresh_results=False; self.banner.setStyleSheet("background:#8a94a0;color:white;padding:0 14px;font-weight:600;")
            self.banner.setText("  Parameters changed — results below belong to the previous model.  Press F5 (Analysis ▸ Perform Analysis) to update.")

    def goto(self,name):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i)==name: self.tabs.setCurrentIndex(i); return

    def show_result(self,display):
        self.goto("Model View"); self.mv.cb_disp.setCurrentIndex(next(i for i,d in enumerate(ui.DISPLAYS) if d.startswith(display)))

    def show_table(self,kind):
        self.goto("Tables"); self.tables.cb.setCurrentText(kind); self.tables.fill()

    def focus_group(self,title,widget=None):
        self.left.setCurrentIndex(0); g=self.groups[title]; self.param_scroll.ensureWidgetVisible(g,0,10)
        if widget is not None: widget.setFocus(); widget.selectAll() if hasattr(widget,"selectAll") else None

    def _tree_clicked(self,item,_col=0):
        f=self.tree_slots.get(id(item))
        if f: f()

    # ---------------- project files ----------------
    def new_project(self):
        ui.restore(self,self._defaults); self.project_path=None; self.setWindowTitle("CBC Designer — Parametric Box Culvert  [untitled]"); self.msg("New project with the default parameters."); self.run()
    def open_project(self,path=None):
        if not path: path,_=W.QFileDialog.getOpenFileName(self,"Open project","","CBC project (*.cbc);;Parameter export (*.txt)")
        if not path: return
        try:
            if path.lower().endswith(".txt"): self.export=section_bb.read_export(path); self.export_path=path; self.drawset=None; self._apply_export()
            else: ui.load_project(self,path); self.project_path=path
        except Exception as ex:
            self.msg(f"Could not open {path}: {ex}","bad"); return
        self.setWindowTitle(f"CBC Designer — Parametric Box Culvert  [{os.path.basename(path)}]"); self.msg(f"Opened {path}"); self.run()
    def save_project(self,path=None):
        path=path or self.project_path
        if not path: path,_=W.QFileDialog.getSaveFileName(self,"Save project","culvert.cbc","CBC project (*.cbc)")
        if not path: return
        ui.save_project(self,path); self.project_path=path; self.setWindowTitle(f"CBC Designer — Parametric Box Culvert  [{os.path.basename(path)}]"); self.msg(f"Project saved: {path}","ok")

    # ---------------- ribbon ----------------
    def _build_ribbon(self):
        G=self.focus_group; R=self.show_result; T=self.show_table
        spec=[
         ("File",[("Project",[("New","new",self.new_project,"New project with default parameters"),("Open","open",lambda: self.open_project(),"Open a project (.cbc) or a parameter export (.txt)"),("Save","save",lambda: self.save_project(),"Save the project (Ctrl+S)")]),
                  ("Export",[("Section\nDXF","dxf",lambda: self.export_dxf(),"Reinforcement section B-B to AutoCAD DXF"),("Drawing set\nDXF","sheets",lambda: self.export_set_dxf(),"All sheets to AutoCAD DXF"),("Drawing set\nPDF","pdf",lambda: self.export_set_pdf(),"All sheets to PDF")]),
                  ("",[("Exit","exit",self.close,"Close the program")])]),
         ("Structure",[("Box culvert wizard",[("Cells and\nopenings","cells",lambda: G("Geometry",self.i_cells),"Number of cells, clear span and height"),("Toe","toe",lambda: G("Site and detailing",self.i_toe),"Base projection beyond the outer walls, shared with the wing walls"),("Skew and\nwing walls","skew",lambda: G("Site and detailing",self.i_skew),"Skew of the culvert axis, flare of the wing walls")]),
                       ("Check structure",[("Nodes","nodes",lambda: T("Nodes"),"Node table"),("Elements","elems",lambda: T("Elements"),"Element table"),("Model\nview","box",lambda: R("Model"),"Analysis model")])]),
         ("Properties",[("Material",[("Concrete and\nsteel","mat",lambda: G("Materials",self.i_fck),"fck, fyk")]),("Section",[("Thickness","sect",lambda: G("Geometry",self.i_ttop),"Slab and wall thicknesses"),("Cover and\nexposure","cover",lambda: G("Site and detailing",self.i_expo),"Exposure class, cover, crack width limit")])]),
         ("Boundary",[("Supports",[("Soil\nsprings","spring",lambda: G("Loading — BS 5400",self.i_ks),"Modulus of subgrade reaction (Winkler)"),("Ground\nprofile","soil",lambda: self.goto("Ground · Plan"),"Soil strata and water table")])]),
         ("Load",[("Static loads",[("Load\ncases","load",lambda: T("Static load cases"),"Static load case table"),("Earth\npressure","earth",lambda: G("Loading — BS 5400",self.i_k0),"Soil weight, K0, surcharge"),("Display\nloads","load",lambda: R("Loads"),"Show the loads of the selected case")]),
                  ("Moving load",[("HB\nvehicle","truck",lambda: G("Loading — BS 5400",self.i_hb),"BS 5400 HB units")]),("Combinations",[("Load\ncombinations","combo",lambda: T("Load combinations"),"EN 1990 combinations generated")])]),
         ("Analysis",[("Perform",[("Perform\nAnalysis","run",self.run,"Analyse and design (F5)")]),("Messages",[("Analysis\nmessages","report",lambda: (self.dock_msg.show(),self.messages.setCurrentIndex(1)),"Analysis message window")])]),
         ("Results",[("Results",[("Reactions","react",lambda: R("Reactions"),"Ground pressure and spring reactions"),("Deformed\nshape","deform",lambda: R("Deformed shape"),"Displacements"),("Moment\nMy","moment",lambda: R("Bending moment"),"Bending moment diagram"),("Shear\nFz","shear",lambda: R("Shear force"),"Shear force diagram"),("Axial\nFx","axial",lambda: R("Axial force"),"Axial force diagram")]),
                     ("Tables",[("Displace-\nments","table",lambda: T("Displacements"),"Displacement table"),("Reactions","table",lambda: T("Reactions"),"Reaction table"),("Beam\nforces","table",lambda: T("Beam forces"),"Beam force table")])]),
         ("Design",[("RC design — EN 1992-1-1",[("Member\ndesign","design",lambda: self.goto("Design"),"Flexure, cracking, shear of every member"),("Code\nchecks","check",lambda: self.goto("Code checks"),"Clause-by-clause checks"),("Report","report",lambda: self.goto("Report"),"Calculation report")])]),
         ("Detailing",[("Reinforcement",[("Section\nB-B","rebar",lambda: self.goto("Detailing"),"Reinforcement arrangement"),("Bar\nschedule","bbs",lambda: self.goto("Schedule (BBS)"),"Bar bending schedule, BS 8666"),("Ground\nand plan","plan",lambda: self.goto("Ground · Plan"),"Strata, skewed plan, wing walls")])]),
         ("Drawings",[("Drawing set",[("Generate\nsheets","sheets",lambda: self.goto("Drawings"),"Produce all sheets"),("To AutoCAD\nDXF","dxf",lambda: self.export_set_dxf(),"All sheets to DXF"),("To PDF","pdf",lambda: self.export_set_pdf(),"All sheets to PDF")])]),
         ("View",[("Windows",[("Tree\nMenu","table",lambda: self.dock_tree.setVisible(not self.dock_tree.isVisible()),"Show / hide the tree menu"),("Message\nWindow","report",lambda: self.dock_msg.setVisible(not self.dock_msg.isVisible()),"Show / hide the message window")]),
                  ("Display",[("Node\nnumbers","nodes",lambda: self.mv.t_nodes.toggle(),"Node numbers in the model view"),("Element\nnumbers","elems",lambda: self.mv.t_elems.toggle(),"Element numbers in the model view"),("Zoom\nfit","fit",lambda: self.mv.draw(),"Fit the model in the view")])]),
        ]
        self.ribbon=ui.Ribbon(spec); tb=W.QToolBar("Ribbon"); tb.setMovable(False); tb.setObjectName("ribbon"); tb.addWidget(self.ribbon); tb.setStyleSheet("QToolBar{border:none;padding:0;}")
        self.addToolBar(QtCore.Qt.TopToolBarArea,tb); self.ribbon.setCurrentIndex(5)
        for key,slot in (("F5",self.run),("Ctrl+S",lambda: self.save_project()),("Ctrl+O",lambda: self.open_project()),("Ctrl+N",self.new_project)):
            QtGui.QShortcut(QtGui.QKeySequence(key),self,slot)

    def _card(self,title):
        box=W.QGroupBox(title); self.groups[title]=box
        return box

    # ---------------- input panel ----------------
    def _input_panel(self):
        panel=W.QWidget(); v=W.QVBoxLayout(panel); v.setContentsMargins(6,4,6,6); v.setSpacing(6)
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
        self.i_pivot=W.QComboBox(); self.i_pivot.addItems(["centre","inlet","outlet"]); self.i_pivot.setFixedHeight(26)
        for lab,wdg in [("Toe, walls + wing walls (mm)",self.i_toe),("Skew of axis to road (°)",self.i_skew),("Skew pivot",self.i_pivot),("Wing wall flare (°)",self.i_flare),
            ("Barrel length (m)",self.i_barrel),("Apron length (m)",self.i_apron),("Max joint spacing (m)",self.i_joint),
            ("Exposure class",self.i_expo),("Crack width limit (mm)",self.i_wk)]:
            sl.addRow(lab,wdg)
        v.addWidget(st); v.addStretch(1)
        sc=W.QScrollArea(); sc.setWidget(panel); sc.setWidgetResizable(True); sc.setFrameShape(W.QFrame.NoFrame); self.param_scroll=sc
        return sc

    # ---------------- view panel (tabs) ----------------
    def _view_panel(self):
        panel=W.QWidget(); v=W.QVBoxLayout(panel); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        self.banner=W.QLabel("—"); self.banner.setFixedHeight(30); self.banner.setAlignment(QtCore.Qt.AlignVCenter); v.addWidget(self.banner)
        self.tabs=W.QTabWidget(); self.tabs.setTabPosition(W.QTabWidget.South); self.tabs.setDocumentMode(True)
        self.mv=ui.ModelView(self); self.tabs.addTab(self.mv,"Model View")
        # Tab 1 — Model & Design
        t1=W.QWidget(); l1=W.QVBoxLayout(t1)
        self.fig1=Figure(figsize=(8,3.5),facecolor="white"); self.cv1=Canvas(self.fig1); l1.addWidget(self.cv1,3)
        self.table=W.QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["Check","Location","Action","Required","Provided","Util.","Status"])
        self.table.horizontalHeader().setStretchLastSection(True); self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers); l1.addWidget(self.table,2)
        self.tabs.addTab(t1,"Design")
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
        self.bbs.setEditTriggers(W.QAbstractItemView.NoEditTriggers); l4.addWidget(self.bbs)
        self.tabs.addTab(t4,"Schedule (BBS)")
        # Tab 5 — Report
        t5=W.QWidget(); l5=W.QVBoxLayout(t5); self.report=W.QTextEdit(); self.report.setReadOnly(True)
        self.report.setStyleSheet(f"QTextEdit{{background:{CARD};border:none;font:13px 'DejaVu Sans';}}"); l5.addWidget(self.report)
        self.tabs.addTab(t5,"Report")
        # Code checks: every clause that governs the design and detailing
        tc=W.QWidget(); lc=W.QVBoxLayout(tc); self.lb_chk=W.QLabel(""); self.lb_chk.setStyleSheet(f"font:600 13px;color:{BLUE};padding:4px;"); lc.addWidget(self.lb_chk)
        self.chk=W.QTableWidget(0,7); self.chk.setHorizontalHeaderLabels(["Group","Clause","Item","Value","Limit","Status","Basis / note"])
        self.chk.horizontalHeader().setStretchLastSection(True); self.chk.verticalHeader().setVisible(False)
        self.chk.setEditTriggers(W.QAbstractItemView.NoEditTriggers); lc.addWidget(self.chk)
        self.tabs.addTab(tc,"Code checks")
        # Ground and plan: soil strata, water, skewed plan with the wing walls
        tg=W.QWidget(); lg=W.QHBoxLayout(tg); lft=W.QVBoxLayout()
        self.use_ground=W.QCheckBox("Use the layered ground below (earth pressure, water, subgrade stiffness, bearing)"); self.use_ground.setChecked(False)
        lft.addWidget(self.use_ground)
        self.soil=W.QTableWidget(4,8); self.soil.setHorizontalHeaderLabels(["Layer","Thickness m","γ kN/m³","γsat kN/m³","φ′ °","c′ kPa","cu kPa","E′ MPa"])
        for r,rowv in enumerate([("Fill / embankment",1.5,19,20,30,0,"",20),("Firm to stiff clay",3.0,19,20,26,5,90,25),("Dense sand",10.0,20,21,36,0,"",60),("",0,"","","","","","")]):
            for c,val in enumerate(rowv): self.soil.setItem(r,c,W.QTableWidgetItem(str(val)))
        self.soil.resizeColumnsToContents(); self.soil.setMaximumHeight(170); lft.addWidget(self.soil)
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
        self.tables=ui.Tables(self); self.tabs.addTab(self.tables,"Tables")
        self.mv.cb_lc.currentIndexChanged.connect(lambda _: self.tables.fill() if self.tabs.tabText(self.tabs.currentIndex())=="Tables" else None)
        self.tabs.currentChanged.connect(lambda i: self.open_drawings() if self.tabs.tabText(i)=="Drawings" else (self.tables.fill() if self.tabs.tabText(i)=="Tables" else None))
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
                    joint_spacing=self.i_joint.value()*1000.0,stock=12000.0,anch_mult=self.anch_mult,lap_mult=self.lap_mult,pivot=self.i_pivot.currentText(),
                    outer_width=p.W_ext*1000.0,wall_t=p.t_wall*1000.0,schedule=getattr(self,'sched',None),wall_lap=getattr(self,'wlap',None))

    # ---------------- run ----------------
    def run(self):
        self.statusBar().showMessage("Analysing…"); pdui(); t0=time.time()
        if not hasattr(self,"_defaults"): self._defaults=ui.collect(self)
        A=lambda t,k="info": self.msg(t,k,"ana")
        p=self.params(); A("─"*74); A("PERFORM ANALYSIS  —  plane frame on elastic foundation, 1 m strip","head")
        self.box=Box(p); nn=len(self.box.fr.nodes); ne=len(self.box.fr.elements)
        A(f"model      : {nn} nodes, {ne} beam elements, {len(self.box.base_nodes)} soil springs (ks = {self.box.ks:,.0f} kN/m³), {3*nn} degrees of freedom"); pdui()
        self.box.analyse(); self.p=p
        A(f"load cases : 5 static (SW, EV, EH, LS, LS1) + {len(self.box.hb_keys)} positions of the HB vehicle  —  solved in {time.time()-t0:.2f} s")
        self.uls=self.box.uls_combos(); self.sls=self.box.sls_combos()
        A(f"combinations: {len(self.uls)} ULS + {len(self.sls)} SLS (EN 1990, min / max earth pressure, surcharge on both sides or one)")
        self.bearing_sls=max(self.box.bearing(c)[0] for c in self.sls)
        self.bearing_uls=max(self.box.bearing(c)[0] for c in self.uls)
        # member design to EN 1992-1-1: flexure, minimum steel, spacing, crack width, shear at d (links when needed)
        R=self.R=ddesign.design(self.box,fck=p.fck,fyk=p.fyk,exposure=self.i_expo.currentText(),wk_lim=self.i_wk.value(),cover=p.cover)
        mu=dbars.multiples(R,(p.height+p.t_top+p.t_base)*1000.0); self.anch_mult=mu["anch_mult"]; self.lap_mult=mu["lap_mult"]; self.wlap=mu["wall"]
        # reinforcement section and bar schedule: no piece longer than the stock length, long runs lapped in two staggered families
        self.bb=section_bb.build(self.detail_params(p))
        self.sched=dbars.schedule(self.bb,section_bb.complete(self.detail_params(p)),self.i_barrel.value()*1000.0,self.i_skew.value())
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
        self.banner.setStyleSheet(f"background:{col};color:white;padding:0 14px;font-weight:600;")
        self.banner.setText(f"  DESIGN {status}     ·     Max utilisation {self.maxutil:.2f}     ·     Governing: {self.govern}     ·     Bearing SLS {self.bearing_sls:.0f} / ULS {self.bearing_uls:.0f} kPa     ·     {len(self.checks)-nbad}/{len(self.checks)} code checks")
        self.mv.set_box(self.box,self.uls,self.sls)
        self._draw_bb(self.fig1,p,False); self._draw_bb(self.fig3,p,True); self._fill_bbs(p); self._fill_report(p); self._fill_ground(p); self._fill_tree(p)
        if self.tabs.tabText(self.tabs.currentIndex())=="Tables": self.tables.fill()
        A(f"design     : EN 1992-1-1 member design, max utilisation {self.maxutil:.2f} ({self.govern})")
        for r in rows:
            if not r[6]: A(f"NOT SATISFIED  {r[0]} — {r[1]}: {r[2]} against {r[3]}","bad")
        for ck in self.checks:
            if not ck["ok"]: A(f"NOT SATISFIED  {ck['group']} {ck['clause']} — {ck['item']}: {ck['value']} (limit {ck['limit']})","bad")
        A(f"SOLUTION TERMINATED  —  total time {time.time()-t0:.2f} s","ok" if ok else "warn")
        self.msg(f"Analysis and design completed: DESIGN {status}, max utilisation {self.maxutil:.2f}, {len(self.checks)-nbad}/{len(self.checks)} code checks.","ok" if ok else "warn")
        self._fresh_results=True; self.lb_size.setText(f"{nn} nodes · {ne} elements · {len(self.box.u)} load cases")
        self.statusBar().showMessage(f"{p.n_cells}-cell {p.span:.2f}×{p.height:.2f} m · governing {self.govern}")

    def _fill_tree(self,p):
        """Works tree: what the model holds, each entry opening its table, view or parameter."""
        t=self.tree; t.clear(); self.tree_slots={}; b=self.box; G=self.focus_group; R=self.show_result; T=self.show_table
        def node(parent,text,slot=None,bold=False):
            it=W.QTreeWidgetItem(parent,[text])
            if bold: f=it.font(0); f.setBold(True); it.setFont(0,f)
            if slot: self.tree_slots[id(it)]=slot
            return it
        w=node(t,"Works",bold=True)
        s_=node(w,"Structure",bold=True)
        node(s_,f"Box culvert : {p.n_cells} cell(s) {p.span*1000:.0f} × {p.height*1000:.0f}",lambda: G("Geometry",self.i_cells))
        node(s_,f"Nodes : {len(b.fr.nodes)}",lambda: T("Nodes")); node(s_,f"Elements : {len(b.fr.elements)}",lambda: T("Elements"))
        if p.toe>0: node(s_,f"Toe : {p.toe*1000:.0f} mm each side",lambda: G("Site and detailing",self.i_toe))
        node(s_,f"Skew {self.i_skew.value():.0f}°, wing wall flare {self.i_flare.value():.0f}°",lambda: G("Site and detailing",self.i_skew))
        pr=node(w,"Properties",bold=True)
        m=node(pr,"Material : 1"); node(m,f"1 : C{p.fck:.0f}  (Ecm {p.Ecm:,.0f} MPa), steel fyk {p.fyk:.0f}",lambda: G("Materials",self.i_fck))
        sec=node(pr,"Section : "+("4" if p.n_cells>1 else "3"))
        for i,(nm,th) in enumerate([("Top slab",p.t_top),("Base slab",p.t_base),("Outer walls",p.t_wall)]+([("Piers",p.t_pier)] if p.n_cells>1 else [])):
            node(sec,f"{i+1} : {nm}  1000 × {th*1000:.0f}",lambda: G("Geometry",self.i_ttop))
        bd=node(w,"Boundaries",bold=True)
        node(bd,f"Point spring supports : {len(b.base_nodes)}  (ks {b.ks:,.0f} kN/m³)",lambda: G("Loading — BS 5400",self.i_ks))
        node(bd,"Ground profile : "+("layered" if p.profile is not None else "uniform"),lambda: self.goto("Ground · Plan"))
        lc=node(w,f"Static Load Cases : {len(b.u)}",bold=True)
        def pick(key): return lambda: (self.mv.cb_lc.setCurrentText(ui.case_title(key)),R("Loads"))
        for i,k in enumerate(ui.STATIC): node(lc,f"{i+1} : {ui.case_title(k)}",pick(k))
        hb=node(lc,f"Moving load, HB {p.hb_units:g} units : {len(b.hb_keys)} positions",lambda: G("Loading — BS 5400",self.i_hb))
        for k in b.hb_keys: node(hb,ui.case_title(k),pick(k))
        cb=node(w,f"Load Combinations : {len(self.uls)+len(self.sls)}",lambda: T("Load combinations"),bold=True)
        node(cb,f"ULS : {len(self.uls)}",lambda: T("Load combinations")); node(cb,f"SLS : {len(self.sls)}",lambda: T("Load combinations"))
        rs=node(w,"Results",bold=True)
        for nm,d in (("Reactions","Reactions"),("Deformed shape","Deformed shape"),("Bending moment diagram","Bending moment"),("Shear force diagram","Shear force"),("Axial force diagram","Axial force")): node(rs,nm,(lambda d=d: R(d)))
        tb=node(rs,"Result tables")
        for k in ("Displacements","Reactions","Beam forces"): node(tb,k,(lambda k=k: T(k)))
        ds=node(w,"Design",bold=True)
        node(ds,f"Member design : utilisation {self.maxutil:.2f}",lambda: self.goto("Design")); nb=sum(1 for c in self.checks if not c["ok"])
        node(ds,f"Code checks : {len(self.checks)-nb} / {len(self.checks)}",lambda: self.goto("Code checks")); node(ds,"Report",lambda: self.goto("Report"))
        dt=node(w,"Detailing and drawings",bold=True)
        for nm in ("Detailing","Schedule (BBS)","Ground · Plan","Drawings"): node(dt,nm,(lambda nm=nm: self.goto(nm)))
        t.expandToDepth(1); hb.setExpanded(False)

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
        se2=dskew.slab_effects(p.span*1000,st["skew"]); Wo=p.W_ext*1000; Lb=st["barrel_length"]
        piers=[(-Wo/2+p.t_wall*1000+j*p.span*1000+(j-0.5)*p.t_pier*1000,p.t_pier*1000) for j in range(1,p.n_cells)]
        g=self.plan=dskew.layout(Wo,Lb,st["apron"],st["flare"],st["skew"],st["pivot"],p.t_wall*1000,piers)
        H.append(f"<h3 style='color:{BLUE};margin:8px 0 2px;'>Plan — skew {st['skew']:g}°, pivot at the {st['pivot']}</h3>")
        H.append(f"<p>Road horizontal; barrel ends stay parallel to the road and the wing wall ends stay on the apron edges.<br>"
                 f"Barrel walls <b>{g['wall_length']:,.0f} mm</b> (square {Lb:,.0f}), end faces {g['end_face_length']:,.0f} mm (square {Wo:,.0f}).</p>")
        H.append("<table cellpadding='2' style='font-size:12px;'><tr><td><b>Wing wall</b></td><td><b>length mm</b></td><td><b>change</b></td><td><b>flare °</b></td><td><b>to barrel wall °</b></td></tr>")
        for en in ("inlet","outlet"):
            for sd in ("left","right"):
                w=g["ends"][en]["walls"][sd]; col="" if w["ok"] else f" style='color:{BAD};'"
                H.append(f"<tr{col}><td>{en} {sd}</td><td>{w['length']:,.0f}</td><td>{w['change']:+,.0f}</td><td>{w['flare']:.1f}</td><td>{180-w['angle_to_barrel_wall']:.1f}</td></tr>")
        H.append("</table>")
        if not g["ok"]: H.append(f"<p style='color:{BAD};'>A barrel corner has slid past a wing wall end: reduce the skew, lengthen the apron, widen the flare or move the pivot.</p>")
        H.append(f"<p>Slab end zones: skew span {se2['skew_span']:,.0f} mm, transverse steel × {se2['As_factor_end_zone']:.2f} — {se2['treatment']}.</p>")
        H.append("<table cellpadding='2' style='font-size:11px;'><tr><td><b>skew °</b></td><td><b>barrel wall</b></td><td><b>inlet L / R</b></td><td><b>outlet L / R</b></td></tr>")
        for r in dskew.simulate(Wo,Lb,st["apron"],st["flare"],pivot=st["pivot"]):
            col="" if r["ok"] else f" style='color:{BAD};'"
            H.append(f"<tr{col}><td>{r['skew']}</td><td>{r['wall_length']:,.0f}</td><td>{r['inlet_left']:,.0f} / {r['inlet_right']:,.0f}</td><td>{r['outlet_left']:,.0f} / {r['outlet_right']:,.0f}</td></tr>")
        H.append("</table>")
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
        ax2=self.figg.add_axes([0.44,0.04,0.54,0.92]); self.draw_plan(ax2,g,dskew.layout(Wo,Lb,st["apron"],st["flare"],90.0,st["pivot"],p.t_wall*1000,piers),px)
        self.cvg.draw_idle()

    def draw_plan(self,ax,g,sq,px,title=True):
        """Plan with the road horizontal: skewed layout solid, the square crossing it was turned from dashed."""
        ax.set_aspect("equal"); ax.axis("off"); L=abs(g["ends"]["outlet"]["y"])*2; xs=[q[0] for e in g["ends"].values() for q in e["apron_poly"]]+[q[0] for q in g["outline"]]
        x0,x1=min(xs),max(xs); r=max(x1-x0,L)*0.12
        ax.fill([x0-r,x1+r,x1+r,x0-r],[-L*0.36,-L*0.36,L*0.36,L*0.36],color="#b8c0c9",alpha=0.45,lw=0,zorder=0)
        ax.plot([x0-r,x1+r],[0,0],color="#ffffff",lw=1.2,ls=(0,(8,6)),zorder=1); ax.text(x1+r,0,"  ROAD",fontsize=px(10),color="#4a627a",va="center")
        ax.fill(*zip(*sq["outline"]),fill=False,ec="#8a94a0",lw=0.8,ls="--",zorder=2)
        for en in ("inlet","outlet"):
            e=g["ends"][en]; ax.fill(*zip(*e["apron_poly"]),color="#e9eef3",ec="#8a94a0",lw=0.7,zorder=2)
            for sd in ("left","right"):
                w0=sq["ends"][en]["walls"][sd]; ax.plot(*zip(w0["start"],w0["end"]),color="#8a94a0",lw=0.8,ls="--",zorder=3)
                w=e["walls"][sd]; (ax_,ay),(bx_,by)=w["start"],w["end"]
                ax.plot([ax_,bx_],[ay,by],color=BAD if w["ok"] else "#7d3c98",lw=3.2,solid_capstyle="butt",zorder=5)
                ax.text((ax_+bx_)/2,(ay+by)/2,f" {w['length']:,.0f}\n ({w['change']:+,.0f})",fontsize=px(9.5),color=BAD,va="center",ha="left" if sd=="right" else "right",zorder=6)
        ax.fill(*zip(*g["outline"]),color="#f4f6f9",ec=BLUE,lw=1.0,zorder=3)
        for poly in g["walls"]: ax.fill(*zip(*poly),color=BLUE,lw=0,zorder=4)
        ax.plot(*zip(*g["axis"]),color=ACC,lw=0.8,ls="-.",zorder=5); ax.plot(*g["pivot_point"],"o",ms=px(6),color=ACC,zorder=7)
        ax.text(g["pivot_point"][0],g["pivot_point"][1],"  pivot",fontsize=px(9),color=ACC,va="bottom",zorder=7)
        ax.text(g["ends"]["inlet"]["axis_x"],-L/2-abs(g["ends"]["inlet"]["apron_edge"][0][1]+L/2)*1.12,"INLET",fontsize=px(9.5),color="#4a627a",ha="center",va="top")
        ax.text(g["ends"]["outlet"]["axis_x"],L/2+abs(g["ends"]["outlet"]["apron_edge"][0][1]-L/2)*1.12,"OUTLET",fontsize=px(9.5),color="#4a627a",ha="center",va="bottom")
        if title: ax.set_title(f"Skew {g['skew']:g}° (dashed: square crossing)",fontsize=px(12),color=BLUE)

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
        """Bar schedule built from the reinforcement section: every piece within the stock length, laps staggered."""
        rows=self.sched; self.bbs.setColumnCount(9); self.bbs.setHorizontalHeaderLabels(["Mark","Member","Bar","Spacing","No.","Shape (BS 8666)","Legs A / B / C … (mm)","Length (mm)","Mass (kg)"])
        self.bbs.setRowCount(len(rows)+1); tot=0.0
        for r,b in enumerate(rows):
            tot+=b["mass"]
            vals=[b["mark"],b["member"]+(f" — lap {b['lap']['l0']:.0f}" if b.get("lap") else ""),f"T{b['dia']:.0f}",f"{b['spacing']:.0f}",f"{b['no']:,}",b["shape"]," / ".join(f"{x:,.0f}" for x in b["legs"]),f"{b['length']:,.0f}",f"{b['mass']:,.1f}"]
            for c,val in enumerate(vals):
                it=W.QTableWidgetItem(val)
                if c>=2: it.setTextAlignment(QtCore.Qt.AlignCenter)
                if c==7 and b["length"]>12000: it.setForeground(QtGui.QBrush(QtGui.QColor(BAD)))
                self.bbs.setItem(r,c,it)
        for c,val in ((1,f"Total — barrel {self.i_barrel.value():.2f} m at skew {self.i_skew.value():g}°, longest bar {max(b['length'] for b in rows):,.0f} mm"),(8,f"{tot:,.0f}")):
            it=W.QTableWidgetItem(val); f=it.font(); f.setBold(True); it.setFont(f); self.bbs.setItem(len(rows),c,it)
        self.bbs.resizeColumnsToContents(); self.bbs_total=tot

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
        <tr><td><b>Steel, barrel</b></td><td>{getattr(self,'bbs_total',0):,.0f} kg in the barrel (bar schedule)</td></tr>
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
    win.show()
    if "--view" in sys.argv: win.show_result(sys.argv[sys.argv.index("--view")+1])
    elif "--table" in sys.argv: win.show_table(sys.argv[sys.argv.index("--table")+1])
    elif "--page" in sys.argv: win.goto(sys.argv[sys.argv.index("--page")+1])
    else: win.tabs.setCurrentIndex(tab)
    if "--lc" in sys.argv: win.mv.cb_lc.setCurrentIndex(int(sys.argv[sys.argv.index("--lc")+1]))
    if "--ribbon" in sys.argv: win.ribbon.setCurrentIndex(int(sys.argv[sys.argv.index("--ribbon")+1]))
    if "--works" in sys.argv: win.left.setCurrentIndex(1)
    if shot:
        def grab():
            if "--dxf" in sys.argv: win.export_dxf(sys.argv[sys.argv.index("--dxf")+1])
            win.grab().save(shot); app.quit()
        QtCore.QTimer.singleShot(1000, grab)
    sys.exit(app.exec())

if __name__=="__main__":
    main()
