// Runs object detection off the main thread so the orb stays smooth.
// Uses transformers.js (https://github.com/huggingface/transformers.js), served
// from node_modules. Models download from Hugging Face once, then the browser caches them.
import { pipeline, env } from "/vendor/transformers/transformers.min.js";

env.allowLocalModels = false;
// Serve the ONNX runtime's WebAssembly files ourselves instead of from a CDN.
env.backends.onnx.wasm.wasmPaths = "/vendor/transformers/";
// Multi-threaded WASM can hang when started from inside a worker; one thread is reliable.
env.backends.onnx.wasm.numThreads = 1;

const INPUT_SIZE = { "Xenova/yolos-tiny": 320, "Xenova/detr-resnet-50": 384 };

let detector = null;
let loading = null;
let modelId = "";
let device = "cpu";

// Precision used on the GPU. DETR in full precision would be a 160 MB download, so it uses fp16.
const GPU_DTYPE = { "Xenova/yolos-tiny": "fp32", "Xenova/detr-resnet-50": "fp16" };

async function gpuAdapter() {
  try {
    return (await navigator.gpu?.requestAdapter()) ?? null;
  } catch {
    return null;
  }
}

async function load(model, cpuOnly = false) {
  if (detector && modelId === model) return detector;
  if (loading && modelId === model) return loading;
  modelId = model;
  detector = null;
  const files = new Map(); // file -> { loaded, total }
  const progress_callback = (p) => {
    if (p.status !== "progress" || !p.total) return;
    files.set(p.file, { loaded: p.loaded, total: p.total });
    let loaded = 0;
    let total = 0;
    for (const f of files.values()) {
      loaded += f.loaded;
      total += f.total;
    }
    self.postMessage({ type: "progress", progress: total ? loaded / total : 0, loaded, total });
  };
  // Prefer the GPU (WebGPU) — tens of milliseconds per frame. Fall back to the CPU (WASM).
  loading = (async () => {
    const adapter = await gpuAdapter();
    const dtype = GPU_DTYPE[model] ?? "fp32";
    if (!cpuOnly && adapter && (dtype !== "fp16" || adapter.features.has("shader-f16"))) {
      try {
        const p = await pipeline("object-detection", model, { device: "webgpu", dtype, progress_callback });
        device = "gpu";
        return p;
      } catch (err) {
        console.warn("WebGPU unavailable for vision, using CPU:", err);
      }
    }
    device = "cpu";
    return pipeline("object-detection", model, { device: "wasm", dtype: "q8", progress_callback });
  })();
  try {
    detector = await loading;
    // These models upscale every frame to 512–800 px by default. A webcam view doesn't
    // need that, and a smaller input makes detection several times faster.
    const ip = detector.processor?.image_processor;
    if (ip?.size) ip.size = { shortest_edge: INPUT_SIZE[model] ?? 384, longest_edge: 640 };
    if (modelId === model) self.postMessage({ type: "ready", model, device, size: ip?.size });
    return detector;
  } finally {
    loading = null;
  }
}

let canvas = null;
let ctx = null;

self.onmessage = async (e) => {
  const msg = e.data;
  try {
    if (msg.type === "load") {
      await load(msg.model, Boolean(msg.cpuOnly));
    } else if (msg.type === "frame") {
      const { bitmap, threshold, model } = msg;
      const det = await load(model);
      if (!canvas || canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        ctx = canvas.getContext("2d", { willReadFrequently: true });
      }
      ctx.drawImage(bitmap, 0, 0);
      bitmap.close();
      const t0 = performance.now();
      const out = await det(canvas, { threshold, percentage: true });
      self.postMessage({
        type: "result",
        id: msg.id,
        ms: Math.round(performance.now() - t0),
        objects: dedupe(out).map((o) => ({ label: o.label, score: o.score, box: o.box })),
      });
    }
  } catch (err) {
    msg.bitmap?.close?.();
    self.postMessage({ type: "error", id: msg.id, message: String(err?.message || err) });
  }
};

/** Drop overlapping boxes of the same label, keeping the most confident (non-max suppression). */
function dedupe(objects) {
  const kept = [];
  for (const o of [...objects].sort((a, b) => b.score - a.score)) {
    if (!kept.some((k) => k.label === o.label && iou(k.box, o.box) > 0.5)) kept.push(o);
  }
  return kept;
}

function iou(a, b) {
  const w = Math.max(0, Math.min(a.xmax, b.xmax) - Math.max(a.xmin, b.xmin));
  const h = Math.max(0, Math.min(a.ymax, b.ymax) - Math.max(a.ymin, b.ymin));
  const inter = w * h;
  const union = (a.xmax - a.xmin) * (a.ymax - a.ymin) + (b.xmax - b.xmin) * (b.ymax - b.ymin) - inter;
  return union > 0 ? inter / union : 0;
}
