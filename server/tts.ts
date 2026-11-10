import fs from "node:fs";
import path from "node:path";
import { config } from "./config.js";
import { httpFetch } from "./net.js";

/**
 * Which voice service speaks. TTS_PROVIDER in .env: "auto" (default: ElevenLabs while
 * it has credits, then Deepgram Aura), "elevenlabs" or "deepgram".
 */
class VoiceChoice {
  private elevenEmpty = false;
  private lastCheck = 0;

  useDeepgram(): boolean {
    if (config.ttsProvider === "deepgram") return true;
    if (config.ttsProvider === "elevenlabs") return false;
    // While on Deepgram, look again every 5 minutes so topping up ElevenLabs takes effect without a restart.
    if (this.elevenEmpty && Date.now() - this.lastCheck > 5 * 60_000) void this.checkCredits();
    return this.elevenEmpty || !config.elevenKey;
  }

  /** ElevenLabs reported no credits left. */
  elevenLabsOut(out?: TurnOutput): void {
    if (this.elevenEmpty) return;
    this.elevenEmpty = true;
    this.lastCheck = Date.now();
    console.warn("[voice] ElevenLabs is out of credits: using Deepgram's voice instead");
    out?.json({
      type: "notice",
      message: "ElevenLabs credits used up: switched to Deepgram voice",
    });
  }

  /** At startup: if ElevenLabs is already out of credits, don't try it first on every sentence. */
  async checkCredits(): Promise<void> {
    if (config.ttsProvider !== "auto" || !config.elevenKey) return;
    this.lastCheck = Date.now();
    try {
      const r = await httpFetch("https://api.elevenlabs.io/v1/user/subscription", { headers: { "xi-api-key": config.elevenKey } });
      if (!r.ok) return;
      const s: any = await r.json();
      const left = Number(s.character_limit) - Number(s.character_count);
      if (Number.isFinite(left) && left < 200) {
        if (this.elevenEmpty) return; // still empty: nothing new to log
        this.elevenEmpty = true;
        const reset = s.next_character_count_reset_unix ? new Date(s.next_character_count_reset_unix * 1000).toLocaleDateString() : "next month";
        console.log(`  Voice: ElevenLabs is out of credits (resets ${reset}), using Deepgram's voice.`);
      } else {
        if (this.elevenEmpty) console.log("[voice] ElevenLabs has credits again: switching back from Deepgram");
        this.elevenEmpty = false;
        console.log(`  Voice: ElevenLabs (${left.toLocaleString()} credits left this month).`);
      }
    } catch {
      /* offline: decide on the first request */
    }
  }
}

export const voice = new VoiceChoice();

export interface TurnOutput {
  json(msg: Record<string, unknown>): void;
  audio(turnId: number, pcm: Buffer): void;
}

interface Item {
  text: string;
  res?: Promise<Response | null>;
}

/**
 * Turns sentences into streamed ElevenLabs audio (raw 24 kHz 16-bit PCM).
 * Requests for the current and the next sentence run at once, but audio is
 * forwarded strictly in order. Everything stops when `signal` aborts.
 */
export class TtsPipeline {
  private items: Item[] = [];
  private cursor = 0;
  private looping = false;
  private inputDone = false;
  private doneSent = false;
  /** Number of sentences whose audio has started streaming to the browser. */
  private started = 0;

  constructor(
    private readonly turnId: number,
    private readonly signal: AbortSignal,
    private readonly out: TurnOutput,
    private readonly onDone: () => void,
    private readonly onFirstAudio: () => void = () => {},
  ) {}

  enqueue(text: string): void {
    this.items.push({ text });
    void this.loop();
  }

  /** True once any audio for this reply has been sent to the browser. */
  get audioStarted(): boolean {
    return this.started > 0;
  }

  /** The sentences whose audio has started reaching the browser. */
  spokenText(): string {
    return this.items.slice(0, this.started).map((i) => i.text).join(" ");
  }

  /** No more sentences are coming. */
  finish(): void {
    this.inputDone = true;
    void this.loop();
  }

  private start(i: number): void {
    const item = this.items[i];
    if (!item || item.res) return;
    // What comes before (and after, if it's already written) lets the voice carry its
    // intonation across pieces instead of starting every sentence fresh.
    const previous = this.items.slice(Math.max(0, i - 3), i).map((x) => x.text).join(" ").slice(-400);
    const next = this.items[i + 1]?.text.slice(0, 200) ?? "";
    item.res = this.request(item.text, previous, next);
  }

  /** Speech for one sentence: ElevenLabs while it has credits, otherwise Deepgram Aura. */
  private async request(text: string, previous = "", next = ""): Promise<Response | null> {
    // A short opener said before ("Oh, nice!", "Hmm.", "Got it."): play the saved audio
    // straight away instead of waiting ~0.3 s for the voice service. Only as the first
    // piece of a reply, so the intonation always matches how it was recorded.
    const key = !previous ? phrases.key(text) : null;
    const saved = key ? phrases.get(key) : null;
    if (saved) {
      console.log(`[voice] turn ${this.turnId}: "${text}" from saved audio`);
      return new Response(new Uint8Array(saved));
    }
    const res0 = voice.useDeepgram() ? await this.requestDeepgram(text) : await this.requestEleven(text, previous, next);
    if (key && res0 && res0 !== "out_of_credits") return phrases.capture(key, res0);
    if (res0 !== "out_of_credits") return res0;
    const res = res0;
    // Credits ran out mid-conversation: switch for good and say this sentence with Deepgram.
    voice.elevenLabsOut(this.out);
    return this.requestDeepgram(text);
  }

  private async requestEleven(text: string, previous = "", next = ""): Promise<Response | null | "out_of_credits"> {
    const url =
      `https://api.elevenlabs.io/v1/text-to-speech/${encodeURIComponent(config.elevenVoiceId)}/stream` +
      `?output_format=pcm_24000`;
    try {
      const res = await httpFetch(url, {
        method: "POST",
        signal: this.signal,
        headers: {
          "xi-api-key": config.elevenKey,
          "Content-Type": "application/json",
          Accept: "audio/pcm",
        },
        body: JSON.stringify({
          text,
          model_id: config.elevenModelId,
          ...(previous ? { previous_text: previous } : {}),
          ...(next ? { next_text: next } : {}),
          // Lower stability = more expressive, conversational delivery (less "narrator").
          voice_settings: { stability: config.elevenStability, similarity_boost: 0.75, style: config.elevenStyle, use_speaker_boost: true },
        }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        if (/quota|credits|limit_reached|exceeds your/i.test(body) && config.deepgramKey) return "out_of_credits";
        let detail = body;
        try {
          const parsed = JSON.parse(body);
          detail = parsed?.detail?.message ?? parsed?.detail?.status ?? JSON.stringify(parsed?.detail ?? parsed);
        } catch {
          /* not JSON */
        }
        const hint =
          res.status === 401 ? " Check ELEVENLABS_API_KEY in .env, or your character quota may be used up." :
          res.status === 402 ? " Your ElevenLabs plan can't use this voice over the API. Pick a default voice and set ELEVENLABS_VOICE_ID in .env." :
          res.status === 404 ? " Check ELEVENLABS_VOICE_ID in .env." :
          res.status === 429 ? " ElevenLabs is rate-limiting requests; wait a moment." : "";
        this.out.json({
          type: "error",
          source: "ElevenLabs",
          message: `Text-to-speech failed (HTTP ${res.status}): ${String(detail).slice(0, 200)}.${hint}`,
        });
        return null;
      }
      return res;
    } catch (err) {
      if (!this.signal.aborted) {
        this.out.json({ type: "error", source: "ElevenLabs", message: `Text-to-speech request failed: ${(err as Error).message}` });
      }
      return null;
    }
  }

  /** Deepgram Aura: same raw 24 kHz 16-bit PCM, so playback doesn't change. */
  private async requestDeepgram(text: string): Promise<Response | null> {
    const url = `https://api.deepgram.com/v1/speak?model=${encodeURIComponent(config.deepgramVoice)}&encoding=linear16&sample_rate=24000&container=none`;
    try {
      const res = await httpFetch(url, {
        method: "POST",
        signal: this.signal,
        headers: { Authorization: `Token ${config.deepgramKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        let detail = body;
        try {
          const j = JSON.parse(body);
          detail = j.err_msg || j.message || detail;
        } catch {
          /* not JSON */
        }
        this.out.json({ type: "error", source: "Deepgram voice", message: `Text-to-speech failed (HTTP ${res.status}): ${String(detail).slice(0, 200)}` });
        return null;
      }
      return res;
    } catch (err) {
      if (!this.signal.aborted) {
        this.out.json({ type: "error", source: "Deepgram voice", message: `Text-to-speech request failed: ${(err as Error).message}` });
      }
      return null;
    }
  }

  private async loop(): Promise<void> {
    if (this.looping) return;
    this.looping = true;
    try {
      while (!this.signal.aborted && this.cursor < this.items.length) {
        this.start(this.cursor);
        this.start(this.cursor + 1); // prefetch the next sentence
        const res = await this.items[this.cursor].res;
        if (res) await this.pipe(res);
        if (this.signal.aborted) break;
        this.out.json({ type: "tts_sentence_end", turnId: this.turnId, pause: pauseAfter(this.items[this.cursor].text) });
        this.cursor++;
      }
    } finally {
      this.looping = false;
    }
    if (!this.signal.aborted && this.inputDone && this.cursor >= this.items.length && !this.doneSent) {
      this.doneSent = true;
      this.out.json({ type: "tts_done", turnId: this.turnId });
      this.onDone();
    }
  }

  private async pipe(res: Response): Promise<void> {
    if (!res.body) return;
    const reader = res.body.getReader();
    let carry: Buffer | null = null; // keep 16-bit samples whole across chunks
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done || this.signal.aborted) break;
        let buf: Buffer = Buffer.from(value);
        if (carry) {
          buf = Buffer.concat([carry, buf]);
          carry = null;
        }
        if (buf.length % 2 === 1) {
          carry = buf.subarray(buf.length - 1);
          buf = buf.subarray(0, buf.length - 1);
        }
        if (buf.length) {
          if (!this.started) this.onFirstAudio();
          this.started = Math.max(this.started, this.cursor + 1);
          this.out.audio(this.turnId, buf);
        }
      }
    } catch {
      /* aborted mid-stream */
    } finally {
      reader.releaseLock();
    }
  }
}

/**
 * How long a person would pause after this piece, in seconds: barely after a comma,
 * a beat after a full stop, a little longer after a question or a trailing "…".
 */
export function pauseAfter(text: string): number {
  const t = text.trim();
  if (/[,;:\u2014-]$/.test(t)) return 0.03;
  if (/(\.\.\.|\u2026)["'\u201d\u2019)]*$/.test(t)) return 0.32;
  if (/\?["'\u201d\u2019)]*$/.test(t)) return 0.2;
  if (/!["'\u201d\u2019)]*$/.test(t)) return 0.12;
  return 0.14;
}

/**
 * Saved audio for short openers ("Oh, nice!", "Hmm.", "Sure."), per voice, on disk. Filled
 * as Cipher says them (and a common few ahead of time), so most replies start instantly.
 */
const OPENERS = [
  "Oh, nice!", "Oh nice.", "Hmm.", "Hmm,", "Hm, yeah.", "Got it.", "Gotcha.", "Ah, gotcha.", "Sure.", "Sure!", "Yeah.", "Yeah,", "Yeah!",
  "Okay.", "Okay,", "Okay!", "Oh!", "Oh,", "Oh.", "Ah,", "Ah.", "Right.", "Right,", "Oh no.", "Oh no!", "Oh wow.", "Oh wow!", "Wow.", "Wow!",
  "Oh, really?", "Really?", "Wait, seriously?", "Hey!", "Hi!", "Hey there!", "Of course.", "Totally.", "Nice!", "Nice.", "Ooh,", "Ooh!",
  "So,", "Well,", "Honestly,", "Let me check.", "One sec.", "Checking.", "Hang on, let me look.", "On it.", "Done.", "Mm-hm?", "Go on…",
  "Sorry, was that for me?", "Ha!", "Haha,", "Ha, yeah.", "Fair enough.", "Good point.", "Exactly.", "Absolutely.", "Yep.", "Yep,", "Hmm, good question.",
];
const MAX_PHRASES = 400;

class PhraseCache {
  private mem = new Map<string, Buffer>();
  private dirFor = "";
  private warming = false;

  private get voiceKey(): string {
    return voice.useDeepgram()
      ? `deepgram-${config.deepgramVoice}`
      : `eleven-${config.elevenVoiceId}-${config.elevenModelId}-${config.elevenStability}-${config.elevenStyle}`;
  }

  private dir(): string {
    const d = path.join(config.dataDir, "phrases", this.voiceKey.replace(/[^\w.-]/g, "_"));
    if (d !== this.dirFor) {
      // Voice changed (or first use): load what's saved for this one.
      this.dirFor = d;
      this.mem.clear();
      try {
        for (const f of fs.readdirSync(d)) if (f.endsWith(".pcm")) this.mem.set(decodeURIComponent(f.slice(0, -4)), fs.readFileSync(path.join(d, f)));
      } catch {
        /* none yet */
      }
    }
    return d;
  }

  /** Only short pieces are worth saving (and repeat often enough). */
  key(text: string): string | null {
    const t = text.trim();
    if (!t || t.length > 28 || t.split(/\s+/).length > 4) return null;
    return t;
  }

  get(key: string): Buffer | null {
    this.dir();
    return this.mem.get(key) ?? null;
  }

  /** Pass the audio through while keeping a copy for next time. */
  capture(key: string, res: Response): Response {
    if (!res.body) return res;
    const [a, b] = res.body.tee();
    void (async () => {
      const parts: Buffer[] = [];
      const reader = b.getReader();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          parts.push(Buffer.from(value));
        }
        const pcm = Buffer.concat(parts);
        if (pcm.length < 24000 * 2 * 0.15) return; // cut short or empty: don't keep
        this.save(key, pcm);
      } catch {
        /* aborted: nothing to keep */
      }
    })();
    return new Response(a, { status: res.status, headers: res.headers });
  }

  private save(key: string, pcm: Buffer): void {
    const d = this.dir();
    if (this.mem.size >= MAX_PHRASES) return;
    this.mem.set(key, pcm);
    try {
      fs.mkdirSync(d, { recursive: true });
      fs.writeFileSync(path.join(d, `${encodeURIComponent(key)}.pcm`), pcm);
    } catch {
      /* in memory only */
    }
  }

  /** Record the common openers once per voice, in the background. */
  async warm(): Promise<void> {
    if (this.warming) return;
    this.warming = true;
    try {
      this.dir();
      let made = 0;
      for (const text of OPENERS) {
        if (this.mem.has(text)) continue;
        const pipe = new TtsPipeline(0, AbortSignal.timeout(20_000), { json: () => {}, audio: () => {} }, () => {});
        const res = await (pipe as any).request(text).catch(() => null);
        if (!res?.body) continue;
        // Read it through so capture() saves it.
        const reader = res.body.getReader();
        while (!(await reader.read()).done);
        made++;
        await new Promise((r) => setTimeout(r, 50));
      }
      if (made) console.log(`  Voice: recorded ${made} common openers for instant replies.`);
    } finally {
      this.warming = false;
    }
  }
}

export const phrases = new PhraseCache();
