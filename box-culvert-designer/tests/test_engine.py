"""Engine checked against results that do not come from this code."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from frame import Frame
from engine import Box, P


def test_fixed_beam_closed_form():
    """Fixed-ended beam, uniform load: end moment wL^2/12, mid-span wL^2/24, end shear wL/2."""
    L, w, n = 4.0, 25.0, 8
    f = Frame()
    ids = [f.add_node(L * k / n, 0.0, fixed=((True,) * 3 if k in (0, n) else (False,) * 3)) for k in range(n + 1)]
    for a, b in zip(ids, ids[1:]): f.elements[f.add_element(a, b, E=30e6, A=0.3, I=0.3 ** 3 / 12)].gy = -w
    u, res = f.solve()
    assert abs(abs(res[0][2]) - w * L * L / 12) < 1e-6
    assert abs(abs(res[0][1]) - w * L / 2) < 1e-6
    mid = res[n // 2 - 1]
    assert abs(abs(mid[5]) - w * L * L / 24) < 1e-6


def test_square_cell_closed_form():
    """Square closed frame of uniform stiffness, uniform load w on the top and an equal uniform reaction on the base:
    by moment distribution every corner carries wL^2/24 and the slabs wL^2/12 at mid-span.  A very soft foundation
    gives the uniform reaction."""
    p = P(); p.n_cells = 1; p.span = p.height = 2.75; p.t_top = p.t_base = p.t_wall = 0.25; p.fill = 1.0; p.ks = 1.0; p.n_div = 12
    b = Box(p); b.case("EV"); F = b.fr.solve()[1]
    L = b.W_cl; w = p.gamma_soil * p.fill
    dg = b.diagram(b.members["top"], F); ms = [m for _, m, _, _ in dg]
    assert abs(min(ms) + w * L * L / 24) < 0.01 * w * L * L / 24          # hogging at the corners
    assert abs(max(ms) - w * L * L / 12) < 0.01 * w * L * L / 12          # sagging at mid-span
    assert abs((max(ms) - min(ms)) - w * L * L / 8) < 1e-6                # statics, whatever the stiffness


def test_against_the_workbook_solver():
    """Single cell 2000 x 2000, 250 walls, 1 m fill, HB 37.5: the figures the parametric workbook reports."""
    from detailing import design
    p = P(); p.n_cells = 1; p.span = p.height = 2.0; p.t_top = p.t_base = p.t_wall = 0.25; p.fill = 1.0
    p.hb_disp_fill = 0.7                                                 # the workbook's HB_DISP setting
    b = Box(p).analyse(); uls = b.uls_combos(); sls = b.sls_combos()
    d = 0.25 - 0.05 - 0.008
    top = b.design_actions("top", uls, d); base = b.design_actions("base", uls, d); wall = b.design_actions("walls", uls, d)
    for got, ref in ((top["M_in"], 48.81), (top["M_out"], 36.00), (top["V_d"], 108.05), (base["M_in"], 48.87), (base["M_out"], 44.66),
                     (base["V_d"], 111.02), (wall["M_out"], 44.66), (wall["V_d"], 40.20)):
        assert abs(got - ref) < 0.012 * ref, (got, ref)
    assert abs(max(b.bearing(c)[0] for c in sls) - 157.6) < 1.0
    assert abs(max(b.bearing(c)[0] for c in uls) - 247.4) < 1.5


def test_load_cases_balance():
    for n, toe in ((1, 0.0), (3, 0.0), (4, 0.4)):
        p = P(); p.n_cells = n; p.toe = toe
        b = Box(p).analyse()
        react = lambda fmap: sum(b.fr.nodes[i].ky * b.combine_u(fmap)[3 * i + 1] for i in b.base_nodes)
        sw = p.gamma_conc * (p.t_top * b.W_cl + p.t_base * (b.W_cl + 2 * b.toe_len) + sum(w["t"] * p.Hc for w in b.wall_chains))
        assert abs(react({"SW": 1.0}) - sw) < 1e-6 * sw
        ev = p.gamma_soil * p.fill * b.W_cl + 2 * b.toe_len * p.gamma_soil * (p.fill + p.t_top + p.height)
        assert abs(react({"EV": 1.0}) - ev) < 1e-6 * ev
        assert abs(react({"EH": 1.0})) < 1e-6 * sw
        k = b.hb_keys[0]; assert 0 < react({k: 1.0}) <= 2 * p.hb_wheel + 1e-9


def test_trends():
    """More fill -> more bearing pressure; a stiffer foundation -> smaller slab moments from the same load."""
    def bear(fill):
        p = P(); p.fill = fill; b = Box(p).analyse(); return max(b.bearing(c)[0] for c in b.sls_combos())
    assert bear(0.6) < bear(2.0) < bear(4.0)
    def hb_m(fill):
        p = P(); p.fill = fill; b = Box(p).analyse()
        return max(max(abs(m) for _, m, _, _ in b.diagram(b.members["top"], b.combine_F({k: 1.0}))) for k in b.hb_keys)
    assert hb_m(0.6) > hb_m(2.0) > hb_m(4.0)                              # the wheel spreads with depth
