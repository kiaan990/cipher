import Anthropic from "@anthropic-ai/sdk";
import { config } from "./config.js";
import { httpFetch } from "./net.js";
import { SentenceChunker } from "./text.js";
import { TtsPipeline, type TurnOutput } from "./tts.js";

export const MOODS = ["calm", "happy", "excited", "curious", "thoughtful", "empathetic", "serious", "playful", "surprised"] as const;
const MOOD_TAG = /^\[\s*mood\s*:\s*([a-z]+)\s*\]/i;
/** Text that could still turn into a mood tag once more tokens arrive. */
const MOOD_PREFIX = /^\[\s*(m(o(o(d(\s*:\s*[a-z]*\s*)?)?)?)?)?$/i;

export const SYSTEM_PROMPT = `Your name is Cipher. You are built on Claude, an AI model made by Anthropic: mention that only when asked what you are or what powers you, and then say it plainly. You are talking with someone in a live voice conversation. Everything you write is converted to speech and played aloud the moment you write it.

How to speak (sound like a warm, quick-witted person on a call, not an assistant reading text):
- Keep turns short: usually one or two sentences, sometimes just a few words ("Oh no, really?"). Go longer only when asked to explain something, and even then talk it through rather than lecturing.
- Talk the way people actually talk: contractions (I'm, you're, that's), everyday words, short sentences. Vary your rhythm; not every reply should have the same shape.
- React like a person first when it fits: a quick, genuine reaction ("Oh, nice!", "Hm, yeah.", "Ah, gotcha.", "Wait, seriously?") and then the substance. Don't use the same opener twice in a row, and skip it when a direct answer is more natural.
- A light touch of natural speech is good: an occasional "so", "honestly", "I mean", or "hmm, let me think" when you really are weighing something. Never stack fillers, and never fake stutters.
- Match their energy: relaxed when they're chatty, brief and crisp when they're busy, gentle when they're upset, playful when they joke. If they speak in short bursts, answer in short bursts.
- Don't end every reply with a question. Ask one only when you genuinely want to know, or the conversation would otherwise stall. Never use canned closers like "Let me know if you need anything else" or "Is there anything else I can help with".
- Skip assistant phrases: no "Great question", "Certainly!", "I'd be happy to help", "As an AI". Don't summarise what they just said back to them.
- Use plain spoken English. No markdown, bullet points, numbered lists, headings, emoji, code or URLs unless the person explicitly asks for them. If you need to give several items, say them in a natural sentence ("you'll want eggs, flour and a bit of butter").
- Write numbers, symbols and abbreviations the way they are said aloud when that helps (for example "about twenty percent", "three thirty p.m.").
- Punctuation shapes the voice: commas and full stops make natural pauses, "…" makes a thoughtful pause, a question mark lifts the voice, an exclamation mark adds energy. Use them deliberately.
- The transcript comes from speech recognition, so it may contain small errors. Infer what was meant; ask only if it is genuinely unclear.
- If what they said seems unfinished or trails off, a tiny nudge ("Mm-hm?" or "Go on…") is a fine whole reply.
- When you use a tool, say at most a few words first ("On it.", "Checking.") and then act. Don't narrate commands, describe permission prompts, or second-guess yourself out loud ("Actually, that doesn't change anything…"). After it's done, give just the result in a sentence.
- If the words look like they weren't meant for you (half a sentence, someone else's conversation, a TV line), don't try to make sense of them: a short "Sorry, was that for me?" is enough.
- If a previous reply of yours is marked as interrupted, the person cut you off. Don't repeat what you were saying or apologise for it; just respond to what they said next, the way a person would.

Mood tag (required):
- End every reply with exactly one mood tag in square brackets after your last sentence, like: Ooh, tell me more. [mood: curious]
- Pick the mood that fits the emotional tone of your reply from: ${MOODS.join(", ")}.
- The tag drives a visual on screen and is never spoken. Never mention it, and never put it anywhere but the very end.`;

const client = config.anthropicKey ? new Anthropic({ apiKey: config.anthropicKey, maxRetries: 1, fetch: httpFetch }) : null;

export type TurnResult = "complete" | "aborted" | "error";

const MAX_TOOL_STEPS = 15; // e.g. open inbox, read, open an email, read, reply, type, send

export interface RunOptions {
  /** A camera still (base64 JPEG) to show Claude with the latest user message, for this reply only. */
  image?: string;
  sceneNote?: string;
  memoryNote?: string;
  macNote?: string;
  tools?: Anthropic.Tool[];
  runTool?: (call: Anthropic.ToolUseBlock, signal: AbortSignal) => Promise<Anthropic.ToolResultBlockParam>;
  /** A few words to say before a slow lookup when the reply hasn't said anything yet ("One sec."). */
  preamble?: (call: Anthropic.ToolUseBlock) => string | undefined;
}

/**
 * One assistant reply: streams Claude's tokens, cuts them into sentences and
 * pipes each sentence to TTS while the rest is still generating.
 */
export class AssistantTurn {
  text = "";
  generationDone = false;
  ttsDone = false;
  /** Set once the session has written this turn into the history. */
  recorded = false;
  /** Mood Claude tagged this reply with, if any. */
  mood: string | null = null;

  /** The next text follows a tool call, so it needs a space before it. */
  private needSpace = false;
  /** Text held back because it might be the start of a mood tag. */
  private hold = "";
  /** When each stage of this reply happened (ms since the turn started), for the latency log. */
  private readonly t0 = performance.now();
  private tFirstToken = 0;
  private tFirstSentence = 0;

  private readonly abortCtl = new AbortController();
  private readonly chunker = new SentenceChunker();
  private readonly tts: TtsPipeline;

  constructor(
    readonly id: number,
    private readonly out: TurnOutput,
  ) {
    this.tts = new TtsPipeline(
      id,
      this.abortCtl.signal,
      out,
      () => {
        this.ttsDone = true;
      },
      () => this.logLatency(),
    );
  }

  get aborted(): boolean {
    return this.abortCtl.signal.aborted;
  }

  /** Still producing text or audio. */
  get busy(): boolean {
    return !this.aborted && (!this.generationDone || !this.ttsDone);
  }

  /** Some of this reply's audio has already gone to the browser (so the user may have heard it). */
  get audioStarted(): boolean {
    return this.tts.audioStarted;
  }

  abort(): void {
    this.abortCtl.abort();
  }

  /** The part of the reply whose audio has started playing (what the user may have heard). */
  spokenText(): string {
    return this.tts.spokenText();
  }

  /** The reply as it should be stored in history: with its mood tag at the end, so Claude keeps using them. */
  historyText(text: string): string {
    return this.mood ? `${text} [mood: ${this.mood}]` : text;
  }

  async run(history: Anthropic.MessageParam[], opts: RunOptions = {}): Promise<TurnResult> {
    this.out.json({ type: "thinking", turnId: this.id });
    if (!client) {
      this.fail("ANTHROPIC_API_KEY is missing. Add it to .env and restart the server.");
      return "error";
    }
    // Stable part first (instructions and what it can control), cached so Claude doesn't
    // re-read ~6,000 tokens every reply. Memory and the camera change more often: after it.
    const system: Anthropic.TextBlockParam[] = [
      { type: "text", text: [SYSTEM_PROMPT, opts.macNote].filter(Boolean).join("\n\n"), cache_control: { type: "ephemeral" } },
    ];
    const extra = [opts.memoryNote, opts.sceneNote && `What you can see:\n${opts.sceneNote}`].filter(Boolean).join("\n\n");
    if (extra) system.push({ type: "text", text: extra });
    const messages = withHistoryCache([...history]);
    const last = messages[messages.length - 1];
    if (opts.image && last?.role === "user" && typeof last.content === "string") {
      messages[messages.length - 1] = {
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: "image/jpeg", data: opts.image } },
          { type: "text", text: last.content },
        ],
      };
    }

    let refused = false;
    try {
      // Claude may use tools (Mac control) several times in one reply: speak, act, speak.
      for (let step = 0; step < MAX_TOOL_STEPS; step++) {
        const stream = await hedgedStream(
          {
            model: config.anthropicModel,
            max_tokens: 1024,
            system,
            // Fastest time-to-first-token for a voice reply.
            thinking: { type: "disabled" },
            ...(opts.tools?.length ? { tools: opts.tools } : {}),
            messages,
          },
          this.abortCtl.signal,
          this.id,
        );

        for await (const event of stream) {
          if (this.aborted) break;
          if (event.type === "content_block_delta" && event.delta.type === "text_delta") {
            const delta = this.filterMood(event.delta.text);
            if (delta) this.emitText(delta);
          } else if (event.type === "content_block_stop" && opts.tools?.length) {
            // A text block just ended. If a tool call follows, say this text now
            // ("Sure, checking that.") instead of after the tool has run.
            for (const sentence of this.chunker.flush()) this.enqueue(sentence);
          } else if (event.type === "message_delta" && event.delta.stop_reason === "refusal") {
            refused = true;
          }
        }
        if (this.aborted) return "aborted";
        const final = await stream.finalMessage();
        const u = final.usage;
        console.log(`[claude] turn ${this.id} step ${step}: ${u.input_tokens} new + ${u.cache_read_input_tokens ?? 0} cached + ${u.cache_creation_input_tokens ?? 0} cache-written input tokens, ${u.output_tokens} out`);
        const calls = final.content.filter((b): b is Anthropic.ToolUseBlock => b.type === "tool_use");
        if (final.stop_reason !== "tool_use" || !calls.length || !opts.runTool) break;

        // Say what was written so far ("Sure, opening Safari.") before acting.
        for (const sentence of this.chunker.flush()) this.enqueue(sentence);
        // Nothing said yet and the lookup may take a moment: say a few words so there's no dead air.
        if (!this.text.trim()) {
          const filler = calls.map((c) => opts.preamble?.(c)).find(Boolean);
          if (filler) {
            this.emitText(filler);
            for (const sentence of this.chunker.flush()) this.enqueue(sentence);
          }
        }
        this.needSpace = Boolean(this.text);
        messages.push({ role: "assistant", content: final.content });
        const results: Anthropic.ToolResultBlockParam[] = [];
        for (const call of calls) {
          if (this.aborted) return "aborted";
          const t0 = performance.now();
          results.push(await opts.runTool(call, this.abortCtl.signal));
          console.log(`[tool] turn ${this.id}: ${call.name} asked for at ${Math.round(t0 - this.t0)} ms, took ${Math.round(performance.now() - t0)} ms`);
        }
        if (this.aborted) return "aborted";
        messages.push({ role: "user", content: results });
      }
    } catch (err) {
      if (this.aborted || err instanceof Anthropic.APIUserAbortError) return "aborted";
      this.fail(describeAnthropicError(err));
      return "error";
    }
    if (this.aborted) return "aborted";
    // A cut-off "[mood: ha" at the very end is dropped; anything else held back is real text.
    if (this.hold && !MOOD_PREFIX.test(this.hold)) this.emitText(this.hold);
    this.hold = "";

    if (refused && !this.text.trim()) {
      const line = "Sorry, I can't help with that one.";
      this.text = line;
      this.out.json({ type: "assistant_delta", turnId: this.id, text: line });
      this.enqueue(line);
    }
    for (const sentence of this.chunker.flush()) this.enqueue(sentence);
    this.generationDone = true;
    this.tts.finish();
    this.out.json({ type: "assistant_done", turnId: this.id });
    return "complete";
  }

  private emitText(delta: string): void {
    if (!this.text || this.needSpace) delta = delta.trimStart();
    if (!delta) return;
    if (this.needSpace) {
      delta = ` ${delta}`;
      this.needSpace = false;
    }
    if (!this.tFirstToken) this.tFirstToken = performance.now() - this.t0;
    this.text += delta;
    this.out.json({ type: "assistant_delta", turnId: this.id, text: delta });
    for (const sentence of this.chunker.push(delta)) this.enqueue(sentence);
  }

  private enqueue(sentence: string): void {
    if (!this.tFirstSentence) this.tFirstSentence = performance.now() - this.t0;
    this.tts.enqueue(sentence);
  }

  private logLatency(): void {
    const ms = (n: number) => `${Math.round(n)} ms`;
    const audio = performance.now() - this.t0;
    console.log(
      `[latency] turn ${this.id}: Claude first words ${ms(this.tFirstToken)} · first phrase ready ${ms(this.tFirstSentence)} · first audio ${ms(audio)} (voice ${ms(audio - this.tFirstSentence)})`,
    );
  }

  /**
   * Remove the "[mood: x]" tag from the stream (Claude writes it at the end of the reply,
   * so the voice can start straight away) and report the mood. Works wherever the tag
   * appears and however the tokens split it.
   */
  private filterMood(delta: string): string {
    let rest = this.hold + delta;
    this.hold = "";
    let out = "";
    for (;;) {
      const i = rest.indexOf("[");
      if (i < 0) return out + rest;
      out += rest.slice(0, i);
      rest = rest.slice(i);
      const m = rest.match(MOOD_TAG);
      if (m) {
        this.setMood(m[1].toLowerCase());
        rest = rest.slice(m[0].length);
      } else if (MOOD_PREFIX.test(rest) && rest.length < 32) {
        this.hold = rest; // might still become a tag
        return out;
      } else {
        out += "[";
        rest = rest.slice(1);
      }
    }
  }

  private setMood(mood: string): void {
    if (!(MOODS as readonly string[]).includes(mood) || mood === this.mood) return;
    this.mood = mood;
    this.out.json({ type: "mood", turnId: this.id, mood });
  }

  private fail(message: string): void {
    // Stop any queued speech too, so the user doesn't hear half a reply that history won't contain.
    this.abortCtl.abort();
    this.generationDone = true;
    this.ttsDone = true;
    this.out.json({ type: "error", source: "Anthropic", message });
    this.out.json({ type: "assistant_done", turnId: this.id, failed: true });
  }
}

function describeAnthropicError(err: unknown): string {
  if (err instanceof Anthropic.AuthenticationError) return "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in .env.";
  if (err instanceof Anthropic.PermissionDeniedError) return "This Anthropic API key isn't allowed to use that model.";
  if (err instanceof Anthropic.NotFoundError) return `Model "${config.anthropicModel}" was not found. Set ANTHROPIC_MODEL in .env.`;
  if (err instanceof Anthropic.RateLimitError) return "Anthropic rate limit reached. Wait a moment and try again.";
  if (err instanceof Anthropic.APIConnectionError) return "Couldn't reach the Anthropic API. Check your internet connection.";
  if (err instanceof Anthropic.APIError) return `Anthropic API error (${err.status ?? "?"}): ${err.message}`;
  return `Unexpected error: ${(err as Error)?.message ?? String(err)}`;
}

/**
 * Cache the conversation so far: a breakpoint on the newest message, so the next reply
 * only has to read what's new. (Copies the message; history itself is left as plain text.)
 */
function withHistoryCache(messages: Anthropic.MessageParam[]): Anthropic.MessageParam[] {
  const i = messages.length - 1;
  const last = messages[i];
  if (!last) return messages;
  const blocks: any[] = typeof last.content === "string" ? [{ type: "text", text: last.content }] : [...last.content];
  if (!blocks.length) return messages;
  blocks[blocks.length - 1] = { ...blocks[blocks.length - 1], cache_control: { type: "ephemeral" } };
  messages[i] = { ...last, content: blocks };
  return messages;
}

/** If Claude hasn't started answering by then, send the same request again (rare slow spells). */
const HEDGE_AFTER_MS = 900;

interface ReplyStream extends AsyncIterable<Anthropic.MessageStreamEvent> {
  finalMessage(): Promise<Anthropic.Message>;
}

/**
 * A reply stream that guards against Anthropic's occasional slow starts: if the first
 * request hasn't produced any words (or a tool call) within HEDGE_AFTER_MS, or fails
 * before it does, a second identical request is sent and whichever starts first is used.
 * The other is cancelled. Normally only one request is ever made.
 */
async function hedgedStream(params: Anthropic.MessageStreamParams, signal: AbortSignal, turnId: number): Promise<ReplyStream> {
  type Lane = { ctl: AbortController; stream: ReturnType<NonNullable<typeof client>["messages"]["stream"]>; events: Anthropic.MessageStreamEvent[]; done: boolean; error: unknown; wake: () => void };
  const t0 = performance.now();
  let winner: Lane | null = null;
  let settle: (l: Lane | null) => void = () => {};
  const decided = new Promise<Lane | null>((r) => (settle = r));
  const lanes: Lane[] = [];

  const open = (): Lane => {
    const ctl = new AbortController();
    const onAbort = () => ctl.abort();
    signal.addEventListener("abort", onAbort, { once: true });
    const lane: Lane = { ctl, stream: client!.messages.stream(params, { signal: ctl.signal }), events: [], done: false, error: null, wake: () => {} };
    lanes.push(lane);
    void (async () => {
      try {
        for await (const ev of lane.stream) {
          lane.events.push(ev);
          const started = ev.type === "content_block_delta" || (ev.type === "content_block_start" && ev.content_block.type === "tool_use");
          if (started && !winner) {
            winner = lane;
            for (const other of lanes) if (other !== lane) other.ctl.abort();
            if (lanes.length > 1) console.log(`[claude] turn ${turnId}: backup request answered first (${Math.round(performance.now() - t0)} ms)`);
            settle(lane);
          }
          lane.wake();
        }
      } catch (err) {
        lane.error = err;
      } finally {
        lane.done = true;
        signal.removeEventListener("abort", onAbort);
        lane.wake();
        if (!winner) {
          // Finished or failed before saying anything: the backup (if any) may still answer.
          if (lane.error && lanes.length === 1 && !signal.aborted) {
            console.log(`[claude] turn ${turnId}: first request failed early, retrying`);
            open();
          } else if (lanes.every((l) => l.done)) {
            winner = lanes.find((l) => !l.error) ?? lane;
            settle(winner);
          }
        }
      }
    })();
    return lane;
  };

  open();
  const hedge = setTimeout(() => {
    if (!winner && !signal.aborted && lanes.length === 1) {
      console.log(`[claude] turn ${turnId}: no words after ${HEDGE_AFTER_MS} ms, sending a backup request`);
      open();
    }
  }, HEDGE_AFTER_MS);
  const lane = await decided;
  clearTimeout(hedge);
  if (!lane) throw new Error("no reply");
  if (lane.error && !lane.events.length) throw lane.error;

  return {
    async *[Symbol.asyncIterator]() {
      let i = 0;
      for (;;) {
        while (i < lane.events.length) yield lane.events[i++];
        if (lane.done) {
          if (lane.error) throw lane.error;
          return;
        }
        await new Promise<void>((r) => (lane.wake = r));
      }
    },
    finalMessage: () => lane.stream.finalMessage(),
  };
}
