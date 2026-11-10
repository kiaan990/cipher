#!/bin/zsh
# Puts Cipher's settings into Railway's private Variables for the linked project.
# Your API keys are read from .env and sent straight to Railway; nothing is printed.
# You choose the sign-in password here (typing is hidden).
set -e
cd "$(dirname "$0")/.."

if ! command -v railway >/dev/null; then
  echo "Install the Railway CLI first:  brew install railway"
  exit 1
fi
if [ ! -f .env ]; then
  echo "No .env file found in $(pwd)."
  exit 1
fi

# Read KEY=value lines from .env without running anything in it.
typeset -A vars
while IFS= read -r line || [ -n "$line" ]; do
  [[ "$line" =~ '^[[:space:]]*#' || "$line" != *=* ]] && continue
  key="${line%%=*}"; key="${key//[[:space:]]/}"
  value="${line#*=}"; value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
  case "$key" in
    ANTHROPIC_API_KEY|DEEPGRAM_API_KEY|ELEVENLABS_API_KEY|ELEVENLABS_VOICE_ID|ANTHROPIC_MODEL|DEEPGRAM_VOICE|TTS_PROVIDER)
      [ -n "$value" ] && vars[$key]="$value" ;;
  esac
done < .env

for required in ANTHROPIC_API_KEY DEEPGRAM_API_KEY; do
  if [ -z "${vars[$required]}" ]; then
    echo "$required is missing from .env."
    exit 1
  fi
done

echo "Choose the password you'll use to sign in to Cipher (at least 10 characters)."
while true; do
  read -rs "pw?Password: "; echo
  read -rs "pw2?Same again: "; echo
  if [ ${#pw} -lt 10 ]; then echo "Too short, try again."; continue; fi
  if [ "$pw" != "$pw2" ]; then echo "They don't match, try again."; continue; fi
  break
done

args=()
for k v in "${(@kv)vars}"; do args+=(--set "$k=$v"); done
args+=(--set "APP_PASSWORD=$pw" --set "DATA_DIR=/data" --set "HOSTED=true")

railway variables "${args[@]}" --skip-deploys >/dev/null
echo "Saved ${#vars} API settings and your password to Railway (values not shown)."
