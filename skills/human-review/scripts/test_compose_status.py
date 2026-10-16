#!/usr/bin/env python3
"""The Demo tab's Start shows its containers coming up, one chip each.

"Starting…" stood in the Running-app row for minutes — a first build, then a database
slow to say healthy — and on a stage nothing on it told "still coming" from "broken"
(7 Oct 2026). So the server follows the run's own `docker compose` output, finds the
project by the label compose put on the first container it named, and answers
`/__compose__?run=<id>` with one row per container; the row draws them grey, green, red.

Pinned here, in the order a Start lives through them: the output lines the scrape reads,
the lights a `docker ps` row turns into, the endpoint (with docker stood in for), and the
chips in a real browser — drawn while the run goes, gone once it succeeds, kept red with
the container's last line when it fails.

Run with:  python3 -m pytest test_compose_status.py
"""
from __future__ import annotations

import functools
import http.client
import importlib.util
import json
import socketserver
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


srv = _load("serve_review_compose", "serve-review.py")


# --------------------------------------------------------------------------- #
# what compose prints, and what is kept of it
# --------------------------------------------------------------------------- #

# `docker compose up -d --build --wait`, piped — Docker Compose v5.1.1, verbatim.
UP_OUTPUT = """\
 Image petclinic-env-backend:806e3de6 Building
 Image petclinic-env-frontend:806e3de6 Building
#6 [backend 2/3] RUN echo hi
 Image petclinic-env-backend:806e3de6 Built
 Network petclinic-806e3de6_default Creating
 Container petclinic-806e3de6-db-1 Creating
 Container petclinic-806e3de6-backend-1 Creating
 Container petclinic-806e3de6-db-1 Started
 Container petclinic-806e3de6-db-1 Healthy
container petclinic-806e3de6-bad-1 exited (3)
"""


def test_the_scrape_keeps_the_images_in_order_and_the_first_container():
    facts = {}
    for line in UP_OUTPUT.splitlines():
        srv.compose_scrape(facts, line)
    assert list(facts["images"].items()) == [
        ("petclinic-env-backend:806e3de6", "Built"),
        ("petclinic-env-frontend:806e3de6", "Building")]
    # The first one named, and only that: it is a handle on the project, nothing more.
    assert facts["container"] == "petclinic-806e3de6-db-1"


def test_lines_that_are_not_compose_events_are_ignored():
    facts = {}
    for line in ["Container", "🐳 building petclinic-x from x", "#5 [1/3] FROM alpine",
                 "  http://localhost:4200", "container x exited (3)"]:
        srv.compose_scrape(facts, line)
    assert facts == {}


# --------------------------------------------------------------------------- #
# a docker ps row, as a light
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("state,status,light,health,code", [
    ("running", "Up 4 seconds (healthy)", "up", "healthy", None),
    ("running", "Up 2 seconds (health: starting)", "starting", "starting", None),
    ("running", "Up 9 seconds (unhealthy)", "down", "unhealthy", None),
    ("running", "Up Less than a second", "up", "", None),       # no healthcheck to wait for
    ("created", "Created", "starting", "", None),
    ("exited", "Exited (0) 1 second ago", "done", "", 0),       # a one-shot that did its job
    ("exited", "Exited (3) 2 seconds ago", "down", "", 3),
    ("restarting", "Restarting (1) 1 second ago", "down", "", 1),
    ("dead", "Dead", "down", "", None),
])
def test_each_container_state_has_one_light(state, status, light, health, code):
    assert srv.container_light(state, status) == (light, health, code)


def test_ps_rows_come_back_sorted_by_service_whatever_order_docker_listed_them():
    text = "\n".join(json.dumps(r) for r in [
        {"Names": "p-web-1", "State": "created", "Status": "Created", "Service": "web"},
        {"Names": "p-db-1", "State": "running", "Status": "Up 3s (healthy)", "Service": "db"},
        # A plain `{{json .}}` row: the service is only in the joined label string.
        {"Names": "p-api-1", "State": "exited", "Status": "Exited (1) 1s ago",
         "Labels": "com.docker.compose.project=p,com.docker.compose.service=api"},
    ]) + "\nnot json\n"
    rows = srv.parse_compose_ps(text)
    assert [(r["service"], r["light"], r["exit"]) for r in rows] == [
        ("api", "down", 1), ("db", "up", None), ("web", "starting", None)]


# --------------------------------------------------------------------------- #
# compose_status: the endpoint's answer, docker stood in for
# --------------------------------------------------------------------------- #

class _Run:
    def __init__(self, compose, state="running"):
        self.id, self.state, self.compose = "r1", state, compose
        self._lock = threading.Lock()


def _docker(project="petclinic-806e3de6", rows=()):
    calls = []

    def docker(*args, timeout=5.0):
        calls.append(args)
        if args[0] == "inspect":
            return project + "\n"
        if args[0] == "ps":
            assert f"label=com.docker.compose.project={project}" in args
            return "\n".join(json.dumps(r) for r in rows)
        raise AssertionError(args)
    docker.calls = calls
    return docker


def test_before_any_container_the_answer_is_the_images_being_built():
    docker = _docker()
    got = srv.compose_status(_Run({"images": {"a:1": "Building"}}), docker=docker)
    assert got["images"] == [{"image": "a:1", "state": "Building"}]
    assert got["containers"] == [] and got["project"] == ""
    assert docker.calls == [], "nothing to ask docker until compose names a container"


def test_the_project_is_read_off_the_container_label_once_and_remembered():
    rows = [{"Names": "petclinic-806e3de6-db-1", "State": "running",
             "Status": "Up 3s (healthy)", "Service": "db"},
            {"Names": "petclinic-806e3de6-backend-1", "State": "running",
             "Status": "Up 1s (health: starting)", "Service": "backend"}]
    docker, run = _docker(rows=rows), _Run({"container": "petclinic-806e3de6-db-1"})
    got = srv.compose_status(run, docker=docker)
    assert got["project"] == "petclinic-806e3de6"
    assert (got["up"], got["total"]) == (1, 2)
    assert [c["service"] for c in got["containers"]] == ["backend", "db"]
    srv.compose_status(run, docker=docker)
    assert [c[0] for c in docker.calls] == ["inspect", "ps", "ps"], "inspected once"


def test_a_red_container_carries_its_last_log_line_and_only_the_red_one_is_asked():
    rows = [{"Names": "p-db-1", "State": "running", "Status": "Up 3s", "Service": "db"},
            {"Names": "p-bad-1", "State": "exited", "Status": "Exited (3) 1s ago",
             "Service": "bad"}]
    asked = []

    def log_line(name):
        asked.append(name)
        return "FATAL - no DATABASE_URL set"
    got = srv.compose_status(_Run({"container": "p-db-1"}), docker=_docker("p", rows),
                             log_line=log_line)
    bad = got["containers"][0]
    assert (bad["service"], bad["light"], bad["tip"]) == ("bad", "down",
                                                          "FATAL - no DATABASE_URL set")
    assert asked == ["p-bad-1"]


SPRING_DEATH = """\
2026-10-07 ERROR 1 --- [main] o.s.boot.SpringApplication : Application run failed
org.springframework.beans.factory.BeanCreationException: Error creating bean 'flyway'
\tat org.springframework.beans.factory.support.AbstractBeanFactory.getBean(AbstractBeanFactory.java:1)
Caused by: org.flywaydb.core.internal.exception.FlywaySqlException: Unable to obtain connection
\tat org.flywaydb.core.internal.jdbc.JdbcUtils.openConnection(JdbcUtils.java:59)
Caused by: org.postgresql.util.PSQLException: FATAL: database "nope" does not exist
\tat org.postgresql.core.v3.ConnectionFactoryImpl.doConnect(ConnectionFactoryImpl.java:1)
\t... 28 common frames omitted
"""


@pytest.mark.parametrize("text,expected", [
    # The deepest cause, not `... 28 common frames omitted`, which is what it printed last.
    (SPRING_DEATH, 'Caused by: org.postgresql.util.PSQLException: FATAL: database "nope" does not exist'),
    ("starting\nFATAL - no DATABASE_URL set\nbye\n", "FATAL - no DATABASE_URL set"),
    ("one\ntwo\n", "two"),                      # nothing sounds like a reason: the last line
    ("", ""),
])
def test_the_red_chip_says_why_rather_than_what_was_printed_last(text, expected):
    assert srv.reason_line(text) == expected


def test_a_label_that_is_not_a_project_name_is_not_passed_on_to_docker():
    docker = _docker(project="x; rm -rf /")
    got = srv.compose_status(_Run({"container": "c"}), docker=docker)
    assert got["project"] == "" and [c[0] for c in docker.calls] == ["inspect"]


# --------------------------------------------------------------------------- #
# the endpoint, on a socket
# --------------------------------------------------------------------------- #

@pytest.fixture
def server(tmp_path, monkeypatch):
    (tmp_path / srv.ACTIONS_FILE).write_text(json.dumps({"version": 1, "actions": {
        "demo-env": {"command": "printf ' Container hrt-db-1 Creating \\nhttp://localhost:4\\n'",
                     "params": {}, "scrape": "url"}}}))
    srv._manifest.update(mtime=None, actions={})
    monkeypatch.setattr(srv.Handler, "root", str(tmp_path))
    monkeypatch.setattr(srv.Handler, "token", "test-token")
    monkeypatch.setattr(srv, "ROOT", tmp_path)
    monkeypatch.setattr(srv, "_docker", _docker("hrt", [
        {"Names": "hrt-db-1", "State": "running", "Status": "Up 1s", "Service": "db"}]))
    httpd = socketserver.ThreadingTCPServer(
        ("127.0.0.1", 0), functools.partial(srv.Handler, directory=str(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield httpd.server_address
    finally:
        httpd.shutdown()
        httpd.server_close()


def _call(address, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(*address, timeout=10)
    sent = {"Host": f"127.0.0.1:{address[1]}", "Sec-Fetch-Site": "same-origin",
            "X-Human-Review-Token": "test-token"}
    if body is not None:
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    conn.request(method, path, json.dumps(body) if body is not None else None, sent)
    r = conn.getresponse()
    payload = r.read().decode()
    conn.close()
    return r.status, payload


def test_the_endpoint_answers_for_a_run_it_issued(server):
    status, payload = _call(server, "POST", srv.RUN, {"id": "demo-env", "params": {}})
    assert status == 200, payload
    run = json.loads(payload)["run"]
    until = time.time() + 5
    while time.time() < until:
        got = json.loads(_call(server, "GET", f"{srv.COMPOSE}?run={run}")[1])
        if got["state"] != "running":
            break
        time.sleep(0.05)
    assert got["project"] == "hrt"
    assert [(c["service"], c["light"]) for c in got["containers"]] == [("db", "up")]


def test_the_endpoint_does_not_know_a_run_nobody_issued(server):
    assert _call(server, "GET", f"{srv.COMPOSE}?run=nope")[0] == 404


def test_a_cross_site_poll_is_refused(server):
    assert _call(server, "GET", f"{srv.COMPOSE}?run=x",
                 headers={"Sec-Fetch-Site": "cross-site"})[0] == 403


# --------------------------------------------------------------------------- #
# Docker Desktop closed: the Start opens it and says so
# --------------------------------------------------------------------------- #

def test_the_servers_docker_lines_are_a_phase_and_not_an_image():
    facts = {}
    srv.compose_scrape(facts, srv.DOCKER_STARTING)
    assert facts == {"docker": "starting"}
    srv.compose_scrape(facts, srv.DOCKER_UP)
    assert facts == {"docker": "up"}
    assert srv.compose_status(_Run(facts), docker=_docker())["docker"] == "up"


def _fakes(tmp_path, refusals):
    """A `docker` that refuses `info` for its first `refusals` calls, and an `open` that
    logs what it was asked to open — the two things the preflight touches on the host."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "docker").write_text(
        "#!/bin/sh\nn=$(cat \"$0.n\" 2>/dev/null || echo 0); echo $((n+1)) > \"$0.n\"\n"
        f"[ \"$n\" -ge {refusals} ]\n")
    (bin_ / "open").write_text("#!/bin/sh\necho \"$@\" >> \"$0.log\"\n")
    for f in ("docker", "open"):
        (bin_ / f).chmod(0o755)
    return bin_


@pytest.mark.skipif(__import__("platform").system() != "Darwin", reason="macOS only")
@pytest.mark.parametrize("refusals, opened", [(0, False), (2, True)])
def test_the_start_opens_docker_desktop_only_when_it_is_closed(tmp_path, refusals, opened):
    import os
    import subprocess
    bin_ = _fakes(tmp_path, refusals)
    out = subprocess.run(["/bin/sh", "-c", srv.DOCKER_PREFLIGHT + "echo the-command"],
                         capture_output=True, text=True, timeout=30,
                         env={**os.environ, "PATH": f"{bin_}:/usr/bin:/bin"}).stdout
    lines = out.splitlines()
    if opened:
        assert lines == [srv.DOCKER_STARTING, srv.DOCKER_UP, "the-command"]
        assert (bin_ / "open.log").read_text().split() == ["-ga", "Docker"], \
            "in the background, without taking focus from the page"
    else:
        assert lines == ["the-command"], "a running Docker costs one `docker info`"
        assert not (bin_ / "open.log").exists()


def test_only_the_start_gets_the_preflight(tmp_path):
    (tmp_path / srv.ACTIONS_FILE).write_text(json.dumps({"version": 1, "actions": {
        "demo-env": {"command": "true", "params": {}},
        "demo-env-stop": {"command": "true", "params": {}}}}), encoding="utf-8")
    seen = {}

    class Spy:
        def __init__(self, action_id, entry, argv, cwd, on_done=None):
            seen[action_id] = argv
            self.id, self.action, self.state = action_id, action_id, "done"

    real, srv.Run = srv.Run, Spy
    try:
        for verb in ("demo-env", "demo-env-stop"):
            assert srv.start_run(verb, {}, tmp_path)[1] is None
    finally:
        srv.Run = real
    assert seen["demo-env"][-1] == srv.DOCKER_PREFLIGHT + "true"
    assert seen["demo-env-stop"][-1] == "true"


# --------------------------------------------------------------------------- #
# the chips, in a browser
# --------------------------------------------------------------------------- #

build = _load("build_review_compose", "build-review-html.py")

RUNTIME = {"command": "./start-docker.sh up --ref abc123", "base": "",
           "stop": "./start-docker.sh down petclinic-abc123"}

STUB = """<script>
window.COMPOSE = null; window.POLLS = 0;
window.HR = {onready: fn => setTimeout(fn, 0), can: () => true,
  run: (id, params, progress) => new Promise((resolve) => {
    progress && progress({run: 'r1', state: 'running', output: 'building'});
    window.FINISH = resolve;
  }),
  tail: snap => (snap && snap.output || '').trim()};
window.ACTIVE = window.ACTIVE || null; window.RAN = [];
const _run = window.HR.run;
window.HR.run = (id, params, progress) => (window.RAN.push(id), _run(id, params, progress));
window.fetch = url => url.startsWith('/__compose__')
  ? (window.POLLS++, Promise.resolve({ok: true, json: () => Promise.resolve(window.COMPOSE)}))
  : url.startsWith('/__run_status__')
  ? Promise.resolve({ok: true, json: () => Promise.resolve({active: window.ACTIVE})})
  : Promise.reject(new Error('down'));
</script>"""

READ = """() => {
  const box = document.querySelector('.appenv-pods');
  if (!box || box.hidden) return null;
  return {chips: [...box.querySelectorAll('.appenv-pod')].map(
            c => [c.textContent, c.dataset.light, c.dataset.tip]),
          count: box.querySelector('.appenv-pods-n').textContent};
}"""


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        pg = browser.new_page()
        yield pg
        browser.close()


def _load(page, html):
    """A fresh window per case: `set_content` keeps the old one, and with it the timers and
    pending runs of the case before, which then press buttons in this one."""
    page.goto("about:blank")
    page.set_content(html)


def _start(page):
    _load(page, "<!doctype html><meta charset=utf-8><style>" + build.CSS + "</style>"
                     + STUB + build.runtime_html(RUNTIME) + build.APP_ENV_JS)
    page.wait_for_timeout(50)
    page.evaluate("document.querySelector('.appenv-start .cmd-run').click()")


def _compose(page, doc):
    polls = page.evaluate("window.POLLS")
    page.evaluate("doc => { window.COMPOSE = doc; }", doc)
    page.wait_for_function(f"window.POLLS > {polls}", timeout=3000)
    page.wait_for_timeout(50)
    return page.evaluate(READ)


def test_the_images_then_the_containers_are_chips_while_start_runs(page):
    _start(page)
    seen = _compose(page, {"state": "running", "containers": [], "images": [
        {"image": "petclinic-env-backend:abc", "state": "Built"},
        {"image": "petclinic-env-frontend:abc", "state": "Building"}]})
    assert [c[:2] for c in seen["chips"]] == [["backend", "built"], ["frontend", "build"]]
    assert seen["count"] == "1/2 built"
    seen = _compose(page, {"state": "running", "up": 1, "total": 2, "images": [],
                           "containers": [
                               {"service": "backend", "light": "starting",
                                "status": "Up 1s (health: starting)"},
                               {"service": "db", "light": "up", "status": "Up 3s (healthy)"}]})
    assert [c[:2] for c in seen["chips"]] == [["backend", "starting"], ["db", "up"]]
    assert seen["count"] == "1/2 up"


def test_the_chips_leave_once_the_start_succeeds(page):
    _start(page)
    _compose(page, {"state": "running", "up": 1, "total": 1, "images": [],
                    "containers": [{"service": "db", "light": "up", "status": "Up"}]})
    page.evaluate("window.FINISH({state: 'done', result: {}})")
    page.wait_for_timeout(50)
    assert page.evaluate(READ) is None


def test_a_failed_start_keeps_the_red_chip_with_the_reason_on_hover(page):
    _start(page)
    page.evaluate("""window.COMPOSE = {state: 'failed', up: 1, total: 2, images: [],
        containers: [{service: 'bad', light: 'down', status: 'Exited (3) 1s ago',
                      tip: 'FATAL - no DATABASE_URL set'},
                     {service: 'db', light: 'up', status: 'Up 3s'}]}""")
    page.evaluate("window.FINISH({state: 'failed', exit: 1, output: 'exited (3)'})")
    page.wait_for_function("document.querySelector('.appenv-pod[data-light=down]')")
    seen = page.evaluate(READ)
    assert seen["chips"][0] == ["bad", "down", "bad: FATAL - no DATABASE_URL set"]
    assert seen["count"] == "1/2 up"


def test_a_page_reloaded_mid_start_picks_the_run_up_by_itself(page):
    """7 Oct 2026, on stage: a live patch rewrote the report a few seconds into a Start, the
    tab reloaded itself, and the reloaded row said "Offline" with no chips while the stack
    came up behind it — the address only appeared after a manual refresh. A served page
    that finds a `demo-env` run in flight follows it (the server joins the press to it)."""
    _load(page, "<!doctype html><meta charset=utf-8><style>" + build.CSS + "</style>"
                     + "<script>window.ACTIVE = {action: 'demo-env', state: 'running', run: 'r1'};"
                     + "</script>" + STUB + build.runtime_html(RUNTIME) + build.APP_ENV_JS)
    page.wait_for_function("window.RAN.includes('demo-env')", timeout=3000)
    seen = _compose(page, {"state": "running", "up": 1, "total": 2, "images": [],
                           "containers": [{"service": "db", "light": "up", "status": "Up"},
                                          {"service": "web", "light": "starting",
                                           "status": "Created"}]})
    assert seen["count"] == "1/2 up"
    assert page.evaluate("document.querySelector('.appenv-state').textContent") \
        .startswith("Starting containers 1/2\u2026 0:0")
    page.evaluate("window.FINISH({state: 'done', result: {base: 'http://localhost:5'}})")
    page.wait_for_timeout(100)
    assert page.evaluate(READ) is None


def test_with_no_start_in_flight_the_page_does_not_press_it(page):
    _load(page, "<!doctype html><meta charset=utf-8><style>" + build.CSS + "</style>"
                     + "<script>window.ACTIVE = {action: 'cue-drive', state: 'running'};</script>"
                     + STUB + build.runtime_html(RUNTIME) + build.APP_ENV_JS)
    page.wait_for_timeout(300)
    assert "demo-env" not in page.evaluate("window.RAN")


STATE = "document.querySelector('.appenv-state')"


def _phase(page, doc):
    _compose(page, doc)
    return page.evaluate(f"[{STATE}.textContent, {STATE}.dataset.tip]")


def test_the_pill_names_the_step_the_start_is_on_and_how_long_it_has_taken(page):
    """16 Oct 2026: "Starting…" stood through Docker Desktop booting and a first build,
    and read as stuck. Each step now has its word, a clock, and on hover why it takes time
    and the last line the command printed."""
    _start(page)
    text, tip = _phase(page, {"state": "running", "docker": "starting",
                              "images": [], "containers": []})
    assert text.startswith("Starting Docker Desktop\u2026 0:0")
    assert "was not running" in tip and tip.endswith("Last output: building")
    text, _ = _phase(page, {"state": "running", "docker": "up", "images": [],
                            "containers": []})
    assert text.startswith("Preparing\u2026")
    text, tip = _phase(page, {"state": "running", "containers": [], "images": [
        {"image": "petclinic-env-backend:abc", "state": "Built"},
        {"image": "petclinic-env-frontend:abc", "state": "Building"}]})
    assert text.startswith("Building images 1/2\u2026") and "1 of 2 images built" in tip
    text, _ = _phase(page, {"state": "running", "containers": [], "images": [
        {"image": "petclinic-env-backend:abc", "state": "Built"}]})
    assert text.startswith("Creating containers\u2026")
    text, _ = _phase(page, {"state": "running", "up": 1, "total": 2, "images": [],
                            "containers": [{"service": "backend", "light": "starting",
                                            "status": "Up 1s (health: starting)"},
                                           {"service": "db", "light": "up", "status": "Up"}]})
    assert text.startswith("Waiting for health 1/2\u2026")
    text, _ = _phase(page, {"state": "running", "up": 1, "total": 3, "images": [],
                            "containers": [{"service": "backend", "light": "starting",
                                            "status": "Created"},
                                           {"service": "db", "light": "up", "status": "Up"},
                                           {"service": "web", "light": "starting",
                                            "status": "Created"}]})
    assert text.startswith("Waiting for health 1/3\u2026"), "never back to Starting"
    text, _ = _phase(page, {"state": "running", "up": 2, "total": 2, "images": [],
                            "containers": [{"service": "backend", "light": "up", "status": "Up"},
                                           {"service": "db", "light": "up", "status": "Up"}]})
    assert text.startswith("Waiting for the address\u2026")
    was = page.evaluate(f"{STATE}.textContent")
    page.wait_for_function(f"{STATE}.textContent !== {json.dumps(was)}", timeout=3000)
    assert page.evaluate(f"{STATE}.textContent").startswith("Waiting for the address"), \
        "the clock ticks between polls, the step stays"
    page.evaluate("window.FINISH({state: 'failed', exit: 1, output: 'boom'})")
    page.wait_for_timeout(1300)
    assert page.evaluate(f"{STATE}.textContent") == "start failed", "the clock stops with the run"
