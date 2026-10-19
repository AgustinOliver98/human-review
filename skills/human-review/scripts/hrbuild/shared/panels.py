"""The page, also in pieces: one file per tab, for the served copy to swap in place.

`review.html` is one file and stays one file: it opens off disk, from the zip and on GitHub
Pages, and every one of those copies is read whole. The served copy is different in one
way: it is read *while* it is being rebuilt. Until now each rebuild reloaded the whole
page under the reader — a ↻ on the Sequence tab re-derived one tab and then threw away the
reader's place, their open folds and the half-typed note on every other one.

So the build also writes the page cut along its tabs, beside it:

  * ``tabs/<tab id>.html`` — that tab's ``<section class="panel">``, exactly as it sits in
    `review.html` (cut out of the *finished* document, after every rewrite has run over
    it, so a piece is byte for byte what a reload would show), with a first line naming
    the tab and its hash;
  * ``tabs/tabs.json`` — the manifest: the page it was cut from, the hash of everything
    that is not a tab (the *shell*: head, styles, scripts, masthead, footer), and per tab
    its hash, its pill on the strip, and whether it can be swapped at all.

Each section carries its own hash (``data-hr-hash``) and ``<html>`` the shell's
(``data-hr-shell``), so an open page knows what it is showing without asking. When the
server's watch stamp moves, `panels.js` compares: the shell or the list of tabs moved →
a full reload, as before; only some tabs moved → those tabs are fetched and swapped in
place. Nothing here is needed by any other copy of the page — off disk the two attributes
are inert.

A tab whose panel runs its own inline script cannot be swapped blind: re-running the
script would register its document-wide listeners twice, and not re-running it would
leave the new markup unwired. Such a script opts in by saying which of the two it is —
``data-hr-swap="keep"`` (it only delegates on `document`, the listener it registered at
load serves the new markup too) or ``data-hr-swap="rerun"`` (it wires what it finds and is
safe to run again over the new panel). A panel with any script that says neither is
marked ``swappable: false`` in the manifest, with the scripts that blocked it, and a change
to it reloads the page.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from hrbuild.shared.actions import ACTIONS, ACTIONS_FILE

#: Where the pieces go, beside the page.
PANELS_DIR = "tabs"
PANELS_MANIFEST = "tabs.json"
PANELS_VERSION = 1

# A panel's opening tag exactly as the orchestrator writes it (`build-review-html.py`, the
# `panels.append` lines): class, id, role, in that order. Anchored on all three so that a
# fragment quoting the page's own markup in prose cannot be mistaken for a panel.
_PANEL_OPEN = re.compile(r'<section class="panel" id="(?P<id>[^"]+)" role="tabpanel"')
_PANEL_STRIP = re.compile(r'<div class="tabstrip" role="tablist"[^>]*>')
_PANEL_PILL = re.compile(r'<button\b[^>]*\bid="tabbtn-(?P<id>[^"]+)"[^>]*>.*?</button>', re.S)
_PANEL_SCRIPT = re.compile(r'<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>', re.S | re.I)
_PANEL_DATA_TYPE = re.compile(r'\btype="(?:application|text)/(?:json|ld\+json|template|plain)"', re.I)
_PANEL_SWAP = re.compile(r'\bdata-hr-swap="(?P<how>keep|rerun)"')
# Files a panel shows by reference rather than inline: an <img>, a <video>, a poster. A
# rebuild that redraws one under the same name leaves the panel's markup unchanged, and a
# panel whose hash did not move is not swapped — so the file's own fingerprint is part of
# the hash.
_PANEL_LOCAL_REF = re.compile(
    r'\b(?:src|poster|data-src)="(?!https?:|data:|blob:|#|/|[a-z]+:)(?P<path>[^"?#]+)"', re.I)
_PANEL_HTML_OPEN = re.compile(r'<html\b')
# What `stamp_panels` puts on a page, so a page stamped once (and then edited in place —
# `refresh-card.py` splices one card into it) can be stamped again.
_PANEL_STAMPED = re.compile(r'(<section class="panel" id="[^"]+" role="tabpanel"[^>]*?) data-hr-hash="[0-9a-f]*"')
_PANEL_SHELL_STAMPED = re.compile(r'(<html) data-hr-shell="[0-9a-f]*"')


def _panel_hash(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=8)
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _panel_file_mark(out_dir: Path, rel: str) -> str:
    """What a referenced file is right now: its bytes' hash when small, else size+mtime
    (a 12MB screencast is not worth reading every build to learn it did not change)."""
    p = out_dir / rel
    try:
        st = p.stat()
    except OSError:
        return f"{rel}:missing"
    if not p.is_file():
        return f"{rel}:dir"
    if st.st_size <= 2_000_000:
        try:
            return f"{rel}:{hashlib.blake2b(p.read_bytes(), digest_size=8).hexdigest()}"
        except OSError:
            pass
    return f"{rel}:{st.st_size}:{st.st_mtime_ns}"


def panel_blockers(section: str) -> list[str]:
    """The inline scripts in a panel that have not said how to survive a swap — the first
    line of each, which is usually the comment saying what it is."""
    out = []
    for m in _PANEL_SCRIPT.finditer(section):
        attrs, body = m.group("attrs"), m.group("body")
        if _PANEL_DATA_TYPE.search(attrs) or _PANEL_SWAP.search(attrs):
            continue
        if re.search(r'\bsrc="', attrs):
            out.append(re.search(r'\bsrc="([^"]*)"', attrs).group(1))
            continue
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        out.append(first[:100])
    return out


def split_panels(doc: str) -> dict | None:
    """Where each tab's pill and panel sit in the finished document.

    `None` when the document is not a tabbed page, or when what was found does not add up
    (pills and panels disagree, an id twice, a panel that does not end where the next
    begins) — a page that cannot be cut cleanly is served the way it always was, whole."""
    strip = _PANEL_STRIP.search(doc)
    starts = list(_PANEL_OPEN.finditer(doc))
    if not strip or not starts:
        return None
    strip_end = doc.find("</div>", strip.end())
    pills = list(_PANEL_PILL.finditer(doc, strip.end(), strip_end))
    ids = [m.group("id") for m in starts]
    if [p.group("id") for p in pills] != ids or len(set(ids)) != len(ids):
        return None
    foot = doc.find("\n<footer>", starts[-1].end())
    if foot < 0:
        return None
    tabs = []
    for i, m in enumerate(starts):
        limit = starts[i + 1].start() if i + 1 < len(starts) else foot
        chunk = doc[m.start():limit].rstrip()
        if not chunk.endswith("</section>"):
            return None
        tabs.append({"id": m.group("id"), "start": m.start(), "end": m.start() + len(chunk),
                     "pill": (pills[i].start(), pills[i].end())})
    return {"tabs": tabs}


def stamp_panels(doc: str, out_dir: Path, page: str,
                 actions: dict | None = None) -> tuple[str, dict | None]:
    """The document with its hashes on it, and the manifest the pieces are written from.

    The shell's hash is taken over the document with every pill and every panel cut out,
    plus the action register (a control a new build declares is answered by the server's
    probe, which a page only reads once — so new actions mean a reload). `actions` is the
    register as `.actions.json` holds it; the build's own (`ACTIONS`) by default."""
    doc = _PANEL_SHELL_STAMPED.sub(r"\1", _PANEL_STAMPED.sub(r"\1", doc), count=1)
    cut = split_panels(doc)
    if cut is None:
        return doc, None
    out_dir = Path(out_dir)
    tabs, shell, pos = [], [], 0
    for t in cut["tabs"]:
        a, b = t["pill"]
        pill = doc[a:b]
        section = doc[t["start"]:t["end"]]
        refs = sorted(set(m.group("path") for m in _PANEL_LOCAL_REF.finditer(section)))
        h = _panel_hash(pill, section, *(_panel_file_mark(out_dir, r) for r in refs))
        tabs.append({"id": t["id"], "hash": h, "pill": pill, "section": section,
                     "blockers": panel_blockers(section)})
    # The shell: the document between the pills and the panels, in order. Pills come
    # first in the document (the strip is in the masthead), the panels after.
    spans = sorted([(t["pill"][0], t["pill"][1], f'<!--hr-tab:{t["id"]}-->') for t in cut["tabs"]]
                   + [(t["start"], t["end"], f'<!--hr-panel:{t["id"]}-->') for t in cut["tabs"]])
    for a, b, mark in spans:
        shell.append(doc[pos:a])
        shell.append(mark)
        pos = b
    shell.append(doc[pos:])
    shell_hash = _panel_hash("".join(shell), json.dumps(ACTIONS if actions is None else actions,
                                                       sort_keys=True, default=str))

    # Stamp from the end forwards so earlier offsets stay valid. Last in the opening tag:
    # every reader of the page that matches `<section class="panel" id="…"` keeps matching.
    out = doc
    for t, meta in sorted(zip(cut["tabs"], tabs), key=lambda p: -p[0]["start"]):
        mark = f' data-hr-hash="{meta["hash"]}"'
        at = doc.index(">", t["start"])
        out = out[:at] + mark + out[at:]
        cut_at = at - t["start"]
        meta["section"] = meta["section"][:cut_at] + mark + meta["section"][cut_at:]
    out = _PANEL_HTML_OPEN.sub(f'<html data-hr-shell="{shell_hash}"', out, count=1)
    manifest = {
        "version": PANELS_VERSION, "page": page, "shell": shell_hash,
        "tabs": [{"id": m["id"], "hash": m["hash"], "pill": m["pill"],
                  "swappable": not m["blockers"],
                  **({"blockers": m["blockers"]} if m["blockers"] else {})}
                 for m in tabs],
    }
    return out, {"manifest": manifest, "sections": {m["id"]: m["section"] for m in tabs}}


def panel_piece(tab_id: str, tab_hash: str, section: str) -> str:
    """One tab's file: a first line a reader can check against the manifest, then the
    panel. The check is what makes a fetch that raced a rebuild harmless: a piece from a
    newer build than the manifest says is refused, and the page reloads instead."""
    return f"<!-- hr-tab {tab_id} {tab_hash} -->\n{section}\n"


def _panel_write_if_changed(path: Path, text: str) -> None:
    """Unchanged pieces keep their mtime; a changed one is replaced whole, never seen
    half-written by a page fetching it while a build is under way."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    part = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def write_panels(out_dir: Path, stamped: dict | None) -> Path | None:
    """The pieces, then the manifest — last, so a manifest on disk never names a piece
    that is not there yet. A page that could not be cut leaves no manifest behind: the
    previous build's would describe a page that no longer exists."""
    folder = Path(out_dir) / PANELS_DIR
    manifest_path = folder / PANELS_MANIFEST
    if stamped is None:
        if manifest_path.exists():
            manifest_path.unlink()
        return None
    folder.mkdir(parents=True, exist_ok=True)
    manifest = stamped["manifest"]
    keep = set()
    for t in manifest["tabs"]:
        name = f'{t["id"]}.html'
        keep.add(name)
        _panel_write_if_changed(folder / name, panel_piece(t["id"], t["hash"], stamped["sections"][t["id"]]))
    for old in folder.glob("*.html"):
        if old.name not in keep:
            old.unlink()
    _panel_write_if_changed(manifest_path, json.dumps(manifest, indent=1) + "\n")
    return manifest_path


def read_panels_manifest(out_dir: Path) -> dict | None:
    """The manifest as the server hands it to an open page, or `None` when there is none
    or it does not parse (mid-write, or a page built before the pieces existed)."""
    try:
        m = json.loads((Path(out_dir) / PANELS_DIR / PANELS_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) and m.get("version") == PANELS_VERSION else None


def restamp_page(out_dir: Path, page: str = "review.html") -> bool:
    """Stamp a page that was edited after its build, and write its pieces again.

    `refresh-card.py` splices one redrawn card into the finished page rather than
    rebuilding it; the panel holding the card has changed, and an open page that did not
    press the card learns that only from the hashes. The action register is the one on
    disk (`.actions.json`), which is the build's plus whatever the card merged into it."""
    out_dir = Path(out_dir)
    path = out_dir / page
    try:
        doc = path.read_text(encoding="utf-8")
        acts = json.loads((out_dir / ACTIONS_FILE).read_text(encoding="utf-8")).get("actions")
    except (OSError, ValueError, AttributeError):
        return False
    stamped, pieces = stamp_panels(doc, out_dir, page, actions=acts or {})
    if stamped != doc:
        _panel_write_if_changed(path, stamped)
    write_panels(out_dir, pieces)
    return pieces is not None
