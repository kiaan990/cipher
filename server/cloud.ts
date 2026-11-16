import { execFile } from "node:child_process";
import type Anthropic from "@anthropic-ai/sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { config } from "./config.js";
import { approvals, type UserTurn } from "./approvals.js";
import { addDays, dateOf, daysBetween, longDate, relative, today, weekdayLegend } from "./clock.js";

/**
 * The user's cloud server (kiaan-cloud). It runs an MCP server; Cipher connects to it as
 * a client and offers its tools to Claude as "cloud_<name>". Looking things up, adding
 * and changing run straight away; deleting needs the user's spoken OK first (set
 * CLOUD_CONFIRM=all to ask before every change).
 *
 * Cipher does not leave the details to the model. Before an event is added it picks a
 * real calendar (by rule, never a silent guess), refuses dates that are plainly in the
 * past, and skips duplicates; after, it tells the model exactly what is now there.
 * Calendar reads are kept for a few seconds and handed over as short lines, not raw JSON.
 * The URL and token come from .env (KIAAN_MCP_URL, KIAAN_MCP_TOKEN) and stay on the server.
 */

const PREFIX = "cloud_";
const CALL_TIMEOUT_MS = 25_000;
const MAX_RESULT_CHARS = 12_000;
/** A saved brief is the whole point of asking for it, so it gets more room before being cut. */
const MAX_BRIEF_CHARS = 40_000;
const BRIEFS_FRESH_MS = 5 * 60_000;
/** Tool names that only read. Anything else counts as a change unless the server marks it read-only. */
const READ_NAME = /^(get|list|read|search|find|fetch|query|lookup|show|view|status|server_status|ask|brief_get|brief_list|activity_log|calendar_events|calendar_list|tasks_list)/i;

type Report = (e: { id: string; kind: string; purpose: string; command: string; status: string; detail?: string }) => void;

interface CalEvent {
  uid?: string;
  title?: string;
  start?: string;
  end?: string;
  all_day?: boolean;
  calendar?: string;
  location?: string;
  notes?: string;
}

type RawResult = { text: string; isError: boolean; data: unknown };

/** How long a calendar read is reused. Short: the calendar can change from elsewhere. */
const READS_FRESH_MS = 20_000;

interface CachedRead {
  at: number;
  /** The whole days this read covers (start inclusive, end exclusive); "" if unknown. */
  start: string;
  end: string;
  /** False when the read was narrowed (to one calendar, say), so it can't stand in for a day. */
  whole: boolean;
  promise: Promise<RawResult>;
}

/**
 * Which calendar an event belongs in when none was named, by what it is. Checked in
 * order; only calendars that exist are used.
 */
const CALENDAR_RULES: Array<[string, RegExp]> = [
  ["University", /\b(speakers?|guest (talk|lecture)|lectures?|seminars?|campus|class(es)?|exams?|midterms?|finals|final exam|university|college|professor|office hours|advis[eo]r|club|career fair|study group|orientation|workshop|recitation)\b/i],
  ["Travel", /\b(flights?|airport|hotel|trip|airbnb|boarding|layover)\b/i],
  ["Fitness", /\b(gym|workout|work out|go(ing)? for a run|running|yoga|lifting|weights|pilates|swim(ming)?|hik(e|ing)|basketball|soccer|tennis)\b/i],
  ["Work", /\b(shift|clients?|stand-?up|coworkers?|boss|manager|payroll)\b/i],
  ["Personal", /\b(dinner|lunch|brunch|birthday|doctor|dentist|haircut|party|family|mom|dad|friends?|appointment|movie|concert)\b/i],
];

/** "ST-113", "st 113", "Personal " -> "st113", "personal": how names are compared. */
const norm = (s: unknown) => String(s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** The value inside the server's {"result": ...} wrapper (which may itself be JSON text). */
function unwrap(text: string): unknown {
  try {
    let v: unknown = JSON.parse(text);
    if (v && typeof v === "object" && !Array.isArray(v) && "result" in v) v = (v as { result: unknown }).result;
    if (typeof v === "string") {
      try {
        v = JSON.parse(v);
      } catch {
        /* plain text */
      }
    }
    return v;
  } catch {
    return null;
  }
}

/** A promise that also gives up when the caller is cancelled (the work itself carries on for others). */
function orAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(new Error("Cancelled."));
    if (signal.aborted) return onAbort();
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

/**
 * Events as short lines, earliest first, instead of the server's raw JSON: a week is
 * about a quarter of the size, which is most of what made calendar answers slow.
 */
function formatEvents(list: CalEvent[]): string {
  const events = list.filter((e) => e && typeof e === "object");
  if (!events.length) return "No events in that range.";
  const notesMax = events.length <= 12 ? 160 : 60;
  const sorted = [...events].sort((a, b) => String(a.start ?? "").localeCompare(String(b.start ?? "")));
  const lines = sorted.map((e) => {
    const date = dateOf(e.start);
    let when: string;
    if (e.all_day || !clockTime(e.start)) {
      const last = dateOf(e.end) ? addDays(dateOf(e.end), -1) : date;
      when = date && last > date ? `all day, through ${last}` : "all day";
    } else {
      const endDate = dateOf(e.end);
      const endTime = clockTime(e.end);
      when = clockTime(e.start) + (endTime ? `–${endDate && endDate !== date ? `${endDate} ` : ""}${endTime}` : "");
    }
    const notes = String(e.notes ?? "").replace(/\s+/g, " ").trim();
    const place = String(e.location ?? "").replace(/\s+/g, " ").trim();
    return [
      `- ${date || String(e.start ?? "?")}`,
      when,
      String(e.title ?? "(no title)").trim(),
      `calendar: ${String(e.calendar ?? "?").trim()}`,
      place ? `at: ${place.slice(0, 80)}` : "",
      e.uid ? `uid: ${e.uid}` : "",
      notes ? `notes: ${notes.length > notesMax ? `${notes.slice(0, notesMax)}…` : notes}` : "",
    ]
      .filter(Boolean)
      .join(" | ");
  });
  return [`${events.length} event${events.length === 1 ? "" : "s"}, earliest first (times are local):`, ...lines].join("\n");
}

/** "2026-11-17T14:30-05:00" -> "2:30 PM" ("" for a date with no time). */
function clockTime(value: unknown): string {
  const m = /T(\d{2}):(\d{2})/.exec(String(value ?? ""));
  if (!m) return "";
  const h = Number(m[1]);
  return `${h % 12 || 12}:${m[2]} ${h < 12 ? "AM" : "PM"}`;
}

interface CloudTool {
  name: string;
  readOnly: boolean;
  destructive: boolean;
  tool: Anthropic.Tool;
}

class Cloud {
  private client: Client | null = null;
  private connecting: Promise<boolean> | null = null;
  private list: CloudTool[] = [];
  private retryAt = 0;
  /** Short names of the saved briefs ("brightspace", "week-ahead"), newest first. */
  private briefs: { at: number; names: string[] } = { at: 0, names: [] };
  /** The calendars' real names, exactly as the server spells them (some end in a space). */
  private calendars: string[] = [];
  /** Calendar reads from the last few seconds, so the same days aren't fetched twice. */
  private reads = new Map<string, CachedRead>();
  /** Events being added right now, so the same one asked for twice at once is added once. */
  private creating = new Set<string>();
  lastError = "";

  get configured(): boolean {
    return !!config.cloudMcpUrl;
  }

  get connected(): boolean {
    return !!this.client && this.list.length > 0;
  }

  /** Connect in the background (safe to call often). */
  preload(): void {
    if (this.configured && !this.client && Date.now() >= this.retryAt) void this.connect();
  }

  private connect(): Promise<boolean> {
    if (this.connecting) return this.connecting;
    this.connecting = (async () => {
      const url = new URL(config.cloudMcpUrl);
      const headers: Record<string, string> = config.cloudMcpToken ? { Authorization: `Bearer ${config.cloudMcpToken}` } : {};
      const attempt = async (kind: "http" | "sse") => {
        const client = new Client({ name: "cipher", version: "1.0.0" });
        const transport =
          kind === "http"
            ? new StreamableHTTPClientTransport(url, { requestInit: { headers } })
            : new SSEClientTransport(url, {
                requestInit: { headers },
                fetch: (u: string | URL, init?: RequestInit) => {
                  const h = new Headers(init?.headers);
                  for (const [k, v] of Object.entries(headers)) h.set(k, v);
                  return fetch(u, { ...init, headers: h });
                },
              });
        await client.connect(transport);
        return client;
      };
      try {
        let client: Client;
        try {
          client = await attempt("http");
        } catch (err) {
          // Older servers speak the SSE transport instead.
          client = await attempt("sse").catch(() => {
            throw err;
          });
        }
        const { tools } = await client.listTools();
        this.list = tools
          .filter((t) => /^[a-zA-Z0-9_-]{1,57}$/.test(t.name))
          .map((t) => {
            const ann = (t.annotations ?? {}) as { readOnlyHint?: boolean; destructiveHint?: boolean };
            const readOnly = ann.readOnlyHint ?? READ_NAME.test(t.name);
            const destructive = ann.destructiveHint ?? /delete|remove|trash|drop|wipe/i.test(t.name);
            return {
              name: t.name,
              readOnly,
              destructive,
              tool: {
                name: PREFIX + t.name,
                description: `[Your cloud server] ${(t.description ?? t.name).slice(0, 900)}${readOnly ? "" : destructive || config.cloudConfirm === "all" ? " (Needs the user's OK first.)" : " (Runs straight away, no OK needed.)"}`,
                input_schema: (t.inputSchema as Anthropic.Tool["input_schema"]) ?? { type: "object", properties: {} },
              },
            };
          });
        this.client = client;
        client.onclose = () => {
          this.client = null;
        };
        this.lastError = "";
        console.log(`  Cloud server: connected (${this.list.length} tools: ${this.list.map((t) => t.name).join(", ")}).`);
        void this.loadBriefs(true);
        void this.loadCalendars();
        return true;
      } catch (err) {
        this.client = null;
        this.lastError = (err as Error).message;
        this.retryAt = Date.now() + 60_000;
        // The address is the only secret guarding the cloud server, so it never goes in the log.
        console.warn(`[cloud] couldn't connect to the cloud server: ${this.lastError.replaceAll(url.host, "<cloud server>").replaceAll(url.pathname, "/<hidden>")}`);
        return false;
      } finally {
        this.connecting = null;
      }
    })();
    return this.connecting;
  }

  /**
   * Learn which briefs exist. The server only finds a brief by its exact short name
   * ("brightspace", not "Brightspace" or "brightspace sync"), so Cipher keeps the list
   * and corrects the name itself rather than reporting "not found".
   */
  private async loadBriefs(force = false): Promise<void> {
    if (!this.client || !this.list.some((t) => t.name === "brief_list")) return;
    if (!force && Date.now() - this.briefs.at < BRIEFS_FRESH_MS) return;
    try {
      const r = await this.client.callTool({ name: "brief_list", arguments: {} }, undefined, { timeout: 10_000 });
      const parts = (r.content as Array<{ type: string; text?: string }> | undefined) ?? [];
      const text = parts.map((p) => p.text ?? "").join("\n") + (r.structuredContent ? JSON.stringify(r.structuredContent) : "");
      const files = [...new Set(text.match(/[A-Za-z0-9][\w.-]*\.md/g) ?? [])].sort().reverse();
      const names = [...new Set(files.map(briefKey).filter(Boolean))];
      if (names.length) {
        this.briefs = { at: Date.now(), names };
        console.log(`[cloud] briefs: ${names.join(", ")}`);
      }
    } catch (err) {
      console.warn(`[cloud] couldn't list briefs: ${(err as Error).message.replace(/https?:\/\/\S+/g, "<cloud server>")}`);
    }
  }

  /** One call to the server, with no checks: text back, and whether it failed. */
  private async raw(name: string, input: Record<string, unknown>, signal?: AbortSignal): Promise<RawResult> {
    const timeout = AbortSignal.timeout(CALL_TIMEOUT_MS);
    const r = await this.client!.callTool({ name, arguments: input }, undefined, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout, timeout: CALL_TIMEOUT_MS });
    const parts = (r.content as Array<{ type: string; text?: string }> | undefined) ?? [];
    let text = parts.map((p) => (p.type === "text" ? p.text ?? "" : `[${p.type}]`)).join("\n").trim();
    if (!text && r.structuredContent) text = JSON.stringify(r.structuredContent);
    // A list comes back either as {"result": [...]} or as one piece of JSON per item.
    const structured = r.structuredContent as { result?: unknown } | undefined;
    let data: unknown = structured && "result" in structured ? structured.result : null;
    if (typeof data === "string") data = unwrap(data) ?? data;
    if (!Array.isArray(data)) {
      const each = parts.filter((p) => p.type === "text").map((p) => unwrap(p.text ?? ""));
      if (each.length === 1 && each[0] !== null) data = each[0];
      else if (each.length > 1 && each.every((v) => v && typeof v === "object")) data = each.flat();
    }
    return { text, isError: !!r.isError, data };
  }

  /**
   * A plain call for the app's own use (the Muse mailbox), not offered to the model.
   * Null when the server can't be reached.
   */
  async direct(name: string, input: Record<string, unknown>): Promise<{ text: string; isError: boolean; data: unknown } | null> {
    if (!this.configured) return null;
    if (!this.client && !(Date.now() >= this.retryAt && (await this.connect()))) return null;
    if (!this.has(name)) return null;
    try {
      return await this.raw(name, input);
    } catch (err) {
      this.lastError = (err as Error).message;
      this.client = null; // a dropped connection: reconnect next time
      return null;
    }
  }

  /** The tools that can't delete anything: what a message arriving by text (through Muse) may use. */
  safeTools(): Anthropic.Tool[] {
    this.preload();
    return this.connected ? this.list.filter((t) => !t.destructive).map((t) => t.tool) : [];
  }

  /** The tools that never need the user's OK: what background work may use without being able to ask. */
  freeTools(): Anthropic.Tool[] {
    this.preload();
    return this.connected ? this.list.filter((t) => !this.needsOk(t)).map((t) => t.tool) : [];
  }

  private has(name: string): boolean {
    return this.list.some((t) => t.name === name);
  }

  /** Learn the calendars' names, so an event always goes into one that exists. */
  private async loadCalendars(): Promise<void> {
    if (!this.client || !this.has("calendar_list_calendars")) return;
    try {
      this.readCalendars((await this.raw("calendar_list_calendars", {})).data);
    } catch (err) {
      console.warn(`[cloud] couldn't list calendars: ${(err as Error).message.replace(/https?:\/\/\S+/g, "<cloud server>")}`);
    }
  }

  private readCalendars(v: unknown): void {
    if (!Array.isArray(v)) return;
    const names = v.map((c) => (c && typeof c === "object" ? String((c as { name?: unknown }).name ?? "") : "")).filter((n) => n.trim());
    if (!names.length) return;
    if (names.join("|") !== this.calendars.join("|")) console.log(`[cloud] calendars: ${names.map((n) => n.trim()).join(", ")}`);
    this.calendars = names;
  }

  /** The real calendar a spoken name means ("personal" -> "Personal "), or null. */
  private matchCalendar(asked: unknown): string | null {
    const want = norm(asked);
    if (!want) return null;
    return (
      this.calendars.find((c) => norm(c) === want) ??
      this.calendars.find((c) => norm(c).includes(want) || want.includes(norm(c))) ??
      null
    );
  }

  /** A course calendar named in some text ("ST 113 project", "st113_1: Project 2" -> "ST-113"). */
  private courseCalendar(text: string): string | null {
    const hay = norm(text);
    return this.calendars.find((c) => /^[a-z]{2,4}\d{3}$/.test(norm(c)) && hay.includes(norm(c))) ?? null;
  }

  /** What is on the calendar on one day (null if it couldn't be read). */
  /** Events seen lately, by uid, so one can be found again when it has to be deleted. */
  private seen = new Map<string, CalEvent>();

  private remember(list: unknown): void {
    if (!Array.isArray(list)) return;
    for (const e of list as CalEvent[]) if (e?.uid && e.title) this.seen.set(e.uid, e);
    while (this.seen.size > 400) this.seen.delete(this.seen.keys().next().value as string);
  }

  /**
   * The cloud server's delete often answers "uid not found" for events that are there.
   * On this Mac the same iCloud calendars are in the Calendar app, so remove it there:
   * the change syncs back. Matches calendar, exact title and day; refuses anything vague.
   */
  private deleteOnMac(e: CalEvent, signal: AbortSignal): Promise<string | null> {
    const date = dateOf(e.start);
    if (config.hosted || process.platform !== "darwin" || !date || !e.title || !e.calendar) return Promise.resolve(null);
    const [y, m, d] = date.split("-").map(Number);
    const q = (v: string) => `"${v.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
    const script = [
      'tell application "Calendar"',
      "set d1 to current date",
      "set day of d1 to 1",
      `set year of d1 to ${y}`,
      `set month of d1 to ${m}`,
      `set day of d1 to ${d}`,
      "set time of d1 to 0",
      "set d2 to d1 + 1 * days",
      `set evs to (every event of calendar ${q(e.calendar)} whose summary is ${q(e.title)} and start date ≥ d1 and start date < d2)`,
      "set n to count of evs",
      // Not here yet: an event made a moment ago may not have synced to this Mac. Fetch and look once more.
      "if n is 0 then",
      "reload calendars",
      "delay 6",
      `set evs to (every event of calendar ${q(e.calendar)} whose summary is ${q(e.title)} and start date ≥ d1 and start date < d2)`,
      "set n to count of evs",
      "end if",
      "if n is 1 then delete (item 1 of evs)",
      "return n",
      "end tell",
    ].join("\n");
    return new Promise((resolve) => {
      execFile("/usr/bin/osascript", ["-e", script], { timeout: 30_000, signal }, (err, out) => {
        const n = Number(String(out).trim());
        if (err || !Number.isFinite(n)) return resolve(null);
        resolve(n === 1 ? "deleted" : n === 0 ? null : "several");
      });
    });
  }

  /**
   * Read events, reusing a read of the same range made in the last few seconds (or one
   * still on its way). The read isn't tied to one caller, so a cancelled caller doesn't
   * spoil it for the others.
   */
  private readEvents(input: Record<string, unknown>, signal?: AbortSignal): Promise<RawResult> {
    const key = JSON.stringify(input);
    const now = Date.now();
    for (const [k, v] of this.reads) if (now - v.at > READS_FRESH_MS) this.reads.delete(k);
    let hit = this.reads.get(key);
    if (!hit) {
      const hasTime = (v: unknown) => /T\d{2}:/.test(String(v ?? ""));
      const start = dateOf(input.start);
      const entry: CachedRead = {
        at: now,
        start: start && hasTime(input.start) ? addDays(start, 1) : start,
        end: dateOf(input.end),
        whole: Object.keys(input).every((k) => k === "start" || k === "end"),
        promise: this.raw("calendar_events", input),
      };
      const drop = () => {
        if (this.reads.get(key) === entry) this.reads.delete(key);
      };
      entry.promise.then((r) => {
        if (r.isError || !Array.isArray(r.data)) drop();
        else this.remember(r.data);
      }, drop);
      this.reads.set(key, entry);
      hit = entry;
    }
    return orAbort(hit.promise, signal);
  }

  /** What is on the calendar on one day (null if it couldn't be read). */
  private async eventsOn(date: string, signal?: AbortSignal): Promise<CalEvent[] | null> {
    if (!this.has("calendar_events")) return null;
    const onDay = (r: RawResult) => (r.isError || !Array.isArray(r.data) ? null : (r.data as CalEvent[]).filter((e) => e && dateOf(e.start) === date));
    try {
      // A week read a moment ago already holds this day.
      const now = Date.now();
      const covering = [...this.reads.values()].find((v) => v.whole && now - v.at <= READS_FRESH_MS && v.start && v.end && v.start <= date && date < v.end);
      if (covering) {
        const got = await orAbort(covering.promise, signal).then(onDay, () => null);
        if (got) return got;
        if (signal?.aborted) return null;
      }
      return onDay(await this.readEvents({ start: date, end: addDays(date, 1) }, signal));
    } catch {
      return null;
    }
  }

  /** Put a just-added event into the reads being kept, so they stay true without reading again. */
  private noteCreated(made: CalEvent): void {
    const date = dateOf(made.start);
    for (const [key, v] of this.reads) {
      if (!v.whole || !v.start || !v.end || !date) this.reads.delete(key);
      else if (v.start <= date && date < v.end) void v.promise.then((r) => Array.isArray(r.data) && (r.data as CalEvent[]).push(made), () => {});
    }
    this.remember([made]);
  }

  /**
   * The calendar an event goes in. Never a silent guess: the one named, else the course
   * it mentions, else a rule by what it is (a speaker event is University), else the
   * default if one was set. Otherwise the model is told to ask.
   */
  private pickCalendar(args: Record<string, unknown>, user: UserTurn): { calendar: string; how: "named" | "course" | "rule" | "default" } | { stop: string } {
    const names = this.calendars.map((c) => c.trim()).join(", ");
    const named = typeof args.calendar === "string" && args.calendar.trim() ? args.calendar : "";
    if (named) {
      const real = this.matchCalendar(named);
      return real ? { calendar: real, how: "named" } : { stop: `Not done: there is no calendar called "${named}". The calendars are: ${names}. Call this again with one of those.` };
    }
    const about = `${args.title ?? ""} ${args.notes ?? ""}`;
    const course = this.courseCalendar(about) ?? this.courseCalendar(user.text);
    if (course) return { calendar: course, how: "course" };
    const rules = (text: string) => CALENDAR_RULES.filter(([name, re]) => re.test(text) && this.matchCalendar(name)).map(([name]) => this.matchCalendar(name)!);
    const byEvent = rules(about);
    if (byEvent.length) return { calendar: byEvent[0], how: "rule" };
    // What the user said may cover several things at once, so it only counts when it points one way.
    const bySaid = [...new Set(rules(user.text))];
    if (bySaid.length === 1) return { calendar: bySaid[0], how: "rule" };
    const fallback = this.matchCalendar(config.cloudDefaultCalendar);
    if (fallback) return { calendar: fallback, how: "default" };
    return {
      stop: `Not done: no calendar was chosen and this one isn't obvious. The calendars are: ${names}. If one clearly fits what the user said, call this again with it as "calendar". Otherwise ask the user which calendar, in one short sentence, and wait.`,
    };
  }

  /** Changes that wait for a spoken yes: deleting always; everything else only if set so. */
  private needsOk(t: CloudTool): boolean {
    return config.cloudConfirm === "all" ? !t.readOnly : t.destructive;
  }

  /** A date far in the past that the user never asked for is a mistake, not a request. */
  private pastDate(date: string, user: UserTurn): string | null {
    if (!date || daysBetween(today(), date) >= -7) return null;
    const said = user.text.toLowerCase();
    if (said.includes(date.slice(0, 4)) || /\b(last|yesterday|ago|past|earlier|previous)\b/.test(said)) return null;
    return `Not done: ${date} is ${longDate(date)}, ${relative(date)}, which is in the past. Today is ${longDate(today())} (${today()}). Work out the date again from the clock note or from the task or brief it came from, and call this again with the right one. If they really did mean a past date, ask them.`;
  }

  /**
   * Put an event request right before it is sent: a real calendar, all-day when only a
   * date was given, no past dates by mistake, no duplicates. Returns either the corrected
   * input or the reply to give instead of calling the server.
   */
  private async prepareEvent(args: Record<string, unknown>, user: UserTurn, signal: AbortSignal): Promise<{ args: Record<string, unknown>; picked: string } | { stop: string; isError: boolean }> {
    const date = dateOf(args.start);
    if (!date) return { stop: `Not done: "start" must be a date like ${addDays(today(), 1)} or a date and time like ${addDays(today(), 1)}T15:00. Take it from the clock note.`, isError: true };
    const past = this.pastDate(date, user);
    if (past) return { stop: past, isError: true };
    const out = { ...args };
    if (/^\s*\d{4}-\d{2}-\d{2}\s*$/.test(String(args.start))) out.all_day = true;

    let picked = "";
    if (!this.calendars.length) await this.loadCalendars();
    if (this.calendars.length) {
      const choice = this.pickCalendar(args, user);
      if ("stop" in choice) return { stop: choice.stop, isError: true };
      out.calendar = choice.calendar;
      if (choice.how !== "named") picked = choice.how;
    }

    const there = await this.eventsOn(date, signal);
    const same = there?.find((e) => norm(e.title) === norm(out.title) && (!out.calendar || norm(e.calendar) === norm(out.calendar)));
    if (same) {
      const when = same.all_day ? "all day" : `at ${clockTime(same.start)}`;
      return { stop: `Already there, nothing added: "${same.title}" is on ${longDate(date)}, ${when}, in the ${String(same.calendar ?? "").trim()} calendar. Tell the user it's already on their calendar for that day.`, isError: false };
    }
    return { args: out, picked };
  }

  /** After adding an event, read the day back and say exactly what is there. */
  private async confirmEvent(args: Record<string, unknown>, uid: string, signal: AbortSignal): Promise<string> {
    const date = dateOf(args.start);
    const there = await this.eventsOn(date, signal);
    const titled = there?.filter((e) => norm(e.title) === norm(args.title)) ?? [];
    const made = titled.find((e) => uid && e.uid === uid) ?? titled.find((e) => norm(e.calendar) === norm(args.calendar)) ?? titled[0];
    if (!made) return `[The app could not see "${args.title}" on ${longDate(date)} when it checked the calendar. Tell the user you tried to add it but couldn't confirm it's there.]`;
    const when = made.all_day ? "all day" : `at ${clockTime(made.start)}`;
    return `[Checked by the app: "${made.title}" is now on ${longDate(date)} (${relative(date)}), ${when}, in the ${String(made.calendar ?? "").trim()} calendar. Tell the user exactly that: the day, the date and the calendar.]`;
  }

  /** The real brief name closest to what was asked for, or null if nothing is close. */
  private matchBrief(asked: string): string | null {
    const want = briefKey(asked);
    const names = this.briefs.names;
    if (!want || !names.length) return null;
    if (names.includes(want)) return want;
    // "brightspace-sync", "brightspace-grades" -> "brightspace": the longest name the request contains.
    const inside = names.filter((n) => want.startsWith(n) || want.includes(n)).sort((a, b) => b.length - a.length)[0];
    if (inside) return inside;
    // "week" -> "week-ahead": the shortest name that contains the request.
    const around = names.filter((n) => n.includes(want)).sort((a, b) => a.length - b.length)[0];
    if (around) return around;
    const first = want.split("-")[0];
    return first.length >= 4 ? names.filter((n) => n.startsWith(first)).sort((a, b) => a.length - b.length)[0] ?? null : null;
  }

  tools(): Anthropic.Tool[] {
    this.preload();
    return this.connected ? this.list.map((t) => t.tool) : [];
  }

  /** Something to say before a call, so the wait isn't silent. Not for changes that ask first. */
  preamble(name: string): string | undefined {
    const t = this.list.find((x) => PREFIX + x.name === name);
    if (!t || this.needsOk(t)) return undefined;
    if (!t.readOnly) return "On it.";
    const lines = ["One sec.", "Let me check.", "Checking.", "Hang on, let me look."];
    return lines[Math.floor(Math.random() * lines.length)];
  }

  owns(name: string): boolean {
    return name.startsWith(PREFIX) && this.list.some((t) => PREFIX + t.name === name);
  }

  /** True for a tool that only looks something up. */
  isRead(name: string): boolean {
    return this.list.find((t) => PREFIX + t.name === name)?.readOnly ?? false;
  }

  describe(): string {
    if (!this.configured) return "";
    if (!this.connected)
      return "The user's cloud server (kiaan-cloud) isn't reachable right now. If they ask for something from it, say you can't reach their cloud server at the moment.";
    return [
      "You're connected to the user's own cloud server, kiaan-cloud, through the cloud_ tools. It holds their most current information: tasks, calendar, saved briefs (including school and Brightspace details), notes and an activity log.",
      "- When they ask about their schedule, assignments, deadlines, tasks, classes, briefs or anything they keep there, look it up with these tools instead of guessing, then answer in a sentence or two.",
      config.cloudConfirm === "all"
        ? "- Looking things up needs no permission. Anything that adds, changes, completes or deletes something needs their OK: call the tool, and if it says it needs approval, ask them in one short sentence and wait."
        : "- Looking things up, adding events and tasks, changing them and marking them done all run straight away: when they ask for one, call the tool at once, don't ask \"shall I?\" first. Only deleting needs their OK: call the tool, and when it says it needs approval, ask in one short sentence what you'd delete and wait.",
      "- Their calendar and tasks live on this server (it syncs to Apple Calendar on its own). For anything about calendar events or tasks use only the cloud_ tools: never the Mac's Calendar or Reminders apps, never the screen.",
      this.calendars.length
        ? `- Their calendars: ${this.calendars.map((c) => c.trim()).join(", ")}. When adding an event, always give "calendar". School work goes in that course's calendar (an ST-113 project goes in ST-113); talks, speakers and campus events go in University. If it isn't clear which calendar, ask which one in a few words; never guess. Always say which calendar it went in.`
        : "",
      "- When you need several things from the cloud server (two days, tasks and the calendar, several events to add), ask for them all in the same step: they run at the same time.",
      "- Dates: write them as YYYY-MM-DD, taken from the clock note in their message or from the task or brief the date came from. Never work a date out from memory. For something that is due on a day, or has no time, give just the date as \"start\" (it becomes an all-day event). For a time, use YYYY-MM-DDTHH:MM in their local time.",
      "- To put a task or assignment on the calendar, look it up first (cloud_tasks_list or the brightspace brief) and use its real due date and name.",
      "- Never say something was added, changed or deleted unless the tool result says so. After adding an event, tell them the weekday, the date and the calendar, exactly as the result gives them. If a result says \"Not done\", it didn't happen: fix what it says and call again, or tell them.",
      "- Say dates and times naturally (\"Thursday at nine\"), not as raw timestamps.",
      "- Brightspace (their school site) is synced to this server. For anything about Brightspace, coursework, assignments, what's due, grades or classes, call cloud_brief_get with name \"brightspace\": that is the latest sync, with what's due soon, grades and what's new. For every assignment and grade in full, use name \"brightspace-data\". Never say you can't see or access their Brightspace without calling it first.",
      "- Brief names are lowercase with hyphens. If a brief isn't found, call cloud_brief_list and try again with a name from it before telling them it's missing.",
      this.briefs.names.length ? `- Briefs saved right now: ${this.briefs.names.join(", ")}.` : "",
    ]
      .filter(Boolean)
      .join("\n");
  }

  async run(call: Anthropic.ToolUseBlock, user: UserTurn, signal: AbortSignal, report: Report): Promise<Anthropic.ToolResultBlockParam> {
    const result = (text: string, isError = false): Anthropic.ToolResultBlockParam => ({
      type: "tool_result",
      tool_use_id: call.id,
      content: text,
      is_error: isError || undefined,
    });
    const t = this.list.find((x) => PREFIX + x.name === call.name);
    if (!t) return result("That cloud tool isn't available.", true);
    let args = (call.input ?? {}) as Record<string, unknown>;
    const argText = JSON.stringify(args);
    const purpose = `${t.name.replace(/_/g, " ")} on your cloud server`;
    const event = { id: call.id.slice(-8), kind: "cloud", purpose, command: `${t.name} ${argText === "{}" ? "" : argText}`.trim(), status: "running" };

    if (this.needsOk(t) && !approvals.approved(`cloud\n${t.name}\n${argText}`, user)) {
      report({ ...event, status: "needs_approval", detail: t.destructive ? "it deletes something on your cloud server" : "it changes something on your cloud server" });
      return result(
        t.destructive
          ? `Not done yet: deleting needs the user's OK. Ask them in one short sentence, naming exactly what you'd delete (its title and day), then stop and wait. If they say yes, call this again with exactly the same input. Until then nothing has been deleted, so don't say it has.`
          : `Not done yet: this changes the user's cloud server, so it needs their OK. Ask them in one short sentence (say what you'll do, e.g. "Add 'finish lab report' to your tasks for Friday?"), then stop and wait. If they say yes, call it again with exactly the same input. Until then nothing has changed, so don't say it has.`,
      );
    }

    if (!this.client && !(await this.connect())) {
      report({ ...event, status: "failed", detail: this.lastError });
      return result(`Couldn't reach the cloud server: ${this.lastError}`, true);
    }
    report(event);
    let creatingKey = "";
    let picked = "";
    try {
      const ask = (input: Record<string, unknown>) => (t.name === "calendar_events" ? this.readEvents(input, signal) : this.raw(t.name, input, signal));
      const stop = (text: string, isError: boolean) => {
        report({ ...event, status: isError ? "failed" : "done", detail: text.slice(0, 200) });
        console.log(`[cloud] ${t.name} ${isError ? "refused by the app" : "skipped"}: ${text.slice(0, 120)}`);
        return result(text, isError);
      };
      const isCreate = t.name === "calendar_create_event";
      if (isCreate) {
        const ready = await this.prepareEvent(args, user, signal);
        if ("stop" in ready) return stop(ready.stop, ready.isError);
        args = ready.args;
        picked = ready.picked;
        // The same event asked for twice in one step: the second waits for nothing and adds nothing.
        const key = `${dateOf(args.start)}|${norm(args.title)}|${norm(args.calendar)}`;
        if (this.creating.has(key)) return stop(`Already being added, nothing added twice: "${args.title}" on ${longDate(dateOf(args.start))} is being added by another call in this same step.`, false);
        this.creating.add(key);
        creatingKey = key;
      } else if ((t.name === "tasks_add" || t.name === "tasks_update") && args.due) {
        const past = this.pastDate(dateOf(args.due), user);
        if (past) return stop(past, true);
      }
      // Briefs are found by exact name only, so put right whatever name was asked for.
      const isBrief = t.name === "brief_get" && typeof args.name === "string";
      const asked = isBrief ? String(args.name) : "";
      if (isBrief) {
        await this.loadBriefs();
        const real = this.matchBrief(asked);
        if (real) args = { ...args, name: real };
      }
      let r = await ask(args);
      if (isBrief && /^\W*(\{"result":\s*")?No brief\b/i.test(r.text)) {
        // Maybe it was saved a moment ago: look again, then try the closest name.
        await this.loadBriefs(true);
        const real = this.matchBrief(asked);
        if (real && real !== args.name) {
          args = { ...args, name: real };
          r = await ask(args);
        } else if (this.briefs.names.length) {
          r.text = `There is no brief called "${asked}". The briefs that exist are: ${this.briefs.names.join(", ")}. Call cloud_brief_get again with one of those names exactly (for Brightspace or school work, use "brightspace").`;
        }
      }
      let text = r.text;
      if (t.name === "calendar_events" && !r.isError && Array.isArray(r.data)) text = formatEvents(r.data as CalEvent[]);
      const limit = isBrief ? MAX_BRIEF_CHARS : MAX_RESULT_CHARS;
      if (text.length > limit) text = text.slice(0, limit) + "\n…(cut short)";
      let failed = r.isError;
      const answer = r.data && typeof r.data === "object" && !Array.isArray(r.data) ? (r.data as { ok?: unknown; error?: unknown }) : null;
      if (!failed && answer?.ok === false) {
        // The server answered, but with a no.
        failed = true;
        const known = t.name === "calendar_delete_event" ? this.seen.get(String(args.uid ?? "")) : undefined;
        const local = known ? await this.deleteOnMac(known, signal) : null;
        if (local === "deleted") {
          failed = false;
          this.reads.clear();
          this.seen.delete(known!.uid!);
          text = `Deleted: "${known!.title}" on ${longDate(dateOf(known!.start))} has been removed from the ${known!.calendar!.trim()} calendar (through the Calendar app on this Mac, since the cloud server couldn't find it).`;
          console.log(`[cloud] calendar_delete_event: the server said no, removed in the Calendar app instead`);
        } else if (t.name === "calendar_delete_event") {
          text = `Not done: the event was not deleted (the cloud server said "${String(answer.error ?? "no")}"${local === "several" ? ", and there is more than one event with that title that day" : ""}). ${known ? "" : "Call cloud_calendar_events for that day first so the event is known, then try once more. "}If it still fails, tell the user it couldn't be deleted and they'll need to remove it in Calendar themselves.`;
        } else {
          text = `Not done: the cloud server said "${String(answer.error ?? "no")}". ${text}`;
        }
      }
      if (!failed) {
        if (t.name === "calendar_list_calendars") this.readCalendars(r.data);
        if (t.name === "calendar_delete_event") this.reads.clear();
        if (isCreate) {
          const uid = String((r.data as { uid?: unknown } | null)?.uid ?? "");
          const date = dateOf(args.start);
          if (uid && typeof args.calendar === "string") {
            // The server gave the new event's id, so it is there: no need to read the day back.
            const made: CalEvent = { uid, title: String(args.title ?? ""), start: String(args.start), end: args.end ? String(args.end) : undefined, all_day: args.all_day === true, calendar: args.calendar, location: args.location ? String(args.location) : undefined, notes: args.notes ? String(args.notes) : undefined };
            this.noteCreated(made);
            const when = made.all_day ? "all day" : `at ${clockTime(made.start)}`;
            text += `\n[Confirmed by the cloud server: "${made.title}" is now on ${longDate(date)} (${relative(date)}), ${when}, in the ${args.calendar.trim()} calendar. Tell the user exactly that: the day, the date and the calendar.]`;
          } else {
            this.reads.clear();
            text += `\n${await this.confirmEvent(args, uid, signal)}`;
          }
          if (picked) text += `\n[The calendar wasn't named, so the app chose ${String(args.calendar ?? "").trim()} ${picked === "default" ? "as the default" : picked === "course" ? "from the course it mentions" : "from what kind of event it is"}. Say the calendar so they can correct it.]`;
        }
        const legend = isBrief ? "" : weekdayLegend(text);
        if (legend) text += `\n${legend}`;
      }
      report({ ...event, status: failed ? "failed" : "done", detail: failed ? text.slice(0, 200) : undefined });
      console.log(`[cloud] ${t.name} ${failed ? "failed" : "ok"} (${text.length} chars)`);
      return result(text || "Done.", failed);
    } catch (err) {
      const msg = signal.aborted ? "Cancelled." : (err as Error).message;
      report({ ...event, status: "failed", detail: msg });
      // A dropped connection: reconnect next time.
      if (!signal.aborted) this.client = null;
      return result(`The cloud server didn't answer: ${msg}`, true);
    } finally {
      if (creatingKey) this.creating.delete(creatingKey);
    }
  }
}

/** "2026-11-11_Brightspace Sync.md" -> "brightspace-sync". */
function briefKey(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/\.md$/, "")
    .replace(/^\d{4}-\d{2}-\d{2}[_\s-]+/, "")
    .replace(/[\s_]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/^-+|-+$/g, "");
}

export const cloud = new Cloud();
