/**
 * The link with Muse.
 *
 * Muse (Meta's assistant) uses the same cloud server Cipher does, and that server can
 * keep small named notes ("briefs"). Two of them are used as a mailbox:
 *
 *   muse-to-cipher   Muse writes what you asked it to pass on to Cipher
 *   cipher-to-muse   Cipher writes its answer, and anything you asked it to tell Muse
 *
 * Cipher looks at the first every few seconds. When its contents change, that is a new
 * message: Cipher answers it in text (no voice) and writes the answer to the second,
 * where Muse reads it. Nothing can be pushed to Muse, so it only sees an answer when
 * it next looks.
 *
 * A message arriving this way can read and add things on the cloud server but can't
 * delete anything, and can't touch this Mac: no commands, no browser, no delegating.
 */
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import Anthropic from "@anthropic-ai/sdk";
import { config } from "./config.js";
import { cloud } from "./cloud.js";
import { memory } from "./memory.js";
import { nowNote } from "./clock.js";
import { httpFetch } from "./net.js";

const INBOX = "muse-to-cipher";
const OUTBOX = "cipher-to-muse";
const FAST_MS = 5_000;
const SLOW_MS = 20_000;
const IDLE_AFTER_MS = 30 * 60_000;
const MAX_STEPS = 10;
const KEEP = 10;
const FILE = path.join(config.dataDir, "muse.json");

interface Exchange {
  at: string;
  from: string;
  reply: string;
}
interface Note {
  at: string;
  text: string;
}
interface State {
  /** A fingerprint of the inbox as last read, so only a change counts as a new message. */
  seen: string | null;
  exchanges: Exchange[];
  notes: Note[];
  turn: number;
}

const client = config.anthropicKey ? new Anthropic({ apiKey: config.anthropicKey, maxRetries: 1, fetch: httpFetch }) : null;
const hash = (s: string) => createHash("sha1").update(s).digest("hex");
const stamp = (d = new Date()) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: config.timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d).replace(",", "");

const SYSTEM = [
  "You are Cipher, the user's personal assistant. Normally you talk with them out loud on their Mac. Right now they are writing to you from somewhere else, through Muse (Meta's assistant), which passes their message to you and reads your answer back to them.",
  "Answer in plain text: short, direct, no markdown headings, no mood tags, nothing meant to be spoken. A few lines at most unless they ask for detail. Lists can be simple lines.",
  "The message may begin with a line holding a time or an id; that is only there to tell messages apart, ignore it.",
  "You can use the cloud server's tools (calendar, tasks, notes, search) to look things up and to add or change things. Over this channel you cannot delete anything, run commands on the Mac, use the browser, or hand off work; if asked, say that needs to be done by talking to you on the Mac.",
  "Only say something was done if a tool result shows it was. If a tool fails, say so plainly.",
].join("\n");

const TOOL: Anthropic.Tool = {
  name: "message_muse",
  description:
    "Leave a note for Muse (Meta's assistant, which the user also talks to). Muse sees it the next time the user talks to it; it can't be delivered sooner. Use when the user asks you to tell, send or pass something to Muse.",
  input_schema: {
    type: "object",
    properties: { message: { type: "string", description: "The note, written so it makes sense on its own." } },
    required: ["message"],
  },
};

class Muse {
  private state: State = { seen: null, exchanges: [], notes: [], turn: 0 };
  private timer: NodeJS.Timeout | null = null;
  private busy = false;
  private lastActive = Date.now();
  private started = false;

  get on(): boolean {
    return config.museLink && cloud.configured && Boolean(client);
  }

  start(): void {
    if (!this.on || this.started) return;
    this.started = true;
    try {
      this.state = { ...this.state, ...JSON.parse(fs.readFileSync(FILE, "utf8")) };
    } catch {
      /* first run */
    }
    console.log("[muse] link on: answering messages Muse leaves on the cloud server");
    this.schedule(3000);
  }

  // ---- the voice side: Cipher can leave Muse a note

  tools(): Anthropic.Tool[] {
    return this.on ? [TOOL] : [];
  }

  owns(name: string): boolean {
    return name === TOOL.name;
  }

  describe(): string {
    if (!this.on) return "";
    const last = this.state.exchanges[0];
    return [
      "Muse: the user also talks to Muse (Meta's assistant). Messages they send you through Muse are answered in text by you, separately from this conversation. To pass something to Muse, use `message_muse`; Muse sees it when the user next talks to it.",
      last ? `- The latest message through Muse (${last.at}): "${last.from.slice(0, 200)}". You answered: "${last.reply.slice(0, 300)}"` : "",
    ]
      .filter(Boolean)
      .join("\n");
  }

  async run(call: Anthropic.ToolUseBlock): Promise<Anthropic.ToolResultBlockParam> {
    const text = String((call.input as { message?: unknown } | null)?.message ?? "").trim();
    const result = (content: string, isError = false): Anthropic.ToolResultBlockParam => ({ type: "tool_result", tool_use_id: call.id, content, is_error: isError || undefined });
    if (!text) return result("Give the note in `message`.", true);
    this.state.notes = [{ at: stamp(), text: text.slice(0, 2000) }, ...this.state.notes].slice(0, KEEP);
    this.save();
    const ok = await this.writeOutbox();
    return ok
      ? result("Left for Muse. It will see it the next time the user talks to it; say so in a few words.")
      : result("Couldn't reach the cloud server, so the note hasn't been left for Muse yet. It is kept and will go with the next one.", true);
  }

  // ---- the mailbox

  private schedule(ms?: number): void {
    if (this.timer) clearTimeout(this.timer);
    const wait = ms ?? (Date.now() - this.lastActive > IDLE_AFTER_MS ? SLOW_MS : FAST_MS);
    this.timer = setTimeout(() => void this.tick(), wait);
    this.timer.unref();
  }

  private async tick(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      const inbox = await this.read(INBOX);
      if (inbox === null) return; // server unreachable: try again later
      const mark = hash(inbox);
      if (this.state.seen === null) {
        // First ever look: whatever is there was not written for this link.
        this.state.seen = mark;
        this.save();
        await this.writeOutbox();
        return;
      }
      if (mark === this.state.seen || !inbox) {
        if (mark !== this.state.seen) {
          this.state.seen = mark;
          this.save();
        }
        return;
      }
      this.lastActive = Date.now();
      console.log(`[muse] message in (${inbox.length} characters)`);
      const reply = await this.answer(inbox);
      this.state.seen = mark;
      this.state.exchanges = [{ at: stamp(), from: inbox.slice(0, 4000), reply }, ...this.state.exchanges].slice(0, KEEP);
      this.save();
      const ok = await this.writeOutbox();
      console.log(`[muse] ${ok ? "answered" : "answered, but the answer couldn't be written to the cloud server yet"}`);
    } catch (err) {
      console.warn(`[muse] ${(err as Error).message.replace(/https?:\/\/\S+/g, "<cloud server>")}`);
    } finally {
      this.busy = false;
      this.schedule();
    }
  }

  /** A brief's contents: "" if it doesn't exist, null if the server can't be reached. */
  private async read(name: string): Promise<string | null> {
    const r = await cloud.direct("brief_get", { name });
    if (!r || r.isError) return null;
    let text = typeof r.data === "string" ? r.data : r.text;
    try {
      const j = JSON.parse(text);
      if (j && typeof j.result === "string") text = j.result;
    } catch {
      /* already plain text */
    }
    text = text.trim();
    return /^No brief\b/i.test(text) ? "" : text;
  }

  private async writeOutbox(): Promise<boolean> {
    const [latest, ...earlier] = this.state.exchanges;
    const lines = [
      "# Cipher → Muse",
      `Updated ${stamp()}. Written by Cipher. To send Cipher a message, save a brief named "${INBOX}" (first line: the current time; then the message), wait about fifteen seconds, and read this brief again.`,
      "",
      "## Latest reply",
      latest ? `Answered ${latest.at}, to: ${JSON.stringify(latest.from.slice(0, 500))}\n\n${latest.reply}` : "(No replies yet.)",
    ];
    if (this.state.notes.length) lines.push("", "## Notes from Cipher", ...this.state.notes.map((n) => `- (${n.at}) ${n.text}`));
    if (earlier.length) lines.push("", "## Earlier", ...earlier.slice(0, 4).map((e) => `- (${e.at}) asked: ${JSON.stringify(e.from.slice(0, 200))}; answered: ${JSON.stringify(e.reply.slice(0, 400))}`));
    const r = await cloud.direct("brief_save", { name: OUTBOX, content: lines.join("\n") });
    return Boolean(r && !r.isError);
  }

  private save(): void {
    try {
      fs.mkdirSync(path.dirname(FILE), { recursive: true });
      fs.writeFileSync(FILE, JSON.stringify(this.state, null, 2));
    } catch (err) {
      console.warn(`[muse] couldn't save its state: ${(err as Error).message}`);
    }
  }

  // ---- answering in text

  private async answer(message: string): Promise<string> {
    if (!client) return "Cipher can't answer right now: it has no key for its model.";
    const turn = 1_000_000 + ++this.state.turn; // kept apart from spoken turns, for approvals
    const user = { text: message, turn };
    const model = /^(off|none|false)?$/i.test(config.toolModel) ? config.anthropicModel : config.toolModel;
    const tools = cloud.safeTools();
    const system = [SYSTEM, cloud.describe(), memory.describe()].filter(Boolean).join("\n\n");
    const messages: Anthropic.MessageParam[] = [];
    for (const e of this.state.exchanges.slice(0, 6).reverse()) {
      messages.push({ role: "user", content: e.from.slice(0, 1500) }, { role: "assistant", content: e.reply.slice(0, 1500) || "(no answer)" });
    }
    messages.push({ role: "user", content: `${message.slice(0, 6000)}\n\n${nowNote()}` });

    const signal = AbortSignal.timeout(120_000);
    try {
      for (let step = 0; step < MAX_STEPS; step++) {
        const res = await client.messages.create({ model, max_tokens: 1500, system, messages, ...(tools.length ? { tools } : {}) }, { signal });
        const text = res.content.filter((b): b is Anthropic.TextBlock => b.type === "text").map((b) => b.text).join("\n").trim();
        const calls = res.content.filter((b): b is Anthropic.ToolUseBlock => b.type === "tool_use");
        if (res.stop_reason !== "tool_use" || !calls.length) return text || "(Cipher had nothing to say.)";
        messages.push({ role: "assistant", content: res.content });
        const results: Anthropic.ToolResultBlockParam[] = [];
        for (const call of calls) {
          results.push(
            cloud.owns(call.name)
              ? await cloud.run(call, user, signal, () => {})
              : { type: "tool_result", tool_use_id: call.id, content: "That isn't available over this channel.", is_error: true },
          );
        }
        messages.push({ role: "user", content: results });
      }
      return "That took more steps than I can do from here. Ask me again in smaller pieces, or talk to me on the Mac.";
    } catch (err) {
      console.warn(`[muse] answering failed: ${(err as Error).message.replace(/https?:\/\/\S+/g, "<cloud server>")}`);
      return "Cipher hit an error answering that. Try again in a moment.";
    }
  }
}

export const muse = new Muse();
