# Human Review for IntelliJ

The IntelliJ end of a [/human-review](https://github.com/victorrentea/human-review) page — the
twin of [`vscode-extension/`](../vscode-extension), speaking the same wire protocol, so
`serve-review.py` can hand a click to either editor.

- **A `File.java:49-51` reference opens in the project window that owns the file** (longest
  path wins across every open project), as a range: the lines selected and highlighted, the
  rest of the file muted until you click, move the caret or type. The window comes to the front.
- **A `human-review` item in the status bar** says whether this checkout's review is being
  served: green (served, on the reviewed commit), amber (served, checkout on another commit),
  grey (a review on disk, no server — click to start one and open the page). Hidden when the
  project has no `.human-review/review.html`.

Not yet (M2/M3): the reviewed-version check across windows (`/review-open`), the before/after
diff (`/open-diff`), the page in an embedded browser (`/open-url`), PR comment threads. Those
routes answer `501`.

## How it connects

The IDE listens on one random loopback port **per process** (IntelliJ hosts every project
window in one JVM, unlike VS Code's one extension host per window) and publishes
`{"app":"idea", port, token, pid}` in a `0600` file `~/.human-review/ide/idea-<pid>.json`,
deleted on exit. Only `127.0.0.1`, only callers sending the token in `x-relay-token`, and only
a short allowlist: `/ping`, `/editor-state`, `/open-file`, and `/command` with
`workbench.action.focusWindow`, `humanReview.status` or `revealInExplorer`.

## Install

Build, then **Settings → Plugins → ⚙ → Install Plugin from Disk…** →
`intellij-plugin/build/distributions/human-review-*.zip`.

```sh
cd intellij-plugin
./gradlew buildPlugin          # → build/distributions/human-review-0.1.0.zip
```

## Settings

**Settings → Tools → Human Review → serve-review.py**: absolute path to the script the status
item starts a server with. Empty: the copy installed with the `human-review` Claude Code plugin,
else `~/workspace/human-review`.

## Develop

```sh
./gradlew test                 # the pure parts: range spans, ownership, registry, status probe
./gradlew verifyPlugin         # against the same IC 2025.1 the build uses
./gradlew runIde --args=/path/to/a/checkout
```

`runIde` passes `-Didea.trust.all.projects=true`: the "Trust this project?" modal would
otherwise hold the EDT, and every bridge route that needs it would answer 503.
