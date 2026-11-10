// Camera + on-device object detection. Frames stay in the browser: only the
// detected labels and boxes are handed to `onScene`, which forwards them to the server.

export const VISION_MODELS = {
  fast: { id: "Xenova/yolos-tiny", threshold: 0.5, label: "YOLOS tiny", size: "10–26 MB" },
  accurate: { id: "Xenova/detr-resnet-50", threshold: 0.7, label: "DETR ResNet-50", size: "45–85 MB" },
};

const FRAME_WIDTH = 480; // frames are scaled down before detection; plenty for 80 COCO classes
const MIN_INTERVAL_MS = 250; // cap detection rate (~4 fps) to leave CPU for audio and the orb
const HEARTBEAT_MS = 1500; // re-send the scene this often even when nothing changed

export class Vision {
  /**
   * @param {object} o
   * @param {HTMLVideoElement} o.video  preview element (mirrored with CSS)
   * @param {HTMLCanvasElement} o.overlay  canvas laid over the preview for boxes
   * @param {(s: {status: string, progress?: number, ms?: number, message?: string}) => void} o.onStatus
   * @param {(objects: Array<{label,score,x,y,w,h}>) => void} o.onScene  stable scene, throttled
   * @param {(obj: {label,x,y}) => void} o.onAppear  a new kind of object came into view
   */
  constructor({ video, overlay, onStatus, onScene, onAppear }) {
    Object.assign(this, { video, overlay, onStatus, onScene, onAppear });
    this.ctx = overlay.getContext("2d");
    this.stream = null;
    this.worker = null;
    this.on = false;
    this.model = "fast";
    this.status = "off";
    this.busy = false;
    this.frameId = 0;
    this.tracks = []; // boxes being drawn, eased toward their latest positions
    this.lastKey = "";
    this.pendingKey = "";
    this.lastSent = 0;
    this.knownLabels = new Set();
    this.timer = null;
    this.raf = 0;
  }

  async start(model = this.model) {
    if (this.on) return;
    this.model = model;
    this.setStatus({ status: "starting" });
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't use a camera here.");
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    this.on = true;
    this.video.srcObject = this.stream;
    await this.video.play().catch(() => {});
    if (!this.video.videoWidth) await new Promise((r) => this.video.addEventListener("loadedmetadata", r, { once: true }));
    this.stream.getVideoTracks()[0]?.addEventListener("ended", () => this.stop());

    this.retries = 0;
    this.startWorker();
    this.draw();
  }

  /**
   * Start (or restart) the detection worker and load the model. If the worker dies,
   * e.g. a GPU hiccup or the server restarting while the model files were loading,
   * it's restarted a few times, falling back to the CPU after a second failure.
   */
  startWorker() {
    this.worker?.terminate();
    this.busy = false;
    this.modelReady = false;
    const worker = new Worker(new URL("./vision-worker.js", import.meta.url), { type: "module" });
    this.worker = worker;
    worker.onmessage = (e) => this.worker === worker && this.onWorker(e.data);
    worker.onerror = (e) => {
      e.preventDefault?.();
      if (this.worker !== worker) return;
      this.workerFailed(e.message || "the detector stopped unexpectedly");
    };
    this.setStatus({ status: "loading", progress: 0 });
    worker.postMessage({ type: "load", model: VISION_MODELS[this.model].id, cpuOnly: this.retries >= 2 });
  }

  workerFailed(reason) {
    console.warn("Vision worker failed:", reason);
    if (!this.on) return;
    if (this.retries >= 4) {
      this.setStatus({ status: "error", message: `Object detection stopped (${reason}). Claude can still see camera stills.` });
      return;
    }
    this.retries++;
    this.setStatus({ status: "loading", progress: 0 });
    clearTimeout(this.restartTimer);
    this.restartTimer = setTimeout(() => this.on && this.startWorker(), 1500 * this.retries);
  }

  stop() {
    if (!this.on && !this.stream) return;
    this.on = false;
    clearTimeout(this.timer);
    clearTimeout(this.restartTimer);
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.tracks = [];
    this.knownLabels.clear();
    this.lastKey = this.pendingKey = "";
    this.ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
    this.setStatus({ status: "off" });
  }

  setModel(model) {
    if (model === this.model) return;
    this.model = model;
    if (!this.on || !this.worker) return; // start() loads the current model itself
    this.modelReady = false;
    this.tracks = [];
    this.setStatus({ status: "loading", progress: 0 });
    this.worker.postMessage({ type: "load", model: VISION_MODELS[model].id, cpuOnly: this.retries >= 2 });
  }

  setStatus(s) {
    this.status = s.status;
    this.onStatus?.(s);
  }

  onWorker(msg) {
    if (!this.on) return;
    if (msg.type === "progress" && !this.modelReady) {
      this.setStatus({ status: "loading", progress: msg.progress });
    } else if (msg.type === "ready") {
      if (msg.model !== VISION_MODELS[this.model].id) return;
      this.modelReady = true;
      this.setStatus({ status: "live" });
      this.schedule(0);
    } else if (msg.type === "result") {
      this.retries = 0;
      this.busy = false;
      if (msg.id !== this.frameId) return;
      this.ingest(msg.objects);
      this.lastMs = msg.ms;
      this.setStatus({ status: "live", ms: msg.ms });
      // Leave the graphics chip free most of the time: wait at least as long as a detection
      // took (so a slow Mac isn't kept busy), and once a second when the orb is struggling.
      const gap = globalThis.__orbPerf?.struggling ? 1000 : Math.max(MIN_INTERVAL_MS, msg.ms * 2);
      this.schedule(Math.max(0, gap - msg.ms));
    } else if (msg.type === "error") {
      this.busy = false;
      // Failing to load the model is fatal for this worker: restart it. A failed frame isn't.
      if (!this.modelReady) this.workerFailed(msg.message);
      else this.schedule(1000);
    }
  }

  schedule(ms) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.capture(), ms);
  }

  async capture() {
    if (!this.on || !this.modelReady || this.busy) return;
    if (document.hidden || this.video.readyState < 2) return this.schedule(500);
    const vw = this.video.videoWidth;
    const vh = this.video.videoHeight;
    const scale = Math.min(1, FRAME_WIDTH / vw);
    try {
      const bitmap = await createImageBitmap(this.video, {
        resizeWidth: Math.round(vw * scale),
        resizeHeight: Math.round(vh * scale),
        resizeQuality: "medium",
      });
      this.busy = true;
      const m = VISION_MODELS[this.model];
      this.worker.postMessage({ type: "frame", id: ++this.frameId, bitmap, model: m.id, threshold: m.threshold }, [bitmap]);
    } catch {
      this.schedule(500);
    }
  }

  /** Detector output -> mirrored, normalised objects; update drawing and notify. */
  ingest(raw) {
    const objects = raw.map((o) => {
      // Boxes come back as fractions of the frame. Mirror x so it matches the selfie preview.
      const xmin = 1 - o.box.xmax;
      const xmax = 1 - o.box.xmin;
      const { ymin, ymax } = o.box;
      return {
        label: o.label,
        score: o.score,
        x: (xmin + xmax) / 2,
        y: (ymin + ymax) / 2,
        w: Math.max(0, xmax - xmin),
        h: Math.max(0, ymax - ymin),
      };
    });
    this.track(objects);

    // Only report a scene once it has been the same for two frames in a row, so a
    // one-frame false positive doesn't reach Claude. Heartbeat keeps it fresh.
    const key = sceneKey(objects);
    const now = performance.now();
    const stable = key === this.pendingKey;
    this.pendingKey = key;
    if ((stable && key !== this.lastKey) || now - this.lastSent > HEARTBEAT_MS) {
      if (stable) {
        for (const o of objects) {
          if (!this.knownLabels.has(o.label)) this.onAppear?.(o);
        }
        this.knownLabels = new Set(objects.map((o) => o.label));
        this.lastKey = key;
      }
      this.lastSent = now;
      this.onScene?.(stable ? objects : this.lastObjects ?? []);
    }
    if (stable) this.lastObjects = objects;
  }

  /**
   * A small JPEG of the current camera frame (base64, not mirrored), so Claude can see
   * what the detector can't: what you're holding, text, colours, faces. Null when the
   * camera isn't showing a picture.
   */
  snapshot(maxWidth = 640, quality = 0.72) {
    if (!this.on || this.video.readyState < 2 || !this.video.videoWidth) return null;
    const vw = this.video.videoWidth;
    const vh = this.video.videoHeight;
    const scale = Math.min(1, maxWidth / vw);
    const c = (this.snapCanvas ??= document.createElement("canvas"));
    c.width = Math.round(vw * scale);
    c.height = Math.round(vh * scale);
    c.getContext("2d").drawImage(this.video, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", quality).split(",")[1] || null;
  }

  // ---- drawing --------------------------------------------------------------------

  /** Match new boxes to the ones on screen (same label, nearest centre) so they glide. */
  track(objects) {
    const free = new Set(this.tracks);
    for (const o of objects) {
      let best = null;
      let bestD = 0.18;
      for (const t of free) {
        if (t.label !== o.label) continue;
        const d = Math.hypot(t.tx - o.x, t.ty - o.y);
        if (d < bestD) {
          bestD = d;
          best = t;
        }
      }
      if (best) {
        free.delete(best);
        Object.assign(best, { tx: o.x, ty: o.y, tw: o.w, th: o.h, score: o.score, seen: performance.now(), dead: false });
      } else {
        this.tracks.push({ label: o.label, score: o.score, x: o.x, y: o.y, w: o.w * 0.85, h: o.h * 0.85, tx: o.x, ty: o.y, tw: o.w, th: o.h, a: 0, seen: performance.now(), dead: false });
      }
    }
    for (const t of free) t.dead = true;
  }

  draw() {
    if (!this.on) return;
    this.raf = requestAnimationFrame(() => this.draw());
    const c = this.overlay;
    const dpr = Math.min(2, devicePixelRatio || 1);
    const W = Math.round(c.clientWidth * dpr);
    const H = Math.round(c.clientHeight * dpr);
    if (!W || !H) return;
    if (c.width !== W || c.height !== H) {
      c.width = W;
      c.height = H;
    }
    const ctx = this.ctx;
    ctx.clearRect(0, 0, W, H);
    const k = 0.28;
    const accent = getComputedStyle(document.body).getPropertyValue("--see").trim() || "120 255 190";
    ctx.font = `600 ${10.5 * dpr}px -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif`;
    ctx.textBaseline = "middle";

    this.tracks = this.tracks.filter((t) => t.a > 0.01 || !t.dead);
    for (const t of this.tracks) {
      t.x += (t.tx - t.x) * k;
      t.y += (t.ty - t.y) * k;
      t.w += (t.tw - t.w) * k;
      t.h += (t.th - t.h) * k;
      t.a += ((t.dead ? 0 : 1) - t.a) * (t.dead ? 0.18 : 0.25);

      const x = (t.x - t.w / 2) * W;
      const y = (t.y - t.h / 2) * H;
      const w = t.w * W;
      const h = t.h * H;
      const r = Math.min(10 * dpr, w / 4, h / 4);

      ctx.globalAlpha = t.a;
      ctx.lineWidth = 1.5 * dpr;
      ctx.strokeStyle = `rgb(${accent} / 0.95)`;
      ctx.fillStyle = `rgb(${accent} / 0.08)`;
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
      ctx.fill();
      ctx.stroke();

      // Corner brackets for a HUD feel.
      ctx.lineWidth = 2.5 * dpr;
      const L = Math.min(14 * dpr, w / 3, h / 3);
      ctx.beginPath();
      ctx.moveTo(x, y + L); ctx.lineTo(x, y); ctx.lineTo(x + L, y);
      ctx.moveTo(x + w - L, y + h); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w, y + h - L);
      ctx.stroke();

      // Label pill.
      const text = `${t.label}  ${Math.round(t.score * 100)}%`;
      const pad = 6 * dpr;
      const tw = ctx.measureText(text).width + pad * 2;
      const th = 18 * dpr;
      const lx = Math.min(Math.max(0, x), W - tw);
      const ly = y - th - 4 * dpr >= 0 ? y - th - 4 * dpr : y + 4 * dpr;
      ctx.fillStyle = `rgb(${accent} / 0.92)`;
      ctx.beginPath();
      ctx.roundRect(lx, ly, tw, th, th / 2);
      ctx.fill();
      ctx.fillStyle = "rgb(6 20 14)";
      ctx.fillText(text, lx + pad, ly + th / 2 + 0.5 * dpr);
    }
    ctx.globalAlpha = 1;
  }
}

function sceneKey(objects) {
  const counts = {};
  for (const o of objects) counts[o.label] = (counts[o.label] || 0) + 1;
  return Object.keys(counts).sort().map((k) => `${k}:${counts[k]}`).join(",");
}
