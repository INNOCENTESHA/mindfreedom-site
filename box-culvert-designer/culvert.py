"""
Single-cell reinforced-concrete box culvert.
Builds a plane-frame model (MIDAS/STAAD style), generates code-style load
cases, combines them, and runs limit-state RC design.
Units: m, kN, kPa. 1 m longitudinal strip.
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from frame import Frame


@dataclass
class Params:
    clear_span: float = 3.0      # internal horizontal (m)
    clear_height: float = 2.5    # internal vertical (m)
    t_top: float = 0.30          # top slab thickness (m)
    t_bot: float = 0.35          # bottom slab thickness (m)
    t_wall: float = 0.30         # wall thickness (m)
    cover_fill: float = 1.0      # earth cover over top slab (m)
    # materials
    fck: float = 30.0            # concrete char. strength (MPa)
    fyk: float = 500.0           # steel char. strength (MPa)
    cover: float = 0.050         # rebar cover (m)
    gamma_c_conc: float = 25.0   # concrete unit wt (kN/m3)
    gamma_soil: float = 19.0     # soil unit wt (kN/m3)
    Ka: float = 0.33             # active/at-rest lateral coeff
    surcharge: float = 10.0      # traffic/construction surcharge (kPa)
    live_load: float = 0.0       # extra vertical live pressure on top (kPa)
    ks: float = 30000.0          # subgrade modulus (kN/m3) Winkler
    water_table: float = 0.0     # height of external water above base (m), 0=none
    gamma_w: float = 9.81
    n_div: int = 10              # elements per member
    E_conc: float = 30e6         # kPa

    @property
    def Bc(self):  # centreline width (wall CL to wall CL)
        return self.clear_span + self.t_wall
    @property
    def Hc(self):  # centreline height (slab CL to slab CL)
        return self.clear_height + (self.t_top + self.t_bot) / 2


# load case keys
CASES = ["SW", "EV", "EH", "SUR", "LL", "WA"]


class Culvert:
    def __init__(self, p: Params):
        self.p = p
        self.members = {}   # name -> list of element indices
        self.node_of = {}
        self._build_frame()

    def _section(self, t):
        A = 1.0 * t
        I = 1.0 * t**3 / 12
        return A, I

    def _build_frame(self):
        p = self.p
        self.fr = Frame()
        B, H = p.Bc, p.Hc
        nd = p.n_div
        # corner coordinates (centreline). origin at bottom-left CL.
        BL, BR, TR, TL = (0, 0), (B, 0), (B, H), (0, H)
        def chain(a, bxy, t, name):
            (xa, ya), (xb, yb) = a, bxy
            xs = np.linspace(xa, xb, nd+1); ys = np.linspace(ya, yb, nd+1)
            ids = []
            for k in range(nd+1):
                key = (round(xs[k], 4), round(ys[k], 4))
                if key in self.node_of:
                    ids.append(self.node_of[key])
                else:
                    i = self.fr.add_node(xs[k], ys[k]); self.node_of[key] = i
                    ids.append(i)
            A, I = self._section(t)
            els = [self.fr.add_element(ids[k], ids[k+1], p.E_conc, A, I) for k in range(nd)]
            self.members[name] = els
            return ids
        bot = chain(BL, BR, p.t_bot, "bottom")
        rig = chain(BR, TR, p.t_wall, "right")
        top = chain(TR, TL, p.t_top, "top")
        lef = chain(TL, BL, p.t_wall, "left")
        self.node_ids = dict(bottom=bot, right=rig, top=top, left=lef)
        # Winkler springs under base slab nodes: ky = ks * tributary width
        trib = B / nd
        for k, nid in enumerate(bot):
            w = trib if 0 < k < nd else trib/2
            self.fr.nodes[nid].ky += p.ks * w
        # tiny lateral restraint to remove rigid-body sway (symmetric loads)
        self.fr.nodes[bot[0]].kx += 1e-3

    # ---------- load cases ----------
    def _fresh(self):
        for e in self.fr.elements:
            e.wt_i = e.wt_j = e.wa = e.gy = 0.0

    def _apply_case(self, case):
        p = self.p; self._fresh()
        if case == "SW":  # self weight of all members
            for name, t in [("top", p.t_top), ("bottom", p.t_bot),
                            ("left", p.t_wall), ("right", p.t_wall)]:
                for ei in self.members[name]:
                    self.fr.elements[ei].gy += -p.gamma_c_conc * t
        elif case == "EV":  # vertical earth fill on top slab (downward)
            q = p.gamma_soil * p.cover_fill
            for ei in self.members["top"]:
                self.fr.elements[ei].gy += -q
        elif case == "LL":  # live/traffic vertical pressure on top slab
            q = p.live_load
            for ei in self.members["top"]:
                self.fr.elements[ei].gy += -q
        elif case == "EH":  # lateral earth pressure on walls (triangular w/ depth)
            self._lateral(p.Ka * p.gamma_soil, from_fill=p.cover_fill)
        elif case == "SUR":  # surcharge -> uniform lateral on walls
            self._lateral_uniform(p.Ka * p.surcharge)
        elif case == "WA":  # external hydrostatic on walls up to water table
            if p.water_table > 0:
                self._lateral(p.gamma_w, from_fill=0.0, top_cap=p.water_table)

    def _wall_depth(self, nid, from_fill):
        # depth below top-of-fill surface for a wall node
        p = self.p
        y = self.fr.nodes[nid].y
        top_y = p.Hc
        return (top_y - y) + from_fill

    def _trans_unit(self, ei):
        """Local transverse unit vector (global) for element ei."""
        e = self.fr.elements[ei]
        ni, nj = self.fr.nodes[e.ni], self.fr.nodes[e.nj]
        dx, dy = nj.x - ni.x, nj.y - ni.y
        L = (dx*dx + dy*dy) ** 0.5
        c, s = dx / L, dy / L
        return (-s, c)   # (+local-y direction in global)

    def _inward_sign(self, ei):
        """+1 if +local-y points toward cell centroid, else -1."""
        e = self.fr.elements[ei]
        ni, nj = self.fr.nodes[e.ni], self.fr.nodes[e.nj]
        mx, my = (ni.x + nj.x) / 2, (ni.y + nj.y) / 2
        cx, cy = self.p.Bc / 2, self.p.Hc / 2      # cell centroid
        tx, ty = self._trans_unit(ei)
        dot = tx * (cx - mx) + ty * (cy - my)
        return 1.0 if dot >= 0 else -1.0

    def _lateral(self, k_gamma, from_fill, top_cap=None):
        """Triangular pressure p(z)=k_gamma*z pushing INWARD on both walls."""
        for name in ("left", "right"):
            ids = self.node_ids[name]
            for k, ei in enumerate(self.members[name]):
                ni, nj = ids[k], ids[k + 1]
                zi = self._wall_depth(ni, from_fill)
                zj = self._wall_depth(nj, from_fill)
                if top_cap is not None:
                    zi = max(0.0, min(zi, top_cap)); zj = max(0.0, min(zj, top_cap))
                pi = k_gamma * max(zi, 0.0); pj = k_gamma * max(zj, 0.0)
                sgn = self._inward_sign(ei)
                self.fr.elements[ei].wt_i += sgn * pi
                self.fr.elements[ei].wt_j += sgn * pj

    def _lateral_uniform(self, press):
        self._lateral_const(press)

    def _lateral_const(self, press):
        for name in ("left", "right"):
            for ei in self.members[name]:
                sgn = self._inward_sign(ei)
                self.fr.elements[ei].wt_i += sgn * press
                self.fr.elements[ei].wt_j += sgn * press

    def run_case(self, case):
        self._apply_case(case)
        u, res = self.fr.solve()
        return res

    def analyse(self):
        self.case_forces = {c: self.run_case(c) for c in CASES}
        return self.case_forces

    # ---------- combinations ----------
    def combine(self, factors: dict):
        """Return per-element [N_i,V_i,M_i,N_j,V_j,M_j] for a factored combo."""
        ne = len(self.fr.elements)
        out = [np.zeros(6) for _ in range(ne)]
        for c, f in factors.items():
            fc = self.case_forces[c]
            for i in range(ne):
                out[i] = out[i] + f * np.array(fc[i])
        return out

    def member_envelope(self, name, combos):
        """Max |M| and coincident V over a member across combos."""
        els = self.members[name]
        mmax = 0.0; vmax = 0.0; nmax = 0.0
        for combo in combos:
            for ei in els:
                f = combo[ei]
                mmax = max(mmax, abs(f[2]), abs(f[5]))
                vmax = max(vmax, abs(f[1]), abs(f[4]))
                nmax = max(nmax, abs(f[0]), abs(f[3]))
        return dict(M=mmax, V=vmax, N=nmax)
