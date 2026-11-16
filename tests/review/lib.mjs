// A scripted "browser" for Cipher: connects to the app's WebSocket, plays recordings in
// as if spoken into the mic (20 ms frames, real time), pretends to play the reply the way
// the page does, and writes down when everything happened.
//
// Nothing here changes the app. Point it at a running copy with PORT (default 3111, the
// isolated test copy; the live app is 3000).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

export const PORT = Number(process.env.PORT || 3111);
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const FRAME = 640; // 20 ms of 16 kHz 16-bit mono
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cipher-review-"));

/** Speech from the Mac's own voices: 16 kHz mono PCM. Not a real person, a real mic or a real room. */
export function tts(text, voice = "Samantha", rate = 185) {
  const f = path.join(tmp, `${Math.random().toString(36).slice(2)}.wav`);
  execFileSync("say", ["-v", voice, "-r", String(rate), "-o", f, "--data-format=LEI16@16000", text]);
  const w = fs.readFileSync(f);
  fs.unlinkSync(f);
  return w.subarray(w.indexOf("data") + 8);
}
export const silence = (ms) => Buffer.alloc(Math.round((ms / 1000) * 16000) * 2);
export const concat = (...parts) => Buffer.concat(parts);
/** White noise at a given loudness (RMS as a fraction of full scale). */
export function noise(ms, rms = 0.02) {
  const n = Math.round((ms / 1000) * 16000);
  const b = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const g = (Math.random() + Math.random() + Math.random() + Math.random() - 2) * 0.866; // ~unit variance
    b.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(g * rms * 32768))), i * 2);
  }
  return b;
}
/** Mix b under a (b is looped or cut to a's length), scaling b by `gain`. */
export function mix(a, b, gain = 1) {
  const out = Buffer.alloc(a.length);
  for (let i = 0; i + 1 < a.length; i += 2) {
    const s = a.readInt16LE(i) + gain * b.readInt16LE(i % (b.length - 1) & ~1);
    out.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(s))), i);
  }
  return out;
}
export function rms(b) {
  let s = 0;
  for (let i = 0; i + 1 < b.length; i += 2) s += b.readInt16LE(i) ** 2;
  return Math.sqrt(s / Math.max(1, b.length / 2)) / 32768;
}

export async function connect(label = "review", { port = PORT, origin = false } = {}) {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/ws?session=review-${label}-${Date.now()}`, origin ? { headers: { Origin: `http://127.0.0.1:${port}` } } : undefined);
  ws.binaryType = "arraybuffer";
  const c = {
    ws,
    events: [], // every JSON message, with the time it arrived
    turns: new Map(), // turnId -> { tThinking, tFirstDelta, tFirstAudio, tDone, text, audioBytes, audioAt: [] }
    feeding: false,
    lastLoudAt: 0,
    speechStartAt: 0,
    playingUntil: 0,
    playing: false,
    closed: false,
  };
  const waiters = [];
  c.waitFor = (pred, ms = 15000) =>
    new Promise((res) => {
      const w = { pred, res };
      waiters.push(w);
      setTimeout(() => {
        const i = waiters.indexOf(w);
        if (i >= 0) waiters.splice(i, 1);
        res(null);
      }, ms);
    });
  const turn = (id) => {
    if (!c.turns.has(id)) c.turns.set(id, { id, tThinking: 0, tFirstDelta: 0, tFirstAudio: 0, tDone: 0, tTextDone: 0, text: "", audioBytes: 0, audioAt: [], actions: [] });
    return c.turns.get(id);
  };
  // Pretend to play audio like the page: tell the server when playback starts and stops.
  const playTimer = setInterval(() => {
    if (c.playing && Date.now() > c.playingUntil + 120) {
      c.playing = false;
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: "playback", playing: false }));
    }
  }, 40);
  ws.onmessage = (e) => {
    const now = Date.now();
    if (typeof e.data !== "string") {
      const id = new DataView(e.data).getUint32(0, true);
      const t = turn(id);
      const bytes = e.data.byteLength - 4;
      if (!t.tFirstAudio) t.tFirstAudio = now;
      t.audioAt.push([now, bytes]);
      t.audioBytes += bytes;
      c.playingUntil = Math.max(c.playingUntil, now) + (bytes / 48000) * 1000;
      if (!c.playing) {
        c.playing = true;
        ws.send(JSON.stringify({ type: "playback", playing: true }));
      }
      return;
    }
    const m = JSON.parse(e.data);
    m._t = now;
    c.events.push(m);
    if (m.turnId != null) {
      const t = turn(m.turnId);
      if (m.type === "thinking") t.tThinking = now;
      if (m.type === "assistant_delta") {
        if (!t.tFirstDelta) t.tFirstDelta = now;
        t.text += m.text ?? "";
      }
      if (m.type === "assistant_done") t.tTextDone = now;
      if (m.type === "tts_done") t.tDone = now;
      if (m.type === "action") t.actions.push(m);
      if (m.type === "interrupted" || m.type === "turn_cancelled") {
        t[m.type] = now;
        c.playingUntil = now; // the page flushes its audio
      }
    }
    for (const w of [...waiters])
      if (w.pred(m)) {
        waiters.splice(waiters.indexOf(w), 1);
        w.res(m);
      }
  };
  ws.onclose = () => {
    c.closed = true;
    clearInterval(playTimer);
  };
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = () => rej(new Error(`couldn't connect to the app on port ${port}`));
  });
  // The mic never stops: silence goes out whenever no recording is playing.
  const mic = setInterval(() => {
    if (!c.feeding && ws.readyState === 1 && c.micOn) ws.send(new Uint8Array(FRAME));
  }, 20);
  ws.addEventListener("close", () => clearInterval(mic));
  c.send = (o) => ws.send(JSON.stringify(o));
  c.start = async () => {
    c.send({ type: "start" });
    const ready = await c.waitFor((m) => m.type === "ready" || m.type === "error", 12000);
    c.micOn = true;
    await sleep(800);
    return ready;
  };
  /** Play a recording into the mic in real time. Returns when the last frame has gone. */
  c.speak = async (pcm) => {
    c.feeding = true;
    c.speechStartAt = 0;
    const t0 = performance.now();
    for (let i = 0, n = 0; i < pcm.length; i += FRAME, n++) {
      const frame = pcm.subarray(i, i + FRAME);
      ws.send(frame.length === FRAME ? frame : Buffer.concat([frame, Buffer.alloc(FRAME - frame.length)]));
      if (rms(frame) > 0.01) {
        c.lastLoudAt = Date.now();
        if (!c.speechStartAt) c.speechStartAt = Date.now();
      }
      const due = t0 + (n + 1) * 20;
      const wait = due - performance.now();
      if (wait > 0) await sleep(wait);
    }
    c.feeding = false;
    return c.lastLoudAt;
  };
  /** Typed text, as the page's own buttons send it: no speech recognition, no wake word. */
  c.type = (text) => c.send({ type: "say", text });
  c.since = (t) => c.events.filter((m) => m._t >= t);
  c.lastTurn = () => [...c.turns.values()].sort((a, b) => b.id - a.id)[0];
  /** Wait until the newest reply has finished (text and voice) and nothing new has started for `quiet` ms. */
  c.settle = async (ms = 60000, quiet = 1200) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const t = c.lastTurn();
      const lastEvent = c.events.length ? c.events[c.events.length - 1]._t : 0;
      if (t && (t.tDone || t.interrupted || t.turn_cancelled) && Date.now() - Math.max(lastEvent, t.tDone || 0) > quiet && !c.playing) return t;
      await sleep(100);
    }
    return c.lastTurn();
  };
  c.close = async () => {
    try {
      c.send({ type: "reset" });
      c.send({ type: "stop" });
    } catch {}
    await sleep(200);
    ws.close();
  };
  return c;
}

/** One spoken question, start to finish, with every stage timed (ms). */
export async function ask(c, pcm, { timeout = 45000 } = {}) {
  const before = c.events.length;
  const turnsBefore = new Set(c.turns.keys());
  const eos = await c.speak(pcm);
  const isEnd = (m) => m.type === "user_turn" || m.type === "ignored" || m.type === "voice_rejected";
  // The turn is sometimes accepted before the last (quiet) frames of the recording have gone out.
  const userTurn = c.events.slice(before).find(isEnd) ?? (await c.waitFor(isEnd, 8000));
  if (!userTurn || userTurn.type !== "user_turn") return { answered: false, why: userTurn?.type ?? "no end of turn within 8 s", eos };
  const isDone = (m) => m.type === "tts_done" && !turnsBefore.has(m.turnId);
  const done = c.events.slice(before).find(isDone) ?? (await c.waitFor(isDone, timeout));
  await sleep(150);
  const ev = c.events.slice(before);
  const t = [...c.turns.values()].filter((x) => !turnsBefore.has(x.id) && x.tFirstDelta).sort((a, b) => b.id - a.id)[0];
  const lastTranscript = ev.filter((m) => m.type === "transcript" && m._t <= userTurn._t).pop();
  const firstInterim = ev.find((m) => m.type === "transcript" && m._t >= eos - 200);
  return {
    answered: Boolean(t?.tFirstAudio),
    heard: userTurn.text,
    reply: t?.text ?? "",
    eos,
    // stage by stage
    eos_to_last_words: lastTranscript ? lastTranscript._t - eos : null, // speech recognition catching up
    eos_to_turn: userTurn._t - eos, // deciding you had finished (includes the above)
    turn_to_first_word: t?.tFirstDelta ? t.tFirstDelta - userTurn._t : null, // the model
    first_word_to_audio: t?.tFirstAudio && t.tFirstDelta ? t.tFirstAudio - t.tFirstDelta : null, // sentence + voice
    eos_to_audio: t?.tFirstAudio ? t.tFirstAudio - eos : null, // what you wait
    audio_s: t ? +(t.audioBytes / 48000).toFixed(1) : 0,
    total_ms: done ? done._t - eos : null,
    turn: t,
    firstInterim: firstInterim ? firstInterim._t - eos : null,
    actions: t?.actions ?? [],
    cancelled: ev.filter((m) => m.type === "turn_cancelled").length,
  };
}

/** One typed request; waits for the reply to finish. */
export async function typed(c, text, { timeout = 90000 } = {}) {
  const turnsBefore = new Set(c.turns.keys());
  const t0 = Date.now();
  c.type(text);
  const done = await c.waitFor((m) => m.type === "tts_done" && !turnsBefore.has(m.turnId), timeout);
  await sleep(150);
  const t = [...c.turns.values()].filter((x) => !turnsBefore.has(x.id)).sort((a, b) => b.id - a.id)[0];
  return {
    reply: t?.text ?? "",
    first_word_ms: t?.tFirstDelta ? t.tFirstDelta - t0 : null,
    first_audio_ms: t?.tFirstAudio ? t.tFirstAudio - t0 : null,
    total_ms: done ? done._t - t0 : null,
    finished: Boolean(done),
    actions: (t?.actions ?? []).map((a) => `${a.kind ?? ""}:${a.status ?? ""}:${String(a.purpose ?? a.command ?? "").slice(0, 80)}`),
    turn: t,
  };
}

export const pct = (a, p) => {
  const s = a.filter((x) => Number.isFinite(x)).sort((x, y) => x - y);
  return s.length ? s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))] : NaN;
};
export const stats = (a) => ({ n: a.filter(Number.isFinite).length, p50: pct(a, 50), p90: pct(a, 90), min: Math.min(...a.filter(Number.isFinite)), max: Math.max(...a.filter(Number.isFinite)) });
/** Longest gap in the voice: time the listener would hear nothing mid-reply because audio hadn't arrived yet (ms). */
export function longestStall(turn) {
  if (!turn?.audioAt?.length) return 0;
  let playhead = turn.audioAt[0][0];
  let worst = 0;
  for (const [at, bytes] of turn.audioAt) {
    if (at > playhead) worst = Math.max(worst, at - playhead), (playhead = at);
    playhead += (bytes / 48000) * 1000;
  }
  return Math.round(worst);
}
export function save(name, data) {
  const dir = new URL("./out/", import.meta.url).pathname;
  fs.mkdirSync(dir, { recursive: true });
  const strip = (k, v) => (k === "turn" || k === "audioAt" ? undefined : v);
  fs.writeFileSync(path.join(dir, `${name}.json`), JSON.stringify(data, strip, 2));
}
