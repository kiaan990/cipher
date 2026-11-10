import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import Anthropic from "@anthropic-ai/sdk";
import { ROOT_DIR, config } from "./config.js";
import { httpFetch } from "./net.js";

/**
 * Long-term memory: short facts about the user that carry over between conversations
 * (name, preferences, plans, people in their life, things they asked to be remembered).
 *
 * Stored only on this computer, in data/memory.json. After each reply, a background
 * Claude call decides what (if anything) is worth remembering, so it adds no delay
 * to the conversation. The facts are added to Claude's instructions at the start of
 * every reply.
 */

export interface MemoryItem {
  id: string;
  text: string;
  at: number;
}

interface MemoryFile {
  enabled: boolean;
  items: MemoryItem[];
}

const MAX_ITEMS = 150;
const MAX_LEN = 240;
const FILE = path.join(config.dataDir, "memory.json");

type Listener = (change: { added: string[]; removed: string[] }) => void;

class MemoryStore {
  private data: MemoryFile = { enabled: true, items: [] };
  private readonly listeners = new Set<Listener>();
  /** Updates run one at a time, in order. */
  private queue: Promise<void> = Promise.resolve();
  private readonly client = config.anthropicKey
    ? new Anthropic({ apiKey: config.anthropicKey, maxRetries: 2, fetch: httpFetch })
    : null;

  constructor() {
    if (!fs.existsSync(FILE)) return; // first run
    const loaded = readMemoryFile(FILE);
    if (loaded) {
      this.data = loaded;
      try {
        backupDaily(loaded); // today's copy, straight away
      } catch {
        /* not fatal */
      }
      return;
    }
    // The file is damaged (e.g. the disk filled up). Keep it for inspection and
    // restore the newest backup, so memories are never silently wiped.
    const aside = `${FILE.replace(/\.json$/, "")}.damaged-${Date.now()}.json`;
    try {
      fs.renameSync(FILE, aside);
    } catch {
      /* leave it */
    }
    for (const backup of listBackups().reverse()) {
      const restored = readMemoryFile(backup);
      if (restored) {
        this.data = restored;
        console.warn(`[memory] memory.json was damaged (kept as ${path.basename(aside)}); restored ${restored.items.length} memories from ${path.basename(backup)}`);
        this.save([], []);
        return;
      }
    }
    console.warn(`[memory] memory.json was damaged and no backup could be read; it was kept as ${path.basename(aside)}`);
  }

  get enabled(): boolean {
    return this.data.enabled;
  }

  list(): MemoryItem[] {
    return [...this.data.items];
  }

  onChange(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  setEnabled(on: boolean): void {
    this.data.enabled = on;
    this.save([], []);
  }

  remove(id: string): void {
    const item = this.data.items.find((i) => i.id === id);
    if (!item) return;
    this.data.items = this.data.items.filter((i) => i !== item);
    this.save([], [item.text]);
  }

  clear(): void {
    const removed = this.data.items.map((i) => i.text);
    this.data.items = [];
    this.save([], removed);
  }

  /** The block added to Claude's instructions, or "" when there's nothing to add. */
  describe(): string {
    if (!this.data.enabled) return "";
    const lines = this.data.items.map((i) => `- ${i.text}`);
    return [
      "Long-term memory. You keep a memory of the person across conversations; it is saved automatically after each reply.",
      "If they ask you to remember something, just confirm briefly. If they ask you to forget something, confirm it's forgotten. If they ask what you remember, tell them in a sentence or two.",
      lines.length
        ? `What you remember about them from earlier conversations (use it naturally, like a friend would; don't recite it unprompted):\n${lines.join("\n")}`
        : "You don't remember anything about them yet.",
    ].join("\n");
  }

  /** Look at one exchange and update the memory in the background. */
  learnFrom(userText: string, assistantText: string): void {
    if (!this.data.enabled || !this.client || !userText.trim()) return;
    this.queue = this.queue.then(() => this.update(userText, assistantText)).catch((err) => {
      console.warn(`[memory] update failed: ${(err as Error)?.message ?? err}`);
    });
  }

  private async update(userText: string, assistantText: string): Promise<void> {
    const current = this.data.items.map((i) => `${i.id}: ${i.text}`).join("\n") || "(nothing yet)";
    const res = await this.client!.messages.create({
      model: config.anthropicModel,
      max_tokens: 400,
      system: `You maintain the long-term memory of a voice assistant. Memory is a short list of facts about the user that will still matter in future conversations.

Save: their name and the names of people, pets and places in their life; preferences, likes and dislikes; goals, plans and upcoming events; work, studies and projects; important things that happened to them; anything they explicitly ask to be remembered.
Don't save: small talk, general-knowledge questions and answers, what the assistant said, temporary states ("is tired right now"), anything already in memory, or guesses.
Never save secrets or sensitive numbers: passwords, PINs, verification or pickup codes, account, card, bank, social security or ID numbers, or anything copied from an email that looks like one. Save the fact without the number instead (e.g. "They have a parcel to pick up at their building").

Write each memory as one short, self-contained sentence about the user, e.g. "Their dog is called Max." Use the user's own words for names.
If a new fact replaces an old one (a changed plan, a corrected name), remove the old id and add the new fact.
If the user asks to forget something, remove the matching ids.
Most exchanges contain nothing worth saving: then add and remove nothing.`,
      messages: [
        {
          role: "user",
          content: `Current memory (id: fact):\n${current}\n\nLatest exchange:\nUser: ${userText.slice(0, 2000)}\nAssistant: ${assistantText.slice(0, 1000)}`,
        },
      ],
      tools: [
        {
          name: "update_memory",
          description: "Apply changes to the user's long-term memory. Pass empty lists when nothing should change.",
          input_schema: {
            type: "object",
            properties: {
              add: { type: "array", items: { type: "string" }, description: "New facts to remember, one short sentence each." },
              remove: { type: "array", items: { type: "string" }, description: "Ids of memories to delete (outdated, wrong, or asked to forget)." },
            },
            required: ["add", "remove"],
          },
        },
      ],
      tool_choice: { type: "tool", name: "update_memory" },
    });

    const call = res.content.find((b) => b.type === "tool_use");
    const input = (call?.type === "tool_use" ? call.input : {}) as { add?: unknown; remove?: unknown };
    const add = (Array.isArray(input.add) ? input.add : [])
      .filter((t): t is string => typeof t === "string")
      .map((t) => t.replace(/\s+/g, " ").trim().slice(0, MAX_LEN))
      .filter(Boolean)
      .slice(0, 6);
    const removeIds = new Set((Array.isArray(input.remove) ? input.remove : []).map(String));
    if (!add.length && !removeIds.size) return;

    const removed = this.data.items.filter((i) => removeIds.has(i.id));
    const known = new Set(this.data.items.filter((i) => !removeIds.has(i.id)).map((i) => i.text.toLowerCase()));
    const fresh = add.filter((t) => !known.has(t.toLowerCase()));
    this.data.items = [
      ...this.data.items.filter((i) => !removeIds.has(i.id)),
      ...fresh.map((text) => ({ id: randomUUID().slice(0, 8), text, at: Date.now() })),
    ].slice(-MAX_ITEMS);
    this.save(fresh, removed.map((i) => i.text));
  }

  private save(added: string[], removed: string[]): void {
    try {
      writeDurably(FILE, JSON.stringify(this.data, null, 2));
      backupDaily(this.data);
    } catch (err) {
      console.warn(`[memory] couldn't save: ${(err as Error).message}`);
    }
    if (added.length) console.log(`[memory] remembered: ${added.join(" | ")}`);
    if (removed.length) console.log(`[memory] forgot: ${removed.join(" | ")}`);
    for (const fn of this.listeners) fn({ added, removed });
  }
}

// ---- saving safely ------------------------------------------------------------------

const BACKUP_DIR = path.join(path.dirname(FILE), "backups");
const KEEP_BACKUPS = 30;

/** Write to a temporary file, force it onto the disk, then swap it in: a crash or power cut leaves either the old file or the new one, never half of one. */
function writeDurably(file: string, text: string): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  const fd = fs.openSync(tmp, "w", 0o600);
  try {
    fs.writeSync(fd, text);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, file);
}

/** One copy per day (the first save of each day), kept for 30 days. */
function backupDaily(data: MemoryFile): void {
  const day = new Date().toISOString().slice(0, 10);
  const file = path.join(BACKUP_DIR, `memory-${day}.json`);
  if (fs.existsSync(file)) return;
  writeDurably(file, JSON.stringify(data, null, 2));
  for (const old of listBackups().slice(0, -KEEP_BACKUPS)) fs.rmSync(old, { force: true });
}

function listBackups(): string[] {
  try {
    return fs
      .readdirSync(BACKUP_DIR)
      .filter((f) => /^memory-\d{4}-\d{2}-\d{2}\.json$/.test(f))
      .sort()
      .map((f) => path.join(BACKUP_DIR, f));
  } catch {
    return [];
  }
}

function readMemoryFile(file: string): MemoryFile | null {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!raw || typeof raw !== "object" || !Array.isArray(raw.items)) return null;
    return {
      enabled: raw.enabled !== false,
      items: raw.items
        .filter((i: any) => i && typeof i.text === "string" && i.text.trim())
        .map((i: any) => ({ id: String(i.id || randomUUID()), text: String(i.text).slice(0, MAX_LEN), at: Number(i.at) || Date.now() })),
    };
  } catch {
    return null;
  }
}

export const memory = new MemoryStore();
