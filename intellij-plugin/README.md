# Human Review for IntelliJ

The IntelliJ end of a [/human-review](https://github.com/victorrentea/human-review) page — the
twin of [`vscode-extension/`](../vscode-extension), speaking the same wire protocol, so
`serve-review.py` can hand a click to either editor.

- **A `File.java:49-51` reference opens in the project window that owns the file** (longest
  path wins across every open project), as a range: the lines selected and highlighted, the
  rest of the file muted until you click, move the caret or type. The window comes to the front.
- **A fix opens as a diff**: the file at the review's base commit on the left (read-only), the
  working tree on the right (editable), scrolled to the line the fix is about, in the project
  that owns the file. A ref git cannot resolve, a file unchanged since, a path no project owns:
  refused in a sentence the page shows, never a diff with an invented left half.
- **The reviewed version, or a plain no**: a reference on a page that carries its commit opens
  only where the file is the very blob that was reviewed — a project here, or another IntelliJ
  or VS Code window running the bridge (it is handed over). Edited since: an amber note on the
  line. Nowhere: a refusal with a prompt to copy for a coding agent.
- **Pages read off disk** reach the plugin through `jetbrains://idea/human-review/…` links
  (`open`, `diff`, `review-open`, the query of the VS Code extension's URI handler), which the
  page sends when the reader picked IntelliJ in the masthead earlier. `jetbrains://` is owned by
  JetBrains Toolbox, which hands it to the IntelliJ it manages: without Toolbox those clicks go
  nowhere.
- **A `human-review` item in the status bar** says whether this checkout's review is being
  served: green (served, on the reviewed commit), amber (served, checkout on another commit),
  grey (a review on disk, no server — click to start one and open the page). Hidden when the
  project has no `.human-review/review.html`.

Not yet (M3): the page in an embedded browser (`/open-url` answers `501`) and PR comment threads
(`comment: true` is accepted and ignored).

## How it connects

The IDE listens on one random loopback port **per process** (IntelliJ hosts every project
window in one JVM, unlike VS Code's one extension host per window) and publishes
`{"app":"idea", port, token, pid}` in a `0600` file `~/.human-review/ide/idea-<pid>.json`,
deleted on exit. Only `127.0.0.1`, only callers sending the token in `x-relay-token`, and only
a short allowlist: `/ping`, `/editor-state`, `/open-file`, `/open-diff`, `/review-open`, and
`/command` with `workbench.action.focusWindow`, `humanReview.status` or `revealInExplorer`.

## Install

Build, then **Settings → Plugins → ⚙ → Install Plugin from Disk…** →
`intellij-plugin/build/distributions/human-review-0.2.0.zip`, and restart the IDE when asked.

```sh
cd intellij-plugin
./gradlew buildPlugin          # → build/distributions/human-review-0.2.0.zip
```

## Settings

**Settings → Tools → Human Review → serve-review.py**: absolute path to the script the status
item starts a server with. Empty: the copy installed with the `human-review` Claude Code plugin,
else `~/workspace/human-review`.

## Develop

```sh
./gradlew test                 # the pure parts, plus a headless IDE (HeadlessIdeTest): the bridge's
                               # routes against a project with a git repo, the diff viewer replaced
                               # by a recorder, jetbrains:// links through the platform's own entry
./gradlew verifyPlugin         # against the same IC 2025.1 the build uses
./gradlew runIde --args=/path/to/a/checkout
```

Tests never touch `~/.human-review/ide/`: `-Dhuman-review.registry.dir` points the registry at
`build/test-registry`, a test bridge is started only by the test that wants one, and no window
is raised in a test run.

`runIde` passes `-Didea.trust.all.projects=true`: the "Trust this project?" modal would
otherwise hold the EDT, and every bridge route that needs it would answer 503.
