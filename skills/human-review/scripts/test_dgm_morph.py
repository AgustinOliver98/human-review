#!/usr/bin/env python3
"""Switching the radius of a diff diagram morphs instead of jumping.

Each radius (0, 1, 2, all) is its own PlantUML render with its own layout, so a bare
visibility flip threw every box somewhere new and the reader lost the change. focus.js
now keeps the changed boxes (`dgm-ripple-1`) at the same place on screen by scrolling the
page, slides the boxes both renders share from their old spot to their new one, and fades
the newcomers in with a glow. The morph must leave nothing behind: once it settles, the
picture is exactly the one a plain flip shows.

The page here is the real stylesheet and the real focus.js around two hand-made renders
with different layouts, so it needs no build and no server.

Run with:  python3 -m pytest test_dgm_morph.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("hr_assets", HERE / "hrbuild" / "shared" / "assets.py")
assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assets)


def _entity(name, x, y, fill):
    return (f'<g class="entity" data-qualified-name="{name}"><rect fill="{fill}" x="{x}" y="{y}" '
            f'width="120" height="60" style="stroke:var(--dgm-line);stroke-width:0.5;"/>'
            f'<text x="{x + 10}" y="{y + 30}">{name}</text></g>')


def _svg(h, *entities):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 {h}" width="400px" '
            f'height="{h}px" style="width:400px;height:{h}px"><g>'
            f'<g class="title"><text x="10" y="20">Diff</text></g>{"".join(entities)}'
            f'<g class="link"><path d="M0,0 L10,10"/></g></g></svg>')


# At 0 the change sits at the top; at 1 a neighbour lands above it and pushes it down,
# which is exactly the jump the morph exists to absorb. Gone leaves at 1.
LEVEL0 = _svg(260, _entity("Visit", 40, 40, "var(--dgm-ripple-1)"),
              _entity("Vet", 40, 160, "var(--dgm-ripple-1)"),
              _entity("Gone", 220, 40, "var(--dgm-ripple-2)"))
LEVEL1 = _svg(500, _entity("Pet", 140, 40, "var(--dgm-ripple-2)"),
              _entity("Visit", 200, 220, "var(--dgm-ripple-1)"),
              _entity("Vet", 200, 340, "var(--dgm-ripple-1)"))

PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><style>{assets.CSS}</style></head>
<body><div class="wrap"><div style="height:500px"></div>
<div class="diagram"><div class="dgmviews"><div class="dgmpane" data-view="diff">
<div class="focus"><span class="lbl">Diff + extra neighbours:</span>
<button type="button" data-level="0" aria-pressed="true">0</button>
<button type="button" data-level="1" aria-pressed="false">1</button></div>
<div class="svgbox" data-level="0">{LEVEL0}</div>
<div class="svgbox" data-level="1" hidden>{LEVEL1}</div>
</div></div></div><div style="height:2000px"></div></div>
{assets.FOCUS_JS}</body></html>"""

CENTRE = """(n) => { const g = document.querySelector('.svgbox:not([hidden]) g.entity[data-qualified-name="' + n + '"]');
  const r = g.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }"""
LAYOUT = """() => { const svg = document.querySelector('.svgbox:not([hidden]) svg'), s = svg.getBoundingClientRect();
  return [...svg.querySelectorAll('g.entity')].map(g => { const r = g.getBoundingClientRect();
    return [g.dataset.qualifiedName, Math.round(r.left - s.left), Math.round(r.top - s.top)]; }); }"""
LEFTOVERS = ("() => document.querySelectorAll('[style*=\"transform\"], .dgm-m-new, .dgm-m-fade, "
             ".dgm-m-glow, .dgm-m-ghost, .dgm-morphing').length")


def _open(p, tmp_path, **ctx):
    page_file = tmp_path / "page.html"
    page_file.write_text(PAGE, encoding="utf-8")
    try:
        browser = p.chromium.launch()
    except Exception as e:  # no browser downloaded for this interpreter
        pytest.skip(f"chromium unavailable: {e}")
    page = browser.new_page(viewport={"width": 1152, "height": 625}, **ctx)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(page_file.as_uri())
    page.evaluate("window.scrollTo(0, 400)")
    return browser, page, errors


def test_the_change_stays_put_the_shared_boxes_slide_and_nothing_is_left_behind(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        browser, page, errors = _open(p, tmp_path)
        try:
            before = page.evaluate(CENTRE, "Visit")
            page.click('.focus button[data-level="1"]')
            page.wait_for_timeout(60)
            mid = page.evaluate("""() => ({
              moving: document.querySelectorAll('.svgbox:not([hidden]) g.entity[style*="transform"]').length,
              arriving: [...document.querySelectorAll('.dgm-m-new')].map(g => g.dataset.qualifiedName),
              ghost: document.querySelectorAll('.dgm-m-ghost').length })""")
            page.wait_for_timeout(1900)
            after = page.evaluate(CENTRE, "Visit")
            morphed, left = page.evaluate(LAYOUT), page.evaluate(LEFTOVERS)
            pressed = page.evaluate("() => document.querySelector('.focus button[aria-pressed=true]').dataset.level")
        finally:
            browser.close()
    assert not errors
    assert mid["moving"] >= 1 and mid["arriving"] == ["Pet"] and mid["ghost"] == 1
    assert abs(after[1] - before[1]) <= 1, "the changed box must stay where the eye was"
    assert left == 0 and pressed == "1"
    # The settled picture is the un-animated one.
    with sync.sync_playwright() as p:
        browser, page, _ = _open(p, tmp_path)
        try:
            page.evaluate("""() => document.querySelectorAll('.svgbox[data-level]').forEach(b => {
              b.hidden = b.dataset.level !== '1'; })""")
            plain = page.evaluate(LAYOUT)
        finally:
            browser.close()
    assert morphed == plain


def test_reduced_motion_keeps_the_anchor_and_the_glow_but_does_not_slide(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        browser, page, errors = _open(p, tmp_path, reduced_motion="reduce")
        try:
            before = page.evaluate(CENTRE, "Visit")
            page.click('.focus button[data-level="1"]')
            page.wait_for_timeout(30)
            moving = page.evaluate("() => document.querySelectorAll('g.entity[style*=\"transform\"]').length")
            glowing = page.evaluate("() => [...document.querySelectorAll('.dgm-m-glow')].map(g => g.dataset.qualifiedName)")
            after = page.evaluate(CENTRE, "Visit")
            page.wait_for_timeout(1700)
            left = page.evaluate(LEFTOVERS)
        finally:
            browser.close()
    assert not errors
    assert moving == 0 and glowing == ["Pet"] and left == 0
    assert abs(after[1] - before[1]) <= 1


def test_the_chooser_pins_so_the_anchoring_scroll_never_takes_it_away():
    css = assets.CSS
    assert ".diagram .focus { position:sticky; top:var(--strip-h" in css


# --- The same morph on a hand-drawn (draw.io) card's Diff / New / Old swap. -------------
#
# draw.io marks its cells, not its boxes: `<g data-cell-id>` holds a vertex, an edge (the
# line takes the pointer by its stroke), an edge's label (nested in the edge), or a layer
# that only holds other cells. The morph keys vertices by cell id, and falls back to the
# label for a box a redraw gave a new id — here "Bee" is `b2` in the new drawing and `b1`
# in the old one, and must still slide rather than vanish and reappear.

def _vertex(cid, x, y, text):
    return (f'<g data-cell-id="{cid}"><a href="#"><g><rect x="{x}" y="{y}" width="120" height="40" '
            f'fill="#dae8fc" stroke="#6c8ebf" stroke-width="2" pointer-events="all"/></g>'
            f'<g><g><foreignObject pointer-events="none" width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" '
            f'style="display:flex;width:1px;height:1px;padding-top:{y + 20}px;margin-left:{x + 1}px;">'
            f'<div style="box-sizing:border-box;font-size:0;"><div style="font-size:12px;">{text}</div></div>'
            f'</div></foreignObject></g></g></a></g>')


def _edge(cid, d):
    return (f'<g data-cell-id="{cid}"><g><path d="{d}" fill="none" stroke="#000" stroke-width="2" '
            f'pointer-events="stroke"/></g><g data-cell-id="{cid}-t"><g><g><foreignObject pointer-events="none" '
            f'width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml">1</div></foreignObject></g></g></g></g>')


def _drawio(*cells):
    return ('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="520px" height="300px" viewBox="0 0 520 300">'
            f'<defs/><g><g data-cell-id="0"><g data-cell-id="1">{"".join(cells)}</g></g></g></svg>')


DRAWIO_NEW = _drawio(_vertex("a", 20, 20, "Alpha"), _vertex("b2", 360, 220, "Bee"),
                     _vertex("c", 200, 120, "Cee"), _edge("e-a-b", "M 80 60 L 420 220"))
DRAWIO_OLD = _drawio(_vertex("a", 360, 20, "Alpha"), _vertex("b1", 20, 220, "Bee"),
                     _vertex("d", 200, 120, "Dee"))

DRAWIO_PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><style>{assets.CSS}</style></head>
<body><div class="wrap"><div class="diagram dgm-toggles"><div class="head"><b>Conceptual Model</b></div>
<div class="dgmviews" data-state="new"><div class="dgmbar">
<button type="button" class="dgm-diff" data-go="diff" aria-pressed="false">Diff</button>
<button type="button" class="dgm-newold" data-go="newold" aria-pressed="true"><u data-view="new" class="on">New</u>/<u data-view="old">Old</u></button></div>
<div class="dgmpane" data-view="diff" hidden><div class="svgbox">{DRAWIO_NEW}</div></div>
<div class="dgmpane" data-view="new"><div class="svgbox">{DRAWIO_NEW}</div></div>
<div class="dgmpane" data-view="old" hidden><div class="svgbox">{DRAWIO_OLD}</div></div>
</div></div><div style="height:1500px"></div></div>
{assets.DGM_VIEWS_JS}{assets.FOCUS_JS}</body></html>"""

CELLS = """() => { const svg = document.querySelector('.dgmpane:not([hidden]) svg'), s = svg.getBoundingClientRect();
  return [...svg.querySelectorAll('g[data-cell-id]')].map(g => { const r = g.getBoundingClientRect();
    return [g.dataset.cellId, Math.round(r.left - s.left), Math.round(r.top - s.top), Math.round(r.width)]; }); }"""
DRAWIO_LEFTOVERS = ("() => document.querySelectorAll('[style*=\"transform\"], .dgm-m-new, .dgm-m-fade, "
                    ".dgm-m-glow, .dgm-m-shape, .dgm-m-ghost, .dgm-morphing').length")


def _open_drawio(p, tmp_path, plain=False, **ctx):
    page_file = tmp_path / "drawio.html"
    page_file.write_text(DRAWIO_PAGE, encoding="utf-8")
    try:
        browser = p.chromium.launch()
    except Exception as e:  # no browser downloaded for this interpreter
        pytest.skip(f"chromium unavailable: {e}")
    context = browser.new_context(viewport={"width": 1152, "height": 625}, **ctx)
    if plain:  # the morph's guard: with it already set, the swap is the bare flip
        context.add_init_script("window.__dgmMorph = true;")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(page_file.as_uri())
    return browser, page, errors


def test_a_drawio_swap_slides_shared_boxes_matches_a_renamed_one_by_label_and_settles_clean(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        browser, page, errors = _open_drawio(p, tmp_path)
        try:
            page.click('.dgmbar button[data-go="newold"] u[data-view="old"]')   # New -> Old
            page.wait_for_timeout(40)
            mid = page.evaluate("""() => ({
              state: document.querySelector('.dgmviews').dataset.state,
              moving: [...document.querySelectorAll('.dgmpane:not([hidden]) g[data-cell-id]')]
                        .filter(g => !g.classList.contains('dgm-m-new') && getComputedStyle(g).transform !== 'none')
                        .map(g => g.dataset.cellId).sort(),
              arriving: [...document.querySelectorAll('.dgm-m-new')].map(g => g.dataset.cellId),
              shape: document.querySelectorAll('.dgm-m-glow .dgm-m-shape').length,
              ghost: [...document.querySelectorAll('.dgm-m-ghost g[data-cell-id]')]
                       .filter(g => g.style.visibility === 'visible').map(g => g.dataset.cellId) })""")
            page.wait_for_timeout(1900)
            morphed, left = page.evaluate(CELLS), page.evaluate(DRAWIO_LEFTOVERS)
            page.click('.dgmbar button[data-go="newold"] u[data-view="new"]')   # Old -> New: the edge waits
            page.wait_for_timeout(40)
            back = page.evaluate("""() => ({
              arriving: [...document.querySelectorAll('.dgm-m-new')].map(g => g.dataset.cellId),
              fading: [...document.querySelectorAll('.dgm-m-fade')].map(g => g.dataset.cellId),
              ghost: [...document.querySelectorAll('.dgm-m-ghost g[data-cell-id]')]
                       .filter(g => g.style.visibility === 'visible').map(g => g.dataset.cellId) })""")
            page.wait_for_timeout(1900)
            left_back = page.evaluate(DRAWIO_LEFTOVERS)
        finally:
            browser.close()
    assert not errors
    assert mid["state"] == "old"
    assert mid["moving"] == ["a", "b1"], "Alpha by id, Bee by its label"
    assert mid["arriving"] == ["d"] and mid["shape"] == 1 and mid["ghost"] == ["c"]
    assert back["arriving"] == ["c"] and back["fading"] == ["e-a-b"] and back["ghost"] == ["d"]
    assert left == 0 and left_back == 0
    with sync.sync_playwright() as p:
        browser, page, _ = _open_drawio(p, tmp_path, plain=True)
        try:
            page.click('.dgmbar button[data-go="newold"] u[data-view="old"]')
            plain = page.evaluate(CELLS)
        finally:
            browser.close()
    assert morphed == plain


def test_a_drawio_swap_with_nothing_moved_leaves_the_picture_alone(tmp_path):
    """Diff -> New of one drawing: same boxes, same lines. Nothing slides and no line
    blinks — a fade on every edge would read as a change that is not there."""
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        browser, page, errors = _open_drawio(p, tmp_path)
        try:
            page.click('.dgmbar button[data-go="diff"]')
            page.wait_for_timeout(40)
            touched = page.evaluate(DRAWIO_LEFTOVERS)
        finally:
            browser.close()
    assert not errors and touched == 0


def test_reduced_motion_on_a_drawio_swap_glows_but_does_not_slide(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        browser, page, errors = _open_drawio(p, tmp_path, reduced_motion="reduce")
        try:
            page.click('.dgmbar button[data-go="newold"] u[data-view="old"]')
            page.wait_for_timeout(30)
            moving = page.evaluate("() => [...document.querySelectorAll('g[data-cell-id]')].filter(g => g.style.transform).length")
            glowing = page.evaluate("() => [...document.querySelectorAll('.dgm-m-glow')].map(g => g.dataset.cellId)")
            page.wait_for_timeout(1700)
            left = page.evaluate(DRAWIO_LEFTOVERS)
        finally:
            browser.close()
    assert not errors
    assert moving == 0 and glowing == ["d"] and left == 0


# --- The same morph on a PlantUML card's Diff / New / Old swap (the Data tab). ------------
#
# New and Old of a domain model hold the same boxes, so nothing arrives: what the switch
# has to show is a box whose content changed and a line drawn between two boxes that were
# both already there. Diff (radius 0) holds only the changed pair, so Diff -> New is the
# radius morph's own picture: the neighbours arrive and glow.

def _box(eid, name, x, y, body=""):
    return (f'<g class="entity" data-qualified-name="{name}" id="{eid}"><rect fill="#fff" x="{x}" y="{y}" '
            f'width="120" height="60" style="stroke:var(--dgm-line);stroke-width:0.5;"/>'
            f'<text x="{x + 10}" y="{y + 30}">{name}</text><text x="{x + 10}" y="{y + 50}">{body}</text></g>')


def _line(a, b):
    return (f'<g class="link" data-entity-1="{a}" data-entity-2="{b}" data-link-type="dependency">'
            f'<path d="M0,0 L10,10" fill="none" style="stroke:var(--dgm-line);stroke-width:1;"/></g>')


PUML_DIFF0 = _svg(260, _box("e1", "Visit", 40, 40, "vet : Vet"), _box("e2", "Vet", 40, 160), _line("e1", "e2"))
PUML_NEW = _svg(420, _box("e3", "Pet", 220, 40), _box("e1", "Visit", 40, 160, "vet : Vet"),
                _box("e2", "Vet", 40, 300), _line("e1", "e2"), _line("e3", "e1"))
PUML_OLD = _svg(420, _box("e2", "Vet", 220, 300), _box("e3", "Pet", 40, 40),
                _box("e1", "Visit", 220, 160), _line("e3", "e1"))

PUML_PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><style>{assets.CSS}</style></head>
<body><div class="wrap"><div class="diagram dgm-toggles"><div class="head"><b>Domain Model</b></div>
<div class="dgmviews" data-state="diff"><div class="dgmbar">
<button type="button" class="dgm-diff" data-go="diff" aria-pressed="true">Diff</button>
<button type="button" class="dgm-newold" data-go="newold" aria-pressed="false"><u data-view="new">New</u>/<u data-view="old">Old</u></button></div>
<div class="dgmpane" data-view="diff"><div class="focus"><span class="lbl">Diff + extra neighbours:</span>
<button type="button" data-level="0" aria-pressed="true">0</button></div>
<div class="svgbox" data-level="0">{PUML_DIFF0}</div></div>
<div class="dgmpane" data-view="new" hidden><div class="svgbox">{PUML_NEW}</div></div>
<div class="dgmpane" data-view="old" hidden><div class="svgbox">{PUML_OLD}</div></div>
</div></div><div style="height:1500px"></div></div>
{assets.DGM_VIEWS_JS}{assets.FOCUS_JS}</body></html>"""

PUML_MID = """() => ({
  state: document.querySelector('.dgmviews').dataset.state,
  moving: [...document.querySelectorAll('.dgmpane:not([hidden]) g.entity')]
            .filter(g => !g.classList.contains('dgm-m-new') && getComputedStyle(g).transform !== 'none')
            .map(g => g.dataset.qualifiedName).sort(),
  arriving: [...document.querySelectorAll('.dgm-m-new')].map(g => g.dataset.qualifiedName),
  glowing: [...document.querySelectorAll('.dgmpane:not([hidden]) .dgm-m-glow')]
             .map(g => g.dataset.qualifiedName || g.getAttribute('data-entity-1') + '>' + g.getAttribute('data-entity-2')).sort(),
  ghost: [...document.querySelectorAll('.dgm-m-ghost g.entity')]
           .filter(g => g.style.visibility !== 'hidden').map(g => g.dataset.qualifiedName) })"""
PUML_LAYOUT = LAYOUT.replace(".svgbox:not([hidden]) svg", ".dgmpane:not([hidden]) .svgbox:not([hidden]) svg")


def _open_puml(p, tmp_path, plain=False, **ctx):
    page_file = tmp_path / "puml.html"
    page_file.write_text(PUML_PAGE, encoding="utf-8")
    try:
        browser = p.chromium.launch()
    except Exception as e:  # no browser downloaded for this interpreter
        pytest.skip(f"chromium unavailable: {e}")
    context = browser.new_context(viewport={"width": 1152, "height": 625}, **ctx)
    if plain:
        context.add_init_script("window.__dgmMorph = true;")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(page_file.as_uri())
    return browser, page, errors


def test_a_plantuml_new_old_swap_slides_the_boxes_and_glows_what_changed(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    steps = {}
    with sync.sync_playwright() as p:
        browser, page, errors = _open_puml(p, tmp_path)
        try:
            for name, click in (("diff>new", 'u[data-view="new"]'), ("new>old", 'u[data-view="old"]'),
                                ("old>new", 'u[data-view="new"]'), ("new>diff", 'button[data-go="diff"]')):
                page.click('.dgmbar ' + click)
                page.wait_for_timeout(40)
                steps[name] = page.evaluate(PUML_MID)
                page.wait_for_timeout(1900)
                steps[name]["left"] = page.evaluate(LEFTOVERS)
            page.click('.dgmbar u[data-view="old"]')
            page.wait_for_timeout(1900)
            morphed = page.evaluate(PUML_LAYOUT)
        finally:
            browser.close()
    assert not errors
    # Diff -> New: the neighbour arrives and glows, the changed pair slides to its new spot.
    assert steps["diff>new"]["arriving"] == ["Pet"] and steps["diff>new"]["glowing"] == ["Pet"]
    assert steps["diff>new"]["moving"] == ["Vet", "Visit"]
    # New -> Old: same boxes, all slide; the box whose content changed glows; no line was gained.
    assert steps["new>old"]["state"] == "old" and steps["new>old"]["arriving"] == []
    assert steps["new>old"]["moving"] == ["Pet", "Vet", "Visit"] and steps["new>old"]["glowing"] == ["Visit"]
    # Old -> New: and now the association Visit -> Vet is gained between two boxes already there.
    assert steps["old>new"]["glowing"] == ["Visit", "e1>e2"]
    # New -> Diff: the neighbour leaves as a ghost.
    assert steps["new>diff"]["ghost"] == ["Pet"]
    assert all(s["left"] == 0 for s in steps.values()), "the morph must leave nothing behind"
    with sync.sync_playwright() as p:
        browser, page, _ = _open_puml(p, tmp_path, plain=True)
        try:
            page.click('.dgmbar u[data-view="old"]')
            plain = page.evaluate(PUML_LAYOUT)
        finally:
            browser.close()
    assert morphed == plain


def test_reduced_motion_on_a_plantuml_swap_glows_but_does_not_slide(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        browser, page, errors = _open_puml(p, tmp_path, reduced_motion="reduce")
        try:
            page.click('.dgmbar u[data-view="old"]')
            page.wait_for_timeout(1700)
            page.click('.dgmbar u[data-view="new"]')
            page.wait_for_timeout(30)
            mid = page.evaluate(PUML_MID)
            page.wait_for_timeout(1700)
            left = page.evaluate(LEFTOVERS)
        finally:
            browser.close()
    assert not errors
    assert mid["moving"] == [] and mid["glowing"] == ["Visit", "e1>e2"] and left == 0
