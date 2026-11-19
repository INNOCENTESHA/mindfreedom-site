"""
Skew simulation: the plan at a range of skews (road horizontal) with the wall lengths, as a picture and a table.

    python tests/skew_simulation.py [out.png] [pivot]
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from detailing import skew
import app

W, L, A, FL, T = 7250.0, 10500.0, 4750.0, 30.0, 250.0
PIERS = [(-W / 2 + T + j * 1500 + (j - 0.5) * T, T) for j in range(1, 4)]


def main(out="skew_simulation.png", pivot="centre", angles=(60, 70, 80, 90, 100, 110, 120, 135)):
    fig = Figure(figsize=(20, 10.5), dpi=110, facecolor="white"); FigureCanvasAgg(fig); px = lambda n: n * 1.15
    sq = skew.layout(W, L, A, FL, 90, pivot, T, PIERS)
    for i, a in enumerate(angles):
        ax = fig.add_subplot(2, 4, i + 1); g = skew.layout(W, L, A, FL, a, pivot, T, PIERS)
        app.Main.draw_plan(None, ax, g, sq, px, title=False)
        ax.set_title(f"skew {a}°   barrel walls {g['wall_length'] / 1000:.2f} m" + ("" if g["ok"] else "   — NOT BUILDABLE"), fontsize=px(11), color="#1b3a5c" if g["ok"] else "#c0392b")
    fig.suptitle(f"4-cell 1500 x 1500 culvert, barrel 10.5 m, apron 4.75 m, flare 30°  —  pivot at the {pivot}  —  road horizontal, dashed = square crossing", fontsize=px(13), color="#1b3a5c")
    fig.tight_layout(rect=(0, 0, 1, 0.96)); fig.savefig(out)
    print(f"{'skew':>5} {'barrel wall':>12} {'end face':>9} {'inlet L':>9} {'inlet R':>9} {'outlet L':>9} {'outlet R':>9}  buildable")
    for r in skew.simulate(W, L, A, FL, (45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130, 135), pivot):
        print(f"{r['skew']:5d} {r['wall_length']:12.0f} {r['end_face']:9.0f} {r['inlet_left']:9.0f} {r['inlet_right']:9.0f} {r['outlet_left']:9.0f} {r['outlet_right']:9.0f}  {'yes' if r['ok'] else 'no'}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
