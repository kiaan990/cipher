#!/bin/zsh
# Builds the vision test scenes (tests/review/vision-scenes/*.jpg) from the stock pictures
# that ship with macOS, at the size the page sends camera stills (960 px wide JPEG).
# The scenes are not committed; run this once before vision.mjs.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"; OUT="$HERE/vision-scenes"; W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
mkdir -p "$OUT" "$W/png"; cd "$W"
for f in Animals/Owl Animals/Zebra Animals/Penguin Animals/Eagle Animals/Parrot Flowers/Sunflower "Flowers/Red Rose" Sports/Basketball Sports/Tennis Sports/Soccer Sports/Golf Sports/Bowling; do
  sips -s format jpeg -Z 600 "/Library/User Pictures/$f.heic" --out "$(basename "$f" | tr -d ' ').jpg" >/dev/null 2>&1
done
css='html,body{margin:0;width:1280px;height:720px;overflow:hidden;font-family:Helvetica,Arial,sans-serif}'
room='background:linear-gradient(135deg,#6b6f76,#3d4046 60%,#2a2c30)'
card='<div style="position:absolute;left:400px;top:150px;width:480px;height:420px;background:#f6f4ee;transform:rotate(-3deg);box-shadow:0 8px 30px #0008;padding:22px;box-sizing:border-box;color:#111">
<div style="font-size:37px;font-weight:700">ORCHID 4471</div><div style="font-size:27px">Meet at gate B19 on Friday</div>
<div style="font-size:21px">Reference code: TULIP-8823-KX</div><div style="font-size:16px">Take two tablets with water at 7:45 each morning</div>
<div style="font-size:13px">Warranty expires 14 March 2029, serial number QF-55291-ZD</div>
<div style="font-size:11px">Contains wheat, soy and traces of hazelnut. Store below 25 degrees.</div>
<div style="font-size:8px">Batch 77104 packed in Rotterdam. Call 0800 555 0142 for help with this product.</div></div>'
mk(){ echo "<html><head><style>$css</style></head><body style=\"$room\">$2</body></html>" > "$1.html"; }
one(){ echo "<div style='position:absolute;inset:0;$2'><img src='$1.jpg' style='position:absolute;left:440px;top:160px;width:400px;height:400px;object-fit:cover;border-radius:12px'></div>"; }
mk text "<div style='position:absolute;inset:0'>$card</div>"
mk text-dim "<div style='position:absolute;inset:0;filter:brightness(0.18) contrast(0.8)'>$card</div><div style='position:absolute;inset:0;background:#000;opacity:0.25'></div>"
mk text-blur "<div style='position:absolute;inset:0;filter:blur(2.5px)'>$card</div>"
mk owl "$(one Owl)"; mk zebra "$(one Zebra)"; mk sunflower "$(one Sunflower)"; mk basketball "$(one Basketball)"
mk owl-dark "$(one Owl 'filter:brightness(0.07)')"; mk owl-verydark "$(one Owl 'filter:brightness(0.025)')"
grid=""; i=0
for n in Owl Tennis Sunflower Zebra Golf RedRose Penguin Soccer Eagle Basketball Parrot Bowling Tennis Owl Golf Sunflower Soccer Zebra Basketball RedRose Bowling Eagle Soccer Tennis; do
  x=$(( (i%6)*206 + 30 )); y=$(( (i/6)*172 + 18 )); r=$(( (i*37)%21 - 10 ))
  grid="$grid<img src='$n.jpg' style='position:absolute;left:${x}px;top:${y}px;width:150px;height:150px;object-fit:cover;transform:rotate(${r}deg);box-shadow:0 2px 8px #0009'>"; i=$((i+1))
done
mk clutter "$grid"   # Quick Look renders 1024 px wide, so the sixth column is cut off: 20 pictures show (4 rows of 5)
for h in *.html; do qlmanage -t -s 1280 -o "$W/png" "$h" >/dev/null 2>&1; done
for p in "$W"/png/*.html.png; do
  n=$(basename "$p" .html.png)
  sips --cropOffset 1 1 -c 900 1280 "$p" --out "$W/c.png" >/dev/null 2>&1
  sips -z 675 960 -s format jpeg -s formatOptions 80 "$W/c.png" --out "$OUT/$n.jpg" >/dev/null 2>&1
done
ls "$OUT"
