// Runs on the audio thread. Downsamples the mic to 16 kHz mono 16-bit PCM
// (what Deepgram expects) and posts 20 ms frames plus their loudness (RMS).

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 320; // 20 ms at 16 kHz

class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.pos = 0;
    this.acc = 0;
    this.count = 0;
    this.frame = new Int16Array(FRAME_SAMPLES);
    this.idx = 0;
    this.sumSq = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      // Box-filter decimation: average the input samples that fall into each output sample.
      this.acc += channel[i];
      this.count++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const s = Math.max(-1, Math.min(1, this.acc / this.count));
        this.acc = 0;
        this.count = 0;
        this.sumSq += s * s;
        this.frame[this.idx++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.idx === FRAME_SAMPLES) {
          const rms = Math.sqrt(this.sumSq / FRAME_SAMPLES);
          this.port.postMessage({ pcm: this.frame.buffer, rms }, [this.frame.buffer]);
          this.frame = new Int16Array(FRAME_SAMPLES);
          this.idx = 0;
          this.sumSq = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("mic-processor", MicProcessor);
