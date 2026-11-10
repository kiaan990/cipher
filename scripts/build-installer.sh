#!/bin/zsh
# Builds build/Cipher Installer.dmg: everything needed to install Cipher on another
# Mac (AirDrop it). Contains your API keys from .env, so keep it private.
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OUT="$ROOT/build"
STAGE="$OUT/stage"
PAYLOAD="$STAGE/payload"
DMGDIR="$STAGE/dmg"
rm -rf "$OUT" && mkdir -p "$PAYLOAD" "$DMGDIR"

echo "1/6 Building the server…"
npx tsc -p tsconfig.json --noEmit false --outDir "$PAYLOAD/server" --rootDir server

echo "2/6 Copying the app…"
rsync -a public "$PAYLOAD/"
rsync -a --exclude pairing.json chrome-extension "$PAYLOAD/"
cp package.json README.md "$PAYLOAD/"
[ -f .env ] && cp .env "$PAYLOAD/.env" || echo "   (no .env: the app will ask for keys)"

echo "3/6 Packing only the libraries it uses…"
rsync -a node_modules "$PAYLOAD/" \
  --exclude ".bin" --exclude "typescript" --exclude "@types" --exclude "tsx" --exclude "esbuild" --exclude "@esbuild" \
  --exclude "onnxruntime-web" \
  --exclude "*.map" --exclude "*.d.ts" --exclude "*.d.mts" --exclude "*.d.cts"
# The on-device AI runtime (Smart Turn, voice match): keep only the Mac builds.
O="$PAYLOAD/node_modules/onnxruntime-node/bin"
find "$O" -mindepth 2 -maxdepth 2 -type d ! -name darwin -exec rm -rf {} +
T="$PAYLOAD/node_modules/@huggingface/transformers"
find "$T" -mindepth 1 -maxdepth 1 ! -name dist ! -name package.json -exec rm -rf {} +
# Browser build (object detection) and the Node build (Smart Turn, voice match).
find "$T/dist" -type f ! -name "transformers.min.js" ! -name "transformers.node.mjs" ! -name "ort-wasm-simd-threaded.jsep.*" -delete
H="$PAYLOAD/node_modules/three"
find "$H" -mindepth 1 -maxdepth 1 ! -name build ! -name examples ! -name package.json -exec rm -rf {} +
find "$H/examples" -mindepth 1 -maxdepth 1 ! -name jsm -exec rm -rf {} +

echo "4/6 Building the Cipher app…"
mkdir -p "$PAYLOAD/mac-app"
"$ROOT/scripts/make-mac-app.sh" "$PAYLOAD/mac-app" >/dev/null

echo "5/6 Checking it starts…"
TEST_DATA="$(mktemp -d)"
PORT=3019 OPEN_BROWSER=false DATA_DIR="$TEST_DATA" node "$PAYLOAD/server/index.js" > "$OUT/selftest.log" 2>&1 &
PID=$!
ok=""
for i in {1..30}; do curl -s -m 1 -o /dev/null http://localhost:3019/healthz && { ok=1; break; }; sleep 0.5; done
for f in / /app.js /vendor/three/build/three.module.min.js /vendor/transformers/transformers.min.js /vendor/transformers/ort-wasm-simd-threaded.jsep.wasm /vendor/noise/index.js /vendor/noise/rnnoise_simd.wasm /vendor/noise/rnnoise/workletProcessor.js; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3019$f")
  [ "$code" = 200 ] || { echo "   self-test failed: $f -> $code"; ok=""; }
done
kill $PID 2>/dev/null; wait $PID 2>/dev/null || true; rm -rf "$TEST_DATA" || true
# The on-device AI runtime must load from the packed libraries alone.
(cd "$PAYLOAD" && node -e 'Promise.all([import("onnxruntime-node"), import("@huggingface/transformers")]).then(([o, t]) => { if (!t.WavLMForXVector || !o.InferenceSession) process.exit(1); })') \
  || { echo "   self-test failed: on-device AI runtime doesn't load"; ok=""; }
[ -n "$ok" ] || { echo "Self-test failed, see build/selftest.log"; exit 1; }
rm -f "$PAYLOAD/chrome-extension/pairing.json"

echo "6/6 Making the installer and disk image…"
INST="$DMGDIR/Install Cipher.app"
osacompile -o "$INST" "installer/Install Cipher.applescript"
cp installer/install.sh "$INST/Contents/Resources/install.sh"
ditto "$PAYLOAD" "$INST/Contents/Resources/payload"
cp "$PAYLOAD/mac-app/Cipher.app/Contents/Resources/applet.icns" "$INST/Contents/Resources/applet.icns"
rm -f "$INST/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$INST/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" "$INST/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet" "$INST/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.voiceorb.installer" "$INST/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.voiceorb.installer" "$INST/Contents/Info.plist"
cp installer/README.txt "$DMGDIR/How to install.txt"
# Diagnostics: on the disk image (helper hidden) and inside the installed app.
cp "installer/Cipher Diagnostics.command" "$DMGDIR/"
cp installer/diagnose-e2e.mjs "$DMGDIR/.diagnose-e2e.mjs"
mkdir -p "$INST/Contents/Resources/payload/tools"
cp "installer/Cipher Diagnostics.command" installer/diagnose-e2e.mjs "$INST/Contents/Resources/payload/tools/"
chmod +x "$DMGDIR/Cipher Diagnostics.command" "$INST/Contents/Resources/payload/tools/Cipher Diagnostics.command"
codesign --force --deep --sign - "$INST" 2>/dev/null
hdiutil create -volname "Cipher" -srcfolder "$DMGDIR" -ov -format UDZO "$OUT/Cipher Installer.dmg" >/dev/null
rm -rf "$STAGE"
echo "Done: $OUT/Cipher Installer.dmg ($(du -h "$OUT/Cipher Installer.dmg" | cut -f1))"
