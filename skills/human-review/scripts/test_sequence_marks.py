"""The Sequence tab's marks (Victor, 19 Oct 2026): the open arrow in the diagram's strongest
ink, the `?`/`values` badge in the SQL marks' colours, the IDE logo where the generator wrote
`↗`, and the DB fixture each test starts from beside its file name."""
from __future__ import annotations

import html
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_review", HERE / "build-review-html.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

ASSETS = HERE / "hrbuild" / "assets"
GENSEQ_CSS = (ASSETS / "css" / "genseq.css").read_text(encoding="utf-8")
GENSEQ_JS = (ASSETS / "genseq.js").read_text(encoding="utf-8")
TESTPAIRS = {"type": "testpairs", "title": "", "snippets": {"auto": "genseq"}}


def test_the_open_arrow_is_in_the_diagrams_own_ink_and_not_bold():
    rule = re.search(r'\.genseq-hot\.genseq-open a\[href\^="genseq:"\] text \{([^}]*)\}',
                     GENSEQ_CSS)
    assert rule and "fill:var(--dgm-fg)" in rule[1] and "font-weight:400" in rule[1]
    assert "font-weight:700; }" not in rule[0]


def test_the_values_badge_and_the_marks_share_one_colour_rule():
    assert 'class="genseq-toggle genseq-value"' in GENSEQ_JS
    toggle = re.search(r"#genseq-panel \.genseq-toggle \{([^}]*)\}", GENSEQ_CSS)[1]
    assert "background" not in toggle and "color" not in toggle, "no second copy of it"
    colours = [c.strip() for c in re.findall(r"#genseq-panel \.genseq-value \{([^}]*)\}", GENSEQ_CSS)]
    assert colours == ["background:var(--link); color:var(--card); font-weight:700;"]


# ── the DB fixture dot ───────────────────────────────────────────────────────────────

FEATURE = """Feature: Search owners

  @fixture:green
  Scenario: Searching on the green data
    When I open the owners page

  Scenario: Adding its own owner
    When I add an owner
"""


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                   check=True, capture_output=True)


def _puml(test_rel: str, line: int, title: str, label: str = "GET /api/owners") -> str:
    return ("@startuml\n"
            f"title [[src://{test_rel}:{line}{{Click to open the test}} {title}]]\n"
            "participant Browser\nparticipant Backend\n"
            f"Browser -> Backend: {label}\n@enduml\n")


def _repo(tmp_path: Path) -> Path:
    feat = "e2e/src/search.feature"
    (tmp_path / "e2e/src").mkdir(parents=True)
    (tmp_path / "e2e/generated").mkdir(parents=True)
    (tmp_path / "be/db/fixtures").mkdir(parents=True)
    (tmp_path / "be/db/fixtures/green.sql").write_text("-- green")
    (tmp_path / "be/db/fixtures/fixture-colors.json").write_text('{"green": "#2fa84f"}')
    (tmp_path / feat).write_text(FEATURE)
    (tmp_path / "e2e/generated/search.feature.green.genseq.puml").write_text(
        _puml(feat, 4, "Searching on the green data"))
    (tmp_path / "e2e/generated/search.feature.own.genseq.puml").write_text(
        _puml(feat, 7, "Adding its own owner"))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "c")
    review = tmp_path / ".human-review"
    (review / "assets").mkdir(parents=True)
    return review


def _summaries(out: str) -> dict[str, str]:
    return {re.search(r"Searching on the green data|Adding its own owner", s)[0]: s
            for s in re.findall(r"<summary data-tip=.*?</summary>", out, re.S)}


def test_each_pair_wears_the_tests_tab_dot_for_the_fixture_its_test_starts_from(tmp_path):
    review = _repo(tmp_path)
    out = build.render_testpairs(TESTPAIRS, {}, [], tmp_path, review)[0]
    rows = _summaries(out)
    green = rows["Searching on the green data"]
    # At the right end, just before the file name — not in the middle of the sentence.
    assert re.search(r'Searching on the green data<span class="seqlang"><span class="fx-dot"'
                     r' role="img"[^>]*data-tip="DB Fixture: green"[^>]*data-fixture="green"'
                     r'[^>]*style="--fx:#2fa84f"></span><a class="srcref seqfile"', green), green
    own = rows["Adding its own owner"]
    assert 'class="fx-dot fx-free"' in own, "on the seed, leaning on none of its rows: a ring"
    assert "DB Fixture: Default · doesn’t rely on its rows" in own


def test_the_test_class_is_set_apart_from_the_test_it_runs():
    """`AddVisitApiTest: adds a visit…` read as one bold string; the class goes quiet
    behind a chevron and the scenario keeps the row (Victor, 19 Oct 2026). Prose titles
    — E2E scenarios — have no class, and a colon in prose is not one."""
    junit = build._pair_title(["VisitTest: create_withoutVet()"])
    assert junit == ('<span class="seqtitle"><span class="seqcls">VisitTest</span>'
                     '<span class="seqsep">›</span>create_withoutVet()</span>')
    both = build._pair_title(["VisitTest: a()", "VisitTest: b()"])
    assert both.count("seqcls") == 1 and "a() · b()" in both, "one class, named once"
    for prose in ("Searching with an empty last name lists every owner",
                  "Owner search: an empty name lists everyone"):
        assert build._pair_title([prose]) == html.escape(prose)
    css = (Path(build.__file__).parent / "hrbuild/assets/css/sequence.css").read_text()
    assert ".seqcls { color:var(--muted); font-weight:400; }" in css
    assert "details.testpair > summary::before { margin-right:-.05rem; }" in css, \
        "the caret sits half as far from the kind chip as core.css's folds do"


def test_a_test_the_verdicts_do_not_name_gets_no_dot(tmp_path, monkeypatch):
    review = _repo(tmp_path)
    for name in ("fixtures_by_test", "fixtures_emptied"):
        monkeypatch.setattr(f"hrbuild.tabs.sequence.{name}", lambda root: {})
    monkeypatch.setattr("hrbuild.tabs.sequence.fixtures_free", lambda root: [])
    out = build.render_testpairs(TESTPAIRS, {}, [], tmp_path, review)[0]
    assert "fx-dot" not in out


def test_a_jvm_verdict_keyed_on_the_annotation_still_reaches_the_method_the_diagram_names(
        tmp_path, monkeypatch):
    """The diagram's handle names the method's line; a verdict may be keyed on `@Test`,
    two annotation lines up. Code in between is another test's, and gets nothing."""
    rel = "be/src/test/java/AddVisitTest.java"
    (tmp_path / "be/src/test/java").mkdir(parents=True)
    (tmp_path / rel).write_text("class AddVisitTest {\n"            # 1
                                "    @Test\n"                       # 2
                                "    @Order(1)\n"                   # 3
                                "    void adds() {}\n"              # 4
                                "    void other() {}\n"             # 5
                                "    void third() {}\n")            # 6
    (tmp_path / "gen").mkdir()
    (tmp_path / "gen/AddVisitTest.java.adds.genseq.puml").write_text(_puml(rel, 4, "adds"))
    (tmp_path / "gen/AddVisitTest.java.third.genseq.puml").write_text(_puml(rel, 6, "third"))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "c")
    review = tmp_path / ".human-review"
    (review / "assets").mkdir(parents=True)
    monkeypatch.setattr("hrbuild.tabs.sequence.fixtures_by_test",
                        lambda root: {f"{rel}:2": "seed"})
    monkeypatch.setattr("hrbuild.tabs.sequence.fixtures_free", lambda root: [])
    monkeypatch.setattr("hrbuild.tabs.sequence.fixtures_emptied", lambda root: {})
    out = build.render_testpairs(TESTPAIRS, {}, [], tmp_path, review)[0]
    rows = re.findall(r"<summary data-tip=.*?</summary>", out, re.S)
    adds = next(r for r in rows if "adds" in r)
    third = next(r for r in rows if "third" in r)
    assert 'data-tip="DB Fixture: Default"' in adds
    assert "fx-dot" not in third


# ── the IDE logo instead of `↗` ──────────────────────────────────────────────────────

def test_the_tab_hands_genseq_js_the_two_ide_logos_once(tmp_path):
    review = _repo(tmp_path)
    out = build.render_testpairs(TESTPAIRS, {}, [], tmp_path, review)[0]
    assert out.count('<template id="seq-ide-marks">') == 1
    tpl = out[out.index('<template id="seq-ide-marks">'):]
    assert build.VSC_ICON in tpl and build.IJ_ICON in tpl


PAGE = """<!doctype html><html><head><style>{css}</style></head><body>
<div class="diagram"><div class="svgbox"><svg xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 400 100" width="400" height="100">
  <g class="message"><a href="vscode://file//x/OwnerRepository.java:19:1">
    <text font-size="13" x="10" y="30">OwnerRepository.save &#8599;</text></a></g>
  <g class="message"><a href="https://example.org/">
    <text font-size="13" x="10" y="60">elsewhere &#8599;</text></a></g>
</svg></div></div>
{tpl}
<script>window.HR = {{onready: function (fn) {{ fn(null); }}}};</script>
<script>{js}</script></body></html>"""


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                       # no chromium installed on this box
            pytest.skip(f"chromium unavailable: {e}")
        yield b
        b.close()


def test_the_arrow_ends_in_the_picked_ides_logo_where_it_used_to_end_in_an_arrow(
        browser, tmp_path):
    page_file = tmp_path / "p.html"
    page_file.write_text(PAGE.format(
        css=GENSEQ_CSS, js=GENSEQ_JS,
        tpl=f'<template id="seq-ide-marks">{build.VSC_ICON}{build.IJ_ICON}</template>'),
        encoding="utf-8")
    page = browser.new_page()
    try:
        page.goto(page_file.as_uri())
        got = page.evaluate("""() => {
          const texts = [...document.querySelectorAll('svg text')];
          const label = texts[0].getBBox();
          const marks = [...document.querySelectorAll('.seq-ide svg')];
          const shown = () => marks.filter(m => getComputedStyle(m).display !== 'none')
                                   .map(m => m.getAttribute('class'));
          const off = shown();
          document.documentElement.classList.add('ide-idea');
          const idea = shown();
          return {texts: texts.map(t => t.textContent), groups: document.querySelectorAll('.seq-ide').length,
                  inLink: !!document.querySelector('a[href^="vscode:"] .seq-ide'),
                  after: marks.every(m => +m.getAttribute('x') >= label.x + label.width),
                  off, idea, noide: document.documentElement.classList.contains('seq-noide')};
        }""")
    finally:
        page.close()
    assert got["texts"] == ["OwnerRepository.save", "elsewhere"], "no ↗ left anywhere"
    assert got["groups"] == 1 and got["inLink"], "a logo only on a link into a file"
    assert got["after"], "after the label's end"
    assert got["off"] == ["vsc-ico"] and got["idea"] == ["ij-ico"]
    assert not got["noide"], "top level, off disk: the click reaches the IDE"


def test_one_diagram_of_several_scenarios_on_one_start_still_gets_its_dot(tmp_path):
    """A per-file diagram (`== … ==` chapters) names several scenarios; on the same start
    they are one dot, not none."""
    feat = "e2e/src/two.feature"
    (tmp_path / "e2e/src").mkdir(parents=True)
    (tmp_path / feat).write_text("Feature: f\n\n  Scenario: one\n    When x\n\n"
                                 "  Scenario: two\n    When y\n")
    (tmp_path / "e2e/src/two.feature.genseq.puml").write_text(
        "@startuml\nparticipant A\nparticipant B\n"
        f"== [[src://{feat}:3{{t}} one]] ==\nA -> B: x\n"
        f"== [[src://{feat}:6{{t}} two]] ==\nA -> B: y\n@enduml\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "c")
    review = tmp_path / ".human-review"
    (review / "assets").mkdir(parents=True)
    out = build.render_testpairs(TESTPAIRS, {}, [], tmp_path, review)[0]
    assert out.count('class="fx-dot fx-free"') == 1, out[:2000]
