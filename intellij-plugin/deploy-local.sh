#!/bin/zsh
# Hot-redeploys this plugin into the running IntelliJ, no restart. Adapted from
# ~/workspace/confluent-intellij/deploy-local.sh.
#
# Needs -Didea.auto.reload.plugins=true in idea.vmoptions (Help → Edit Custom VM Options…): the
# IDE then reloads a loaded plugin when one of its jars changes *content* (a new file name is
# ignored), so the jar keeps the file name the IDE already has and only its bytes change.
# The plugin must be installed once from disk first (Settings → Plugins → ⚙ → Install Plugin
# from Disk… → build/distributions/human-review-<version>.zip).
#
# IDE_CONFIG=… picks the IDE's config directory; by default the newest IntelliJIdea* that has
# this plugin installed.
set -e
cd "${0:A:h}"

PLUGIN_DIR=human-review          # the zip's top folder: pluginName in gradle.properties
VERSION=$(sed -n 's/^pluginVersion *= *//p' gradle.properties)
BUILT=build/libs/human-review-$VERSION.jar

if [[ -z "$IDE_CONFIG" ]]; then
  for d in ~/Library/Application\ Support/JetBrains/IntelliJIdea*(N/On); do
    [[ -d "$d/plugins/$PLUGIN_DIR/lib" ]] && { IDE_CONFIG=$d; break; }
  done
fi
[[ -n "$IDE_CONFIG" && -d "$IDE_CONFIG/plugins/$PLUGIN_DIR/lib" ]] || {
  echo "Human Review is not installed in any IntelliJIdea* config — install the zip from disk once:"
  echo "  ./gradlew buildPlugin, then Settings → Plugins → ⚙ → Install Plugin from Disk… → build/distributions/human-review-$VERSION.zip"
  exit 1
}
LIB="$IDE_CONFIG/plugins/$PLUGIN_DIR/lib"
# The installed jar's own file name (not the searchable-options one): a different name is ignored.
JAR=$(cd "$LIB" && print -l human-review-*.jar(N) | grep -v searchableOptions | head -1)
[[ -n "$JAR" ]] || { echo "No human-review-*.jar in $LIB — install the zip from disk once"; exit 1; }
TARGET="$LIB/$JAR"
LOG=~/Library/Logs/JetBrains/${IDE_CONFIG:t}/idea.log
grep -q -- '-Didea.auto.reload.plugins=true' "$IDE_CONFIG/idea.vmoptions" 2>/dev/null ||
  echo "⚠ -Didea.auto.reload.plugins=true is not in $IDE_CONFIG/idea.vmoptions: IntelliJ will not notice the new jar"

# buildSearchableOptions boots a headless IDE and is the slow step; a stale index is harmless.
./gradlew buildPlugin -x test -x buildSearchableOptions -q
[[ -f "$BUILT" ]] || { echo "Built jar not found: $BUILT"; exit 1; }

LOG_LINES=$( [[ -f "$LOG" ]] && wc -l < "$LOG" || echo 0 )
# Never overwrite in place: the loaded plugin's classloader still reads the old jar by offset,
# and a rewritten file gives it ZipExceptions → ClassNotFound → a half-dead plugin.
# A rename swaps the path to a new file while the old one stays intact for whoever has it open.
STAGED="${TARGET:h:h}/$JAR.tmp"   # outside lib/ so the IDE never sees it, same volume so mv is a rename
cp "$BUILT" "$STAGED"
mv -f "$STAGED" "$TARGET"
echo "Copied $BUILT over $JAR (${IDE_CONFIG:t}) — waiting for IntelliJ to reload it (click into IntelliJ if nothing happens)…"

for i in {1..60}; do
  NEW_LOG=$(tail -n +$((LOG_LINES + 1)) "$LOG" 2>/dev/null)
  if grep -q -i 'failed to unload' <<< "$NEW_LOG"; then
    echo "❌ IntelliJ could not unload the plugin — restart IntelliJ to pick up the change"
    exit 3
  fi
  # `- load plugin …`, anchored: `- unload plugin 'Human Review'` comes first and must not match.
  if grep -q "^- load plugin 'Human Review'" <<< "$NEW_LOG"; then
    echo "✅ Reloaded live in IntelliJ after ${i}s ($(grep "^- load plugin 'Human Review'" <<< "$NEW_LOG" | tail -1 | sed 's/^- load plugin //'))"
    exit 0
  fi
  sleep 1
done
echo "No reload line in $LOG after 60s"
exit 2
