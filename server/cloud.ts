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
 * real calendar, refuses dates that are plainly in the past, and skips duplicates; after,
 * it reads the calendar back and tells the model exactly what is now there.
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
}

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
  private async raw(name: string, input: Record<string, unknown>, signal?: AbortSignal): Promise<{ text: string; isError: boolean; data: unknown }> {
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

  private async eventsOn(date: string, signal?: AbortSignal): Promise<CalEvent[] | null> {
    if (!this.has("calendar_events")) return null;
    try {
      const r = await this.raw("calendar_events", { start: date, end: addDays(date, 1) }, signal);
      const v = r.data;
      if (r.isError || !Array.isArray(v)) return null;
      this.remember(v);
      return (v as CalEvent[]).filter((e) => e && dateOf(e.start) === date);
    } catch {
      return null;
    }
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
  private async prepareEvent(args: Record<string, unknown>, user: UserTurn, signal: AbortSignal): Promise<{ args: Record<string, unknown> } | { stop: string; isError: boolean }> {
    const date = dateOf(args.start);
    if (!date) return { stop: `Not done: "start" must be a date like ${addDays(today(), 1)} or a date and time like ${addDays(today(), 1)}T15:00. Take it from the clock note.`, isError: true };
    const past = this.pastDate(date, user);
    if (past) return { stop: past, isError: true };
    const out = { ...args };
    if (/^\s*\d{4}-\d{2}-\d{2}\s*$/.test(String(args.start))) out.all_day = true;

    if (!this.calendars.length) await this.loadCalendars();
    if (this.calendars.length) {
      const named = typeof args.calendar === "string" && args.calendar.trim() ? args.calendar : "";
      const real = named
        ? this.matchCalendar(named)
        : this.courseCalendar(`${args.title ?? ""} ${args.notes ?? ""}`) ?? this.courseCalendar(user.text) ?? this.matchCalendar(config.cloudDefaultCalendar);
      if (named && !real) return { stop: `Not done: there is no calendar called "${named}". The calendars are: ${this.calendars.map((c) => c.trim()).join(", ")}. Call this again with one of those.`, isError: true };
      if (real) out.calendar = real;
    }

    const there = await this.eventsOn(date, signal);
    const same = there?.find((e) => norm(e.title) === norm(out.title) && (!out.calendar || norm(e.calendar) === norm(out.calendar)));
    if (same) {
      const when = same.all_day ? "all day" : `at ${clockTime(same.start)}`;
      return { stop: `Already there, nothing added: "${same.title}" is on ${longDate(date)}, ${when}, in the ${String(same.calendar ?? "").trim()} calendar. Tell the user it's already on their calendar for that day.`, isError: false };
    }
    return { args: out };
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
      this.calendars.length ? `- Their calendars: ${this.calendars.map((c) => c.trim()).join(", ")}. School work goes in that course's calendar (an ST-113 project goes in ST-113); if nothing fits, leave "calendar" out and the app picks one.` : "",
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
    try {
      const ask = (input: Record<string, unknown>) => this.raw(t.name, input, signal);
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
        if (isCreate) text += `\n${await this.confirmEvent(args, String((r.data as { uid?: unknown } | null)?.uid ?? ""), signal)}`;
        if (t.name === "calendar_events") this.remember(r.data);
        if (t.name === "calendar_events") text += "\n[All-day events list their end as the following day; they are on the start day only.]";
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
