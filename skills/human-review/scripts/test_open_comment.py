"""A card posted to the PR opens on its lines *and* on its comment thread: the page sends
`comment=1` (with `commentLine` when the thread sits on another line than the reference
starts on), the server checks it and passes it on, and the editor bridge expands and focuses
the thread. Every other link goes out exactly as it did."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_action_server import _call, build, server, srv  # noqa: F401  (fixture)
from test_open_range import SHA, _bridge, _file, _record


# ── the server ────────────────────────────────────────────────────────────────────────────

def test_a_comment_reaches_the_editor(server, tmp_path, monkeypatch):
    f = _file(tmp_path)
    opened, _ = _record(monkeypatch)

    status, _ = _call(server, "GET", f"{srv.OPEN}?path={f}&line=4&comment=1")

    assert status == 204 and opened == [((f, 4), {"comment": True})]


def test_the_comment_line_travels_when_it_is_not_the_first_line(server, tmp_path, monkeypatch):
    f = _file(tmp_path)
    opened, _ = _record(monkeypatch)

    _call(server, "GET", f"{srv.OPEN}?path={f}&line=45&endLine=48&comment=1&commentLine=48")
    _call(server, "GET", f"{srv.OPEN}?path={f}&line=45&endLine=48&comment=1&commentLine=45")

    assert opened == [((f, 45), {"end_line": 48, "comment": True, "comment_line": 48}),
                      ((f, 45), {"end_line": 48, "comment": True})]


def test_a_guide_with_its_commit_asks_the_bridge_for_the_thread(server, tmp_path, monkeypatch):
    f = _file(tmp_path)
    _, asked = _record(monkeypatch)

    _call(server, "GET", f"{srv.OPEN}?path={f}&line=4&comment=true&sha={SHA}&root={tmp_path}")

    assert asked == [((f, 4, SHA, str(tmp_path), ""), {"comment": True})]


@pytest.mark.parametrize("flag", ["0", "", "yes", "TRUE1", "false"])
def test_anything_but_an_explicit_comment_sends_none(server, tmp_path, monkeypatch, flag):
    f = _file(tmp_path)
    opened, _ = _record(monkeypatch)

    _call(server, "GET", f"{srv.OPEN}?path={f}&line=4&comment={flag}&commentLine=9")

    assert opened == [((f, 4), {})]


@pytest.mark.parametrize("at", ["x", "-3", "0", "4.5", ""])
def test_a_bad_comment_line_is_dropped_and_the_comment_kept(at):
    assert srv.comment_aim({"comment": ["1"], "commentLine": [at]}, 4) == {"comment": True}


GH = "https://github.com/victorrentea/petclinic/pull/53#discussion_r1234"


def test_the_comments_github_url_travels_to_the_editor(server, tmp_path, monkeypatch):
    """IntelliJ cannot expand the thread in the file; it offers the comment on GitHub, and
    needs its URL for that."""
    f = _file(tmp_path)
    opened, _ = _record(monkeypatch)
    from urllib.parse import quote
    _call(server, "GET", f"{srv.OPEN}?path={f}&line=4&comment=1&commentUrl={quote(GH, safe='')}")
    assert opened == [((f, 4), {"comment": True, "comment_url": GH})]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://evil.example/o/r/pull/1",
                                 "http://github.com/o/r/pull/1", "https://github.com/o/r/issues/1",
                                 "https://github.com.evil/o/r/pull/1", "file:///etc/passwd"])
def test_a_comment_url_that_is_not_a_github_pull_request_is_dropped(url):
    assert srv.comment_aim({"comment": ["1"], "commentUrl": [url]}, 4) == {"comment": True}


def test_no_comment_no_url():
    assert srv.comment_aim({"commentUrl": [GH]}, 4) == {}


# ── what goes to the bridge ───────────────────────────────────────────────────────────────

def test_open_file_carries_the_comment_only_when_asked(tmp_path, monkeypatch):
    httpd, got = _bridge()
    try:
        entry = {"port": httpd.server_address[1], "token": "t"}
        monkeypatch.setattr(srv, "owning_windows", lambda target: [(entry, {})])
        f = _file(tmp_path)

        srv.open_in_editor(f, 45, end_line=48, comment=True, comment_line=48)
        srv.open_in_editor(f, 4, comment=True)
        srv.open_in_editor(f, 4)
        srv.open_in_editor(f, 4, comment=True, comment_url=GH)

        assert [b for _, b in got] == [
            {"path": str(f), "line": 45, "focus": True, "endLine": 48,
             "comment": True, "commentLine": 48},
            {"path": str(f), "line": 4, "focus": True, "comment": True},
            {"path": str(f), "line": 4, "focus": True},
            {"path": str(f), "line": 4, "focus": True, "comment": True, "commentUrl": GH}]
    finally:
        httpd.shutdown()


def test_review_open_carries_the_comment(tmp_path, monkeypatch):
    httpd, got = _bridge()
    try:
        registry = tmp_path / ".walkie-talkie" / "ide"
        registry.mkdir(parents=True)
        (registry / "vscode-1.json").write_text(json.dumps({"port": httpd.server_address[1], "token": "t"}))
        monkeypatch.setattr(srv.Path, "home", classmethod(lambda cls: tmp_path))

        srv.review_open(Path("/r/V4.sql"), 4, SHA, "/r", "test-pr", comment=True)
        srv.review_open(Path("/r/V4.sql"), 4, SHA, "/r", "test-pr", comment=True, comment_url=GH)

        assert got == [("/review-open", {"file": "/r/V4.sql", "line": 4, "sha": SHA,
                                         "root": "/r", "branch": "test-pr", "comment": True}),
                       ("/review-open", {"file": "/r/V4.sql", "line": 4, "sha": SHA,
                                         "root": "/r", "branch": "test-pr", "comment": True,
                                         "commentUrl": GH})]
    finally:
        httpd.shutdown()


# ── the card ──────────────────────────────────────────────────────────────────────────────

def test_an_inline_thread_says_where_it_sits():
    link = build.gh_comment_link({"_ghUrl": "https://x/pull/49#discussion_r1", "_ghThread": {
        "path": "db/V4__visit_vet.sql", "line": 4, "start": 4}})
    assert 'data-pr-path="db/V4__visit_vet.sql" data-pr-line="4" data-pr-start="4"' in link


def test_a_summary_item_names_no_thread():
    link = build.gh_comment_link({"_ghUrl": "https://x/pull/49#pullrequestreview-1",
                                  "_ghInSummary": True})
    assert "data-pr-" not in link and "on GitHub" in link


# ── the page ──────────────────────────────────────────────────────────────────────────────

def _comment_query(path: str, line: str, face: str, gh: dict | None):
    """Run the page's own `commentQuery` in node, on a card `<li>` whose "on GitHub ↗" link
    carries `gh` as its data-pr-* attributes (None: a card with no posted thread)."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = build.EDITOR_JS
    start = js.index("  function endOf(link, line) {")
    stop = js.index("  // The one button on the page that copies something")
    script = js[start:stop] + f"""
var attrs = {json.dumps(gh or {})};
var gh = {{ matches: function () {{ return {json.dumps(gh is not None)}; }},
           getAttribute: function (k) {{ return attrs[k.replace('data-pr-', '')] || null; }} }};
var li = {{ children: [{{ matches: function () {{ return false; }} }}, gh], parentElement: null }};
var link = {{ textContent: {json.dumps(face)}, getAttribute: function () {{ return ''; }},
             closest: function () {{ return li; }} }};
process.stdout.write(JSON.stringify(commentQuery(link, {json.dumps(path)}, {json.dumps(line)})));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


V4 = "/w/petclinic-pr/petclinic-backend/src/main/resources/db/migration/V4__visit_vet.sql"
V4_REL = "petclinic-backend/src/main/resources/db/migration/V4__visit_vet.sql"


def test_the_cards_own_line_asks_for_its_thread():
    assert _comment_query(V4, "4", "V4__visit_vet.sql:4",
                          {"path": V4_REL, "line": "4", "start": "4"}) == "&comment=1"


def test_a_range_names_the_line_the_thread_sits_on():
    assert _comment_query("/w/p/VisitTest.java", "445", "VisitTest.java:445-448",
                          {"path": "VisitTest.java", "line": "448", "start": "445"}) \
        == "&comment=1&commentLine=448"


def test_another_file_or_other_lines_in_the_card_ask_for_nothing():
    gh = {"path": V4_REL, "line": "4", "start": "4"}
    assert _comment_query("/w/petclinic-pr/Other.java", "4", "Other.java:4", gh) == ""
    assert _comment_query(V4, "9", "V4__visit_vet.sql:9", gh) == ""
    # A path that only ends in the same letters is another file.
    assert _comment_query("/w/x" + V4_REL, "4", "V4__visit_vet.sql:4", gh) == ""


def test_a_card_without_a_posted_thread_asks_for_nothing():
    assert _comment_query(V4, "4", "V4__visit_vet.sql:4", None) == ""


def test_the_card_names_its_comment_on_github():
    gh = {"path": "VisitTest.java", "line": "448", "start": "445", "href": GH}
    assert _comment_query("/w/p/VisitTest.java", "445", "VisitTest.java:445-448", gh) \
        == "&comment=1&commentLine=448&commentUrl=" + __import__("urllib.parse").parse.quote(GH, safe="~()*!.'")


def test_the_served_open_sends_it():
    assert "+ commentQuery(link, ref2.path, ref2.line)" in build.EDITOR_JS


def test_an_intellij_link_off_disk_carries_the_comment_too():
    """Off disk with IntelliJ picked, the card's reference becomes a jetbrains:// link — with
    the same comment fields the served page sends, so the plugin can offer the thread."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = build.EDITOR_JS
    body = js[js.index("  function endOf(link, line) {"):js.index("  // The one button on the page that copies something")]
    gh = {"path": "VisitTest.java", "line": "448", "start": "445", "href": GH}
    script = f"""
var STAMP = {{}};
function parse() {{ return {{path: '/w/p/VisitTest.java', line: 445}}; }}
{body}
var attrs = {json.dumps(gh)};
var gh = {{ matches: function () {{ return true; }},
           getAttribute: function (k) {{ return attrs[k.replace('data-pr-', '')] || null; }} }};
var li = {{ children: [gh], parentElement: null }};
var link = {{ textContent: 'VisitTest.java:445-448', getAttribute: function () {{ return ''; }},
             closest: function () {{ return li; }} }};
process.stdout.write(ideaLink(link));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    from urllib.parse import parse_qs, urlsplit
    u = urlsplit(out)
    assert out.startswith("jetbrains://idea/human-review/open?")
    assert {k: v[0] for k, v in parse_qs(u.query).items()} == {
        "file": "/w/p/VisitTest.java", "line": "445", "endLine": "448",
        "comment": "1", "commentLine": "448", "commentUrl": GH}
