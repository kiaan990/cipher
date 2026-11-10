// Cipher diagnostic: talks to the Cipher running on this Mac like the browser does
// (speech in, voice out) and times each step. Usage: node diagnose-e2e.mjs <dir-with-wavs>
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const dir = process.argv[2];
const files = ["q1.wav", "q2.wav"].map((f) => path.join(dir, f));
let WS = globalThis.WebSocket;
if (!WS) {
  // Older Node: borrow the ws package from an installed copy of Cipher.
  const roots = [
    path.join(process.env.HOME, "Library/Application Support/Voice Orb/app"),
    path.join(process.env.HOME, "voice-orb"),
    path.join(process.env.HOME, "Downloads/voice-orb"),
  ];
  for (const r of roots) {
    try {
      WS = createRequire(path.join(r, "package.json"))("ws");
      break;
    } catch {
      /* next */
    }
  }
}
if (!WS) {
  console.log("e2e test skipped: no WebSocket available in this Node.js");
  process.exit(0);
}

const pcm = (f) => {
  const w = fs.readFileSync(f);
  return w.subarray(w.indexOf("data") + 8);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ws = new WS(`ws://127.0.0.1:3000/ws?session=diagnostic-${Date.now()}`);
ws.binaryType = "arraybuffer";
let turn = 0;
let speechEnd = 0;
let firstAudio = 0;
let userTurnAt = 0;
let firstText = 0;
let silence = true;

const timer = setInterval(() => silence && ws.readyState === 1 && ws.send(new Uint8Array(2560)), 80);
const finish = (code, msg) => {
  if (msg) console.log(msg);
  clearInterval(timer);
  try {
    ws.send(JSON.stringify({ type: "reset" }));
    ws.send(JSON.stringify({ type: "stop" }));
  } catch {
    /* closed */
  }
  setTimeout(() => process.exit(code), 300);
};
setTimeout(() => finish(1, "e2e test: TIMED OUT (no reply within 60 s)"), 60_000);

async function speak(buf) {
  silence = false;
  for (let i = 0; i < buf.length; i += 2560) {
    ws.send(buf.subarray(i, i + 2560));
    await sleep(80);
  }
  speechEnd = Date.now();
  firstAudio = firstText = userTurnAt = 0;
  silence = true;
}

ws.onopen = () => ws.send(JSON.stringify({ type: "start" }));
ws.onerror = () => finish(1, "e2e test: couldn't connect to Cipher at 127.0.0.1:3000");
ws.onmessage = async (e) => {
  if (typeof e.data !== "string") {
    if (!firstAudio && speechEnd) firstAudio = Date.now();
    return;
  }
  const m = JSON.parse(e.data);
  if (m.type === "error") console.log(`e2e ERROR from ${m.source}: ${m.message}`);
  if (m.type === "ready" && turn === 0) await speak(pcm(files[0]));
  if (m.type === "user_turn" && !userTurnAt) userTurnAt = Date.now();
  if (m.type === "assistant_delta" && !firstText) firstText = Date.now();
  if (m.type === "tts_done") {
    const t = (x) => (x ? `${x - speechEnd} ms` : "never");
    console.log(
      `e2e turn ${turn + 1}: heard you ${t(userTurnAt)} · first words ${t(firstText)} · voice started ${t(firstAudio)}  (all measured from the end of speech)`,
    );
    turn++;
    if (turn < files.length) {
      await sleep(1500);
      await speak(pcm(files[turn]));
    } else finish(0);
  }
};
