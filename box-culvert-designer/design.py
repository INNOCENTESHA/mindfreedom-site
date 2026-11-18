"""
Limit-state RC design of box-culvert sections (EC2-style, parameterised).
Per 1 m strip. Returns required steel, chosen bars, and utilisation.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

BARS = [10, 12, 16, 20, 25, 32]          # mm diameters
def bar_area(dia): return math.pi * dia**2 / 4   # mm^2

@dataclass
class FaceDesign:
    location: str        # e.g. "Top slab - support (top face)"
    M: float             # kNm
    t: float             # section thickness m
    d: float             # effective depth mm
    As_req: float        # mm2/m
    As_min: float        # mm2/m
    dia: int
    spacing: int         # mm
    As_prov: float       # mm2/m
    util: float          # As_req/As_prov

@dataclass
class ShearCheck:
    location: str
    V: float
    VRdc: float
    ok: bool
    util: float

def choose_bars(As_need):
    """Pick smallest dia @ practical spacing giving As>=As_need (mm2/m)."""
    best = None
    for dia in BARS:
        A1 = bar_area(dia)
        for sp in (250, 225, 200, 175, 150, 125, 100):
            As = A1 * 1000.0 / sp
            if As >= As_need:
                cand = (dia, sp, As)
                # prefer larger spacing (fewer bars), smaller dia
                if best is None or sp > best[1] or (sp == best[1] and dia < best[0]):
                    best = cand
                break
    if best is None:
        dia = 32; sp = 100; best = (dia, sp, bar_area(dia)*1000/sp)
    return best

def design_flexure(location, M, t, fck, fyk, cover, assumed_dia=16):
    b = 1000.0                           # mm
    d = t*1000 - cover*1000 - assumed_dia/2
    M = abs(M)
    K = M*1e6 / (b * d**2 * fck)
    Kbal = 0.167
    z = d * min(0.95, 0.5 + math.sqrt(max(0.25 - K/1.134, 0.0)))
    As_req = M*1e6 / (0.87 * fyk * z) if M > 0 else 0.0
    fctm = 0.30 * fck**(2/3)
    As_min = max(0.26*fctm/fyk*b*d, 0.0013*b*d)
    As_need = max(As_req, As_min)
    dia, sp, As_prov = choose_bars(As_need)
    comp = K > Kbal
    return FaceDesign(location, M, t, d, As_req, As_min, dia, sp, As_prov,
                      As_need/As_prov), comp

def check_shear(location, V, t, fck, cover, As_prov, assumed_dia=16):
    b = 1000.0
    d = t*1000 - cover*1000 - assumed_dia/2
    k = min(1 + math.sqrt(200/d), 2.0)
    rho = min(As_prov/(b*d), 0.02)
    vmin = 0.035 * k**1.5 * fck**0.5
    vRdc = max(0.12*k*(100*rho*fck)**(1/3), vmin)
    VRdc = vRdc * b * d / 1000.0         # kN
    V = abs(V)
    return ShearCheck(location, V, VRdc, V <= VRdc, V/VRdc if VRdc else 9.9)
