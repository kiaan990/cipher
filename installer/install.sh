#!/bin/zsh
# Installs (or updates) Cipher for this Mac user. Run by "Install Cipher.app".
#   exit 3: Node.js missing or too old
set -e
SRC="$(cd "$(dirname "$0")" && pwd)/payload"
HOME_DIR="$HOME/Library/Application Support/Voice Orb"
APP_DIR="$HOME_DIR/app"
DATA_DIR="$HOME_DIR/data"
LOG_DIR="$HOME_DIR/logs"
LABEL="${VOICE_ORB_LABEL:-com.voiceorb.server}"   # overridable for testing
PORT="${VOICE_ORB_PORT:-3000}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# ---- Node.js (needs 20.18 or newer)
find_node() {
  local c
  for c in "$(/bin/zsh -lic 'command -v node' 2>/dev/null | tail -1)" /opt/homebrew/bin/node /usr/local/bin/node $HOME/.nvm/versions/node/*/bin/node(N) $HOME/.volta/bin/node; do
    [ -x "$c" ] || continue
    local v; v="$("$c" -p 'process.versions.node' 2>/dev/null)" || continue
    local major="${v%%.*}" rest="${v#*.}"; local minor="${rest%%.*}"
    if [ "$major" -gt 20 ] || { [ "$major" -eq 20 ] && [ "$minor" -ge 18 ]; }; then echo "$c"; return 0; fi
  done
  return 1
}
NODE="$(find_node)" || { echo "Cipher needs Node.js 20.18 or newer (nodejs.org)."; exit 3; }

# ---- stop older copies (e.g. "npm start" from a zip in Downloads), which would hold the port
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
for pid in $(lsof -tiTCP:$PORT -sTCP:LISTEN 2>/dev/null); do
  if ps -o command= -p "$pid" | grep -qE "server/index\.(ts|js)|voice-orb"; then
    echo "Stopping an older Cipher (pid $pid)"
    kill "$pid" 2>/dev/null || true
  fi
done
pkill -f "voice-orb.*tsx.*server/index.ts" 2>/dev/null || true
sleep 1

# ---- copy the app (keeps data/ and any newer .env from a previous install)
mkdir -p "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
[ -f "$APP_DIR/.env" ] && cp "$APP_DIR/.env" "$HOME_DIR/.env.previous" || true
rsync -a --delete --exclude "chrome-extension/pairing.json" "$SRC/" "$APP_DIR/"
chmod 600 "$APP_DIR/.env" 2>/dev/null || true
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true

# ---- background service: starts at login, restarts itself if it stops
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$NODE</string><string>$APP_DIR/server/index.js</string></array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>OPEN_BROWSER</key><string>false</string>
    <key>DATA_DIR</key><string>$DATA_DIR</string>
    <key>PORT</key><string>$PORT</string>
    <key>PATH</key><string>$(dirname "$NODE"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/server.log</string>
</dict>
</plist>
PLIST
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"

# ---- the Cipher app (Spotlight, Launchpad, Dock)
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Cipher.app"
ditto "$APP_DIR/mac-app/Cipher.app" "$HOME/Applications/Cipher.app"
xattr -dr com.apple.quarantine "$HOME/Applications/Cipher.app" 2>/dev/null || true
if [ -z "$VOICE_ORB_TEST" ] && ! defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Cipher.app"; then
  defaults write com.apple.dock persistent-apps -array-add "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>file://${HOME// /%20}/Applications/Cipher.app/</string><key>_CFURLStringType</key><integer>15</integer></dict></dict></dict>"
  killall Dock 2>/dev/null || true
fi

# ---- wait for it to come up
for i in {1..40}; do
  curl -s -m 1 -o /dev/null "http://localhost:$PORT/healthz" && { echo "installed"; exit 0; }
  sleep 0.5
done
echo "Installed, but the service didn't start. Log: $LOG_DIR/server.log"
exit 4
