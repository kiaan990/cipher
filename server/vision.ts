/**
 * What the camera sees. Two sources, used together:
 *   - the browser's on-device object detector: labels and boxes, continuously. Cheap and
 *     always there, but it knows only ~80 kinds of object and no detail.
 *   - camera stills (when the user allows them): a JPEG held in memory for the next reply
 *     only, so Claude can actually look. Never written to disk or kept in the conversation.
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
  /** The view when they started speaking, kept only when it differs from the latest still. */
  private earlier: string | null = null;
  private earlierAt = 0;

  setEnabled(on: boolean): void {
    this.enabled = on;
    if (!on) {
      this.current = [];
      this.lastSeen.clear();
      this.still = this.earlier = null;
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

  /**
   * The newest still, and optionally the view from when they began speaking (sent by the
   * browser only when the two differ, e.g. they held something up and put it down again).
   */
  setStill(raw: unknown, earlier?: unknown, earlierAgoMs?: unknown): void {
    if (!isJpeg(raw)) {
      this.still = this.earlier = null;
      return;
    }
    const now = Date.now();
    this.still = raw;
    this.stillAt = now;
    const ago = Number(earlierAgoMs);
    if (isJpeg(earlier) && Number.isFinite(ago) && ago >= 0 && ago < 15_000) {
      this.earlier = earlier;
      this.earlierAt = now - ago;
    } else {
      this.earlier = null;
    }
  }

  /** What to show Claude with the next reply: a still from the last few seconds, if the camera is on. */
  freshStill(): CameraView | null {
    const now = Date.now();
    if (!this.enabled || !this.still || now - this.stillAt >= STILL_FRESH_MS) return null;
    const view: CameraView = { jpeg: this.still, ageMs: now - this.stillAt };
    if (this.earlier && now - this.earlierAt < EARLIER_FRESH_MS) view.earlier = { jpeg: this.earlier, ageMs: now - this.earlierAt };
    return view;
  }

  /** A short note for Claude's system prompt describing the scene right now. */
  describe(): string {
    if (!this.enabled) {
      return "Camera: off. You can't see the person right now. If they ask what you see, tell them to turn on the camera with the camera button.";
    }
    const now = Date.now();
    const still = Boolean(this.freshStill());
    const lines: string[] = [];
    if (still) {
      lines.push(
        "Camera: on, and you can see. A live picture from their webcam is attached to their latest message: that is your view right now. The person in it is who you're talking with, and anything held up to the camera is being shown to you. You can read text and see colours, faces and expressions in it. Go by the picture; if you can't make something out, say so and ask them to hold it closer or steadier rather than guessing.",
        "The picture is not mirrored: something on the right of the picture is on their left.",
      );
    }
    const detecting = this.updatedAt && now - this.updatedAt <= STALE_MS;
    if (!detecting) {
      return still ? lines.join("\n") : "Camera: on, but nothing has come through yet (the vision model may still be loading). Say so if they ask what you see.";
    }

    const groups = new Map<string, Detection[]>();
    for (const d of this.current) groups.set(d.label, [...(groups.get(d.label) ?? []), d]);
    const inView = [...groups.entries()]
      .sort((a, b) => Math.max(...b[1].map((d) => d.w * d.h)) - Math.max(...a[1].map((d) => d.w * d.h)))
      .map(([label, ds]) => `${ds.length > 1 ? `${ds.length} × ${label}` : label} (${ds.map(place).join("; ")})`);
    const gone = [...this.lastSeen.entries()]
      .filter(([label]) => !groups.has(label))
      .map(([label, t]) => `${label} (${Math.max(1, Math.round((now - t) / 1000))}s ago)`);

    lines.push(
      still
        ? "An object detector also watches continuously. It knows only about 80 everyday object types and its labels can be wrong: use it for what has come and gone, and the picture for what is there."
        : "Camera: on, but you only get an object detector's report, no picture. It knows about 80 everyday object types (people, phones, cups, bottles, laptops, books, chairs and so on), its labels can be wrong, and it gives no colours, faces, text or expressions: don't claim to see those.",
      `Detector, in view now: ${inView.length ? inView.join(", ") : "nothing it recognises"}. (Positions are from the person's side: "their left" is their own left.)`,
    );
    if (gone.length) lines.push(`Detector, recently left the view: ${gone.join(", ")}.`);
    lines.push("Use what you see when it's relevant (they ask what you see, hold something up, ask where something is). Don't narrate the scene unprompted.");
    return lines.join("\n");
  }
}

/** A still for one reply, with how old it is, and the earlier view if it changed while they spoke. */
export interface CameraView {
  jpeg: string;
  ageMs: number;
  earlier?: { jpeg: string; ageMs: number };
}

const STILL_FRESH_MS = 6000;
const EARLIER_FRESH_MS = 20_000;

/** Only a plausible JPEG of reasonable size (a 960 px still is roughly 60–200 KB). */
function isJpeg(raw: unknown): raw is string {
  return typeof raw === "string" && raw.startsWith("/9j/") && raw.length < 1_500_000 && /^[A-Za-z0-9+/=]+$/.test(raw);
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
  const horiz = d.x < 0.36 ? "on their left" : d.x > 0.64 ? "on their right" : "center";
  const vert = d.y < 0.33 ? "top" : d.y > 0.67 ? "bottom" : "";
  const area = d.w * d.h;
  const size = area > 0.35 ? "close up" : area < 0.03 ? "small / far" : "";
  return [vert && horiz === "center" ? vert : [vert, horiz].filter(Boolean).join(" "), size]
    .filter(Boolean)
    .join(", ") + `, ${Math.round(d.score * 100)}%`;
}
