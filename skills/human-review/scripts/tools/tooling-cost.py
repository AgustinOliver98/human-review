#!/usr/bin/env python3
"""What building human-review itself has cost, in Claude API list-price dollars.

A one-off measurement, re-run by hand. Nothing in the build calls this: the figure it
printed on 20 Oct 2026 is hardcoded in `hrbuild/tabs/cost.py` (`TOOLING_INVESTMENT`) as a
dated baseline, because a number that silently moves every build would read as "this PR".

How it measures
---------------
* Every `~/.claude/projects/*/**/*.jsonl` is streamed line by line (7+ GB; nothing is
  loaded whole). Read-only.
* **Dedupe by `message.id`**, globally: a streamed message is written once per content
  block, with `usage` growing row over row, so the row with the most `output_tokens` is
  kept; a resumed or forked session copies earlier messages into a new file, so each id is
  owned by the file that started earliest.
* **Priced per message, per model**, at the list prices in `PRICES` (verified against
  https://platform.claude.com/docs/en/about-claude/pricing on 8 Oct 2026, re-read
  unchanged on 20 Oct 2026): input, output, 5m cache writes at 1.25x input, 1h writes
  at 2x, cache reads at the model's own rate (0.1x, 0.05x on Opus/Sonnet 5.5, 0.025x on
  Fable/Mythos 5.1), web search $10/1k, fast mode and `inference_geo: us` multipliers
  where the usage says so.
* **Which sessions are human-review** is decided per session tree (the main transcript
  plus its `subagents/agent-*.jsonl`), from tool calls, never prose — CLAUDE.md/AGENTS.md
  mention human-review in every workspace session:
    - a session whose project dir is the human-review repo (or one of its worktrees) is in;
    - elsewhere, the share of tool calls whose input names a human-review path
      (`HR_PATTERN`) decides: >= `--mostly` (0.5) is in, >= `--borderline` (0.2) is
      borderline and reported apart, below is out;
    - `claude -p` sessions (entrypoint `sdk-cli`) on an eval checkout are "eval runs";
    - petclinic sessions before the move (`--move`, the commit that took the skill to its
      own repo) are the "petclinic era".

Time, beside the money (8 Oct 2026), for every session counted in:
* **your time** — `harness_cost.claude_human_time` over the whole session: the dictations
  Wispr Flow logged, the words it did not (spoken or typed), reading the replies;
* **agent time** — `harness_cost.claude_busy_spans`, main thread and subagents: each
  prompt to its turn's last record. `agent_seconds` adds the sessions up (parallel ones
  count twice); `wall_seconds` is their union, the hours something was being built.

Usage:  tooling-cost.py [--out DIR] [--until 2026-10-08]
Writes  sessions.csv (one row per session tree), summary.json, and prints the summary.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

PROJECTS = Path(os.path.expanduser("~/.claude/projects"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import harness_cost as hc  # noqa: E402
PRICE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing (read 2026-10-20)"

# $ per MTok: (input, output, cache read). Writes are 1.25x / 2x input for 5m / 1h.
# Most specific id first: `price_key` takes the first prefix the model id starts with.
PRICES = [
    ("claude-fable-5-1", (10.0, 50.0, 0.25)),
    ("claude-mythos-5-1", (10.0, 50.0, 0.25)),
    ("claude-fable-5", (10.0, 50.0, 1.00)),
    ("claude-mythos-5", (10.0, 50.0, 1.00)),
    ("claude-opus-5-5", (4.0, 20.0, 0.20)),
    ("claude-opus-5", (5.0, 25.0, 0.50)),
    ("claude-opus-4-8", (5.0, 25.0, 0.50)),
    ("claude-opus-4-7", (5.0, 25.0, 0.50)),
    ("claude-opus-4-6", (5.0, 25.0, 0.50)),
    ("claude-opus-4-5", (5.0, 25.0, 0.50)),
    ("claude-opus-4-1", (15.0, 75.0, 1.50)),
    ("claude-opus-4", (15.0, 75.0, 1.50)),
    ("claude-sonnet-5-5", (2.0, 10.0, 0.10)),
    ("claude-sonnet-5", (2.0, 10.0, 0.20)),
    ("claude-sonnet-4-6", (3.0, 15.0, 0.30)),
    ("claude-sonnet-4-5", (3.0, 15.0, 0.30)),
    ("claude-sonnet-4", (3.0, 15.0, 0.30)),
    ("claude-haiku-5-5", None),            # priced by prompt length, see `haiku55`
    ("claude-haiku-4-5", (1.0, 5.0, 0.10)),
    ("claude-3-5-haiku", (0.8, 4.0, 0.08)),
]
FAST = {"claude-opus-5-5": (8.0, 40.0), "claude-opus-5": (10.0, 50.0),
        "claude-opus-4-8": (10.0, 50.0)}
WEB_SEARCH_PER_1K = 10.0

HR_PATTERN = re.compile(
    r"human-review|hrbuild|build-review-html|refresh-report|review\.html|review-cost"
    r"|review-points|harness_cost|human_review")
HR_DIR = re.compile(r"-workspace-human-review(?:$|-)")
EVAL_DIR = re.compile(r"-petclinic-(?:eval|pr|pr-owner-grid-paginated|pr-visit-has-vet)$")
PETCLINIC_DIR = re.compile(r"-workspace-petclinic|petclinic")


def price_key(model: str) -> str | None:
    m = (model or "").lower()
    for key, _ in PRICES:
        if m == key or m.startswith(key + "-") or m.startswith(key + "[") or m.startswith(key + "@"):
            # `claude-opus-4` must not swallow `claude-opus-4-5`: the longer keys come
            # first, so reaching here means none of them matched.
            return key
    return None


def cost_of(model: str, u: dict) -> float:
    key = price_key(model)
    if key is None:
        return 0.0
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens") or 0
    w1 = cc.get("ephemeral_1h_input_tokens") or 0
    if not (w5 or w1):
        w5 = u.get("cache_creation_input_tokens") or 0
    inp_t = u.get("input_tokens") or 0
    out_t = u.get("output_tokens") or 0
    read_t = u.get("cache_read_input_tokens") or 0
    table = dict(PRICES)[key]
    if table is None:                       # Haiku 5.5: two tiers by prompt length
        prompt = inp_t + w5 + w1 + read_t
        table = (0.10, 0.50, 0.01) if prompt <= 100_000 else (0.50, 2.50, 0.05)
    inp, out, read = table
    if (u.get("speed") == "fast") and key in FAST:
        f_in, f_out = FAST[key]
        read *= f_in / inp
        inp, out = f_in, f_out
    usd = (inp_t * inp + out_t * out + w5 * inp * 1.25 + w1 * inp * 2.0
           + read_t * read) / 1e6
    if u.get("inference_geo") == "us":
        usd *= 1.1
    stu = u.get("server_tool_use") or {}
    usd += (stu.get("web_search_requests") or 0) * WEB_SEARCH_PER_1K / 1000
    return usd


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class FileStat:
    __slots__ = ("path", "project", "session", "agent", "entry", "cwd", "branch", "first",
                 "last", "tools", "hr_tools", "prompts", "hr_prompts", "sidechain_msgs",
                 "seg", "segs")

    def __init__(self, path: Path):
        self.path = path
        rel = path.relative_to(PROJECTS).parts
        self.project = rel[0]
        if len(rel) >= 3 and "subagents" in rel:
            self.session = rel[1]
            self.agent = path.stem
        else:
            self.session = path.stem
            self.agent = None
        self.entry = None
        self.cwd = None
        self.branch = None
        self.first = None
        self.last = None
        self.tools = self.hr_tools = self.prompts = self.hr_prompts = 0
        self.sidechain_msgs = 0
        # A segment is one typed prompt and every turn it caused: [tools, hr_tools, hr_prompt]
        self.seg = 0
        self.segs = [[0, 0, False]]

    def hr_segment(self, seg: int) -> bool:
        tools, hr, prompt = self.segs[seg]
        return hr >= 0.5 * tools if tools else prompt


def scan(path: Path, msgs: dict) -> FileStat:
    st = FileStat(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"type":"assistant"' in line or '"type": "assistant"' in line:
                kind = "assistant"
            elif '"type":"user"' in line or '"type": "user"' in line:
                # Tool results are the bulk of the bytes and carry nothing we need.
                if '"tool_use_id"' in line:
                    continue
                kind = "user"
            else:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != kind:
                continue
            ts = parse_ts(d.get("timestamp"))
            if ts:
                st.first = ts if st.first is None or ts < st.first else st.first
                st.last = ts if st.last is None or ts > st.last else st.last
            st.entry = st.entry or d.get("entrypoint")
            st.cwd = st.cwd or d.get("cwd")
            st.branch = st.branch or d.get("gitBranch")
            msg = d.get("message") or {}
            if kind == "user":
                if d.get("isMeta"):
                    continue
                c = msg.get("content")
                text = c if isinstance(c, str) else " ".join(
                    b.get("text", "") for b in (c or []) if isinstance(b, dict))
                if not text.strip() or text.lstrip().startswith("<"):
                    continue          # command echoes, reminders, notifications
                st.prompts += 1
                hit = bool(HR_PATTERN.search(text))
                st.hr_prompts += hit
                st.seg += 1
                st.segs.append([0, 0, hit])
                continue
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    st.tools += 1
                    st.segs[st.seg][0] += 1
                    if HR_PATTERN.search(json.dumps(b.get("input"), ensure_ascii=False)):
                        st.hr_tools += 1
                        st.segs[st.seg][1] += 1
            u = msg.get("usage")
            if not u:
                continue
            mid = msg.get("id") or d.get("uuid")
            if d.get("isSidechain"):
                st.sidechain_msgs += 1
            out = u.get("output_tokens") or 0
            prev = msgs.get(mid)
            if prev is None:
                msgs[mid] = [msg.get("model") or "", u, out, {id(st): (st, st.seg)},
                             bool(d.get("isSidechain"))]
            else:
                prev[3].setdefault(id(st), (st, st.seg))
                if out >= prev[2]:
                    prev[0], prev[1], prev[2] = msg.get("model") or prev[0], u, out
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=".", help="directory for sessions.csv and summary.json")
    ap.add_argument("--move", default="2026-08-22T00:48:11+03:00",
                    help="when the skill left petclinic for its own repo")
    ap.add_argument("--mostly", type=float, default=0.5)
    ap.add_argument("--borderline", type=float, default=0.2)
    ap.add_argument("--until", default=None, help="ignore messages after this ISO date")
    a = ap.parse_args()
    move = dt.datetime.fromisoformat(a.move)
    until = dt.datetime.fromisoformat(a.until).replace(tzinfo=dt.timezone.utc) if a.until else None

    msgs: dict = {}
    stats: list[FileStat] = []
    files = sorted(PROJECTS.glob("*/**/*.jsonl"))
    seen = set()
    for i, f in enumerate(files):
        rf = f.resolve()
        if rf in seen or f.is_symlink() or not f.is_file():
            continue
        seen.add(rf)
        stats.append(scan(f, msgs))
        if i % 500 == 0:
            print(f"  {i}/{len(files)} files", file=sys.stderr)

    far = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    per_file_cost: dict[int, dict] = defaultdict(lambda: defaultdict(float))
    per_file_tokens: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    per_file_hrseg: dict[int, float] = defaultdict(float)   # $ in prompts that were HR work
    per_file_unknown: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    for mid, (model, u, _out, holders, side) in msgs.items():
        owner, seg = min(holders.values(), key=lambda h: (h[0].first or far, str(h[0].path)))
        if until and owner.first and owner.first > until:
            continue
        if model == "<synthetic>":
            continue
        key = id(owner)
        if price_key(model) is None:
            per_file_unknown[key][model] += 1
        c = cost_of(model, u)
        bucket = "side" if side and owner.agent is None else "own"
        per_file_cost[key][(model, bucket)] += c
        if owner.hr_segment(seg):
            per_file_hrseg[key] += c
        t = per_file_tokens[key]
        cc = u.get("cache_creation") or {}
        w1 = cc.get("ephemeral_1h_input_tokens") or 0
        w5 = cc.get("ephemeral_5m_input_tokens") or 0
        if not (w1 or w5):
            w5 = u.get("cache_creation_input_tokens") or 0
        t["in"] += u.get("input_tokens") or 0
        t["out"] += u.get("output_tokens") or 0
        t["w5"] += w5
        t["w1"] += w1
        t["read"] += u.get("cache_read_input_tokens") or 0
        t["msgs"] += 1

    # Session trees: main transcript + subagent files, keyed by (project, session).
    trees: dict = defaultdict(list)
    for s in stats:
        trees[(s.project, s.session)].append(s)

    rows = []
    for (project, session), members in trees.items():
        main_ = next((m for m in members if m.agent is None), None)
        tools = sum(m.tools for m in members)
        hr_tools = sum(m.hr_tools for m in members)
        prompts = sum(m.prompts for m in members if m.agent is None)
        hr_prompts = sum(m.hr_prompts for m in members if m.agent is None)
        main_usd = sub_usd = hrseg_usd = 0.0
        models = defaultdict(float)
        unknown = defaultdict(int)
        tok = defaultdict(int)
        for m in members:
            for (model, bucket), c in per_file_cost.get(id(m), {}).items():
                models[model] += c
                if m.agent is None and bucket == "own":
                    main_usd += c
                else:
                    sub_usd += c
            for k, v in per_file_tokens.get(id(m), {}).items():
                tok[k] += v
            for k, v in per_file_unknown.get(id(m), {}).items():
                unknown[k] += v
            hrseg_usd += per_file_hrseg.get(id(m), 0.0)
        total = main_usd + sub_usd
        if total == 0 and tools == 0:
            continue
        firsts = [m.first for m in members if m.first]
        lasts = [m.last for m in members if m.last]
        first = min(firsts) if firsts else None
        last = max(lasts) if lasts else None
        # A session that called no tool did no work on the repo: a prompt that merely
        # quotes a review page (the voice corpus labeller pastes whole dictations) is not.
        share = hr_tools / tools if tools else 0.0
        head = main_ or members[0]
        entry, cwd, branch = head.entry or "", head.cwd or "", head.branch or ""
        in_repo = bool(HR_DIR.search(project))
        eval_run = entry.startswith("sdk") and (bool(EVAL_DIR.search(project))
                                                or "hr-claude" in branch)
        if in_repo or (eval_run and hr_tools):
            # The repo's own sessions are all tool work; an eval run exists to end in a
            # review, so the feature it implements first is the eval's fixture, not noise.
            verdict = "in"
        elif share >= a.mostly:
            verdict = "in"
        elif share >= a.borderline:
            verdict = "borderline"
        else:
            verdict = "out"
        if eval_run:
            bucket = "eval runs"
        elif first and first < move:
            bucket = "petclinic era"
        elif in_repo:
            bucket = "human-review repo"
        elif project == "-Users-victorrentea-workspace":
            bucket = "workspace sessions"
        elif PETCLINIC_DIR.search(project):
            bucket = "petclinic checkouts (after move)"
        else:
            bucket = "other project dirs"
        rows.append(dict(
            session=session, project=project, bucket=bucket, verdict=verdict,
            entrypoint=entry, branch=branch, cwd=cwd,
            first=first.isoformat() if first else "", last=last.isoformat() if last else "",
            subagent_files=sum(1 for m in members if m.agent), tools=tools, hr_tools=hr_tools,
            hr_share=round(share, 3), prompts=prompts, hr_prompts=hr_prompts,
            usd_main=round(main_usd, 4), usd_subagents=round(sub_usd, 4), usd=round(total, 4),
            usd_hr_segments=round(total if in_repo or eval_run else hrseg_usd if tools else 0.0, 4),
            msgs=tok["msgs"], input=tok["in"], output=tok["out"], cache_write_5m=tok["w5"],
            cache_write_1h=tok["w1"], cache_read=tok["read"],
            models=";".join(f"{k}={v:.4f}" for k, v in sorted(models.items(), key=lambda kv: -kv[1])),
            unknown_models=";".join(f"{k}={v}" for k, v in unknown.items()),
        ))

    # Time, only for the sessions the money counts: reading a transcript whole is slow.
    all_spans: list[tuple] = []
    for r in rows:
        r["human_seconds"] = r["agent_seconds"] = 0
        main_file = PROJECTS / r["project"] / f"{r['session']}.jsonl"
        if r["verdict"] != "in" or not r["first"] or not main_file.is_file():
            continue
        lo = dt.datetime.fromisoformat(r["first"])
        hi = min(dt.datetime.fromisoformat(r["last"]), until or far)
        spans = hc.claude_busy_spans(main_file, lo, hi)
        for agent in sorted((PROJECTS / r["project"] / r["session"] / "subagents")
                            .glob("agent-*.jsonl")):
            spans += hc.claude_busy_spans(agent, lo, hi)
        all_spans += spans
        r["agent_seconds"] = round(sum((b - a).total_seconds() for a, b in spans))
        r["human_seconds"] = round(hc.claude_human_time(main_file, lo, hi)["seconds"])

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: r["first"])
    with open(out / "sessions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def agg(sel):
        s = dict(sessions=0, usd=0.0, usd_main=0.0, usd_subagents=0.0, subagent_files=0)
        for r in sel:
            s["sessions"] += 1
            s["subagent_files"] += r["subagent_files"]
            for k in ("usd", "usd_main", "usd_subagents"):
                s[k] += r[k]
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in s.items()}

    def by_model(sel):
        acc = defaultdict(float)
        for r in sel:
            for part in filter(None, r["models"].split(";")):
                k, v = part.rsplit("=", 1)
                acc[k] += float(v)
        return {k: round(v, 2) for k, v in sorted(acc.items(), key=lambda kv: -kv[1])}

    inc = [r for r in rows if r["verdict"] == "in"]
    border = [r for r in rows if r["verdict"] == "borderline"]
    buckets = {b: agg([r for r in inc if r["bucket"] == b])
               for b in sorted({r["bucket"] for r in inc})}
    # The five-way split the cost tab shows: each bucket's main threads, subagents apart.
    split = {b: v["usd_main"] for b, v in buckets.items()}
    split["subagents (all buckets)"] = round(sum(r["usd_subagents"] for r in inc), 2)
    unknown = defaultdict(int)
    for r in inc + border:
        for part in filter(None, r["unknown_models"].split(";")):
            k, v = part.rsplit("=", 1)
            unknown[k] += int(v)
    summary = dict(
        price_source=PRICE_SOURCE, move=a.move, rule=dict(mostly=a.mostly, borderline=a.borderline),
        total=agg(inc),
        split=split,
        buckets=buckets,
        by_model=by_model(inc),
        first=min(r["first"] for r in inc if r["first"]),
        last=max(r["last"] for r in inc if r["last"]),
        borderline=agg(border),
        borderline_prorated=round(sum(r["usd"] * r["hr_share"] for r in border), 2),
        borderline_buckets={b: agg([r for r in border if r["bucket"] == b])
                            for b in sorted({r["bucket"] for r in border})},
        segment_level_total=round(sum(r["usd_hr_segments"] for r in rows), 2),
        unknown_models_in_scope=dict(unknown),
        all_transcripts_usd=round(sum(r["usd"] for r in rows), 2),
        all_transcripts_first=min(r["first"] for r in rows if r["first"]),
        human_seconds=sum(r["human_seconds"] for r in inc),
        agent_seconds=sum(r["agent_seconds"] for r in inc),
        wall_seconds=round(hc._intervals_union(all_spans)),
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
