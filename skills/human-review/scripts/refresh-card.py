#!/usr/bin/env python3
"""Redraw one draw.io card and put it back into the finished page, in place.

What the card's green ring runs (`diagrams.card_rerun_html`, served by `serve-review.py`):

    refresh-card.py --dir .human-review --name conceptual

The reader has just moved a box in draw.io and wants to see it on the page. The tab's own
ring answers that by re-deriving the whole tab — on the Data tab every PlantUML delta as
well, thirty seconds of renders nothing changed — and then rebuilding the whole page,
another ten. Forty seconds for one dragged box, and the reload lands them at the top of
the card they were looking at. This does the part of that which can have changed:

1. **the one `drawio-diff.py`** the card was drawn by, exactly as it ran last time — the
   command its verdict recorded (`<name>-diff.json`, `rerun`). In-process when it is the
   one beside us, so the interpreter starts once. Its exports come out of draw.io's
   render cache when the same XML was drawn before (the base side always is);
2. **the card**, rendered by the same functions the build renders it with and passed
   through the same per-card rewrites the build gives it afterwards — the prompt pill and
   the (i), the short file name, the page-wide link and tooltip rewrites — so the markup is
   the markup a full build writes (`test_refresh_card.py` holds the two to equality);
3. **the splice**: the card's old markup in `review.html` is replaced by the new, read and
   written back in one go (the file is re-read right before the write and replaced
   atomically, so nothing written to the page meanwhile is lost); the manifest entries the
   card declares are merged into `.actions.json` the same way. The new card is also left at
   `.card-<name>.html`, where the server picks it up for the page to swap in without a
   reload.

When the edit changes something outside the card — the drawing became identical to the
base, or stopped being, which strikes the tab through or un-strikes it — or the card cannot
be found on the page, it rebuilds the whole page instead, with the command the page was
built by. Slower, never wrong.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hrbuild.shared.actions import ACTIONS, ACTIONS_FILE  # noqa: E402
from hrbuild.shared.adopt import _close, place_prompts  # noqa: E402
from hrbuild.shared.diagrams import (CARD_NAME, card_rerun_id,  # noqa: E402
                                     drawio_unchanged, drawio_widget_html, shorten_dgm_src)
from hrbuild.shared.panels import restamp_page  # noqa: E402
from hrbuild.shared.postprocess import one_tooltip_only, open_links_in_new_tabs  # noqa: E402

DRAWIO_DIFF = HERE / "drawio-diff.py"
BUILD = HERE / "build-review-html.py"
PANEL = re.compile(r'<section class="panel" id="([^"]+)"')


def card_file(review: Path, name: str) -> Path:
    """Where the new card is left for the server to hand to the page."""
    return review / f".card-{name}.html"


def locate(page: str, name: str) -> tuple[int, int, str] | None:
    """`(start, end, tab)` of the card named `name` in a finished page, or None.

    Found by the `data-drawio` it carries on its opening tag, bounded by that tag's own
    closing one (`adopt._close`, which steps over scripts, styles and the `<div>`s inside
    the SVG's foreignObjects), and placed in the tab whose panel it sits in."""
    marker = f'data-drawio="{name}"'
    at = page.find(marker)
    if at < 0 or page.find(marker, at + 1) >= 0:
        return None
    start = page.rfind("<div", 0, at)
    if start < 0 or page.find(">", start) < at:
        return None
    span = _close(page, start)
    panels = list(PANEL.finditer(page, 0, start))
    if not span or not panels:
        return None
    return start, span[1], panels[-1].group(1)


def card_html(name: str, assets: Path, root: Path, rebuild: str, tab: str) -> str:
    """The card as a full build leaves it on the page.

    The build draws it (`expand_drawio` → `drawio_widget_html`, `shorten_dgm_src`), then
    gives every card on its tab its prompt pill and (i) (`place_prompts`, which works card
    by card), then rewrites the finished document's links and tooltips. Nothing else the
    build does reaches inside a draw.io card: `place_tab_reruns` leaves a card that carries
    its own ring alone, and the two document passes not repeated here (`cross_link`,
    `promote_traced`) read quoted code and the requirements map, neither of which a card
    holds — `test_refresh_card.py` builds the page both ways and compares them."""
    card = shorten_dgm_src(drawio_widget_html(name, assets, root, rebuild))
    card = place_prompts(tab, card)
    return one_tooltip_only(open_links_in_new_tabs(card))


def rebuild_line(review: Path, name: str) -> str:
    """How the page was built, as its own manifest says: the last stage of the card's Revert.

    Only the card that offers a Revert prints it, and that card's manifest entry carries it
    — so read it there rather than re-derive the interpreter probe a build makes. Otherwise
    the line a `refresh-report.py` build is started with."""
    try:
        cmd = json.loads((review / ACTIONS_FILE).read_text("utf-8"))["actions"][
            f"drawio-redraw:{name}"]["command"]
        return cmd.rsplit(" \\\n  && ", 1)[1]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    spec = importlib.util.spec_from_file_location("hr_build_for_card", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return " ".join([mod.rebuild_interpreter(), shlex.quote(str(BUILD)),
                     shlex.quote(str(review / "content.json")), "--out",
                     shlex.quote(str(review / "review.html"))])


def run_differ(command: str) -> int:
    """Re-run the recorded `drawio-diff.py` line; in-process when it is ours."""
    argv = shlex.split(command)
    if argv and Path(argv[0]).resolve() == DRAWIO_DIFF.resolve():
        spec = importlib.util.spec_from_file_location("drawio_diff", DRAWIO_DIFF)
        mod = importlib.util.module_from_spec(spec)
        held = sys.argv
        sys.argv = [str(DRAWIO_DIFF), *argv[1:]]
        try:
            spec.loader.exec_module(mod)
            mod.main()
        except SystemExit as exc:
            code = exc.code
            if code not in (None, 0):
                if not isinstance(code, int):
                    print(code, file=sys.stderr)
                return 1
        finally:
            sys.argv = held
            sys.stdout.flush()
        return 0
    return subprocess.run(["/bin/sh", "-c", command]).returncode


def write_atomically(path: Path, text: str) -> None:
    part = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    part.write_text(text, encoding="utf-8")
    try:
        os.chmod(part, path.stat().st_mode & 0o777)
    except OSError:
        pass
    os.replace(part, path)


def splice(review: Path, name: str, card: str) -> bool:
    """Replace the card in `review.html` — re-read now, written back at once."""
    page_path = review / "review.html"
    page = page_path.read_text(encoding="utf-8")
    where = locate(page, name)
    if where is None:
        return False
    start, end, _ = where
    if page[start:end] != card:
        write_atomically(page_path, page[:start] + card + page[end:])
    return True


def merge_actions(review: Path, name: str, declared: dict) -> None:
    """The card's entries in the manifest, as the build would have left them: what it just
    declared, and none of what it declared last time and no longer does."""
    path = review / ACTIONS_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {"version": 1, "actions": {}}
    acts = doc.setdefault("actions", {})
    before = json.dumps(acts, sort_keys=True)
    for key in (f"drawio-redraw:{name}", card_rerun_id(name)):
        acts.pop(key, None)
    acts.update(declared)
    if json.dumps(acts, sort_keys=True) != before:
        write_atomically(path, json.dumps(doc, indent=2) + "\n")


def full_rebuild(rebuild: str, why: str) -> int:
    print(f"[card] {why} — rebuilding the whole page", flush=True)
    return subprocess.run(["/bin/sh", "-c", rebuild]).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".human-review", help="the review directory")
    ap.add_argument("--name", required=True, help="the card: the `drawio-diff.py --name`")
    args = ap.parse_args(argv)
    if not CARD_NAME.match(args.name):
        ap.error(f"not a card name: {args.name!r}")
    review, name = Path(args.dir), args.name
    assets = review / "assets"
    clock = [("start", time.monotonic())]

    def lap(what):
        clock.append((what, time.monotonic()))

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                               text=True, check=True).stdout.strip())
    vfile = assets / f"{name}-diff.json"
    try:
        old = json.loads(vfile.read_text(encoding="utf-8"))
        command = old["rerun"]["command"]
    except (OSError, ValueError, KeyError, TypeError):
        print(f"[card] {vfile} records no command to redraw {name} with — run the step "
              "that draws it (the tab's ring) once", file=sys.stderr)
        return 2
    card_file(review, name).unlink(missing_ok=True)
    rebuild = rebuild_line(review, name)
    lap("setup")

    print(f"[card] $ {Path(shlex.split(command)[0]).name} … --name {name}", flush=True)
    if run_differ(command) != 0:
        print(f"[card] drawio-diff.py failed — the card on the page is the previous one",
              file=sys.stderr)
        return 1
    lap("drawio-diff")
    new = json.loads(vfile.read_text(encoding="utf-8"))
    if drawio_unchanged(old) != drawio_unchanged(new):
        return full_rebuild(rebuild, "the drawing " + (
            "is now the base's again" if drawio_unchanged(new) else "differs from the base now")
            + ", which strikes the tab through or un-strikes it")

    page = (review / "review.html").read_text(encoding="utf-8")
    where = locate(page, name)
    if where is None:
        return full_rebuild(rebuild, f"no card named {name} on the page")
    ACTIONS.clear()
    card = card_html(name, assets, root, rebuild, where[2])
    if (not card.startswith("<div ") or f'data-drawio="{name}"' not in card
            or '<figure class="snippet"' in card or 'class="rm-data"' in card):
        return full_rebuild(rebuild, "the card did not render as a card")
    lap("render")
    if not splice(review, name, card):
        return full_rebuild(rebuild, f"the card named {name} left the page")
    merge_actions(review, name, dict(ACTIONS))
    # The panel the card sits in changed: its hash on the page and its piece beside it
    # follow, so another open copy of the page swaps that tab in rather than keep the old
    # card (`shared/panels.py`).
    restamp_page(review)
    write_atomically(card_file(review, name), card)
    lap("splice")
    steps = " · ".join(f"{what} {b - a:.2f}s"
                       for (_, a), (what, b) in zip(clock, clock[1:]))
    print(f"[card] {name} redrawn in place ({steps})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
