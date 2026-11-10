import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import os from "node:os";
import { config } from "./config.js";
import { httpFetch } from "./net.js";

/**
 * Smart Turn v3.2 (pipecat-ai/smart-turn-v3 on Hugging Face, BSD-2-Clause): an 8 MB
 * open model that listens to the end of what you said (intonation, a trailing "um…",
 * an unfinished phrase) and judges whether you've finished your turn or are just
 * pausing. Runs on this machine's CPU in about 10–30 ms.
 *
 * Input: the last 8 s of 16 kHz mono audio, left-padded with silence, turned into
 * Whisper log-mel features. Output: probability that the turn is complete.
 */

const SAMPLE_RATE = 16000;
const WINDOW_SAMPLES = 8 * SAMPLE_RATE;
const MODEL_FILE = "smart-turn-v3.2-cpu.onnx";
// Pinned to a known revision and checked against its published hash.
const MODEL_REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93";
const MODEL_SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f";
const MODEL_URL = `https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/${MODEL_REVISION}/${MODEL_FILE}`;
const MODEL_PATH = path.join(config.dataDir, "models", MODEL_FILE);

type Ort = typeof import("onnxruntime-node");

interface Loaded {
  ort: Ort;
  session: import("onnxruntime-node").InferenceSession;
  extract: (audio: Float32Array) => Promise<{ input_features: { data: Float32Array; dims: number[] } }>;
}

let loading: Promise<Loaded | null> | null = null;
let ready: Loaded | null = null;

/** Start loading in the background (downloads the model the first time). Safe to call repeatedly. */
export function preloadSmartTurn(): void {
  if (!config.smartTurn || loading) return;
  loading = load()
    .then((l) => {
      ready = l;
      return l;
    })
    .catch((err) => {
      console.warn(`[smart-turn] off: ${(err as Error).message}`);
      return null;
    });
}

export function smartTurnReady(): boolean {
  return ready !== null;
}

/**
 * Probability (0–1) that the speaker has finished, judged from the end of `pcm16`
 * (16 kHz mono, 16-bit). Returns null if the model isn't available.
 */
export async function predictTurnComplete(pcm16: Int16Array): Promise<number | null> {
  const m = ready;
  if (!m) return null;
  const audio = new Float32Array(WINDOW_SAMPLES); // zeros at the start = left padding
  const take = Math.min(pcm16.length, WINDOW_SAMPLES);
  const src = pcm16.subarray(pcm16.length - take);
  const off = WINDOW_SAMPLES - take;
  for (let i = 0; i < take; i++) audio[off + i] = src[i] / 32768;

  // Zero-mean, unit-variance normalisation (WhisperFeatureExtractor do_normalize=True).
  let mean = 0;
  for (let i = 0; i < audio.length; i++) mean += audio[i];
  mean /= audio.length;
  let v = 0;
  for (let i = 0; i < audio.length; i++) v += (audio[i] - mean) ** 2;
  const std = Math.sqrt(v / audio.length + 1e-7);
  for (let i = 0; i < audio.length; i++) audio[i] = (audio[i] - mean) / std;

  const { input_features } = await m.extract(audio);
  const feeds = { input_features: new m.ort.Tensor("float32", input_features.data, [1, 80, 800]) };
  const out = await m.session.run(feeds);
  const first = out[m.session.outputNames[0]];
  return Number((first.data as Float32Array)[0]);
}

async function load(): Promise<Loaded> {
  await ensureModel();
  const ort: Ort = await import("onnxruntime-node");
  const session = await ort.InferenceSession.create(MODEL_PATH, {
    executionMode: "sequential",
    interOpNumThreads: 1,
    // A few threads: ~13 ms instead of ~40 ms per check on an Apple Silicon Mac.
    intraOpNumThreads: Math.max(1, Math.min(4, os.availableParallelism() - 1)),
    graphOptimizationLevel: "all",
  });
  // Hugging Face transformers.js ships the same Whisper log-mel front end the model was trained on.
  const { WhisperFeatureExtractor } = await import("@huggingface/transformers");
  const fe: any = new (WhisperFeatureExtractor as any)({
    feature_size: 80,
    sampling_rate: SAMPLE_RATE,
    hop_length: 160,
    chunk_length: 8,
    n_fft: 400,
    n_samples: WINDOW_SAMPLES,
    nb_max_frames: 800,
    padding_value: 0,
  });
  const extract = (audio: Float32Array) => fe(audio);
  const loaded: Loaded = { ort, session, extract };
  // Warm up once so the first real turn isn't slow.
  ready = loaded;
  const t = performance.now();
  await predictTurnComplete(new Int16Array(SAMPLE_RATE));
  console.log(`  Turn detection: Smart Turn v3.2 (local, warm-up ${Math.round(performance.now() - t)} ms).`);
  return loaded;
}

async function ensureModel(): Promise<void> {
  if (fs.existsSync(MODEL_PATH) && sha256(fs.readFileSync(MODEL_PATH)) === MODEL_SHA256) return;
  console.log("  Turn detection: downloading Smart Turn v3.2 (8.7 MB, once)…");
  const res = await httpFetch(MODEL_URL, { signal: AbortSignal.timeout(60_000) });
  if (!res.ok) throw new Error(`couldn't download the Smart Turn model (HTTP ${res.status})`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (sha256(buf) !== MODEL_SHA256) throw new Error("the downloaded Smart Turn model didn't match its expected checksum");
  fs.mkdirSync(path.dirname(MODEL_PATH), { recursive: true });
  const tmp = `${MODEL_PATH}.tmp`;
  fs.writeFileSync(tmp, buf);
  fs.renameSync(tmp, MODEL_PATH);
}

function sha256(buf: Buffer): string {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

/** The last few seconds of what the user said, for Smart Turn. */
export class AudioTail {
  private readonly buf = new Int16Array(WINDOW_SAMPLES);
  private filled = 0;
  private pos = 0;

  push(chunk: Buffer): void {
    const n = chunk.length >> 1;
    for (let i = 0; i < n; i++) {
      this.buf[this.pos] = chunk.readInt16LE(i * 2);
      this.pos = (this.pos + 1) % WINDOW_SAMPLES;
    }
    this.filled = Math.min(WINDOW_SAMPLES, this.filled + n);
  }

  /** Oldest to newest. */
  snapshot(): Int16Array {
    const out = new Int16Array(this.filled);
    const start = (this.pos - this.filled + WINDOW_SAMPLES) % WINDOW_SAMPLES;
    for (let i = 0; i < this.filled; i++) out[i] = this.buf[(start + i) % WINDOW_SAMPLES];
    return out;
  }

  clear(): void {
    this.filled = 0;
    this.pos = 0;
  }
}
