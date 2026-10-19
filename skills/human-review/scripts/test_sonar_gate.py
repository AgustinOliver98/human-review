#!/usr/bin/env python3
"""Is Sonar green too? — the gate records what the CI run's Sonar steps said, and the grade
panel says it with a second link (Victor, 20 Oct 2026).

The producer half reads a recorded `gh run view --json jobs,event,headBranch` (petclinic's
run 37347327883 on be762955, both Sonar steps green) and a recorded SonarCloud
`project_branches/list`; nothing here touches the network.

Run with:  python3 -m pytest test_sonar_gate.py
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DATA = HERE / "testdata" / "sonar"
RUN = json.loads((DATA / "petclinic-run-37347327883.json").read_text())
BRANCHES = json.loads((DATA / "sonarcloud-branches.json").read_text())
SHA = "be762955d5f477feeca0f7db55e32fa1c2fb8db5"
RUN_URL = "https://github.com/victorrentea/petclinic/actions/runs/37347327883"
DASH = "https://sonarcloud.io/summary/new_code?id=victorrentea_petclinic&branch=test-pr"

sys.path.insert(0, str(HERE))
import preflight  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_review_html",
                                               HERE / "build-review-html.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv(preflight.SONAR_API_ENV, "0")
    (tmp_path / "sonar-project.properties").write_text(
        "sonar.projectKey=victorrentea_petclinic\nsonar.organization=victorrentea\n"
        "sonar.host.url=https://sonarcloud.io\n")
    return tmp_path


def _with(step: str, conclusion: str) -> dict:
    run = copy.deepcopy(RUN)
    for st in run["jobs"][0]["steps"]:
        if st["name"] == step:
            st["conclusion"] = conclusion
    return run


# ── the producer ──────────────────────────────────────────────────────────────────────

def test_a_green_push_run_records_sonar_green_and_the_branch_dashboard(project):
    s = preflight.sonar_from_run(RUN, SHA, project)
    assert s == {"verdict": "success", "gate": "success", "scanStep": "SonarCloud Scan",
                 "gateStep": "SonarCloud Quality Gate check",
                 "projectKey": "victorrentea_petclinic", "url": DASH}


def test_the_cache_steps_that_say_sonar_are_not_the_scan(project):
    """`Cache SonarCloud packages` and its `Post …` twin analyse nothing."""
    run = _with("Cache SonarCloud packages", "failure")
    for st in run["jobs"][0]["steps"]:
        if st["name"] == "Post Cache SonarCloud packages":
            st["conclusion"] = "failure"
    assert preflight.sonar_from_run(run, SHA, project)["verdict"] == "success"


@pytest.mark.parametrize("step,conclusion,verdict,gate", [
    ("SonarCloud Quality Gate check", "failure", "failure", "failure"),
    ("SonarCloud Scan", "failure", "failure", "success"),
    ("SonarCloud Scan", "skipped", "skipped", "success"),
])
def test_the_steps_conclusions_make_the_verdict(project, step, conclusion, verdict, gate):
    s = preflight.sonar_from_run(_with(step, conclusion), SHA, project)
    assert (s["verdict"], s["gate"]) == (verdict, gate)


def test_a_run_without_sonar_records_nothing(project):
    run = copy.deepcopy(RUN)
    run["jobs"][0]["steps"] = [st for st in run["jobs"][0]["steps"]
                               if "sonar" not in st["name"].lower()]
    assert preflight.sonar_from_run(run, SHA, project) is None


def test_a_pull_request_run_links_the_pull_requests_analysis(project):
    run = dict(RUN, event="pull_request")
    s = preflight.sonar_from_run(run, SHA, project, pr=37)
    assert s["url"] == ("https://sonarcloud.io/summary/new_code?id=victorrentea_petclinic"
                        "&pullRequest=37")


def test_the_key_comes_from_the_pom_or_the_workflow_when_there_is_no_properties_file(tmp_path):
    (tmp_path / "pom.xml").write_text(
        "<project><properties><sonar.projectKey>acme_shop</sonar.projectKey>"
        "</properties></project>")
    assert preflight.sonar_project(tmp_path) == ("acme_shop", "https://sonarcloud.io")
    (tmp_path / "pom.xml").unlink()
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("run: mvn verify sonar:sonar -Dsonar.projectKey=acme_cart\n")
    assert preflight.sonar_project(tmp_path)[0] == "acme_cart"


def _api(monkeypatch, sha: str, status: str):
    doc = copy.deepcopy(BRANCHES)
    row = next(b for b in doc["branches"] if b["name"] == "test-pr")
    row["status"]["qualityGateStatus"], row["commit"]["sha"] = status, sha
    seen = []

    def urlopen(url, timeout):
        seen.append((url, timeout))
        return io.BytesIO(json.dumps(doc).encode())
    monkeypatch.delenv(preflight.SONAR_API_ENV, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return seen


def test_a_red_gate_the_api_holds_for_this_commit_is_a_failure(project, monkeypatch):
    """A gate step with `continue-on-error` leaves a green job over a red gate."""
    seen = _api(monkeypatch, SHA, "ERROR")
    s = preflight.sonar_from_run(RUN, SHA, project)
    assert s["verdict"] == "failure" and s["api"] == {"status": "ERROR", "sha": SHA,
                                                     "stale": False}
    assert seen == [("https://sonarcloud.io/api/project_branches/list"
                     "?project=victorrentea_petclinic", preflight.SONAR_API_TIMEOUT_S)]


def test_an_api_answer_about_another_commit_changes_nothing(project, monkeypatch):
    _api(monkeypatch, "39346ec5" + "0" * 32, "ERROR")
    s = preflight.sonar_from_run(RUN, SHA, project)
    assert s["verdict"] == "success" and s["api"]["stale"] is True


def test_the_api_unreachable_is_silence_not_a_failure(project, monkeypatch):
    def down(url, timeout):
        raise OSError("offline")
    monkeypatch.delenv(preflight.SONAR_API_ENV, raising=False)
    monkeypatch.setattr("urllib.request.urlopen", down)
    s = preflight.sonar_from_run(RUN, SHA, project)
    assert s["verdict"] == "success" and "api" not in s


def _stub_gh(tmp_path: Path, view: dict | None) -> dict:
    """A `gh` whose `run view` answers with `view` (or fails), and whose `run list` /
    `workflow list` describe one green CI run on HEAD; `git push` is a no-op."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(
        "#!/usr/bin/env python3\nimport sys, json\n"
        f"VIEW = json.loads({json.dumps(json.dumps(view))})\n"
        "a = sys.argv[1:]\n"
        "if a[:2] == ['run', 'view']:\n"
        "    if VIEW is None: sys.exit(1)\n"
        "    print(json.dumps(VIEW))\n"
        "elif a[:2] == ['run', 'list']:\n"
        "    print(json.dumps([{'databaseId': 37347327883, 'status': 'completed',\n"
        "        'conclusion': 'success', 'workflowName': 'CI', 'event': 'push',\n"
        f"        'url': {RUN_URL!r}}}]))\n"
        "elif a[:2] == ['workflow', 'list']:\n"
        "    print(json.dumps([{'id': 1, 'name': 'CI', 'path': '.github/workflows/ci.yml',\n"
        "        'state': 'active'}]))\n"
        "else: print('')\n")
    (bindir / "gh").chmod(0o755)
    (bindir / "git").write_text(
        '#!/bin/sh\nif [ "$1" = push ]; then exit 0; fi\nexec /usr/bin/git "$@"\n')
    (bindir / "git").chmod(0o755)
    return dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                **{preflight.SONAR_API_ENV: "0"})


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    sh = lambda c: subprocess.run(c, shell=True, cwd=r, check=True, capture_output=True)
    sh("git init -q -b test-pr && git config user.email t@t && git config user.name t")
    (r / "sonar-project.properties").write_text("sonar.projectKey=victorrentea_petclinic\n")
    sh("git add -A && git commit -qm one")
    (r / ".human-review" / "assets").mkdir(parents=True)
    (r / ".human-review" / "assets" / "old.svg").write_text("<svg/>")
    return r


def test_the_gate_writes_sonar_into_gate_json(tmp_path):
    repo, env = _repo(tmp_path), _stub_gh(tmp_path, RUN)
    p = subprocess.run([sys.executable, str(HERE / "preflight.py")], cwd=repo, env=env,
                       text=True, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr
    gate = json.loads((repo / ".human-review" / ".gate.json").read_text())
    assert gate["verdict"] == "green"
    assert gate["sonar"]["verdict"] == "success" and gate["sonar"]["url"] == DASH
    assert gate["sonar"]["runId"] == 37347327883


def test_sonar_only_rereads_the_recorded_run_and_touches_nothing_else(tmp_path):
    """The cheap re-run: no push, no gate, no wipe — only `sonar` in `.gate.json` moves."""
    repo, env = _repo(tmp_path), _stub_gh(tmp_path, RUN)
    recorded = {"sha": SHA, "verdict": "green", "caveat": "green: CI (run 37347327883)",
                "workflows": [{"name": "CI", "runId": 37347327883, "url": RUN_URL,
                               "status": "completed", "verdict": "success"}]}
    (repo / ".human-review" / ".gate.json").write_text(json.dumps(recorded))
    p = subprocess.run([sys.executable, str(HERE / "preflight.py"), "--sonar-only"],
                       cwd=repo, env=env, text=True, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr
    gate = json.loads((repo / ".human-review" / ".gate.json").read_text())
    assert {k: v for k, v in gate.items() if k != "sonar"} == recorded
    assert gate["sonar"]["url"] == DASH
    assert (repo / ".human-review" / "assets" / "old.svg").is_file()
    assert not (repo / ".human-review" / ".started").exists()


def test_gh_failing_on_run_view_records_no_sonar(tmp_path):
    repo, env = _repo(tmp_path), _stub_gh(tmp_path, None)
    p = subprocess.run([sys.executable, str(HERE / "preflight.py")], cwd=repo, env=env,
                       text=True, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "sonar" not in json.loads((repo / ".human-review" / ".gate.json").read_text())


# ── the grade panel ───────────────────────────────────────────────────────────────────

def _panel(tmp_path, sonar: dict | None, score: int = 9) -> tuple[str, dict]:
    out = tmp_path / ".human-review"
    out.mkdir()
    gate = {"sha": SHA, "verdict": "green", "caveat": "green",
            "workflows": [{"name": "CI", "runId": 37347327883, "url": RUN_URL,
                           "verdict": "success"}]}
    if sonar is not None:
        gate["sonar"] = sonar
    (out / ".gate.json").write_text(json.dumps(gate))
    spec = {"verdict": {"score": score}}
    build.grade_signals(spec, out, root=None)
    build.cap_grade(spec)
    return build.grade_reasons_html(spec), spec


def _a(href: str, face: str) -> str:
    return f'<a href="{href}" target="_blank" rel="noopener">{face}</a>'


def test_ci_and_sonar_green_is_one_bullet_with_two_links(tmp_path):
    panel, spec = _panel(tmp_path, {"verdict": "success", "gate": "success", "url": DASH})
    assert (f'<li>✅ {_a(RUN_URL, "CI")} and {_a(html_amp(DASH), "Sonar")} '
            'green on be762955</li>') in panel
    assert spec["verdict"]["score"] == 9


def html_amp(url: str) -> str:
    return url.replace("&", "&amp;")


def test_a_red_sonar_gate_under_green_ci_is_its_own_bullet_and_caps_at_7(tmp_path):
    panel, spec = _panel(tmp_path, {"verdict": "failure", "gate": "failure", "url": DASH,
                                    "gateStep": "SonarCloud Quality Gate check"})
    assert f'<li>✅ {_a(RUN_URL, "CI")} green on be762955</li>' in panel
    assert (f'{_a(html_amp(DASH), "Sonar")} quality gate failed on be762955 '
            '(caps the grade at 7)</li>') in panel
    assert "SonarCloud Quality Gate check step concluded failure" in panel
    assert spec["verdict"] == {"score": 7, "modelScore": 9}
    keys = [s["key"] for s in spec["_gradeSignals"]]
    assert keys[:2] == ["ci-green", "ci-sonar-failed"]


@pytest.mark.parametrize("sonar", [None, {"verdict": "skipped", "url": DASH}])
def test_no_sonar_or_a_skipped_one_leaves_the_ci_bullet_as_it_was(tmp_path, sonar):
    panel, spec = _panel(tmp_path, sonar)
    assert f'<li>✅ {_a(RUN_URL, "CI")} green on be762955</li>' in panel
    assert "Sonar" not in panel and spec["verdict"] == {"score": 9}


def test_sonar_green_without_a_dashboard_url_links_only_ci(tmp_path):
    panel, _ = _panel(tmp_path, {"verdict": "success", "url": "javascript:alert(1)"})
    assert f'<li>✅ {_a(RUN_URL, "CI")} and Sonar green on be762955</li>' in panel
