#!/usr/bin/env python3
"""The structured review record, end to end: written by the parser, checked against
`reference/review-points.schema.json` on both sides, and rendered under the builder's own
titles and labels.

What a Copilot run showed is that the Review tab had two authors: the committed
`review-points.md`, and a model writing content.json that renamed the piles ("Candidates
retained for human judgement") and whose free-text `source:` became every assumption's
badge ("implementation decision"). The record is now the only source, its shape is a
contract, and every word around it is the builder's.

Run with:  python3 -m pytest test_review_points_schema.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_points_schema as schema  # noqa: E402

_spec = importlib.util.spec_from_file_location("rp_for_schema", HERE / "review-points.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

_bspec = importlib.util.spec_from_file_location("build_for_schema", HERE / "build-review-html.py")
build = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(build)


POINTS = """---
base: 2a45c210
implementation: 7f3c1a9e
audited-head: 9b8c7d6e
head: 1234abcd
harness: copilot
reviewers: four reviewer subagents
---

## Fixed

### The seed hard-coded the number of vets
- file: db/seed/R__seed.sql:143
- source: /code-review high
- fixed-in: HEAD

## Ignored

### Collapse the two booking implementations
- file: src/VisitRestController.java:66
- source: Opus audit, rejected candidate
- severity: medium
- why: out of scope

## Assumptions

### Stable column proportions instead of fixed pixel widths
- file: web/owner-list.component.css:74
- source: implementation decision
- alternative: fixed pixel widths
- confidence: 0.79

### Restrict sorting to Name and City
- file: src/OwnerListParameters.java:41
- source: human
- alternative: sort every column
- confidence: 1.0
"""


def _report(tmp_path: Path, text: str = POINTS) -> dict:
    (tmp_path / "review-points.md").write_text(text, encoding="utf-8")
    return rp.document(tmp_path / "review-points.md", "review-points.md")


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #

def test_the_parser_writes_a_report_the_schema_accepts(tmp_path):
    doc = _report(tmp_path)
    assert schema.problems(doc) == []
    assert doc["schema"] == schema.SCHEMA_VERSION


def test_the_report_keeps_the_four_commits_apart(tmp_path):
    """The audited range, the feature's own commit, HEAD and the recording commit are four
    different facts; a run that named the latest housekeeping commit as `Implements:` made
    the reviewer explain in prose which commit the audit actually covered."""
    prov = _report(tmp_path)["provenance"]
    assert prov["auditedBase"] == prov["base"] == "2a45c210"
    assert prov["auditedHead"] == "9b8c7d6e"
    assert prov["implementation"] == "7f3c1a9e"
    assert prov["head"] == "1234abcd"
    assert prov["harness"] == "copilot"


def test_a_file_from_before_the_split_reads_its_one_commit_as_the_audited_head(tmp_path):
    prov = _report(tmp_path, POINTS.replace("audited-head: 9b8c7d6e\n", ""))["provenance"]
    assert prov["auditedHead"] == prov["implementation"] == "7f3c1a9e"


def test_an_assumption_says_who_decided_it_and_nothing_else(tmp_path):
    """`source:` on an assumption used to reach the page as its badge. It is reduced to
    the one fact it can carry — agent or human — and the free text is warned about."""
    doc = _report(tmp_path)
    by_title = {a["title"]: a for a in doc["assumptions"]}
    assert by_title["Stable column proportions instead of fixed pixel widths"]["decidedBy"] \
        == "agent"
    assert by_title["Restrict sorting to Name and City"]["decidedBy"] == "human"
    assert all("source" not in a for a in doc["assumptions"])
    assert not any("implementation decision" in w for w in doc["warnings"]), \
        "a known spelling of 'the agent decided' is not worth a warning"
    odd = _report(tmp_path, POINTS.replace("source: implementation decision",
                                           "source: my gut"))
    assert any("my gut" in w and "agent" in w for w in odd["warnings"])


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.pop("schema"), "missing required `schema`"),
    (lambda d: d.update(schema="review-points/1"), "must be 'review-points/2'"),
    (lambda d: d.update(colour="red"), "unknown key `colour`"),
    (lambda d: d["assumptions"][0].update(confidence=1.5), "above 1"),
    (lambda d: d["assumptions"][0].update(severity="high"), "unknown key `severity`"),
    (lambda d: d["assumptions"][0].update(source="implementation decision"),
     "unknown key `source`"),
    (lambda d: d["assumptions"][0].update(decidedBy="model"), "must be one of"),
    (lambda d: d["findings"][0].update(severity="critical"), "must be one of"),
    (lambda d: d["findings"][0].pop("refs"), "missing required `refs`"),
    (lambda d: d["autofixes"][0].update(refs=[]), "at least 1"),
    (lambda d: d["provenance"].update(implementation=""), "does not match"),
    (lambda d: d["sections"].update(Notes="Notes"), "unknown key `Notes`"),
])
def test_a_report_off_the_contract_is_refused_with_its_path(tmp_path, mutate, expected):
    doc = _report(tmp_path)
    mutate(doc)
    found = schema.problems(doc)
    assert any(expected in p for p in found), found
    assert all(p.startswith("$") for p in found), "every problem names where it is"


def test_the_schema_is_real_json_schema_and_agrees_with_the_checker(tmp_path):
    """The checker implements a subset of JSON Schema so no trainee needs `jsonschema`;
    where the real package is installed, the two must agree on what is valid."""
    jsonschema = pytest.importorskip("jsonschema")
    raw = schema.load_schema()
    jsonschema.Draft202012Validator.check_schema(raw)
    validator = jsonschema.Draft202012Validator(raw)
    good = _report(tmp_path)
    assert list(validator.iter_errors(good)) == [] and schema.problems(good) == []
    for bad in ({**good, "colour": "red"},
                {**good, "assumptions": [dict(good["assumptions"][0], confidence=-0.1)]},
                {k: v for k, v in good.items() if k != "provenance"}):
        assert list(validator.iter_errors(bad)) and schema.problems(bad)


def test_the_checker_refuses_a_schema_keyword_it_does_not_implement():
    with pytest.raises(ValueError, match="not supported"):
        schema.problems({}, {"type": "object", "patternProperties": {}})


def test_review_points_exits_6_when_its_own_report_breaks_the_contract(tmp_path,
                                                                        monkeypatch):
    (tmp_path / "review-points.md").write_text(POINTS, encoding="utf-8")
    monkeypatch.setattr(rp.review_points_schema, "problems", lambda doc: ["$: broken"])
    assert rp.main(["--root", str(tmp_path), "--check"]) == 6
    assert not (tmp_path / ".human-review" / "review-points.json").exists()


# --------------------------------------------------------------------------- #
# the reader: the builder refuses a bad report and owns every word around a good one
# --------------------------------------------------------------------------- #

SPEC = {
    "findings": {"auto": "review-points"},
    "autofixes": {"auto": "review-points"},
    "assumptions": {"auto": "review-points"},
    "tabs": [{"id": "review", "label": "Review", "blocks": [
        {"type": "findings", "title": "Candidates retained for human judgement"},
        {"type": "autofixes", "title": "Corrections from the recorded audit",
         "body": "model prose"},
        {"type": "assumptions", "title": "Implementation decisions"}]}],
}


def _resolved(tmp_path: Path, doc: dict, spec: dict | None = None):
    (tmp_path / "review-points.json").write_text(json.dumps(doc), encoding="utf-8")
    spec = copy.deepcopy(spec or SPEC)
    return spec, build.resolve_review_points(spec, tmp_path)


def test_the_builder_refuses_a_report_that_breaks_the_contract(tmp_path):
    doc = _report(tmp_path)
    doc["assumptions"][0]["confidence"] = 7
    with pytest.raises(SystemExit) as stop:
        _resolved(tmp_path, doc)
    assert "review-points.schema.json" in str(stop.value)
    assert "confidence" in str(stop.value)


def test_the_builder_refuses_a_report_from_before_the_schema(tmp_path):
    doc = _report(tmp_path)
    doc.pop("schema")
    with pytest.raises(SystemExit, match="regenerate"):
        _resolved(tmp_path, doc)


def test_a_report_beside_the_content_file_wins_over_piles_it_typed(tmp_path):
    spec = dict(copy.deepcopy(SPEC),
                findings=[{"title": "typed by a model", "body": "x"}])
    spec, points = _resolved(tmp_path, _report(tmp_path), spec)
    assert [f["title"] for f in spec["findings"]] == ["Collapse the two booking implementations"]
    assert points["provenance"]["implementation"] == "7f3c1a9e"


def _render(spec) -> str:
    build.reset_list()
    build.set_bands([])
    heading = lambda b, i, t: (f'<h2>{b.get("title", t)}</h2>'  # noqa: E731
                               + (f'<p>{b["body"]}</p>' if b.get("body") else ""))
    return "".join(build.render_pile_block(spec, b, heading=heading)[0]
                   for b in spec["tabs"][0]["blocks"])


def test_the_pile_titles_and_intros_are_the_builders(tmp_path, capsys):
    spec, _ = _resolved(tmp_path, _report(tmp_path))
    out = _render(spec)
    for title in ("Open review issues", "Auto-fixed", "Implementation assumptions"):
        assert f"<h2>{title}</h2>" in out
    for typed in ("Candidates retained", "Corrections from the recorded audit",
                  "Implementation decisions", "model prose"):
        assert typed not in out
    assert "<code>7f3c1a9e</code>, the implementation commit" in out
    assert "Read the other way" in out and "stay open until you agree" in out
    assert "closed decisions" not in out    # the pile is titled, and counted, as open
    assert spec["tabs"][0]["tip"] == build.REVIEW_TAB_TIP
    err = capsys.readouterr().err
    assert "Candidates retained for human judgement" in err and "ignored" in err


def test_an_assumption_reads_assumption_and_n_percent(tmp_path):
    """`assumption(79%)`, one badge — not the item's own `source` as the badge
    (`implementation decision [79%]`)."""
    spec, _ = _resolved(tmp_path, _report(tmp_path))
    out = _render(spec)
    cards = re.findall(r'<li class="n-assumed">.*?</li>', out, re.S)
    assert len(cards) == 2
    for card in cards:
        assert '<span class="badge sev-assumed">assumption(<span class="f-confidence' in card
    assert ">79%</span>)</span>" in out and ">100%</span>)</span>" in out
    assert "confident<" not in out
    assert "implementation decision" not in out
    human = next(c for c in cards if "Restrict sorting" in c)
    agent = next(c for c in cards if "Stable column" in c)
    assert "chosen by the human" in human and "chosen by the human" not in agent


def test_an_absent_report_still_gets_the_builders_titles(tmp_path):
    spec = copy.deepcopy(SPEC)
    build.resolve_review_points(spec, tmp_path)
    out = _render(spec)
    assert "<h2>Open review issues</h2>" in out and "Candidates retained" not in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
