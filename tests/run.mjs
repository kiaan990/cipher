// Plays every recording in a folder to the running app, as if spoken into the mic,
// and times each reply. Usage: npm test            (tests/audio/talk)
//                              npm test -- real     (your own recordings, tests/audio/real)
//                              npm test -- tasks    (these really act on your Mac)
// Recordings: 16 kHz, mono, 16-bit WAV. Results are saved in tests/out/.
import fs from "node:fs";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const set = process.argv[2] || "talk";
const dir = path.join(here, "audio", set);
const files = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith(".wav")).sort() : [];
if (!files.length) {
  console.error(`No recordings in tests/audio/${set}. Add 16 kHz mono WAV files there.`);
  process.exit(1);
}
const run = (file) =>
  new Promise((resolve) => {
    const label = path.basename(file, ".wav");
    execFile(process.execPath, [path.join(here, "measure.mjs"), path.join(dir, file), label, set === "tasks" ? "90000" : "25000"], { timeout: 150_000 }, (err, out) => {
      try {
        resolve(JSON.parse(out.trim().split("\n").pop()));
      } catch {
        resolve({ label, error: err?.message ?? "no result" });
      }
    });
  });
const median = (xs) => {
  const s = xs.filter((x) => Number.isFinite(x) && x > 0).sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : NaN;
};

const status = await fetch(`http://127.0.0.1:${process.env.PORT || 3000}/api/status`).then((r) => r.json()).catch(() => null);
if (!status) {
  console.error("The app isn't running. Start it first (npm start).");
  process.exit(1);
}
console.log(`Model: ${status.model}   Set: ${set} (${files.length} recordings)\n`);
const results = [];
for (const f of files) {
  const r = await run(f); // one at a time: they share the mic line
  results.push(r);
  console.log(r.error ? `${r.label.padEnd(8)} FAILED: ${r.error}` : `${r.label.padEnd(8)} end of speech to voice ${String(r.eos_to_audio).padStart(5)} ms   (turn decided ${r.eos_to_commit}, first word ${r.commit_to_text}, first sound ${r.commit_to_audio})   heard: "${r.heard}"`);
}
const ok = results.filter((r) => !r.error && r.heard);
const summary = {
  model: status.model,
  set,
  at: new Date().toISOString(),
  answered: `${ok.length}/${results.length}`,
  median_ms: Object.fromEntries(["eos_to_commit", "commit_to_text", "commit_to_audio", "eos_to_audio"].map((k) => [k, median(ok.map((r) => r[k]))])),
};
console.log(`\nAnswered ${summary.answered}. Median, end of speech to voice: ${summary.median_ms.eos_to_audio} ms (first word from Claude after ${summary.median_ms.commit_to_text} ms).`);
const out = path.join(here, "out", `${set}-${status.model}-${summary.at.replace(/[:.]/g, "-")}.json`);
fs.writeFileSync(out, JSON.stringify({ summary, results }, null, 2));
console.log(`Saved ${path.relative(process.cwd(), out)}`);
process.exit(ok.length === results.length ? 0 : 1);
