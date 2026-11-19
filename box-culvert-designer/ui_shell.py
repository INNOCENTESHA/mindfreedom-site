"""
Workspace of the desktop application, laid out the way structural analysis packages are:
a ribbon of task tabs, a works tree and parameter panel on the left, the model view in the middle
(model, loads, deformed shape, reactions and force diagrams with a colour legend), result tables,
and a message window underneath.
"""
import json, math, time
import numpy as np
from matplotlib.figure import Figure
from matplotlib.collections import PolyCollection, LineCollection
from matplotlib import cm, colors as mcolors
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as Canvas, NavigationToolbar2QT as NavBar
from PySide6 import QtCore, QtGui, QtWidgets as W

INK = "#2b3440"; EDGE = "#c3c9d1"; PANEL = "#eef0f3"; RIB = "#f6f7f9"; HILITE = "#cfe3fa"; ACCENT = "#1f6fc4"
VIEW_BG = "#0b0e13"

STYLE = f"""
QMainWindow, QDockWidget {{ background:{PANEL}; }}
QWidget {{ font: 9pt 'Segoe UI', 'DejaVu Sans'; color:{INK}; }}
QDockWidget::title {{ background:#dfe3e8; padding:4px 8px; border:1px solid {EDGE}; font-weight:600; }}
QTreeWidget, QTableWidget, QTextEdit {{ background:#ffffff; border:1px solid {EDGE}; }}
QTreeWidget::item {{ padding:2px 0; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{ background:{HILITE}; color:{INK}; }}
QHeaderView::section {{ background:#e6e9ee; padding:4px; border:none; border-right:1px solid {EDGE}; border-bottom:1px solid {EDGE}; font-weight:600; }}
QTabWidget::pane {{ border:1px solid {EDGE}; background:#ffffff; }}
QTabBar::tab {{ padding:5px 12px; background:#e2e6eb; border:1px solid {EDGE}; margin-right:1px; }}
QTabBar::tab:selected {{ background:#ffffff; font-weight:600; }}
QStatusBar {{ background:#dfe3e8; border-top:1px solid {EDGE}; }}
QToolButton {{ border:1px solid transparent; border-radius:3px; padding:2px; }}
QToolButton:hover {{ background:{HILITE}; border:1px solid #9cc2ee; }}
QToolButton:checked {{ background:#b9d6f7; border:1px solid #7fb0e8; }}
QGroupBox {{ border:1px solid {EDGE}; margin-top:9px; background:#ffffff; font-weight:600; }}
QGroupBox::title {{ subcontrol-origin:margin; left:8px; padding:0 4px; }}
"""


# ------------------------------------------------------------------ icons (drawn, no image files)
def icon(kind, size=32):
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing); p.scale(size / 32.0, size / 32.0)
    C = QtGui.QColor; blue, grey, red, green, amber = C("#1f6fc4"), C("#5d6976"), C("#c8372d"), C("#2f9e55"), C("#d98a12")
    pen = lambda c, w=2.0: p.setPen(QtGui.QPen(c, w, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
    nob = lambda: p.setBrush(QtCore.Qt.NoBrush)
    L = lambda *a: p.drawLine(QtCore.QPointF(a[0], a[1]), QtCore.QPointF(a[2], a[3]))
    poly = lambda pts: p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts]))
    fillp = lambda pts, c: (p.setBrush(c), p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])), nob())
    def box(w=2.2, c=grey):
        pen(c, w); nob(); p.drawRect(QtCore.QRectF(5, 9, 22, 16)); L(16, 9, 16, 25)
    def arrow(x, y0, y1, c):
        pen(c, 1.8); L(x, y0, x, y1); s = 1 if y1 > y0 else -1; L(x, y1, x - 2.5, y1 - 3 * s); L(x, y1, x + 2.5, y1 - 3 * s)
    def page(c=grey):
        pen(c, 1.6); nob(); poly([(8, 4), (20, 4), (25, 9), (25, 28), (8, 28), (8, 4)]); poly([(20, 4), (20, 9), (25, 9)])
    def grid(c=grey):
        pen(c, 1.4); nob(); p.drawRect(QtCore.QRectF(5, 6, 22, 20))
        for y in (11, 16, 21): L(5, y, 27, y)
        L(13, 6, 13, 26); L(20, 6, 20, 26)
    k = kind
    if k == "new": page(); pen(green, 2.2); L(22, 20, 22, 30); L(17, 25, 27, 25)
    elif k == "open": pen(amber, 1.8); fillp([(4, 11), (12, 11), (14, 8), (26, 8), (26, 25), (4, 25)], C("#f5d58a"))
    elif k == "save":
        pen(blue, 1.8); fillp([(5, 5), (23, 5), (27, 9), (27, 27), (5, 27)], C("#bcd6f3")); p.setBrush(C("#ffffff")); p.drawRect(QtCore.QRectF(10, 17, 12, 10)); nob(); L(10, 5, 10, 11); L(10, 11, 20, 11); L(20, 11, 20, 5)
    elif k in ("dxf", "pdf", "report"):
        page(); p.setPen(red if k == "pdf" else blue); f = p.font(); f.setPixelSize(8); f.setBold(True); p.setFont(f)
        p.drawText(QtCore.QRectF(8, 14, 17, 12), QtCore.Qt.AlignCenter, {"dxf": "DXF", "pdf": "PDF", "report": "RPT"}[k])
    elif k == "box": box(2.6, blue)
    elif k == "cells": box(2.0); pen(blue, 2.0); L(10.5, 9, 10.5, 25); L(21.5, 9, 21.5, 25)
    elif k == "toe": box(2.0); pen(red, 2.6); L(1, 25, 5, 25); L(27, 25, 31, 25)
    elif k == "skew": pen(grey, 2); nob(); poly([(9, 6), (27, 6), (23, 26), (5, 26), (9, 6)]); pen(red, 1.4); L(3, 16, 29, 16)
    elif k == "mat":
        pen(grey, 1.6); p.setBrush(C("#d5d9de")); p.drawRect(QtCore.QRectF(6, 7, 20, 18)); p.setBrush(C("#7c8792"))
        for x, y in ((10, 11), (17, 13), (22, 20), (11, 20), (15, 17)): p.drawEllipse(QtCore.QPointF(x, y), 1.4, 1.4)
        nob()
    elif k == "sect": pen(grey, 1.6); p.setBrush(C("#d5d9de")); p.drawRect(QtCore.QRectF(4, 12, 24, 8)); nob(); pen(red, 1.5); L(30, 12, 30, 20); L(28.5, 12, 31.5, 12); L(28.5, 20, 31.5, 20)
    elif k == "cover": pen(grey, 1.6); nob(); p.drawRect(QtCore.QRectF(5, 8, 22, 16)); pen(red, 1.8); poly([(9, 12), (9, 20), (23, 20), (23, 12)])
    elif k == "spring":
        box(1.6); pen(green, 1.6)
        for x in (8, 16, 24): poly([(x, 25), (x - 2, 26.5), (x + 2, 28), (x - 2, 29.5), (x, 31)])
    elif k == "soil":
        for i, c in enumerate(("#d9b98a", "#b9976a", "#8f7a5c")): p.setPen(QtCore.Qt.NoPen); p.setBrush(C(c)); p.drawRect(QtCore.QRectF(4, 6 + 7 * i, 24, 7))
        nob(); pen(blue, 1.4); L(4, 16, 28, 16)
    elif k == "load": box(1.6); [arrow(x, 1, 8, red) for x in (8, 14, 20, 26)]
    elif k == "truck":
        pen(grey, 1.8); p.setBrush(C("#f1c66a")); p.drawRect(QtCore.QRectF(4, 9, 16, 11)); p.drawRect(QtCore.QRectF(20, 13, 8, 7)); p.setBrush(C("#333a42"))
        for x in (9, 16, 24): p.drawEllipse(QtCore.QPointF(x, 22), 2.8, 2.8)
        nob()
    elif k == "earth":
        box(1.6); pen(amber, 1.5)
        for y, l in ((11, 2), (15, 3.5), (19, 5), (23, 6.5)): L(5 - l, y, 4, y)
        L(3, 9, -2.5 + 0, 25)
    elif k == "combo": p.setPen(blue); f = p.font(); f.setPixelSize(13); f.setBold(True); p.setFont(f); p.drawText(QtCore.QRectF(0, 0, 32, 32), QtCore.Qt.AlignCenter, "ΣγF")
    elif k == "run": pen(green, 1.5); fillp([(9, 5), (26, 16), (9, 27)], C("#43b46b"))
    elif k == "react": box(1.6); [arrow(x, 31, 26, green) for x in (8, 16, 24)]
    elif k == "deform": pen(grey, 1.2); nob(); p.drawRect(QtCore.QRectF(5, 9, 22, 16)); pen(blue, 2); path = QtGui.QPainterPath(QtCore.QPointF(5, 9)); path.quadTo(16, 16, 27, 9); p.drawPath(path); path = QtGui.QPainterPath(QtCore.QPointF(5, 25)); path.quadTo(16, 19, 27, 25); p.drawPath(path)
    elif k in ("moment", "shear", "axial"):
        pen(grey, 1.8); L(4, 12, 28, 12)
        if k == "moment":
            path = QtGui.QPainterPath(QtCore.QPointF(4, 6)); path.quadTo(16, 36, 28, 6); pen(red, 1.8); p.setBrush(C(200, 55, 45, 70)); path.lineTo(28, 12); path.lineTo(4, 12); path.closeSubpath(); p.drawPath(path); nob()
        elif k == "shear": pen(blue, 1.8); fillp([(4, 12), (4, 3), (16, 12), (28, 21), (28, 12)], C(31, 111, 196, 70))
        else: pen(amber, 1.8); fillp([(4, 12), (4, 20), (28, 20), (28, 12)], C(217, 138, 18, 70))
    elif k == "table": grid(blue)
    elif k == "design": pen(grey, 1.6); p.setBrush(C("#d5d9de")); p.drawRect(QtCore.QRectF(5, 9, 22, 14)); p.setBrush(red); p.setPen(QtCore.Qt.NoPen); [p.drawEllipse(QtCore.QPointF(x, 19), 1.8, 1.8) for x in (9, 14, 18, 23)]; nob()
    elif k == "check": grid(); pen(green, 3); poly([(9, 17), (14, 22), (24, 10)])
    elif k == "rebar": box(1.4); pen(red, 1.8); nob(); p.drawRect(QtCore.QRectF(7.5, 11.5, 17, 11))
    elif k == "bbs": grid(); pen(red, 2); poly([(7, 9), (11, 9)]); poly([(7, 14), (11, 14)]); poly([(7, 19), (11, 19)])
    elif k == "plan": pen(grey, 1.8); nob(); p.drawRect(QtCore.QRectF(10, 10, 12, 12)); pen(blue, 1.8); L(10, 10, 4, 3); L(22, 10, 28, 3); L(10, 22, 4, 29); L(22, 22, 28, 29)
    elif k == "sheets": pen(grey, 1.5); p.setBrush(C("#ffffff")); p.drawRect(QtCore.QRectF(9, 4, 18, 20)); p.drawRect(QtCore.QRectF(5, 8, 18, 20)); nob(); pen(blue, 1.3); L(8, 14, 20, 14); L(8, 18, 20, 18); L(8, 22, 16, 22)
    elif k == "fit": pen(blue, 2); [poly(q) for q in ([(4, 11), (4, 4), (11, 4)], [(21, 4), (28, 4), (28, 11)], [(28, 21), (28, 28), (21, 28)], [(11, 28), (4, 28), (4, 21)])]; pen(grey, 1.6); p.drawRect(QtCore.QRectF(10, 11, 12, 10))
    elif k in ("nodes", "elems"):
        pen(grey, 1.8); L(5, 22, 27, 22); p.setBrush(green); p.setPen(QtCore.Qt.NoPen); [p.drawRect(QtCore.QRectF(x - 2, 20, 4, 4)) for x in (5, 16, 27)]; nob()
        p.setPen(blue if k == "elems" else green); f = p.font(); f.setPixelSize(11); f.setBold(True); p.setFont(f); p.drawText(QtCore.QRectF(0, 3, 32, 14), QtCore.Qt.AlignCenter, "12" if k == "nodes" else "[3]")
    elif k == "values": p.setPen(red); f = p.font(); f.setPixelSize(12); f.setBold(True); p.setFont(f); p.drawText(QtCore.QRectF(0, 0, 32, 32), QtCore.Qt.AlignCenter, "48.8")
    elif k == "exit": pen(red, 2.6); L(8, 8, 24, 24); L(24, 8, 8, 24)
    else: pen(grey); nob(); p.drawEllipse(QtCore.QPointF(16, 16), 9, 9)
    p.end(); return QtGui.QIcon(pm)


# ------------------------------------------------------------------ ribbon
class Ribbon(W.QTabWidget):
    """Task tabs holding groups of large buttons. spec: [(tab, [(group, [(text, icon, slot, tip[, checkable])])])]"""
    def __init__(self, spec):
        super().__init__(); self.setFixedHeight(112); self.setDocumentMode(True); self.buttons = {}
        self.setStyleSheet(f"QTabWidget::pane{{border:none;border-bottom:1px solid {EDGE};background:{RIB};}}"
                           f"QTabBar::tab{{padding:4px 14px;background:transparent;border:none;border-bottom:2px solid transparent;}}"
                           f"QTabBar::tab:selected{{color:{ACCENT};border-bottom:2px solid {ACCENT};font-weight:600;background:{RIB};}}")
        for tab, groups in spec:
            page = W.QWidget(); h = W.QHBoxLayout(page); h.setContentsMargins(6, 2, 6, 0); h.setSpacing(2)
            for gname, items in groups:
                g = W.QWidget(); v = W.QVBoxLayout(g); v.setContentsMargins(4, 0, 4, 0); v.setSpacing(0)
                row = W.QHBoxLayout(); row.setSpacing(1)
                for it in items:
                    text, ic, slot, tip = it[:4]
                    b = W.QToolButton(); b.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon); b.setIcon(icon(ic)); b.setIconSize(QtCore.QSize(30, 30))
                    b.setText(text); b.setToolTip(tip); b.setMinimumWidth(60); b.setFixedHeight(64); b.setAutoRaise(True)
                    if len(it) > 4 and it[4]: b.setCheckable(True); b.toggled.connect(slot)
                    else: b.clicked.connect(slot)
                    row.addWidget(b); self.buttons[(tab, text.replace("\n", " "))] = b
                v.addLayout(row)
                cap = W.QLabel(gname); cap.setAlignment(QtCore.Qt.AlignCenter); cap.setStyleSheet("color:#6b7682;font-size:8pt;"); v.addWidget(cap)
                h.addWidget(g)
                sep = W.QFrame(); sep.setFrameShape(W.QFrame.VLine); sep.setStyleSheet(f"color:{EDGE};"); h.addWidget(sep)
            h.addStretch(1); self.addTab(page, tab)


# ------------------------------------------------------------------ model view
STATIC = {"SW": "Self weight", "EV": "Vertical earth (fill)", "EH": "Horizontal earth, at rest", "LS": "Live-load surcharge, both sides", "LS1": "Live-load surcharge, one side"}
DISPLAYS = ["Model", "Loads", "Deformed shape", "Reactions", "Bending moment  My", "Shear force  Fz", "Axial force  Fx"]


def case_title(k):
    if k in STATIC: return f"{k}: {STATIC[k]}"
    if k.startswith("HB"): return f"{k[:3]}: HB {'two axles' if k[2] == '2' else 'one axle'} at x = {float(k.split('@')[1]):.3f} m"
    return k


class ModelView(W.QWidget):
    """The analysis model and its results on a dark view with a banded colour legend.
    The frame solver stores displacements and member end forces with the sign opposite to the global axes
    (loads enter as their negative); values are converted here: settlement is -Z, tension is +."""
    def __init__(self, main):
        super().__init__(); self.main = main; self.box = None; self._cache = {}
        v = W.QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        bar = W.QWidget(); bar.setStyleSheet(f"background:{RIB};border-bottom:1px solid {EDGE};"); h = W.QHBoxLayout(bar); h.setContentsMargins(6, 3, 6, 3)
        self.cb_disp = W.QComboBox(); self.cb_disp.addItems(DISPLAYS); self.cb_lc = W.QComboBox(); self.cb_lc.setMinimumWidth(330); self.cb_lc.setMaxVisibleItems(30)
        h.addWidget(W.QLabel("Display")); h.addWidget(self.cb_disp); h.addSpacing(10); h.addWidget(W.QLabel("Load case / combination")); h.addWidget(self.cb_lc)
        self.t_nodes = self._toggle("nodes", "Node numbers"); self.t_elems = self._toggle("elems", "Element numbers"); self.t_vals = self._toggle("values", "Values on the diagram", True)
        for t in (self.t_nodes, self.t_elems, self.t_vals): h.addWidget(t)
        h.addStretch(1); v.addWidget(bar)
        self.fig = Figure(facecolor=VIEW_BG); self.cv = Canvas(self.fig); self.nav = NavBar(self.cv, self); self.nav.setIconSize(QtCore.QSize(16, 16))
        self.nav.setStyleSheet("QToolBar{border:none;background:%s;}" % RIB); h.addWidget(self.nav)
        v.addWidget(self.cv, 1)
        self.cb_disp.currentIndexChanged.connect(self.draw); self.cb_lc.currentIndexChanged.connect(self.draw)
        self.cv.mpl_connect("motion_notify_event", self._moved)

    def _toggle(self, ic, tip, on=False):
        b = W.QToolButton(); b.setIcon(icon(ic, 22)); b.setIconSize(QtCore.QSize(22, 22)); b.setCheckable(True); b.setChecked(on); b.setToolTip(tip); b.toggled.connect(lambda _: self.draw()); return b

    def _moved(self, ev):
        if ev.inaxes is not None and ev.xdata is not None and getattr(ev.inaxes, "_is_model", False): self.main.lb_xy.setText(f"X {ev.xdata:8.3f}   Z {ev.ydata:8.3f}  m")

    # ---- data
    def set_box(self, box, uls, sls):
        self.box = box; self.uls = uls; self.sls = sls; self._cache = {}
        self.Fk = {k: np.array(v) for k, v in box.F.items()}
        keep = self.cb_lc.currentText(); self.cb_lc.blockSignals(True); self.cb_lc.clear()
        self.cases = [("ULS envelope  (all combinations)", ("env", uls)), ("SLS envelope  (characteristic)", ("env", sls)),
                      ("ULS governing  (largest top slab moment)", ("one", self._governing(uls))), ("SLS governing  (largest bearing pressure)", ("one", max(sls, key=lambda c: box.bearing(c)[0])))]
        self.cases += [(case_title(k), ("one", {k: 1.0})) for k in list(STATIC) + box.hb_keys]
        self.cb_lc.addItems([c[0] for c in self.cases])
        i = self.cb_lc.findText(keep); self.cb_lc.setCurrentIndex(i if i >= 0 else 0); self.cb_lc.blockSignals(False); self.draw()

    def F_of(self, fmap): return sum(f * self.Fk[k] for k, f in fmap.items())

    def _governing(self, combos):
        top = self.box.members["top"]; return max(combos, key=lambda c: np.abs(self.F_of(c)[top][:, [2, 5]]).max())

    def current(self):
        """(label, kind, combination map used for single-case displays, list of maps for envelopes)"""
        name, (kind, data) = self.cases[max(0, self.cb_lc.currentIndex())]
        if kind == "env": return name, kind, (self._governing(data) if data is self.uls else max(data, key=lambda c: self.box.bearing(c)[0])), data
        return name, kind, data, [data]

    def loads_of(self, fmap):
        """Element loads of a combination: arrays gy, wt_i, wt_j (the engine keeps loads only while a case is solved)."""
        b = self.box; ne = len(b.fr.elements); out = np.zeros((ne, 3))
        for k, f in fmap.items():
            if k not in self._cache:
                if k.startswith("HB"): b.case("HB", hb_pos=float(k.split("@")[1]), hb_two=(k[2] == "2"))
                else: b.case(k)
                self._cache[k] = np.array([[e.gy, e.wt_i, e.wt_j] for e in b.fr.elements])
            out += f * self._cache[k]
        return out

    def end_values(self, comp, maps):
        """Values at the i and j end of every element: arrays (hi_i, hi_j, lo_i, lo_j) over the combinations."""
        ci, cj, si, sj = {"M": (2, 5, 1, -1), "V": (1, 4, 1, -1), "N": (0, 3, 1, -1)}[comp]
        A = np.array([self.F_of(m) for m in maps]); vi = si * A[:, :, ci]; vj = sj * A[:, :, cj]
        return vi.max(0), vj.max(0), vi.min(0), vj.min(0)

    # ---- drawing
    def draw(self, *_):
        b = self.box
        if b is None: return
        fig = self.fig; fig.clear(); ax = fig.add_axes([0.0, 0.0, 0.90, 1.0]); ax._is_model = True
        ax.set_facecolor(VIEW_BG); ax.set_aspect("equal"); ax.axis("off")
        nodes = b.fr.nodes; els = b.fr.elements; pt = fig.dpi / 72.0 and 1.0
        P1 = np.array([[nodes[e.ni].x, nodes[e.ni].y] for e in els]); P2 = np.array([[nodes[e.nj].x, nodes[e.nj].y] for e in els])
        d = P2 - P1; Ls = np.hypot(d[:, 0], d[:, 1]); nrm = np.c_[-d[:, 1] / Ls, d[:, 0] / Ls]
        xs = [n.x for n in nodes]; ys = [n.y for n in nodes]; x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); size = max(x1 - x0, y1 - y0)
        disp = self.cb_disp.currentText().split("  ")[0]; name, kind, fmap, maps = self.current()
        results = disp not in ("Model", "Loads")
        ax.add_collection(LineCollection(np.stack([P1, P2], 1), colors="#7f8b99" if results else "#d7dde5", linewidths=1.2 if results else 2.0, zorder=3))
        ax.plot(xs, ys, "s", ms=2.6 * 96.0 / fig.dpi, color="#39d27a", zorder=4)
        sp = 0.045 * size                                                    # Winkler springs under the base
        for nid in b.base_nodes:
            n = nodes[nid]; zz = np.linspace(0, -sp, 7); xx = n.x + np.array([0, 0, 1, -1, 1, 0, 0]) * sp * 0.16
            ax.plot(xx, n.y + zz, color="#3fae6a", lw=0.7, zorder=2); ax.plot([n.x - sp * 0.2, n.x + sp * 0.2], [n.y - sp] * 2, color="#3fae6a", lw=0.9, zorder=2)
        fs = 7.5 * 96.0 / fig.dpi; self._k = 96.0 / fig.dpi
        if self.t_nodes.isChecked():
            for i, n in enumerate(nodes): ax.text(n.x, n.y, f" {i + 1}", color="#39d27a", fontsize=fs, va="bottom", zorder=6)
        if self.t_elems.isChecked():
            for i in range(len(els)): m = (P1[i] + P2[i]) / 2; ax.text(m[0], m[1], f"{i + 1}", color="#8fb9ff", fontsize=fs, ha="center", va="center", zorder=6, bbox=dict(fc=VIEW_BG, ec="none", pad=0.4))
        info = []; legend = None; unit = ""
        if disp == "Loads":
            Lw = self.loads_of(fmap); vmax = np.abs(Lw).max() or 1.0; sc = 0.16 * size / vmax; segs = []; heads = []
            for i in range(len(els)):
                gy, wi, wj = Lw[i]; mid = (P1[i] + P2[i]) / 2
                for val, vec in ((gy, np.array([0.0, 1.0])), ((wi + wj) / 2, nrm[i])):
                    if abs(val) < 1e-9: continue
                    tip = mid; tail = mid - vec * val * sc; segs.append([tail, tip]); heads.append((tail, tip))
            ax.add_collection(LineCollection(segs, colors="#ff5a4d", linewidths=0.9, zorder=5))
            for tail, tip in heads[::1]:
                ax.annotate("", xy=tip, xytext=tail, arrowprops=dict(arrowstyle="-|>", color="#ff5a4d", lw=0.0, mutation_scale=7), zorder=5)
            gmax = np.abs(Lw[:, 0]).max(); wmax = np.abs(Lw[:, 1:]).max()
            info = [f"vertical  max {gmax:,.2f} kN/m", f"lateral   max {wmax:,.2f} kN/m"]; unit = "kN/m per metre run of culvert"
        elif disp == "Deformed shape":
            u = -sum(f * b.u[k] for k, f in fmap.items()); U = np.array([[u[3 * i], u[3 * i + 1]] for i in range(len(nodes))]); mag = np.hypot(U[:, 0], U[:, 1]); umax = mag.max() or 1e-12
            sc = 0.10 * size / umax; Q = np.array([[n.x, n.y] for n in nodes]) + U * sc
            S = np.stack([[Q[e.ni] for e in els], [Q[e.nj] for e in els]], 1); val = np.array([(mag[e.ni] + mag[e.nj]) / 2 for e in els]) * 1000
            legend = self._bands(ax, S, val, lines=True); unit = "mm"; i = int(mag.argmax())
            info = [f"MAX  {umax * 1000:.3f} mm  at node {i + 1}", f"DX {U[i, 0] * 1000:+.3f}   DZ {U[i, 1] * 1000:+.3f} mm", f"plot scale  x {sc:,.0f}"]
        elif disp == "Reactions":
            u = sum(f * b.u[k] for k, f in fmap.items()); R = np.array([nodes[n].ky * u[3 * n + 1] for n in b.base_nodes]); pr = np.array([R[i] / nodes[n]._trib for i, n in enumerate(b.base_nodes)])
            sc = 0.22 * size / (np.abs(pr).max() or 1.0); bx = np.array([nodes[n].x for n in b.base_nodes]); by = np.array([nodes[n].y for n in b.base_nodes]) - sp * 1.15
            quads = [[(bx[i], by[i]), (bx[i + 1], by[i + 1]), (bx[i + 1], by[i + 1] - pr[i + 1] * sc), (bx[i], by[i] - pr[i] * sc)] for i in range(len(bx) - 1)]
            legend = self._bands(ax, quads, (pr[:-1] + pr[1:]) / 2, rng=(float(pr.min()), float(pr.max()))); unit = "kPa  (ground pressure)"
            if self.t_vals.isChecked():
                for i in sorted({0, len(bx) - 1, int(pr.argmax()), int(pr.argmin())}): ax.text(bx[i], by[i] - pr[i] * sc - 0.02 * size, f"{pr[i]:.1f}", color="white", fontsize=fs, ha="center", va="top", zorder=7)
            info = [f"MAX  {pr.max():.1f} kPa", f"MIN  {pr.min():.1f} kPa", f"ΣFz  {R.sum():,.1f} kN/m"]
        elif results:
            comp = {"Bending moment": "M", "Shear force": "V", "Axial force": "N"}[disp]; hi_i, hi_j, lo_i, lo_j = self.end_values(comp, maps)
            vmax = max(np.abs(hi_i).max(), np.abs(hi_j).max(), np.abs(lo_i).max(), np.abs(lo_j).max()) or 1.0; sc = 0.17 * size / vmax; sgn = -1.0
            quads = []; vals = []
            for a_i, a_j in ((hi_i, hi_j), (lo_i, lo_j)) if kind == "env" else ((hi_i, hi_j),):
                for i in range(len(els)):
                    quads.append([P1[i], P2[i], P2[i] + sgn * nrm[i] * a_j[i] * sc, P1[i] + sgn * nrm[i] * a_i[i] * sc]); vals.append((a_i[i] + a_j[i]) / 2)
            legend = self._bands(ax, quads, np.array(vals), rng=(float(min(lo_i.min(), lo_j.min())), float(max(hi_i.max(), hi_j.max())))); unit = {"M": "kNm/m", "V": "kN/m", "N": "kN/m  (tension +)"}[comp]
            allv = np.r_[hi_i, hi_j, lo_i, lo_j]; info = [f"MAX  {allv.max():+,.2f}", f"MIN  {allv.min():+,.2f}"]
            if self.t_vals.isChecked():                                      # peak of each member
                for mname, ids in b.members.items():
                    if not len(ids): continue
                    ids = np.array(ids)
                    for arr_i, arr_j in ((hi_i, hi_j), (lo_i, lo_j)):
                        cand = np.r_[arr_i[ids], arr_j[ids]]; k = int(np.abs(cand).argmax()); val = cand[k]
                        if abs(val) < 0.03 * vmax: continue
                        e = ids[k % len(ids)]; base = P1[e] if k < len(ids) else P2[e]; q = base + sgn * nrm[e] * val * sc
                        ax.text(q[0], q[1], f"{val:.1f}", color="white", fontsize=fs, ha="center", va="center", zorder=8, bbox=dict(fc=VIEW_BG, ec="none", pad=0.3, alpha=0.75))
        m = 0.20 * size; ax.set_xlim(x0 - m, x1 + m); ax.set_ylim(y0 - m - 0.06 * size, y1 + m)
        # title block of the view (top right), as result views carry
        head = [self.cb_disp.currentText().upper(), name] + ([f"shown for: {self._short(fmap)}"] if kind == "env" and disp in ("Loads", "Deformed shape", "Reactions") else []) + info + ([f"UNIT  {unit}"] if unit else [])
        fig.text(0.012, 0.985, "\n".join(head), color="#e8edf3", fontsize=8.5 * self._k, va="top", ha="left", family="DejaVu Sans Mono", linespacing=1.45)
        ax.annotate("", xy=(x0 - 0.5 * m, y0 - 0.9 * m + 0.1 * size), xytext=(x0 - 0.5 * m, y0 - 0.9 * m), arrowprops=dict(arrowstyle="-|>", color="#4d8dff", lw=1.2))
        ax.annotate("", xy=(x0 - 0.5 * m + 0.1 * size, y0 - 0.9 * m), xytext=(x0 - 0.5 * m, y0 - 0.9 * m), arrowprops=dict(arrowstyle="-|>", color="#ff5a4d", lw=1.2))
        ax.text(x0 - 0.5 * m + 0.115 * size, y0 - 0.9 * m, "X", color="#ff5a4d", fontsize=8 * self._k, va="center"); ax.text(x0 - 0.5 * m, y0 - 0.9 * m + 0.115 * size, "Z", color="#4d8dff", fontsize=8 * self._k, ha="center")
        if legend is not None: self._legend(legend, unit)
        self.cv.draw_idle()

    def _short(self, fmap): return " + ".join(f"{f:g} {k.split('@')[0]}" for k, f in fmap.items())

    def _bands(self, ax, shapes, vals, lines=False, n=12, rng=None):
        vals = np.asarray(vals, float); lo, hi = rng if rng else (float(vals.min()), float(vals.max()))
        if hi - lo < 1e-9: hi = lo + 1e-9
        bounds = np.linspace(lo, hi, n + 1); import matplotlib; cmap = matplotlib.colormaps["jet"].resampled(n); norm = mcolors.BoundaryNorm(bounds, n)
        if lines: ax.add_collection(LineCollection(shapes, array=vals, cmap=cmap, norm=norm, linewidths=2.4, zorder=5))
        else: ax.add_collection(PolyCollection(shapes, array=vals, cmap=cmap, norm=norm, edgecolors="face", linewidths=0.3, alpha=0.92, zorder=5))
        return cmap, norm, bounds

    def _legend(self, legend, unit):
        cmap, norm, bounds = legend; cax = self.fig.add_axes([0.915, 0.22, 0.014, 0.56])
        cb = self.fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, ticks=bounds, spacing="proportional")
        cb.ax.set_yticklabels([f"{v:,.2f}" for v in bounds]); cb.ax.tick_params(colors="#e8edf3", labelsize=7.5 * self._k, length=0); cb.outline.set_edgecolor("#55606c")


# ------------------------------------------------------------------ result tables
class Tables(W.QWidget):
    KINDS = ["Nodes", "Elements", "Static load cases", "Load combinations", "Displacements", "Reactions", "Beam forces"]
    def __init__(self, main):
        super().__init__(); self.main = main; v = W.QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4)
        h = W.QHBoxLayout(); self.cb = W.QComboBox(); self.cb.addItems(self.KINDS); self.note = W.QLabel(""); self.note.setStyleSheet("color:#6b7682;")
        b = W.QPushButton("Copy table"); b.clicked.connect(self.copy)
        h.addWidget(W.QLabel("Table")); h.addWidget(self.cb); h.addWidget(b); h.addWidget(self.note, 1); v.addLayout(h)
        self.t = W.QTableWidget(); self.t.setEditTriggers(W.QAbstractItemView.NoEditTriggers); self.t.setAlternatingRowColors(True); v.addWidget(self.t, 1)
        self.cb.currentIndexChanged.connect(self.fill)

    def copy(self):
        t = self.t; rows = ["\t".join(t.horizontalHeaderItem(c).text() for c in range(t.columnCount()))]
        rows += ["\t".join(t.item(r, c).text() if t.item(r, c) else "" for c in range(t.columnCount())) for r in range(t.rowCount())]
        W.QApplication.clipboard().setText("\n".join(rows)); self.main.msg(f"{self.cb.currentText()}: {t.rowCount()} rows copied to the clipboard")

    def fill(self, *_):
        mv = self.main.mv; b = mv.box
        if b is None: return
        kind = self.cb.currentText(); name, k_, fmap, maps = mv.current(); nodes = b.fr.nodes; els = b.fr.elements; note = ""
        member = {}
        for mname, ids in b.members.items():
            for e in ids: member[e] = mname
        for wc in b.wall_chains:
            for e in wc["els"]: member[e] = "wall" if wc["outer"] else "pier"
        if kind == "Nodes":
            hd = ["Node", "X (m)", "Z (m)", "Spring kz (kN/m/m)"]; rows = [(i + 1, f"{n.x:.4f}", f"{n.y:.4f}", f"{n.ky:,.0f}" if n.ky else "") for i, n in enumerate(nodes)]
        elif kind == "Elements":
            hd = ["Element", "Node i", "Node j", "Member", "Length (m)", "A (m²/m)", "I (m⁴/m)"]
            rows = [(i + 1, e.ni + 1, e.nj + 1, member.get(i, ""), f"{math.hypot(nodes[e.nj].x - nodes[e.ni].x, nodes[e.nj].y - nodes[e.ni].y):.4f}", f"{e.A:.4f}", f"{e.I:.6f}") for i, e in enumerate(els)]
        elif kind == "Static load cases":
            hd = ["No.", "Name", "Type", "Description"]; keys = list(STATIC) + b.hb_keys
            rows = [(i + 1, k.split("@")[0] if k in STATIC else k, "Dead" if k == "SW" else "Earth pressure" if k in ("EV", "EH") else "Live surcharge" if k.startswith("LS") else "Moving load (HB)", case_title(k).split(": ", 1)[1]) for i, k in enumerate(keys)]
        elif kind == "Load combinations":
            hd = ["No.", "Limit state", "Combination"]; rows = [(i + 1, ls, mv._short(c)) for i, (ls, c) in enumerate([("ULS", c) for c in mv.uls] + [("SLS", c) for c in mv.sls])]
        elif kind == "Displacements":
            u = -sum(f * b.u[k] for k, f in fmap.items()); hd = ["Node", "DX (mm)", "DZ (mm)", "RY (rad)"]; note = mv._short(fmap)
            rows = [(i + 1, f"{u[3 * i] * 1000:.4f}", f"{u[3 * i + 1] * 1000:.4f}", f"{u[3 * i + 2]:.6f}") for i in range(len(nodes))]
        elif kind == "Reactions":
            u = sum(f * b.u[k] for k, f in fmap.items()); hd = ["Node", "X (m)", "FZ (kN/m)", "Tributary (m)", "Pressure (kPa)"]; note = mv._short(fmap)
            rows = [(n + 1, f"{nodes[n].x:.3f}", f"{nodes[n].ky * u[3 * n + 1]:.3f}", f"{nodes[n]._trib:.3f}", f"{nodes[n].ky * u[3 * n + 1] / nodes[n]._trib:.2f}") for n in b.base_nodes]
            rows.append(("Σ", "", f"{sum(nodes[n].ky * u[3 * n + 1] for n in b.base_nodes):.3f}", "", ""))
        else:
            hd = ["Element", "Member", "End", "Axial (kN/m)", "Shear (kN/m)", "Moment (kNm/m)"]; rows = []
            if k_ == "env":
                hd = ["Element", "Member", "End", "N max", "N min", "V max", "V min", "M max", "M min"]; N = mv.end_values("N", maps); V = mv.end_values("V", maps); M = mv.end_values("M", maps); note = f"envelope of {len(maps)} combinations"
                for i in range(len(els)):
                    for j, end in enumerate("ij"): rows.append((i + 1, member.get(i, ""), end) + tuple(f"{a[q][i]:.2f}" for a in (N, V, M) for q in (j, j + 2)))
            else:
                N = mv.end_values("N", maps); V = mv.end_values("V", maps); M = mv.end_values("M", maps); note = mv._short(fmap)
                for i in range(len(els)):
                    for j, end in enumerate("ij"): rows.append((i + 1, member.get(i, ""), end, f"{N[j][i]:.2f}", f"{V[j][i]:.2f}", f"{M[j][i]:.2f}"))
        t = self.t; t.clear(); t.setColumnCount(len(hd)); t.setHorizontalHeaderLabels(hd); t.setRowCount(len(rows)); t.verticalHeader().setVisible(False)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                it = W.QTableWidgetItem(str(val)); it.setTextAlignment((QtCore.Qt.AlignLeft if c in (1, 3) and kind in ("Static load cases",) or (kind == "Load combinations" and c == 2) or (c == 1 and "Member" in hd) else QtCore.Qt.AlignRight) | QtCore.Qt.AlignVCenter); t.setItem(r, c, it)
        t.resizeColumnsToContents(); t.horizontalHeader().setStretchLastSection(True); self.note.setText("   " + note)


# ------------------------------------------------------------------ message window
class Messages(W.QTabWidget):
    def __init__(self):
        super().__init__(); self.setTabPosition(W.QTabWidget.South); self.cmd = self._pane(); self.ana = self._pane()
        self.addTab(self.cmd, "Command Message"); self.addTab(self.ana, "Analysis Message")
    def _pane(self):
        t = W.QTextEdit(); t.setReadOnly(True); t.setStyleSheet("QTextEdit{font:8.5pt 'DejaVu Sans Mono','Consolas';border:none;}"); return t
    def add(self, text, kind="info", pane="cmd"):
        col = {"info": INK, "ok": "#1e8449", "warn": "#b9770e", "bad": "#c0392b", "head": ACCENT}[kind]
        t = self.cmd if pane == "cmd" else self.ana
        t.append(f"<span style='color:#8a94a0'>{time.strftime('%H:%M:%S')}</span>&nbsp;&nbsp;<span style='color:{col}'>{text}</span>")
        t.verticalScrollBar().setValue(t.verticalScrollBar().maximum())


# ------------------------------------------------------------------ project files
def collect(main):
    out = {}
    for k, w in vars(main).items():
        if not k.startswith("i_"): continue
        out[k] = w.currentText() if isinstance(w, W.QComboBox) else w.value()
    out["use_ground"] = main.use_ground.isChecked()
    out["soil"] = [[(main.soil.item(r, c).text() if main.soil.item(r, c) else "") for c in range(main.soil.columnCount())] for r in range(main.soil.rowCount())]
    return out


def restore(main, data):
    for k, v in data.items():
        w = getattr(main, k, None)
        if k == "use_ground": main.use_ground.setChecked(bool(v))
        elif k == "soil":
            for r, row in enumerate(v[:main.soil.rowCount()]):
                for c, val in enumerate(row[:main.soil.columnCount()]): main.soil.setItem(r, c, W.QTableWidgetItem(str(val)))
        elif isinstance(w, W.QComboBox): w.setCurrentText(str(v))
        elif w is not None and k.startswith("i_"): w.setValue(type(w.value())(v))


def save_project(main, path):
    with open(path, "w", encoding="utf-8") as f: json.dump(dict(format="CBC project", version=1, inputs=collect(main)), f, indent=1)


def load_project(main, path):
    with open(path, encoding="utf-8") as f: data = json.load(f)
    if data.get("format") != "CBC project": raise ValueError("not a CBC project file")
    restore(main, data["inputs"])
