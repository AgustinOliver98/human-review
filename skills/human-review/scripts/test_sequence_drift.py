"""A scenario is never both drawn and "no diagram yet" on the Sequence tab.

19 Oct 2026: six imports added above `add-visit.spec.ts`'s tagged test moved it from line 31
to 37. Its committed diagram still said 31, so the tab showed it as a drawn row (by the
picture) and again under "no diagram came back" (by the tag at 37). The diagram's line is
now re-anchored on the title it also records.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import time

seq = importlib.import_module("hrbuild.tabs.sequence")

# The tagged Playwright test sits at line 9; its diagram was drawn when it was at line 3.
SPEC = """import {test} from '@playwright/test';
import {a} from './a';
import {b} from './b';
import {c} from './c';
import {d} from './d';
import {e} from './e';
import {f} from './f';

test('Add a visit',
  {tag: [GENERATE_SEQUENCE_TAG]},
  async ({page}) => {
    await page.goto('/owners');
  });

test('Never drawn',
  {tag: [GENERATE_SEQUENCE_TAG]},
  async ({page}) => {
    await page.goto('/vets');
  });
"""

# Its method moved from line 4 to line 8; the diagram titles it the way JUnit does.
JAVA = """class AddVisitApiTest {
    @Test
    void untagged() {
    }

    @GenerateSequence
    @Test
    void addsAVisit() throws Exception {
        call("{x}");
    }
}
"""

FEATURE = """Feature: owners

  Scenario: Plain listing
    When I open the owners page

  @generate_sequence
  Scenario: Searching shows the first page
    When I open the owners page
"""


def _puml(rel: str, line: int, title: str) -> str:
    return (f"@startuml\ntitle [[src://{rel}:{line}{{Click to open the test}} Test: {title}]]\n"
            "participant Browser\nparticipant Backend\nBrowser -> Backend: GET /x\n@enduml\n")


def _repo(tmp_path, *, commit_tests_after_trace: bool):
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                                    capture_output=True, text=True)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    gen = tmp_path / "t" / "generated"
    gen.mkdir(parents=True)
    (gen / "add-visit.spec.ts.add-a-visit.genseq.puml").write_text(
        _puml("t/add-visit.spec.ts", 3, "Add a visit"))
    (gen / "AddVisitApiTest.java.adds-a-visit.genseq.puml").write_text(
        _puml("b/AddVisitApiTest.java", 4, "AddVisitApiTest: adds a visit"))
    (gen / "owners.feature.searching.genseq.puml").write_text(
        _puml("t/owners.feature", 2, "Searching shows the first page"))
    run("add", "-A")
    env = dict(os.environ, GIT_COMMITTER_DATE="2026-10-12T18:00:00", GIT_AUTHOR_DATE="2026-10-12T18:00:00")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "traced"], check=True, env=env)
    for rel, text in {"t/add-visit.spec.ts": SPEC, "b/AddVisitApiTest.java": JAVA,
                      "t/owners.feature": FEATURE}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    run("add", "-A")
    when = "2026-10-19T23:14:00" if commit_tests_after_trace else "2026-10-11T09:00:00"
    env = dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "tests"], check=True, env=env)
    seq.genseq_by_test.cache_clear()
    return tmp_path


def test_a_diagram_whose_test_moved_down_still_names_that_test(tmp_path):
    root = _repo(tmp_path, commit_tests_after_trace=True)
    assert seq._scenarios_drawn("t/generated/add-visit.spec.ts.add-a-visit.genseq.puml",
                                "t/add-visit.spec.ts", root) == [(9, "Add a visit")]
    assert seq._scenarios_drawn("t/generated/AddVisitApiTest.java.adds-a-visit.genseq.puml",
                                "b/AddVisitApiTest.java", root) == [
        (8, "AddVisitApiTest: adds a visit")]
    assert seq._scenarios_drawn("t/generated/owners.feature.searching.genseq.puml",
                                "t/owners.feature", root) == [
        (7, "Searching shows the first page")]


def test_a_scenario_is_never_both_drawn_and_undrawn(tmp_path):
    root = _repo(tmp_path, commit_tests_after_trace=True)
    drawn, undrawn = seq.derived_snippets(root)
    assert [x["ref"] for x in drawn] == ["b/AddVisitApiTest.java:6-10",
                                         "t/add-visit.spec.ts:9-13", "t/owners.feature:6-8"]
    # Only the test no diagram names at all, quoted from its own declaration.
    assert [x["ref"] for x in undrawn] == ["t/add-visit.spec.ts:15-19"]


def test_a_title_that_matches_nothing_keeps_the_recorded_line(tmp_path):
    """Renamed or deleted since: the diagram's own line is all there is, so it stays."""
    lines = SPEC.splitlines()
    assert seq._current_decl(lines, "ts", 3, "Some other test") == 3


def test_the_undrawn_group_says_why(tmp_path):
    root = _repo(tmp_path, commit_tests_after_trace=True)
    _, undrawn = seq.derived_snippets(root)
    assert undrawn[0]["caption"] == "Changed on 19 Oct, after the last traced run (12 Oct)."


def test_a_test_older_than_the_traced_run_was_traced_and_drew_nothing(tmp_path):
    root = _repo(tmp_path, commit_tests_after_trace=False)
    # The step's own copy of its run is the better clock, when there is one.
    head = root / seq.GENSEQ_OVERLAY / ".head"
    head.parent.mkdir(parents=True)
    head.write_text("x")
    t = time.mktime((2026, 10, 15, 10, 0, 0, 0, 0, -1))
    os.utime(head, (t, t))
    _, undrawn = seq.derived_snippets(root)
    assert undrawn[0]["caption"] == "The last traced run (15 Oct) drew no diagram for it."


def test_the_tab_shows_no_undrawn_group_for_a_test_that_only_moved(tmp_path, monkeypatch):
    root = _repo(tmp_path, commit_tests_after_trace=True)
    # Leave only the moved, drawn test in the spec.
    (root / "t/add-visit.spec.ts").write_text(SPEC.split("test('Never drawn'")[0])
    monkeypatch.setattr(seq, "_context_svg", lambda rel, root, out: (None, "<p>pic</p>"))
    block = {"type": "testpairs", "id": "sequences", "kind": "sequence",
             "snippets": {"auto": "genseq"},
             "unpaired": {"id": "tests-nosequence",
                          "title": "Tagged for tracing, but no diagram yet"}}
    out, _, _ = seq.render_testpairs(block, {}, [], root, root / ".human-review")
    assert "no diagram yet" not in out
    # The moved test is recognised as the tagged one it is.
    assert out.count('data-why="tagged"') == 3
