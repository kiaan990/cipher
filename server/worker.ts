/**
 * The backend worker.
 *
 * The voice that talks is a small, fast model: good at conversation, slow and unsteady
 * when a request takes many steps (it does them one at a time, and each step is a pause).
 * So multi-step work is handed over whole. The voice calls `do_task` with a plain
 * description; a stronger model plans it once, runs the cloud calls it needs side by
 * side, checks what came back, and writes a short answer. That happens as a background
 * job, so the conversation carries on and the answer is spoken when it is ready.
 *
 * The worker can read and add things on the cloud server. It can't delete anything and
 * can't touch this Mac: when something needs deleting, or a choice only the user can
 * make, it stops and hands the question back to be asked aloud.
 */
import Anthropic from "@anthropic-ai/sdk";
import { config } from "./config.js";
import { cloud } from "./cloud.js";
import { memory } from "./memory.js";
import { jobs, type JobHandle, type JobOutcome } from "./jobs.js";
import { nowNote } from "./clock.js";
import { httpFetch } from "./net.js";
import type { UserTurn } from "./approvals.js";

const MAX_STEPS = 12;
const MAX_AT_ONCE = 2;
const TIME_LIMIT_MS = Number(process.env.WORKER_TIME_LIMIT_MS ?? 4 * 60_000);
const KIND = "do_task";

type Report = (e: { id: string; kind: string; purpose: string; command: string; status: string; detail?: string }) => void;

const client = config.anthropicKey ? new Anthropic({ apiKey: config.anthropicKey, maxRetries: 1, fetch: httpFetch }) : null;
const tidy = (s: string) => s.replace(/https?:\/\/\S+/g, "<cloud server>");

const SYSTEM = [
  "You are the part of Cipher, the user's personal assistant, that does longer pieces of work in the background. The user talks to Cipher out loud; Cipher has handed you a task in writing and will read your final answer to them aloud. You never talk to the user directly and can't ask them anything mid-task.",
  "How to work:",
  "- Plan once, before the first tool call. Work out everything you need to read, then ask for all of it in the same step: tool calls made together run at the same time, and every extra step costs the user several seconds.",
  "- Do the same for changes: add all the events or tasks in one step, not one per step.",
  "- Read before you write when it could matter: check the calendar for clashes or an existing copy before adding an event, check the task list before adding a task that may already be there.",
  "- Every event needs a calendar. Pass `calendar` every time, chosen from the calendars listed below. If the right one isn't clear from the task, don't guess: leave that event out and ask which calendar in your answer.",
  "- Take every date from the clock note in the task, never from memory.",
  "- After changing things, trust a tool result that says it was confirmed. Only re-read when a result is unclear or failed.",
  "- You can't delete anything. If the task needs something deleted, find exactly what (title, day, calendar) and say so in your answer, so the user can be asked.",
  "- If part of the task can't be done, or needs a choice only the user can make, do everything else and then say what is left and why.",
  "- Only say something was done if a tool result shows it was. If a tool failed, say so plainly.",
  "Your final answer is read aloud, so write it for the ear: plain sentences, no markdown, no lists with symbols, no ids or web addresses. Lead with what was done. Keep it under about ninety words; for a long list give the count and the few that matter. If you need the user to decide something, end with that one question.",
].join("\n");

const TOOL: Anthropic.Tool = {
  name: KIND,
  description:
    "Hand a multi-step piece of work on the cloud server (calendar, tasks, notes, web search) to a stronger model that works in the background and reports back. Use it when a request needs more than two or three steps: adding several events or tasks at once, planning or tidying a week, checking the calendar against tasks or notes, looking something up and then saving it. One lookup or one add is quicker done directly. It can't delete anything and can't use this Mac.",
  input_schema: {
    type: "object",
    properties: {
      task: {
        type: "string",
        description:
          "The whole job, written so it makes sense on its own: what the user wants, every name, date (as YYYY-MM-DD from the clock note), time and calendar they mentioned, and what a good result looks like. The worker hasn't heard the conversation.",
      },
      title: { type: "string", description: "A few words naming the job, e.g. \"plan next week's study blocks\"." },
    },
    required: ["task"],
  },
};

class Worker {
  private turn = 0;

  get on(): boolean {
    return Boolean(client) && cloud.configured;
  }

  tools(): Anthropic.Tool[] {
    return this.on ? [TOOL] : [];
  }

  owns(name: string): boolean {
    return name === TOOL.name;
  }

  describe(): string {
    if (!this.on) return "";
    return [
      "Bigger jobs: when a request needs more than two or three steps on the cloud server (several events or tasks at once, planning or tidying a week, checking the calendar against tasks or notes, researching and then saving), call `do_task` once with a complete brief instead of doing it step by step. It runs in the background on a stronger model; say in a few words that you're on it and keep talking, and you'll be given the result to say when it's ready.",
      "- Put everything that matters in the brief: what they asked, names, dates from the clock note, times, and which calendar if they said. The worker hasn't heard the conversation.",
      "- A single lookup or a single add is quicker done directly; don't hand those off.",
      "- It can't delete. If its answer says something needs deleting or asks a question, ask the user, and do the delete yourself if they agree.",
    ].join("\n");
  }

  run(call: Anthropic.ToolUseBlock, user: UserTurn, report: Report): Anthropic.ToolResultBlockParam {
    const input = (call.input ?? {}) as Record<string, unknown>;
    const result = (content: string, isError = false): Anthropic.ToolResultBlockParam => ({ type: "tool_result", tool_use_id: call.id, content, is_error: isError || undefined });
    if (!this.on) return result("Background work isn't available right now. Do it directly, step by step.", true);
    const task = String(input.task ?? "").trim();
    if (task.length < 15) return result("Give the whole job in `task`: what to do, with the names, dates and times that matter.", true);
    if (jobs.running().filter((j) => j.kind === KIND).length >= MAX_AT_ONCE) {
      return result(`${MAX_AT_ONCE} background jobs are already running. Wait for one to finish, or cancel one, before starting another.`, true);
    }
    const title = (String(input.title ?? "").trim() || task).replace(/\s+/g, " ").slice(0, 120);
    // What the user actually said goes along too: it is what a calendar or a past date is checked against.
    const brief = `${task.slice(0, 6000)}\n\n[What the user said, word for word, when they asked: "${user.text.slice(0, 600)}"]`;
    const job = jobs.start(KIND, title, (handle) => this.work(brief, handle));
    report({ id: call.id.slice(-8), kind: "worker", purpose: `background job: ${title}`, command: `${config.workerModel} with the cloud server's tools`, status: "done", detail: `started as job ${job.id}` });
    return result(
      `Started as background job ${job.id}. You'll be given the result to say when it finishes, usually within a minute. Tell the user in a few words that you're on it, and carry on. Don't do any part of it yourself and don't start it again.`,
    );
  }

  /** The job itself. Also what the tests call. */
  async work(brief: string, handle: Pick<JobHandle, "signal" | "progress">): Promise<JobOutcome> {
    if (!client) return { ok: false, result: "Cipher has no key for its model, so the job couldn't run." };
    const started = Date.now();
    const signal = AbortSignal.any([handle.signal, AbortSignal.timeout(TIME_LIMIT_MS)]);
    // Kept apart from spoken turns and from Muse's, so nothing here can answer a question put to the user.
    const user: UserTurn = { text: brief, turn: 2_000_000 + ++this.turn };
    const tools = cloud.freeTools();
    const allowed = new Set(tools.map((t) => t.name));
    if (!tools.length) return { ok: false, result: "The cloud server couldn't be reached, so nothing was done." };
    const system = [SYSTEM, cloud.describe(), memory.describe()].filter(Boolean).join("\n\n");
    const messages: Anthropic.MessageParam[] = [{ role: "user", content: `${brief}\n\n${nowNote()}` }];
    let model = config.workerModel;
    let thinking = true;
    let calls = 0;
    const log = (line: string) => console.log(`[worker] ${tidy(line)}`);
    log(`started on ${model}: ${brief.slice(0, 100).replace(/\s+/g, " ")}`);

    try {
      for (let step = 1; step <= MAX_STEPS; step++) {
        handle.progress(step === 1 ? "planning" : `thinking (step ${step})`);
        let res: Anthropic.Message;
        try {
          res = await client.messages.create({ model, max_tokens: 6000, system, messages, tools, ...(thinking ? { thinking: { type: "adaptive" as const } } : {}) }, { signal });
        } catch (err) {
          // A model name that isn't available, or one that doesn't think this way: carry on with the task model.
          const status = (err as { status?: number }).status;
          if (step === 1 && (status === 400 || status === 404) && (thinking || model !== config.toolModel)) {
            log(`${model} refused (${status}): ${(err as Error).message.slice(0, 160)}`);
            if (thinking && status === 400) thinking = false;
            else {
              model = /^(off|none|false)?$/i.test(config.toolModel) ? config.anthropicModel : config.toolModel;
              thinking = false;
            }
            step--;
            continue;
          }
          throw err;
        }
        const text = res.content.filter((b): b is Anthropic.TextBlock => b.type === "text").map((b) => b.text).join("\n").trim();
        const wanted = res.content.filter((b): b is Anthropic.ToolUseBlock => b.type === "tool_use");
        if (res.stop_reason !== "tool_use" || !wanted.length) {
          log(`done in ${((Date.now() - started) / 1000).toFixed(1)} s, ${step} step(s), ${calls} call(s)`);
          return { ok: true, result: tidy(text) || "The job finished but had nothing to report." };
        }
        messages.push({ role: "assistant", content: res.content });
        const names = wanted.map((c) => c.name.replace(/_/g, " "));
        handle.progress(names.length > 3 ? `${names.slice(0, 3).join(", ")} and ${names.length - 3} more` : names.join(", "));
        log(`step ${step}: ${wanted.map((c) => c.name).join(", ")}`);
        calls += wanted.length;
        // Everything asked for in one step runs at the same time.
        const results = await Promise.all(
          wanted.map(async (call): Promise<Anthropic.ToolResultBlockParam> => {
            if (!allowed.has(call.name) || !cloud.owns(call.name)) {
              return { type: "tool_result", tool_use_id: call.id, content: "Not available to background work. If this is a delete, say exactly what should be deleted in your answer so the user can be asked.", is_error: true };
            }
            try {
              return await cloud.run(call, user, signal, () => {});
            } catch (err) {
              return { type: "tool_result", tool_use_id: call.id, content: `Failed: ${tidy((err as Error).message)}`, is_error: true };
            }
          }),
        );
        messages.push({ role: "user", content: results });
      }
      log(`stopped after ${MAX_STEPS} steps`);
      return { ok: false, result: "That job took more steps than allowed and was stopped part-way. Some of it may be done; check before asking again, and try it in smaller pieces." };
    } catch (err) {
      const timedOut = signal.aborted && !handle.signal.aborted;
      log(`failed after ${((Date.now() - started) / 1000).toFixed(1)} s: ${(err as Error).message.slice(0, 200)}`);
      if (handle.signal.aborted) return { ok: false, result: calls ? "Cancelled part-way. Some of it may already be done." : "Cancelled before anything was done." };
      return {
        ok: false,
        result: timedOut
          ? `That job ran out of time${calls ? " part-way; some of it may already be done, so check before asking again" : " before anything was done"}.`
          : `The job hit an error${calls ? " part-way; some of it may already be done, so check before asking again" : " before anything was done"}.`,
      };
    }
  }
}

export const worker = new Worker();
