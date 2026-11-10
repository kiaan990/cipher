/**
 * Dreaming from the command line.
 *
 *   npm run dream               a deep dream now
 *   npm run dream -- light      a light dream (check and re-read only, no tidying)
 *   npm run dream -- --dry      ask the model and show what it would change, changing nothing
 *   npm run dream -- status     what is waiting, and the latest dreams
 *   npm run dream -- undo       put things back as they were before the latest dream
 *
 * If Cipher is running, this asks the running app to do it (the app holds memory open,
 * so two programs must not both write it). Otherwise it does the work itself.
 */
import "./log.js";
import { config } from "./config.js";

const args = process.argv.slice(2);
const dry = args.includes("--dry");
const action = args.find((a) => ["status", "undo"].includes(a)) ?? "dream";
const kind = args.includes("light") ? "light" : "deep";
const base = `http://127.0.0.1:${config.port}`;
const headers = { "x-voice-orb": "1" };
const say = (text: string): void => void process.stdout.write(`${text}\n`);

type Listing = { status: Record<string, unknown> & { busy: boolean }; dreams: { id: string; text: string }[] };
const fetchListing = async (): Promise<Listing | null> => {
  try {
    const res = await fetch(`${base}/api/dream`, { headers, signal: AbortSignal.timeout(4000) });
    return res.ok ? ((await res.json()) as Listing) : null;
  } catch {
    return null;
  }
};

function showStatus(status: Record<string, unknown>): void {
  const at = (n: unknown) => (Number(n) ? new Date(Number(n)).toLocaleString() : "never");
  say(`Dreaming: ${status.enabled ? "on" : "off"} (${status.model})${status.busy ? ", a dream is running" : ""}`);
  say(`Memory: ${status.facts} facts, ${status.pages} pages. Waiting: ${status.newExchanges} new exchanges, ${status.unchecked} unchecked facts.`);
  say(`Last dream: ${at(status.lastDreamAt)}. Last deep dream: ${at(status.lastDeepAt)}. Dreams today: ${status.dreamsToday}.`);
}

async function viaApp(before: Listing): Promise<void> {
  if (action === "status") {
    showStatus(before.status);
    for (const d of before.dreams.slice(0, 3)) say(`\n${d.text}`);
    return;
  }
  if (action === "undo") {
    const out = (await (await fetch(`${base}/api/dream/undo`, { method: "POST", headers })).json()) as { undone?: { text: string }; error?: string };
    return say(out.undone ? `Undone:\n${out.undone.text}` : (out.error ?? "Nothing to undo."));
  }
  const res = await fetch(`${base}/api/dream?kind=${kind}${dry ? "&dry=1" : ""}`, { method: "POST", headers });
  if (!res.ok) return say(((await res.json()) as { error?: string }).error ?? "The app refused.");
  say(`Cipher is dreaming (${kind}${dry ? ", dry run" : ""}). This can take a few minutes…`);
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    const now = await fetchListing();
    if (!now) return say("Lost contact with the app.");
    if (now.status.busy) continue;
    const latest = now.dreams[0];
    return say(latest && latest.id !== before.dreams[0]?.id ? latest.text : "There was nothing to do.");
  }
}

async function alone(): Promise<void> {
  const { dreamer, describeDream } = await import("./dream.js");
  if (action === "status") {
    showStatus(dreamer.status());
    for (const d of dreamer.records(3)) say(`\n${describeDream(d)}`);
    return;
  }
  if (action === "undo") {
    const record = await dreamer.undo();
    return say(record ? `Undone:\n${describeDream(record)}` : "There is no dream to undo.");
  }
  say(`Dreaming (${kind}${dry ? ", dry run" : ""}). This can take a few minutes…`);
  say(describeDream(await dreamer.dream(kind, { dry })));
}

const running = await fetchListing();
try {
  await (running ? viaApp(running) : alone());
} catch (err) {
  console.error(`Dreaming failed: ${(err as Error).message}`);
  process.exitCode = 1;
}
