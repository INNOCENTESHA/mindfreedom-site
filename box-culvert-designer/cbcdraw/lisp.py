"""
A small AutoLISP interpreter - enough of the language to execute the CBC drawing
generator unchanged.  Faithful to the semantics the generator relies on:

  * one namespace for functions and variables, symbols are case-insensitive
  * DYNAMIC scoping (a callee sees and can setq the caller's locals)
  * integer vs real arithmetic, (/ 7 2) = 3
  * lists with dotted pairs, nil == empty list
  * rtos honours DIMZIN (trailing zero suppression)

Host objects (AutoCAD entities, COM objects) are opaque Python objects supplied
by the `host` passed to Interp; see acad.py.
"""
from __future__ import annotations
import math, os, re, functools
from decimal import Decimal, ROUND_HALF_UP


class LispError(Exception):
    pass


class LispExit(Exception):
    pass


class Sym:
    __slots__ = ("name",)
    _tab: dict = {}

    def __new__(cls, name):
        name = name.upper()
        s = cls._tab.get(name)
        if s is None:
            s = object.__new__(cls); s.name = name; cls._tab[name] = s
        return s

    def __repr__(self):
        return self.name


T = Sym("T")
QUOTE, LAMBDA, SLASH, DOT = Sym("QUOTE"), Sym("LAMBDA"), Sym("/"), Sym(".")


class Dotted:
    __slots__ = ("car", "cdr")

    def __init__(self, car, cdr):
        self.car = car; self.cdr = cdr

    def __repr__(self):
        return f"({self.car!r} . {self.cdr!r})"

    def __eq__(self, o):
        return isinstance(o, Dotted) and lequal(self.car, o.car) and lequal(self.cdr, o.cdr)

    def __hash__(self):
        return hash((repr(self.car), repr(self.cdr)))


class Lambda:
    __slots__ = ("params", "locals", "body", "name")

    def __init__(self, params, locs, body, name="lambda"):
        self.params = params; self.locals = locs; self.body = body; self.name = name

    def __repr__(self):
        return f"#<USUBR {self.name}>"


class Builtin:
    __slots__ = ("fn", "name")

    def __init__(self, fn, name):
        self.fn = fn; self.name = name

    def __repr__(self):
        return f"#<SUBR {self.name}>"


class CatchErr:
    def __init__(self, msg):
        self.msg = msg

    def __repr__(self):
        return f"#<%catch-all-apply-error% {self.msg}>"


class LFile:
    def __init__(self, fh, path, mode):
        self.fh = fh; self.path = path; self.mode = mode


# ----------------------------------------------------------------------------- reader
_TOK = re.compile(r'''\s+|;\|.*?\|;|;[^\n]*|(\()|(\))|(')|("(?:\\.|[^"\\])*")|([^\s()'";]+)''', re.S)
_INT = re.compile(r'^[+-]?\d+$')
_REAL = re.compile(r'^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$')
_ESC = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "e": "\x1b"}


def _unescape(s):
    out = []; i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in _ESC:
                out.append(_ESC[n]); i += 2; continue
            out.append("\\"); out.append(n); i += 2; continue     # unknown escape kept (e.g. \\P of MTEXT arrives as \P)
        out.append(c); i += 1
    return "".join(out)


def tokenize(src):
    pos = 0; n = len(src)
    while pos < n:
        m = _TOK.match(src, pos)
        if not m:
            raise LispError(f"reader: bad input at {pos}: {src[pos:pos+30]!r}")
        pos = m.end()
        if m.group(1): yield "("
        elif m.group(2): yield ")"
        elif m.group(3): yield "'"
        elif m.group(4) is not None: yield ("S", _unescape(m.group(4)[1:-1]))
        elif m.group(5) is not None: yield ("A", m.group(5))


def _atom(tok):
    if _INT.match(tok): return int(tok)
    if _REAL.match(tok): return float(tok)
    return Sym(tok)


def parse(src):
    """Return the list of top-level forms."""
    toks = list(tokenize(src)); i = 0

    def rd():
        nonlocal i
        t = toks[i]; i += 1
        if t == "(":
            items = []
            while True:
                if i >= len(toks): raise LispError("reader: unbalanced (")
                if toks[i] == ")":
                    i += 1; break
                items.append(rd())
            if len(items) == 3 and items[1] is DOT:
                return Dotted(items[0], items[2])
            if len(items) > 3 and items[-2] is DOT:          # (a b . c)
                return items[:-2] + [Dotted(None, items[-1])]
            return items or None
        if t == ")": raise LispError("reader: unexpected )")
        if t == "'": return [QUOTE, rd()]
        kind, v = t
        return v if kind == "S" else _atom(v)

    forms = []
    while i < len(toks):
        forms.append(rd())
    return forms


# ----------------------------------------------------------------------------- helpers
def lequal(a, b, fuzz=0.0):
    if a is b: return True
    if isinstance(a, bool) or isinstance(b, bool): return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= fuzz
    if isinstance(a, str) and isinstance(b, str): return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(lequal(x, y, fuzz) for x, y in zip(a, b))
    if isinstance(a, Dotted) and isinstance(b, Dotted):
        return lequal(a.car, b.car, fuzz) and lequal(a.cdr, b.cdr, fuzz)
    return a == b if type(a) is type(b) else False


def lst(x):
    """Python list or None (nil == empty list)."""
    return x if x else None


def truthy(x):
    return x is not None


def tsym(b):
    return T if b else None


def to_str(x):
    if x is None: return "nil"
    if isinstance(x, str): return x
    if isinstance(x, bool): return ":vlax-true" if x else ":vlax-false"
    if isinstance(x, int): return str(x)
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e15: return f"{x:.1f}"
        return repr(round(x, 12)).rstrip("0") if "e" not in repr(x) else repr(x)
    if isinstance(x, list): return "(" + " ".join(to_str(i) for i in x) + ")"
    return repr(x)


def wc_regex(pat):
    """AutoLISP wcmatch pattern -> compiled regex list (comma = alternatives)."""
    alts = []; cur = []; i = 0
    while i < len(pat):
        c = pat[i]
        if c == "`" and i + 1 < len(pat): cur.append(re.escape(pat[i + 1])); i += 2; continue
        if c == ",": alts.append("".join(cur)); cur = []; i += 1; continue
        if c == "#": cur.append(r"\d")
        elif c == "@": cur.append(r"[A-Za-z]")
        elif c == ".": cur.append(r"[^A-Za-z0-9]")
        elif c == "*": cur.append(".*")
        elif c == "?": cur.append(".")
        elif c == "[":
            j = pat.find("]", i + 1)
            if j < 0: cur.append(r"\[")
            else:
                body = pat[i + 1:j]
                if body.startswith("~"): body = "^" + body[1:]
                cur.append("[" + body.replace("\\", "\\\\") + "]"); i = j
        else: cur.append(re.escape(c))
        i += 1
    alts.append("".join(cur))
    return alts


def wcmatch(s, pat):
    for a in wc_regex(pat):
        neg = a.startswith("\\~") or a.startswith("~")
        body = a[2:] if a.startswith("\\~") else a[1:] if a.startswith("~") else a
        ok = re.fullmatch(body, s, re.S) is not None
        if ok != neg: return True
    return False


def rtos(x, mode=2, prec=4, dimzin=0):
    q = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-prec), rounding=ROUND_HALF_UP)
    s = f"{q:.{prec}f}"
    if prec > 0 and (dimzin & 8):
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", "-0.0", ""): s = "0"
    if (dimzin & 4) and s.startswith("0."): s = s[1:]
    if (dimzin & 4) and s.startswith("-0."): s = "-" + s[2:]
    return s


# ----------------------------------------------------------------------------- interpreter
class Interp:
    def __init__(self, host=None, search_dirs=(), log=None):
        self.globals: dict = {}
        self.frames: list = []
        self.host = host
        self.search_dirs = list(search_dirs)
        self.out: list = []                 # princ output
        self.caught: list = []              # errors swallowed by vl-catch-all-apply (reviewed in tests)
        self.sysvars: dict = {"DIMZIN": 0, "CMDECHO": 1}
        self.depth = 0
        self.names: list = []               # LISP call stack (diagnostics)
        self.log = log or (lambda s: None)
        self._lam_cache: dict = {}
        self.special = {n: getattr(self, "_sf_" + n.lower().replace("-", "_")) for n in
                        ("QUOTE", "SETQ", "DEFUN", "LAMBDA", "FUNCTION", "IF", "COND", "PROGN", "AND", "OR",
                         "WHILE", "REPEAT", "FOREACH", "VLAX-FOR")}
        _install_builtins(self)
        if host is not None:
            host.install(self)

    # -- environment (dynamic scoping)
    def lookup(self, name):
        for f in reversed(self.frames):
            if name in f: return f[name]
        return self.globals.get(name)

    def assign(self, name, val):
        for f in reversed(self.frames):
            if name in f:
                f[name] = val; return val
        self.globals[name] = val; return val

    def defbuiltin(self, name, fn):
        self.globals[name.upper()] = Builtin(fn, name.upper())

    # -- eval
    def eval(self, x):
        if isinstance(x, Sym):
            n = x.name
            if n == "T": return T
            if n == "NIL": return None
            if n == "PI": return math.pi
            if n == ":VLAX-TRUE": return True
            if n == ":VLAX-FALSE": return False
            v = self.lookup(n)
            if v is None and n not in self.globals and not any(n in f for f in self.frames) and n.startswith(("VLA-", "VLAX-", "AC")):
                return self.host.constant(n) if self.host else None
            return v
        if not isinstance(x, list):
            return x                         # numbers, strings, nil, host objects
        head = x[0]
        if isinstance(head, Sym):
            sf = self.special.get(head.name)
            if sf is not None: return sf(x)
            f = self.lookup(head.name)
            if f is None:
                f = self.host.resolve(head.name) if self.host else None
                if f is None: raise LispError(f"no function definition: {head.name}")
        else:
            f = self.eval(head)
        args = [self.eval(a) for a in x[1:]]
        return self.call(f, args, head)

    def tofn(self, f):
        if isinstance(f, (Lambda, Builtin)): return f
        if isinstance(f, Sym):
            v = self.lookup(f.name)
            if v is None and self.host: v = self.host.resolve(f.name)
            if v is None: raise LispError(f"no function definition: {f.name}")
            return self.tofn(v)
        if isinstance(f, list) and f and f[0] is LAMBDA:
            k = id(f); lam = self._lam_cache.get(k)
            if lam is None:
                lam = self._mklambda(f[1], f[2:], "lambda"); self._lam_cache[k] = lam
            return lam
        raise LispError(f"bad function: {to_str(f)}")

    def call(self, f, args, head=None):
        f = self.tofn(f)
        if isinstance(f, Builtin):
            return f.fn(*args)
        if len(args) != len(f.params):
            raise LispError(f"{'too few' if len(args) < len(f.params) else 'too many'} arguments: {f.name} "
                            f"expects {len(f.params)}, got {len(args)}")
        frame = dict.fromkeys(f.locals)
        frame.update(zip(f.params, args))
        self.frames.append(frame); self.depth += 1; self.names.append(f.name)
        if self.depth > 400: raise LispError("stack overflow")
        try:
            r = None
            for form in f.body: r = self.eval(form)
            return r
        except LispExit:
            raise
        except Exception as e:                              # remember where in the LISP program the error arose
            if not hasattr(e, "lstack"):
                e.lstack = list(self.names); e.lframe = {k: to_str(v)[:80] for k, v in frame.items()}
            raise
        finally:
            self.frames.pop(); self.depth -= 1; self.names.pop()

    def progn(self, forms):
        r = None
        for f in forms: r = self.eval(f)
        return r

    def _mklambda(self, plist, body, name):
        params, locs, seen = [], [], False
        for p in (plist or []):
            if p is SLASH: seen = True
            elif seen: locs.append(p.name)
            else: params.append(p.name)
        return Lambda(params, locs, body, name)

    # -- special forms
    def _sf_quote(self, x): return x[1]

    def _sf_function(self, x): return self.eval(x[1]) if isinstance(x[1], list) else x[1]

    def _sf_setq(self, x):
        v = None
        for i in range(1, len(x) - 1, 2):
            v = self.eval(x[i + 1]); self.assign(x[i].name, v)
        return v

    def _sf_defun(self, x):
        lam = self._mklambda(x[2], x[3:], x[1].name)
        self.assign(x[1].name, lam); return x[1]

    def _sf_lambda(self, x): return self._mklambda(x[1], x[2:], "lambda")

    def _sf_if(self, x):
        if self.eval(x[1]) is not None: return self.eval(x[2])
        return self.eval(x[3]) if len(x) > 3 else None

    def _sf_cond(self, x):
        for clause in x[1:]:
            if clause is None: continue
            v = self.eval(clause[0])
            if v is not None:
                return self.progn(clause[1:]) if len(clause) > 1 else v
        return None

    def _sf_progn(self, x): return self.progn(x[1:])

    def _sf_and(self, x):
        for a in x[1:]:
            if self.eval(a) is None: return None
        return T

    def _sf_or(self, x):
        for a in x[1:]:
            if self.eval(a) is not None: return T
        return None

    def _sf_while(self, x):
        r = None; n = 0
        while self.eval(x[1]) is not None:
            r = self.progn(x[2:]); n += 1
            if n > 2_000_000: raise LispError("while: runaway loop")
        return r

    def _sf_repeat(self, x):
        r = None
        for _ in range(int(self.eval(x[1]) or 0)): r = self.progn(x[2:])
        return r

    def _sf_foreach(self, x):
        name = x[1].name; seq = self.eval(x[2]) or []
        frame = {name: None}; self.frames.append(frame); r = None
        try:
            for item in list(seq):
                frame[name] = item; r = self.progn(x[3:])
        finally:
            self.frames.pop()
        return r

    def _sf_vlax_for(self, x):
        name = x[1].name; coll = self.eval(x[2])
        frame = {name: None}; self.frames.append(frame); r = None
        try:
            for item in list(self.host.iterate(coll)):
                frame[name] = item; r = self.progn(x[3:])
        finally:
            self.frames.pop()
        return r

    # -- files
    def resolve_path(self, path):
        """Map a (Windows) path from the generator to a local file, by file name."""
        if not isinstance(path, str): return None
        if os.path.exists(path): return path
        base = re.split(r"[\\/]", path)[-1]
        stem = os.path.splitext(base)[0].lower()
        for d in self.search_dirs:
            if not os.path.isdir(d): continue
            names = os.listdir(d)
            for n in names:
                if n.lower() == base.lower(): return os.path.join(d, n)
            for n in names:                                   # same picture, different extension
                if os.path.splitext(n)[0].lower() == stem and os.path.splitext(n)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                    if os.path.splitext(base)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                        return os.path.join(d, n)
        return None

    def load_file(self, path):
        p = self.resolve_path(path)
        if not p: raise LispError(f"LOAD failed: {path}")
        with open(p, encoding="utf-8", errors="replace") as f:
            src = f.read()
        r = None
        for form in parse(src): r = self.eval(form)
        return r

    def run(self, src):
        r = None
        for form in parse(src): r = self.eval(form)
        return r


# ----------------------------------------------------------------------------- builtins
def _num(x, who):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise LispError(f"bad argument type: numberp: {to_str(x)} ({who})")
    return x


def _install_builtins(I: Interp):
    D = I.defbuiltin

    def add(*a):
        for v in a: _num(v, "+")
        return sum(a)

    def sub(*a):
        for v in a: _num(v, "-")
        if len(a) == 1: return -a[0]
        r = a[0]
        for v in a[1:]: r -= v
        return r

    def mul(*a):
        r = 1
        for v in a: r *= _num(v, "*")
        return r

    def div(*a):
        for v in a: _num(v, "/")
        r = a[0]
        for v in a[1:]:
            if isinstance(r, int) and isinstance(v, int):
                if v == 0: raise LispError("divide by zero")
                q = abs(r) // abs(v); r = q if (r >= 0) == (v >= 0) else -q
            else:
                if v == 0: raise LispError("divide by zero")
                r = r / v
        return r

    def cmp(op):
        def f(*a):
            for x, y in zip(a, a[1:]):
                if x is None or y is None:
                    if op == "=" and x is y: continue
                    if op == "/=" and x is not y: continue
                    return None
                if isinstance(x, str) != isinstance(y, str):
                    if op == "/=": continue
                    return None
                if op == "=": ok = (x == y)
                elif op == "/=": ok = (x != y)
                elif isinstance(x, Sym) or isinstance(y, Sym): raise LispError(f"bad argument type for {op}: {to_str(x)} {to_str(y)}")
                elif op == "<": ok = x < y
                elif op == ">": ok = x > y
                elif op == "<=": ok = x <= y
                else: ok = x >= y
                if not ok: return None
            return T
        return f

    D("+", add); D("-", sub); D("*", mul); D("/", div)
    for op in ("=", "/=", "<", ">", "<=", ">="): D(op, cmp(op))
    D("1+", lambda x: _num(x, "1+") + 1); D("1-", lambda x: _num(x, "1-") - 1)
    D("ABS", lambda x: abs(_num(x, "abs")))
    D("MAX", lambda *a: (float(max(a)) if any(isinstance(v, float) for v in a) else max(a)))
    D("MIN", lambda *a: (float(min(a)) if any(isinstance(v, float) for v in a) else min(a)))
    D("FIX", lambda x: int(_num(x, "fix")))               # truncation toward zero
    D("FLOAT", lambda x: float(_num(x, "float")))
    D("SQRT", lambda x: math.sqrt(x)); D("SIN", math.sin); D("COS", math.cos)
    D("ATAN", lambda y, x=None: math.atan(y) if x is None else math.atan2(y, x))
    D("EXPT", lambda a, b: a ** b); D("EXP", math.exp); D("LOG", math.log)
    D("REM", lambda a, b: math.fmod(a, b) if isinstance(a, float) or isinstance(b, float) else int(math.fmod(a, b)))
    D("ZEROP", lambda x: tsym(x == 0)); D("MINUSP", lambda x: tsym(x < 0))
    D("NUMBERP", lambda x: tsym(isinstance(x, (int, float)) and not isinstance(x, bool)))
    D("NOT", lambda x: tsym(x is None)); D("NULL", lambda x: tsym(x is None))
    D("LISTP", lambda x: tsym(x is None or isinstance(x, (list, Dotted))))
    D("ATOM", lambda x: tsym(not isinstance(x, (list, Dotted))))
    D("BOUNDP", lambda s: tsym(I.lookup(s.name) is not None))
    D("EQ", lambda a, b: tsym(a is b or (type(a) is type(b) and isinstance(a, (int, float, str)) and a == b)
                              or (type(a) is type(b) and hasattr(a, "ent") and a == b)))
    D("EQUAL", lambda a, b, fuzz=0.0: tsym(lequal(a, b, fuzz)))

    # lists
    def car(x):
        if x is None: return None
        if isinstance(x, Dotted): return x.car
        if isinstance(x, list): return x[0]
        raise LispError(f"bad argument type: consp {to_str(x)}")

    def cdr(x):
        if x is None: return None
        if isinstance(x, Dotted): return x.cdr
        if isinstance(x, list):
            if len(x) == 2 and isinstance(x[1], Dotted) and x[1].car is None: return x[1].cdr
            return lst(x[1:])
        raise LispError(f"bad argument type: consp {to_str(x)}")

    D("CAR", car); D("CDR", cdr)
    import itertools
    for n in (2, 3, 4):
        for combo in itertools.product("AD", repeat=n):
            name = "C" + "".join(combo) + "R"
            def mk(combo=combo):
                def f(x):
                    for c in reversed(combo): x = car(x) if c == "A" else cdr(x)
                    return x
                return f
            D(name, mk())
    D("LIST", lambda *a: lst(list(a)))

    def cons(a, b):
        if b is None: return [a]
        if isinstance(b, list): return [a] + b
        return Dotted(a, b)
    D("CONS", cons)
    D("NTH", lambda n, l: (l[n] if l and 0 <= n < len(l) else None))
    D("LENGTH", lambda l: len(l) if l else 0)
    D("REVERSE", lambda l: lst(list(reversed(l))) if l else None)
    D("LAST", lambda l: l[-1] if l else None)

    def append(*ls):
        out = []
        for l in ls:
            if l: out.extend(l)
        return lst(out)
    D("APPEND", append)

    def assoc(k, al):
        for it in (al or []):
            if it is None: continue
            if lequal(car(it), k): return it
        return None
    D("ASSOC", assoc)

    def member(x, l):
        for i, it in enumerate(l or []):
            if lequal(it, x): return l[i:]
        return None
    D("MEMBER", member)
    D("SUBST", lambda new, old, l: lst([new if lequal(it, old) else it for it in (l or [])]))

    def mapcar(f, *ls):
        if any(l is None for l in ls): return None
        return lst([I.call(f, list(items)) for items in zip(*ls)])
    D("MAPCAR", mapcar)
    D("APPLY", lambda f, l: I.call(f, list(l or [])))
    D("EVAL", lambda x: I.eval(x))
    D("SET", lambda s, v: I.assign(s.name, v))
    D("VL-REMOVE-IF", lambda f, l: lst([x for x in (l or []) if I.call(f, [x]) is None]))
    D("VL-REMOVE-IF-NOT", lambda f, l: lst([x for x in (l or []) if I.call(f, [x]) is not None]))
    D("VL-REMOVE", lambda x, l: lst([y for y in (l or []) if not lequal(x, y)]))
    D("VL-POSITION", lambda x, l: next((i for i, y in enumerate(l or []) if lequal(x, y)), None))
    D("VL-MEMBER-IF", lambda f, l: next((l[i:] for i, y in enumerate(l or []) if I.call(f, [y]) is not None), None))
    D("VL-SOME", lambda f, l: next((T for y in (l or []) if I.call(f, [y]) is not None), None))
    D("VL-EVERY", lambda f, l: tsym(all(I.call(f, [y]) is not None for y in (l or []))))

    def _cmpkey(f):
        def c(a, b):
            if I.call(f, [a, b]) is not None: return -1
            if I.call(f, [b, a]) is not None: return 1
            return 0
        return functools.cmp_to_key(c)
    D("VL-SORT", lambda l, f: lst(sorted(l or [], key=_cmpkey(f))))
    def sort_i(l, f):
        """Indices that sort l.  Elements the comparison treats as equal come out in REVERSE original order,
        as AutoCAD's vl-sort-i returns them, e.g. (vl-sort-i '(1 1 1) '<) -> (2 1 0); the reference drawing
        confirms it (equal-sized views are packed last-first)."""
        l = l or []
        def c(a, b):
            if I.call(f, [l[a], l[b]]) is not None: return -1
            if I.call(f, [l[b], l[a]]) is not None: return 1
            return b - a                                    # tie: higher index first
        return lst(sorted(range(len(l)), key=functools.cmp_to_key(c)))
    D("VL-SORT-I", sort_i)

    # strings
    def strcat(*a):
        for s in a:
            if not isinstance(s, str): raise LispError(f"bad argument type: stringp {to_str(s)}")
        return "".join(a)
    D("STRCAT", strcat)
    D("STRLEN", lambda *a: sum(len(s) for s in a))

    def substr(s, start, n=None):
        if not isinstance(s, str): raise LispError(f"bad argument type: stringp {to_str(s)}")
        return s[start - 1:] if n is None else s[start - 1:start - 1 + n]
    D("SUBSTR", substr)
    D("STRCASE", lambda s, low=None: s.lower() if low is not None else s.upper())
    D("ITOA", lambda n: str(int(n)))

    def atoi(s):
        m = re.match(r"\s*[+-]?\d+", s); return int(m.group()) if m else 0

    def atof(s):
        m = re.match(r"\s*[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?)", s); return float(m.group()) if m else 0.0
    D("ATOI", atoi); D("ATOF", atof)
    D("RTOS", lambda x, mode=2, prec=None: rtos(_num(x, "rtos"), mode, 4 if prec is None else prec, int(I.sysvars.get("DIMZIN", 0))))
    D("CHR", lambda n: chr(n)); D("ASCII", lambda s: ord(s[0]))
    D("VL-STRING->LIST", lambda s: lst([ord(c) for c in s]))
    D("VL-LIST->STRING", lambda l: "".join(chr(c) for c in (l or [])))

    def vss(pat, s, start=0):
        i = s.find(pat, start or 0); return i if i >= 0 else None
    D("VL-STRING-SEARCH", vss)
    D("VL-STRING-TRIM", lambda chars, s: s.strip(chars))
    D("VL-STRING-RIGHT-TRIM", lambda chars, s: s.rstrip(chars))
    D("VL-STRING-LEFT-TRIM", lambda chars, s: s.lstrip(chars))
    D("VL-STRING-SUBST", lambda new, old, s, start=0: s[:start] + s[start:].replace(old, new, 1))
    D("WCMATCH", lambda s, p: tsym(wcmatch(s, p)))
    D("VL-PRINC-TO-STRING", to_str); D("VL-PRIN1-TO-STRING", lambda x: '"' + x + '"' if isinstance(x, str) else to_str(x))
    D("VL-SYMBOL-NAME", lambda s: s.name)
    D("READ", lambda s: (parse(s) or [None])[0])

    def typ(x):
        if x is None: return None
        if isinstance(x, bool): return Sym("SYM")
        if isinstance(x, int): return Sym("INT")
        if isinstance(x, float): return Sym("REAL")
        if isinstance(x, str): return Sym("STR")
        if isinstance(x, (list, Dotted)): return Sym("LIST")
        if isinstance(x, Sym): return Sym("SYM")
        if isinstance(x, Builtin): return Sym("SUBR")
        if isinstance(x, Lambda): return Sym("USUBR")
        if isinstance(x, LFile): return Sym("FILE")
        return I.host.typeof(x) if I.host else Sym("VLA-OBJECT")
    D("TYPE", typ)

    # output
    def princ(*a):
        if a: I.out.append(to_str(a[0]))
        return a[0] if a else None
    for n in ("PRINC", "PRINT", "PRIN1", "PROMPT"): D(n, princ)
    D("TERPRI", lambda: None)

    # geometry
    def angle(p, q):
        a = math.atan2(q[1] - p[1], q[0] - p[0]); return a + 2 * math.pi if a < 0 else a
    D("ANGLE", angle)
    D("DISTANCE", lambda p, q: math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q))))

    def polar(p, a, d):
        r = [p[0] + d * math.cos(a), p[1] + d * math.sin(a)]
        if len(p) > 2: r.append(p[2])
        return r
    D("POLAR", polar)

    # files / system
    def lopen(path, mode):
        mode = mode.lower()
        if mode == "r":
            p = I.resolve_path(path)
            if not p: return None
            return LFile(open(p, encoding="utf-8", errors="replace"), p, "r")
        return LFile(None, path, mode)                     # writes (the generator's log) go to the interpreter log

    def read_line(f):
        ln = f.fh.readline()
        return ln.rstrip("\r\n") if ln else None

    def write_line(s, f=None):
        I.log(s); return s

    def lclose(f):
        if f.fh: f.fh.close()
        return None
    D("OPEN", lopen); D("READ-LINE", read_line); D("WRITE-LINE", write_line); D("CLOSE", lclose)
    D("FINDFILE", lambda p: I.resolve_path(p))
    D("LOAD", lambda p, onfail=None: I.load_file(p))
    D("VL-FILENAME-DIRECTORY", lambda p: re.sub(r"[\\/][^\\/]*$", "", p))
    D("VL-FILENAME-BASE", lambda p: os.path.splitext(re.split(r"[\\/]", p)[-1])[0])
    D("VL-FILENAME-EXTENSION", lambda p: os.path.splitext(p)[1] or None)
    D("VL-MKDIR", lambda p: T); D("VL-LOAD-COM", lambda: None)
    D("VL-FILE-DELETE", lambda p: None)

    def getvar(n):
        n = n.upper()
        if n == "DATE": return 2460000.5
        if n == "MILLISECS": return 0
        return I.sysvars.get(n)

    def setvar(n, v):
        I.sysvars[n.upper()] = v; return v
    D("GETVAR", getvar); D("SETVAR", setvar)
    D("ALERT", lambda s: I.log("ALERT: " + s))

    def lexit(*a):
        raise LispExit("exit")
    D("EXIT", lexit); D("QUIT", lexit)
    D("GETFILED", lambda *a: None)
    D("GC", lambda: None)

    def catch_apply(f, args=None):
        try:
            return I.call(f, list(args or []))
        except LispExit:
            raise
        except Exception as e:                              # noqa: BLE001 - mirrors vl-catch-all-apply
            name = f.name if isinstance(f, (Sym, Lambda, Builtin)) else "lambda"
            I.caught.append((name, str(e)))
            return CatchErr(str(e))
    D("VL-CATCH-ALL-APPLY", catch_apply)
    D("VL-CATCH-ALL-ERROR-P", lambda x: tsym(isinstance(x, CatchErr)))
    D("VL-CATCH-ALL-ERROR-MESSAGE", lambda x: x.msg)
