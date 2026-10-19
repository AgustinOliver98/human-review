#!/usr/bin/env python3
"""Every icon beside a title is centred on the title's capitals.

Victor asked three times on 7 Oct 2026: the rerun rings after a tab's title sat high. The
nudges that had been tried measured the title's line box, whose middle is half an x-height
above the baseline; a title is read by its capitals, which reach higher. This test measures
what the eye uses: the middle of the capitals (baseline − cap-height/2, from canvas
`measureText`) against the ring's geometric centre (the gear's centre, where the eye
puts it, not the ink box the arrow-head stretches), and fails at more than half a CSS px:
the 1.5px nudge it replaced still left the ring .7px high, the Data card 1.45px low.

The page is the real stylesheet around each title row the build draws a ring into — a
tab's `h2.tabtitle`, a Data card's `.head`, the Demo tab's `.vidhead` with its narration
voices — so it needs no build and no server.

Run with:  python3 -m pytest test_title_icons_centred.py
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

RING = ('<button type="button" class="chip chip-rerun chip-served tabrerun">'
        '<span class="rr-ico"><svg class="rr-ring" viewBox="0 0 24 24"><path d="M18.5 5.5A9.2 9.2 0 1 1 5.5 5.5" '
        'fill="none" stroke="currentColor" stroke-width="2.4"/></svg><span class="rr-mark">⚙️</span></span></button>')
GROUP = f'<span class="tabre">{RING}{RING.replace("chip-served", "chip-rerun-ai")}</span>'
VOICES = ('<div class="voice-switch" role="radiogroup">'
          + "".join(f'<label><input type="radio" name="v"{" checked" if i == 0 else ""}> '
                    f'<span class="vs-emoji">{e}</span></label>' for i, e in enumerate("👩🐘🌍"))
          + "</div>")

PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><style>{assets.CSS}</style></head>
<body><div class="wrap">
<section class="panel" id="sequence" style="display:block"><h2 class="tabtitle" data-case="tab title">Sequence diagrams{GROUP}</h2></section>
<section class="panel" id="data" style="display:block"><div class="diagram"><div class="head" data-case="data card"><b>Domain Model</b>{GROUP}</div></div></section>
<section class="panel" id="behaviour" style="display:block"><div class="vidwrap"><video></video>
<div class="vidside"><div class="vidhead" data-case="intro"><h2 class="tabtitle">Intro{GROUP}</h2>{VOICES}</div></div></div></section>
</div></body></html>"""

MEASURE = """() => {
  const cv = document.createElement('canvas').getContext('2d');
  return [...document.querySelectorAll('[data-case]')].map(row => {
    const title = row.matches('h2') ? row : row.querySelector('h2, b');
    const t = [...title.childNodes].find(n => n.nodeType === 3 && n.nodeValue.trim());
    const rg = document.createRange(); rg.selectNodeContents(t); const r = rg.getBoundingClientRect();
    const cs = getComputedStyle(title); cv.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const m = cv.measureText('H');
    const base = r.top + (r.height - m.fontBoundingBoxAscent - m.fontBoundingBoxDescent) / 2 + m.fontBoundingBoxAscent;
    const capMid = base - m.actualBoundingBoxAscent / 2;
    const mid = e => { const b = e.getBoundingClientRect(); return (b.top + b.bottom) / 2 - capMid; };
    return { case: row.dataset.case, titleTop: r.top,
             rings: [...row.querySelectorAll('svg.rr-ring')].map(mid),
             voices: [...row.querySelectorAll('.voice-switch label')].map(l => ({
               dy: mid(l), top: l.getBoundingClientRect().top,
               border: getComputedStyle(l).borderTopWidth, radius: getComputedStyle(l).borderTopLeftRadius })) };
  });
}"""


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    sync = pytest.importorskip("playwright.sync_api")
    page_file = tmp_path_factory.mktemp("align") / "page.html"
    page_file.write_text(PAGE, encoding="utf-8")
    with sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # no browser downloaded for this interpreter
            pytest.skip(f"chromium unavailable: {e}")
        try:
            page = browser.new_page(viewport={"width": 1152, "height": 625}, device_scale_factor=2)
            page.goto(page_file.as_uri())
            page.add_style_tag(content=".vidwrap{display:grid;grid-template-columns:1fr 19rem;gap:1rem}")
            return {r["case"]: r for r in page.evaluate(MEASURE)}
        finally:
            browser.close()


@pytest.mark.parametrize("case", ["tab title", "data card", "intro"])
def test_the_rings_sit_on_the_middle_of_the_titles_capitals(rows, case):
    rings = rows[case]["rings"]
    assert len(rings) == 2
    for dy in rings:
        assert abs(dy) <= .5, f"{case}: ring centre {dy:+.2f}px off the capitals' middle"


def test_each_voice_is_one_pill_on_the_title_row_centred_on_its_capitals(rows):
    voices = rows["intro"]["voices"]
    assert len(voices) == 3
    for v in voices:
        assert v["border"] == "1px" and v["radius"] != "0px", "a radio and its face in one pill"
        assert abs(v["dy"]) <= .5, f"voice pill centre {v['dy']:+.2f}px off the capitals' middle"
        assert v["top"] < rows["intro"]["titleTop"] + 20, "the voices wrapped under the title"
