#!/usr/bin/env python3
"""A rebuild swaps the tabs it changed into an open served page, instead of reloading it.

`review.html` stays one file. The build also writes it cut along its tabs
(`hrbuild/shared/panels.py`): `tabs/<id>.html` per tab and `tabs/tabs.json`, the manifest;
each panel carries its hash, `<html>` the hash of everything else (the shell). The server
hands the manifest over with the watch stamp (`serve-review.py`), and the page swaps the
tabs whose hashes moved (`assets/panels.js`) — or reloads, when the shell moved, the tabs
are not the same tabs, or a changed tab runs a script that cannot be re-run in place.

Three layers, three kinds of test: the cut (string in, hashes and pieces out), the server's
answer, and — when Playwright is installed — a real browser on a real served page: scroll
and fold one tab, rebuild a change into another, and the page must not have navigated.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hrbuild.shared import panels as P  # noqa: E402


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("serve_review_panels", "serve-review.py")


# --------------------------------------------------------------------------- #
# the cut
# --------------------------------------------------------------------------- #

def _doc(a="<p>A body</p>", b="<p>B body</p>", badge="1", title="t", script="shell()"):
    """The shape the orchestrator writes, reduced to what the cut reads."""
    return (
        '<!doctype html>\n<html lang="en"><head><title>' + title + '</title><style>x</style>'
        '</head>\n<body><div class="wrap"><div class="masthead"><div class="tabstrip" '
        'role="tablist" aria-label="Review sections">'
        '<button type="button" class="tab" role="tab" id="tabbtn-a" aria-controls="a" '
        f'aria-selected="false" tabindex="-1">A<span class="n">{badge}</span></button>'
        '<button type="button" class="tab" role="tab" id="tabbtn-b" aria-controls="b" '
        'aria-selected="false" tabindex="-1">B</button></div></div>\n'
        f'<section class="panel" id="a" role="tabpanel" aria-labelledby="tabbtn-a">{a}</section>\n'
        f'<section class="panel" id="b" role="tabpanel" aria-labelledby="tabbtn-b">{b}</section>\n'
        '<footer><p>f</p></footer>\n</div>\n'
        f'<script>{script}</script>\n</body></html>\n'
    )


def _stamp(doc, out_dir, actions=None):
    return P.stamp_panels(doc, out_dir, "review.html", actions=actions or {})


def _hashes(stamped):
    m = stamped["manifest"]
    return m["shell"], {t["id"]: t["hash"] for t in m["tabs"]}


def test_every_panel_and_the_shell_carry_their_hash(tmp_path):
    doc, st = _stamp(_doc(), tmp_path)
    m = st["manifest"]
    assert m["version"] == P.PANELS_VERSION and m["page"] == "review.html"
    assert [t["id"] for t in m["tabs"]] == ["a", "b"]
    assert all(t["swappable"] for t in m["tabs"])
    assert f'<html data-hr-shell="{m["shell"]}" lang="en">' in doc
    for t in m["tabs"]:
        # Last in the opening tag, so every reader matching `<section class="panel" id=…`
        # (refresh-card.py, half the tests) still matches.
        opening = (f'<section class="panel" id="{t["id"]}" role="tabpanel" '
                   f'aria-labelledby="tabbtn-{t["id"]}" data-hr-hash="{t["hash"]}">')
        assert opening in doc
        assert st["sections"][t["id"]].startswith(opening)
        assert st["sections"][t["id"]] in doc, "a piece is not byte for byte the panel"
        assert t["pill"].startswith(f'<button type="button" class="tab" role="tab" id="tabbtn-{t["id"]}"')


def test_a_change_in_one_tab_moves_that_tab_s_hash_only(tmp_path):
    shell, tabs = _hashes(_stamp(_doc(), tmp_path)[1])
    shell2, tabs2 = _hashes(_stamp(_doc(b="<p>B, rebuilt</p>"), tmp_path)[1])
    assert shell2 == shell
    assert tabs2["a"] == tabs["a"] and tabs2["b"] != tabs["b"]


def test_a_pill_is_part_of_its_tab_not_of_the_shell(tmp_path):
    """The count on a pill changes with its tab's content; were it shell, every finding
    added would reload the page."""
    shell, tabs = _hashes(_stamp(_doc(), tmp_path)[1])
    shell2, tabs2 = _hashes(_stamp(_doc(badge="2"), tmp_path)[1])
    assert shell2 == shell and tabs2["a"] != tabs["a"] and tabs2["b"] == tabs["b"]


@pytest.mark.parametrize("change", [{"title": "other"}, {"script": "shell(2)"}])
def test_a_change_to_what_every_tab_shares_moves_the_shell(tmp_path, change):
    shell, tabs = _hashes(_stamp(_doc(), tmp_path)[1])
    shell2, tabs2 = _hashes(_stamp(_doc(**change), tmp_path)[1])
    assert shell2 != shell and tabs2 == tabs


def test_a_new_action_moves_the_shell_and_a_reworded_command_does_not(tmp_path):
    """The page learns which actions the server runs once, from its probe; the command
    behind one is the server's to read at each press."""
    shell, _ = _hashes(_stamp(_doc(), tmp_path, {"x": {"command": "true"}})[1])
    shell2, _ = _hashes(_stamp(_doc(), tmp_path, {"x": {"command": "true"}, "y": {}})[1])
    shell3, _ = _hashes(_stamp(_doc(), tmp_path, {"x": {"command": "cd /elsewhere && true"}})[1])
    assert shell2 != shell and shell3 == shell


def test_a_file_the_panel_shows_by_reference_is_part_of_its_hash(tmp_path):
    (tmp_path / "assets").mkdir()
    pic = tmp_path / "assets" / "d.svg"
    pic.write_text("<svg>1</svg>")
    a = '<img src="assets/d.svg">'
    _, tabs = _hashes(_stamp(_doc(a=a), tmp_path)[1])
    pic.write_text("<svg>2</svg>")
    _, tabs2 = _hashes(_stamp(_doc(a=a), tmp_path)[1])
    assert tabs2["a"] != tabs["a"] and tabs2["b"] == tabs["b"]


def test_a_panel_running_its_own_script_is_not_swappable_unless_it_says_how(tmp_path):
    plain = '<script>\n// wires the widget\nvar x = 1;</script>'
    data = '<script type="application/json" id="d">{"a": 1}</script>'
    keep = '<script data-hr-swap="keep">document.addEventListener("click", f);</script>'
    rerun = '<script data-hr-swap="rerun">wire(document.currentScript.parentNode);</script>'
    _, st = _stamp(_doc(a=plain, b=data + keep + rerun), tmp_path)
    a, b = st["manifest"]["tabs"]
    assert a["swappable"] is False and a["blockers"] == ["// wires the widget"]
    assert b["swappable"] is True and "blockers" not in b
    _, st = _stamp(_doc(a='<script src="https://cdn.example/x.js"></script>'), tmp_path)
    assert st["manifest"]["tabs"][0]["blockers"] == ["https://cdn.example/x.js"]


def test_stamping_a_stamped_page_changes_nothing(tmp_path):
    """`refresh-card.py` splices a card into a finished page and stamps it again."""
    once, st = _stamp(_doc(), tmp_path)
    twice, st2 = _stamp(once, tmp_path)
    assert twice == once and st2 == st


def test_a_page_that_does_not_cut_cleanly_is_left_whole(tmp_path):
    assert P.stamp_panels("<html><body><p>no tabs</p></body></html>", tmp_path, "r.html") \
        == ("<html><body><p>no tabs</p></body></html>", None)
    lying = _doc().replace('id="tabbtn-b" aria-controls="b"', 'id="tabbtn-c" aria-controls="c"')
    assert P.split_panels(lying) is None
    unclosed = _doc().replace("<p>B body</p></section>", "<p>B body</p>")
    assert P.split_panels(unclosed) is None


def test_the_pieces_are_written_then_the_manifest_and_stale_ones_go(tmp_path):
    _, st = _stamp(_doc(), tmp_path)
    folder = tmp_path / P.PANELS_DIR
    folder.mkdir()
    (folder / "gone.html").write_text("old tab")
    P.write_panels(tmp_path, st)
    assert sorted(p.name for p in folder.iterdir()) == ["a.html", "b.html", "tabs.json"]
    m = P.read_panels_manifest(tmp_path)
    assert m == st["manifest"]
    for t in m["tabs"]:
        text = (folder / f'{t["id"]}.html').read_text(encoding="utf-8")
        first, rest = text.split("\n", 1)
        assert first == f'<!-- hr-tab {t["id"]} {t["hash"]} -->'
        assert rest.rstrip("\n") == st["sections"][t["id"]]
    # An unchanged piece is not rewritten: the watcher sees only what moved.
    before = (folder / "a.html").stat().st_mtime_ns
    time.sleep(0.01)
    _, st2 = _stamp(_doc(b="<p>B again</p>"), tmp_path)
    P.write_panels(tmp_path, st2)
    assert (folder / "a.html").stat().st_mtime_ns == before
    # And a page that cannot be cut takes the manifest away rather than leave one that
    # describes another page.
    P.write_panels(tmp_path, None)
    assert P.read_panels_manifest(tmp_path) is None


def test_restamp_after_an_in_place_edit_follows_the_panel_it_touched(tmp_path):
    doc, st = _stamp(_doc(), tmp_path)
    (tmp_path / "review.html").write_text(doc.replace("<p>A body</p>", "<p>A, card redrawn</p>"))
    (tmp_path / ".actions.json").write_text(json.dumps({"version": 1, "actions": {}}))
    P.write_panels(tmp_path, st)
    assert P.restamp_page(tmp_path)
    m = P.read_panels_manifest(tmp_path)
    assert m["shell"] == st["manifest"]["shell"]
    assert m["tabs"][0]["hash"] != st["manifest"]["tabs"][0]["hash"]
    assert m["tabs"][1]["hash"] == st["manifest"]["tabs"][1]["hash"]
    assert f'data-hr-hash="{m["tabs"][0]["hash"]}"' in (tmp_path / "review.html").read_text()


# --------------------------------------------------------------------------- #
# the server's answer
# --------------------------------------------------------------------------- #

def test_the_server_reads_the_manifest_where_the_build_writes_it():
    assert sr.PANELS_MANIFEST == Path(P.PANELS_DIR) / P.PANELS_MANIFEST


def test_the_watch_answer_carries_the_manifest_of_the_stamp_it_publishes(tmp_path):
    _, st = _stamp(_doc(), tmp_path)
    P.write_panels(tmp_path, st)
    w = sr.Watcher(tmp_path, quiet=0)
    first = w.answer()
    assert first["stamp"] and first["panels"] == st["manifest"]
    _, st2 = _stamp(_doc(b="<p>B, rebuilt</p>"), tmp_path)
    P.write_panels(tmp_path, st2)
    # Not before the stamp moves: a manifest ahead of its stamp would name pieces the
    # page is not yet being told to fetch.
    w.tick(now=time.time())
    assert w.answer()["panels"] == st["manifest"]
    w.tick(now=time.time() + 1)
    second = w.answer()
    assert second["stamp"] != first["stamp"] and second["panels"] == st2["manifest"]


def test_no_manifest_or_a_broken_one_is_none(tmp_path):
    assert sr.read_panels(tmp_path) is None
    (tmp_path / "tabs").mkdir()
    (tmp_path / "tabs" / "tabs.json").write_text("{half")
    assert sr.read_panels(tmp_path) is None
    assert sr.Watcher(tmp_path).answer()["panels"] is None


# --------------------------------------------------------------------------- #
# the whole loop: a build, a server, a browser
# --------------------------------------------------------------------------- #

LONG = "".join(f"<p id='a-p{i}'>Alpha paragraph {i}</p>" for i in range(200))


def _content(alpha_top="", beta="Beta first", title="panel swap"):
    return {
        "title": title, "summary": "<p>x</p>",
        "verdict": {"score": 5, "label": "x", "bullets": ["y"]},
        "scope": [{"label": "files", "value": "1", "href": "https://example.invalid"}],
        "findings": [{"title": "f", "body": "b", "severity": "high"}],
        "autofixes": [{"title": "a"}],
        "sections": [
            {"id": "sa", "title": "Alpha", "body": alpha_top
             + "<details id='fold'><summary>Fold</summary><p>inside</p></details>"
             + "<input id='note' type='text'>" + LONG},
            {"id": "sb", "title": "Beta", "body": f"<p class='beta-text'>{beta}</p>"}],
        "tabs": [{"id": "alpha", "label": "Alpha", "blocks": [{"type": "section", "id": "sa"}]},
                 {"id": "beta", "label": "Beta", "blocks": [{"type": "section", "id": "sb"}]}],
    }


def _build(repo: Path, **content):
    review = repo / ".human-review"
    review.mkdir(exist_ok=True)
    (review / "content.json").write_text(json.dumps(_content(**content)), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HERE / "build-review-html.py"),
                           ".human-review/content.json", "--out", ".human-review/review.html"],
                          cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return review


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, check=True, env=env)
    return repo


def test_a_build_writes_its_pieces_beside_the_page(tmp_path):
    review = _build(_repo(tmp_path))
    page = (review / "review.html").read_text(encoding="utf-8")
    m = P.read_panels_manifest(review)
    assert m and m["page"] == "review.html"
    assert f'data-hr-shell="{m["shell"]}"' in page
    assert [t["id"] for t in m["tabs"]][:2] == ["alpha", "beta"]
    for t in m["tabs"]:
        piece = (review / "tabs" / f'{t["id"]}.html').read_text(encoding="utf-8")
        assert piece.split("\n", 1)[1].rstrip("\n") in page


def _free_port():
    for _ in range(50):
        port = random.randint(41000, 59000)
        if sr.free(port):
            return port
    pytest.skip("no free port on loopback")


def test_a_served_page_swaps_the_tab_a_rebuild_changed_and_keeps_the_reader_s_place(tmp_path):
    sync = pytest.importorskip("playwright.sync_api")
    repo = _repo(tmp_path)
    review = _build(repo)
    port = _free_port()
    started = subprocess.run([sys.executable, str(HERE / "serve-review.py"), str(review),
                              "--port", str(port), "--no-open", "--idle-minutes", "5"],
                             capture_output=True, text=True, timeout=30)
    assert started.returncode == 0, started.stderr
    url = started.stdout.strip()
    pid = (sr.probe(port) or {}).get("pid")
    errors = []
    try:
        with sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url + "#alpha")
            page.wait_for_function("window.HR && window.HR.caps && window.HR.caps()")
            page.evaluate("window.__kept = 'still here'")
            page.evaluate("document.getElementById('fold').open = true")
            page.fill("#note", "half a thought")

            def top_of(el_id):
                return page.evaluate(f"document.getElementById('{el_id}').getBoundingClientRect().top")

            def scroll_to(el_id):
                page.evaluate(f"""(() => {{
                  var pin = parseFloat(getComputedStyle(document.documentElement)
                                         .getPropertyValue('--strip-h')) || 0;
                  var el = document.getElementById('{el_id}');
                  window.scrollTo(0, el.getBoundingClientRect().top + pageYOffset - pin - 40);
                }})()""")
                page.wait_for_timeout(100)

            def swapped(n):
                page.wait_for_function(
                    "window.HR.lastCatchUp && window.HR.lastCatchUp.how === 'swapped in place'"
                    f" && (window.__swaps || 0) >= {n}",
                    timeout=90000)

            page.evaluate("""document.addEventListener('hr:swapped', function () {
                               window.__swaps = (window.__swaps || 0) + 1; })""")
            scroll_to("a-p120")
            before = top_of("a-p120")

            # 1. A change in the other tab: swapped in place, nothing here moves.
            _build(repo, beta="Beta second")
            swapped(1)
            assert page.evaluate("window.__kept") == "still here", "the page reloaded"
            assert page.evaluate("performance.getEntriesByType('navigation').length") == 1
            assert "beta" in page.evaluate("window.HR.lastCatchUp.tabs")
            assert "alpha" not in page.evaluate("window.HR.lastCatchUp.tabs")
            assert page.text_content("#beta .beta-text") == "Beta second"
            assert page.evaluate("document.getElementById('fold').open") is True
            assert page.input_value("#note") == "half a thought"
            assert abs(top_of("a-p120") - before) < 2
            assert page.get_attribute("#tabbtn-alpha", "aria-selected") == "true"

            # 2. A change in the tab being read, above where the reader is: swapped too,
            # and the paragraph they were reading stays where it was on screen.
            swaps = page.evaluate("window.__swaps")
            _build(repo, alpha_top="<p id='added'>" + "New at the top. " * 80 + "</p>",
                   beta="Beta second")
            swapped(swaps + 1)
            assert page.evaluate("window.__kept") == "still here", "the page reloaded"
            assert "alpha" in page.evaluate("window.HR.lastCatchUp.tabs")
            assert page.locator("#added").count() == 1
            assert page.evaluate("document.getElementById('fold').open") is True
            assert page.input_value("#note") == "half a thought"
            assert abs(top_of("a-p120") - before) < 2, "the reader lost their place"
            assert page.get_attribute("#tabbtn-alpha", "aria-selected") == "true"

            # 3. A change every tab shares (the head, the masthead): a full reload.
            with page.expect_navigation(timeout=90000):
                _build(repo, alpha_top="<p id='added'>x</p>", beta="Beta second",
                       title="panel swap, retitled")
            page.wait_for_function("window.HR && window.HR.caps && window.HR.caps()")
            assert page.evaluate("window.__kept") is None
            assert "the shell changed" in page.evaluate("window.HR.lastCatchUp.how")
            browser.close()
    finally:
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    assert errors == []


# --------------------------------------------------------------------------- #
# the two tabs that run the most of their own script: Tests and Review
# --------------------------------------------------------------------------- #

def _tests_and_review_repo(tmp_path, version=1):
    """A repository with a real requirements matrix (semcov's own test project), a Review
    tab whose finding carries a fold, and the two tabs the swap is about."""
    sem = _load("test_semcov_for_panels", "test_semcov.py")
    root = tmp_path / "repo"
    if not root.is_dir():
        root, review = sem._repo(tmp_path)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True, env=env)
        spec = json.loads((review / "content.json").read_text(encoding="utf-8"))
        g, entries, frag, _ = sem._render(tmp_path)
        (review / "assets" / "requirements-map.v1.html").write_text(frag, encoding="utf-8")
        (review / "content.base.json").write_text(json.dumps(spec), encoding="utf-8")
    review = root / ".human-review"
    frag = (review / "assets" / "requirements-map.v1.html").read_text(encoding="utf-8")
    if version > 1:
        frag += f'<p class="tests-probe">rebuilt {version}</p>'
    (review / "assets" / "requirements-map.html").write_text(frag, encoding="utf-8")
    spec = json.loads((review / "content.base.json").read_text(encoding="utf-8"))
    spec.update({
        "title": "panel swap, tests", "summary": "<p>x</p>",
        "verdict": {"score": 5, "label": "x", "bullets": ["y"]},
        "scope": [{"label": "files", "value": "1", "href": "https://example.invalid"}],
        "findings": [{"title": "The vet is not checked", "severity": "high",
                      "body": f"<p>Seen in build {version}, at <a class='srcref' "
                              f"href='vscode://file/{root}/src/Visit.java:3'>Visit.java:3</a>."
                              "</p><details id='ffold'>"
                              "<summary>Why</summary><p>Because.</p></details>"}],
        "autofixes": [{"title": "a"}],
        "sections": [{"id": "requirements-map", "title": "",
                      "includeHtml": "assets/requirements-map.html", "includeFirst": True}],
        "tabs": [{"id": "review", "label": "Review", "count": True,
                  "blocks": [{"type": "findings"}, {"type": "autofixes"}]},
                 {"id": "requirements", "label": "Tests",
                  "blocks": [{"type": "section", "id": "requirements-map"}]}],
    })
    (review / "content.json").write_text(json.dumps(spec), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HERE / "build-review-html.py"),
                           ".human-review/content.json", "--out", ".human-review/review.html"],
                          cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return root, review


def test_the_tests_and_review_tabs_swap_with_the_reader_s_state(tmp_path):
    """A picked sentence and its wires, an open chapter, Show all, the overlay scrollbars,
    an open finding fold and the clickable finding titles all survive a rebuild that
    changes both tabs — re-derived by the tabs' own scripts, run again over the new markup."""
    sync = pytest.importorskip("playwright.sync_api")
    root, review = _tests_and_review_repo(tmp_path)
    m = P.read_panels_manifest(review)
    assert all(t["swappable"] for t in m["tabs"]), [t.get("blockers") for t in m["tabs"]]
    port = _free_port()
    started = subprocess.run([sys.executable, str(HERE / "serve-review.py"), str(review),
                              "--port", str(port), "--no-open", "--idle-minutes", "5"],
                             capture_output=True, text=True, timeout=30)
    assert started.returncode == 0, started.stderr
    url = started.stdout.strip()
    pid = (sr.probe(port) or {}).get("pid")
    errors = []
    STATE = """() => {
      var q = s => document.querySelector(s), all = s => document.querySelectorAll(s);
      var pick = q('#requirements .rm-f[aria-current="true"]');
      var box = q('#requirements .rm-tkhead input[type=checkbox]');
      return {
        pick: pick ? pick.dataset.s : null,
        hits: all('#requirements .rm-t[data-hit="yes"]').length,
        wired: (q('#requirements [data-wired]') || {dataset: {}}).dataset.wired || null,
        chapters: [].map.call(all('#requirements .rm-chh'), h => h.getAttribute('aria-expanded')).join(','),
        showAll: box ? box.checked : null,
        rows: all('#requirements .rm-t').length,
        bars: all('#requirements .rm-ovbar').length,
        pops: all('.rm-covpop').length,
        fold: q('#ffold') ? q('#ffold').open : null,
        opens: all('#review .f-title.opens').length,
      };
    }"""
    try:
        with sync.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1300, "height": 850})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url + "#review")
            page.wait_for_function("window.HR && window.HR.caps && window.HR.caps()")
            page.evaluate("window.__kept = 'still here'")
            page.evaluate("document.getElementById('ffold').open = true")
            page.click("#tabbtn-requirements")
            page.wait_for_timeout(300)
            # A sentence some test covers, then the chapter it is in, then Show all.
            page.evaluate("""() => {
              var f = [].find.call(document.querySelectorAll('#requirements .rm-f[data-s]'),
                                   x => !x.closest('.rm-legend'));
              f.click(); }""")
            page.evaluate("document.querySelector('#requirements .rm-chh').click()")
            page.evaluate("""() => { var b = document.querySelector(
                '#requirements .rm-tkhead input[type=checkbox]');
                b.checked = true; b.dispatchEvent(new Event('change', {bubbles: true})); }""")
            page.wait_for_timeout(300)
            before = page.evaluate(STATE)
            assert before["pick"] and before["chapters"].startswith("true") and before["showAll"]
            assert before["fold"] is True and before["bars"] == 2 and before["opens"] == 1
            assert before["wired"] == "yes" and before["hits"] >= 1

            _tests_and_review_repo(tmp_path, version=2)
            page.wait_for_function(
                "window.HR.lastCatchUp && window.HR.lastCatchUp.how === 'swapped in place'"
                " && window.HR.lastCatchUp.tabs.indexOf('requirements') >= 0"
                " && window.HR.lastCatchUp.tabs.indexOf('review') >= 0", timeout=90000)
            page.wait_for_timeout(300)
            assert page.evaluate("window.__kept") == "still here", "the page reloaded"
            assert page.locator("#requirements .tests-probe").count() == 1
            assert "Seen in build 2" in page.text_content("#review")
            after = page.evaluate(STATE)
            assert after == before, (before, after)
            browser.close()
    finally:
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    assert errors == []
