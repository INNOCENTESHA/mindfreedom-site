"""
Stand-in for the AutoCAD object model used by the CBC drawing generator.

The generator talks to AutoCAD through entmake/entget/ssget and through the
ActiveX (vla-*, vlax-*) interface.  This module records what it creates:
layers, text / dimension styles, layouts and every entity, each with enough
geometry to answer GetBoundingBox (the generator's packing engine measures the
views it has drawn).

Nothing here draws; export.py turns the recorded document into DXF.
"""
from __future__ import annotations
import math, os, datetime
from .lisp import Sym, Dotted, LispError, T, lst, to_str, wcmatch, lequal
from . import metrics


def key(name):
    return str(name).upper()


class Obj:
    """Generic ActiveX-like object: properties in a dict, methods as m_<name>."""
    kind = "Object"

    _oid = 1000
    registry: dict = {}

    def __init__(self, doc=None, **props):
        self.doc = doc
        self.p = {key(k): v for k, v in props.items()}
        Obj._oid += 1; self.oid = Obj._oid; Obj.registry[self.oid] = self

    def get(self, name):
        k = key(name)
        g = getattr(self, "get_" + k.lower(), None)
        if g: return g()
        if k in self.p: return self.p[k]
        if self.doc is not None: self.doc.unknown.add(f"get {self.kind}.{name}")
        raise LispError(f"property not available: {self.kind}.{name}")

    def put(self, name, val):
        k = key(name)
        s = getattr(self, "put_" + k.lower(), None)
        if s: s(val)
        else: self.p[k] = val
        return None

    def method(self, name, *args):
        m = getattr(self, "m_" + key(name).lower(), None)
        if m is None:
            if self.doc is not None: self.doc.unknown.add(f"call {self.kind}.{name}")
            raise LispError(f"method not available: {self.kind}.{name}")
        return m(*args)

    def __repr__(self):
        return f"#<{self.kind} {self.p.get('NAME', '')}>"


class Collection(Obj):
    kind = "Collection"
    item_cls = Obj

    def __init__(self, doc, kind):
        super().__init__(doc); self.kind = kind; self.items = {}

    def m_add(self, name, *a):
        k = key(name)
        if k not in self.items:
            self.items[k] = self.make(name)
        return self.items[k]

    def make(self, name):
        o = Obj(self.doc, Name=name); o.kind = self.kind[:-1] if self.kind.endswith("s") else self.kind
        return o

    def m_item(self, name):
        if isinstance(name, int):
            vals = list(self.items.values())
            if 0 <= name < len(vals): return vals[name]
            raise LispError("index out of range")
        k = key(name)
        if k not in self.items: raise LispError(f"Key not found: {name}")
        return self.items[k]

    def get_count(self): return len(self.items)

    def m_load(self, name, file=None):                      # Linetypes.Load
        return self.m_add(name)

    def __iter__(self): return iter(list(self.items.values()))


class TextStyle(Obj):
    kind = "TextStyle"

    def m_setfont(self, typeface, bold, italic, charset, pitch):
        self.p["TYPEFACE"] = typeface; self.p["BOLD"] = bool(bold); self.p["ITALIC"] = bool(italic)

    def m_getfont(self, *a): return None


class TextStyles(Collection):
    def make(self, name):
        return TextStyle(self.doc, Name=name, Height=0.0, Width=1.0, Typeface="Arial")


class DimStyle(Obj):
    kind = "DimStyle"

    def m_copyfrom(self, src):
        self.p["VARS"] = {k: v for k, v in self.doc.interp.sysvars.items() if k.startswith("DIM")}


class DimStyles(Collection):
    def make(self, name):
        return DimStyle(self.doc, Name=name, Vars={})


class Layer(Obj):
    kind = "Layer"


class Layers(Collection):
    def make(self, name):
        return Layer(self.doc, Name=name, Color=7, Linetype="Continuous", Lineweight=-3, Plottable=True, Freeze=False, LayerOn=True)


# ----------------------------------------------------------------------------- entities
class Ent(Obj):
    """A drawing entity.  `t` is the DXF type; geometry lives in properties."""
    kind = "Entity"
    _n = 0

    def __init__(self, doc, t, space, **props):
        super().__init__(doc, **props)
        self.t = t; self.space = space; self.deleted = False
        Ent._n += 1; self.id = Ent._n
        self.p.setdefault("LAYER", "0")
        space.ents.append(self); doc.last = self

    # ---- generic properties
    def get_objectname(self):
        return {"LINE": "AcDbLine", "LWPOLYLINE": "AcDbPolyline", "CIRCLE": "AcDbCircle", "TEXT": "AcDbText",
                "MTEXT": "AcDbMText", "DIMENSION": "AcDbRotatedDimension" if self.p.get("DIMKIND") == "rotated" else "AcDbAlignedDimension",
                "MULTILEADER": "AcDbMLeader", "HATCH": "AcDbHatch", "ACAD_TABLE": "AcDbTable", "IMAGE": "AcDbRasterImage",
                "INSERT": "AcDbBlockReference", "VIEWPORT": "AcDbViewport", "SOLID": "AcDbTrace", "POINT": "AcDbPoint"}.get(self.t, "AcDb" + self.t.title())

    def get_handle(self): return f"{self.id + 0x100:X}"
    def get_objectid(self): return self.id
    def m_delete(self): self.deleted = True
    def m_update(self): return None
    def m_evaluate(self): return None
    def m_getobjectidstring(self, *a): return str(self.id)

    def m_getboundingbox(self, mn_sym, mx_sym):
        from .geom import bbox
        b = bbox(self)
        if b is None: raise LispError("GetBoundingBox: null extents")
        self.doc.interp.assign(mn_sym.name, [b[0], b[1], 0.0]); self.doc.interp.assign(mx_sym.name, [b[2], b[3], 0.0])
        return None

    def m_move(self, a, b):
        from .geom import move
        move(self, b[0] - a[0], b[1] - a[1]); return None

    def m_scaleentity(self, base, f):
        from .geom import scale
        scale(self, base, f); return None

    def __repr__(self):
        return f"<Entity name: {self.id:x} {self.t}>"

    # ---- hatch
    def m_appendouterloop(self, arr):
        self.p.setdefault("LOOPS", []).append(("outer", [_loop_points(o) for o in arr.items]))

    def m_appendinnerloop(self, arr):
        self.p.setdefault("LOOPS", []).append(("inner", [_loop_points(o) for o in arr.items]))

    # ---- mleader
    def m_setdoglegdirection(self, idx, vec):
        self.p["DOGLEGDIR"] = list(vec); self.p["DOG0"] = self.p.get("DOGLEGLENGTH", 0.0)   # length in force when flipped

    # ---- table
    def _cell(self, r, c): return self.p["CELLS"].setdefault((int(r), int(c)), {})
    def m_settext(self, r, c, s): self._cell(r, c)["text"] = s
    def m_gettext(self, r, c): return self._cell(r, c).get("text", "")
    def m_setcelltextheight(self, r, c, h): self._cell(r, c)["height"] = float(h)
    def m_setcelltextstyle(self, r, c, sty): self._cell(r, c)["style"] = sty
    def m_setcellalignment(self, r, c, a): self._cell(r, c)["align"] = a
    def m_setrowheight(self, r, h): self.p["ROWH"][int(r)] = float(h); self.p.setdefault("ROWSET", set()).add(int(r))
    def m_getrowheight(self, r):
        from .geom import table_rows
        return table_rows(self)[int(r)]
    def m_settextheight(self, rowtypes, h): self.p["DEFTEXTH"] = float(h)
    def m_settextstyle(self, rowtypes, sty): self.p["DEFSTYLE"] = sty
    def m_setalignment(self, rowtypes, a): self.p["DEFALIGN"] = a
    def m_generatelayout(self): return None
    def m_setcelltextheight2(self, *a): return None
    def m_setcolumnwidth(self, c, w): self.p["COLW"][int(c)] = float(w)
    def m_getcolumnwidth(self, c): return self.p["COLW"][int(c)]
    def m_mergecells(self, r0, r1, c0, c1): self.p["MERGES"].append((int(r0), int(r1), int(c0), int(c1)))
    def m_unmergecells(self, r0, r1, c0, c1):
        self.p["MERGES"] = [m for m in self.p["MERGES"] if m != (int(r0), int(r1), int(c0), int(c1))]
    def m_recomputetableblock(self, *a): return None
    def get_rows(self): return len(self.p["ROWH"])
    def get_columns(self): return len(self.p["COLW"])
    def get_height(self):
        if self.t == "ACAD_TABLE":
            from .geom import table_rows
            return sum(table_rows(self))
        return self.p.get("HEIGHT")
    def get_width(self):
        if self.t == "ACAD_TABLE": return sum(self.p["COLW"])
        return self.p.get("WIDTH")
    def get_measurement(self):
        a, b = self.p["P1"], self.p["P2"]
        if self.p.get("DIMKIND") == "rotated":
            ang = self.p.get("ROTATION", 0.0); d = (b[0] - a[0]) * math.cos(ang) + (b[1] - a[1]) * math.sin(ang)
            return abs(d) * self.p.get("LINEARSCALEFACTOR", 1.0)
        return math.dist(a[:2], b[:2]) * self.p.get("LINEARSCALEFACTOR", 1.0)
    def get_textposition(self):
        from .geom import dim_text_position
        return dim_text_position(self)
    def put_scalefactor(self, v):
        v = float(v)
        if self.t == "IMAGE":                               # a raster image is ScaleFactor wide, height in proportion
            w, h = self.p["PIXELS"]; self.p["IMAGEWIDTH"] = v; self.p["IMAGEHEIGHT"] = v * h / w
        self.p["SCALEFACTOR"] = v

    def get_imagewidth(self): return self.p["IMAGEWIDTH"]
    def get_imageheight(self): return self.p["IMAGEHEIGHT"]


def _loop_points(o):
    from .geom import outline
    return outline(o)


class EName:
    """An entity name (what entlast / ssname / entnext return).  Distinct from the ActiveX object,
    as in AutoCAD: (type ename) is ENAME, (type (vlax-ename->vla-object ename)) is VLA-OBJECT."""
    __slots__ = ("ent",)

    def __init__(self, ent): self.ent = ent
    def __eq__(self, o): return isinstance(o, EName) and o.ent is self.ent
    def __hash__(self): return hash(id(self.ent))
    def __repr__(self): return f"<Entity name: {self.ent.id:x}>"


def unwrap(x):
    return x.ent if isinstance(x, EName) else x


def wrap(e):
    return None if e is None else (e if isinstance(e, EName) else EName(e))


class SafeArray:
    def __init__(self, n): self.items = [None] * n


class Space(Obj):
    """A block table record: model space, a paper space layout block, or a block definition."""
    kind = "Block"

    def __init__(self, doc, name, layout=None):
        super().__init__(doc, Name=name); self.ents = []; self.layout = layout

    def live(self): return [e for e in self.ents if not e.deleted]
    def __iter__(self): return iter(self.live())
    def get_count(self): return len(self.live())

    def m_addline(self, a, b): return Ent(self.doc, "LINE", self, P1=list(a), P2=list(b))
    def m_addcircle(self, c, r): return Ent(self.doc, "CIRCLE", self, CENTER=list(c), RADIUS=float(r))

    def m_addtext(self, s, p, h):
        return Ent(self.doc, "TEXT", self, TEXTSTRING=s, INSERTIONPOINT=list(p), TEXTALIGNMENTPOINT=list(p), HEIGHT=float(h),
                   STYLENAME=self.doc.interp.sysvars.get("TEXTSTYLE", "Standard"), ALIGNMENT=0, ROTATION=0.0, SCALEFACTOR=1.0)

    def m_addmtext(self, p, w, s):
        return Ent(self.doc, "MTEXT", self, TEXTSTRING=s, INSERTIONPOINT=list(p), WIDTH=float(w), HEIGHT=2.5,
                   STYLENAME=self.doc.interp.sysvars.get("TEXTSTYLE", "Standard"), ATTACHMENTPOINT=1, ROTATION=0.0)

    def _dim(self, kind, p1, p2, loc, rot):
        v = {k: x for k, x in self.doc.interp.sysvars.items() if k.startswith("DIM")}
        return Ent(self.doc, "DIMENSION", self, DIMKIND=kind, P1=list(p1), P2=list(p2), LOC=list(loc), ROTATION=float(rot),
                   STYLENAME=self.doc.interp.sysvars.get("DIMSTYLE", "Standard"), LINEARSCALEFACTOR=float(v.get("DIMLFAC", 1.0)),
                   TEXTOVERRIDE="", LAYER=self.doc.clayer())

    def m_adddimrotated(self, p1, p2, loc, rot): return self._dim("rotated", p1, p2, loc, rot)
    def m_adddimaligned(self, p1, p2, loc): return self._dim("aligned", p1, p2, loc, 0.0)

    def m_addmleader(self, pts, idx=0):
        pts = [float(v) for v in pts]; P = [pts[i:i + 3] for i in range(0, len(pts), 3)]
        col = Obj(self.doc, ColorIndex=0); col.kind = "AcCmColor"
        return Ent(self.doc, "MULTILEADER", self, POINTS=P, TEXTSTRING="", CONTENTTYPE=2, TEXTHEIGHT=4.0, ARROWHEADSIZE=4.0,
                   DOGLEGLENGTH=8.0, LANDINGGAP=2.0, SCALEFACTOR=1.0, TEXTSTYLENAME="Standard", LAYER=self.doc.clayer(),
                   LEADERLINECOLOR=col, ARROWHEADTYPE=0, TEXTLEFTATTACHMENTTYPE=1, TEXTRIGHTATTACHMENTTYPE=1)

    def m_addhatch(self, ptype, name, assoc, *a):
        return Ent(self.doc, "HATCH", self, PATTERNTYPE=ptype, PATTERNNAME=name, ASSOCIATIVITY=bool(assoc), PATTERNSCALE=1.0,
                   PATTERNANGLE=0.0, LOOPS=[], LAYER=self.doc.clayer())

    def m_addtable(self, p, rows, cols, rowh, colw):
        return Ent(self.doc, "ACAD_TABLE", self, INSERTIONPOINT=list(p), ROWH=[float(rowh)] * int(rows), COLW=[float(colw)] * int(cols),
                   CELLS={}, MERGES=[], LAYER=self.doc.clayer(), STYLENAME="Standard", VERTCELLMARGIN=1.5, HORZCELLMARGIN=1.5,
                   TITLESUPPRESSED=False, HEADERSUPPRESSED=False, REGENERATETABLESUPPRESSED=False)

    def m_addraster(self, path, p, scale, rot):
        local = self.doc.interp.resolve_path(path)
        if not local: raise LispError(f"image file not found: {path}")
        w, h = metrics.image_size(local)
        # AutoCAD: the image is inserted 1 unit wide x scalefactor, height in proportion
        return Ent(self.doc, "IMAGE", self, IMAGEFILE=path, LOCALFILE=local, ORIGIN=list(p), SCALEFACTOR=float(scale), ROTATION=float(rot),
                   PIXELS=(w, h), IMAGEWIDTH=float(scale), IMAGEHEIGHT=float(scale) * h / w, LAYER=self.doc.clayer())

    def m_addpviewport(self, c, w, h):
        return Ent(self.doc, "VIEWPORT", self, CENTER=list(c), WIDTH=float(w), HEIGHT=float(h), CUSTOMSCALE=1.0, VIEWPORTON=True,
                   DISPLAYLOCKED=False, TARGET=[0.0, 0.0, 0.0], VIEWCENTER=[0.0, 0.0], DIRECTION=[0.0, 0.0, 1.0], TWISTANGLE=0.0,
                   LAYER=self.doc.clayer())

    def m_item(self, i): return self.live()[i]


def _vp_display(self, on): self.p["VIEWPORTON"] = bool(on)
Ent.m_display = _vp_display


class Layout(Obj):
    kind = "Layout"

    def __init__(self, doc, name, taborder):
        super().__init__(doc, Name=name, TabOrder=taborder, ConfigName="None", CanonicalMediaName="", PaperUnits=1, PlotRotation=0,
                         PlotType=1, StandardScale=16, CenterPlot=False, StyleSheet="", ShowPlotStyles=False)
        self.block = Space(doc, "*Model_Space" if key(name) == "MODEL" else f"*Paper_Space{taborder}", layout=self)

    def get_block(self): return self.block

    def put_name(self, name):
        items = self.doc.layouts.items
        for k, v in list(items.items()):
            if v is self: del items[k]
        if key(name) in items: raise LispError(f"layout name already in use: {name}")
        items[key(name)] = self; self.p["NAME"] = name

    def m_refreshplotdeviceinfo(self): return None
    def m_setcustomscale(self, a, b): self.p["CUSTOMSCALE"] = (a, b)
    def m_delete(self): self.doc.layouts.items.pop(key(self.p["NAME"]), None)
    def m_copyfrom(self, src): return None


class Layouts(Collection):
    def make(self, name):
        return Layout(self.doc, name, len(self.items))


class Document(Obj):
    kind = "Document"

    def __init__(self, interp=None):
        super().__init__(None, Name="Drawing1.dwg", FullName="Drawing1.dwg")
        self.doc = self; self.interp = interp; self.unknown = set(); self.last = None; self.commands = []
        self.layers = Layers(self, "Layers"); self.layers.m_add("0")
        self.textstyles = TextStyles(self, "TextStyles"); self.textstyles.m_add("Standard")
        self.dimstyles = DimStyles(self, "DimStyles"); self.dimstyles.m_add("Standard")
        self.linetypes = Collection(self, "Linetypes")
        self.layouts = Layouts(self, "Layouts")
        self.model_layout = self.layouts.m_add("Model")
        self.layouts.m_add("Layout1")
        self.active_layout = self.model_layout
        self.blocks = {}                                     # block definitions (entmake BLOCK ... ENDBLK)
        self._blk = None
        self.summary = Obj(self); self.summary.kind = "SummaryInfo"; self.summary.custom = {}
        self.summary.m_addcustominfo = lambda k, v: self.summary.custom.__setitem__(k, v)
        self.summary.m_setcustombykey = lambda k, v: self.summary.custom.__setitem__(k, v)
        self.summary.m_getcustombykey = lambda k, sym: self._getcustom(k, sym)
        self.plot = Obj(self); self.plot.kind = "Plot"
        self.plot.m_plottofile = lambda *a: T
        self.utility = Obj(self); self.utility.kind = "Utility"
        self.utility.m_getobjectidstring = lambda o, flag=False: str(o.oid)

    def _getcustom(self, k, sym):
        if k not in self.summary.custom: raise LispError("key not found")
        self.interp.assign(sym.name, self.summary.custom[k])

    @property
    def model(self): return self.model_layout.block

    def clayer(self): return self.interp.sysvars.get("CLAYER", "0")

    def spaces(self):
        for lay in self.layouts: yield lay.block

    def all_ents(self):
        for sp in self.spaces():
            for e in sp.live(): yield e

    def current_space(self): return self.active_layout.block

    def get_layers(self): return self.layers
    def get_textstyles(self): return self.textstyles
    def get_dimstyles(self): return self.dimstyles
    def get_linetypes(self): return self.linetypes
    def get_layouts(self): return self.layouts
    def get_modelspace(self): return self.model
    def get_paperspace(self):
        return self.active_layout.block if self.active_layout is not self.model_layout else list(self.layouts)[1].block
    def get_activelayout(self): return self.active_layout
    def put_activelayout(self, lay): self.active_layout = lay; self.interp.sysvars["CTAB"] = lay.p["NAME"]
    def get_activespace(self): return 1 if self.active_layout is self.model_layout else 0
    def put_activespace(self, v): self.p["ACTIVESPACE"] = v
    def put_mspace(self, v): self.p["MSPACE"] = v
    def get_summaryinfo(self): return self.summary
    def get_plot(self): return self.plot
    def get_utility(self): return self.utility
    def get_blocks(self): raise LispError("Blocks collection not available")
    def m_startundomark(self): return None
    def m_endundomark(self): return None
    def m_regen(self, *a): return None
    def m_save(self): return None
    def m_saveas(self, *a): return None
    def m_copyfrom(self, *a): return None                    # DimStyle.CopyFrom(doc) handled on DimStyle


class App(Obj):
    kind = "Application"

    def get_activedocument(self): return self.doc
    def m_zoomextents(self): return None
    def m_zoomcenter(self, *a): return None
    def m_update(self): return None


CONSTANTS = {"VLAX-VBOBJECT": 9, "VLAX-VBDOUBLE": 5, "VLAX-VBSTRING": 8, "VLAX-VBINTEGER": 2, "VLAX-VBLONG": 3, "VLAX-VBVARIANT": 12,
             "ACMODELSPACE": 1, "ACPAPERSPACE": 0}


class Host:
    """Binds the document to the interpreter: entmake/ssget/... and the vla-/vlax- interface."""

    def __init__(self):
        self.doc = None; self.app = None

    def install(self, I):
        self.I = I
        self.doc = Document(I); self.app = App(self.doc)
        D = I.defbuiltin
        doc = self.doc
        D("VLAX-GET-ACAD-OBJECT", lambda: self.app)
        D("VLAX-3D-POINT", lambda *a: [float(v) for v in (a[0] if len(a) == 1 else a)])
        D("VLAX-ENAME->VLA-OBJECT", lambda e: unwrap(e))
        D("VLAX-VLA-OBJECT->ENAME", lambda o: wrap(o))
        D("VLAX-VARIANT-VALUE", lambda v: v)
        D("VLAX-MAKE-VARIANT", lambda v=None, t=None: v)
        D("VLAX-SAFEARRAY->LIST", lambda a: lst(list(a.items)) if isinstance(a, SafeArray) else a)
        D("VLAX-MAKE-SAFEARRAY", lambda t, dims, *more: SafeArray(int(dims.cdr) - int(dims.car) + 1))
        D("VLAX-SAFEARRAY-PUT-ELEMENT", lambda a, i, v: a.items.__setitem__(int(i), v))
        D("VLAX-SAFEARRAY-FILL", lambda a, l: setattr(a, "items", list(l)) or a)
        D("VLAX-RELEASE-OBJECT", lambda o: None)
        D("VLAX-GET", lambda o, p: self._obj(o).get(self._nm(p)))
        D("VLAX-PUT", lambda o, p, v: self._obj(o).put(self._nm(p), v))
        D("VLAX-GET-PROPERTY", lambda o, p, *a: self._obj(o).get(self._nm(p)) if not a else self._obj(o).method(self._nm(p), *a))
        D("VLAX-PUT-PROPERTY", lambda o, p, *a: self._obj(o).put(self._nm(p), a[-1]))
        D("VLAX-INVOKE", lambda o, m, *a: self._obj(o).method(self._nm(m), *a))
        D("VLAX-INVOKE-METHOD", lambda o, m, *a: self._obj(o).method(self._nm(m), *a))

        def no_com(*a): raise LispError("Automation server not available (running outside AutoCAD / Excel)")
        D("VLAX-GET-OBJECT", no_com); D("VLAX-CREATE-OBJECT", no_com); D("VLAX-GET-OR-CREATE-OBJECT", no_com)
        D("VLAX-ERASED-P", lambda o: T if getattr(o, "deleted", False) else None)
        D("VLAX-METHOD-APPLICABLE-P", lambda o, m: T if hasattr(o, "m_" + self._nm(m).lower()) else None)
        D("VLAX-PROPERTY-AVAILABLE-P", lambda o, p, *a: T if (key(self._nm(p)) in o.p or hasattr(o, "get_" + self._nm(p).lower())) else None)

        D("ENTMAKE", self.entmake); D("ENTMAKEX", self.entmake)
        D("ENTLAST", lambda: wrap(doc.last))
        D("ENTGET", self.entget)
        D("ENTDEL", lambda e: setattr(unwrap(e), "deleted", not unwrap(e).deleted) or e)
        D("ENTNEXT", self.entnext)
        D("ENTMOD", self.entmod); D("ENTUPD", lambda e: e)
        D("SSGET", self.ssget)
        D("SSNAME", lambda ss, i: wrap(ss[int(i)]) if ss and 0 <= int(i) < len(ss) else None)
        D("SSLENGTH", lambda ss: len(ss) if ss else 0)
        D("TBLSEARCH", self.tblsearch)
        D("COMMAND", self.command); D("VL-CMDF", self.command)
        D("MENUCMD", lambda s: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        D("HANDENT", lambda h: None)
        D("REDRAW", lambda *a: None); D("GRAPHSCR", lambda: None); D("TEXTSCR", lambda: None)
        I.sysvars.update(CLAYER="0", CTAB="Model", TEXTSTYLE="Standard", DIMSTYLE="Standard", LAYOUTCREATEVIEWPORT=1,
                         DWGPREFIX="", DWGNAME="Drawing1.dwg", TILEMODE=1, LUNITS=2, LUPREC=4)

    # -- interpreter hooks
    def _nm(self, p): return p.name if isinstance(p, Sym) else str(p)

    def _obj(self, o):
        o = unwrap(o)
        if not isinstance(o, Obj): raise LispError(f"bad argument type: VLA-OBJECT {to_str(o)}")
        return o

    def resolve(self, name):
        from .lisp import Builtin
        if name.startswith("VLA-GET-"):
            prop = name[8:]; return Builtin(lambda o, *a: self._obj(o).get(prop), name)
        if name.startswith("VLA-PUT-"):
            prop = name[8:]; return Builtin(lambda o, v: self._obj(o).put(prop, v), name)
        if name.startswith("VLA-"):
            meth = name[4:]; return Builtin(lambda o, *a: self._obj(o).method(meth, *a), name)
        return None

    def constant(self, name):
        if name in CONSTANTS: return CONSTANTS[name]
        if name.startswith("AC"): return Sym(name)          # enum constants kept symbolic
        return None

    def iterate(self, coll):
        if isinstance(coll, (Collection, Space)): return list(coll)
        raise LispError(f"vlax-for: not a collection: {to_str(coll)}")

    def typeof(self, x):
        if isinstance(x, EName): return Sym("ENAME")
        if isinstance(x, SafeArray): return Sym("SAFEARRAY")
        if isinstance(x, list): return Sym("LIST")
        return Sym("VLA-OBJECT")

    # -- entmake & friends
    def entmake(self, groups=None):
        doc = self.doc
        if not groups: return None
        g = {}
        multi = {}
        for it in groups:
            if isinstance(it, Dotted): c, v = it.car, it.cdr
            else: c, v = it[0], list(it[1:])
            multi.setdefault(c, []).append(v)
            g.setdefault(c, v)
        t = g.get(0)
        if t == "BLOCK":
            doc._blk = Space(doc, g.get(2)); doc._blk.p["BASE"] = g.get(10, [0.0, 0.0, 0.0]); return groups
        if t == "ENDBLK":
            doc.blocks[key(doc._blk.p["NAME"])] = doc._blk; doc._blk = None; return groups
        space = doc._blk if doc._blk is not None else doc.current_space()
        if 410 in g:
            space = doc.layouts.m_item(g[410]).block
        layer = g.get(8, doc.clayer())
        if key(layer) not in doc.layers.items: doc.layers.m_add(layer)
        last = doc.last
        if t == "LINE":
            e = Ent(doc, t, space, P1=g[10], P2=g[11])
        elif t == "LWPOLYLINE":
            # vertex groups arrive in order: 10 then optional 40/41/42 belonging to that vertex
            verts = []; cw = None
            for it in groups:
                c, v = (it.car, it.cdr) if isinstance(it, Dotted) else (it[0], list(it[1:]))
                if c == 10: verts.append({"p": [float(v[0]), float(v[1])], "sw": None, "ew": None, "b": 0.0})
                elif c == 40 and verts: verts[-1]["sw"] = float(v)
                elif c == 41 and verts: verts[-1]["ew"] = float(v)
                elif c == 42 and verts: verts[-1]["b"] = float(v)
                elif c == 43: cw = float(v)
            e = Ent(doc, t, space, VERTS=verts, CLOSED=bool(int(g.get(70, 0)) & 1), CONSTWIDTH=cw)
        elif t == "CIRCLE":
            e = Ent(doc, t, space, CENTER=g[10], RADIUS=float(g[40]))
        elif t == "ARC":
            e = Ent(doc, t, space, CENTER=g[10], RADIUS=float(g[40]), A0=float(g[50]), A1=float(g[51]))
        elif t == "TEXT":
            e = Ent(doc, t, space, TEXTSTRING=g.get(1, ""), INSERTIONPOINT=g[10], TEXTALIGNMENTPOINT=g.get(11, g[10]), HEIGHT=float(g[40]),
                    STYLENAME=g.get(7, "Standard"), ROTATION=float(g.get(50, 0.0)), SCALEFACTOR=float(g.get(41, 1.0)),
                    JH=int(g.get(72, 0)), JV=int(g.get(73, 0)))
        elif t == "SOLID":
            e = Ent(doc, t, space, PTS=[g[10], g[11], g[12], g.get(13, g[12])])
        elif t == "POINT":
            e = Ent(doc, t, space, P1=g[10])
        elif t == "INSERT":
            e = Ent(doc, t, space, NAME=g[2], INSERTIONPOINT=g[10], XSCALE=float(g.get(41, 1.0)), YSCALE=float(g.get(42, 1.0)),
                    ROTATION=float(g.get(50, 0.0)))
        elif t == "MTEXT":
            e = Ent(doc, t, space, TEXTSTRING="".join(multi.get(3, [])) + g.get(1, ""), INSERTIONPOINT=g[10], WIDTH=float(g.get(41, 0.0)),
                    HEIGHT=float(g.get(40, 2.5)), STYLENAME=g.get(7, "Standard"), ATTACHMENTPOINT=int(g.get(71, 1)), ROTATION=float(g.get(50, 0.0)))
        else:
            raise LispError(f"entmake: entity type not supported: {t}")
        e.p["LAYER"] = layer
        if 62 in g: e.p["COLOR"] = int(g[62])
        if 6 in g: e.p["LINETYPE"] = g[6]
        if 370 in g: e.p["LINEWEIGHT"] = int(g[370])
        if 48 in g: e.p["LTSCALE"] = float(g[48])
        e.groups = groups
        if doc._blk is not None: doc.last = last           # block members are not "entlast" of the drawing
        return groups

    def entget(self, e, *a):
        e = unwrap(e)
        if e is None: raise LispError("bad argument type: lentityp nil")
        if e.deleted: return None                           # an erased entity has no data
        out = [Dotted(-1, EName(e)), Dotted(0, e.t), Dotted(8, e.p.get("LAYER", "0")),
               Dotted(410, e.space.layout.p["NAME"] if e.space.layout else "Model")]
        p = e.p
        if e.t == "LINE": out += [[10] + list(p["P1"]), [11] + list(p["P2"])]
        elif e.t == "LWPOLYLINE":
            out += [Dotted(90, len(p["VERTS"])), Dotted(70, 1 if p["CLOSED"] else 0)]
            for v in p["VERTS"]: out += [[10] + v["p"], Dotted(42, v["b"])]
        elif e.t == "CIRCLE": out += [[10] + list(p["CENTER"]), Dotted(40, p["RADIUS"])]
        elif e.t == "TEXT":
            out += [[10] + list(p["INSERTIONPOINT"]), [11] + list(p["TEXTALIGNMENTPOINT"]), Dotted(40, p["HEIGHT"]), Dotted(1, p["TEXTSTRING"]),
                    Dotted(7, p["STYLENAME"]), Dotted(50, p.get("ROTATION", 0.0)), Dotted(41, p.get("SCALEFACTOR", 1.0)),
                    Dotted(72, p.get("JH", 0)), Dotted(73, p.get("JV", 0))]
        elif e.t == "MTEXT":
            out += [[10] + list(p["INSERTIONPOINT"]), Dotted(40, p["HEIGHT"]), Dotted(41, p["WIDTH"]), Dotted(1, p["TEXTSTRING"]),
                    Dotted(7, p["STYLENAME"]), Dotted(71, p.get("ATTACHMENTPOINT", 1))]
        elif e.t == "INSERT": out += [Dotted(2, p["NAME"]), [10] + list(p["INSERTIONPOINT"])]
        elif e.t == "VIEWPORT":
            # 12 = view centre (DCS), 17 = view target: the model point seen at the viewport centre is target + centre
            out += [[10] + list(p["CENTER"]), Dotted(40, p["WIDTH"]), Dotted(41, p["HEIGHT"]), Dotted(69, 2),
                    [12] + list(p["VIEWCENTER"]), [17] + list(p["TARGET"]), Dotted(45, p["HEIGHT"] / float(p.get("CUSTOMSCALE", 1.0) or 1.0))]
        return out

    def entmod(self, groups):
        e = None; g = {}
        for it in groups:
            if isinstance(it, Dotted):
                if it.car == -1: e = unwrap(it.cdr)
                g[it.car] = it.cdr
            else: g[it[0]] = list(it[1:])
        if e is None: raise LispError("entmod: no entity name")
        if 8 in g: e.p["LAYER"] = g[8]
        if e.t == "TEXT":
            for c, k in ((1, "TEXTSTRING"), (40, "HEIGHT"), (10, "INSERTIONPOINT"), (11, "TEXTALIGNMENTPOINT"), (7, "STYLENAME"),
                         (50, "ROTATION"), (41, "SCALEFACTOR"), (72, "JH"), (73, "JV")):
                if c in g: e.p[k] = g[c]
        elif e.t == "LINE":
            if 10 in g: e.p["P1"] = g[10]
            if 11 in g: e.p["P2"] = g[11]
        elif e.t == "MTEXT":
            for c, k in ((1, "TEXTSTRING"), (40, "HEIGHT"), (41, "WIDTH"), (10, "INSERTIONPOINT")):
                if c in g: e.p[k] = g[c]
        return groups

    def entnext(self, e=None):
        ents = self.doc.model.live()
        if e is None: return wrap(ents[0]) if ents else None
        e = unwrap(e); sp = e.space.ents
        try:
            i = sp.index(e)
        except ValueError:
            return None
        for n in sp[i + 1:]:
            if not n.deleted: return EName(n)
        return None

    def ssget(self, mode=None, flt=None, *more):
        if not isinstance(mode, str) or key(mode) not in ("_X", "X"):
            raise LispError("ssget: only the \"_X\" (whole database) mode is available")
        ents = [e for e in self.doc.all_ents() if self._match(e, flt or [])]
        return ents or None

    def _match(self, e, flt):
        def val(c):
            if c == 0: return e.t
            if c == 8: return e.p.get("LAYER", "0")
            if c == 410: return e.space.layout.p["NAME"] if e.space.layout else "Model"
            if c == 2: return e.p.get("NAME", "")
            if c == 7: return e.p.get("STYLENAME", "")
            return None

        def test(it):
            c, v = it.car, it.cdr
            cur = val(c)
            if cur is None: return False
            return wcmatch(key(cur), key(v)) if isinstance(v, str) else lequal(cur, v)

        def group(i, op):
            res = []
            while i < len(flt):
                it = flt[i]
                if isinstance(it, Dotted) and it.car == -4:
                    tag = key(it.cdr)
                    if tag.startswith("<"):
                        r, i = group(i + 1, tag[1:]); res.append(r); continue
                    return (comb(res, op), i + 1)
                res.append(test(it)); i += 1
            return (comb(res, op), i)

        def comb(res, op):
            if op == "OR": return any(res)
            if op == "NOT": return not all(res)
            if op == "XOR": return sum(res) == 1
            return all(res)
        return group(0, "AND")[0]

    def tblsearch(self, table, name, *a):
        t = key(table); k = key(name)
        if t == "BLOCK": return [Dotted(0, "BLOCK"), Dotted(2, name)] if k in self.doc.blocks else None
        coll = {"LAYER": self.doc.layers, "STYLE": self.doc.textstyles, "DIMSTYLE": self.doc.dimstyles, "LTYPE": self.doc.linetypes}.get(t)
        if coll is None: return None
        return [Dotted(0, t), Dotted(2, name)] if k in coll.items else None

    def command(self, *args):
        self.doc.commands.append(args); return None
