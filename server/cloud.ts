import type Anthropic from "@anthropic-ai/sdk";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import { config } from "./config.js";
import { approvals, type UserTurn } from "./approvals.js";

/**
 * The user's cloud server (kiaan-cloud). It runs an MCP server; Cipher connects to it as
 * a client and offers its tools to Claude as "cloud_<name>". Looking things up runs
 * straight away; anything that changes the server needs the user's spoken OK first.
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
                description: `[Your cloud server] ${(t.description ?? t.name).slice(0, 900)}${readOnly ? "" : " (Changes the server: needs the user's OK.)"}`,
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

  /** Something to say before a lookup, so the wait isn't silent. Not for changes (those ask first). */
  preamble(name: string): string | undefined {
    const t = this.list.find((x) => PREFIX + x.name === name);
    if (!t?.readOnly) return undefined;
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
      "- Looking things up needs no permission. Anything that adds, changes, completes or deletes something on the server needs their OK: call the tool, and if it says it needs approval, ask them in one short sentence and wait.",
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

    if (!t.readOnly && !approvals.approved(`cloud\n${t.name}\n${argText}`, user)) {
      report({ ...event, status: "needs_approval", detail: t.destructive ? "it deletes something on your cloud server" : "it changes something on your cloud server" });
      return result(
        `Not done yet: this changes the user's cloud server, so it needs their OK. Ask them in one short sentence (say what you'll do, e.g. "Add 'finish lab report' to your tasks for Friday?"), then wait. If they say yes, call it again with exactly the same input.`,
      );
    }

    if (!this.client && !(await this.connect())) {
      report({ ...event, status: "failed", detail: this.lastError });
      return result(`Couldn't reach the cloud server: ${this.lastError}`, true);
    }
    report(event);
    try {
      const timeout = AbortSignal.timeout(CALL_TIMEOUT_MS);
      const ask = async (input: Record<string, unknown>) => {
        const r = await this.client!.callTool({ name: t.name, arguments: input }, undefined, { signal: AbortSignal.any([signal, timeout]), timeout: CALL_TIMEOUT_MS });
        const parts = (r.content as Array<{ type: string; text?: string }> | undefined) ?? [];
        let text = parts.map((p) => (p.type === "text" ? p.text ?? "" : `[${p.type}]`)).join("\n").trim();
        if (!text && r.structuredContent) text = JSON.stringify(r.structuredContent);
        return { text, isError: !!r.isError };
      };
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
      const failed = r.isError;
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
