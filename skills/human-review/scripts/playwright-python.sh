#!/usr/bin/env bash
# Print the path of a Python interpreter that can `import playwright` and has Chromium,
# provisioning it on first use. Shared by publish-demo.sh (the README tour) and
# publish-demo-shots.sh (the screenshot gallery) and by run-steps.py (ds-audit, the trace
# shot, the C4 views), so they all keep one venv between them.
#
# Python Playwright is not something a training laptop has lying around, and installing it
# into the system interpreter is not ours to do. One throwaway venv, provisioned once and
# reused on every later run. Progress goes to stderr; stdout is only the interpreter path.
set -euo pipefail

VENV="${HUMAN_REVIEW_SHOTS_VENV:-$HOME/.cache/human-review/shots-venv}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "playwright-python: provisioning Playwright in $VENV (first run only)…" >&2
  mkdir -p "$(dirname "$VENV")"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip >&2
  "$VENV/bin/python" -m pip install --quiet playwright numpy pillow pygments >&2
fi
# numpy, Pillow and Pygments are for ds-audit.py, which runs on this interpreter too: it
# measures pixel churn on its screenshots and highlights the code it quotes (21 Oct 2026: a
# venv made for the tour had none of the three).
if ! "$VENV/bin/python" -c "import playwright, numpy, PIL, pygments" >/dev/null 2>&1; then
  "$VENV/bin/python" -m pip install --quiet playwright numpy pillow pygments >&2
fi
# `install` is idempotent and returns in about a second when the browser is already in the
# shared ms-playwright cache, so it is cheaper to always run it than to guess whether the
# revision this playwright wants happens to be the one on disk.
"$VENV/bin/python" -m playwright install chromium >&2

echo "$VENV/bin/python"
