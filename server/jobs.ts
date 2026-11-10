/**
 * Background jobs: work that takes longer than a spoken pause.
 *
 * A job is anything Cipher started and stopped waiting for: a shell command that ran
 * past a few seconds, a slow cloud call, or a task handed to Claude Code. Jobs are kept
 * in a small SQLite file so "what's running?" still has an answer after a restart, and
 * so a finished job is announced exactly once, even if nobody was on the page.
 */
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { config } from "./config.js";

export type JobStatus = "running" | "done" | "failed" | "cancelled" | "interrupted";

export interface Job {
  id: number;
  kind: string;
  title: string;
  status: JobStatus;
  progress: string;
  result: string;
  createdAt: number;
  updatedAt: number;
  finishedAt: number | null;
  /** Claude Code's own session id, so a delegated task can be continued later. */
  sessionId: string | null;
  /** The folder a delegated task worked in. */
  folder: string | null;
  announced: boolean;
}

export interface JobHandle {
  id: number;
  signal: AbortSignal;
  /** A short line about what the job is doing right now. */
  progress(line: string): void;
  setSession(sessionId: string): void;
}

/** What a job's work resolves to. */
export interface JobOutcome {
  ok: boolean;
  result: string;
}

const MAX_RESULT = 4000;
const KEEP_FINISHED = 200;

class Jobs extends EventEmitter {
  private db: DatabaseSync;
  private controllers = new Map<number, AbortController>();

  constructor() {
    super();
    fs.mkdirSync(config.dataDir, { recursive: true });
    this.db = new DatabaseSync(path.join(config.dataDir, "jobs.db"));
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        progress TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        finished_at INTEGER,
        session_id TEXT,
        folder TEXT,
        announced INTEGER NOT NULL DEFAULT 0
      );
    `);
    // Anything still marked running belonged to a copy of the app that has stopped.
    const now = Date.now();
    this.db
      .prepare("UPDATE jobs SET status='interrupted', result='The app restarted before this finished.', finished_at=?, updated_at=?, announced=0 WHERE status='running'")
      .run(now, now);
    this.db.prepare("DELETE FROM jobs WHERE status!='running' AND id NOT IN (SELECT id FROM jobs ORDER BY id DESC LIMIT ?)").run(KEEP_FINISHED);
  }

  private row(r: any): Job {
    return {
      id: Number(r.id),
      kind: r.kind,
      title: r.title,
      status: r.status,
      progress: r.progress,
      result: r.result,
      createdAt: Number(r.created_at),
      updatedAt: Number(r.updated_at),
      finishedAt: r.finished_at == null ? null : Number(r.finished_at),
      sessionId: r.session_id ?? null,
      folder: r.folder ?? null,
      announced: Boolean(r.announced),
    };
  }

  get(id: number): Job | null {
    const r = this.db.prepare("SELECT * FROM jobs WHERE id=?").get(id);
    return r ? this.row(r) : null;
  }

  /** Newest first. */
  list(limit = 10): Job[] {
    return this.db.prepare("SELECT * FROM jobs ORDER BY id DESC LIMIT ?").all(limit).map((r) => this.row(r));
  }

  running(): Job[] {
    return this.db.prepare("SELECT * FROM jobs WHERE status='running' ORDER BY id").all().map((r) => this.row(r));
  }

  /** Finished jobs nobody has been told about yet, oldest first. */
  unannounced(): Job[] {
    return this.db.prepare("SELECT * FROM jobs WHERE status!='running' AND announced=0 ORDER BY id").all().map((r) => this.row(r));
  }

  markAnnounced(id: number): void {
    this.db.prepare("UPDATE jobs SET announced=1 WHERE id=?").run(id);
  }

  /**
   * Start a job. `work` runs right away; its outcome is recorded when it settles.
   * `controller` lets a caller hand over work that is already under way.
   */
  start(kind: string, title: string, work: (job: JobHandle) => Promise<JobOutcome>, opts: { controller?: AbortController; folder?: string } = {}): Job {
    const now = Date.now();
    const info = this.db
      .prepare("INSERT INTO jobs (kind, title, status, created_at, updated_at, folder) VALUES (?, ?, 'running', ?, ?, ?)")
      .run(kind, title.slice(0, 200), now, now, opts.folder ?? null);
    const id = Number(info.lastInsertRowid);
    const controller = opts.controller ?? new AbortController();
    this.controllers.set(id, controller);
    console.log(`[jobs] #${id} started (${kind}): ${title.slice(0, 80)}`);

    const handle: JobHandle = {
      id,
      signal: controller.signal,
      progress: (line) => {
        const text = line.replace(/\s+/g, " ").trim().slice(0, 200);
        if (!text || !this.controllers.has(id)) return;
        this.db.prepare("UPDATE jobs SET progress=?, updated_at=? WHERE id=? AND status='running'").run(text, Date.now(), id);
        this.emit("update", this.get(id));
      },
      setSession: (sessionId) => {
        this.db.prepare("UPDATE jobs SET session_id=? WHERE id=?").run(sessionId, id);
      },
    };

    const finish = (status: JobStatus, result: string) => {
      if (!this.controllers.delete(id)) return; // already settled (cancelled, say)
      const at = Date.now();
      this.db
        .prepare("UPDATE jobs SET status=?, result=?, finished_at=?, updated_at=? WHERE id=? AND status='running'")
        .run(status, clip(result), at, at, id);
      const job = this.get(id)!;
      console.log(`[jobs] #${id} ${job.status} after ${Math.round((at - job.createdAt) / 1000)} s`);
      this.emit("update", job);
      this.emit("done", job);
    };
    this.finishers.set(id, finish);

    void Promise.resolve()
      .then(() => work(handle))
      .then(
        (out) => finish(controller.signal.aborted ? "cancelled" : out.ok ? "done" : "failed", out.result),
        (err) => finish(controller.signal.aborted ? "cancelled" : "failed", `It stopped with an error: ${(err as Error)?.message ?? err}`),
      )
      .finally(() => this.finishers.delete(id));

    const job = this.get(id)!;
    this.emit("update", job);
    return job;
  }

  private finishers = new Map<number, (status: JobStatus, result: string) => void>();

  /** Stop a running job (the most recent one if no id is given). Returns it, or null. */
  cancel(id?: number): Job | null {
    const target = id ?? [...this.controllers.keys()].sort((a, b) => b - a)[0];
    if (target == null) return null;
    const controller = this.controllers.get(target);
    if (!controller) return null;
    const finish = this.finishers.get(target);
    controller.abort();
    // The user asked for this, so there is nothing to announce later.
    finish?.("cancelled", "Cancelled when asked.");
    this.markAnnounced(target);
    return this.get(target);
  }

  /** A short note for the model: what is running and what recently finished. */
  describe(): string {
    const running = this.running();
    const recent = this.list(6).filter((j) => j.status !== "running" && Date.now() - (j.finishedAt ?? 0) < 30 * 60_000);
    if (!running.length && !recent.length) return "";
    const lines = ["Background jobs (use jobs_status for detail):"];
    for (const j of running) lines.push(`- Job ${j.id}, running for ${ago(j.createdAt)}: ${j.title}${j.progress ? ` (now: ${j.progress})` : ""}`);
    for (const j of recent.slice(0, 3)) lines.push(`- Job ${j.id}, ${j.status} ${ago(j.finishedAt ?? j.updatedAt)} ago: ${j.title}`);
    return lines.join("\n");
  }
}

function clip(text: string): string {
  const t = text.trim();
  // Keep the end: for commands and agents alike, the conclusion comes last.
  return t.length > MAX_RESULT ? `[earlier output left out]\n${t.slice(-MAX_RESULT)}` : t;
}

export function ago(since: number): string {
  const s = Math.max(0, Math.round((Date.now() - since) / 1000));
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${Math.round(s / 3600)} h`;
}

export const jobs = new Jobs();
