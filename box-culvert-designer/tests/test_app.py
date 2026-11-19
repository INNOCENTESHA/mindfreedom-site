"""The desktop application driven without a display: every view, table and what-if input must work."""
import os, sys, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
W = pytest.importorskip("PySide6.QtWidgets")
import app as A, ui_shell as ui


@pytest.fixture(scope="module")
def win():
    q = W.QApplication.instance() or W.QApplication([])
    w = A.Main(); w.show(); yield w; w.close()


def test_every_display_and_case(win):
    mv = win.mv; n = mv.cb_lc.count(); assert n > 20
    for d in range(len(ui.DISPLAYS)):
        for lc in (0, 1, 2, 3, 4, 6, 8, 9, n - 1):
            mv.cb_lc.setCurrentIndex(lc); mv.cb_disp.setCurrentIndex(d)       # draws; any exception fails the test
    for t in (mv.t_nodes, mv.t_elems, mv.t_vals): t.toggle()


def test_tables(win):
    for lc in (0, 2, 5):
        win.mv.cb_lc.setCurrentIndex(lc)
        for k in ui.Tables.KINDS:
            win.show_table(k); assert win.tables.t.rowCount() > 0, k
    win.show_table("Reactions"); t = win.tables.t                          # the reactions add up to the bearing check
    total = float(t.item(t.rowCount() - 1, 2).text()); assert total > 0


def test_ribbon_and_tree(win):
    for b in win.ribbon.buttons.values():
        if b.text() in ("Exit", "Open", "Save") or "DXF" in b.text() or "PDF" in b.text() or "Generate" in b.text(): continue
        b.click()
    def walk(it):
        win._tree_clicked(it)
        for i in range(it.childCount()): walk(it.child(i))
    for i in range(win.tree.topLevelItemCount()): walk(win.tree.topLevelItem(i))


@pytest.mark.parametrize("cells,span,height,toe,skew,ground", [(1, 2.0, 2.0, 0, 90, False), (2, 3.0, 2.5, 400, 60, True), (6, 1.5, 1.2, 0, 120, False), (3, 4.0, 3.0, 600, 75, True)])
def test_what_if_inputs(win, cells, span, height, toe, skew, ground):
    win.i_cells.setValue(cells); win.i_span.setValue(span); win.i_height.setValue(height); win.i_toe.setValue(toe); win.i_skew.setValue(skew)
    win.use_ground.setChecked(ground); win.i_water.setValue(2.0 if ground else 0.0)
    t = max(0.25, round(span / 10 / 0.025) * 0.025)
    for w in (win.i_ttop, win.i_tbase, win.i_twall): w.setValue(t)
    assert "previous model" in win.banner.text()                           # results are marked out of date until re-run
    win.run()
    assert "DESIGN" in win.banner.text() and win.box.p.n_cells == cells
    assert len(win.box.wall_chains) == cells + 1
    for name in ("Detailing", "Schedule (BBS)", "Report", "Code checks", "Ground · Plan", "Design", "Model View"): win.goto(name)


def test_project_round_trip(win, tmp_path):
    win.i_cells.setValue(5); win.i_fill.setValue(2.5); win.i_expo.setCurrentText("XD2"); path = str(tmp_path / "a.cbc")
    win.save_project(path); before = ui.collect(win)
    win.new_project(); assert win.i_cells.value() != 5 or win.i_fill.value() != 2.5
    win.open_project(path); assert ui.collect(win) == before
    assert json.load(open(path))["format"] == "CBC project"
