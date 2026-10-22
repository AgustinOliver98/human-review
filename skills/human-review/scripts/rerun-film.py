#!/usr/bin/env python3
"""Ask a model for the Demo film's script, and nothing else.

The second model-written artifact of `/human-review`, beside the requirements↔tests matrix:
`.human-review/feature-script.js`, the twenty-odd lines that say what to click while the
recorder films (`record-feature-video.sh`, the `video` step of `run-steps.py`). The harness
is a program; *which screens the change touched and what to say on each* is a judgement,
read off the diff, and a second pass words and orders it differently. So it is owned the
way the matrix is: `refresh-report.py` never writes it, and this is the one command that
does — `claude -p --model sonnet` over `reference/film-prompt.md`, the guidance of
`reference/feature-script.md` spelt as a prompt.

A sibling of `rerun-model.py` rather than a flag on it, because nothing about the two runs
is shared except the plumbing: a different prompt, a different artifact, a different check
that the result is usable, and a different price — so a different ledger, or the matrix's
button would quote an average over two kinds of work. The plumbing itself (the argv, the
cost field, the ledger writer) is borrowed from `rerun-model.py`, not copied.

The same three properties, for the same reasons:

- **Sonnet, named.** `HUMAN_REVIEW_MODEL` overrides it, as it does for the matrix.
- **The previous script is kept**, as `.human-review/.model-prev/feature-script.js`, before
  the model starts. A film the reader liked has to survive the click that replaced it.
- **It refuses rather than hand the recorder a broken script.** The result must exist, be
  non-empty, parse (`node --check`) and export a function — the one shape the recorder
  accepts (`typeof flow !== "function"` is its own first check). Anything else exits
  non-zero before the film step is reached, naming what is wrong and where the old one is.

    rerun-film.py                      # rewrite .human-review/feature-script.js
    rerun-film.py --dir .human-review  # …explicitly
    rerun-film.py --dry-run            # print the command, spend nothing

It does not film. The served page's 🤖 on the Demo tab — and the line its clipboard face
hands out — run `refresh-report.py --steps video --no-serve` after it, chained with `&&`
by the build's action register (`hrbuild/shared/actions.py`), so the button and the pasted
line are one string. `--dry-run` spends nothing, and every test of this file goes through it
or through a stubbed `claude`.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _sibling(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: The matrix's program, for its plumbing: `claude_argv`, `_priced`, `record_run`, `MODEL`.
MODEL_STEP = _sibling("hr_rerun_model_for_film", "rerun-model.py")

#: The prompt — `reference/feature-script.md`'s rules, addressed to the run that pays for them.
PROMPT = HERE.parent / "reference" / "film-prompt.md"

#: What the model owns here, relative to the review directory. The first of the recorder's
#: three candidates (`record-feature-video.sh`), so what this writes is what gets filmed —
#: unless `$HUMAN_REVIEW_FEATURE_SCRIPT` points elsewhere, which `main` warns about.
WRITES = "feature-script.js"

#: Shared with the matrix: one dot-prefixed folder of "what the last paid press replaced",
#: kept out of `publish-demo.sh`'s copy for the same reason.
PREV = MODEL_STEP.PREV

#: This button's own spending, so its hover quotes what *a film script* has cost here.
RUNS_LEDGER = ".film-runs.json"

LOOKS_LIKE_A_REVIEW = MODEL_STEP.LOOKS_LIKE_A_REVIEW

#: Loads the script the way the recorder will (`require`, then `typeof … === "function"`),
#: with one difference: a dependency that does not resolve *here* — the recorder runs with
#: the project's own `NODE_PATH` — is stubbed rather than fatal, because "playwright is not
#: on this NODE_PATH" is a fact about this check, not about the script.
EXPORTS_CHECK = r"""
const Module = require("module");
const real = Module.prototype.require;
const stub = new Proxy(function () {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? () => "" : stub),
  apply: () => stub, construct: () => stub,
});
Module.prototype.require = function (id) {
  try { return real.apply(this, arguments); }
  catch (e) { if (e && e.code === "MODULE_NOT_FOUND" && id !== process.argv[1]) return stub; throw e; }
};
const flow = require(process.argv[1]);
process.exit(typeof flow === "function" ? 0 : 3);
"""


#: The shell commands the writer may run unasked: reading the diff and the templates, and
#: running its own route deriver and `node --check` on the result. With `--setting-sources
#: ""` the user's allow-list is not loaded, so anything past this list is denied rather than
#: prompted for. `cd`, `env` and `npx` are on it because the deriver is run as
#: `cd .human-review && NODE_PATH=… node changed-screens.js`: without them, the first run of
#: this list (22 Oct 2026) shipped a deriver it could not test, and filmed 1 screen of 3.
FILM_BASH = ("git", "node", "npx", "cd", "env", "ls", "cat", "head", "tail", "grep", "find",
             "wc", "sed", "jq", "echo")


def film_argv(root: Path) -> list[str]:
    """`claude_argv` without what a script writer never uses: MCP servers, the user's
    settings (hooks, plugins, CLAUDE.md), the saved session, and every tool but the six it
    needs. Measured on 22 Oct 2026, one Bash call on Sonnet: $0.107 with the plain argv,
    $0.013 with this — and the 60k tokens it no longer carries are re-read on every turn
    of a twenty-turn run, not only the first."""
    extra = (os.environ.get("HUMAN_REVIEW_MODEL_ARGS") or "").split()
    return ["claude", "-p", "--model", MODEL_STEP.MODEL, "--permission-mode", "acceptEdits",
            "--output-format", "json", "--strict-mcp-config", "--no-session-persistence",
            "--setting-sources", "", "--tools", "Bash,Read,Write,Edit,Glob,Grep",
            "--allowedTools", *[f"Bash({c}:*)" for c in FILM_BASH],
            "--add-dir", str(root), *extra]


def broken(script: Path, cwd: Path | None = None) -> str | None:
    """Why the recorder could not use this script, or None when it could.

    In the order a reader would want to hear it: not there, empty, does not parse, parses
    and exports something that is not a function. Each is a script the `video` step would
    turn into *nothing was filmed* — or worse, a film of nothing — so each is a refusal here,
    while the previous script is still one copy away."""
    if not script.is_file():
        return "it was not written"
    if not script.read_text(encoding="utf-8", errors="replace").strip():
        return "it is empty"
    node = shutil.which("node")
    if not node:
        return "there is no `node` on PATH to check it with"
    check = subprocess.run([node, "--check", str(script)], capture_output=True, text=True,
                           timeout=30)
    if check.returncode != 0:
        lines = [l for l in (check.stderr or "").splitlines() if l.strip()]
        why = next((l for l in lines if "Error" in l), lines[0] if lines else "")
        return f"it does not parse (node --check: {why.strip() or check.returncode})"
    load = subprocess.run([node, "-e", EXPORTS_CHECK, str(script.resolve())],
                          capture_output=True, text=True, timeout=30,
                          cwd=str(cwd) if cwd else None)
    if load.returncode == 3:
        return "it does not export a function (module.exports = async ({page, say, …}) => …)"
    if load.returncode != 0:
        lines = [l for l in (load.stderr or "").splitlines() if l.strip()]
        why = next((l for l in lines if "Error" in l), lines[-1] if lines else "")
        return f"it throws when loaded ({why.strip() or load.returncode})"
    return None


def keep_previous(review: Path) -> Path | None:
    """Copy today's script into `.model-prev/`, and return where; None when there was none.

    With every other `*.js` beside it: a script derives its screens from the diff, and the
    derivation usually lives in a helper it `require`s (`./changed-screens.js` on petclinic),
    which the model may rewrite too. A kept script whose helper moved on is not a film that
    can be put back.

    Copied, not moved: the prompt tells the model to start from it, which it can only do
    if it is still where the recorder looks while the model is working."""
    if not (review / WRITES).is_file():
        return None
    dest = review / PREV
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(review.glob("*.js")):
        if src.is_file():
            shutil.copy2(src, dest / src.name)
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".human-review", help="the review directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the command and spend nothing")
    args = ap.parse_args(argv)

    review = Path(args.dir)
    if not review.is_dir() or not (review / LOOKS_LIKE_A_REVIEW).is_file():
        print(f"[film] {review}/ is not a review directory — no {LOOKS_LIKE_A_REVIEW} in "
              "it, so there is no report to film for. Run /human-review from the repository "
              "root first.", file=sys.stderr)
        return 2
    if not PROMPT.is_file():
        print(f"[film] {PROMPT} is missing — that file *is* the step.", file=sys.stderr)
        return 2

    prompt = PROMPT.read_text(encoding="utf-8")
    root = Path.cwd().resolve()
    argvec = film_argv(root)
    model = MODEL_STEP.MODEL
    print("[film] $ " + " ".join(a if a else '""' for a in argvec)
          + f"  < {PROMPT.name} ({len(prompt)} chars)")
    elsewhere = os.environ.get("HUMAN_REVIEW_FEATURE_SCRIPT")
    if elsewhere:
        # Not a refusal: the variable may be the very file the reader wants kept. But the
        # recorder reads it *first*, so a film after this run would not show what it wrote.
        print(f"[film] note: $HUMAN_REVIEW_FEATURE_SCRIPT={elsewhere} — the recorder reads "
              f"that before {review}/{WRITES}, so the film will not use what this writes.",
              file=sys.stderr)
    if args.dry_run:
        print(f"[film] dry run — nothing was asked of {model} and nothing was paid for.")
        return 0

    if not shutil.which("claude"):
        print("[film] no `claude` on PATH. This step is the skill's model half spelt as a "
              "command; without the CLI there is nothing to spell it with.", file=sys.stderr)
        return 2
    if not shutil.which("node"):
        # Before the money, not after: without node the result cannot be checked, and an
        # unchecked script is exactly what this program exists not to hand the recorder.
        print("[film] no `node` on PATH — the script could be written and never checked, "
              "and the recorder needs node anyway.", file=sys.stderr)
        return 2

    kept = keep_previous(review)
    if kept:
        print(f"[film] the script being replaced is in {kept}/ — this is a judgement, not "
              "a refresh, and the film you were watching has to survive the click.")
    started = time.time()
    proc = subprocess.run(argvec, cwd=str(root), input=prompt, text=True,
                          capture_output=True)
    cost, said = MODEL_STEP._priced(proc.stdout)
    if said:
        print(said)
    elif proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    MODEL_STEP.record_run(review, cost, time.time() - started, ledger=RUNS_LEDGER,
                          out=proc.stdout)
    if proc.returncode != 0:
        print(f"[film] {model} exited {proc.returncode}; the script on disk is whatever it "
              "managed to write.", file=sys.stderr)
        return 1

    why = broken(review / WRITES, root)
    if why:
        print(f"[film] {review}/{WRITES} is not a script the recorder can run: {why}.",
              file=sys.stderr)
        print(("[film] the previous one is in " + str(kept) + "/ — copy it back rather than "
               "filming nothing.") if kept else
              "[film] there was no previous script; the Demo tab will say nothing was "
              "filmed until one is written.", file=sys.stderr)
        return 4
    print("[film] film script rewritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
