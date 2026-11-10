// The glowing orb: a canvas-2D renderer that eases between per-state looks
// and reacts to a live audio level. Runs at display refresh rate.

const STATES = {
  //            core colour       edge colour      glow             energy speed
  idle:        { a: [120, 132, 190], b: [58, 66, 122],  glow: [92, 108, 190],  energy: 0.12, speed: 0.22 },
  listening:   { a: [120, 215, 255], b: [52, 112, 245], glow: [70, 170, 255],  energy: 0.45, speed: 0.55 },
  thinking:    { a: [196, 150, 255], b: [96, 70, 220],  glow: [150, 110, 255], energy: 0.3,  speed: 0.4 },
  speaking:    { a: [255, 196, 150], b: [226, 104, 92], glow: [255, 140, 110], energy: 0.5,  speed: 0.65 },
  interrupted: { a: [255, 245, 245], b: [255, 110, 120], glow: [255, 170, 170], energy: 0.9,  speed: 1.1 },
};

const lerp = (a, b, t) => a + (b - a) * t;
const lerp3 = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.state = "idle";
    this.look = structuredClone(STATES.idle);
    this.thinkW = 0;
    this.level = 0;
    this.prevLevel = 0;
    this.flashAmt = 0;
    this.dim = 0;
    this.levelFn = () => 0;
    this.ripples = [];
    this.lastRipple = 0;
    this.particles = Array.from({ length: 90 }, () => ({
      angle: Math.random() * Math.PI * 2,
      dist: 1.15 + Math.random() * 1.2,
      speed: (0.02 + Math.random() * 0.06) * (Math.random() < 0.5 ? -1 : 1),
      size: 0.5 + Math.random() * 1.4,
      phase: Math.random() * Math.PI * 2,
      drift: Math.random() * Math.PI * 2,
    }));
    this.resize();
    addEventListener("resize", () => this.resize());
    this.last = performance.now();
    requestAnimationFrame((t) => this.frame(t));
  }

  setState(state) {
    if (STATES[state]) this.state = state;
  }

  setSpectrumSource() {}
  setQuality() {}
  setWordsEnabled() {}
  setMood() {}
  word() {}

  setLevelSource(fn) {
    this.levelFn = fn;
  }

  setDimmed(dimmed) {
    this.dimTarget = dimmed ? 1 : 0;
  }

  flash() {
    this.flashAmt = 1;
    this.spawnRipple(1);
  }

  resize() {
    this.dpr = Math.min(devicePixelRatio || 1, 2);
    this.w = innerWidth;
    this.h = innerHeight;
    this.canvas.width = Math.round(this.w * this.dpr);
    this.canvas.height = Math.round(this.h * this.dpr);
  }

  spawnRipple(strength) {
    this.ripples.push({ age: 0, strength: Math.min(1, strength) });
    if (this.ripples.length > 8) this.ripples.shift();
  }

  frame(now) {
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    const t = now / 1000;
    this.update(dt, t);
    this.draw(t);
    requestAnimationFrame((n) => this.frame(n));
  }

  update(dt, t) {
    const target = STATES[this.state];
    const k = 1 - Math.exp(-dt * 5);
    const L = this.look;
    L.a = lerp3(L.a, target.a, k);
    L.b = lerp3(L.b, target.b, k);
    L.glow = lerp3(L.glow, target.glow, k);
    L.energy = lerp(L.energy, target.energy, k);
    L.speed = lerp(L.speed, target.speed, k);
    this.thinkW = lerp(this.thinkW, this.state === "thinking" ? 1 : 0, 1 - Math.exp(-dt * 3));
    this.dim = lerp(this.dim, this.dimTarget || 0, k);

    // Audio level: fast attack, slower release, scaled so normal speech fills the range.
    const raw = Math.min(1, (this.levelFn() || 0) * 7);
    const rate = raw > this.level ? 18 : 5;
    this.prevLevel = this.level;
    this.level = lerp(this.level, raw, 1 - Math.exp(-dt * rate));

    // Ripples on syllable onsets.
    if ((this.state === "listening" || this.state === "speaking") && this.level > 0.18) {
      if (this.level - this.prevLevel > 0.02 && t - this.lastRipple > 0.22) {
        this.spawnRipple(this.level);
        this.lastRipple = t;
      }
    }
    for (const r of this.ripples) r.age += dt / 1.6;
    this.ripples = this.ripples.filter((r) => r.age < 1);

    this.flashAmt = Math.max(0, this.flashAmt - dt * 3.2);
    this.phase = (this.phase || 0) + dt * L.speed * (1 + this.level * 1.5);
  }

  draw(t) {
    const { ctx, w, h, dpr, look: L, level } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h * 0.44;
    const breath = Math.sin(t * 1.25) * 0.5 + 0.5;
    const R = Math.min(w, h) * 0.17 * (1 + 0.035 * breath + 0.14 * level);
    const dimK = 1 - this.dim * 0.55;

    // Outer glow
    const glowA = (0.22 + 0.12 * breath * (1 - L.energy) + 0.35 * level) * dimK;
    let g = ctx.createRadialGradient(cx, cy, R * 0.3, cx, cy, R * 3.2);
    g.addColorStop(0, rgba(L.glow, glowA));
    g.addColorStop(0.45, rgba(L.glow, glowA * 0.35));
    g.addColorStop(1, rgba(L.glow, 0));
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // Ripples
    ctx.lineWidth = 1.5;
    for (const r of this.ripples) {
      const rr = R * (1.02 + r.age * 1.3);
      ctx.strokeStyle = rgba(L.a, (1 - r.age) * 0.45 * r.strength * dimK);
      ctx.beginPath();
      ctx.arc(cx, cy, rr, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Particles
    ctx.globalCompositeOperation = "lighter";
    for (const p of this.particles) {
      p.angle += p.speed * (0.016 + level * 0.05) * (1 + L.energy);
      const d = R * (p.dist + Math.sin(t * 0.5 + p.drift) * 0.06 + level * 0.25);
      const x = cx + Math.cos(p.angle) * d;
      const y = cy + Math.sin(p.angle) * d * 0.92;
      const tw = 0.35 + 0.65 * (Math.sin(t * 1.7 + p.phase) * 0.5 + 0.5);
      ctx.fillStyle = rgba(L.a, (0.12 + 0.4 * level + 0.15 * L.energy) * tw * dimK);
      ctx.beginPath();
      ctx.arc(x, y, p.size * (1 + level * 0.8), 0, Math.PI * 2);
      ctx.fill();
    }

    // Body: three soft, deforming layers blended additively
    const amp = 0.018 + L.energy * 0.03 + level * 0.11;
    const ph = this.phase;
    for (let layer = 0; layer < 3; layer++) {
      const off = layer * 2.1;
      const scale = 1 - layer * 0.07;
      ctx.beginPath();
      const N = 96;
      for (let i = 0; i <= N; i++) {
        const th = (i / N) * Math.PI * 2;
        const wob =
          Math.sin(3 * th + ph * 2.0 + off) * 0.5 +
          Math.sin(5 * th - ph * 2.6 + off * 1.7) * 0.3 +
          Math.sin(2 * th + ph * 1.3 - off) * 0.2;
        const rr = R * scale * (1 + amp * wob);
        const x = cx + Math.cos(th) * rr;
        const y = cy + Math.sin(th) * rr;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.closePath();
      const lg = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.3, R * 0.05, cx, cy, R * 1.1);
      const mix = lerp3(L.a, L.b, layer / 2);
      lg.addColorStop(0, rgba(lerp3(mix, [255, 255, 255], 0.15), (0.26 + level * 0.12) * dimK));
      lg.addColorStop(0.6, rgba(mix, 0.2 * dimK));
      lg.addColorStop(1, rgba(L.b, 0.07 * dimK));
      ctx.fillStyle = lg;
      ctx.fill();
    }

    // Thinking: slow swirling arcs inside the orb
    if (this.thinkW > 0.01) {
      ctx.lineCap = "round";
      for (let i = 0; i < 5; i++) {
        const rot = t * (0.8 + i * 0.25) * (i % 2 ? -1 : 1) + i * 1.3;
        const rad = R * (0.35 + i * 0.12);
        ctx.strokeStyle = rgba(lerp3(L.a, [255, 255, 255], 0.4), 0.35 * this.thinkW * dimK);
        ctx.lineWidth = R * 0.035;
        ctx.beginPath();
        ctx.arc(cx, cy, rad, rot, rot + 1.1 + Math.sin(t * 1.5 + i) * 0.5);
        ctx.stroke();
      }
    }

    // Specular core
    g = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, 0, cx - R * 0.3, cy - R * 0.35, R * 0.8);
    g.addColorStop(0, `rgba(255,255,255,${(0.14 + level * 0.14) * dimK})`);
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.fill();

    // Interruption flash
    if (this.flashAmt > 0) {
      g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 2.4);
      g.addColorStop(0, `rgba(255,255,255,${0.75 * this.flashAmt})`);
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    ctx.globalCompositeOperation = "source-over";
  }
}
