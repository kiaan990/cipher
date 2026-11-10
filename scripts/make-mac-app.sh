#!/bin/zsh
# Builds "Cipher.app" into ~/Applications (open it from Spotlight, Launchpad or the Dock).
set -e
cd "$(dirname "$0")/.."
# Optional argument: folder to build into (default ~/Applications).
DEST="${1:-$HOME/Applications}"
APP="$DEST/Cipher.app"
TMP="$(mktemp -d)"
rm -rf "$APP"
mkdir -p "$DEST"
osacompile -o "$APP" mac-app/VoiceOrb.applescript
# Icon: every size macOS asks for, from the 1024 px drawing.
mkdir -p "$TMP/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s mac-app/icon.png --out "$TMP/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) mac-app/icon.png --out "$TMP/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/icon.iconset" -o "$APP/Contents/Resources/applet.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleName Cipher" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.voiceorb.launcher" "$APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.voiceorb.launcher" "$APP/Contents/Info.plist"
# Use our icon (newer macOS prefers Assets.car's default script icon otherwise).
rm -f "$APP/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" "$APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet" "$APP/Contents/Info.plist"
# Re-sign after editing, so macOS doesn't call it damaged.
codesign --force --deep --sign - "$APP" 2>/dev/null
touch "$APP"
rm -rf "$TMP"
echo "Built $APP"
