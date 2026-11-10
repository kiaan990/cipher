import fs from "node:fs";
import path from "node:path";
import { config } from "./config.js";
import { httpFetch } from "./net.js";
import { voice } from "./tts.js";

/**
 * Backchannels: the little "mm-hm" / "yeah" a listener makes while you're mid-thought.
 * Made once with the same voice Claude speaks with, cached in data/backchannels/, and
 * sent to the page, which plays them quietly on their own channel. They never enter the
 * conversation history and never count as Claude talking.
 */

/** What kind of listener sound a clip is, so it can fit what the user is saying. */
export type CueKind = "neutral" | "surprise" | "sympathy" | "understand" | "laugh" | "yield";

/**
 * Listener sounds. Made with ElevenLabs' expressive model (eleven_v3: soft, breathy,
 * real laughs) since they're recorded once and cached, so its slower speed doesn't matter.
 * Several takes of the commonest ones, so it never sounds like the same clip on repeat.
 */
const CUES: Array<{ text: string; kind: CueKind }> = [
  { text: "[softly] Mm-hmm.", kind: "neutral" },
  { text: "[softly] Mm-hmm.", kind: "neutral" },
  { text: "[quietly] Mhm.", kind: "neutral" },
  { text: "[softly] Yeah.", kind: "neutral" },
  { text: "[softly] Yeah.", kind: "neutral" },
  { text: "[quietly] Yeah, yeah.", kind: "neutral" },
  { text: "[softly] Right.", kind: "neutral" },
  { text: "[softly] Uh-huh.", kind: "neutral" },
  { text: "[softly] Yep.", kind: "neutral" },
  { text: "[surprised] Oh wow.", kind: "surprise" },
  { text: "[happy] Oh, nice!", kind: "surprise" },
  { text: "[surprised] No way.", kind: "surprise" },
  { text: "[sympathetic] Oh no.", kind: "sympathy" },
  { text: "[sympathetic] Aw, man.", kind: "sympathy" },
  { text: "[sympathetic] Oof.", kind: "sympathy" },
  { text: "[softly] Got it.", kind: "understand" },
  { text: "[softly] Okay, sure.", kind: "understand" },
  { text: "[softly] I see.", kind: "understand" },
  { text: "[chuckles] Ha.", kind: "laugh" },
  { text: "[laughs softly] Ha, yeah.", kind: "laugh" },
  { text: "Oh, sorry, go ahead.", kind: "yield" },
  { text: "Sorry, you go.", kind: "yield" },
];
/** Bump to re-record every clip. */
const CUE_SET = "v2";
/** Lower-case forms speech recognition may hear if a cue leaks back into the mic. */
export const CUE_ECHOES = new Set([
  "mm-hmm", "mhm", "mm-hm", "mm hmm", "mmhmm", "hmm", "mm", "yeah", "yeah yeah", "right", "uh-huh", "uh huh", "uhhuh", "okay", "ok", "yep",
  "oh wow", "wow", "oh nice", "nice", "no way", "oh no", "aw man", "oof", "got it", "okay sure", "i see", "ha", "ha yeah", "haha",
  "oh sorry go ahead", "sorry go ahead", "sorry you go",
]);

const RATE = 24000;
let clips: string[] = []; // base64 16-bit PCM at 24 kHz
let kinds: CueKind[] = [];
let loadingKey = "";

export function backchannelClips(): string[] {
  return clips;
}

/** The kind of each clip in backchannelClips(), same order. */
export function backchannelKinds(): CueKind[] {
  return kinds;
}

/** Make (or load) the clips for the current voice. Cheap after the first time. */
export async function prepareBackchannels(): Promise<void> {
  if (!config.backchannels) return;
  const deepgram = voice.useDeepgram() || !config.elevenKey;
  const key = `${CUE_SET}-` + (deepgram ? `deepgram-${config.deepgramVoice}` : `eleven-${config.elevenVoiceId}-v3`);
  if (key === loadingKey) return;
  loadingKey = key;
  const dir = path.join(config.dataDir, "backchannels", key.replace(/[^\w.-]/g, "_"));
  const out: string[] = [];
  const outKinds: CueKind[] = [];
  for (let i = 0; i < CUES.length; i++) {
    const cue = CUES[i];
    // Deepgram's voice can't laugh: skip those rather than read "ha" out flatly.
    if (deepgram && cue.kind === "laugh") continue;
    const file = path.join(dir, `${i}.pcm`);
    try {
      let pcm: Buffer;
      if (fs.existsSync(file)) pcm = fs.readFileSync(file);
      else {
        let raw: Buffer;
        try {
          raw = await synthesize(cue.text, deepgram).catch((err) => {
            // The expressive model refused: the everyday one still works (without laughs).
            if (deepgram || cue.kind === "laugh") throw err;
            return synthesize(cue.text, false, config.elevenModelId);
          });
        } catch (err) {
          if (!deepgram && cue.kind === "laugh") throw err;
          // ElevenLabs refused (e.g. out of credits): don't leave the listener silent.
          if (deepgram || !config.deepgramKey) throw err;
          loadingKey = "";
          voice.elevenLabsOut();
          return prepareBackchannels();
        }
        pcm = shape(raw);
        if (pcm.length < RATE * 2 * 0.15) throw new Error("clip came back empty");
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(file, pcm);
      }
      out.push(pcm.toString("base64"));
      outKinds.push(cue.kind);
    } catch (err) {
      console.warn(`[backchannel] couldn't make "${cue.text}": ${(err as Error).message}`);
    }
  }
  if (key !== loadingKey) return; // the voice changed meanwhile
  if (!out.length) loadingKey = ""; // try again next conversation
  clips = out;
  kinds = outKinds;
  if (out.length) console.log(`  Backchannels: ${out.length} listener sounds ready.`);
}

async function synthesize(tagged: string, deepgram: boolean, model = "eleven_v3"): Promise<Buffer> {
  const text = deepgram || model !== "eleven_v3" ? tagged.replace(/\[[^\]]*\]\s*/g, "") : tagged;
  const res = deepgram
    ? await httpFetch(`https://api.deepgram.com/v1/speak?model=${encodeURIComponent(config.deepgramVoice)}&encoding=linear16&sample_rate=${RATE}&container=none`, {
        method: "POST",
        headers: { Authorization: `Token ${config.deepgramKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(15_000),
      })
    : await httpFetch(`https://api.elevenlabs.io/v1/text-to-speech/${encodeURIComponent(config.elevenVoiceId)}?output_format=pcm_${RATE}`, {
        method: "POST",
        headers: { "xi-api-key": config.elevenKey, "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          model_id: model,
          // Relaxed and soft, like an aside rather than an answer. (v3 only takes 0, 0.5 or 1.)
          voice_settings: { stability: model === "eleven_v3" ? 0.5 : 0.3, similarity_boost: 0.75, use_speaker_boost: true },
        }),
        signal: AbortSignal.timeout(30_000),
      });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

/** Trim the silence around the word and fade the edges so it starts and ends softly. */
function shape(raw: Buffer): Buffer {
  const n = raw.length >> 1;
  const s = new Int16Array(n);
  for (let i = 0; i < n; i++) s[i] = raw.readInt16LE(i * 2);
  const loud = (i: number) => Math.abs(s[i]) > 600;
  let a = 0;
  while (a < n && !loud(a)) a++;
  let b = n - 1;
  while (b > a && !loud(b)) b--;
  a = Math.max(0, a - RATE * 0.02);
  b = Math.min(n - 1, b + RATE * 0.06);
  const len = Math.max(0, b - a + 1);
  const fade = Math.min(Math.floor(RATE * 0.015), len >> 2);
  const out = Buffer.alloc(len * 2);
  for (let i = 0; i < len; i++) {
    const g = fade > 0 ? Math.min(1, i / fade, (len - 1 - i) / fade) : 1;
    out.writeInt16LE(Math.round(s[a + i] * g), i * 2);
  }
  return out;
}
