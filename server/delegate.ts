/**
 * Handing real work to Claude Code.
 *
 * Cipher talks; it should not also try to write a program or dig through a folder inside
 * one spoken reply. `delegate` starts Claude Code (the command-line agent installed on
 * this Mac) on a task, in one folder, as a background job. Cipher carries on talking and
 * is told when the work is done.
 *
 * Limits, on purpose:
 *   - it works in one folder inside your home folder, never the home folder itself
 *   - it runs with "accept edits" permissions and a fixed list of tools; permission
 *     checks are never skipped
 *   - it gets none of Cipher's keys: they are removed from its environment
 *   - in "ask" mode every delegation needs your spoken OK first
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type Anthropic from "@anthropic-ai/sdk";
import { config } from "./config.js";
import { approvals, type UserTurn } from "./approvals.js";
import { jobs, type JobHandle, type JobOutcome } from "./jobs.js";
import type { ControlMode } from "./mac.js";

const LIMIT_MS = Number(process.env.DELEGATE_LIMIT_MIN ?? 30) * 60_000;
const MAX_AT_ONCE = 2;
const DEFAULT_TOOLS = "Read,Edit,Write,Glob,Grep,Bash,WebSearch,WebFetch,TodoWrite";
const NEVER = ["Bash(sudo:*)", "Bash(rm -rf /:*)", "Bash(rm -rf ~:*)", "Bash(security:*)", "Bash(launchctl:*)", "Bash(diskutil:*)", "Bash(shutdown:*)", "Bash(reboot:*)"];
/** Anything that looks like a credential stays with Cipher. */
const SECRET = /KEY|TOKEN|SECRET|PASSWORD|KIAAN_MCP|^APP_|DEEPGRAM|ELEVENLABS|ANTHROPIC/i;

type Report = (e: { id: string; kind: string; purpose: string; command: string; status: string; detail?: string }) => void;

function findClaude(): string | null {
  const places = [process.env.CLAUDE_BIN, path.join(os.homedir(), ".local/bin/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"];
  for (const p of places) {
    try {
      if (p && fs.statSync(p).isFile()) return p;
    } catch {
      /* not there */
    }
  }
  return null;
}

const TOOL: Anthropic.Tool = {
  name: "delegate",
  description:
    "Hand a bigger piece of work to Claude Code, a coding agent on this Mac: writing or changing code, building something, researching across many files, anything that needs more than a couple of commands. It runs in the background as a job (minutes, not seconds) and you are told when it finishes, so say you've started it and carry on. Give it a complete brief: it knows nothing about this conversation.",
  input_schema: {
    type: "object",
    properties: {
      purpose: { type: "string", description: "A few words on what this is for, shown to the user." },
      task: { type: "string", description: "The full brief: what to do, where, and what done looks like. Write it for someone who hasn't heard the conversation." },
      folder: { type: "string", description: "The folder to work in, inside the home folder (e.g. ~/projects/site). Leave out for a scratch folder." },
      continue_job: { type: "number", description: "To follow up on an earlier delegated job (same folder, it remembers its work), give that job's number." },
    },
    required: ["purpose", "task"],
  },
};

class Delegate {
  private bin = findClaude();

  available(mode: ControlMode): boolean {
    return !config.hosted && mode !== "off" && Boolean(this.bin);
  }

  owns(name: string): boolean {
    return name === TOOL.name;
  }

  tools(mode: ControlMode): Anthropic.Tool[] {
    return this.available(mode) ? [TOOL] : [];
  }

  describe(mode: ControlMode): string {
    if (!this.available(mode)) return "";
    return [
      "Delegating: for work that needs more than two or three commands (code, multi-step file work, research in a folder), use `delegate` rather than doing it yourself step by step. Say in a few words that you've handed it off, then keep talking normally.",
      mode === "ask" ? "- Delegating needs the user's spoken OK first: say what you'd hand off and where, then wait." : "",
    ]
      .filter(Boolean)
      .join("\n");
  }

  run(call: Anthropic.ToolUseBlock, mode: ControlMode, user: UserTurn, report: Report): Anthropic.ToolResultBlockParam {
    const input = (call.input ?? {}) as Record<string, any>;
    const result = (content: string, isError = false): Anthropic.ToolResultBlockParam => ({ type: "tool_result", tool_use_id: call.id, content, is_error: isError || undefined });
    if (!this.available(mode) || !this.bin) return result("Delegating isn't available right now.", true);

    const task = String(input.task ?? "").trim();
    if (task.length < 10) return result("Give a full brief in `task`: what to do and what done looks like.", true);
    const earlier = input.continue_job != null ? jobs.get(Number(input.continue_job)) : null;
    if (input.continue_job != null && (!earlier || earlier.kind !== "delegate" || !earlier.sessionId || !earlier.folder)) {
      return result(`Job ${input.continue_job} isn't a delegated job that can be continued. Start a new one instead.`, true);
    }
    if (earlier?.status === "running") return result(`Job ${earlier.id} is still running. Wait for it to finish, or cancel it first.`, true);

    // ---- where it may work
    const home = os.homedir();
    let folder = earlier?.folder ?? String(input.folder ?? "").trim();
    if (!folder) {
      folder = path.join(home, "Cipher Work");
      fs.mkdirSync(folder, { recursive: true });
    }
    folder = path.resolve(home, folder.replace(/^~(?=\/|$)/, home));
    let real = "";
    try {
      real = fs.realpathSync(folder);
    } catch {
      return result(`There is no folder at ${folder}. Check the name with the user (or look with a command) before delegating.`, true);
    }
    if (!fs.statSync(real).isDirectory()) return result(`${folder} is a file, not a folder.`, true);
    const inHome = real.startsWith(fs.realpathSync(home) + path.sep);
    if (!inHome || /\/(Library|\.ssh|\.gnupg|\.aws|\.config|\.claude)(\/|$)/.test(real.slice(home.length))) {
      return result("Delegated work must be in an ordinary folder inside the home folder (not the home folder itself, and not Library or settings folders). Ask the user which project folder to use.", true);
    }
    if (jobs.running().filter((j) => j.kind === "delegate").length >= MAX_AT_ONCE) {
      return result(`${MAX_AT_ONCE} delegated jobs are already running. Wait for one to finish or cancel one.`, true);
    }

    const purpose = String(input.purpose ?? "").slice(0, 120) || "delegated work";
    const shown = real.replace(home, "~");
    const event = { id: randomUUID().slice(0, 8), kind: "delegate", purpose: `hand off: ${purpose}`, command: `Claude Code in ${shown}`, status: "running" };
    // The OK is for handing work into this folder: the brief is reworded between asking
    // and doing, so it can't be part of what has to match.
    if (mode === "ask" && !approvals.approved(`delegate\n${real}`, user)) {
      report({ ...event, status: "needs_approval", detail: "it lets Claude Code read and change files in that folder" });
      return result(
        `Not started yet: handing work to Claude Code needs the user's OK. Say in one sentence what you'd hand off and that it would work in ${shown}, ask if that's alright, then stop and wait. If they agree, call delegate again for the same folder.`,
      );
    }

    const bin = this.bin;
    const job = jobs.start("delegate", purpose, (handle) => runClaude(bin, task, real, earlier?.sessionId ?? null, handle), { folder: real });
    report({ ...event, status: "done", detail: `started as job ${job.id}` });
    return result(
      `Started as background job ${job.id}, working in ${shown}. It will take a while; you'll be told when it finishes. Tell the user in a few words that you've handed it off, and carry on.`,
    );
  }
}

/** Run Claude Code once, to completion, feeding its progress to the job. */
function runClaude(bin: string, task: string, folder: string, resume: string | null, job: JobHandle): Promise<JobOutcome> {
  return new Promise((resolve) => {
    const env: NodeJS.ProcessEnv = {};
    for (const [k, v] of Object.entries(process.env)) if (!SECRET.test(k)) env[k] = v;
    env.PATH = [path.dirname(bin), "/opt/homebrew/bin", "/usr/local/bin", env.PATH ?? "/usr/bin:/bin"].join(":");
    const allowed = (process.env.DELEGATE_ALLOWED_TOOLS || DEFAULT_TOOLS).split(",").map((t) => t.trim()).filter(Boolean);
    const args = [
      "-p",
      "--output-format", "stream-json",
      "--verbose",
      "--permission-mode", "acceptEdits",
      "--allowedTools", allowed.join(","),
      "--disallowedTools", NEVER.join(","),
      "--strict-mcp-config",
      "--append-system-prompt",
      "You were started by a voice assistant on the user's behalf; nobody can answer questions, so make sensible choices and finish. Stay inside the working folder. End with a short plain summary (three sentences at most, no markdown) of what you did, what you checked, and anything left undone: it will be read aloud.",
      ...(resume ? ["--resume", resume] : []),
    ];
    if (process.env.DELEGATE_MODEL) args.push("--model", process.env.DELEGATE_MODEL);

    const child = spawn(bin, args, { cwd: folder, env, detached: true, stdio: ["pipe", "pipe", "pipe"] });
    child.stdin.end(task);

    let final: { ok: boolean; text: string } | null = null;
    let lastText = "";
    let errors = "";
    let buffer = "";
    let settled = false;
    const kill = () => {
      try {
        process.kill(-child.pid!, "SIGTERM");
      } catch {
        /* already gone */
      }
      setTimeout(() => {
        try {
          process.kill(-child.pid!, "SIGKILL");
        } catch {
          /* already gone */
        }
      }, 3000).unref();
    };
    let timedOut = false;
    const limit = setTimeout(() => {
      timedOut = true;
      kill();
    }, LIMIT_MS);
    job.signal.addEventListener("abort", kill, { once: true });

    const onLine = (line: string) => {
      let e: any;
      try {
        e = JSON.parse(line);
      } catch {
        return;
      }
      if (e.session_id) job.setSession(String(e.session_id));
      if (e.type === "assistant") {
        for (const part of e.message?.content ?? []) {
          if (part.type === "text" && part.text?.trim()) {
            lastText = part.text.trim();
            job.progress(lastText.slice(0, 160));
          } else if (part.type === "tool_use") {
            const i = part.input ?? {};
            const detail = i.file_path ?? i.path ?? i.command ?? i.pattern ?? i.query ?? i.url ?? i.description ?? "";
            job.progress(`${part.name}${detail ? `: ${String(detail).replace(os.homedir(), "~")}` : ""}`);
          }
        }
      } else if (e.type === "result") {
        final = { ok: !e.is_error, text: String(e.result ?? "").trim() };
      }
    };
    child.stdout.on("data", (chunk: Buffer) => {
      buffer += chunk.toString("utf8");
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        onLine(buffer.slice(0, nl));
        buffer = buffer.slice(nl + 1);
      }
    });
    child.stderr.on("data", (chunk: Buffer) => (errors = (errors + chunk.toString("utf8")).slice(-1500)));

    const done = (outcome: JobOutcome) => {
      if (settled) return;
      settled = true;
      clearTimeout(limit);
      job.signal.removeEventListener("abort", kill);
      resolve(outcome);
    };
    child.on("error", (err) => done({ ok: false, result: `Claude Code couldn't start: ${err.message}` }));
    child.on("close", (code) => {
      if (buffer.trim()) onLine(buffer);
      if (timedOut) return done({ ok: false, result: `Stopped: it ran past the ${Math.round(LIMIT_MS / 60_000)} minute limit. The last thing it said: ${lastText || "(nothing)"}` });
      if (final) return done({ ok: final.ok && code === 0, result: final.text || lastText || "(it finished without saying anything)" });
      done({ ok: false, result: `Claude Code stopped early (exit code ${code}). ${errors.trim() || lastText || ""}`.trim() });
    });
  });
}

export const delegate = new Delegate();
