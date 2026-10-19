"""Serve, pressed off disk, has to start a server — and a running one must not reload a tab
for writes the page never shows. Both broke on 19 Oct 2026:

- The launcher was a Background launchd job, and every server it started inherited that
  class (priority 4, throttled I/O). On a busy Mac a probe took 5-15 s, so `find_server`
  took a live server for none, started another, and the launcher gave up after 30 s on every
  click. Three servers ended up serving one report.
- A coverage run writes one `.exec` per test into `.human-review/coverage/`, a second or two
  apart; each gap was a quiet period, and the served tab reloaded about once a second.
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import re
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("serve_review_lifecycle", "serve-review.py")
launcher = _load("serve_launcher_lifecycle", "serve-launcher.py")


# --- the launcher's launchd class ---------------------------------------------------------

def test_the_launcher_is_not_installed_as_a_background_job():
    """Its class is inherited by every server it starts. Background (and unset, which is
    Standard) are throttled; the server answers the click the reader is waiting on."""
    script = (HERE / "install-serve-launcher.sh").read_text(encoding="utf-8")
    kinds = re.findall(r"<key>ProcessType</key><string>(\w+)</string>", script)
    assert kinds == ["Interactive"]


# --- a slow server is still the report's server -------------------------------------------

def _slow_marker(served: Path, delay: float):
    """A server that answers the marker for `served`, but only after `delay` seconds."""
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            body = json.dumps({sr.MARKER_KEY: 1, "pid": 1,
                               "served": str(served.resolve())}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_the_recorded_server_is_waited_for_not_replaced(tmp_path):
    """Two seconds is past the one-second scan, well inside the patience the identity file
    earns: the answer is that server, not "none, start another"."""
    httpd = _slow_marker(tmp_path, 2.0)
    try:
        port = httpd.server_address[1]
        (tmp_path / sr.IDENTITY_FILE).write_text(json.dumps({"port": port, "pid": 1}))
        found = sr.find_server(tmp_path, preferred=port + 1, span=0)
        assert found and found[0] == port
    finally:
        httpd.shutdown()


def test_the_scan_still_does_not_wait_on_ports_that_are_only_a_guess(tmp_path):
    """Patience is for the recorded port only: twenty slow guesses would be twenty
    seconds of a click."""
    httpd = _slow_marker(tmp_path, 2.0)
    try:
        port = httpd.server_address[1]
        t0 = time.monotonic()
        assert sr.find_server(tmp_path, preferred=port, span=1) is None
        assert time.monotonic() - t0 < 1.8
    finally:
        httpd.shutdown()


def test_a_launcher_that_timed_out_still_hands_over_a_server_that_came_up(tmp_path, monkeypatch):
    page = tmp_path / "review.html"
    page.write_text('<b id="hr-serve">Serve</b>')
    httpd = _slow_marker(tmp_path, 0.0)
    try:
        port = httpd.server_address[1]
        (tmp_path / ".server.json").write_text(json.dumps({"port": port, "pid": 1}))

        def too_slow(*a, **kw):
            raise launcher.subprocess.TimeoutExpired(a[0], 30)

        monkeypatch.setattr(launcher.subprocess, "run", too_slow)
        assert launcher.serve(page) == (200, {"url": f"http://127.0.0.1:{port}/review.html"})
    finally:
        httpd.shutdown()


def test_a_launcher_that_timed_out_with_nothing_up_says_so(tmp_path, monkeypatch):
    page = tmp_path / "review.html"
    page.write_text('<b id="hr-serve">Serve</b>')

    def too_slow(*a, **kw):
        raise launcher.subprocess.TimeoutExpired(a[0], 30)

    monkeypatch.setattr(launcher.subprocess, "run", too_slow)
    status, body = launcher.serve(page)
    assert status == 504 and "30 s" in body["error"]


# --- what the watcher reloads for ---------------------------------------------------------

def _tree(root: Path):
    (root / "assets").mkdir(parents=True)
    (root / "review.html").write_text("<html></html>")
    (root / "assets" / "a.svg").write_text("<svg/>")
    for d in ("coverage/junit-0", "logs", ".city-build", ".model-prev", ".tools"):
        (root / d).mkdir(parents=True)


def test_a_coverage_run_writing_into_the_review_does_not_reload_the_page(tmp_path):
    _tree(tmp_path)
    before = sr.fingerprint(tmp_path)
    for i in range(3):
        (tmp_path / "coverage" / "junit-0" / f"{i:05}.exec").write_bytes(b"x" * i)
    (tmp_path / "logs" / "testcov.log").write_text("running")
    for d in (".city-build", ".model-prev", ".tools"):
        (tmp_path / d / "scratch").write_text("x")
    (tmp_path / sr.IDENTITY_FILE).write_text('{"port": 1}')
    assert sr.fingerprint(tmp_path) == before


def test_the_page_and_its_assets_still_reload_it(tmp_path):
    _tree(tmp_path)
    before = sr.fingerprint(tmp_path)
    (tmp_path / "assets" / "a.svg").write_text("<svg></svg>")
    assert sr.fingerprint(tmp_path) != before
    mid = sr.fingerprint(tmp_path)
    (tmp_path / "review.html").write_text("<html>new</html>")
    assert sr.fingerprint(tmp_path) != mid


def test_only_the_top_level_scratch_is_skipped(tmp_path):
    """`assets/logs/` is something the page may show: the names are skipped at the top of
    the review directory, not wherever they turn up."""
    _tree(tmp_path)
    (tmp_path / "assets" / "logs").mkdir()
    before = sr.fingerprint(tmp_path)
    (tmp_path / "assets" / "logs" / "shown.html").write_text("x")
    assert sr.fingerprint(tmp_path) != before
