#!/usr/bin/env python3
"""A pairing that never read the tests now on the card says so — and never re-runs itself.

The visit-vet demo (5 Oct 2026): the model paired the ticket's sentences over 30 candidate
tests, no e2e among them, and a later coverage run put the e2e runs on changed lines. Every
build after that drew the matrix as if the model had read those tests, and nothing on the
page or in the terminal said otherwise. Now:

- `rerun-model.py` records in `test-mapping.json` which tests the model was shown
  (`offered`) and a fingerprint of each one's body (`offeredDigest`), and the schema
  accepts both;
- the build (`semcov.write_fragment`) calls the pairing stale when today's candidates
  include a test it was never shown, or one whose body changed since — by content, never
  by a clock: the mapping being older than `assets/test-coverage.json` is not a reason
  (every cheap refresh rewrote that file, and clearing the pill cost a paid run each time);
- it warns loudly on stderr, puts a small pill with the command over the ticket, and
  records why in the merged mapping;
- `refresh-report.py` repeats that warning as its last word;
- nothing here ever calls a model.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_semcov import S, _repo  # noqa: E402 — the same throwaway repository


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("rerun_model", "rerun-model.py")
R = _load("refresh_report", "refresh-report.py")


def _age(path: Path, seconds: float) -> None:
    """Move a file's mtime `seconds` into the past."""
    t = path.stat().st_mtime - seconds
    os.utime(path, (t, t))


def _mapping(review: Path, **extra) -> Path:
    p = review / S.MAPPING
    p.write_text(json.dumps({"schema": "test-mapping/1", "sentences": [], **extra}),
                 encoding="utf-8")
    return p


def test_no_mapping_is_not_stale(tmp_path):
    _, review = _repo(tmp_path)
    assert S.pairing_stale(review) is None


def _offered_now(root: Path, review: Path) -> list[dict]:
    """What `write_fragment` would offer the model today: `model_input(...)["tests"]`."""
    g = S.gather(S._spec(review), review, root)
    return S.model_input(g["ticket"], g["sentences"], g["rows"], g["scripted"], g["docs"],
                         g["decisions"])["tests"]


def test_a_mapping_older_than_the_coverage_is_not_stale_by_that_alone(tmp_path):
    """Every cheap refresh re-ran `traces`, which moved `run.json`, which made `testcov`
    rewrite the coverage: the clock said stale after every refresh, and nothing had moved."""
    root, review = _repo(tmp_path)
    tests = _offered_now(root, review)
    _age(_mapping(review, offered=[t["id"] for t in tests],
                  offeredDigest=S.offered_digests(tests)), 3600)
    assert S.pairing_stale(review, [t["id"] for t in tests], None,
                           S.offered_digests(tests)) is None


def test_a_candidate_the_model_was_never_shown_makes_it_stale_whatever_the_clock_says(tmp_path):
    """The 5 Oct case: the pairing was shown only the unit tests; today's coverage puts an
    e2e scenario on the card. Newer file or not, that is stale."""
    _, review = _repo(tmp_path)
    _age(review / S.COVERAGE, 3600)
    _mapping(review, offered=["test/VisitTest.java:3"])
    assert S.pairing_stale(review, ["test/VisitTest.java:3"]) is None
    why = S.pairing_stale(review, ["test/VisitTest.java:3", "e2e/add-visit.spec.ts:31"])
    assert why and "1 candidate test(s) the model was never shown: add-visit.spec.ts:31" in why


def test_a_test_whose_body_changed_since_the_pairing_makes_it_stale(tmp_path):
    root, review = _repo(tmp_path)
    tests = _offered_now(root, review)
    ids = [t["id"] for t in tests]
    _mapping(review, offered=ids, offeredDigest=S.offered_digests(tests))
    assert S.pairing_stale(review, ids, None, S.offered_digests(tests)) is None
    edited = [{**t, "body": t["body"] + "\n    assertThat(x).isTrue();"} if i == 0 else t
              for i, t in enumerate(tests)]
    why = S.pairing_stale(review, ids, None, S.offered_digests(edited))
    assert why and f"1 test(s) changed since the model read them: {Path(ids[0]).name}" in why


def test_offered_without_digests_is_judged_on_the_ids_alone(tmp_path):
    """A mapping rerun-model.py wrote before `offeredDigest` existed: a body change cannot
    be told, an unseen candidate still can."""
    _, review = _repo(tmp_path)
    _mapping(review, offered=["a/B.java:3"])
    assert S.pairing_stale(review, ["a/B.java:3"], None, {"a/B.java:3": "f" * 16}) is None
    assert "never shown" in S.pairing_stale(review, ["a/B.java:3", "a/C.java:9"])


def test_a_mapping_that_records_nothing_it_was_shown_is_not_called_stale(tmp_path):
    """No `offered`: no record of what the model read, so no evidence either way — the old
    clock signal was the only thing that ever flagged these, and it was noise."""
    _, review = _repo(tmp_path)
    _age(_mapping(review), 3600)
    assert S.pairing_stale(review, ["test/VisitTest.java:3", "e2e/x.spec.ts:1"]) is None


def test_the_digest_is_of_the_body_the_model_reads():
    assert S.body_digest("void a() {}") == S.body_digest("void a() {}")
    assert S.body_digest("void a() {}") != S.body_digest("void a() { }")
    assert S.offered_digests([{"id": "x:1", "body": "b"}]) == {"x:1": S.body_digest("b")}


def test_the_schema_accepts_what_the_model_was_shown():
    doc = {"schema": "test-mapping/1", "sentences": [], "offered": ["a/B.java:3"],
           "offeredDigest": {"a/B.java:3": "0123456789abcdef"}}
    assert S.problems(doc) == []
    assert any("offered" in p for p in S.problems({**doc, "offered": "a/B.java:3"}))
    assert any("offeredDigest" in p for p in S.problems({**doc, "offeredDigest": ["x"]}))


def test_rerun_model_records_the_tests_it_offered(tmp_path, monkeypatch):
    """`--answer` is the no-cost path through the same install as a paid run."""
    root, review = _repo(tmp_path)
    monkeypatch.chdir(root)
    g = S.gather(S._spec(review), review, root)
    asked = S.model_input(g["ticket"], g["sentences"], g["rows"], g["scripted"], g["docs"],
                          g["decisions"])
    reply = {"schema": "test-mapping/1", "sentences": [
        {"id": x["id"], "coverage": "missing", "tests": [],
         **({"review": [{"id": t["id"], "verdict": "reject", "why": "no"}
                        for t in x["scripted"]]} if x["scripted"] else {})}
        for x in asked["sentences"]]}
    (tmp_path / "reply.json").write_text(json.dumps(reply), encoding="utf-8")
    assert M.main(["--dir", ".human-review", "--answer", str(tmp_path / "reply.json")]) == 0
    written = json.loads((review / S.MAPPING).read_text())
    assert written["offered"] == [t["id"] for t in asked["tests"]] and written["offered"]
    assert written["offeredDigest"] == S.offered_digests(asked["tests"])
    assert S.load_model_mapping(review) is not None, "the schema must accept what it wrote"
    # …and the very next build, with nothing changed, finds nothing to say.
    assert S.pairing_stale(review, [t["id"] for t in asked["tests"]], None,
                           S.offered_digests(asked["tests"])) is None


def test_the_build_warns_and_the_page_says_so(tmp_path, capsys):
    root, review = _repo(tmp_path)
    _mapping(review, offered=["test/VisitTest.java:3"])
    S.write_fragment(S._spec(review), review, root)
    err = capsys.readouterr().err
    assert "WARNING: the Tests tab's pairing has not read every test now on the card" in err
    assert "rerun-model.py" in err
    page = (review / S.FRAGMENT).read_text()
    assert '<span class="rm-stale-badge" role="note"' in page
    assert "<p class=\"rm-stale\"" not in page, "no banner any more"
    assert f"{S.STALE_NOTE} rerun-model.py {S.STALE_TAIL}" in page
    assert 'class="rm-stale-ai"' in page and "\U0001F916</button>" in page
    merged = json.loads((review / S.MERGED).read_text())
    assert merged["stale"]["command"] == "rerun-model.py"
    assert "never shown: VisitTest.java:8" in merged["stale"]["why"]


def test_a_fresh_pairing_draws_no_note(tmp_path, capsys):
    """Shown everything on the card, every body as it is now — and older than the coverage
    file, which is what every cheap refresh made it."""
    root, review = _repo(tmp_path)
    tests = _offered_now(root, review)
    _age(_mapping(review, offered=[t["id"] for t in tests],
                  offeredDigest=S.offered_digests(tests)), 3600)
    S.write_fragment(S._spec(review), review, root)
    assert "WARNING" not in capsys.readouterr().err
    assert "rm-stale-badge" not in (review / S.FRAGMENT).read_text().split("</style>", 1)[1]
    assert "stale" not in json.loads((review / S.MERGED).read_text())


def test_the_command_names_a_review_directory_that_is_not_the_default(tmp_path):
    root = tmp_path / "repo"
    assert S.rerun_command(root / ".human-review", root) == "rerun-model.py"
    assert S.rerun_command(root / "out" / "hr", root) == "rerun-model.py --dir out/hr"


def test_refresh_repeats_the_warning_only_for_its_own_build(tmp_path, capsys):
    review = tmp_path / ".human-review"
    (review / "assets").mkdir(parents=True)
    merged = review / R.MERGED_MAPPING
    merged.write_text(json.dumps({"sentences": [], "stale": {
        "why": "1 candidate test(s) the model was never shown: add-visit.spec.ts:56",
        "command": "rerun-model.py"}}), encoding="utf-8")
    got = R.stale_pairing(review, since=merged.stat().st_mtime - 1)
    assert got and got["command"] == "rerun-model.py"
    # A merged file an earlier build left says nothing about this one.
    assert R.stale_pairing(review, since=merged.stat().st_mtime + 60) is None
    R.warn_stale_pairing(got)
    err = capsys.readouterr().err
    assert "WARNING: the Tests tab's pairing has not read every test now on the card" in err
    assert "rerun-model.py" in err and "paid model call" in err


def test_nothing_on_the_stale_path_calls_a_model(tmp_path, monkeypatch):
    """The warning names the command; it never runs it."""
    import subprocess
    root, review = _repo(tmp_path)
    _mapping(review, offered=["test/VisitTest.java:3"])
    calls = []
    real = subprocess.run

    def spy(argv, *a, **k):
        if argv and argv[0] == "claude" or "rerun-model.py" in " ".join(map(str, argv)):
            calls.append(argv)
        return real(argv, *a, **k)
    monkeypatch.setattr(subprocess, "run", spy)
    S.write_fragment(S._spec(review), review, root)
    assert calls == []
    assert "stale" in json.loads((review / S.MERGED).read_text()), "the stale path was taken"
