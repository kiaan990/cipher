// Reads logs/server.log (real conversations) and prints what actually happened:
// reply latency by stage, end-of-turn decisions, tool timings, interruptions, errors.
// Usage: node tests/review/log-stats.mjs [path-to-log]
import fs from "node:fs";
const file = process.argv[2] ?? "logs/server.log";
const lines = fs.readFileSync(file, "utf8").split("\n");
const pct = (a, p) => { if (!a.length) return NaN; const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]; };
const row = (name, a) => console.log(`${name.padEnd(34)} n=${String(a.length).padStart(3)}  p50 ${pct(a, 50)}  p90 ${pct(a, 90)}  max ${Math.max(...a)}  min ${Math.min(...a)}`);
const lat = { token: [], phrase: [], audio: [], voice: [] }, cachedOpen = [], uncached = [];
const tools = {}, turn = { finished: [], unfinishedWait: [], fallback: 0, smartMs: [] };
const count = {};
const bump = (k) => (count[k] = (count[k] ?? 0) + 1);
const models = {}, cache = { read: 0, fresh: 0, written: 0, steps: 0 };
let first = "", last = "";
for (const l of lines) {
  const ts = l.slice(0, 23); if (/^\d{4}-/.test(ts)) { first ||= ts; last = ts; }
  let m;
  if ((m = l.match(/\[latency\] turn \d+: Claude first words (\d+) ms · first phrase ready (\d+) ms · first audio (\d+) ms \(voice (-?\d+) ms\)/))) {
    lat.token.push(+m[1]); lat.phrase.push(+m[2]); lat.audio.push(+m[3]); lat.voice.push(+m[4]);
    (+m[4] < 30 ? cachedOpen : uncached).push(+m[3]);
  } else if ((m = l.match(/\[tool\] turn \d+: (\S+) asked for at (\d+) ms, took (\d+) ms/))) (tools[m[1]] ??= []).push(+m[3]);
  else if ((m = l.match(/\[turn\] finished \(p=([\d.]+), (\d+) ms\)/))) { turn.finished.push(+m[1]); turn.smartMs.push(+m[2]); }
  else if ((m = l.match(/\[turn\] sounds unfinished \(p=([\d.]+), (\d+) ms\): waiting up to (\d+) ms/))) { turn.unfinishedWait.push(+m[3]); turn.smartMs.push(+m[2]); }
  else if (/1 s fallback/.test(l)) turn.fallback++;
  else if ((m = l.match(/\[claude\] turn \d+ step \d+ \(([^,)]+)[^)]*\): (\d+) new \+ (\d+) cached \+ (\d+) cache-written/))) { models[m[1]] = (models[m[1]] ?? 0) + 1; cache.steps++; cache.fresh += +m[2]; cache.read += +m[3]; cache.written += +m[4]; }
  if (/backup request/.test(l)) bump("model slow to start: backup request sent");
  if (/\[focus\] different speaker/.test(l)) bump("focus: turn ignored as a different speaker");
  if (/\[focus\] same speaker/.test(l)) bump("focus: turn accepted");
  if (/\[barge\].*stopping/.test(l)) bump("barge-in: stopped");
  if (/\[barge\].*kept talking/.test(l)) bump("barge-in: kept talking");
  if (/\[echo\] ignored/.test(l)) bump("own voice heard back and ignored");
  if (/\[wake\] ignored/.test(l)) bump("speech ignored: no wake word");
  if (/backchannel \(/.test(l)) bump("listener sound played");
  if (/dropped \d+ characters of narration/.test(l)) bump("narration dropped before a tool");
  if (/from saved audio/.test(l)) bump("opener played from saved audio");
  if (/\[deepgram\]/.test(l)) bump("speech-recognition warnings");
  if (/no microphone audio/.test(l)) bump("mic silent for 4 s");
  if (/became job|carries on in the background|\[jobs\]/.test(l)) bump("job lines");
  if (/Server listening|Model: /.test(l) && /Model: /.test(l)) bump("server starts");
}
console.log(`log: ${file}\nfrom ${first} to ${last}\n`);
console.log("REPLY LATENCY, ms from the moment the turn was accepted (does NOT include waiting to decide you had finished, or the browser's playback buffer)");
row("model first words", lat.token); row("first phrase ready for the voice", lat.phrase); row("voice: phrase -> first audio", lat.voice); row("first audio sent to browser", lat.audio);
if (cachedOpen.length) row("  ...when opener was saved audio", cachedOpen);
if (uncached.length) row("  ...when voice had to be made", uncached);
console.log("\nEND-OF-TURN");
console.log(`decided finished: ${turn.finished.length}, decided unfinished and waited: ${turn.unfinishedWait.length}, fell back to the 1 s timer: ${turn.fallback}`);
if (turn.smartMs.length) row("turn-detection model run time", turn.smartMs);
if (turn.unfinishedWait.length) row("extra wait when judged unfinished", turn.unfinishedWait);
console.log("\nTOOLS (ms each)");
for (const [k, a] of Object.entries(tools).sort((a, b) => b[1].length - a[1].length)) row(k, a);
console.log("\nMODEL STEPS", models, `\ninput tokens: ${cache.fresh} fresh, ${cache.read} read from cache, ${cache.written} written to cache over ${cache.steps} steps (cache hit share ${(100 * cache.read / Math.max(1, cache.read + cache.fresh + cache.written)).toFixed(0)}%)`);
console.log("\nEVENTS"); for (const [k, v] of Object.entries(count).sort((a, b) => b[1] - a[1])) console.log(String(v).padStart(4), k);
