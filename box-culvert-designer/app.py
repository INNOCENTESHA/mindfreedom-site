"""
CBC — Box Culvert Parametric Designer (desktop GUI, PySide6).
Parametric inputs -> plane-frame analysis (BS5400 HB) -> EC2 design ->
live cross-section with reinforcement + design-check table + DXF export.
"""
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.patches
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas
from PySide6 import QtCore, QtGui, QtWidgets as W

from engine import Box, P
from design import design_flexure, check_shear

BLUE="#1b3a5c"; ACC="#2d7dd2"; OK="#1e8449"; BAD="#c0392b"; LIGHT="#f4f6f9"; CARD="#ffffff"

def spin(val, lo, hi, step, dec=0):
    s=W.QDoubleSpinBox() if dec else W.QSpinBox()
    s.setRange(lo,hi); s.setValue(val)
    if dec: s.setDecimals(dec); s.setSingleStep(step)
    else: s.setSingleStep(int(step))
    s.setFixedHeight(26)
    return s

class Main(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CBC — Box Culvert Parametric Designer  v0.1")
        self.resize(1360, 860)
        self.setStyleSheet(f"QMainWindow{{background:{LIGHT};}}")
        self._build_header()
        central=W.QWidget(); self.setCentralWidget(central)
        root=W.QHBoxLayout(central); root.setContentsMargins(10,8,10,10); root.setSpacing(10)
        root.addWidget(self._input_panel(), 0)
        root.addWidget(self._view_panel(), 1)
        self.statusBar().showMessage("Ready")
        self.run()

    def _build_header(self):
        bar=W.QWidget(); bar.setFixedHeight(58); bar.setStyleSheet(f"background:{BLUE};")
        h=W.QHBoxLayout(bar); h.setContentsMargins(16,0,16,0)
        t=W.QLabel("CBC   ·   Parametric Box Culvert Designer")
        t.setStyleSheet("color:white;font:600 18px 'DejaVu Sans';")
        sub=W.QLabel("BS 5400 HB · EN 1992-1-1 · 2D frame on elastic foundation")
        sub.setStyleSheet("color:#aecbed;font:12px 'DejaVu Sans';")
        col=W.QVBoxLayout(); col.setSpacing(0); col.addWidget(t); col.addWidget(sub)
        h.addLayout(col); h.addStretch(1)
        for name,slot in [("Analyse && Design",self.run),("Export DXF",self.export_dxf)]:
            b=W.QPushButton(name); b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{ACC};color:white;border:none;"
                            f"padding:8px 16px;border-radius:5px;font:600 13px;}}"
                            f"QPushButton:hover{{background:#3b8ee0;}}")
            b.clicked.connect(slot); h.addWidget(b)
        tb=W.QToolBar(); tb.setMovable(False); tb.addWidget(bar)
        tb.setStyleSheet("QToolBar{border:none;padding:0;}")
        self.addToolBar(QtCore.Qt.TopToolBarArea, tb)
        bar.setFixedWidth(1360)

    def _card(self, title):
        box=W.QGroupBox(title)
        box.setStyleSheet(f"QGroupBox{{background:{CARD};border:1px solid #dde3ea;"
            f"border-radius:7px;margin-top:10px;font:600 12px;color:{BLUE};}}"
            f"QGroupBox::title{{subcontrol-origin:margin;left:12px;padding:0 5px;}}")
        return box

    def _input_panel(self):
        panel=W.QWidget(); panel.setFixedWidth(330)
        v=W.QVBoxLayout(panel); v.setContentsMargins(0,0,0,0); v.setSpacing(8)
        # geometry
        g=self._card("Geometry"); gl=W.QFormLayout(g); gl.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_cells=spin(4,1,8,1); self.i_span=spin(1.5,0.5,6,0.1,2); self.i_height=spin(1.5,0.5,6,0.1,2)
        self.i_ttop=spin(0.25,0.15,0.6,0.025,3); self.i_tbase=spin(0.25,0.15,0.6,0.025,3)
        self.i_twall=spin(0.25,0.15,0.6,0.025,3); self.i_fill=spin(1.0,0.0,8,0.1,2)
        for lab,wdg in [("No. of cells",self.i_cells),("Clear span (m)",self.i_span),
            ("Clear height (m)",self.i_height),("Top slab t (m)",self.i_ttop),
            ("Base slab t (m)",self.i_tbase),("Wall t (m)",self.i_twall),("Fill depth (m)",self.i_fill)]:
            gl.addRow(lab,wdg)
        v.addWidget(g)
        # materials
        m=self._card("Materials"); ml=W.QFormLayout(m); ml.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_fck=spin(25,20,60,5); self.i_fyk=spin(460,250,600,10); self.i_cover=spin(0.05,0.03,0.09,0.005,3)
        for lab,wdg in [("fck (MPa)",self.i_fck),("fyk (MPa)",self.i_fyk),("Cover (m)",self.i_cover)]:
            ml.addRow(lab,wdg)
        v.addWidget(m)
        # loading
        l=self._card("Loading — BS 5400"); ll=W.QFormLayout(l); ll.setLabelAlignment(QtCore.Qt.AlignRight)
        self.i_hb=spin(37.5,0,45,2.5,1); self.i_soil=spin(20,14,24,1); self.i_k0=spin(0.5,0.3,1.0,0.05,2)
        self.i_sur=spin(16.67,0,40,1,2); self.i_ks=spin(30000,5000,120000,5000)
        for lab,wdg in [("HB units",self.i_hb),("γ soil (kN/m³)",self.i_soil),("K₀ at-rest",self.i_k0),
            ("Surcharge (kPa)",self.i_sur),("Subgrade kₛ (kN/m³)",self.i_ks)]:
            ll.addRow(lab,wdg)
        v.addWidget(l); v.addStretch(1)
        return panel

    def _view_panel(self):
        panel=W.QWidget(); v=W.QVBoxLayout(panel); v.setContentsMargins(0,0,0,0); v.setSpacing(8)
        # status banner
        self.banner=W.QLabel("—"); self.banner.setFixedHeight(54)
        self.banner.setAlignment(QtCore.Qt.AlignVCenter)
        v.addWidget(self.banner)
        # section canvas
        card=self._card("Cross-section and reinforcement"); cl=W.QVBoxLayout(card)
        self.fig=Figure(figsize=(8,4.2),facecolor="white"); self.canvas=Canvas(self.fig)
        cl.addWidget(self.canvas); v.addWidget(card,3)
        # results table
        rc=self._card("Design checks — EN 1992-1-1"); rl=W.QVBoxLayout(rc)
        self.table=W.QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(["Check","Location","Action","Required","Provided","Util.","Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("QTableWidget{font:12px 'DejaVu Sans';gridline-color:#e3e8ee;}"
            "QHeaderView::section{background:#eef2f7;padding:5px;border:none;font:600 12px;color:#30506f;}")
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        rl.addWidget(self.table); v.addWidget(rc,2)
        return panel

    def params(self):
        p=P(); p.n_cells=self.i_cells.value(); p.span=self.i_span.value(); p.height=self.i_height.value()
        p.t_top=self.i_ttop.value(); p.t_base=self.i_tbase.value(); p.t_wall=self.i_twall.value(); p.t_pier=self.i_twall.value()
        p.fill=self.i_fill.value(); p.fck=self.i_fck.value(); p.fyk=self.i_fyk.value(); p.cover=self.i_cover.value()
        p.hb_units=self.i_hb.value(); p.hb_wheel=self.i_hb.value()*10/4
        p.gamma_soil=self.i_soil.value(); p.K0=self.i_k0.value(); p.surcharge=self.i_sur.value(); p.ks=self.i_ks.value()
        return p

    def run(self):
        self.statusBar().showMessage("Analysing…"); QtWidgets_process()
        p=self.params(); self.box=Box(p).analyse(); self.p=p
        uls=self.box.uls_combos(); sls=self.box.sls_combos()
        self.bearing_sls=max(self.box.bearing(c)[0] for c in sls)
        self.bearing_uls=max(self.box.bearing(c)[0] for c in uls)
        tmap={'top':p.t_top,'base':p.t_base,'walls':p.t_wall,'piers':p.t_pier}
        names={'top':'Top slab','base':'Base slab','walls':'Outer walls','piers':'Inner (pier) walls'}
        rows=[]; maxutil=0; govern="-"; self.faces={}
        for m in ['top','base','walls','piers']:
            if m=='piers' and p.n_cells<2: continue
            e=self.box.envelope(m,uls); t=tmap[m]
            Mcrit=e['Mmin'] if abs(e['Mmin'])>abs(e['Mmax']) else e['Mmax']
            fd,_=design_flexure(names[m],Mcrit,t,p.fck,p.fyk,p.cover)
            sh=check_shear(names[m],e['Vmax'],t,p.fck,p.cover,fd.As_prov)
            self.faces[m]=[(fd.dia,fd.spacing),(fd.dia,fd.spacing)]
            rows.append(("Flexure",names[m],f"{Mcrit:,.1f} kNm/m",f"As {fd.As_req:,.0f} mm²/m",
                         f"T{fd.dia}@{fd.spacing} ({fd.As_prov:,.0f})",fd.util,fd.util<=1))
            rows.append(("Shear",names[m]+" at d",f"{sh.V:,.1f} kN/m","VRd,c "+f"{sh.VRdc:,.1f}",
                         f"ρ-based",sh.util,sh.ok))
            for u in (fd.util,sh.util):
                if u>maxutil: maxutil=u; govern=("Shear - "+names[m]) if u==sh.util else ("Flexure - "+names[m])
        rows.append(("Bearing","Founding, SLS",f"{self.bearing_sls:,.1f} kPa","≤ 210 kPa","site SI",
                     self.bearing_sls/210,self.bearing_sls<=210))
        self._fill_table(rows)
        status = "PASS" if maxutil<=1 and self.bearing_sls<=210 else "REVIEW"
        col = OK if status=="PASS" else BAD
        self.banner.setStyleSheet(f"background:{col};color:white;border-radius:7px;padding:0 18px;"
                                  f"font:600 15px 'DejaVu Sans';")
        self.banner.setText(f"  DESIGN {status}     ·     Max utilisation {maxutil:.2f}     ·     "
            f"Governing: {govern}     ·     Bearing SLS {self.bearing_sls:.0f} / ULS {self.bearing_uls:.0f} kPa")
        self._draw_section(p)
        self.statusBar().showMessage(f"{p.n_cells}-cell {p.span:.2f}×{p.height:.2f} m  ·  "
            f"{len(self.box.u)} load cases  ·  governing {govern}")

    def _fill_table(self, rows):
        self.table.setRowCount(len(rows))
        for r,(chk,loc,act,req,prov,util,ok) in enumerate(rows):
            vals=[chk,loc,act,req,prov,f"{util:.2f}","OK" if ok else "FAIL"]
            for c,val in enumerate(vals):
                it=W.QTableWidgetItem(val)
                if c==5: it.setTextAlignment(QtCore.Qt.AlignCenter)
                if c==6:
                    it.setForeground(QtGui.QBrush(QtGui.QColor(OK if ok else BAD)))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    f=it.font(); f.setBold(True); it.setFont(f)
                self.table.setItem(r,c,it)
        self.table.resizeColumnsToContents()

    def _draw_section(self, p):
        self.fig.clear(); ax=self.fig.add_subplot(111); ax.set_aspect("equal"); ax.axis("off")
        tw=p.t_wall; tp=p.t_pier; tt=p.t_top; tb=p.t_base; S=p.span; H=p.height
        xs=[0.0]; xs.append(S+tw/2+tp/2)
        for _ in range(p.n_cells-2): xs.append(xs[-1]+S+tp)
        if p.n_cells>=2: xs.append(xs[-1]+S+tp/2+tw/2)
        W_ext=xs[-1]+tw/2; OH=H+tt+tb
        # concrete fill
        ax.add_patch(matplotlib.patches.Rectangle((-tw/2,0),W_ext, OH, facecolor="#d9e2ec",edgecolor=BLUE,lw=1.6,zorder=1))
        # openings
        left=-tw/2
        cx=left+tw
        for i in range(p.n_cells):
            ax.add_patch(matplotlib.patches.Rectangle((cx,tb),S,H,facecolor="white",edgecolor=BLUE,lw=1.2,zorder=2))
            cx+=S+ (tp if i<p.n_cells-1 else 0)
        # reinforcement (schematic red)
        c=p.cover
        ax.plot([left+c,left+tw+ (p.n_cells*S)+(p.n_cells-1)*tp - c],[OH-c,OH-c],color=BAD,lw=1.4,zorder=3)
        ax.plot([left+c,left+tw+ (p.n_cells*S)+(p.n_cells-1)*tp - c],[c,c],color=BAD,lw=1.4,zorder=3)
        # vertical bars in each wall
        wx=left+tw/2
        xwalls=[left+tw/2]
        xx=left+tw
        for i in range(p.n_cells):
            xx+=S
            if i<p.n_cells-1:
                xwalls.append(xx+tp/2); xx+=tp
        xwalls.append(W_ext-tw/2)
        for xw in xwalls:
            ax.plot([xw,xw],[c,OH-c],color=BAD,lw=1.1,zorder=3)
        # dimensions
        ax.annotate("",(left,-0.45),(W_ext-tw/2,-0.45),arrowprops=dict(arrowstyle="<->",color=BLUE))
        ax.text((left+W_ext-tw/2)/2,-0.72,f"{(W_ext+tw/2):.2f} m overall",ha="center",color=BLUE,fontsize=9)
        ax.annotate("",(W_ext-tw/2+0.5,0),(W_ext-tw/2+0.5,OH),arrowprops=dict(arrowstyle="<->",color=BLUE))
        ax.text(W_ext-tw/2+0.7,OH/2,f"{OH:.2f} m",va="center",rotation=90,color=BLUE,fontsize=9)
        ax.text(left+tw, OH+0.18, f"{p.n_cells} cell × {S:.2f} m clear × {H:.2f} m · C{p.fck:.0f}/{p.fck+8:.0f} · fy{p.fyk:.0f}",
                color=BLUE,fontsize=9)
        ax.set_xlim(left-1.0, W_ext+1.1); ax.set_ylim(-1.0, OH+0.6)
        self.fig.tight_layout(); self.canvas.draw()

    def export_dxf(self):
        from dxf_export import export_dxf
        pr=type("pp",(),{})()
        # minimal adapter to dxf_export's expected attrs (single-cell draws; use overall)
        self.statusBar().showMessage("DXF export: wired in next build step")

def QtWidgets_process():
    app=W.QApplication.instance()
    if app: app.processEvents()

def main():
    shot=None
    if "--shot" in sys.argv: shot=sys.argv[sys.argv.index("--shot")+1]
    app=W.QApplication(sys.argv)
    app.setStyle("Fusion")
    win=Main(); win.show()
    if shot:
        def grab():
            win.grab().save(shot); app.quit()
        QtCore.QTimer.singleShot(900, grab)
    sys.exit(app.exec())

if __name__=="__main__":
    main()
