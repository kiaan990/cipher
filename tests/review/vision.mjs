// Vision: what Cipher gets right and wrong from a camera still, and how fast.
// Stills are sent exactly as the page sends them (a 960 px JPEG with the question), but
// they are rendered test scenes built from stock photos, not frames from a real camera:
// no lens blur, no motion, no real low-light sensor noise, and the in-browser object
// detector is not running. Usage: PORT=3111 node tests/review/vision.mjs
import fs from "node:fs";
import { connect, typed, sleep, save, stats, PORT } from "./lib.mjs";
const dir = new URL("./vision-scenes/", import.meta.url).pathname;
const jpeg = (n) => fs.readFileSync(`${dir}${n}.jpg`).toString("base64");
const out = { scenes: [], overTime: null, speed: null };
async function look(c, scene, question) {
  c.send({ type: "vision", enabled: true });
  if (scene) c.send({ type: "vision_still", jpeg: jpeg(scene) });
  await sleep(150);
  return typed(c, question);
}
const TEXT = [["35 px", /4471/], ["25 px", /B\s?19/i], ["20 px", /8823/], ["15 px", /7[:.]45|seven forty.?five/i], ["12 px", /55291/], ["10 px", /hazelnut/i], ["7.5 px", /77104|0142/]];
const cases = [
  ["text", "Read me everything written on the card I'm holding up, line by line.", (r) => TEXT.map(([size, re]) => `${size}:${re.test(r) ? "read" : "MISSED"}`).join("  ")],
  ["text-dim", "Read me everything written on the card I'm holding up, line by line.", (r) => TEXT.map(([size, re]) => `${size}:${re.test(r) ? "read" : "MISSED"}`).join("  ")],
  ["text-blur", "Read me everything written on the card I'm holding up, line by line.", (r) => TEXT.map(([size, re]) => `${size}:${re.test(r) ? "read" : "MISSED"}`).join("  ")],
  ["owl", "What am I holding up?", (r) => (/owl/i.test(r) ? "right" : "WRONG")],
  ["zebra", "What am I holding up?", (r) => (/zebra/i.test(r) ? "right" : "WRONG")],
  ["sunflower", "What am I holding up?", (r) => (/sunflower/i.test(r) ? "right" : "WRONG")],
  ["basketball", "What am I holding up?", (r) => (/basketball/i.test(r) ? "right" : "WRONG")],
  ["owl-dark", "What am I holding up?", (r) => (/owl/i.test(r) ? "right" : /dark|can'?t (see|make|tell)|hard to/i.test(r) ? "said it's too dark" : "WRONG")],
  ["owl-verydark", "What am I holding up?", (r) => (/owl/i.test(r) ? "right" : /dark|can'?t (see|make|tell)|hard to/i.test(r) ? "said it's too dark" : "WRONG (guessed)")],
  ["clutter", "How many soccer balls can you see in this picture, and is there a penguin?", (r) => `soccer balls (3): ${/\b(three|3)\b/i.test(r) ? "right" : "WRONG"}, penguin (yes): ${/\byes\b|there is a penguin|there's a penguin|a penguin/i.test(r) && !/no penguin|don'?t see a penguin/i.test(r) ? "right" : "WRONG"}`],
  ["clutter", "How many pictures are on the table in total, and how many of them are birds?", (r) => `total (20): ${/\b(twenty|20)\b/i.test(r) ? "right" : "WRONG"}, birds (6): ${/\b(six|6)\b/i.test(r) ? "right" : "WRONG"}`],
  ["clutter", "Where exactly is the red rose?", (r) => (/bottom/i.test(r) && /left|second/i.test(r) ? "right (bottom row, second from left)" : "WRONG or vague")],
];
for (const [scene, question, score] of cases) {
  for (let run = 0; run < 2; run++) {
    const c = await connect(`vision-${scene}`);
    await c.start();
    const r = await look(c, scene, question);
    const row = { scene, question, run: run + 1, verdict: score(r.reply), first_word_ms: r.first_word_ms, reply: r.reply.slice(0, 400) };
    out.scenes.push(row);
    console.log(`${scene.padEnd(13)} ${String(r.first_word_ms).padStart(5)} ms  ${row.verdict}\n     "${r.reply.slice(0, 230).replace(/\n/g, " ")}"`);
    await c.close();
  }
}
// Does it understand what it saw over time, or only the frame in front of it?
{
  const c = await connect("vision-time");
  await c.start();
  const a = await look(c, "owl", "What's this?");
  const b = await look(c, "sunflower", "And this one?");
  const d = await look(c, "sunflower", "What did I show you just before this one?");
  const e = await look(c, "sunflower", "What colour were its eyes, the first thing I showed you?");
  const f = await look(c, "basketball", "Did anything change in what you can see since my last question?");
  out.overTime = { first: a.reply.slice(0, 120), second: b.reply.slice(0, 120), recall_what: d.reply.slice(0, 160), recall_detail_not_said_before: e.reply.slice(0, 200), noticed_change: f.reply.slice(0, 200) };
  console.log("\nover time:", JSON.stringify(out.overTime, null, 1));
  await c.close();
}
// What a picture costs in speed.
{
  const c = await connect("vision-speed");
  await c.start();
  const withPic = [], without = [];
  for (let i = 0; i < 5; i++) {
    without.push((await typed(c, ["What's four plus four?", "Name a colour.", "What's the capital of Peru?", "Is ice cold?", "What comes after nine?"][i])).first_word_ms);
    withPic.push((await look(c, ["owl", "zebra", "sunflower", "basketball", "text"][i], "In three words, what's in front of you?")).first_word_ms);
  }
  c.send({ type: "vision", enabled: false });
  out.speed = { first_word_ms_without_picture: stats(without), first_word_ms_with_picture: stats(withPic) };
  console.log("\nspeed:", JSON.stringify(out.speed));
  await c.close();
}
save(`vision-${PORT}-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}`, out);
process.exit(0);
