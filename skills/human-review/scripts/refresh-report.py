#!/usr/bin/env python3
"""Rebuild and re-serve an existing review page, without asking a model anything.

`/human-review` has two halves that have never been separable by hand, and were therefore
run together every time somebody wanted a page refreshed:

  * **the model's half** — the findings, the prose, and the pairing of the ticket's
    sentences with tests that the script could not decide (`test-mapping.json`; the Tests
    tab's matrix itself is drawn by `semcov.py`, here, from it). Slow, paid for, and *not
    reproducible*: a second pass over
    the same diff words and ranks its findings differently, so re-running it does not
    confirm the first one, it replaces it. It runs when the human asks for it, never as a
    side effect of anything else;
  * **the programs** — the diagram deltas, the Code City shot, the complexity increment, the
    contract diff, the logging scan, the test manifest, the recordings, and the build of the
    HTML itself. Fixed inputs, fixed outputs, safe to run again at any time.

This is the second half, as one command. Run it after *any* change that the page should
show: an edit to `build-review-html.py`, a fix in the branch under review, a new commit, a
tweak to `content.json`. It never writes the model's half and never calls a model — a
logging statement whose privacy verdict is not already in the cache renders as *not
evaluated* rather than quietly buying an answer.

    refresh-report.py                     # rebuild the page and serve it
    refresh-report.py --steps cheap       # …after re-running the fast producers
    refresh-report.py --steps static      # …after re-running the ones that need nothing up
    refresh-report.py --steps all         # …after re-running every producer, heavy included
    refresh-report.py --steps diagrams,tests
    refresh-report.py --no-serve          # write the file, print nothing to open

It refuses to build in two cases, and both are the same principle: a page must not assert
something the repository contradicts. The first is a **missing model-written part** — the
layout, the model's half of the sentence↔test pairing. Those are not steps this
program can re-run, and a page without them is not a smaller page, it is the same page
with its argument deleted. The second is a **commit claiming a `review-points.md` that is
not on disk**: the branch says it recorded its own review and the file is gone, so the
band reading *nothing records what was reviewed* would be true of the disk and false about
the run.

The film's script (`feature-script.js`) is the other model-written artifact — +1 LLM script
beside the matrix — and it too is never written here: `rerun-film.py` is the command that
does. But it is not a refusal when it is missing. No script is no film, a state the `video`
step and the Demo tab already name, not a page with its argument deleted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_STEPS = HERE / "run-steps.py"
BUILD = HERE / "build-review-html.py"
SERVE = HERE / "serve-review.py"
DS_AUDIT = HERE / "ds-audit.py"
REVIEW_COMMITS = HERE / "review-commits.py"
CONFIG = "human-review.json"

#: What only the model writes, and what it is — named so the refusal can say which part of
#: `/human-review` produces it rather than "a file is missing". Deliberately short: these
#: are the artifacts nothing else can reconstruct. Everything else under `.human-review/`
#: is the output of a program, and the build's own validation already names those,
#: correctly, as "did the step that produces it run?".
#:
#: `content.json` is on the list and no longer for the reason it used to be. It was *the
#: judgement* — the findings, which ones were fixed, which were left, what the coder
#: assumed — written by a model at the end of a review and corroborated by nothing outside
#: itself. That record now belongs to the branch: `/record-review` writes
#: `review-points.md`, commits it with the fixes, and the content file asks for the three
#: piles with `{"auto": "review-points"}`. What is left in it is the *layout* and the
#: *ledes* — which tabs the page has, in what order, and the sentences over them. Still a
#: model's work, still not reproducible, still not something this program will invent; a
#: much smaller claim.
MODEL_OWNED = {
    "content.json": "the layout and the ledes — which tabs, in what order, and the "
                    "sentences over them (the three Review piles come from the branch's "
                    'own review-points.md, via {"auto": "review-points"})',
    "test-mapping.json": "the pairing of the ticket's sentences with the tests that the "
                         "script could not decide (rerun-model.py asks a cheap model; "
                         "semcov.py draws the matrix from it, the ticket and the coverage)",
}

#: What still stands in for a model-owned file written by an older run. The Tests tab's
#: matrix was the model's whole HTML (`requirements-map.html`) until the script drew it;
#: a review made then has no `test-mapping.json`, and its matrix is still a matrix.
MODEL_OWNED_LEGACY = {"test-mapping.json": "assets/requirements-map.html"}

#: Model-written too — **+1 LLM script** beside the matrix — and owned the same way: this
#: program never writes it, and `rerun-film.py` (the Demo tab's 🤖) is the one command
#: that does. Kept apart from MODEL_OWNED for the one way it differs: its absence is not a
#: refusal. No script means no film, which is a real state of a review — the `video` step
#: says "no feature script" and the Demo tab says nothing was filmed — whereas a page
#: without its matrix is the same page with its argument deleted.
MODEL_OWNED_OPTIONAL = {
    "feature-script.js": "the Demo film's script — which screens to drive and what to say "
                         "on each (rerun-film.py rewrites it; without it there is no film)",
}


def missing_model_work(review: Path) -> list[tuple[str, str]]:
    """Which model-written artifacts are not on disk, with what each one is.

    A directory counts as present when it exists and holds something: a directory left
    behind empty by a wipe is the same absence as no directory at all. A file an older run
    wrote in its place (`MODEL_OWNED_LEGACY`) counts as present."""
    gone = []
    for rel, what in MODEL_OWNED.items():
        p = review / rel
        legacy = MODEL_OWNED_LEGACY.get(rel)
        if not p.exists() and legacy and (review / legacy).is_file():
            continue
        if p.is_dir():
            if not any(p.iterdir()):
                gone.append((rel, what))
        elif not p.is_file():
            gone.append((rel, what))
    return gone


#: The film script's name, under the review directory. `record-feature-video.sh` also reads
#: `human-review-feature.js` at the repository root and `$HUMAN_REVIEW_FEATURE_SCRIPT`.
FILM_SCRIPT = "feature-script.js"


def film_script(review: Path) -> Path | None:
    """The script the recorder would film from, in its own order, or None."""
    for p in (os.environ.get("HUMAN_REVIEW_FEATURE_SCRIPT"), review / FILM_SCRIPT,
              Path("human-review-feature.js")):
        if p and Path(p).is_file():
            return Path(p)
    return None


def film_asked(steps: str) -> bool:
    """Whether this run's producers include the film: `all`, or a list naming `video`."""
    steps = (steps or "").strip()
    return steps == "all" or "video" in {s.strip() for s in steps.split(",")}


def config_base(explicit: str | None) -> str:
    """What the branch is measured against: the flag, the repo's config, else origin/main.

    Read here as well as in `run-steps.py` because the check below asks git a question
    about a *range*, and a range this program guessed differently from the producers would
    refuse a build over a commit the page never claimed to cover."""
    if explicit:
        return explicit
    try:
        cfg = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "origin/main"
    base = cfg.get("base") if isinstance(cfg, dict) else None
    return base if isinstance(base, str) and base.strip() else "origin/main"


def broken_points_promise(base: str) -> tuple[str, str] | None:
    """`(sha, path)` when a commit says it carries a points file that is not on disk.

    A `Review-Points:` trailer is a commit asserting that this branch records what was
    reviewed, fixed and declined. When the named file is not there, the page would render
    the absence honestly — a grey band — and be wrong about *why*: the record was not
    skipped, it was lost. That happens in exactly the ways nobody notices: a rebase that
    dropped the file while keeping the commit message, a cherry-pick of the fixes without
    it, a `git checkout --` over the working tree.

    So it is a refusal rather than a warning. Every other missing input on this page
    degrades to a named absence, because "this project has no such thing" is a real state;
    this one cannot be, because the commit already said otherwise. The two claims cannot
    both stand, and the build is not the place to choose between them.
    """
    proc = subprocess.run([sys.executable, str(REVIEW_COMMITS), "--base", base, "--json"],
                          capture_output=True, text=True)
    if not (proc.stdout or "").strip():
        return None
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return None
    rel = doc.get("points_file") or "review-points.md"
    # Only the trailer counts, never the fallback: the fallback *is* "the one commit that
    # touches the points file", so a fallback plus a missing file is a contradiction in
    # terms and would refuse every build on a branch that has neither.
    if doc.get("review") and not doc.get("fallback") and not Path(rel).is_file():
        return doc["review"], rel
    return None


#: The producers that drive a browser, record a film or run a whole test suite. Minutes
#: each, and each needs something up — a served app, a Chrome, a tracing backend — so they
#: are not what "refresh the page" should mean. `--steps all` is how you ask for them.
HEAVY_STEPS = ("sequence", "video", "city", "dsaudit")

#: The producers that need nothing but the repository: no served app, no browser, no film,
#: no test suite. This is the set a *button* may re-run — the Rerun in the page's header
#: (`serve-review.py`) asks for exactly this — and it is named here rather than there
#: because which producers are safe to fire off a click is a fact about the producers.
#:
#: It is not `cheap` minus the video, and the difference is the whole reason it exists.
#: `cheap` skips the four in HEAVY_STEPS and keeps `traces`, whose configured `commands`
#: are a project's own e2e suite — in petclinic, a cucumber run that needs the stack up on
#: :4200. Minutes, and a failure when nothing is listening. A reader who presses Rerun
#: after editing a test body is asking for the page to catch up with the repository, not
#: for a browser suite to be run at them.
STATIC_STEPS = ("reviewpoints", "aftermath", "diagrams", "c2", "c4", "complexity", "api",
                "specchanges", "logging", "owners", "tests")


def steps_argv(steps: str) -> list[str] | None:
    """`--steps` as arguments for `run-steps.py`, or None for "run no producers at all".

    The default is None and that is the common case: most refreshes are a change to the
    *page*, not to the evidence, and re-deriving evidence nothing touched is a minute of
    waiting for a byte-identical result."""
    steps = (steps or "").strip()
    if not steps or steps == "none":
        return None
    if steps == "all":
        return []
    if steps == "cheap":
        return ["--skip", ",".join(HEAVY_STEPS)]
    if steps == "static":
        return ["--only", ",".join(STATIC_STEPS)]
    return ["--only", steps]


def c4_pending(review: Path) -> bool:
    """A repository with a Structurizr DSL whose page has never had its C4 views drawn.

    The `c4` step is newer than most pages: a page built before it carries no
    `assets/c4/`, and a plain refresh — which runs no producer — would never draw them.
    So that one step is run once, the way the UX tab's fragment is re-rendered when an
    older ds-audit.py drew it. After that it is a producer like any other (`static`) —
    except after a run that could not draw (no Docker): that one is retried, so starting
    Docker and refreshing is the whole remedy the card's note promises."""
    try:
        held = json.loads((review / "assets" / "c4" / "verdict.json").read_text("utf-8"))
    except (OSError, ValueError):
        held = None
    if isinstance(held, dict) and held.get("state") in ("drawn", "none"):
        return False
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", "*.dsl"],
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


def plan(review: Path, steps: str, base: str | None, serve: bool,
         allow_model: bool, session: str | None, timing: bool = False,
         force: bool = False, c4: bool = False) -> list[list[str]]:
    """Every command this run will make, in order, as argv lists.

    Built as data so the decisions above are testable without running a browser, a build or
    a server — the same reason `run-steps.py` keeps its own step table as data."""
    out = []
    produce = steps_argv(steps)
    if produce is not None:
        out.append([sys.executable, str(RUN_STEPS), *produce]
                   + (["--base", base] if base else [])
                   + (["--timing"] if timing else [])
                   + (["--force"] if force else [])
                   # A refresh never stamps the ledger. Its windows would name a stretch of
                   # a *later* session, in which none of the reviewed conversation happened,
                   # and moving `.steps.json` costs the build the whole cost ledger, which
                   # is keyed on it. See `run-steps.Ctx`.
                   + ["--no-ledger"])
    elif c4:
        out.append([sys.executable, str(RUN_STEPS), "--only", "c4"]
                   + (["--base", base] if base else []) + ["--no-ledger"])
    # The UX tab is a fragment pasted whole, written by a step no refresh runs (it needs both
    # sides' stacks up). Re-drawn here from its own JSON when an older ds-audit.py drew it —
    # a no-op otherwise — so a change to how the audit renders reaches every page on its next
    # rebuild, rather than only the pages whose audit happens to be captured again.
    if (review / "assets" / "ds-audit.json").is_file():
        out.append([sys.executable, str(DS_AUDIT), "--rerender-if-stale", str(review)])
    build = [sys.executable, str(BUILD), str(review / "content.json"),
             "--out", str(review / "review.html")]
    if not allow_model:
        build.append("--no-model")
    out.append(build)
    if serve:
        out.append([sys.executable, str(SERVE), str(review)])
    return out


#: Where the build leaves the merged pairing, and — when the model's half never read some of
#: the tests now on the card — why (`semcov.write_fragment`, key `stale`).
MERGED_MAPPING = "assets/test-mapping.merged.json"


def stale_pairing(review: Path, since: float | None = None) -> dict | None:
    """`{"why", "command"}` when the build just drew the Tests tab from a pairing that has
    not read every test now on the card (`semcov.pairing_stale`), else None. Only a merged
    file this run wrote counts (`since`): one left by an earlier build says nothing about
    this one."""
    p = review / MERGED_MAPPING
    try:
        if since is not None and p.stat().st_mtime < since:
            return None
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    got = doc.get("stale") if isinstance(doc, dict) else None
    return got if isinstance(got, dict) and got.get("why") else None


def warn_stale_pairing(stale: dict) -> None:
    """The warning, loud, on stderr — repeated after the build's own output so it is the
    last thing on the screen rather than one line in a scroll of build chatter. It never
    runs the model: the pairing is the one paid step, and only a human starts it."""
    bar = "!" * 78
    print(f"[refresh] {bar}\n[refresh] WARNING: the Tests tab's pairing has not read every "
          f"test now on the card — {stale['why']}.\n[refresh] The page says so, as a !🤖 pill after the ticket checkbox. Re-run the "
          f"pairing step (a paid model call), then refresh:\n[refresh]   "
          f"{stale.get('command') or 'rerun-model.py'}\n[refresh] {bar}", file=sys.stderr)


def session_id(review: Path) -> str | None:
    """The session that did the work, so a rebuilt page keeps reporting its real cost.

    A build run in a later session cannot recompute what the first one spent, and a page
    that silently drops the number is a page that looks free. The run wrote the id down
    for exactly this; passing it back is what makes a refresh a refresh and not a new,
    cheaper-looking review."""
    p = review / ".session"
    try:
        # Present but blank is an answer, not a gap: the run was started by a harness with
        # no Claude session id (Copilot, Codex), so there is no transcript to price. It
        # comes back as "" — not None — so the caller can stop the refreshing session's
        # own id from standing in for it. That stand-in billed a Copilot run $39 for the
        # Claude conversation that merely pressed refresh.
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def run_started(review: Path) -> float | None:
    """`.started` as epoch seconds, or None when the run never wrote one."""
    try:
        raw = (review / ".started").read_text(encoding="utf-8").strip()
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".human-review", help="the review directory")
    ap.add_argument("--steps", default="none",
                    help="none (default), static, cheap, all, or a comma-separated list")
    ap.add_argument("--base", help="base ref for the producers (default: the config's)")
    ap.add_argument("--no-serve", dest="serve", action="store_false",
                    help="write the page and do not start the server")
    ap.add_argument("--allow-model", action="store_true",
                    help="let the build make the Logging tab's uncached privacy calls")
    ap.add_argument("--timing", action="store_true",
                    help="print what each producer and each phase of this run cost")
    ap.add_argument("--force", action="store_true",
                    help="re-run every producer, including the ones whose inputs are "
                         "unchanged (the default is to skip those and say so)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    args = ap.parse_args(argv)

    review = Path(args.dir)
    if not review.is_dir():
        print(f"[refresh] no {review}/ here — there is no report to refresh. "
              "Run /human-review from the repository root first.", file=sys.stderr)
        return 2

    gone = missing_model_work(review)
    if gone:
        print(f"[refresh] {review}/ is missing the parts only a model writes:",
              file=sys.stderr)
        for rel, what in gone:
            print(f"  - {rel} — {what}", file=sys.stderr)
        print("[refresh] this program does not write them, on purpose: they are a "
              "judgement, and a second pass over the same diff produces a different one "
              "at full price. Restore them, or ask for /human-review to run its own half "
              "again.", file=sys.stderr)
        return 3

    base = config_base(args.base)
    promise = broken_points_promise(base)
    if promise:
        sha, rel = promise
        print(f"[refresh] {sha[:8]} carries a `Review-Points: {rel}` trailer and {rel} is "
              f"not on disk.", file=sys.stderr)
        print("[refresh] that commit says this branch records what was reviewed, fixed "
              "and declined. The record is gone — a rebase or a cherry-pick dropped the "
              "file and kept the message. A page built now would say nothing was ever "
              "recorded, which is not what happened. Restore the file (`git checkout "
              f"{sha} -- {rel}`), or drop the trailer if the claim was never true.",
              file=sys.stderr)
        return 3

    if film_asked(args.steps) and film_script(review) is None:
        # A note, never a refusal (see MODEL_OWNED_OPTIONAL): the step will say "no feature
        # script" and the Demo tab "nothing was filmed". This only says who writes it.
        print(f"[refresh] no {FILM_SCRIPT} — the film's script is model-written and this "
              "program does not write it; rerun-film.py does (the Demo tab's 🤖). The video "
              "step will film nothing.", file=sys.stderr)

    if not args.dry_run:
        # The logs an earlier build left beside the page (eval run 11: a `refresh.out` from
        # another folder, a `run-steps-2.out` from an old base) — whatever was last written
        # before this run's `.started`. This run's own, and this refresh's, are newer.
        started = run_started(review)
        if started is not None:
            sys.path.insert(0, str(HERE))
            from preflight import sweep_old_logs
            for name in sweep_old_logs(review, started):
                print(f"[refresh] removed {name}, a log from before this run", flush=True)

    commands = plan(review, args.steps, args.base, args.serve,
                    args.allow_model, session_id(review), args.timing, args.force,
                    c4=c4_pending(review))
    env = dict(os.environ)
    sid = session_id(review)
    if sid:
        env["CLAUDE_CODE_SESSION_ID"] = sid
    elif sid == "":
        env.pop("CLAUDE_CODE_SESSION_ID", None)

    url = ""
    began = time.time()
    phases: list[tuple[str, float]] = []
    for cmd in commands:
        printable = " ".join(Path(c).name if c.startswith("/") and Path(c).exists() else c
                             for c in cmd)
        # Flushed, because the served page reads this line to learn the build has begun
        # (`rerun.js`), and to a pipe Python holds it in a buffer until the process ends —
        # the band and the tab fills stood still for the whole build, then the page reloaded.
        print(f"[refresh] $ {printable}", flush=True)
        if args.dry_run:
            continue
        is_serve = cmd[1] == str(SERVE)
        t0 = time.monotonic()
        proc = subprocess.run(cmd, env=env, text=True,
                              capture_output=is_serve)
        phases.append((Path(cmd[1]).stem, time.monotonic() - t0))
        if is_serve:
            url = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        # A producer that fails is a fact about the run and the page still gets built —
        # the build names the evidence it could not find. A failing *build* is different:
        # there is no page, and serving the last one under a fresh URL would be the one
        # outcome nobody can tell from success.
        if proc.returncode != 0 and cmd[1] == str(BUILD):
            print("[refresh] the build failed — the page on disk is the previous one.",
                  file=sys.stderr)
            return 1
    if phases and not args.dry_run:
        # A refresh's own time goes on the run's cost record (`report-cost.json`), never
        # money: it called no model, and the run it refreshes was billed once already.
        try:
            sys.path.insert(0, str(HERE))
            import harness_cost
            harness_cost.note_refresh(review, sum(s for p, s in phases
                                                  if p != Path(str(SERVE)).stem), args.steps)
        except Exception as exc:  # noqa: BLE001 — a timing note must never fail a refresh
            print(f"[refresh] refresh time not recorded: {exc}", file=sys.stderr)
    if args.timing and phases:
        # The three phases of a refresh — produce, build, serve — as three numbers, because
        # "the refresh takes two minutes" was never actionable: whether that is the
        # producers or the build decides whether the fix is a cache or a profiler.
        print("\n[refresh] phase             seconds")
        for phase, secs in phases:
            print(f"[refresh]   {phase:<16} {secs:7.2f}")
        print(f"[refresh]   {'TOTAL':<16} {sum(s for _, s in phases):7.2f}")
    if not args.dry_run:
        stale = stale_pairing(review, since=began)
        if stale:
            warn_stale_pairing(stale)
    if url:
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
