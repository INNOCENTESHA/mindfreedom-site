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

BLUE="#1b3a5c"; ACC="#2d7dd2"; OK="#1e8449"; BAD="#c0392b"; LIGHT="#f4f6f9"; CARD="#ffffff"; RED="#c0392b"

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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CBC — Box Culvert Parametric Designer  v0.1")
        self.resize(1380, 880); self.setStyleSheet(f"QMainWindow{{background:{LIGHT};}}")
        self._build_header()
        central=W.QWidget(); self.setCentralWidget(central)
        root=W.QHBoxLayout(central); root.setContentsMargins(10,8,10,10); root.setSpacing(10)
        root.addWidget(self._input_panel(),0); root.addWidget(self._view_panel(),1)
        self.statusBar().showMessage("Ready"); self.run()

    # ---------------- header ----------------
    def _build_header(self):
        bar=W.QWidget(); bar.setFixedHeight(58); bar.setFixedWidth(1380); bar.setStyleSheet(f"background:{BLUE};")
        h=W.QHBoxLayout(bar); h.setContentsMargins(16,0,16,0)
        t=W.QLabel("CBC   ·   Parametric Box Culvert Designer"); t.setStyleSheet("color:white;font:600 18px 'DejaVu Sans';")
        sub=W.QLabel("BS 5400 HB · EN 1992-1-1 · 2D frame on elastic foundation"); sub.setStyleSheet("color:#aecbed;font:12px 'DejaVu Sans';")
        col=W.QVBoxLayout(); col.setSpacing(0); col.addWidget(t); col.addWidget(sub); h.addLayout(col); h.addStretch(1)
        for name,slot in [("Analyse && Design",self.run),("Export DXF",self.export_dxf)]:
            b=W.QPushButton(name); b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{ACC};color:white;border:none;padding:8px 16px;border-radius:5px;font:600 13px;}}QPushButton:hover{{background:#3b8ee0;}}")
            b.clicked.connect(slot); h.addWidget(b)
        tb=W.QToolBar(); tb.setMovable(False); tb.addWidget(bar); tb.setStyleSheet("QToolBar{border:none;padding:0;}")
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
        v.addWidget(l); v.addStretch(1); return panel

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
        t3=W.QWidget(); l3=W.QVBoxLayout(t3); self.fig3=Figure(figsize=(8,6),facecolor="white"); self.cv3=Canvas(self.fig3); l3.addWidget(self.cv3)
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
        v.addWidget(self.tabs,1); return panel

    def params(self):
        p=P(); p.n_cells=self.i_cells.value(); p.span=self.i_span.value(); p.height=self.i_height.value()
        p.t_top=self.i_ttop.value(); p.t_base=self.i_tbase.value(); p.t_wall=self.i_twall.value(); p.t_pier=self.i_twall.value()
        p.fill=self.i_fill.value(); p.fck=self.i_fck.value(); p.fyk=self.i_fyk.value(); p.cover=self.i_cover.value()
        p.hb_units=self.i_hb.value(); p.hb_wheel=self.i_hb.value()*10/4
        p.gamma_soil=self.i_soil.value(); p.K0=self.i_k0.value(); p.surcharge=self.i_sur.value(); p.ks=self.i_ks.value(); return p

    # ---------------- run ----------------
    def run(self):
        self.statusBar().showMessage("Analysing…"); pdui()
        p=self.params(); self.box=Box(p).analyse(); self.p=p
        self.uls=self.box.uls_combos(); self.sls=self.box.sls_combos()
        self.bearing_sls=max(self.box.bearing(c)[0] for c in self.sls)
        self.bearing_uls=max(self.box.bearing(c)[0] for c in self.uls)
        tmap={'top':p.t_top,'base':p.t_base,'walls':p.t_wall,'piers':p.t_pier}
        names={'top':'Top slab','base':'Base slab','walls':'Outer walls','piers':'Inner (pier) walls'}
        rows=[]; maxutil=0; govern="-"; self.design={}
        for m in ['top','base','walls','piers']:
            if m=='piers' and p.n_cells<2: continue
            e=self.box.envelope(m,self.uls); t=tmap[m]
            Mc=e['Mmin'] if abs(e['Mmin'])>abs(e['Mmax']) else e['Mmax']
            fd,_=design_flexure(names[m],Mc,t,p.fck,p.fyk,p.cover); sh=check_shear(names[m],e['Vmax'],t,p.fck,p.cover,fd.As_prov)
            self.design[m]=dict(fd=fd,sh=sh,env=e,Mc=Mc,t=t,name=names[m])
            rows.append(("Flexure",names[m],f"{Mc:,.1f} kNm/m",f"As {fd.As_req:,.0f} mm²/m",f"T{fd.dia}@{fd.spacing} ({fd.As_prov:,.0f})",fd.util,fd.util<=1))
            rows.append(("Shear",names[m]+" at d",f"{sh.V:,.1f} kN/m",f"VRd,c {sh.VRdc:,.1f}","ρ-based",sh.util,sh.ok))
            for tag,u in [("Shear",sh.util),("Flexure",fd.util)]:
                if u>maxutil: maxutil=u; govern=f"{tag} - {names[m]}"
        rows.append(("Bearing","Founding, SLS",f"{self.bearing_sls:,.1f} kPa","≤ 210 kPa","site SI",self.bearing_sls/210,self.bearing_sls<=210))
        self.maxutil=maxutil; self.govern=govern
        self._fill_checks(rows)
        status="PASS" if maxutil<=1 and self.bearing_sls<=210 else "REVIEW"; col=OK if status=="PASS" else BAD
        self.banner.setStyleSheet(f"background:{col};color:white;border-radius:7px;padding:0 18px;font:600 15px 'DejaVu Sans';")
        self.banner.setText(f"  DESIGN {status}     ·     Max utilisation {maxutil:.2f}     ·     Governing: {govern}     ·     Bearing SLS {self.bearing_sls:.0f} / ULS {self.bearing_uls:.0f} kPa")
        self._draw_section(self.fig1,p,False); self._draw_bmd(p); self._draw_section(self.fig3,p,True); self._fill_bbs(p); self._fill_report(p)
        self.statusBar().showMessage(f"{p.n_cells}-cell {p.span:.2f}×{p.height:.2f} m · {len(self.box.u)} load cases · governing {govern}")

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
                f"{series[0][2][ipk]:.0f}", color=BLUE, fontsize=8, ha="center")
        ax.set_title(f"Bending moment envelope  ·  ULS, governing HB position  ·  max |M| = {mmax:.0f} kNm/m", color=BLUE, fontsize=11, loc="center", pad=12)
        ax.set_xlim(left-1.0,left+Wext+1.0); ax.set_ylim(-1.0,OH+1.0)
        self.fig2.tight_layout(); self.fig2.canvas.draw()

    # ---------------- BBS ----------------
    def _fill_bbs(self,p):
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

    def export_dxf(self):
        self.statusBar().showMessage("DXF export wired in next build step")

def main():
    shot=None; tab=0
    if "--shot" in sys.argv: shot=sys.argv[sys.argv.index("--shot")+1]
    if "--tab" in sys.argv: tab=int(sys.argv[sys.argv.index("--tab")+1])
    app=W.QApplication(sys.argv); app.setStyle("Fusion"); win=Main(); win.tabs.setCurrentIndex(tab); win.show()
    if shot:
        def grab(): win.grab().save(shot); app.quit()
        QtCore.QTimer.singleShot(1000, grab)
    sys.exit(app.exec())

if __name__=="__main__":
    main()
