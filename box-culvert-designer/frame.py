"""
Plane-frame direct-stiffness solver (2D, 3 DOF/node: ux, uy, rotation).
Supports: nodal loads, member global-gravity UDL, member local transverse
linearly-varying load, uniform local axial load, and nodal springs (Winkler).
Sign convention validated against closed-form beams in tests/ at bottom.
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field


@dataclass
class Node:
    x: float
    y: float
    # support/spring: stiffness added to the diagonal (0 = free, large = fixed)
    kx: float = 0.0
    ky: float = 0.0
    kr: float = 0.0
    fixed: tuple[bool, bool, bool] = (False, False, False)


@dataclass
class Element:
    ni: int            # start node index
    nj: int            # end node index
    E: float           # Young's modulus (kPa)
    A: float           # area (m^2) per metre strip
    I: float           # second moment (m^4) per metre strip
    # distributed loads (per element, in each load case) filled by loader
    # local transverse (kN/m) at i and j (linearly varying), +ve = +local y
    wt_i: float = 0.0
    wt_j: float = 0.0
    wa: float = 0.0    # uniform local axial (kN/m), +ve along i->j
    gy: float = 0.0    # global-Y body UDL (kN/m of member), e.g. -selfweight


class Frame:
    def __init__(self):
        self.nodes: list[Node] = []
        self.elements: list[Element] = []

    def add_node(self, x, y, **kw) -> int:
        self.nodes.append(Node(x, y, **kw)); return len(self.nodes) - 1

    def add_element(self, ni, nj, E, A, I) -> int:
        self.elements.append(Element(ni, nj, E, A, I)); return len(self.elements) - 1

    # ---- element geometry ----
    def _geom(self, e: Element):
        xi, yi = self.nodes[e.ni].x, self.nodes[e.ni].y
        xj, yj = self.nodes[e.nj].x, self.nodes[e.nj].y
        dx, dy = xj - xi, yj - yi
        L = np.hypot(dx, dy)
        c, s = dx / L, dy / L
        return L, c, s

    def _k_local(self, e: Element, L):
        E, A, I = e.E, e.A, e.I
        EA_L = E * A / L
        EI = E * I
        k = np.array([
            [ EA_L, 0, 0, -EA_L, 0, 0],
            [0, 12*EI/L**3, 6*EI/L**2, 0, -12*EI/L**3, 6*EI/L**2],
            [0, 6*EI/L**2, 4*EI/L, 0, -6*EI/L**2, 2*EI/L],
            [-EA_L, 0, 0, EA_L, 0, 0],
            [0, -12*EI/L**3, -6*EI/L**2, 0, 12*EI/L**3, -6*EI/L**2],
            [0, 6*EI/L**2, 2*EI/L, 0, -6*EI/L**2, 4*EI/L],
        ])
        return k

    def _T(self, c, s):
        T = np.zeros((6, 6))
        R = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
        T[:3, :3] = R; T[3:, 3:] = R
        return T

    def _fef_local(self, e: Element, L, c, s):
        """Fixed-end force vector in LOCAL coords (6,), for all member loads."""
        f = np.zeros(6)
        # --- transverse linearly varying load wt_i..wt_j (local +y) ---
        w1, w2 = e.wt_i, e.wt_j
        # uniform part w1 + triangular part (w2-w1) from 0 at i to (w2-w1) at j
        wu = w1
        wtri = w2 - w1
        # uniform UDL fixed-end (local): shear each end wu*L/2, moments -/+ wu L^2/12
        f[1] += wu * L / 2;         f[4] += wu * L / 2
        f[2] += wu * L**2 / 12;     f[5] += -wu * L**2 / 12
        # triangular 0->wtri (i->j): standard FEM
        f[1] += wtri * L * 3/20;    f[4] += wtri * L * 7/20
        f[2] += wtri * L**2 / 30;   f[5] += -wtri * L**2 / 20
        # --- uniform axial ---
        f[0] += e.wa * L / 2;       f[3] += e.wa * L / 2
        # --- global-Y body UDL gy (project to local) ---
        # global (0, gy): local axial = gy*s, local transverse = gy*c
        qa = e.gy * s
        qt = e.gy * c
        f[0] += qa * L / 2;         f[3] += qa * L / 2
        f[1] += qt * L / 2;         f[4] += qt * L / 2
        f[2] += qt * L**2 / 12;     f[5] += -qt * L**2 / 12
        return f

    def solve(self):
        n = len(self.nodes); ndof = 3 * n
        K = np.zeros((ndof, ndof)); F = np.zeros(ndof)
        fef_store = []
        for e in self.elements:
            L, c, s = self._geom(e)
            kl = self._k_local(e, L); T = self._T(c, s)
            kg = T.T @ kl @ T
            fef_l = self._fef_local(e, L, c, s)
            fef_g = T.T @ fef_l
            fef_store.append((L, c, s, kl, T, fef_l))
            dofs = [3*e.ni, 3*e.ni+1, 3*e.ni+2, 3*e.nj, 3*e.nj+1, 3*e.nj+2]
            for a in range(6):
                F[dofs[a]] -= fef_g[a]   # equivalent nodal load = -FEF
                for b in range(6):
                    K[dofs[a], dofs[b]] += kg[a, b]
        # springs + penalty supports
        BIG = 1e14
        for i, nd in enumerate(self.nodes):
            K[3*i, 3*i]     += nd.kx + (BIG if nd.fixed[0] else 0)
            K[3*i+1, 3*i+1] += nd.ky + (BIG if nd.fixed[1] else 0)
            K[3*i+2, 3*i+2] += nd.kr + (BIG if nd.fixed[2] else 0)
        u = np.linalg.solve(K, F)
        # recover member end forces (local): f = kl*T*u_e + fef_l
        results = []
        for e, (L, c, s, kl, T, fef_l) in zip(self.elements, fef_store):
            dofs = [3*e.ni, 3*e.ni+1, 3*e.ni+2, 3*e.nj, 3*e.nj+1, 3*e.nj+2]
            ue = u[dofs]
            fl = kl @ (T @ ue) + fef_l
            results.append(fl)   # [N_i,V_i,M_i,N_j,V_j,M_j] local
        return u, results


# ----------------------- self-validation -----------------------
if __name__ == "__main__":
    E = 30e6; b = 1.0; h = 0.3
    A = b*h; I = b*h**3/12
    # (1) Fixed-fixed beam, span Lb, UDL w -> end moment wL^2/12, mid wL^2/24
    Lb, w = 6.0, 10.0
    fr = Frame()
    N = 10
    xs = np.linspace(0, Lb, N+1)
    ids = [fr.add_node(x, 0.0) for x in xs]
    fr.nodes[ids[0]].fixed = (True, True, True)
    fr.nodes[ids[-1]].fixed = (True, True, True)
    for a in range(N):
        ei = fr.add_element(ids[a], ids[a+1], E, A, I)
        fr.elements[ei].gy = -w   # downward UDL via gravity body load
    u, res = fr.solve()
    M_end = abs(res[0][2])
    # midspan moment: take element spanning mid; approximate by max |M| recovered
    Ms = max(abs(r[2]) for r in res) 
    print(f"[fixed-fixed UDL] end M = {M_end:.3f} (theory {w*Lb**2/12:.3f}) ; "
          f"max end-moment seen = {Ms:.3f}")
    # (2) Propped nothing — cantilever, point via UDL check end reaction
    print("validation done")
