/**
 * What the camera sees, as reported by the browser's on-device object detector.
 * Only labels and boxes arrive here; video frames never leave the browser.
 */

export interface Detection {
  label: string;
  score: number;
  /** Box centre and size as fractions of the frame (0..1), already mirrored like a selfie view. */
  x: number;
  y: number;
  w: number;
  h: number;
}

// The COCO classes the detection models know. Anything else is dropped, so arbitrary
// text from the browser can never end up in Claude's instructions.
const KNOWN_LABELS = new Set(
  ("person bicycle car motorcycle airplane bus train truck boat traffic-light fire-hydrant stop-sign " +
    "parking-meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella handbag tie " +
    "suitcase frisbee skis snowboard sports-ball kite baseball-bat baseball-glove skateboard surfboard tennis-racket " +
    "bottle wine-glass cup fork knife spoon bowl banana apple sandwich orange broccoli carrot hot-dog pizza donut cake " +
    "chair couch potted-plant bed dining-table toilet tv laptop mouse remote keyboard cell-phone microwave oven toaster " +
    "sink refrigerator book clock vase scissors teddy-bear hair-drier toothbrush " +
    // extra labels in DETR's config
    "street-sign hat shoe eye-glasses plate mirror window desk door blender")
    .split(" ")
    .map((l) => l.replace(/-/g, " ")),
);

const MAX_OBJECTS = 25;
const STALE_MS = 8000; // camera reports this old are treated as no longer current (CPU-only detection can take ~2–3 s a frame)
const RECENT_MS = 30_000; // how long an object that left the frame is still mentioned

export class VisionState {
  enabled = false;
  private current: Detection[] = [];
  private updatedAt = 0;
  /** label -> last time it was in view */
  private lastSeen = new Map<string, number>();
  /** Latest camera still (base64 JPEG), kept in memory only, for the next reply. */
  private still: string | null = null;
  private stillAt = 0;

  setEnabled(on: boolean): void {
    this.enabled = on;
    if (!on) {
      this.current = [];
      this.lastSeen.clear();
      this.still = null;
    }
  }

  update(raw: unknown): void {
    if (!this.enabled || !Array.isArray(raw)) return;
    const now = Date.now();
    this.current = raw.slice(0, MAX_OBJECTS).flatMap((d) => {
      const det = sanitize(d);
      return det ? [det] : [];
    });
    this.updatedAt = now;
    for (const d of this.current) this.lastSeen.set(d.label, now);
    for (const [label, t] of this.lastSeen) if (now - t > RECENT_MS) this.lastSeen.delete(label);
  }

  setStill(raw: unknown): void {
    // Only a plausible JPEG of reasonable size (a 640 px still is ~30–120 KB).
    if (typeof raw === "string" && raw.startsWith("/9j/") && raw.length < 1_500_000 && /^[A-Za-z0-9+/=]+$/.test(raw)) {
      this.still = raw;
      this.stillAt = Date.now();
    } else {
      this.still = null;
    }
  }

  /** A still from the last few seconds, if the camera is on. */
  freshStill(): string | null {
    return this.enabled && this.still && Date.now() - this.stillAt < 6000 ? this.still : null;
  }

  /** A short note for Claude's system prompt describing the scene right now. */
  describe(): string {
    if (!this.enabled) {
      return "Camera: off. You can't see the person right now. If they ask what you see, tell them to turn on the camera with the camera button.";
    }
    const now = Date.now();
    const stillNote = this.freshStill()
      ? "\nA live still from their webcam is attached to their latest message. That's what you see right now: the person in it is who you're talking with, and anything held up is what they're showing you. Trust the image over the detector list. Describe what you see naturally and briefly; you can read text, see colours and recognise objects in it. (The image is the camera's view, so their left and right are swapped.)"
      : "";
    if (!this.updatedAt || now - this.updatedAt > STALE_MS) {
      if (stillNote) return `Camera: on.${stillNote}`;
      return "Camera: on, but no recent detections yet (the vision model may still be loading).";
    }

    const groups = new Map<string, Detection[]>();
    for (const d of this.current) groups.set(d.label, [...(groups.get(d.label) ?? []), d]);
    const inView = [...groups.entries()]
      .sort((a, b) => Math.max(...b[1].map((d) => d.w * d.h)) - Math.max(...a[1].map((d) => d.w * d.h)))
      .map(([label, ds]) => {
        const name = ds.length > 1 ? `${ds.length} × ${label}` : label;
        return `${name} (${ds.map(place).join("; ")})`;
      });

    const gone = [...this.lastSeen.entries()]
      .filter(([label]) => !groups.has(label))
      .map(([label, t]) => `${label} (${Math.max(1, Math.round((now - t) / 1000))}s ago)`);

    const lines = [
      stillNote
        ? "Camera: on. An object detector also watches the webcam continuously; it only knows about 80 everyday object types and can be wrong, so use it for what's come and gone, and the attached still for what's there now."
        : "Camera: on. An object detector watches the person's webcam and reports what it finds. It only knows about 80 everyday object types (people, phones, cups, bottles, laptops, books, chairs and so on) and gives no detail like colours, faces, text or expressions. Labels can be wrong.",
      `In view now: ${inView.length ? inView.join(", ") : "nothing recognised"}.`,
    ];
    if (groups.has("person")) lines.push("A person in view, especially close up and central, is most likely the person you're talking with.");
    if (gone.length) lines.push(`Recently left the view: ${gone.join(", ")}.`);
    if (stillNote) lines.splice(1, 0, stillNote.trim());
    lines.push(
      "Use this naturally when it's relevant, for example if they ask what you see, hold something up, or ask where something is. Don't narrate the scene unprompted, and don't claim to see details the detector can't provide.",
    );
    return lines.join("\n");
  }
}

function sanitize(d: any): Detection | null {
  if (!d || typeof d.label !== "string") return null;
  const label = d.label.toLowerCase().trim();
  if (!KNOWN_LABELS.has(label)) return null;
  const nums = [d.score, d.x, d.y, d.w, d.h].map(Number);
  if (!label || nums.some((n) => !Number.isFinite(n))) return null;
  const [score, x, y, w, h] = nums.map((n) => Math.min(1, Math.max(0, n)));
  return { label, score, x, y, w, h };
}

/** Plain-language position and size, from the person's own point of view. */
function place(d: Detection): string {
  const horiz = d.x < 0.36 ? "on your left" : d.x > 0.64 ? "on your right" : "center";
  const vert = d.y < 0.33 ? "top" : d.y > 0.67 ? "bottom" : "";
  const area = d.w * d.h;
  const size = area > 0.35 ? "close up" : area < 0.03 ? "small / far" : "";
  return [vert && horiz === "center" ? vert : [vert, horiz].filter(Boolean).join(" "), size]
    .filter(Boolean)
    .join(", ") + `, ${Math.round(d.score * 100)}%`;
}
