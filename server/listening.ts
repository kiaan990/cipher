import fs from "node:fs";
import path from "node:path";
import { config } from "./config.js";

/**
 * Who and what the orb listens to:
 *
 *  - Wake word: ignore everything until you say it (e.g. "Cipher"), then stay awake
 *    for a while so you can keep talking without repeating it.
 *  - Voice match: answer only your voice. A speaker-verification model (WavLM base plus SV,
 *    microsoft/wavlm-base-plus-sv converted for transformers.js as Xenova/wavlm-base-plus-sv,
 *    MIT licence) turns a few seconds of speech into a "voiceprint"; each thing said is
 *    compared with the one you recorded. Runs on this machine in about 0.1 s.
 *
 * The noise filter (RNNoise) runs in the browser; see public/audio.js.
 */

export type Strictness = "relaxed" | "normal" | "strict";

export interface ListeningSettings {
  wakeWord: boolean;
  wakePhrase: string;
  /** How long it stays awake after the last exchange. */
  awakeSeconds: number;
  voiceMatch: boolean;
  strictness: Strictness;
  /** After the wake word, answer only the voice that said it (no recording needed). */
  focusSpeaker: boolean;
}

const DEFAULTS: ListeningSettings = {
  wakeWord: true,
  wakePhrase: "Cipher",
  awakeSeconds: 15,
  voiceMatch: false,
  strictness: "normal",
  focusSpeaker: true,
};
/** Bumped when a default changes in a way saved settings should pick up once. */
const SETTINGS_VERSION = 3;

/** Similarity needed to count as you. Same voice scores ~0.9+, different people mostly well below. */
const THRESHOLDS: Record<Strictness, number> = { relaxed: 0.8, normal: 0.86, strict: 0.91 };
const FOCUS_THRESHOLD = 0.75;

const SETTINGS_FILE = path.join(config.dataDir, "listening.json");
const VOICEPRINT_FILE = path.join(config.dataDir, "voiceprint.json");
const MODEL_ID = "Xenova/wavlm-base-plus-sv";
const MODEL_REVISION = "e61029603001bd11295c36d878698708bf59190f";
const SAMPLE_RATE = 16000;

// ---- settings -------------------------------------------------------------------

type Listener = () => void;

class Listening {
  settings: ListeningSettings = { ...DEFAULTS };
  private voiceprint: Float32Array | null = null;
  private readonly listeners = new Set<Listener>();
  modelState: "off" | "loading" | "ready" | "failed" = "off";
  modelError = "";

  constructor() {
    try {
      const saved = JSON.parse(fs.readFileSync(SETTINGS_FILE, "utf8"));
      Object.assign(this.settings, sanitize(saved));
      // Version 2 turned the wake word (and focusing on whoever says it) on by default.
      const v = Number(saved?.v) || 1;
      if (v < 2) {
        this.settings.wakeWord = true;
        this.settings.focusSpeaker = true;
      }
      // Version 3: the assistant is now called Cipher, so the old default wake phrase moves too.
      if (v < 3 && /^(hey )?claude$/i.test(this.settings.wakePhrase.trim())) this.settings.wakePhrase = "Cipher";
      if (v < SETTINGS_VERSION) saveJson(SETTINGS_FILE, { ...this.settings, v: SETTINGS_VERSION });
    } catch {
      /* first run */
    }
    try {
      const v = JSON.parse(fs.readFileSync(VOICEPRINT_FILE, "utf8"));
      if (Array.isArray(v?.embedding) && v.embedding.length > 100) this.voiceprint = Float32Array.from(v.embedding);
    } catch {
      /* none yet */
    }
    if (this.modelWanted) this.preload();
  }

  /** Something needs the speaker model: voice match, or focusing on whoever woke it. */
  get modelWanted(): boolean {
    return this.voiceMatchActive || this.focusActive;
  }

  /** Lock onto the voice that says the wake word (only when there's no recorded voiceprint). */
  get focusActive(): boolean {
    return this.settings.wakeWord && this.settings.focusSpeaker && !this.voiceMatchActive;
  }

  get enrolled(): boolean {
    return this.voiceprint !== null;
  }

  /** Voice match is on and has a voiceprint to compare against. */
  get voiceMatchActive(): boolean {
    return this.settings.voiceMatch && this.voiceprint !== null;
  }

  onChange(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private changed(): void {
    for (const fn of this.listeners) fn();
  }

  update(patch: Partial<ListeningSettings>): void {
    const before = JSON.stringify(this.settings);
    Object.assign(this.settings, sanitize(patch));
    if (JSON.stringify(this.settings) === before) return;
    saveJson(SETTINGS_FILE, { ...this.settings, v: SETTINGS_VERSION });
    if (this.modelWanted) this.preload();
    console.log(
      `[listening] wake word ${this.settings.wakeWord ? `on ("${this.settings.wakePhrase}")` : "off"}, voice match ${this.settings.voiceMatch ? `on (${this.settings.strictness})` : "off"}, focus on speaker ${this.settings.focusSpeaker ? "on" : "off"}`,
    );
    this.changed();
  }

  /** What the browser shows in Settings. */
  state(): Record<string, unknown> {
    return { ...this.settings, enrolled: this.enrolled, model: this.modelState, modelError: this.modelError };
  }

  // ---- wake word ----------------------------------------------------------------

  /** True if `text` contains the wake phrase (allowing for how speech recognition spells it). */
  heardWakeWord(text: string): boolean {
    return matchesWakePhrase(text, this.settings.wakePhrase);
  }

  /** Words for Deepgram to listen out for, so the wake phrase is recognised reliably. */
  keyterms(): string[] {
    if (!this.settings.wakeWord) return [];
    const p = this.settings.wakePhrase.trim();
    return p ? [p] : [];
  }

  // ---- voice match ----------------------------------------------------------------

  private model: { proc: any; model: any } | null = null;
  private loading: Promise<boolean> | null = null;

  /** Load the model in the background (downloads ~100 MB the first time). */
  preload(): Promise<boolean> {
    if (this.loading) return this.loading;
    this.modelState = "loading";
    this.modelError = "";
    this.changed();
    this.loading = (async () => {
      try {
        const T: any = await import("@huggingface/transformers");
        T.env.cacheDir = path.join(config.dataDir, "models");
        const t = performance.now();
        const opts = { revision: MODEL_REVISION };
        const proc = await T.AutoProcessor.from_pretrained(MODEL_ID, opts);
        const model = await T.AutoModel.from_pretrained(MODEL_ID, { ...opts, dtype: "q8" });
        this.model = { proc, model };
        await this.embed(new Float32Array(SAMPLE_RATE)); // warm up
        console.log(`  Voice match: model ready (${Math.round(performance.now() - t)} ms).`);
        this.modelState = "ready";
        return true;
      } catch (err) {
        console.warn(`[voice-match] couldn't load the model: ${(err as Error).message}`);
        this.modelState = "failed";
        this.modelError = "Couldn't load the voice model. Check the internet connection, then switch Voice match off and on.";
        this.loading = null;
        return false;
      } finally {
        this.changed();
      }
    })();
    return this.loading;
  }

  private async embed(audio: Float32Array): Promise<Float32Array> {
    const m = this.model!;
    const inputs = await m.proc(audio);
    const { embeddings } = await m.model(inputs);
    return normalize(Float32Array.from(embeddings.data as Float32Array));
  }

  /**
   * Is this you? Compares with your recorded voiceprint, or (focus mode) with `focus`, the
   * voice that said the wake word. Returns null when it can't tell (model not ready, too
   * little speech, nothing to compare with), in which case the caller should let it through.
   */
  async check(pcm: Int16Array, opts: { mustCheck?: boolean; focus?: Float32Array | null; minSeconds?: number } = {}): Promise<{ ok: boolean; score: number; voice: Float32Array } | null> {
    const against = this.voiceMatchActive ? this.voiceprint : this.focusActive ? (opts.focus ?? null) : null;
    if (!against) return null;
    if (!this.model && !(await this.preload())) return null;
    const voiced = voicedOnly(pcm, 6);
    const seconds = voiced.length / SAMPLE_RATE;
    // Under ~0.8 s ("yes", "ok") a voiceprint is unreliable: only judge it when we must.
    if (seconds < (opts.minSeconds ?? (opts.mustCheck ? 0.35 : 0.8))) return null;
    const e = await this.embed(voiced);
    const score = dot(e, against);
    // Focus mode learnt the voice from a single sentence, so it uses a lower bar: measured
    // on 10 voices x 6 sentences, the same speaker never scored under 0.75, while clearly
    // different voices (man/woman, other accents, the TV) mostly score well below.
    let need = this.voiceMatchActive ? THRESHOLDS[this.settings.strictness] : FOCUS_THRESHOLD;
    if (seconds < 1.5) need -= 0.04; // short clips score lower, even for you
    return { ok: score >= need, score, voice: e };
  }

  /** A voiceprint of whoever is speaking in `pcm`, for focus mode. Null if there's too little speech. */
  async voiceOf(pcm: Int16Array): Promise<Float32Array | null> {
    if (!this.focusActive) return null;
    if (!this.model && !(await this.preload())) return null;
    const voiced = voicedOnly(pcm, 6);
    if (voiced.length / SAMPLE_RATE < 0.7) return null;
    return this.embed(voiced);
  }

  /** Blend a newly confirmed sample into a focus voiceprint, so it settles on the voice. */
  static blend(print: Float32Array, sample: Float32Array, weight = 0.3): Float32Array {
    const out = new Float32Array(print.length);
    for (let i = 0; i < out.length; i++) out[i] = print[i] * (1 - weight) + sample[i] * weight;
    return normalize(out);
  }

  /** Make a voiceprint from a recording of you reading for a few seconds. */
  async enroll(pcm: Int16Array): Promise<{ ok: boolean; message: string }> {
    if (!this.model && !(await this.preload())) return { ok: false, message: this.modelError || "The voice model isn't available." };
    const voiced = voicedOnly(pcm, 30);
    const seconds = voiced.length / SAMPLE_RATE;
    if (seconds < 5) return { ok: false, message: `Only heard ${seconds.toFixed(1)} seconds of speech. Read all three sentences, a little louder, and try again.` };
    // Average several 3-second pieces, so one cough or bad word doesn't spoil it.
    const win = 3 * SAMPLE_RATE;
    const parts: Float32Array[] = [];
    for (let i = 0; i + win * 0.6 <= voiced.length; i += win) parts.push(await this.embed(voiced.subarray(i, Math.min(voiced.length, i + win))));
    const mean = new Float32Array(parts[0].length);
    for (const p of parts) for (let i = 0; i < mean.length; i++) mean[i] += p[i] / parts.length;
    const print = normalize(mean);
    const fit = Math.min(...parts.map((p) => dot(p, print)));
    this.voiceprint = print;
    saveJson(VOICEPRINT_FILE, { created: new Date().toISOString(), seconds: Math.round(seconds), embedding: Array.from(print) });
    console.log(`[voice-match] voiceprint saved (${seconds.toFixed(1)} s of speech, ${parts.length} pieces, consistency ${fit.toFixed(2)})`);
    this.changed();
    return { ok: true, message: "Got it. It will now answer only your voice." };
  }

  forgetVoice(): void {
    this.voiceprint = null;
    fs.rmSync(VOICEPRINT_FILE, { force: true });
    console.log("[voice-match] voiceprint deleted");
    this.changed();
  }
}

export const listening = new Listening();
export const blendVoice = Listening.blend;

// ---- helpers ----------------------------------------------------------------------

function sanitize(raw: any): Partial<ListeningSettings> {
  const out: Partial<ListeningSettings> = {};
  if (!raw || typeof raw !== "object") return out;
  if (typeof raw.wakeWord === "boolean") out.wakeWord = raw.wakeWord;
  if (typeof raw.wakePhrase === "string") {
    const p = raw.wakePhrase.replace(/[^\p{L}\p{N}' -]/gu, " ").replace(/\s+/g, " ").trim().slice(0, 40);
    if (p.split(" ").some((w: string) => w.length >= 2)) out.wakePhrase = p;
  }
  if (Number.isFinite(raw.awakeSeconds)) out.awakeSeconds = Math.max(5, Math.min(120, Math.round(raw.awakeSeconds)));
  if (typeof raw.voiceMatch === "boolean") out.voiceMatch = raw.voiceMatch;
  if (raw.strictness in THRESHOLDS) out.strictness = raw.strictness;
  if (typeof raw.focusSpeaker === "boolean") out.focusSpeaker = raw.focusSpeaker;
  return out;
}

function saveJson(file: string, value: unknown): void {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(value), { mode: 0o600 });
    fs.renameSync(tmp, file);
  } catch (err) {
    console.warn(`[listening] couldn't save ${path.basename(file)}: ${(err as Error).message}`);
  }
}

const GREETINGS = new Set(["hey", "hi", "hay", "hei", "ok", "okay", "hello", "yo", "a"]);
/** Common ways speech recognition mishears a name. Only trusted right after a greeting. */
const SOUNDALIKES: Record<string, string[]> = {
  claude: ["cloud", "claud", "clawed", "clod", "clyde", "claudia", "clot"],
  orb: ["or", "orbs", "orby", "orve", "herb"],
  cipher: ["cypher", "sipher", "sypher", "sifer", "cifer", "syfer", "psypher", "psyfer", "saifer", "sighfer", "siphur"],
};
/** Names distinctive enough that their soundalikes count even without "hey" in front. */
const DISTINCT_NAMES = new Set(["cipher"]);

function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}' ]/gu, " ")
    .split(/\s+/)
    .map((w) => w.replace(/'s$/, "").replace(/'/g, ""))
    .filter(Boolean);
}

export function matchesWakePhrase(text: string, phrase: string): boolean {
  const said = words(text);
  const p = words(phrase);
  if (!said.length || !p.length) return false;
  const hasGreeting = GREETINGS.has(p[0]) && p.length > 1;
  const name = hasGreeting ? p.slice(1) : p;
  const close = (a: string, b: string, loose: boolean) =>
    a === b || (b.length >= 5 && editDistance(a, b) <= 1) || (loose && (SOUNDALIKES[b] ?? []).includes(a));
  for (let i = 0; i + name.length <= said.length; i++) {
    const greeted = i > 0 && GREETINGS.has(said[i - 1]);
    const exact = name.every((w, k) => close(said[i + k], w, false));
    const loose = (greeted || (name.length === 1 && DISTINCT_NAMES.has(name[0]))) && name.every((w, k) => close(said[i + k], w, true));
    // A short name on its own ("orb") is too easy to hear by accident: it needs the greeting.
    const longEnough = name.join("").length >= 5;
    if (loose || (exact && (greeted || longEnough || !hasGreeting))) return true;
  }
  return false;
}

function editDistance(a: string, b: string): number {
  const dp = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j];
      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return dp[b.length];
}

/**
 * Keep only the parts with speech, newest `maxSeconds`. Only pauses longer than ~0.25 s
 * are cut: chopping out every quiet moment also cuts the soft sounds inside words, and the
 * spliced result no longer sounds like the speaker.
 */
function voicedOnly(pcm: Int16Array, maxSeconds: number): Float32Array {
  const frame = 320; // 20 ms
  const n = Math.floor(pcm.length / frame);
  const rms = new Float32Array(n);
  let peak = 0;
  for (let f = 0; f < n; f++) {
    let s = 0;
    for (let i = f * frame; i < (f + 1) * frame; i++) s += (pcm[i] / 32768) ** 2;
    rms[f] = Math.sqrt(s / frame);
    if (rms[f] > peak) peak = rms[f];
  }
  const gate = Math.max(0.004, peak * 0.05);
  const loud = Array.from(rms, (r) => r >= gate);
  const keep: number[] = [];
  const GAP = 12; // frames of quiet kept inside speech (~0.25 s)
  for (let f = 0; f < n; ) {
    if (loud[f]) {
      keep.push(f++);
      continue;
    }
    let e = f;
    while (e < n && !loud[e]) e++;
    const inside = f > 0 && e < n; // a pause between two bits of speech
    const len = e - f;
    // Keep short pauses whole; of long ones (and leading/trailing silence) keep only a little edge.
    const edge = inside && len <= GAP ? len : 3;
    for (let k = f; k < Math.min(e, f + edge); k++) if (f > 0) keep.push(k);
    for (let k = Math.max(f + edge, e - 3); k < e; k++) if (e < n) keep.push(k);
    f = e;
  }
  const take = keep.slice(-Math.floor((maxSeconds * SAMPLE_RATE) / frame));
  const out = new Float32Array(take.length * frame);
  take.forEach((f, k) => {
    for (let i = 0; i < frame; i++) out[k * frame + i] = pcm[f * frame + i] / 32768;
  });
  return out;
}

function normalize(v: Float32Array): Float32Array {
  let s = 0;
  for (const x of v) s += x * x;
  const n = Math.sqrt(s) || 1;
  for (let i = 0; i < v.length; i++) v[i] /= n;
  return v;
}

function dot(a: Float32Array, b: Float32Array): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}
