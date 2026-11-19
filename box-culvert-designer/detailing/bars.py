"""
Bars as they are made and delivered.

No bar in the schedule may exceed what a mill and a bending shop supply:
  * length     <= 12 m stock (BS 4449 / EN 10080 standard stock length);
  * diameter   one of the preferred sizes 8 10 12 16 20 25 32 40 mm;
  * strength   a ribbed weldable grade with 400 <= fyk <= 600 MPa (EN 1992-1-1 3.2.2(3)), B500 or the older 460;
  * bent shape fits a 2750 mm wide lorry load (BS 8666: the shorter side of the enclosing rectangle).

A run longer than the stock length is cut into pieces that lap.  Alternate bars form two families (A, B) whose
lap centres are at least 1.3 l0 apart, so that not more than half of the bars lap at any section (8.7.2(3)).  Top bars
are lapped at mid-span only and bottom bars over the supports only (see `zones`).
"""
from __future__ import annotations
import math
from . import ec2

STOCK = 12000.0
SIZES = (8, 10, 12, 16, 20, 25, 32, 40)
GRADES = {460: "grade 460 (BS 4449:1997)", 500: "B500 (BS 4449:2005 / EN 10080)"}
TRANSPORT = 2750.0


def mass_per_m(dia: float) -> float:
    return math.pi * dia * dia / 4.0 * 7850e-6


def plen(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def sub(pts, s0: float, s1: float):
    """Part of a polyline between the developed stations s0 and s1."""
    out = []; s = 0.0
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b); e = s + L
        if e > s0 - 1e-9 and s < s1 + 1e-9 and L > 0:
            t0 = max(0.0, (s0 - s) / L); t1 = min(1.0, (s1 - s) / L)
            p = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0); q = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if not out or math.dist(out[-1], p) > 1e-6: out.append(p)
            if math.dist(out[-1], q) > 1e-6: out.append(q)
        s = e
    return out


def developed(pts, dia: float) -> float:
    """Cutting length: centre-line legs less the saving at each bend (BS 8666 former radius), rounded up to 25 mm."""
    r = ec2.bs8666_former_radius(dia) + dia / 2.0; L = plen(pts)
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
        ang = abs(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]))
        if ang > 1e-6: L -= 2.0 * r * math.tan(ang / 2.0) - r * ang
    return math.ceil(L / 25.0 - 1e-9) * 25.0


def shape_code(pts) -> str:
    """BS 8666 shape code of a planar bar from its legs."""
    n = len(pts) - 1
    if n <= 1: return "00"
    angs = []
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
        angs.append(math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1])))
    right = all(abs(abs(a) - 90) < 1 for a in angs)
    if n == 2: return "11" if right else "15"
    if n == 3:
        same = angs[0] * angs[1] > 0
        if right: return "21" if same else "26"
        return "25" if same else "26"
    return "99"


def enclosing(pts) -> tuple:
    """Sides of the smallest axis-aligned rectangle round the bar in its own plane (long, short)."""
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; a, b = max(xs) - min(xs), max(ys) - min(ys)
    return (max(a, b), min(a, b))


# ------------------------------------------------------------------ laps in a long run
def zones(P: dict, layer: str) -> list:
    """Stations x (across the section, 0 = centre line) where a transverse slab bar may be lapped, with the half-width
    available.  The rule is by position, for both slabs:
      * top reinforcement is never lapped at or near a support: the whole lap lies in the middle 60 % of a cell;
      * bottom reinforcement is never lapped at or near mid-span: the whole lap lies over a pier, clear of the
        middle 40 % of the cells either side."""
    nc = int(round(P["N_CELLS"])); sw, ti, wc = P["SPAN_W"], P["T_INWALL"], P["W_CLEAR"]; out = []
    if layer == "top":
        for j in range(nc): out.append((-wc / 2.0 + j * (sw + ti) + sw / 2.0, 0.30 * sw))            # clear of the fifth of the span next to each support
    else:
        for j in range(1, nc): out.append((-wc / 2.0 + j * sw + (j - 1) * ti + ti / 2.0, ti / 2.0 + 0.30 * sw))   # clear of the middle 40 % of each span
    return out


LAYER = {"01": "top", "02": "bottom", "03": "bottom", "04": "top"}      # top slab top / base bottom / top slab bottom / base top


def split(pts, l0: float, stock: float = STOCK, prefer=None, min_piece: float = 0.0):
    """Cut a bar longer than the stock length into lapping pieces, in two alternating families.

    prefer: [(station on the developed length, half-width)] of the low-stress zones.
    Returns None when no cut is needed, else dict(A=[centres], B=[centres], pieces_A, pieces_B, stagger, preferred, ok)
    with pieces as (s0, s1) on the developed length."""
    run = plen(pts)
    if run <= stock + 0.5: return None
    stag = 1.3 * l0; min_piece = max(min_piece, 2.0 * l0)
    cands = []; tight = []                                        # tight: the lap is longer than the permitted zone it sits in
    for c, hw in (prefer or []):
        room = max(0.0, hw - l0 / 2.0)
        if hw < l0 / 2.0 - 1e-6: tight.append(c)
        for k in (0.0, -room, room):
            x = c + k
            if l0 / 2.0 < x < run - l0 / 2.0 and all(abs(x - y) > 1.0 for y in cands): cands.append(x)
    cands.sort()

    def families(cs):
        """Every way to cut the run at stations of cs with all pieces <= stock (fewest cuts first)."""
        res = []
        def go(start, chosen):
            if run - start <= stock + 1e-6: res.append(tuple(chosen)); return
            if len(chosen) > 12: return
            for c in reversed(cs):
                if chosen and c <= chosen[-1] + l0: continue
                if c + l0 / 2.0 - start < min_piece - 1e-6 or run - (c - l0 / 2.0) < min_piece - 1e-6: continue
                if c + l0 / 2.0 - start > stock + 1e-6: continue
                go(c - l0 / 2.0, chosen + [c])
                if len(res) > 200000: return
        go(0.0, [])
        if not res: return []
        nmin = min(len(r) for r in res)
        return [r for r in res if len(r) <= nmin + 1]            # one more lap is allowed if that is what staggering takes

    def best_pair(cs, staggered=True):
        fam = families(cs); best = None
        for a in fam:
            for b in fam:
                d = min((abs(x - y) for x in a for y in b), default=1e18)
                if staggered and d < stag - 1e-6: continue
                key = (-(len(a) + len(b)), d)                           # fewest laps first, then the widest stagger
                if best is None or key > best[0]: best = (key, a, b)
        return None if best is None else (best[0][1], best[1], best[2])

    pair = best_pair(cands) if cands else None
    if pair is None and cands: pair = best_pair(cands, staggered=False)   # permitted positions only, even if all bars then lap at one section
    preferred = pair is not None
    if pair is None:                                              # no permitted position reaches within the stock length: regular cuts, flagged
        lay = ec2.lap_layout(run, l0, stock)
        pair = (lay["stagger"] or 0.0, tuple(lay["A"]["centres"]), tuple(lay["B"]["centres"]))

    def pieces(cs):
        out = []; s = 0.0
        for c in cs: out.append((s, c + l0 / 2.0)); s = c - l0 / 2.0
        out.append((s, run)); return out
    d, a, b = pair; pa, pb = pieces(a), pieces(b)
    if any(abs(x - t) < 1.0 for x in a + b for t in tight): preferred = False    # centred in its zone but reaching beyond it
    ok = d >= stag - 1e-6 and all(e - s <= stock + 1e-6 for s, e in pa + pb)
    return dict(A=list(a), B=list(b), pieces_A=pa, pieces_B=pb, stagger=d, preferred=preferred, ok=ok, l0=l0, run=run)


def wall_lap(htot: float, cover: float, dia: float, lap50: float, lap100: float) -> dict:
    """Lap of the two U-bars (top and base) in an outer wall.  Alternate bars are reversed so that the two lap centres
    are 2 x stagger apart.  Where the wall is too short for 1.3 l0 between them every bar laps at one section, and the
    lap is lengthened to the 100 % value (alpha6 = 1.5, Table 8.3) instead."""
    LIM = TRANSPORT - 50.0; H = htot - 2 * cover; co = cover + dia / 2.0
    def stagger(lap):                                     # as drawn; the longer leg must still travel bent
        return max(0.0, min(0.65 * lap, H / 2.0 - lap / 2.0 - 100.0, LIM - (H / 2.0 + lap / 2.0)))
    if H / 2.0 + lap50 / 2.0 > LIM:                       # even equal legs are too long: short legs + a lapped straight wall bar
        LS = lap50 + 150.0; LL = LS + 1.3 * lap50
        if LL <= LIM and LS + LL <= htot - 2 * co - 2 * lap50: return dict(lap=lap50, stagger=0.65 * lap50, staggered=True, fits=True, percent=50, wall_bar=True)
        return dict(lap=lap100, stagger=0.0, staggered=False, percent=100, wall_bar=True, fits=2 * (lap100 + 150.0) <= htot - 2 * co - 2 * lap100)
    s50 = stagger(lap50)
    if 2 * s50 >= 1.3 * lap50 - 1e-6: return dict(lap=lap50, stagger=s50, staggered=True, fits=True, percent=50)
    return dict(lap=lap100, stagger=stagger(lap100), staggered=False, percent=100, fits=lap100 <= H - 2 * ec2.bs8666_min_end_projection(dia))


# ------------------------------------------------------------------ schedule
MEMBER = {"01": "Top slab top face + outer walls (U-bar)", "02": "Base slab bottom face + outer walls (U-bar)", "03": "Top slab bottom face",
          "04": "Base slab top face", "05": "Outer wall inner face", "06": "Pier wall, each face", "07": "Haunch bar", "08": "Distribution, along the barrel",
          "09": "Skew end zone, parallel to the end face", "21": "Outer wall starter", "11": "Outer wall, outer face (straight, lapped top and bottom)",
          "12": "Toe edge U-cap"}
SPACING = {"01": "OUT_S", "02": "OUT_S", "21": "OUT_S", "03": "TOPIN_S", "04": "BOTIN_S", "05": "WALLIN_S", "06": "PIER_S", "07": "HCH_S", "11": "OUT_S", "12": "OUT_S"}


def schedule(D, P: dict, barrel_length: float, skew_deg: float = 90.0, dist_lap_mult: float | None = None, stock: float = STOCK) -> list:
    """Bar schedule of the barrel from the reinforcement section: every piece with its number, shape and cutting length.
    barrel_length is measured square to the road; at a skew the walls and the bars along them are 1 / sin(skew) longer."""
    s = math.sin(math.radians(skew_deg)); axis = barrel_length / s; cv = P["COVER"]; rows = []
    groups = {}
    for pc in D.pieces:
        key = (pc["mark"], pc["fam"], pc["idx"], round(plen(pc["pts"])))
        g = groups.setdefault(key, dict(pc=pc, count=0)); g["count"] += 1
    for (mark, fam, idx, _), g in sorted(groups.items(), key=lambda kv: kv[0]):
        pc = g["pc"]; sp = P[SPACING[mark]]; n_sec = int(math.floor((axis - 2 * cv) / sp)) + 1
        if pc["alt"]:                                              # two alternating families share the positions
            n = (n_sec + 1) // 2 if fam == "A" else n_sec // 2
        else: n = n_sec
        name = mark + ("a" if fam == "B" else "") + (f".{idx}" if pc["split"] else "")
        L = developed(pc["pts"], pc["dia"]); legs = [round(math.dist(a, b)) for a, b in zip(pc["pts"], pc["pts"][1:])]
        rows.append(dict(mark=name, base=mark, member=MEMBER.get(mark, ""), dia=pc["dia"], spacing=sp, no=n * g["count"], shape=shape_code(pc["pts"]), legs=legs,
                         length=L, mass=L / 1000.0 * mass_per_m(pc["dia"]) * n * g["count"], box=enclosing(pc["pts"]), lap=pc.get("lap")))
    # distribution bars run the length of the barrel; lapped in two families when longer than the stock
    dd = P["DIST_D"]; run = axis - 2 * cv; l0 = (dist_lap_mult or P["LAP_MULT"]) * dd; nd = len(D.dots)
    lay = ec2.lap_layout(run, l0, stock)
    for fam, tag, n in (("A", "", (nd + 1) // 2), ("B", "a", nd // 2)):
        pcs = lay[fam]["pieces"]; cnt = {}
        for L in pcs: cnt[math.ceil(L / 25.0 - 1e-9) * 25.0] = cnt.get(math.ceil(L / 25.0 - 1e-9) * 25.0, 0) + 1
        for i, (L, k) in enumerate(sorted(cnt.items(), reverse=True)):
            if n * k == 0: continue
            rows.append(dict(mark="08" + tag + (f".{i + 1}" if len(pcs) > 1 else ""), base="08", member=MEMBER["08"], dia=dd, spacing=P["DIST_S"], no=n * k, shape="00", legs=[L],
                             length=L, mass=L / 1000.0 * mass_per_m(dd) * n * k, box=(L, 0.0),
                             lap=dict(l0=l0, stagger=lay["stagger"], n=lay["n_laps"]) if lay["n_laps"] else None))
    # skewed ends: bars parallel to the end face in the triangular zones, both ends, top and bottom mats of both slabs
    if abs(skew_deg - 90.0) > 1e-6:
        from . import skew as skew_mod
        ez = skew_mod.end_zone_bars(P["W_TOT"], skew_deg, P["OUT_S"], cv); d = P["OUT_D"]; cnt = {}
        for L in ez["lengths"]:
            for piece in _cut(L, P["LAP_MULT"] * d, stock): cnt[piece] = cnt.get(piece, 0) + 1
        for i, (L, k) in enumerate(sorted(cnt.items(), reverse=True)[:60]):
            rows.append(dict(mark=f"09.{i + 1}", base="09", member=MEMBER["09"], dia=d, spacing=P["OUT_S"], no=k * 8, shape="00", legs=[L], length=L,
                             mass=L / 1000.0 * mass_per_m(d) * k * 8, box=(L, 0.0), lap=None))
    return rows


def _cut(L: float, l0: float, stock: float) -> list:
    """Straight bar of length L as stock-length pieces with laps, rounded up to 25 mm."""
    r = lambda x: math.ceil(x / 25.0 - 1e-9) * 25.0
    if L <= stock: return [r(L)]
    n = math.ceil((L - l0) / (stock - l0)); each = (L + (n - 1) * l0) / n
    return [r(each)] * n


def limits(rows: list, fyk: float, stock: float = STOCK) -> list:
    """Manufacturing and delivery limits on a schedule: [(item, value, limit, ok, note)]."""
    out = []; longest = max(rows, key=lambda r: r["length"])
    out.append(("Longest bar in the schedule", f"{longest['length']:.0f} mm (mark {longest['mark']})", f"<= {stock:.0f} mm stock length", longest["length"] <= stock + 1e-6,
                "longer runs are cut and lapped, alternate bars staggered"))
    sizes = sorted({int(r["dia"]) for r in rows}); bad = [d for d in sizes if d not in SIZES]
    out.append(("Bar sizes", ", ".join(f"T{d}" for d in sizes), "preferred sizes " + " ".join(str(d) for d in SIZES), not bad, "BS 4449 / BS 8666 preferred sizes"))
    out.append(("Steel grade", f"fyk {fyk:.0f} MPa" + (f" - {GRADES[int(fyk)]}" if int(fyk) in GRADES else ""), "400 to 600 MPa, a supplied grade (460 or 500)", 400 <= fyk <= 600 and int(fyk) in GRADES,
                "EN 1992-1-1 3.2.2(3); design uses fyd = fyk / 1.15"))
    bent = [r for r in rows if r["shape"] != "00"]
    if bent:
        w = max(bent, key=lambda r: r["box"][1])
        out.append(("Bent bars: shorter side of the enclosing rectangle", f"{w['box'][1]:.0f} mm (mark {w['mark']})", f"<= {TRANSPORT:.0f} mm for road transport", w["box"][1] <= TRANSPORT + 1e-6, "BS 8666"))
        def slack(r):                                   # end legs need the end projection, a leg between two bends twice (r + d)
            need = [ec2.bs8666_min_end_projection(r["dia"]) if i in (0, len(r["legs"]) - 1) else 2.0 * (ec2.bs8666_former_radius(r["dia"]) + r["dia"]) for i in range(len(r["legs"]))]
            i = min(range(len(need)), key=lambda j: r["legs"][j] - need[j]); return r["legs"][i] - need[i], r["legs"][i], need[i]
        short = min(bent, key=lambda r: slack(r)[0]); sl, leg, need = slack(short)
        out.append(("Bent bars: tightest leg", f"{leg:.0f} mm (mark {short['mark']}, T{short['dia']:.0f})", f">= {need:.0f} mm", sl >= -1e-6, "BS 8666 Table 2: end projection, and 2 (r + d) between bends"))
    for r in rows:
        if r.get("lap") and r["lap"].get("stagger") is not None and r["mark"].split(".")[0] in ("01", "02", "03", "04", "08"):
            lp = r["lap"]
            out.append((f"Mark {r['base']}: lap centres of alternate bars", f"{lp['stagger']:.0f} mm apart, lap {lp['l0']:.0f} mm", f">= 1.3 l0 = {1.3 * lp['l0']:.0f} mm", lp["stagger"] >= 1.3 * lp["l0"] - 1e-6,
                        "8.7.2(3): not more than 50 % of the bars lapped at one section"))
            if r["base"] in LAYER:
                top = LAYER[r["base"]] == "top"
                out.append((f"Mark {r['base']}: position of the laps ({'top' if top else 'bottom'} bar)", "at mid-span of the cells" if top else "over the piers",
                            "top bars not lapped at or near a support" if top else "bottom bars not lapped at or near mid-span", bool(lp.get("preferred", True)),
                            "" if lp.get("preferred", True) else "the lap does not fit inside the permitted position: use smaller bars at closer spacing, or wider cells"))
    return out


def multiples(R, htot: float) -> dict:
    """Anchorage and lap lengths used on the drawings, as multiples of the bar diameter, from the member design R.
    The lap covers 50 % of the bars lapped at a section, or 100 % where the outer wall is too short to stagger."""
    am = math.ceil(max(v["anchorage_bent"]["multiple"] for v in R.lengths.values()))
    lm = math.ceil(max(v["lap50"]["multiple"] for v in R.lengths.values()))
    d1 = max(R.faces[(m, "outer")].dia for m in ("top", "base", "walls")); Ln = R.lengths[d1]
    wl = wall_lap(htot, R.cover["used"], d1, lm * d1, max(Ln["lap100"]["l0"], lm * d1))
    if not wl["staggered"]: lm = max(lm, math.ceil(wl["lap"] / d1))
    wl["lap"] = lm * d1 if not wl["staggered"] else wl["lap"]
    return dict(anch_mult=am, lap_mult=lm, wall=wl, d1=d1)
