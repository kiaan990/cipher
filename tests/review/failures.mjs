// What the user sees and hears when something is broken. Run by run-failures.sh against
// throwaway copies of the app, each with one thing broken. Usage: PORT=<port> node failures.mjs <label>
import { connect, ask, typed, tts, silence, concat, sleep, save, PORT } from "./lib.mjs";
const label = process.argv[2] ?? "failure";
const out = { label };
let c;
try {
  c = await connect(label);
} catch (err) {
  console.log(JSON.stringify({ label, could_not_connect: String(err.message) }));
  process.exit(0);
}
const ready = await c.start();
out.on_start = ready ? ready.type : "nothing within 12 s (no ready, no error)";
await sleep(1500);
const spoken = await ask(c, concat(tts("Cipher, what's the capital of France?"), silence(300)), { timeout: 20000 });
out.spoken_question = spoken.answered ? { answered: true, reply: spoken.reply.slice(0, 120), wait_ms: spoken.eos_to_audio } : { answered: false, why: spoken.why, heard: spoken.heard ?? null };
await sleep(1000);
const t = await typed(c, "What's on my calendar tomorrow?", { timeout: 45000 });
out.typed_calendar_question = { finished: t.finished, reply: t.reply.slice(0, 200), total_ms: t.total_ms, actions: t.actions, had_audio: Boolean(t.turn?.audioBytes) };
await sleep(1000);
out.messages_shown_to_user = c.events.filter((m) => ["error", "notice", "stopped"].includes(m.type)).map((m) => `${m.type}${m.source ? ` (${m.source})` : ""}: ${String(m.message ?? "").slice(0, 220)}`);
out.status = c.events.find((m) => m.type === "status")?.missingKeys;
console.log(JSON.stringify(out, null, 1));
save(`failure-${label}`, out);
await c.close();
process.exit(0);
