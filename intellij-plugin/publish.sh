#!/bin/zsh
# Ships the plugin: hot-reloads it into Victor's running IntelliJ (deploy-local.sh), then
# uploads the same version to the JetBrains Marketplace. Run after every change to the plugin,
# with `pluginVersion` in gradle.properties already bumped — the Marketplace refuses a version
# it has seen.
#
# The token lives outside the repository, in ~/.claude/jetbrains-marketplace.env:
#   JETBRAINS_PUBLISH_TOKEN=perm-…   (plugins.jetbrains.com → avatar → My Tokens)
set -e
cd "${0:A:h}"

ENV=~/.claude/jetbrains-marketplace.env
[[ -f "$ENV" ]] || { echo "No $ENV — create a token at plugins.jetbrains.com → My Tokens, save it there as JETBRAINS_PUBLISH_TOKEN=…"; exit 1; }
set -a; source "$ENV"; set +a
[[ -n "$JETBRAINS_PUBLISH_TOKEN" ]] || { echo "JETBRAINS_PUBLISH_TOKEN is empty in $ENV"; exit 1; }

VERSION=$(sed -n 's/^pluginVersion *= *//p' gradle.properties)
# A reload that fails is not a reason to hold the upload back: say so and go on.
./deploy-local.sh || echo "⚠ deploy-local.sh exited $? — the running IntelliJ did not reload $VERSION; uploading anyway"
./gradlew publishPlugin -q
echo "✅ $VERSION uploaded to the Marketplace — JetBrains reviews it before it reaches anyone"
