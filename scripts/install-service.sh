#!/bin/zsh
# Runs Cipher in the background on this Mac: starts when you log in, restarts
# itself if it stops, no terminal needed. Undo with scripts/uninstall-service.sh.
set -e
cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
LABEL="com.voiceorb.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
NODE="$(command -v node)"
[ -x "$NODE" ] || { echo "Node.js not found. Install it from nodejs.org first."; exit 1; }
[ -f node_modules/tsx/dist/cli.mjs ] || npm install
mkdir -p logs "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NODE</string>
    <string>$APP_DIR/node_modules/tsx/dist/cli.mjs</string>
    <string>server/index.ts</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>OPEN_BROWSER</key><string>false</string>
    <key>PATH</key><string>$(dirname "$NODE"):/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$APP_DIR/logs/server.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/logs/server.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
echo "Cipher is now running in the background at http://localhost:3000"
echo "It starts when you log in and restarts itself if it stops. Log: $APP_DIR/logs/server.log"
