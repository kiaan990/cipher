/**
 * The transcript log: every exchange (what the person said, what Cipher said back),
 * kept in order and searchable.
 *
 * Conversation history only holds the last few dozen messages, and long-term memory
 * only holds the short facts drawn from them. This log is what both come from. It lets
 * a remembered fact be checked against what was actually said (see dream.ts), and lets
 * Cipher look up an earlier conversation (see recall.ts).
 *
 * Stored only on this computer, in data/transcripts.db. Only spoken words are kept:
 * no tool results, screen contents, or camera stills.
 */
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { config } from "./config.js";

export interface Exchange {
  id: number;
  session: string;
  at: number;
  user: string;
  assistant: string;
}

const FILE = path.join(config.dataDir, "transcripts.db");
/** Exchanges older than this are dropped. */
const KEEP_DAYS = Number(process.env.TRANSCRIPT_KEEP_DAYS ?? 365) || 365;
const MAX_TEXT = 8000;

/** The words as spoken: without the app's own notes, mood tags and "[did: …]" markers. */
export function spokenWords(text: string): string {
  return text
    .replace(/\[Background job[\s\S]*?\[End of background note\]/g, "")
    .replace(/\s*\[mood:[^\]]*\]\s*$/i, "")
    .replace(/\s*\[did:[^\]]*\]/gi, "")
    .replace(/ … \[(interrupted by the user|reply cut off by an error)\]/g, " …")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_TEXT);
}

/** Turn free text into a safe full-text query: each word quoted, any of them may match. */
function matchQuery(text: string): string {
  const words = (text.toLowerCase().match(/[\p{L}\p{N}]{2,}/gu) ?? []).filter((w) => !STOP.has(w));
  return [...new Set(words)].slice(0, 12).map((w) => `"${w}"`).join(" OR ");
}
const STOP = new Set("the and for that this with from have what when where who how did was were are you your our about does not but they them their his her its can could would should will just like any all tell told said say know remember".split(" "));

class Transcripts {
  private db: DatabaseSync;
  private lastAt = 0;

  constructor() {
    fs.mkdirSync(config.dataDir, { recursive: true });
    this.db = new DatabaseSync(FILE);
    try {
      fs.chmodSync(FILE, 0o600);
    } catch {
      /* best effort */
    }
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS exchanges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session TEXT NOT NULL,
        at INTEGER NOT NULL,
        user TEXT NOT NULL,
        assistant TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS exchanges_session ON exchanges (session, id);
      CREATE VIRTUAL TABLE IF NOT EXISTS exchanges_fts USING fts5(user, assistant, tokenize = 'porter unicode61');
    `);
    this.prune();
    this.lastAt = Number((this.db.prepare("SELECT MAX(at) AS at FROM exchanges").get() as any)?.at ?? 0);
  }

  /** Save one exchange. Returns its id, or 0 when there was nothing to save. */
  record(session: string, userText: string, assistantText: string): number {
    const user = spokenWords(userText);
    const assistant = spokenWords(assistantText);
    if (!user) return 0; // a note from the app, not something the person said
    try {
      const at = Date.now();
      const info = this.db.prepare("INSERT INTO exchanges (session, at, user, assistant) VALUES (?, ?, ?, ?)").run(session.slice(0, 64), at, user, assistant);
      const id = Number(info.lastInsertRowid);
      this.db.prepare("INSERT INTO exchanges_fts (rowid, user, assistant) VALUES (?, ?, ?)").run(id, user, assistant);
      this.lastAt = at;
      return id;
    } catch (err) {
      console.warn(`[transcripts] couldn't save an exchange: ${(err as Error).message}`);
      return 0;
    }
  }

  /** When the last exchange was saved (0 if never). */
  get lastActivity(): number {
    return this.lastAt;
  }

  get newestId(): number {
    return Number((this.db.prepare("SELECT MAX(id) AS id FROM exchanges").get() as any)?.id ?? 0);
  }

  count(afterId = 0): number {
    return Number((this.db.prepare("SELECT COUNT(*) AS n FROM exchanges WHERE id > ?").get(afterId) as any).n);
  }

  get(id: number): Exchange | null {
    const r = this.db.prepare("SELECT * FROM exchanges WHERE id = ?").get(id);
    return r ? this.row(r) : null;
  }

  /** Exchanges after `afterId`, oldest first. */
  since(afterId: number, limit = 400): Exchange[] {
    return this.db.prepare("SELECT * FROM exchanges WHERE id > ? ORDER BY id LIMIT ?").all(afterId, limit).map((r) => this.row(r));
  }

  /** An exchange with the ones just before and after it in the same conversation. */
  around(id: number, each = 2): Exchange[] {
    const hit = this.get(id);
    if (!hit) return [];
    const before = this.db.prepare("SELECT * FROM exchanges WHERE session = ? AND id < ? ORDER BY id DESC LIMIT ?").all(hit.session, id, each).map((r) => this.row(r)).reverse();
    const after = this.db.prepare("SELECT * FROM exchanges WHERE session = ? AND id > ? ORDER BY id LIMIT ?").all(hit.session, id, each).map((r) => this.row(r));
    return [...before, hit, ...after];
  }

  /** The exchanges that best match some words, best first. */
  search(text: string, limit = 5): Exchange[] {
    const query = matchQuery(text);
    if (!query) return [];
    try {
      return this.db
        .prepare("SELECT e.* FROM exchanges_fts f JOIN exchanges e ON e.id = f.rowid WHERE exchanges_fts MATCH ? ORDER BY bm25(exchanges_fts) LIMIT ?")
        .all(query, limit)
        .map((r) => this.row(r));
    } catch (err) {
      console.warn(`[transcripts] search failed: ${(err as Error).message}`);
      return [];
    }
  }

  /** Forget everything (used when the person clears Cipher's memory). */
  clear(): void {
    this.db.exec("DELETE FROM exchanges; DELETE FROM exchanges_fts;");
    this.lastAt = 0;
  }

  private prune(): void {
    const cutoff = Date.now() - KEEP_DAYS * 24 * 60 * 60 * 1000;
    const old = this.db.prepare("SELECT id FROM exchanges WHERE at < ?").all(cutoff) as { id: number }[];
    if (!old.length) return;
    const drop = this.db.prepare("DELETE FROM exchanges_fts WHERE rowid = ?");
    for (const { id } of old) drop.run(id);
    this.db.prepare("DELETE FROM exchanges WHERE at < ?").run(cutoff);
  }

  private row(r: any): Exchange {
    return { id: Number(r.id), session: String(r.session), at: Number(r.at), user: String(r.user), assistant: String(r.assistant) };
  }
}

/** A short date for showing an exchange to the model, e.g. "3 Nov 2026, 14:05". */
export function when(at: number): string {
  return new Date(at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const transcripts = new Transcripts();
