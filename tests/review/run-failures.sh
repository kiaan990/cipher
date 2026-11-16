#!/bin/zsh
# Runs the app five times from a throwaway copy, each with one thing broken, and records
# what the user would see and hear (failures.mjs). Nothing in the real app or its .env is
# touched; the copies (which contain the real keys) are deleted at the end.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"; trap 'lsof -ti tcp:3121 | xargs kill 2>/dev/null; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/app" "$WORK/data"
cp -R "$ROOT/server" "$ROOT/public" "$ROOT/package.json" "$ROOT/tsconfig.json" "$WORK/app/"
ln -s "$ROOT/node_modules" "$WORK/app/node_modules"
ln -s "$ROOT/data/models" "$WORK/data/models"
run() { # label, sed expression applied to .env, extra env
  local label="$1" edit="$2" extra="${3:-}"
  sed -E "$edit" "$ROOT/.env" > "$WORK/app/.env"; chmod 600 "$WORK/app/.env"
  (cd "$WORK/app" && env PORT=3121 DATA_DIR="$WORK/data" OPEN_BROWSER=false MUSE_LINK=off TTS_PROVIDER="${TTS:-deepgram}" ${=extra} node node_modules/tsx/dist/cli.mjs server/index.ts > "$WORK/$label.log" 2>&1 &)
  sleep 7
  echo "=== $label ==="
  PORT=3121 node "$ROOT/tests/review/failures.mjs" "$label" 2>&1 | sed -E 's#https?://[^ "]+#[url]#g'
  echo "--- server log (errors only) ---"
  grep -iE "error|fail|couldn|can't|refus|invalid|unreach|missing|out of credits|Cloud server|Voice:" "$WORK/$label.log" | sed -E 's#https?://[^ "]+#[url]#g' | cut -c25-260 | sort | uniq -c | sort -rn | head -8
  lsof -ti tcp:3121 | xargs kill 2>/dev/null; sleep 1
}
run "model-key-rejected" 's/^(ANTHROPIC_API_KEY=).*/\1sk-ant-invalid-for-review/'
run "model-unreachable" 's/^(#nothing)//' "ANTHROPIC_BASE_URL=http://127.0.0.1:9"
run "speech-recognition-key-rejected" 's/^(DEEPGRAM_API_KEY=).*/\1invalid-for-review/'
TTS=auto run "voice-key-rejected" 's/^(ELEVENLABS_API_KEY=).*/\1invalid-for-review/'
run "cloud-server-unreachable" 's#^(KIAAN_MCP_URL=).*#\1https://127.0.0.1:9/mcp#'
