#!/usr/bin/env python3
"""The window never scrolls sideways.

The masthead and the tab strip are full-bleed bands, `width:100vw`, and `vw` counts the
vertical scrollbar. Wherever scrollbars take room — a mouse plugged in, "always show" in
System Settings — both bands ran 15px under it, and every tab long enough to scroll grew
a horizontal scrollbar along the bottom of the window. Headless Chromium hides scrollbars
by default, which is why no measurement caught it: this test launches it with them shown
and styles them classic (`::-webkit-scrollbar`), 15px, as a mouse-driven Mac draws them.

The page here is the real stylesheet around a real masthead-shaped band and enough text
to scroll, so it needs no build and no server.

Run with:  python3 -m pytest test_no_page_hscroll.py
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

PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><style>{assets.CSS}</style>
<style>::-webkit-scrollbar{{width:15px;height:15px}}</style></head>
<body><div class="wrap"><header class="masthead"><div class="titlerow oneline"><h1>PR</h1></div>
<nav class="tabstrip"><button class="tab">Review</button></nav></header>
{"<p>a line long enough to be a paragraph of a review</p>" * 400}</div></body></html>"""


@pytest.mark.parametrize("width", [1280, 1728])
def test_the_window_has_no_horizontal_scrollbar(width, tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    page_file = tmp_path / "page.html"
    page_file.write_text(PAGE, encoding="utf-8")
    with sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
        except Exception as e:  # no browser downloaded for this interpreter
            pytest.skip(f"chromium unavailable: {e}")
        try:
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(page_file.as_uri())
            # What the reader sees is the scrollbar, not `scrollWidth`: a clipped viewport
            # still reports the bands' 15px in it. A horizontal bar takes its height out of
            # the viewport, and a sideways wheel is what would move the page if it could.
            page.mouse.move(width / 2, 400)
            page.mouse.wheel(200, 0)
            page.wait_for_timeout(150)
            ch, ih, cw, iw, sx = page.evaluate(
                "() => [document.documentElement.clientHeight, innerHeight, "
                "document.documentElement.clientWidth, innerWidth, scrollX]")
        finally:
            browser.close()
    if cw == iw:
        pytest.skip("this Chromium draws overlay scrollbars; nothing to measure")
    assert ch == ih, f"a horizontal scrollbar takes {ih - ch}px of the window at {width}px"
    assert sx == 0, f"a sideways wheel moved the page {sx}px at {width}px"


# ---------------------------------------------------------------------------------------- #
# Eval run 10: the masthead keeps one row of chips. The review chip wrapped to a second row
# and "8 earlier commits outside the review ▸" took a third: 164px of sticky header on every
# tab against the reference's 108px. The run's own chips, at the two widths a laptop has.
# ---------------------------------------------------------------------------------------- #

def _run10_masthead() -> str:
    from hrbuild.shared import chips, masthead
    state = {"diffBase": "98cb82a7" * 5, "diffBaseSource": "audited",
             "outside": [{"sha": f"{i:040x}", "subject": f"earlier commit {i}"}
                         for i in range(8)]}
    spec = {"pr": {"branch": "hr-claude-10", "base": "main",
                   "repo": "https://github.com/victorrentea/petclinic"}}
    bar = "".join(chips.chip_html(c) for c in [
        {"label": "files", "value": '<span class="added">+6</span> / ✍️26', "tip": "t"},
        {"label": "lines", "value": '<span class="added">+1330</span> / −292', "tip": "t",
         "href": "https://example.com"},
        {"label": "tests", "value": "+54 / −9 / ✍️7", "tip": "t", "href": "#t"},
        {"face": chips.review_chip_face(10, 6, 6), "tip": "t", "href": "#t"}])
    strip = ('<div class="tabstrip" role="tablist"><button type="button" class="tab" '
             'role="tab" aria-controls="p1">Review</button></div>')
    return masthead.masthead_html(spec, "", bar, strip, state)


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 1280])
def test_the_masthead_keeps_its_chips_on_one_row(width, scheme, tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    page_file = tmp_path / "mast.html"
    page_file.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<style>{assets.CSS}</style></head><body><div class="wrap">
<h1>Owners grid: paged and sorted by Name or City (#25)</h1>
{_run10_masthead()}<section class="panel" id="p1">{"<p>text</p>" * 200}</section>
</div>{assets.TABS_JS}</body></html>""", encoding="utf-8")
    with sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # no browser downloaded for this interpreter
            pytest.skip(f"chromium unavailable: {e}")
        try:
            page = browser.new_page(viewport={"width": width, "height": 900},
                                    color_scheme=scheme)
            page.goto(page_file.as_uri())
            # Measured once the fonts are in: a width taken while a fallback face is still
            # standing in is not the width the reader sees, and the "closed" height would be.
            page.wait_for_function("document.fonts.status === 'loaded'")
            page.wait_for_timeout(100)
            measure = ("() => { const m = document.querySelector('.masthead');"
                       " const tops = [...m.querySelectorAll('.scopebar > *')]"
                       "   .map(c => Math.round(c.getBoundingClientRect().top));"
                       " return [new Set(tops).size, Math.round(m.getBoundingClientRect().height),"
                       "   document.getElementById('hr-outside').hidden]; }")
            rows, closed, hidden = page.evaluate(measure)
            assert rows == 1, f"the scope bar wrapped to {rows} rows at {width}px"
            assert hidden, "the earlier commits are folded until asked for"
            page.click(".sn-badge")
            _, opened, hidden = page.evaluate(measure)
            assert not hidden and opened > closed, "opened, the list sits in flow"
            page.keyboard.press("Escape")
            _, after, hidden = page.evaluate(measure)
            assert hidden and abs(after - closed) <= 1, "Esc closes it and gives the height back"
            page.click(".sn-badge")
            page.mouse.click(width / 2, 800)
            assert page.evaluate(measure)[2], "a click outside closes it"
        finally:
            browser.close()


# ---------------------------------------------------------------------------------------- #
# The API tab on a phone. A property path oasdiff names is one unbroken word —
# `items/pets/items/visits/items/vetFirstName` — and the change row is a flex line, whose
# text item will not shrink below its longest word: at 390px the row ran 61px past the
# window and the whole page scrolled sideways. The row lives in the shadow root the page
# moves `openapi-visual-diff.html` into, styled only by that producer's own stylesheet, so
# that is what this page is made of: the real page CSS outside, the producer's inside.
# ---------------------------------------------------------------------------------------- #

def _visual_diff_css() -> str:
    import re
    spec = importlib.util.spec_from_file_location("ovd_hscroll", HERE / "openapi-visual-diff.py")
    ovd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ovd)
    return "".join(re.findall(r"<style\b[^>]*>.*?</style>", ovd.TEMPLATE, re.S))


_LONG_PATHS = ("items/pets/items/visits/items/vetFirstName",
               "items/pets/items/visits/items/vetLastName", "pets/items/visits/items/vetId")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_an_api_change_naming_a_deep_property_wraps_on_a_phone(scheme, tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    rows = "".join(
        f'<div class="dv-change l1"><span class="lvl">info</span><span>added the optional '
        f'response property <code>{p}</code> with the <code>200</code> status</span></div>'
        for p in _LONG_PATHS)
    inner = (_visual_diff_css() + '<div class="swagger-ui"><div class="opblock">'
             + rows + "</div></div>")
    page_file = tmp_path / "api.html"
    page_file.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{assets.CSS}</style></head><body><div class="wrap"><section class="panel">
<div class="oavhost" id="embed-swaggerdiff"></div>
<template id="embed-swaggerdiff-tpl">{inner}</template>
<script>(function(){{var h=document.getElementById('embed-swaggerdiff'),
t=document.getElementById('embed-swaggerdiff-tpl');
h.attachShadow({{mode:'open'}}).appendChild(t.content);t.remove();}})();</script>
</section></div></body></html>""", encoding="utf-8")
    with sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # no browser downloaded for this interpreter
            pytest.skip(f"chromium unavailable: {e}")
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844},
                                    color_scheme=scheme)
            page.goto(page_file.as_uri())
            sw, cw, past = page.evaluate(
                "() => { const r = document.getElementById('embed-swaggerdiff').shadowRoot,"
                " W = document.documentElement.clientWidth;"
                " return [document.documentElement.scrollWidth, W,"
                "   [...r.querySelectorAll('.dv-change code')]"
                "     .filter(c => c.getBoundingClientRect().right > W + 1)"
                "     .map(c => c.textContent)]; }")
        finally:
            browser.close()
    assert not past, f"these paths run past a 390px window: {past}"
    assert sw <= cw, f"the page scrolls {sw - cw}px sideways at 390px"
