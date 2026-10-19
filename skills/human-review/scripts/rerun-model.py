#!/usr/bin/env python3
"""Ask a cheap model for the one judgement the Tests tab's matrix still needs, and nothing else.

`refresh-report.py` is the machine half of `/human-review`: fixed inputs, fixed outputs,
free, safe to run again at any time. This is the other half, reduced to the smallest thing
that can still be a *command*. The matrix used to be all of it — a model wrote
`assets/requirements-map.html` and a `test-index/` catalogue, layout and CSS included, at
$4–$10 a run. Now `semcov.py` draws the matrix and proposes pairings on its own, from shared
evidence — but a shared word is a *candidate*, not proof: run 5 painted "sortable by any
column" green over a test that checks the page size. So this program asks a model, in one
call, to confirm or reject every link the script made (one line of reason each), to pair
the sentences the script could not, and to mark a sentence a recorded scope decision
narrowed — and writes the answer, `test-mapping.json`, checked against
`reference/test-mapping.schema.json`. The build merges it in; without it no scripted link
is shown as covering anything.

The Demo film's script, the other model-written artifact, has a sibling of this program:
`rerun-film.py`, which borrows its plumbing (`claude_argv`, `_priced`, `record_run`).

Five properties are the whole point:

- **A cheap model, named here.** `haiku` by default: choosing among eight tests for a
  sentence is not work that needs more. `--model`, `"mappingModel"` in the repository's
  `human-review.json`, or `$HUMAN_REVIEW_MAPPING_MODEL` change it. Its price lands on the
  cost tab through `.model-runs.json`, read off the CLI's own `total_cost_usd`.
- **Every scripted link is a candidate, and the model confirms or rejects each one** — with
  the open sentences, in the same single call. Only a ticket with no claim in it at all gets
  an empty answer written and no model run.
- **What it claims is checked by passes that can only lower it.** Eval run 8's Haiku answer
  called 25 of 27 sentences covered and none partial. A free script rule drops a link whose
  test shares nothing specific with its sentence (`semcov.sanity`) — unless the model quoted
  the assertion line and it is in the body, and never down to red on its own; a second cheap call
  re-reads every kept link against the test body and must quote the assertion line, looked
  up in the real body (`matrix-check-prompt.md`, `semcov.apply_check`). Neither ever adds a
  link or raises a coverage word. `--no-check` / `"mappingCheck": false` skips the second.
- **The previous answer is kept**, under `.human-review/.model-prev/`. Dot-prefixed,
  because `publish-demo.sh` publishes what does not start with a dot.
- **It refuses rather than half-writes.** An answer that is not JSON, fails the schema,
  names a sentence it was not asked about or a test it was not shown, or claims a coverage
  its own links cannot stand behind, is not written: this exits non-zero, says why, and the
  file on disk stays what it was.

    rerun-model.py                      # confirm/reject the scripted links, pair the rest
    rerun-model.py --dry-run            # print the command and what is open, spend nothing
    rerun-model.py --prompt-only        # the whole prompt on stdout, for another harness
    rerun-model.py --answer reply.json  # validate and install an answer made elsewhere

`--prompt-only` and `--answer` are how a session that is not Claude Code runs this step:
GitHub Copilot picks its cheap model itself (*Auto*, or `gpt-5-mini`), so it reads the
prompt, answers it, and hands the answer back here to be checked and written.

`--dry-run` is not a nicety either: every test of this file, and every check that the
button is wired to the right program, runs through it. Nothing below it may cost money.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The prompt, beside the skill's other prose rather than inside this file. It is the thing
#: being paid for, so it is reviewed like prose and diffed like prose. The sentences, the
#: links the script made for each, their candidate tests and the recorded scope decisions
#: are appended to it as JSON.
PROMPT = HERE.parent / "reference" / "matrix-prompt.md"
#: The second read: every link the first answer kept, re-read against the test bodies by
#: another cheap call whose verdicts can only lower what the first claimed (`semcov.
#: apply_check`). Eval run 8's Haiku answer called 25 of 27 sentences covered and none
#: partial; this is what makes a cheap model's "covered" worth reading.
CHECK_PROMPT = HERE.parent / "reference" / "matrix-check-prompt.md"
#: Where a repository turns the second read off, in `human-review.json` (`false`).
MAPPING_CHECK_KEY = "mappingCheck"

#: What the model owns, in `refresh-report.MODEL_OWNED`'s own spelling minus `content.json`
#: — the layout and the ledes are a human's answer to "what is this page for", and no
#: button regenerates those.
WRITES = ("test-mapping.json",)

#: The model the pairing asks by default. Sonnet, chosen by Victor on 3 Oct 2026 from a
#: measurement on eval run 8: one Sonnet call got 5 of the 6 sentences the judges flagged
#: right in ~100 s for $0.42; haiku with its downgrade-only second read got 3 of 6 in
#: ~340 s for $0.35. Haiku stays one setting away (`"mappingModel": "haiku"`). A Copilot
#: session picks its own (*Auto* or `gpt-5-mini`) and comes back through `--answer`.
MAPPING_MODEL_DEFAULT = "sonnet"
#: The models the downgrade-only second read is for: it was built to catch haiku's
#: over-claiming, and on Sonnet it would only double the price.
CHECKED_MODELS = ("haiku",)
#: Where a repository says which model pairs its sentences, in `human-review.json`.
MAPPING_MODEL_KEY = "mappingModel"

#: Where the copy being replaced goes. Dot-prefixed: see the module docstring.
PREV = ".model-prev"

#: What each paid run really cost, appended here so the button that spends it can stop
#: guessing. The label used to read `~$5 on Sonnet` — a number typed once, never measured —
#: and three real runs on the demo page came in at $4.00, $8.09 and $10.63. A reader who
#: budgeted for the label was out by a factor of two, in the direction that matters.
#:
#: Dot-prefixed like the manifest, and for the same reason: it is a record of this
#: machine's spending, not a fact about the branch, so it must not travel in the zip.
RUNS_LEDGER = ".model-runs.json"
RUNS_KEPT = 20

#: The film script's model (`rerun-film.py` reads it here), named rather than defaulted.
#: `HUMAN_REVIEW_MODEL` overrides it for the one case that is not a preference — a harness
#: where `sonnet` resolves to nothing. The pairing does not use it: see `mapping_model`.
MODEL = os.environ.get("HUMAN_REVIEW_MODEL") or "sonnet"


def mapping_model(flag: str | None = None, config: Path = Path("human-review.json")) -> str:
    """Which model pairs the open sentences: the flag, then `$HUMAN_REVIEW_MAPPING_MODEL`,
    then the repository's `human-review.json` (`"mappingModel"`), then sonnet."""
    if flag:
        return flag
    if os.environ.get("HUMAN_REVIEW_MAPPING_MODEL"):
        return os.environ["HUMAN_REVIEW_MAPPING_MODEL"]
    try:
        got = json.loads(config.read_text(encoding="utf-8")).get(MAPPING_MODEL_KEY)
        if isinstance(got, str) and got.strip():
            return got.strip()
    except (OSError, ValueError, AttributeError):
        pass
    return MAPPING_MODEL_DEFAULT


def mapping_argv(model: str) -> list[str]:
    """The pairing's headless invocation: the prompt on stdin, the answer in the JSON
    envelope's `result`. No tools at all — everything the model needs is in the prompt, and
    a run that cannot open a file cannot wander the repository at the invoice's expense —
    and no MCP servers, which would only slow it down."""
    extra = (os.environ.get("HUMAN_REVIEW_MODEL_ARGS") or "").split()
    return ["claude", "-p", "--model", model, "--output-format", "json", "--tools", "",
            "--strict-mcp-config", *extra]


def mapping_check(flag: bool | None = None, config: Path = Path("human-review.json"),
                  model: str | None = None) -> bool:
    """Whether the second, downgrade-only read runs: `--no-check`, then
    `$HUMAN_REVIEW_MAPPING_CHECK` (`0`/`false`/`off`), then `"mappingCheck"` in the
    repository's `human-review.json`, then on for the models in CHECKED_MODELS only."""
    if flag is False:
        return False
    env = os.environ.get("HUMAN_REVIEW_MAPPING_CHECK")
    if env is not None and env.strip():
        return env.strip().lower() not in ("0", "false", "off", "no")
    try:
        got = json.loads(config.read_text(encoding="utf-8")).get(MAPPING_CHECK_KEY)
        if isinstance(got, bool):
            return got
    except (OSError, ValueError, AttributeError):
        pass
    if model is None:
        return True
    return any(m in model.lower() for m in CHECKED_MODELS)


def build_check_prompt(chk_input: dict) -> str:
    """The second read's prompt file, then the links to re-read, as JSON."""
    return (CHECK_PROMPT.read_text(encoding="utf-8").rstrip() + "\n\n## Input\n\n```json\n"
            + json.dumps(chk_input, indent=1, ensure_ascii=False) + "\n```\n")


def _ask(argvec: list[str], prompt: str, root: Path) -> tuple:
    """`(proc, cost, said, seconds)` of one headless call."""
    started = time.time()
    proc = subprocess.run(argvec, cwd=str(root), input=prompt, text=True, capture_output=True)
    cost, said = _priced(proc.stdout)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc, cost, said, time.time() - started


def _combined(outs: list[str]) -> str:
    """One CLI-shaped reply out of several, for the ledger: the costs added and the token
    counts summed per model — a press of the button is one row, however many calls it took
    (`review-cost.py` bills the ledger's last row as *the* run)."""
    cost, usage = None, {}
    for out in outs:
        c, _ = _priced(out)
        if isinstance(c, (int, float)):
            cost = (cost or 0.0) + c
        try:
            doc = json.loads(out)
        except (TypeError, ValueError):
            continue
        for name, u in ((doc.get("modelUsage") or {}) if isinstance(doc, dict) else {}).items():
            if isinstance(u, dict):
                acc = usage.setdefault(name, {})
                for k in _MODEL_USAGE_KEYS:
                    acc[k] = acc.get(k, 0) + int(u.get(k) or 0)
    return json.dumps({"total_cost_usd": cost, "modelUsage": usage})


def downgrade(sc, doc: dict, g: dict) -> tuple[dict, str]:
    """`(answer, what was lowered)` after the script's free sanity rule."""
    texts = {s["id"]: s["text"] for s in g["sentences"]}
    doc, dropped = sc.sanity(doc, texts, g["docs"])
    return doc, (f"the script dropped {dropped} link(s) sharing nothing specific with their "
                 "sentence" if dropped else "")


def checked(sc, doc: dict, chk, asked: dict) -> tuple[dict, str]:
    """`(answer, what the second read lowered)` — or the answer untouched, saying why, when
    the read is unusable or would leave an answer the checks refuse."""
    bad = sc.check_problems(chk)
    if bad:
        return doc, "the second read was unusable (" + "; ".join(bad) + ") — nothing lowered"
    out, lowered = sc.apply_check(doc, chk, asked)
    if sc.problems(out, *_facts(asked)):
        return doc, "the second read's result failed the checks — nothing lowered"
    return out, (f"a second read lowered {lowered['links']} link(s) and "
                 f"{lowered['sentences']} sentence(s)"
                 if lowered["links"] or lowered["sentences"] else "")


def _noted(doc: dict, *said: str) -> dict:
    parts = [x for x in (doc.get("note"), *said) if x]
    return {**doc, "note": "; ".join(parts)} if parts else doc


#: What makes a directory a review directory. Checked before anything is bought, because
#: `--dir` arrives from a server that computed it as a path *relative to the repository
#: root* — so the value is `.` whenever the report is served from the root itself, and `.`
#: is a directory that exists. Without this, a misconfigured server would have handed a
#: model the repository and asked it to write a matrix into it, at full price, and the
#: first sign of trouble would have been the invoice.
LOOKS_LIKE_A_REVIEW = "content.json"


def claude_argv(root: Path) -> list[str]:
    """The headless invocation, as argv, with the prompt going in on **stdin**.

    On stdin and not as the trailing argument, which is how this was first written and
    which does not work: `--add-dir` takes a *list* of directories, so a prompt after it is
    swallowed as another directory and `claude` exits with "Input must be provided" — a
    failure that looks like a broken model step and is actually a broken command line. It
    is also the safer shape, because a 4KB positional argument is a 4KB positional
    argument.

    `--permission-mode acceptEdits` because the run's whole job is to write two files and
    there is nobody at a keyboard to approve each one; `--add-dir` so the repository is
    reachable when the server's cwd and the repository are not the same directory. Built as
    data, and printed by `--dry-run`, so "which model did that page cost" is a question the
    command answers rather than one the invoice does.
    """
    extra = (os.environ.get("HUMAN_REVIEW_MODEL_ARGS") or "").split()
    return ["claude", "-p", "--model", MODEL, "--permission-mode", "acceptEdits",
            "--output-format", "json", "--add-dir", str(root), *extra]


def missing(review: Path) -> list[str]:
    """Which of the model's artifacts is not on disk, or is on disk and empty."""
    gone = []
    for rel in WRITES:
        p = review / rel
        if p.is_dir():
            if not any(p.iterdir()):
                gone.append(rel)
        elif not p.is_file() or not p.stat().st_size:
            gone.append(rel)
    return gone


def _semcov():
    """`semcov.py`, the scripted half: what is open, what to ask, how to check the answer."""
    import importlib.util
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    if "semcov" in sys.modules:
        return sys.modules["semcov"]
    spec = importlib.util.spec_from_file_location("semcov", HERE / "semcov.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["semcov"] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_answer(text: str):
    """The JSON document out of a model's reply: the whole reply, or the one fenced block
    in it, or the span from the first `{` to the last `}`. None when there is none."""
    text = (text or "").strip()
    for candidate in (text,
                      *[m.group(1) for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S)],
                      text[text.find("{"):text.rfind("}") + 1] if "{" in text else ""):
        try:
            doc = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def build_prompt(asked: dict) -> str:
    """The prompt file, then what is open, as the JSON the prompt describes."""
    return (PROMPT.read_text(encoding="utf-8").rstrip() + "\n\n## Input\n\n```json\n"
            + json.dumps(asked, indent=1, ensure_ascii=False) + "\n```\n")


def _facts(asked: dict) -> tuple:
    return ({x["id"] for x in asked["sentences"]}, {t["id"] for t in asked["tests"]},
            {x["id"]: [t["id"] for t in x.get("scripted") or []] for x in asked["sentences"]},
            {d["id"] for d in asked.get("decisions") or []})


def check_answer(doc, asked: dict) -> list[str]:
    """Every reason this answer may not be written: the schema, then the facts — only the
    sentences asked about, only the tests shown, a verdict on every link the script made,
    and only the decisions listed."""
    if doc is None:
        return ["the reply holds no JSON object"]
    return _semcov().problems(doc, *_facts(asked))


def judged(doc, asked: dict):
    """`(answer to install or None, problems, dropped sentence ids)` — `semcov.salvage`: a
    sentence with a problem of its own is dropped (it stays unconfirmed on the page), a
    problem with the whole document refuses it."""
    if doc is None:
        return None, ["the reply holds no JSON object"], []
    return _semcov().salvage(doc, *_facts(asked))


def keep_refused(review: Path, text: str) -> Path | None:
    """The reply that was refused, kept where a reader can see what the model said."""
    dest = review / PREV / "test-mapping.refused.json"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return dest
    except OSError:
        return None


def install(review: Path, doc: dict, offered: list[str] | None = None,
            digests: dict[str, str] | None = None) -> Path:
    """Write the answer, by everyone's name for it — with `offered`, the ids of every test
    the model was shown, and `digests` (`offeredDigest`), a fingerprint of each one's body
    as it was shown, so a later build can tell when the card offers a test this answer never
    read, or one whose body has changed since (`semcov.pairing_stale`). Neither given: the
    record `doc` already carries stays as it is (the second read's path)."""
    if offered is not None:
        doc = {**doc, "offered": list(offered)}
    if digests is not None:
        doc = {**doc, "offeredDigest": dict(digests)}
    out = review / WRITES[0]
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def keep_previous(review: Path) -> Path:
    """Put today's answer somewhere a reader can get it back from, and return where.

    Copied and not moved: until the new answer has passed its checks, the old one is still
    the one the page is built from."""
    dest = review / PREV
    dest.mkdir(parents=True, exist_ok=True)
    for rel in WRITES:
        src = review / rel
        target = dest / Path(rel).name
        if src.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src, target)
        elif src.is_file():
            shutil.copy2(src, target)
    return dest


def _priced(out: str):
    """`(cost, what the model said)` out of `claude -p --output-format json`.

    `(None, "")` for anything this does not recognise, which is not an error: the run
    happened and the artifacts are on disk either way, and a bookkeeping field that moved
    between CLI versions must never be the reason a $5 run reports as a failure.
    """
    try:
        doc = json.loads(out)
        if not isinstance(doc, dict):
            raise ValueError
    except Exception:
        return None, ""
    cost = doc.get("total_cost_usd")
    return (float(cost) if isinstance(cost, (int, float)) else None,
            doc.get("result") or "")


#: The four token counts a turn is billed for, in the CLI's two spellings: `usage` is the
#: API's snake_case, `modelUsage` (one entry per model the run called) its camelCase.
_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
               "cache_read_input_tokens")
_MODEL_USAGE_KEYS = ("inputTokens", "outputTokens", "cacheCreationInputTokens",
                     "cacheReadInputTokens")


def _usage(out: str) -> tuple[int | None, dict]:
    """`(tokens, {model id: tokens})` out of `claude -p --output-format json`.

    Eval run 6's cost tab billed the mapping `$0.16` beside `0` tokens: the ledger kept the
    CLI's dollar figure and dropped the token counts printed right next to it, so the run
    read as money spent on nothing. The same four fields `review-cost.py` counts for a
    transcript turn (`turn_tokens`), so the two kinds of row add up in one column.
    `modelUsage` first — it names every model the run called; `usage` when that is absent.
    `(None, {})` for anything unrecognised, for `_priced`'s reason: bookkeeping never fails
    a run."""
    try:
        doc = json.loads(out)
        if not isinstance(doc, dict):
            raise ValueError
    except Exception:
        return None, {}
    per_model = {}
    for name, u in (doc.get("modelUsage") or {}).items():
        if isinstance(u, dict):
            n = sum(int(u.get(k) or 0) for k in _MODEL_USAGE_KEYS)
            if n:
                per_model[str(name)] = n
    if per_model:
        return sum(per_model.values()), per_model
    u = doc.get("usage")
    if isinstance(u, dict):
        n = sum(int(u.get(k) or 0) for k in _USAGE_KEYS)
        return (n, {}) if n else (None, {})
    return None, {}


def record_run(review: Path, cost, seconds: float, ledger: str = RUNS_LEDGER,
               model: str | None = None, out: str | None = None) -> None:
    """Append what this run cost, so the button can stop guessing what the next one will.

    Appended even when the cost could not be read, with `cost: null` — the *number* of runs
    is itself the answer to "has anybody ever pressed this", and a ledger that only records
    the runs it could price would quietly claim a page had never been rerun.

    Bounded, and failures are swallowed whole. This is bookkeeping running after the money
    has already been spent; an unwritable directory is not a reason to report a successful
    run as a failed one.

    `ledger` is the file it goes in: the matrix's by default, `rerun-film.py` passes its
    own — the two buttons buy different amounts of work, and an average over both would be
    the right price for neither.

    `out` is the CLI's own JSON reply: its token counts go in beside the cost (`tokens`,
    and `models` as `{model id: tokens}`), so the cost tab's row is not `$0.16 · 0`.
    """
    path = review / ledger
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        runs = doc.get("runs") if isinstance(doc, dict) else doc
        if not isinstance(runs, list):
            runs = []
    except Exception:
        runs = []
    run = {"when": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "model": model or MODEL, "cost": cost, "seconds": round(seconds, 1)}
    tokens, per_model = _usage(out) if out else (None, {})
    if tokens is not None:
        run["tokens"] = tokens
        if per_model:
            run["models"] = per_model
    runs.append(run)
    try:
        path.write_text(json.dumps({"version": 1, "runs": runs[-RUNS_KEPT:]}, indent=2)
                        + "\n", encoding="utf-8")
    except OSError:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".human-review", help="the review directory")
    ap.add_argument("--model", help="the model that judges the pairing "
                                    f"(default: {MAPPING_MODEL_KEY} in human-review.json, "
                                    f"else {MAPPING_MODEL_DEFAULT})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the command and what is open, spend nothing")
    ap.add_argument("--prompt-only", action="store_true",
                    help="print the whole prompt for another harness to answer, spend nothing")
    ap.add_argument("--answer", help="validate and install an answer made elsewhere")
    ap.add_argument("--no-check", dest="check", action="store_false", default=None,
                    help="skip the second, downgrade-only read (default: "
                         f"{MAPPING_CHECK_KEY} in human-review.json, else on)")
    ap.add_argument("--check-prompt", action="store_true",
                    help="print the second read's prompt for the installed answer, spend nothing")
    ap.add_argument("--check-answer",
                    help="apply a second read made elsewhere to the installed answer")
    args = ap.parse_args(argv)

    review = Path(args.dir)
    if not review.is_dir() or not (review / LOOKS_LIKE_A_REVIEW).is_file():
        print(f"[model] {review}/ is not a review directory — no "
              f"{LOOKS_LIKE_A_REVIEW} in it, so there is no report to regenerate. "
              "Run /human-review from the repository root first.", file=sys.stderr)
        return 2
    if not PROMPT.is_file():
        print(f"[model] {PROMPT} is missing — that file *is* the step.", file=sys.stderr)
        return 2

    root = Path.cwd().resolve()
    sc = _semcov()
    try:
        spec = json.loads((review / LOOKS_LIKE_A_REVIEW).read_text(encoding="utf-8"))
    except ValueError:
        spec = {}
    g = sc.gather(spec if isinstance(spec, dict) else {}, review, root)
    if g is None:
        print("[model] no requirement text resolved for this branch — no GitHub issue "
              "(review-points.md `ticket:`, pr.ticket in content.json, #N in the PR title, "
              "the branch name), no `ticket:` text, no matching openspec/changes/<name>/, "
              "no impl-conversation.md request 0 — so there are no sentences to pair.",
              file=sys.stderr)
        return 2
    asked = sc.model_input(g["ticket"], g["sentences"], g["rows"], g["scripted"], g["docs"],
                           g["decisions"])
    offered = [t["id"] for t in asked["tests"]]
    digests = sc.offered_digests(asked["tests"])
    decided = len(g["scripted"]["decided"])
    links = sum(len(e["tests"]) for e in g["scripted"]["decided"])
    print(f"[model] {len(g['sentences'])} sentences, {len(g['rows'])} tests: the script "
          f"paired {decided} ({links} candidate links, each to confirm or reject), "
          f"{len(g['scripted']['open'])} open; {len(asked['sentences'])} sentences to ask "
          f"about, {len(asked['decisions'])} recorded decisions.")

    if args.check_prompt or args.check_answer:
        # The second read, for a harness that is not Claude Code: its prompt over the
        # answer installed, and its reply applied to it — downgrade-only, as in a full run.
        current = sc.load_model_mapping(review)
        if current is None:
            print(f"[model] no valid {WRITES[0]} to check — install an answer first "
                  "(--answer).", file=sys.stderr)
            return 2
        if args.check_prompt:
            print(build_check_prompt(sc.check_input(current, asked)))
            return 0
        doc, said = checked(sc, current, parse_answer(
            Path(args.check_answer).read_text(encoding="utf-8")), asked)
        keep_previous(review)
        install(review, _noted(doc, said))
        print(f"[model] {args.check_answer} applied: {said or 'nothing lowered'}.")
        return 0

    if args.answer:
        doc, bad, dropped = judged(parse_answer(Path(args.answer).read_text(encoding="utf-8")),
                                   asked)
        if doc is None:
            print(f"[model] {args.answer} is refused:", file=sys.stderr)
            for b in bad:
                print(f"  - {b}", file=sys.stderr)
            return 5
        if dropped:
            print(f"[model] {len(dropped)} sentence(s) of {args.answer} dropped — they stay "
                  f"unconfirmed: {', '.join(dropped)}", file=sys.stderr)
            for b in bad:
                print(f"  - {b}", file=sys.stderr)
            doc = {**doc, "note": f"{len(dropped)} sentence(s) dropped for failing the "
                                  f"checks: {', '.join(dropped)}"}
        doc, said = downgrade(sc, doc, g)
        keep_previous(review)
        print(f"[model] {install(review, _noted(doc, said), offered, digests)} written from {args.answer}"
              + (f" — {said}" if said else "") + ". Its second read: --check-prompt, then "
              "--check-answer.")
        return 0

    prompt = build_prompt(asked)
    if args.prompt_only:
        print(prompt)
        return 0

    # Only a ticket with no claim in it at all is answered without a model. A sentence the
    # script paired is *not* settled: its links were made on shared words, and run 5 painted
    # "sortable by any column" green over a test that checks the page size because nothing
    # ever asked a model to read it. Every scripted link goes to the model, in this one call.
    if not asked["sentences"]:
        if args.dry_run:
            print("[model] dry run — no sentence makes a claim, so nothing would be asked.")
            return 0
        keep_previous(review)
        install(review, {"schema": sc.SCHEMA_VERSION,
                         "note": "no sentence of the ticket makes a claim; no model was asked",
                         "sentences": []}, offered, digests)
        print("[model] no sentence makes a claim — no model run, nothing spent.")
        return 0

    model = mapping_model(args.model)
    argvec = mapping_argv(model)
    check = mapping_check(args.check, model=model)
    # Printed with the prompt named rather than quoted, always: a log line carrying all of
    # it is a log line nobody reads — including a reader checking what the button buys.
    print("[model] $ " + " ".join(a if a else '""' for a in argvec)
          + f"  < {PROMPT.name} + {len(asked['sentences'])} sentences, "
          f"{len(asked['tests'])} candidate tests ({len(prompt)} chars)")
    print("[model] then " + (f"$ {' '.join(a if a else chr(34) * 2 for a in argvec)}  < "
                             f"{CHECK_PROMPT.name} + the links it kept — a second read that "
                             "can only lower them" if check else
                             f"no second read ({MAPPING_CHECK_KEY} is off)"))
    if args.dry_run:
        print(f"[model] dry run — nothing was asked of {model} and nothing was paid for.")
        return 0

    if not shutil.which("claude"):
        print("[model] no `claude` on PATH. Answer the prompt in another harness instead: "
              "--prompt-only, then --answer.", file=sys.stderr)
        return 2

    kept = keep_previous(review)
    proc, cost, said, seconds = _ask(argvec, prompt, root)
    outs, spent = [proc.stdout], [seconds]

    def billed():
        """The press's reply for the ledger: the one call's own, or all of them added."""
        return outs[0] if len(outs) == 1 else _combined(outs)

    def ledger():
        # One row per press, however many calls it took — written once the last call is
        # back, so the second read's price is on it, and on every way out, refusals too.
        record_run(review, _priced(billed())[0], sum(spent), model=model, out=billed())

    if proc.returncode != 0:
        ledger()
        print(f"[model] {model} exited {proc.returncode}; {WRITES[0]} is left as it was.",
              file=sys.stderr)
        return 1
    doc = parse_answer(said or proc.stdout)
    good, bad, dropped = judged(doc, asked)
    if good is None:
        ledger()
        where = keep_refused(review, said or proc.stdout)
        print(f"[model] {model}'s answer is refused, and {WRITES[0]} is left as it was "
              f"(the previous one is also in {kept}/"
              + (f"; the reply is in {where}" if where else "") + "):", file=sys.stderr)
        for b in bad[:20]:
            print(f"  - {b}", file=sys.stderr)
        if len(bad) > 20:
            print(f"  - … and {len(bad) - 20} more", file=sys.stderr)
        return 5
    if dropped:
        keep_refused(review, said or proc.stdout)
        print(f"[model] {len(dropped)} of {model}'s sentences are dropped — they stay "
              f"unconfirmed on the page: {', '.join(dropped)}", file=sys.stderr)
        for b in bad[:20]:
            print(f"  - {b}", file=sys.stderr)
        good = {**good, "note": f"{len(dropped)} sentence(s) dropped for failing the "
                                f"checks: {', '.join(dropped)}"}
    first = {e["id"]: e["coverage"] for e in good["sentences"]}
    verdicts = [v for e in good["sentences"] for v in e.get("review") or []]
    rejected = sum(1 for v in verdicts if v["verdict"] == "reject")
    doc, said_script = downgrade(sc, good, g)
    said_check = ""
    if check:
        chk_input = sc.check_input(doc, asked)
        if chk_input["sentences"]:
            cproc, _, csaid, csec = _ask(argvec, build_check_prompt(chk_input), root)
            outs.append(cproc.stdout)
            spent.append(csec)
            if cproc.returncode != 0:
                said_check = f"the second read failed ({model} exited {cproc.returncode}) — " \
                             "nothing lowered"
            else:
                doc, said_check = checked(sc, doc, parse_answer(csaid or cproc.stdout), asked)
    ledger()
    doc = _noted(doc, said_script, said_check)
    install(review, doc, offered, digests)
    total = _priced(billed())[0]
    price = f"${total:.4f}" if isinstance(total, (int, float)) else "an unpriced run"

    def counts(by_sid: dict) -> str:
        tally: dict = {}
        for c in by_sid.values():
            tally[c] = tally.get(c, 0) + 1
        return ", ".join(f"{n} {c}" for c, n in sorted(tally.items()))

    print(f"[model] {model} answered {len(doc['sentences'])} of {len(asked['sentences'])} "
          f"sentences, confirmed {len(verdicts) - rejected} and rejected {rejected} scripted "
          f"links, for {price} ({len(outs)} call{'s' if len(outs) != 1 else ''}); "
          f"{WRITES[0]} written.")
    print(f"[model] coverage as answered: {counts(first)}; after the downgrade-only "
          f"passes: {counts({e['id']: e['coverage'] for e in doc['sentences']})}"
          + "".join(f"; {x}" for x in (said_script, said_check) if x) + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
