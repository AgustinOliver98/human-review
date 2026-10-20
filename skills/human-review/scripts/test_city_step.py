#!/usr/bin/env python3
"""The Code City is drawn into the review directory, never over the repository's own copy.

hr-try-4 (2 Oct 2026): `steps.city.out` was passed straight to the generator as its output
folder, so every review rewrote `petclinic-backend/docs/generated/codecity/codecity.html`
— a committed file. Each run left the working tree dirty, and the project's pre-push gate
then demanded that the review's by-product be committed. The page links to
`assets/codecity/codecity.html`, so that is where the city is generated now; a project
whose own command can only write in place gets its original bytes put back.

Run with:  python3 -m pytest test_city_step.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("run_steps", HERE / "run-steps.py")
steps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(steps)

PAGE = ".human-review/assets/codecity/codecity.html"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def _repo(tmp_path: Path) -> Path:
    """A checkout with a committed city, the way petclinic has one."""
    repo = tmp_path / "repo"
    (repo / "docs/generated/codecity").mkdir(parents=True)
    (repo / "docs/generated/codecity/codecity.html").write_text("<html>main's city</html>\n")
    (repo / ".gitignore").write_text(".human-review/\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return repo


class Shell:
    """`sh`, faked by substring — and able to DO something, because the point of these
    tests is what a command leaves on disk."""

    def __init__(self, effects=None):
        self.effects = effects or {}
        self.ran: list[str] = []

    def __call__(self, cmd, ctx, check=True, capture=False):
        self.ran.append(cmd)
        for needle, effect in self.effects.items():
            if needle in cmd:
                effect()
        return subprocess.CompletedProcess(cmd, 0, "3 changed\n", "")

    def first(self, needle: str) -> str:
        return next(c for c in self.ran if needle in c)


def test_the_built_in_generator_writes_beside_the_review_not_over_the_committed_city(
        tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    sh = Shell()
    monkeypatch.setattr(steps, "sh", sh)
    ctx = steps.Ctx("origin/main", {"steps": {"city": {
        "out": "docs/generated/codecity", "title": "Code City"}}}, dry=False)

    steps._city(ctx)

    regen = sh.first("regenerate-codecity.sh")
    assert '--out ".human-review/assets/codecity"' in regen
    assert "docs/generated/codecity" not in regen
    # and the shot is taken of that same page, the one the tab links to
    assert sh.first("capture-codecity.sh").endswith(f"highlight {PAGE}")


def test_a_projects_own_in_place_command_gets_its_original_bytes_back(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    committed = Path("docs/generated/codecity/codecity.html")

    def generate():                        # what a generator that only writes in place does
        committed.write_text("<html>this branch's city</html>\n")

    monkeypatch.setattr(steps, "sh", Shell({"make-city": generate}))
    ctx = steps.Ctx("origin/main", {"steps": {"city": {
        "regenerate": "./make-city", "html": str(committed)}}}, dry=False)

    steps._city(ctx)

    assert Path(PAGE).read_text() == "<html>this branch's city</html>\n", \
        "the new page is copied out to where the tab links"
    assert committed.read_text() == "<html>main's city</html>\n"
    assert _git(repo, "status", "--porcelain") == "", "the review left the tree as it found it"


def test_bytes_restored_keeps_an_uncommitted_edit_and_removes_what_it_created(tmp_path):
    edited = tmp_path / "edited.html"
    edited.write_text("somebody's uncommitted edit")
    created = tmp_path / "created.html"
    with steps.bytes_restored([edited, created]):
        edited.write_text("generated")
        created.write_text("generated")
    assert edited.read_text() == "somebody's uncommitted edit", \
        "the bytes on disk, not git's — git has never seen this edit"
    assert not created.exists()


# ── the two shell scripts ───────────────────────────────────────────────────────────

def test_regenerate_writes_to_an_absolute_out_and_leaves_the_repository_alone(tmp_path):
    repo = _repo(tmp_path)
    tool = tmp_path / "tool"
    (tool / ".git").mkdir(parents=True)
    (tool / "generate.sh").write_text(
        '#!/usr/bin/env bash\nset -e\nmkdir -p "$2"\n'
        'echo "<html>city of $1</html>" > "$2/codecity.html"\necho x > "$2/codemap.tsv"\n')
    (tool / "generate.sh").chmod(0o755)
    out = repo / ".human-review/assets/codecity"
    env = {**os.environ, "CODECITY_TOOL_DIR": str(tool)}

    r = subprocess.run([str(HERE / "regenerate-codecity.sh"), "--no-pull", "--out", str(out)],
                       cwd=repo, env=env, capture_output=True, text=True)

    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["codecity.html"]
    assert _git(repo, "status", "--porcelain") == ""


def _capture_rig(tmp_path: Path) -> tuple[Path, dict]:
    """A checkout `capture-codecity.sh` accepts, with `node` stubbed: the browser is not
    what is under test, the file handling around it is."""
    repo = _repo(tmp_path)
    (repo / "petclinic-test/node_modules/playwright").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "node").write_text("#!/usr/bin/env bash\necho '3 changed'\n")
    (bin_dir / "node").chmod(0o755)
    return repo, {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def test_capture_shoots_the_city_generated_beside_the_png_without_copying_it_onto_itself(
        tmp_path):
    repo, env = _capture_rig(tmp_path)
    page = repo / PAGE
    page.parent.mkdir(parents=True)
    page.write_text("<html>branch city</html>\n")

    r = subprocess.run([str(HERE / "capture-codecity.sh"), ".human-review/assets/codecity.png",
                        "highlight", PAGE], cwd=repo, env=env, capture_output=True, text=True)

    assert r.returncode == 0, r.stderr      # `cp` onto itself under `set -e` was a failure
    assert page.read_text() == "<html>branch city</html>\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_capture_still_copies_a_city_that_lives_elsewhere(tmp_path):
    repo, env = _capture_rig(tmp_path)
    r = subprocess.run([str(HERE / "capture-codecity.sh"), ".human-review/assets/codecity.png",
                        "highlight", "docs/generated/codecity/codecity.html"],
                       cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (repo / PAGE).read_text() == "<html>main's city</html>\n"


def test_capture_names_the_colour_the_shot_was_taken_in():
    """The city picks its own opening colour — "outgoing coupling" when there is a change
    set to diff against, something else when there is not — so the line under the shot reads
    the colour back off the page instead of assuming one. Grep-shaped: the rig above fakes
    `node`, and the JS is the thing that has to keep doing this."""
    src = (HERE / "capture-codecity.sh").read_text(encoding="utf-8")
    assert 'getElementById("colorMetric")?.selectedOptions' in src
    assert "coloured by ${result.color}" in src
    assert "console.log(lit);" in src


def test_the_colour_rides_into_the_lit_note(tmp_path, monkeypatch):
    """Whatever the shot says on its last line is what the run notes — count and colour."""
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    class Shot(Shell):
        def __call__(self, cmd, ctx, check=True, capture=False):
            super().__call__(cmd, ctx, check, capture)
            out = "8 changed · coloured by outgoing coupling\n" if "capture-codecity" in cmd else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(steps, "sh", Shot())
    ctx = steps.Ctx("origin/main", {"steps": {"city": {
        "out": "docs/generated/codecity", "title": "Code City"}}}, dry=False)

    steps._city(ctx)

    assert any("codecity lit: 8 changed · coloured by outgoing coupling" in n for n in ctx.notes)


# ── the city is coloured by the coverage the test step measured ─────────────────────

def _coverage_on_disk(repo: Path, head: str) -> None:
    """What `testcov.py` leaves: per-test hits and every file's executable lines."""
    assets = repo / ".human-review/assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "test-coverage.json").write_text(json.dumps({
        "head": head, "executableAll": {"src/main/java/A.java": [1, 2, 3, 4]},
        "tests": [{"suite": "E2E Playwright", "source": "jacoco+v8", "file": "e2e/a.spec.ts",
                   "hits": {"src/main/java/A.java": [1, 2]}}]}))


class RealCoverage(Shell):
    """`sh` faked for everything but the converter, which is what is under test."""

    def __call__(self, cmd, ctx, check=True, capture=False):
        if "city-coverage.py" in cmd or cmd.startswith("git "):
            self.ran.append(cmd)
            return subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return super().__call__(cmd, ctx, check, capture)


def test_the_city_is_generated_with_the_coverage_the_test_step_left(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    _coverage_on_disk(repo, _git(repo, "rev-parse", "HEAD").strip())
    sh = RealCoverage()
    monkeypatch.setattr(steps, "sh", sh)
    ctx = steps.Ctx("origin/main", {"steps": {"city": {"out": "x", "title": "Code City"}}},
                    dry=False)

    steps._city(ctx)

    regen = sh.first("regenerate-codecity.sh")
    assert '--coverage ".human-review/assets/codecity-coverage.json"' in regen
    got = json.loads((repo / ".human-review/assets/codecity-coverage.json").read_text())
    assert got["files"]["src/main/java/A.java"] == {
        "line": {"covered": 2, "total": 4}, "acceptance": {"covered": 2, "total": 4}}
    assert not [n for n in ctx.notes if "coverage" in n], ctx.notes
    assert not any("mvn" in c or "npm" in c for c in sh.ran), "no test is run from here"


def test_without_coverage_on_disk_the_city_is_built_as_before_and_says_why(
        tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    stale = repo / ".human-review/assets/codecity-coverage.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")                 # a previous run's: must not colour this one
    sh = RealCoverage()
    monkeypatch.setattr(steps, "sh", sh)
    ctx = steps.Ctx("origin/main", {"steps": {"city": {"out": "x"}}}, dry=False)

    steps._city(ctx)

    assert "--coverage" not in sh.first("regenerate-codecity.sh")
    assert not stale.exists()
    assert any("no coverage colours on the city" in n for n in ctx.notes)


def test_coverage_of_another_commit_is_used_and_named_stale(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    _coverage_on_disk(repo, "0123456789abcdef")
    monkeypatch.setattr(steps, "sh", RealCoverage())
    ctx = steps.Ctx("origin/main", {"steps": {"city": {"out": "x"}}}, dry=False)
    steps._city(ctx)
    assert any("measured on 01234567" in n for n in ctx.notes), ctx.notes


def test_the_traced_browser_suite_runs_in_traces_before_its_harvest(tmp_path, monkeypatch):
    """`city.tests` moved out of `_city` (the city now waits for the coverage it dumps):
    `traces` runs it first — even with no report to harvest, since `testcov` reads it."""
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    sh = Shell()
    monkeypatch.setattr(steps, "sh", sh)
    ctx = steps.Ctx("origin/main", {"steps": {"city": {"tests": "npm test"}}}, dry=False)
    try:
        steps._traces(ctx)
    except LookupError as e:
        assert "traces.report" in str(e)
    assert sh.ran[0] == "npm test"
    names = [row[0] for row in steps.STEPS]
    assert steps.NEEDS["city"] == {"testcov"} and steps.NEEDS["testcov"] == {"traces"}
    assert names.index("traces") < names.index("testcov") < names.index("city")
    assert "city" not in steps.USES, "the city reads files; the stack is the suites'"


# ── the ⏳ on the Code City tab ─────────────────────────────────────────────────────

def test_the_code_city_tab_has_the_tests_tabs_run_the_tests_press_with_the_city_after_it(
        tmp_path):
    _bspec = importlib.util.spec_from_file_location("brh_city", HERE / "build-review-html.py")
    build = importlib.util.module_from_spec(_bspec)
    _bspec.loader.exec_module(build)
    build.ACTIONS.clear()
    tests = build.declare_run_tests_rerun(tmp_path, tmp_path / ".human-review", HERE)
    city = build.declare_city_run_tests(tmp_path, tmp_path / ".human-review", HERE)
    assert city["id"] == "__rerun_tests__:city"
    assert city["steps"] == tests["steps"] + ["city"], "one runner: the tests, then the city"
    cmd = build.ACTIONS["__rerun_tests__:city"]["command"]
    assert f"--steps {','.join(city['steps'])} --force --no-serve" in cmd
    assert cmd.index("traces") < cmd.index("testcov") < cmd.index("city --force")
    button = build.run_tests_button(city)
    assert 'data-rerun="__rerun_tests__"' in button and 'data-tab="city"' in button
    assert build.RUN_TESTS_FACE in button and "⏳" in button
    # The Tests tab's own is unchanged.
    assert 'data-tab="requirements"' in build.run_tests_button(tests)
    build.ACTIONS.clear()
