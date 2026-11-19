"""
Layered ground under and beside the culvert.

A profile is a list of layers from the ground surface down.  It supplies
  * vertical and at-rest lateral earth pressure with depth (water table included),
  * the modulus of subgrade reaction for the frame model, from the settlement of the layered ground,
  * settlement and bearing resistance at the founding level (EN 1997-1 Annex D).
Units: m, kN, kPa, degrees.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

GAMMA_W = 9.81


@dataclass
class Layer:
    name: str
    thickness: float               # m
    gamma: float = 19.0            # bulk unit weight above the water table, kN/m3
    gamma_sat: float | None = None # saturated unit weight, kN/m3
    phi: float = 30.0              # effective angle of shearing resistance, degrees
    c: float = 0.0                 # effective cohesion, kPa
    cu: float | None = None        # undrained shear strength, kPa (fine soils)
    E: float = 30_000.0            # drained deformation modulus, kPa
    nu: float = 0.3
    K0: float | None = None        # at-rest coefficient; default 1 - sin(phi) (Jaky)

    @property
    def k0(self): return self.K0 if self.K0 is not None else 1.0 - math.sin(math.radians(self.phi))
    @property
    def gsat(self): return self.gamma_sat if self.gamma_sat is not None else self.gamma + 1.0


@dataclass
class Profile:
    layers: list
    water_depth: float | None = None      # depth of the water table below ground level, m (None = below the profile)

    def _tops(self):
        z = 0.0; out = []
        for L in self.layers:
            out.append((z, z + L.thickness, L)); z += L.thickness
        return out

    def layer_at(self, z: float) -> Layer:
        for z0, z1, L in self._tops():
            if z < z1 - 1e-12: return L
        return self.layers[-1]

    def depth(self): return sum(L.thickness for L in self.layers)

    def sigma_v(self, z: float, surcharge: float = 0.0) -> tuple:
        """Total vertical stress, pore pressure and effective vertical stress at depth z."""
        sv = surcharge; zw = self.water_depth
        for z0, z1, L in self._tops():
            if z <= z0: break
            a, b = z0, min(z, z1)
            if zw is None or b <= zw: sv += L.gamma * (b - a)
            elif a >= zw: sv += L.gsat * (b - a)
            else: sv += L.gamma * (zw - a) + L.gsat * (b - zw)
        if z > self.depth():                                   # below the profile: the last layer continues
            L = self.layers[-1]; a = self.depth()
            sv += (L.gsat if (zw is not None and a >= zw) else L.gamma) * (z - a)
        u = GAMMA_W * (z - zw) if (zw is not None and z > zw) else 0.0
        return sv, u, sv - u

    def lateral_at_rest(self, z: float, surcharge: float = 0.0) -> dict:
        """Horizontal pressure on a rigid buried wall at depth z: K0 sigma'v + u (earth) ; K0 q (surcharge part)."""
        L = self.layer_at(z); sv, u, se = self.sigma_v(z)
        return dict(earth=L.k0 * se, water=u, surcharge=L.k0 * surcharge, total=L.k0 * (se + surcharge) + u, K0=L.k0)

    def breaks(self, z0: float, z1: float) -> list:
        """Depths between z0 and z1 where the pressure diagram changes slope (layer boundaries, water table)."""
        zs = {z0, z1}
        for a, b, L in self._tops():
            for z in (a, b):
                if z0 < z < z1: zs.add(z)
        if self.water_depth is not None and z0 < self.water_depth < z1: zs.add(self.water_depth)
        return sorted(zs)

    # ---- settlement and subgrade reaction
    def settlement(self, q_net: float, B: float, founding_depth: float, L_long: float | None = None, depth_factor: float = 2.0) -> dict:
        """One-dimensional settlement of a footing B wide carrying net pressure q_net at the founding level.
        The stress spreads 2 vertical : 1 horizontal; layers are summed down to depth_factor x B below the base."""
        z_end = founding_depth + depth_factor * B
        s = 0.0; parts = []
        zs = self.breaks(founding_depth, z_end)
        for a, b in zip(zs, zs[1:]):
            n = max(1, int(math.ceil((b - a) / 0.25)))
            dz = (b - a) / n; L = self.layer_at((a + b) / 2); ds = 0.0
            for i in range(n):
                zm = a + (i + 0.5) * dz - founding_depth
                if L_long: dq = q_net * B * L_long / ((B + zm) * (L_long + zm))
                else: dq = q_net * B / (B + zm)                     # strip
                ds += dq * dz / L.E
            s += ds; parts.append((L.name, a, b, ds))
        return dict(s=s, parts=parts, z_end=z_end)

    def subgrade_modulus(self, B: float, founding_depth: float, L_long: float | None = None) -> float:
        """ks = pressure / settlement (kN/m3) of the layered ground under a base B wide."""
        s = self.settlement(100.0, B, founding_depth, L_long)["s"]
        return 100.0 / s if s > 0 else float("inf")

    # ---- bearing resistance, EN 1997-1 Annex D
    def bearing_drained(self, B: float, founding_depth: float, L_long: float | None = None, V: float = 0.0, H: float = 0.0) -> dict:
        """D.4 (drained).  Strength of the layer under the base; a weaker layer within B below is checked by projecting
        the load 2:1 onto it (see bearing).  Returns the characteristic resistance qRk in kPa."""
        Ly = self.layer_at(founding_depth + 1e-6); phi = math.radians(Ly.phi)
        sv, u, q = self.sigma_v(founding_depth)
        zw = self.water_depth
        gam = (Ly.gsat - GAMMA_W) if (zw is not None and zw <= founding_depth + B) else Ly.gamma
        Nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.pi / 4 + phi / 2) ** 2
        Nc = (Nq - 1) / math.tan(phi) if phi > 1e-9 else math.pi + 2
        Ng = 2 * (Nq - 1) * math.tan(phi)
        if L_long:
            sq = 1 + B / L_long * math.sin(phi); sg = 1 - 0.3 * B / L_long
        else: sq = sg = 1.0
        sc = (sq * Nq - 1) / (Nq - 1) if Nq > 1 else 1.0
        iq = ig = ic = 1.0
        if H and V:
            m = (2 + B / L_long) / (1 + B / L_long) if L_long else 2.0
            cot = 1 / math.tan(phi) if phi > 1e-9 else 0.0
            base = max(1 - H / (V + B * (L_long or 1.0) * Ly.c * cot), 0.0)
            iq = base ** m; ig = base ** (m + 1); ic = iq - (1 - iq) / (Nc * math.tan(phi)) if phi > 1e-9 else 1.0
        qR = Ly.c * Nc * sc * ic + q * Nq * sq * iq + 0.5 * gam * B * Ng * sg * ig
        return dict(qRk=qR, Nc=Nc, Nq=Nq, Ngamma=Ng, layer=Ly.name, q_overburden=q, gamma_eff=gam)

    def bearing_undrained(self, B: float, founding_depth: float, L_long: float | None = None) -> dict | None:
        """D.3 (undrained): R/A' = (pi + 2) cu sc + q."""
        Ly = self.layer_at(founding_depth + 1e-6)
        if Ly.cu is None: return None
        sv, u, q = self.sigma_v(founding_depth)
        sc = 1 + 0.2 * B / L_long if L_long else 1.0
        return dict(qRk=(math.pi + 2) * Ly.cu * sc + sv, layer=Ly.name)

    def bearing(self, q_ed: float, B: float, founding_depth: float, L_long: float | None = None, gamma_R: float = 1.4) -> dict:
        """Design check at the base and on the top of every lower layer within 2B (load spread 2V:1H).
        gamma_R = 1.4 is the resistance factor of Design Approach 2 (EN 1997-1 Table A.5); q_ed is the ULS pressure."""
        rows = []
        zs = [founding_depth] + [a for a, b, L in self._tops() if founding_depth < a <= founding_depth + 2 * B]
        for z in zs:
            dz = z - founding_depth; Bz = B + dz
            q_here = q_ed * B / Bz if not L_long else q_ed * B * L_long / (Bz * (L_long + dz))
            d = self.bearing_drained(Bz, z, (L_long + dz) if L_long else None)
            und = self.bearing_undrained(Bz, z, (L_long + dz) if L_long else None)
            qRk = min(d["qRk"], und["qRk"]) if und else d["qRk"]
            rows.append(dict(depth=z, layer=d["layer"], q_ed=q_here, qRk=qRk, qRd=qRk / gamma_R, util=q_here / (qRk / gamma_R),
                             governs="undrained" if (und and und["qRk"] < d["qRk"]) else "drained"))
        worst = max(rows, key=lambda r: r["util"])
        return dict(rows=rows, util=worst["util"], governing=worst, ok=worst["util"] <= 1.0)
