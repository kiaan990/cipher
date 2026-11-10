#!/bin/zsh
# Cipher diagnostics: checks this Mac's Cipher and writes a report to the Desktop.
# Double-click to run. Never includes API keys or passwords.
HERE="$(cd "$(dirname "$0")" && pwd)"
REPORT="$HOME/Desktop/Cipher Diagnostics $(date +%Y-%m-%d_%H%M).txt"
TMP="$(mktemp -d)"

main() {
line() { print -- "\n== $1 =="; }
scrub() { sed -E 's/(sk-ant-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+/\1…/g; s/([A-Fa-f0-9]{6})[A-Fa-f0-9]{26,}/\1…/g; s/(Token |xi-api-key: )[^ ]+/\1…/g'; }

print "Cipher diagnostics — $(date)"
print "(This takes about a minute. It makes two short test requests to Claude.)"

line "This Mac"
print "Model:   $(sysctl -n hw.model)   Chip: $(sysctl -n machdep.cpu.brand_string)"
print "Memory:  $(( $(sysctl -n hw.memsize) / 1073741824 )) GB   macOS $(sw_vers -productVersion)"
batt="$(pmset -g batt | sed -n 2p | sed 's/^ *-InternalBattery-[0-9]* *//; s/(id=[0-9]*)//')"
print "Power:   ${batt:-plugged in (no battery)}   source: $(pmset -g batt | head -1 | sed "s/Now drawing from //; s/'//g")"
print "Low Power Mode: $(pmset -g | awk '/lowpowermode/ {print ($2==1?"ON (slows the Mac down)":"off")}')"
pmset -g therm 2>/dev/null | grep -iE "warning|limit" | sed 's/^/Thermal: /'
print "CPU load: $(sysctl -n vm.loadavg)"
print "Busiest apps now:"; ps -Aceo pcpu,comm -r | sed -n 2,6p | sed 's/^/   /'

line "Node.js"
for n in "$(/bin/zsh -lic 'command -v node' 2>/dev/null | tail -1)" /opt/homebrew/bin/node /usr/local/bin/node; do
  [ -x "$n" ] && print "$n  →  $("$n" -v)"
done | sort -u

line "Cipher copies on this Mac"
for d in "$HOME/Library/Application Support/Voice Orb/app" "$HOME/voice-orb" "$HOME/Downloads/voice-orb" "$HOME/Desktop/voice-orb"; do
  [ -d "$d" ] && print "$d  (changed $(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$d"))"
done
print "\nBackground service:"
launchctl print "gui/$(id -u)/com.voiceorb.server" 2>/dev/null | grep -E "^\t(state|pid|program|last exit code) =" | sed 's/^\t/   /' || print "   not installed"
print "\nWhat's answering on port 3000:"
lsof -nP -iTCP:3000 -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print "   pid " $2 " (" $1 ")"}' | sort -u
for p in $(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null); do print "   pid $p runs: $(ps -o command= -p $p | cut -c1-160)"; done
# (the TypeScript runner's launcher process "tsx/dist/cli.mjs" belongs to the same server)
other=$(pgrep -fl "server/index\.(ts|js)" | grep -v "tsx/dist/cli.mjs" | wc -l | tr -d ' ')
print "Cipher server processes running: $other  (more than 1 means an old copy is also running)"
pgrep -fl "server/index\.(ts|js)" | cut -c1-160 | sed 's/^/   /'

line "Cipher status"
st=$(curl -s -m 3 -w '\n(answered in %{time_total}s)' http://127.0.0.1:3000/api/status)
print "${st:-NOT RESPONDING on http://127.0.0.1:3000}"
print "\nPermissions: $(curl -s -m 40 -H 'x-voice-orb: 1' http://127.0.0.1:3000/api/permissions || echo 'unknown (older version)')"

line "Network to the AI services (connect · secure · first byte)"
for u in https://api.anthropic.com/v1/models https://api.deepgram.com/v1/projects https://api.elevenlabs.io/v1/models; do
  for i in 1 2 3; do
    curl -s -o /dev/null -m 10 -w "$(print -- $u | cut -d/ -f3)  %{time_connect}s · %{time_appconnect}s · %{time_starttransfer}s\n" "$u" || print "$u  FAILED"
  done
done
print "\nWi-Fi: $(/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I 2>/dev/null | awk -F': ' '/ agrCtlRSSI|lastTxRate/ {printf "%s=%s ", $1, $2}' || true)"
if command -v networkQuality >/dev/null; then
  print "Speed test (15 s):"; networkQuality -s -M 15 2>/dev/null | grep -E "Uplink capacity|Downlink capacity|Responsiveness|Idle Latency" | sed 's/^/   /'
fi

line "Live test (two spoken questions through this Mac's Cipher)"
if curl -s -m 2 -o /dev/null http://127.0.0.1:3000/healthz; then
  say -o "$TMP/q1.wav" --data-format=LEI16@16000 "Cipher, what is the capital of France?"
  say -o "$TMP/q2.wav" --data-format=LEI16@16000 "Tell me one short fun fact."
  NODE="$(/bin/zsh -lic 'command -v node' 2>/dev/null | tail -1)"; [ -x "$NODE" ] || NODE=/opt/homebrew/bin/node
  E2E="$HERE/diagnose-e2e.mjs"; [ -f "$E2E" ] || E2E="$HERE/.diagnose-e2e.mjs"
  "$NODE" "$E2E" "$TMP" 2>&1 | scrub
else
  print "skipped: Cipher isn't running"
fi

line "Recent log (timings, smoothness, errors)"
for log in "$HOME/Library/Application Support/Voice Orb/logs/server.log" "$HOME/voice-orb/logs/server.log"; do
  [ -f "$log" ] || continue
  print "$log:"
  grep -E "latency|\[perf\]|error|Error|ERROR|warn|refused|failed|Deepgram|ElevenLabs|Voice:|running|chrome\]" "$log" | grep -v "memory\]" | uniq | tail -40 | scrub | sed 's/^/   /'
done

}

main 2>&1 | tee "$REPORT"
rm -rf "$TMP"
print "\n== Done ==\nReport saved to your Desktop:\n  $REPORT\n\nSend it to your Mac mini with AirDrop (right-click → Share → AirDrop)."
open -R "$REPORT"
