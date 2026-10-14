"""The change set, file by file: what each number on the page is a count of.

The masthead says `files +26 / ✍23` and a package box on the Structure tab is shaded by
how much of the branch landed in it. Both are counts, and a count the reader cannot open
is one they take on trust. So both carry the list behind them, as `data-tip-pop` (tip.js:
a tip that takes the pointer, scrolls, and holds its links in the Tab order), each file a
link that opens it as a diff — the base on the left, the working tree on the right —
through the same handles every other diff link on the page uses (editor.js).

Measured the way `chips._numstat` measures, from the same range with the same pathspecs,
so the list under `+26` has twenty-six rows.
"""
from __future__ import annotations

import html
import urllib.parse
from pathlib import Path

from .snippets import diff_uri_handler
from .util import _git


def changed_files(root: Path, rng: str, pathspecs: list[str]) -> list[dict]:
    """`{path, status, adds, dels}` per file of `rng`, `status` one of `A`, `M`, `D` — a
    rename or a copy is an edit from the reviewer's side of the desk, as the chip counts
    it. `adds`/`dels` are None for a binary file."""
    status = _git(root, "diff", "--name-status", rng, "--", ".", *pathspecs) or ""
    numstat = _git(root, "diff", "--numstat", "-z", rng, "--", ".", *pathspecs) or ""
    lines: dict[str, tuple[int | None, int | None]] = {}
    tokens = numstat.split("\0")
    i = 0
    while i < len(tokens):
        cols = tokens[i].split("\t")
        i += 1
        if len(cols) < 3:
            continue
        path = cols[2]
        if not path:                       # a rename: `a\td\t` then old, then new
            path = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2
        a, d = cols[0], cols[1]
        lines[path] = (int(a) if a.isdigit() else None, int(d) if d.isdigit() else None)
    out = []
    for line in status.splitlines():
        cols = line.split("\t")
        if len(cols) < 2 or not cols[0]:
            continue
        code = cols[0][:1]
        path = cols[-1]
        a, d = lines.get(path, (None, None))
        out.append({"path": path, "status": code if code in "AD" else "M",
                    "adds": a, "dels": d})
    return sorted(out, key=lambda f: f["path"])


def _numbers(f: dict) -> str:
    if f["adds"] is None and f["dels"] is None:
        return '<span class="tipnum">binary</span>'
    bits = [f"+{f['adds']}" if f["adds"] else "", f"−{f['dels']}" if f["dels"] else ""]
    said = " ".join(b for b in bits if b)
    return f'<span class="tipnum">{said}</span>' if said else ""


def file_link(f: dict, base: str, root: Path, face: str | None = None) -> str:
    """One file of the list: a link that opens its diff, or — deleted, so there is no
    working-tree side to open — its name alone."""
    rel = f["path"]
    face = html.escape(face or rel)
    src = root / rel
    if f["status"] == "D" or not src.is_file():
        return f'<span title="deleted">{face}</span>'
    # The extension's own diff URI reads the left side out of git: an added file has none,
    # and goes through the served diff or the plain file link instead (snippets.diff_link_html).
    handler = None if f["status"] == "A" else diff_uri_handler()
    uri = ""
    if handler:
        q = urllib.parse.urlencode({"file": str(src.resolve()), "base": base, "line": 1})
        uri = f' data-diff-uri="{html.escape(f"vscode://{handler}/diff?{q}")}"'
    # No `srcref` pill: in a list of thirty files the boxed face is thirty boxes. editor.js
    # takes any `vscode:` link, whatever its class, and the data-diff-* make it a diff.
    return (f'<a class="popfile" href="vscode://file/{html.escape(str(src.resolve()))}:1:1"'
            f'{uri} data-diff-path="{html.escape(rel)}" data-diff-base="{html.escape(base)}">'
            f'{face}</a>')


def files_pop(head: str, files: list[dict], base: str, root: Path,
              strip: str = "") -> str:
    """The markup of one `data-tip-pop`: a line saying what the list is, then the files.
    `strip` is a folder prefix the reader already knows (the package box they hovered)."""
    items = []
    for f in files:
        face = f["path"][len(strip):].lstrip("/") if strip and f["path"].startswith(strip) else None
        items.append(f"<li>{file_link(f, base, root, face)}{_numbers(f)}</li>")
    return (f'<p class="tippophead">{head}</p>'
            f'<ul class="tiplist">{"".join(items)}</ul>')
