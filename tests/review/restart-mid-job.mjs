// A background command is running when the app is stopped. Part 1 (start): starts a 45 s
// command and exits. Part 2 (after): after the app is back, reports what it says about it.
// Usage: PORT=3111 node tests/review/restart-mid-job.mjs start|after
import { execSync } from "node:child_process";
import { connect, typed, sleep } from "./lib.mjs";
const alive = () => { try { return execSync("pgrep -f 'sleep 46'", { encoding: "utf8" }).trim().split("\n").length; } catch { return 0; } };
const c = await connect("restart", { origin: true });
await c.start();
if (process.argv[2] === "start") {
  c.send({ type: "mac_mode", mode: "full" });
  const confirm = await c.waitFor((m) => m.type === "mac_mode_confirm", 3000);
  if (confirm) c.send({ type: "mac_mode", mode: "full", confirm: confirm.code });
  await sleep(300);
  const r = await typed(c, "Run this exact shell command and tell me what it prints: sleep 46; echo survived > /tmp/cipher-review-marker.txt; echo done");
  console.log(JSON.stringify({ said: r.reply.slice(0, 120), command_running: alive() > 0 }));
  process.exit(0); // leave without resetting, as a crash would
} else {
  const known = new Set(c.turns.keys());
  const note = await c.waitFor((m) => m.type === "thinking" && !known.has(m.turnId), 15000);
  if (note) await c.waitFor((m) => m.type === "tts_done" && m.turnId === note.turnId, 30000);
  await sleep(300);
  console.log(JSON.stringify({ command_still_running_after_restart: alive() > 0, announced_on_reconnect: note ? c.turns.get(note.turnId)?.text.slice(0, 200) : "nothing announced within 15 s" }));
  const r = await typed(c, "What happened to that command I asked you to run?");
  console.log(JSON.stringify({ asked_later: r.reply.slice(0, 220) }));
  c.send({ type: "mac_mode", mode: "ask" });
  await c.close();
  process.exit(0);
}
