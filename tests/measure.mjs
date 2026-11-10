import fs from "node:fs";
const [file, label, extraWaitMs] = process.argv.slice(2);
const w = fs.readFileSync(file); const pcm = w.subarray(w.indexOf("data") + 8);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ws = new WebSocket(`ws://127.0.0.1:${process.env.PORT || 3000}/ws?session=test-${label}-${Date.now()}`);
ws.binaryType = "arraybuffer";
let silence = true, tEnd = 0, tCommit = 0, tDelta = 0, tAudio = 0, text = "", reply = "", bytes = 0, playing = false, pt = null, first = 0;
const rms = (b) => { let s = 0; for (let i = 0; i + 1 < b.length; i += 2) s += b.readInt16LE(i) ** 2; return Math.sqrt(s / (b.length / 2)) / 32768; };
setInterval(() => silence && ws.readyState === 1 && ws.send(new Uint8Array(2560)), 80);
const waiters = []; const waitFor = (p, ms) => new Promise((res) => { waiters.push({ p, res }); setTimeout(() => res(null), ms); });
const others = [];
ws.onmessage = (e) => {
  if (typeof e.data !== "string") { if (!tAudio) tAudio = Date.now(); if (!first) first = Date.now(); bytes += e.data.byteLength;
    if (!playing) { playing = true; ws.send(JSON.stringify({ type: "playback", playing: true })); }
    clearTimeout(pt); pt = setTimeout(() => { playing = false; ws.send(JSON.stringify({ type: "playback", playing: false })); }, Math.max(0, first + bytes / 96 - Date.now()) + 100); return; }
  const m = JSON.parse(e.data);
  if (m.type === "user_turn" && !tCommit) { tCommit = Date.now(); text = m.text; }
  if (m.type === "assistant_delta") { if (!tDelta) tDelta = Date.now(); reply += m.text ?? m.delta ?? ""; }
  if (!["assistant_delta", "transcript", "interim", "level"].includes(m.type)) others.push(m.type + (m.status ? ":" + m.status : "") + (m.kind ? ":" + m.kind : ""));
  for (const x of [...waiters]) if (x.p(m)) { waiters.splice(waiters.indexOf(x), 1); x.res(m); }
};
ws.onopen = () => ws.send(JSON.stringify({ type: "start" }));
await waitFor((m) => m.type === "ready", 10000); await sleep(1500);
silence = false;
for (let i = 0; i < pcm.length; i += 2560) { const c = pcm.subarray(i, i + 2560); ws.send(c); await sleep(80); if (rms(c) > 0.01) tEnd = Date.now(); }
silence = true;
await waitFor((m) => m.type === "tts_done", Number(extraWaitMs) || 25000); await sleep(400);
console.log(JSON.stringify({ label, heard: text, eos_to_commit: tCommit - tEnd, commit_to_text: tDelta - tCommit, commit_to_audio: tAudio - tCommit, eos_to_audio: tAudio - tEnd, reply: reply.slice(0, 200), events: [...new Set(others)].join(",") }));
ws.send(JSON.stringify({ type: "reset" })); ws.send(JSON.stringify({ type: "stop" })); setTimeout(() => process.exit(0), 300);
