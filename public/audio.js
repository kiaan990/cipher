// Mic capture and gapless playback of streamed PCM, both on one AudioContext.

const PLAYBACK_RATE = 24000; // ElevenLabs pcm_24000
const NOISE = "/vendor/noise/";

let rnnoiseWasm = null;
/** RNNoise (xiph/rnnoise, BSD licence) as an AudioWorklet: removes fans, typing, traffic, TV hum. */
async function rnnoiseNode(ctx) {
  const lib = await import(`${NOISE}index.js`);
  rnnoiseWasm ??= await lib.loadRnnoise({ url: `${NOISE}rnnoise.wasm`, simdUrl: `${NOISE}rnnoise_simd.wasm` });
  await ctx.audioWorklet.addModule(`${NOISE}rnnoise/workletProcessor.js`);
  return new lib.RnnoiseWorkletNode(ctx, { maxChannels: 1, wasmBinary: rnnoiseWasm });
}

export class AudioEngine {
  /**
   * @param {{ onMicFrame: (pcm: ArrayBuffer, rms: number) => void,
   *           onPlaybackChange: (playing: boolean) => void }} handlers
   */
  constructor(handlers) {
    this.handlers = handlers;
    this.ctx = null;
    this.sources = new Set();
    this.nextTime = 0;
    this.playing = false;
    this.buf = null;
  }

  /** @param {{ noiseFilter?: boolean }} [opts] noiseFilter: clean the mic with RNNoise before anything hears it. */
  async start(opts = {}) {
    // RNNoise works at 48 kHz, so ask for that when it's on (the mic worklet resamples to 16 kHz either way).
    const ctx = new AudioContext(opts.noiseFilter ? { latencyHint: "interactive", sampleRate: 48000 } : { latencyHint: "interactive" });
    this.ctx = ctx;
    await ctx.audioWorklet.addModule("mic-worklet.js");

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        // With RNNoise on, Chrome's own (weaker) suppressor would only add artefacts.
        noiseSuppression: !opts.noiseFilter,
        autoGainControl: true,
        channelCount: 1,
      },
    });

    // --- input
    let mic = ctx.createMediaStreamSource(this.stream);
    this.noiseFilter = false;
    if (opts.noiseFilter) {
      try {
        mic = mic.connect(await rnnoiseNode(ctx));
        this.noiseFilter = true;
      } catch (err) {
        console.warn("Noise filter unavailable, using the plain microphone:", err);
      }
    }
    this.micAnalyser = ctx.createAnalyser();
    this.micAnalyser.fftSize = 1024;
    this.micAnalyser.smoothingTimeConstant = 0.6;
    this.micAnalyser.minDecibels = -90;
    this.micAnalyser.maxDecibels = -20;
    this.worklet = new AudioWorkletNode(ctx, "mic-processor");
    this.worklet.port.onmessage = (e) => this.handlers.onMicFrame(e.data.pcm, e.data.rms);
    mic.connect(this.micAnalyser);
    mic.connect(this.worklet);
    // Keep the worklet pulled by the graph without making it audible.
    const sink = ctx.createGain();
    sink.gain.value = 0;
    this.worklet.connect(sink).connect(ctx.destination);

    // --- output
    this.outGain = ctx.createGain();
    this.outAnalyser = ctx.createAnalyser();
    this.outAnalyser.fftSize = 1024;
    this.outAnalyser.smoothingTimeConstant = 0.6;
    this.outAnalyser.minDecibels = -90;
    this.outAnalyser.maxDecibels = -20;
    this.outGain.connect(this.outAnalyser);
    // Play through an <audio> element rather than straight to the speakers:
    // Chrome's echo canceller only "hears" audio played that way, which is what
    // stops Claude's own voice from being picked up as an interruption.
    const dest = ctx.createMediaStreamDestination();
    this.outAnalyser.connect(dest);
    this.audioEl = new Audio();
    this.audioEl.srcObject = dest.stream;
    this.audioEl.autoplay = true;
    try {
      await this.audioEl.play();
    } catch {
      // Fallback: direct output.
      this.outAnalyser.disconnect();
      this.outAnalyser.connect(ctx.destination);
    }

    this.buf = new Float32Array(this.micAnalyser.fftSize);
    if (ctx.state === "suspended") await ctx.resume();
  }

  /**
   * Turn Claude's voice down while something loud is heard, without stopping it. Whether it
   * stops is decided by the words actually heard (on the server), so a cough or the TV
   * doesn't cut a reply off.
   */
  duck(on) {
    if (!this.ctx || !this.outGain || this.ducked === on) return;
    this.ducked = on;
    this.outGain.gain.setTargetAtTime(on ? 0.3 : 1, this.ctx.currentTime, on ? 0.03 : 0.12);
  }

  /** Queue one chunk of 16-bit PCM for gapless playback. */
  playPcm(arrayBuffer) {
    const ctx = this.ctx;
    if (!ctx) return;
    const int16 = new Int16Array(arrayBuffer);
    if (!int16.length) return;
    const buffer = ctx.createBuffer(1, int16.length, PLAYBACK_RATE);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < int16.length; i++) data[i] = int16[i] / 32768;

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.outGain);
    // Small lead-in when starting from silence absorbs network jitter.
    const startAt = Math.max(this.nextTime, ctx.currentTime + 0.05, this.fadeEnd || 0);
    src.start(startAt);
    this.nextTime = startAt + buffer.duration;
    this.sources.add(src);
    src.onended = () => {
      this.sources.delete(src);
      if (this.sources.size === 0) this.setPlaying(false);
    };
    this.setPlaying(true);
  }

  /** Turn base64 16-bit PCM clips into ready-to-play buffers. */
  loadCues(clips) {
    if (!this.ctx) return;
    this.cues = clips.map((b64) => {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const int16 = new Int16Array(bytes.buffer, 0, bytes.length >> 1);
      const buffer = this.ctx.createBuffer(1, Math.max(1, int16.length), PLAYBACK_RATE);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < int16.length; i++) data[i] = int16[i] / 32768;
      return buffer;
    });
  }

  /**
   * A quiet listener sound ("mm-hmm") on its own channel: it goes through the same
   * echo-cancelled output, but doesn't count as Claude speaking, so talking over it
   * never triggers an interruption.
   */
  playCue(index, volume = 0.55) {
    const buffer = this.cues?.[index];
    if (!this.ctx || !buffer || this.playing) return false;
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    const gain = this.ctx.createGain();
    gain.gain.value = volume;
    src.connect(gain).connect(this.outGain);
    src.start(this.ctx.currentTime + 0.01);
    this.cueSrc = src;
    src.onended = () => {
      gain.disconnect();
      if (this.cueSrc === src) this.cueSrc = null;
    };
    return true;
  }

  /** Natural pause between sentences. */
  addGap(seconds) {
    if (this.ctx && this.nextTime > this.ctx.currentTime) this.nextTime += seconds;
  }

  /**
   * Stop and drop everything queued. `fade`: trail off over ~0.15 s like a person
   * stopping mid-word, instead of a hard cut.
   */
  stopPlayback(fade = false) {
    try {
      this.cueSrc?.stop();
    } catch {}
    const ctx = this.ctx;
    const soft = fade && ctx && this.outGain && this.sources.size > 0;
    const end = soft ? ctx.currentTime + 0.15 : 0;
    if (soft) {
      const g = this.outGain.gain;
      g.cancelScheduledValues(ctx.currentTime);
      g.setValueAtTime(g.value, ctx.currentTime);
      g.linearRampToValueAtTime(0, end);
      g.setValueAtTime(1, end + 0.01);
      this.ducked = false;
      this.fadeEnd = end + 0.01;
    }
    for (const src of this.sources) {
      src.onended = null;
      try {
        if (soft) {
          src.stop(end);
          setTimeout(() => src.disconnect(), 250);
        } else {
          src.stop();
          src.disconnect();
        }
      } catch {}
    }
    this.sources.clear();
    this.nextTime = 0;
    this.setPlaying(false);
  }

  get isPlaying() {
    return this.playing;
  }

  levelIn() {
    return this.rms(this.micAnalyser);
  }

  levelOut() {
    return this.rms(this.outAnalyser);
  }

  /** Fill `out` with 0..1 energies in log-spaced bands across the voice range. */
  spectrum(out, which = "in") {
    const an = which === "out" ? this.outAnalyser : this.micAnalyser;
    if (!an) return out.fill(0);
    if (!this.fbuf) this.fbuf = new Uint8Array(an.frequencyBinCount);
    an.getByteFrequencyData(this.fbuf);
    const n = out.length;
    const span = 150; // ~7 kHz at 48 kHz / 1024
    for (let i = 0; i < n; i++) {
      const lo = Math.floor(2 + Math.pow(i / n, 1.7) * span);
      const hi = Math.max(lo + 1, Math.floor(2 + Math.pow((i + 1) / n, 1.7) * span));
      let m = 0;
      for (let b = lo; b < hi; b++) if (this.fbuf[b] > m) m = this.fbuf[b];
      out[i] = Math.max(0, (m / 255 - 0.3) / 0.7);
    }
    return out;
  }

  rms(analyser) {
    if (!analyser || !this.buf) return 0;
    analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    return Math.sqrt(sum / this.buf.length);
  }

  setPlaying(playing) {
    if (this.playing === playing) return;
    this.playing = playing;
    this.handlers.onPlaybackChange(playing);
  }

  async stop() {
    this.stopPlayback();
    this.stream?.getTracks().forEach((t) => t.stop());
    if (this.audioEl) this.audioEl.srcObject = null;
    try {
      await this.ctx?.close();
    } catch {}
    this.ctx = null;
  }
}
