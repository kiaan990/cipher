// The 3D orb: a WebGL scene (Three.js) that reacts to
//  - the conversation state (idle / listening / thinking / speaking / interrupted),
//  - Claude's mood for the current reply (colour and motion),
//  - every word spoken by you or Claude (pulses + floating words),
//  - live audio (level and frequency spectrum),
//  - the mouse (drag to spin, hover to bulge, tap to start / interrupt).

import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const BANDS = 48; // spectrum bands (mirrored around the ring)
const MAX_PULSES = 8;

// ---- looks --------------------------------------------------------------------
// Colours are [core-bright, deep] in sRGB 0-255.
const MOODS = {
  calm:       { a: [110, 175, 255], b: [40, 70, 170],   speed: 0.5,  freq: 1.3, amp: 0.8, beat: "breathe" },
  happy:      { a: [255, 214, 120], b: [255, 128, 60],  speed: 1.05, freq: 1.7, amp: 1.1, beat: "bounce" },
  excited:    { a: [255, 120, 210], b: [255, 70, 90],   speed: 1.6,  freq: 2.5, amp: 1.4, beat: "bounce" },
  curious:    { a: [110, 255, 220], b: [30, 160, 210],  speed: 0.9,  freq: 2.0, amp: 1.0, beat: "tilt" },
  thoughtful: { a: [175, 150, 255], b: [80, 60, 200],   speed: 0.4,  freq: 1.1, amp: 0.7, beat: "breathe" },
  empathetic: { a: [255, 165, 180], b: [200, 80, 140],  speed: 0.55, freq: 1.1, amp: 0.9, beat: "heart" },
  serious:    { a: [205, 220, 240], b: [70, 95, 135],   speed: 0.35, freq: 3.0, amp: 0.5, beat: "none" },
  playful:    { a: [170, 255, 120], b: [240, 110, 220], speed: 1.3,  freq: 1.5, amp: 1.3, beat: "bounce" },
  surprised:  { a: [255, 250, 160], b: [255, 160, 50],  speed: 1.4,  freq: 2.2, amp: 1.3, beat: "pop" },
};

const STATE = {
  //           amp   scan  bloom spread pull  ring  sweep wire  pts
  idle:        { amp: 0.045, scan: 0.35, bloom: 0.85, spread: 0.2, pull: 0,    ring: 0.12, sweep: 0, wire: 0.55, pts: 0.6 },
  listening:   { amp: 0.06,  scan: 0.8,  bloom: 1.15, spread: 0.45, pull: 1,   ring: 0.35, sweep: 0, wire: 0.9,  pts: 1.0 },
  thinking:    { amp: 0.05,  scan: 1.0,  bloom: 1.1,  spread: 0.15, pull: 0.4, ring: 1.6,  sweep: 1, wire: 1.0,  pts: 0.8 },
  speaking:    { amp: 0.085, scan: 0.7,  bloom: 1.35, spread: 0.95, pull: -0.3, ring: 0.5, sweep: 0, wire: 0.8,  pts: 1.1 },
  interrupted: { amp: 0.16,  scan: 1.2,  bloom: 1.9,  spread: 1.2, pull: -0.6, ring: 2.5,  sweep: 0, wire: 1.4,  pts: 1.4 },
};
const LISTEN_COLORS = { a: [90, 220, 255], b: [30, 100, 255] };
const THINK_COLORS = { a: [190, 150, 255], b: [100, 60, 230] };
const CUT_COLORS = { a: [255, 90, 110], b: [255, 40, 60] };
const SEE_COLORS = { a: [120, 255, 190], b: [30, 200, 140] };

const srgb = (c) => new THREE.Color().setRGB(c[0] / 255, c[1] / 255, c[2] / 255, THREE.SRGBColorSpace);
const damp = (cur, target, rate, dt) => cur + (target - cur) * (1 - Math.exp(-rate * dt));

// ---- shaders ------------------------------------------------------------------
const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const DISPLACE = /* glsl */ `
uniform float uTime, uPhase, uAmp, uFreq, uLevel, uBass, uSpike, uHoverAmt, uBeat;
uniform vec3 uHover;
uniform vec4 uPulses[${MAX_PULSES}];
${NOISE}
float displace(vec3 n){
  float d = snoise(n*uFreq + vec3(0.0, uPhase, uPhase*0.6)) * uAmp;
  d += snoise(n*uFreq*2.3 - vec3(uPhase*1.3)) * uAmp * 0.35;
  d *= 1.0 + uLevel*1.5;
  d += uBass*0.10 + uBeat;
  d += snoise(n*9.0 + uTime*7.0) * uSpike * 0.22;
  for (int i = 0; i < ${MAX_PULSES}; i++) {
    float age = uPulses[i].w;
    if (age < 1.0) {
      float dist = acos(clamp(dot(n, uPulses[i].xyz), -1.0, 1.0));
      float w = exp(-pow((dist - age*3.3) * 4.5, 2.0));
      d += w * (1.0 - age) * 0.11;
    }
  }
  float hd = acos(clamp(dot(n, uHover), -1.0, 1.0));
  d += exp(-hd*hd*9.0) * uHoverAmt * 0.13;
  return d;
}`;

const SURFACE_VERT = /* glsl */ `
${DISPLACE}
uniform float uRadius;
varying vec3 vN; varying vec3 vView; varying float vD; varying vec3 vObj;
void main(){
  vec3 n = normalize(position);
  float d = displace(n);
  vD = d; vObj = n;
  vec4 mv = modelViewMatrix * vec4(n * (uRadius + d), 1.0);
  vView = -mv.xyz;
  vN = normalize(normalMatrix * n);
  gl_Position = projectionMatrix * mv;
}`;

const CORE_FRAG = /* glsl */ `
uniform vec3 uColA, uColB; uniform float uScan, uTime, uGlow, uDim, uFlash;
varying vec3 vN; varying vec3 vView; varying float vD; varying vec3 vObj;
void main(){
  vec3 V = normalize(vView);
  float fr = pow(1.0 - max(dot(normalize(vN), V), 0.0), 2.4);
  vec3 col = mix(uColB * 0.07, uColA * 0.75, fr);
  col += uColA * smoothstep(0.0, 0.25, vD) * 0.35 * uGlow;
  float lat = vObj.y;
  float lines = smoothstep(0.93, 1.0, sin(lat*64.0 - uTime*2.5)*0.5 + 0.5);
  float sweep = exp(-pow((lat - sin(uTime*0.8))*13.0, 2.0));
  float lon = atan(vObj.z, vObj.x);
  float meridians = smoothstep(0.975, 1.0, abs(sin(lon*12.0)));
  col += uColA * uScan * (lines*0.12 + sweep*0.22 + meridians*0.1*fr);
  col = mix(col, vec3(1.0), uFlash);
  gl_FragColor = vec4(col * uDim, 1.0);
}`;

const WIRE_FRAG = /* glsl */ `
uniform vec3 uColA; uniform float uWire, uDim, uFlash;
varying vec3 vN; varying vec3 vView; varying float vD; varying vec3 vObj;
void main(){
  float fr = pow(1.0 - max(dot(normalize(vN), normalize(vView)), 0.0), 1.5);
  vec3 col = mix(uColA, vec3(1.0), uFlash*0.6) * (0.25 + smoothstep(0.0, 0.25, vD)*0.6);
  gl_FragColor = vec4(col, (0.04 + fr*0.4) * uWire * uDim);
}`;

const POINTS_VERT = /* glsl */ `
${NOISE}
attribute float aBand; attribute float aRand;
uniform sampler2D uSpec; uniform float uTime, uPhase, uSpread, uPull, uLevel, uSize, uKick;
varying float vA; varying float vS;
void main(){
  vec3 n = normalize(position);
  float s = texture2D(uSpec, vec2(aBand, 0.5)).r;
  float r = 1.5 + aRand*0.45 + s*uSpread + snoise(n*1.6 + uPhase*0.4)*0.12
            - uPull*0.3*(0.4 + aRand) + uKick*(0.6 + aRand*1.2);
  vec4 mv = modelViewMatrix * vec4(n * r, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * (0.6 + aRand*0.9 + s*1.6) * (6.0 / -mv.z);
  float tw = 0.5 + 0.5*sin(uTime*(0.8 + aRand*2.2) + aRand*40.0);
  vA = (0.2 + 0.8*tw) * (0.22 + s*1.0 + uLevel*0.25);
  vS = s;
}`;

const POINTS_FRAG = /* glsl */ `
uniform vec3 uColA, uColB; uniform float uDim, uOpacity;
varying float vA; varying float vS;
void main(){
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  float a = smoothstep(0.5, 0.0, d);
  gl_FragColor = vec4(mix(uColB, uColA, clamp(vS + 0.35, 0.0, 1.0)), a * vA * uOpacity * uDim);
}`;

const RING_VERT = /* glsl */ `
varying vec2 vP;
void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

const RING_FRAG = /* glsl */ `
uniform vec3 uCol; uniform float uDash, uFill, uRot, uOpacity, uSweep, uSweepRot, uDim;
varying vec2 vP;
void main(){
  float a = atan(vP.y, vP.x) / 6.28318 + 0.5;
  float seg = step(uFill, fract(a*uDash + uRot));
  float sweep = pow(fract(a - uSweepRot), 10.0) * uSweep;
  float alpha = (seg*uOpacity + sweep) * uDim;
  gl_FragColor = vec4(uCol * (1.0 + sweep*2.0), alpha);
}`;

const GLITCH = {
  uniforms: { tDiffuse: { value: null }, uAmt: { value: 0 }, uTime: { value: 0 }, uAberr: { value: 0.0025 } },
  vertexShader: /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse; uniform float uAmt, uTime, uAberr; varying vec2 vUv;
    float h(float n){ return fract(sin(n)*43758.5453); }
    void main(){
      vec2 uv = vUv;
      float row = floor(uv.y*36.0); float tick = floor(uTime*24.0);
      float tear = step(0.78, h(row*7.1 + tick)) * (h(row + tick*3.3) - 0.5);
      uv.x += tear * 0.08 * uAmt;
      vec2 dir = uv - 0.5;
      float k = uAberr + 0.025*uAmt;
      vec3 c = vec3(texture2D(tDiffuse, uv + dir*k).r, texture2D(tDiffuse, uv).g, texture2D(tDiffuse, uv - dir*k).b);
      c *= 1.0 - 0.12*uAmt*(0.5 + 0.5*sin(uv.y*900.0));
      float vig = smoothstep(1.15, 0.35, length(dir)*1.35);
      gl_FragColor = vec4(c * mix(1.0, vig, 0.55), 1.0);
    }`,
};

// ---- the orb ------------------------------------------------------------------
export class Orb3D {
  constructor(canvas) {
    this.canvas = canvas;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    if (!renderer.getContext()) throw new Error("WebGL unavailable");
    this.renderer = renderer;
    renderer.setClearColor(new THREE.Color("#06070c"), 1);

    this.state = "idle";
    this.mood = "calm";
    this.levelFn = () => 0;
    this.specFn = null;
    this.onTap = null;
    this.dimTarget = 0;

    // Animated values
    this.v = { amp: 0.045, scan: 0.35, bloom: 0.85, spread: 0.2, pull: 0, ring: 0.12, sweep: 0, wire: 0.55, pts: 0.6,
      speed: 0.5, freq: 1.3, moodAmp: 0.8, dim: 1, hover: 0 };
    this.colA = srgb(MOODS.calm.a);
    this.colB = srgb(MOODS.calm.b);
    this.level = 0;
    this.prevLevel = 0;
    this.phase = 0;
    this.flashAmt = 0;
    this.glitch = 0;
    this.spike = 0;
    this.kick = 0;
    this.shake = 0;
    this.moodPop = 0;
    this.spec = new Float32Array(BANDS);
    this.rawSpec = new Float32Array(BANDS);
    this.pulses = Array.from({ length: MAX_PULSES }, () => new THREE.Vector4(0, 0, 1, 1));
    this.pulseIdx = 0;
    this.words = [];
    this.lastWordPulse = 0;

    this.perfLevel = 0;
    this.baseLevel = 0;
    this.maxPr = Orb3D.LEVELS[0].pr;
    this.buildScene();
    this.buildPost();
    this.bindPointer();
    this.resize();
    addEventListener("resize", () => this.resize());

    this.clock = new THREE.Clock();
    renderer.setAnimationLoop(() => this.frame());
  }

  // ---- public API (matches the 2D orb) -----------------------------------------
  setState(state) {
    if (!STATE[state] || state === this.state) return;
    this.state = state;
  }
  setLevelSource(fn) { this.levelFn = fn; }
  /** fn(out: Float32Array) fills `out` with 0..1 band energies. */
  setSpectrumSource(fn) { this.specFn = fn; }
  setDimmed(dimmed) { this.dimTarget = dimmed ? 1 : 0; }

  /**
   * "full" or "lite". With "full", the orb still steps itself down on a Mac that can't
   * keep up (see perfCheck), and back up when there's headroom again.
   */
  setQuality(q) {
    this.baseLevel = q === "lite" ? 3 : 0;
    this.applyLevel(Math.max(this.baseLevel, this.perfLevel ?? 0), true);
  }

  /** Quality steps, best first. Each one is cheaper to draw than the one before. */
  static LEVELS = [
    { pr: 1.75, lite: false, glitch: true }, // full
    { pr: 1.25, lite: false, glitch: true }, // a little softer
    { pr: 1.0, lite: false, glitch: true }, // standard sharpness
    { pr: 1.0, lite: true, glitch: true }, // fewer particles, no dust
    { pr: 0.75, lite: true, glitch: false }, // lightest
  ];

  applyLevel(level, force = false) {
    level = Math.max(this.baseLevel ?? 0, Math.min(Orb3D.LEVELS.length - 1, level));
    if (!force && level === this.perfLevel) return;
    this.perfLevel = level;
    const L = Orb3D.LEVELS[level];
    this.lite = L.lite;
    this.maxPr = L.pr;
    this.points.geometry.setDrawRange(0, this.lite ? 1400 : this.points.geometry.attributes.position.count);
    this.dust.visible = !this.lite;
    if (this.glitchPass) this.glitchPass.enabled = L.glitch;
    this.resize();
    // Other parts of the app (e.g. the camera detector) ease off when the Mac is struggling.
    globalThis.__orbPerf = { level, struggling: level >= 3 };
    dispatchEvent(new CustomEvent("orb-perf", { detail: globalThis.__orbPerf }));
  }

  /**
   * Called every drawn frame with the time since the last one. Steps quality down after
   * ~2.5 s below 48 fps, and back up after 20 s at a steady 58+ fps (at most once a minute,
   * so it doesn't flip back and forth).
   */
  perfCheck(ms, now) {
    if (document.hidden || ms > 250) return; // background tab or a hiccup, not a trend
    this.fpsAvg = this.fpsAvg ? this.fpsAvg * 0.95 + (1000 / ms) * 0.05 : 1000 / ms;
    if (this.fpsAvg < 48) {
      this.slowSince ??= now;
      this.fastSince = null;
      if (now - this.slowSince > 2500 && this.perfLevel < Orb3D.LEVELS.length - 1) {
        this.applyLevel(this.perfLevel + 1);
        this.slowSince = null;
        this.lastStepDown = now;
        this.fpsAvg = 55; // give the new level a fair start
      }
    } else {
      this.slowSince = null;
      if (this.fpsAvg >= 58) {
        this.fastSince ??= now;
        const settled = now - (this.lastStepDown ?? -1e9) > 60_000;
        if (now - this.fastSince > 20_000 && settled && this.perfLevel > (this.baseLevel ?? 0)) {
          this.applyLevel(this.perfLevel - 1);
          this.fastSince = null;
        }
      } else {
        this.fastSince = null;
      }
    }
  }

  setWordsEnabled(on) {
    this.wordsOn = on;
    if (!on) for (const w of [...this.words]) this.removeWord(w);
  }

  setMood(mood) {
    if (!MOODS[mood] || mood === this.mood) return;
    this.mood = mood;
    this.moodPop = 1;
    this.pulse(new THREE.Vector3(0, 0, 1), 1);
    this.pulse(new THREE.Vector3(0, 0, -1), 1);
  }

  /** Interruption: glitch, shock ring, flash, the cloud blown outward. */
  flash() {
    this.flashAmt = 1;
    this.glitch = 1;
    this.spike = 1;
    this.kick = 1;
    this.shake = 1;
    this.spawnShock(1.4, CUT_COLORS.a);
    for (let i = 0; i < 4; i++) this.pulse(new THREE.Vector3().randomDirection(), 1);
  }

  /** Something new came into the camera's view. x, y: 0..1 position in the (mirrored) preview. */
  see(label, x = 0.5, y = 0.5) {
    const dir = new THREE.Vector3((x - 0.5) * 2.4, (0.5 - y) * 1.8, 0.9).normalize();
    this.spawnShock(0.55, SEE_COLORS.a);
    this.word(label, "see", dir);
  }

  /** A word was heard (who = "user"), spoken (who = "assistant") or seen (who = "see"). */
  word(text, who, atDir) {
    if (this.wordsOn === false) return;
    const clean = String(text).replace(/[^\p{L}\p{N}'’-]/gu, "").slice(0, 18);
    if (!clean) return;
    if (this.words.length > 28) this.removeWord(this.words[0]);

    const dir = atDir ? atDir.clone() : new THREE.Vector3().randomDirection();
    if (!atDir) dir.z = Math.abs(dir.z) * 0.8 + 0.35; // keep words on the visible side
    dir.normalize();
    const color = who === "user" ? LISTEN_COLORS.a : who === "see" ? SEE_COLORS.a : MOODS[this.mood].a;
    const sprite = makeWordSprite(clean.toUpperCase(), color);
    this.scene.add(sprite);
    const w = { sprite, who, dir, age: 0, life: who === "user" ? 0.9 : who === "see" ? 1.5 : 2.6, pulsed: false };
    this.words.push(w);
    if (who === "assistant") this.wordPulse(dir, 0.7);
    this.updateWord(w, 0);
  }

  /** Local ripple in a world-space direction from the orb's centre. */
  pulse(worldDir, strength = 1) {
    const local = worldDir.clone().normalize().applyQuaternion(this.spin.quaternion.clone().invert());
    const p = this.pulses[this.pulseIdx];
    p.set(local.x, local.y, local.z, 1 - Math.min(1, strength));
    this.pulseIdx = (this.pulseIdx + 1) % MAX_PULSES;
  }

  // ---- scene ------------------------------------------------------------------
  buildScene() {
    const scene = (this.scene = new THREE.Scene());
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    this.camera.position.set(0, 0, 7);

    this.root = new THREE.Group(); // positioned so the orb sits above the captions
    scene.add(this.root);
    this.spin = new THREE.Group(); // rotated by drag + idle drift
    this.root.add(this.spin);

    // Shared uniforms for everything that deforms with the surface.
    this.specTex = new THREE.DataTexture(new Uint8Array(BANDS * 4), BANDS, 1, THREE.RGBAFormat);
    this.specTex.magFilter = this.specTex.minFilter = THREE.LinearFilter;
    this.specTex.needsUpdate = true;
    const u = (this.u = {
      uTime: { value: 0 }, uPhase: { value: 0 }, uAmp: { value: 0.05 }, uFreq: { value: 1.3 },
      uLevel: { value: 0 }, uBass: { value: 0 }, uSpike: { value: 0 }, uBeat: { value: 0 },
      uHover: { value: new THREE.Vector3(0, 0, 1) }, uHoverAmt: { value: 0 },
      uPulses: { value: this.pulses },
      uColA: { value: this.colA }, uColB: { value: this.colB },
      uScan: { value: 0.4 }, uGlow: { value: 1 }, uDim: { value: 1 }, uFlash: { value: 0 }, uWire: { value: 0.6 },
      uSpec: { value: this.specTex }, uSpread: { value: 0.2 }, uPull: { value: 0 }, uKick: { value: 0 },
      uSize: { value: 2.2 }, uOpacity: { value: 0.7 },
    });

    // Core
    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1, 48),
      new THREE.ShaderMaterial({ uniforms: { ...u, uRadius: { value: 1 } }, vertexShader: SURFACE_VERT, fragmentShader: CORE_FRAG }),
    );
    this.spin.add(core);
    this.core = core;

    // Geodesic lattice shell
    const wire = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1, 5),
      new THREE.ShaderMaterial({
        uniforms: { ...u, uRadius: { value: 1.045 } },
        vertexShader: SURFACE_VERT, fragmentShader: WIRE_FRAG,
        wireframe: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      }),
    );
    this.spin.add(wire);

    // Particle cloud whose shells follow the spectrum
    const N = 3200;
    const pos = new Float32Array(N * 3);
    const band = new Float32Array(N);
    const rnd = new Float32Array(N);
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const th = golden * i;
      pos.set([Math.cos(th) * r, y, Math.sin(th) * r], i * 3);
      band[i] = Math.abs(Math.atan2(y, Math.cos(th) * r)) / Math.PI;
      rnd[i] = Math.random();
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    pg.setAttribute("aBand", new THREE.BufferAttribute(band, 1));
    pg.setAttribute("aRand", new THREE.BufferAttribute(rnd, 1));
    this.points = new THREE.Points(
      pg,
      new THREE.ShaderMaterial({
        uniforms: u, vertexShader: POINTS_VERT, fragmentShader: POINTS_FRAG,
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      }),
    );
    this.spin.add(this.points);

    // HUD rings (tilted, spinning, dashed)
    this.rings = [];
    const ringDefs = [
      { r: 1.42, w: 0.008, dash: 72, fill: 0.45, tilt: [1.25, 0.2, 0], speed: 0.06, opacity: 0.55 },
      { r: 2.2, w: 0.005, dash: 180, fill: 0.7, tilt: [0.3, -0.5, 0], speed: -0.03, opacity: 0.4 },
      { r: 2.45, w: 0.012, dash: 6, fill: 0.62, tilt: [-0.9, 0.6, 0.3], speed: 0.045, opacity: 0.45 },
      { r: 1.7, w: 0.004, dash: 1, fill: 0.0, tilt: [1.57, 0, 0], speed: 0, opacity: 0.18 },
    ];
    for (const d of ringDefs) {
      const mat = new THREE.ShaderMaterial({
        uniforms: {
          uCol: { value: this.colA }, uDash: { value: d.dash }, uFill: { value: d.fill }, uRot: { value: 0 },
          uOpacity: { value: d.opacity }, uSweep: { value: 0 }, uSweepRot: { value: Math.random() }, uDim: u.uDim,
        },
        vertexShader: RING_VERT, fragmentShader: RING_FRAG,
        transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(new THREE.RingGeometry(d.r, d.r + d.w, 256, 1), mat);
      mesh.rotation.set(...d.tilt);
      this.spin.add(mesh);
      this.rings.push({ mesh, mat, ...d });
    }

    // Radial equaliser facing the camera
    const barGeo = new THREE.PlaneGeometry(0.016, 1);
    barGeo.translate(0, 0.5, 0);
    this.eqMat = new THREE.MeshBasicMaterial({ color: this.colA, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false });
    this.eq = new THREE.InstancedMesh(barGeo, this.eqMat, BANDS * 2);
    this.eqDummy = new THREE.Object3D();
    this.root.add(this.eq);

    // Shock rings (interrupt / tap / mood change)
    this.shocks = [];
    for (let i = 0; i < 5; i++) {
      const m = new THREE.Mesh(
        new THREE.RingGeometry(0.97, 1, 128),
        new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }),
      );
      m.visible = false;
      this.root.add(m);
      this.shocks.push({ mesh: m, age: 1, power: 1 });
    }

    // Far star dust for depth
    const S = 900;
    const sp = new Float32Array(S * 3);
    for (let i = 0; i < S; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(9 + Math.random() * 14);
      sp.set([v.x, v.y, v.z], i * 3);
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute("position", new THREE.BufferAttribute(sp, 3));
    this.dust = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0x8090c0, size: 0.04, transparent: true, opacity: 0.5, depthWrite: false }));
    scene.add(this.dust);
  }

  buildPost() {
    const composer = (this.composer = new EffectComposer(this.renderer));
    composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.6, 0.5, 0.22);
    composer.addPass(this.bloom);
    this.glitchPass = new ShaderPass(GLITCH);
    composer.addPass(this.glitchPass);
    composer.addPass(new OutputPass());
  }

  resize() {
    const w = innerWidth;
    const h = innerHeight;
    this.hasSize = w > 16 && h > 16; // a hidden or collapsed window has no size to render into
    if (!this.hasSize) return;
    const pr = Math.min(devicePixelRatio || 1, this.maxPr ?? 1.75);
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(pr);
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    // Keep the whole halo visible on narrow screens.
    // Portrait screens: pull back just enough to keep the outer rings in view.
    this.baseZ = this.camera.aspect < 1.2 ? Math.min(10 / Math.max(0.55, this.camera.aspect / 1.2), 8.4 / Math.max(0.5, this.camera.aspect)) : 10;
    this.camera.updateProjectionMatrix();
    this.root.position.y = this.camera.aspect < 0.8 ? 0.9 : 0.55; // leave room for captions below
    this.u.uSize.value = 2.2 * pr;
  }

  // ---- pointer interaction -----------------------------------------------------
  bindPointer() {
    const c = this.canvas;
    c.style.touchAction = "none";
    this.ndc = new THREE.Vector2(0, 0);
    this.ndcSmooth = new THREE.Vector2(0, 0);
    this.ray = new THREE.Raycaster();
    this.spinVel = new THREE.Vector2(0, 0);
    this.drag = null;
    this.hitDir = null;
    this.hoverTarget = 0;

    const toNdc = (e) => this.ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);

    c.addEventListener("pointermove", (e) => {
      toNdc(e);
      if (this.drag) {
        const dx = e.clientX - this.drag.x;
        const dy = e.clientY - this.drag.y;
        this.drag.x = e.clientX;
        this.drag.y = e.clientY;
        this.drag.moved += Math.abs(dx) + Math.abs(dy);
        this.spinVel.x = dy * 0.6;
        this.spinVel.y = dx * 0.6;
      }
    });
    c.addEventListener("pointerdown", (e) => {
      toNdc(e);
      this.drag = { x: e.clientX, y: e.clientY, moved: 0, t: performance.now() };
      c.setPointerCapture(e.pointerId);
      c.style.cursor = "grabbing";
    });
    const end = (e) => {
      if (!this.drag) return;
      const tap = this.drag.moved < 6 && performance.now() - this.drag.t < 400;
      this.drag = null;
      c.style.cursor = "";
      if (tap && this.hitDir) {
        this.pulse(this.hitDir, 1);
        this.spawnShock(0.8, [255, 255, 255]);
        this.onTap?.();
      }
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", () => {
      this.hoverTarget = 0;
      this.hitDir = null;
    });
  }

  updateHover() {
    this.ray.setFromCamera(this.ndc, this.camera);
    const center = this.root.getWorldPosition(new THREE.Vector3());
    const hit = this.ray.ray.intersectSphere(new THREE.Sphere(center, 1.15), new THREE.Vector3());
    if (hit) {
      this.hitDir = hit.sub(center).normalize();
      this.hoverTarget = 1;
      const local = this.hitDir.clone().applyQuaternion(this.spin.quaternion.clone().invert());
      this.u.uHover.value.lerp(local, 0.35).normalize();
      if (!this.drag) this.canvas.style.cursor = "pointer";
    } else {
      this.hitDir = null;
      this.hoverTarget = 0;
      if (!this.drag) this.canvas.style.cursor = "";
    }
  }

  // ---- effects -----------------------------------------------------------------
  spawnShock(power, color) {
    const s = this.shocks.find((x) => x.age >= 1) || this.shocks[0];
    s.age = 0;
    s.power = power;
    s.mesh.material.color.copy(srgb(color));
    s.mesh.visible = true;
  }

  wordPulse(dir, strength) {
    const now = this.simTime ?? this.clock?.elapsedTime ?? 0;
    if (now - this.lastWordPulse < 0.08) return; // don't saturate the pulse slots
    this.lastWordPulse = now;
    this.pulse(dir, strength);
  }

  updateWord(w, dt) {
    w.age += dt / w.life;
    const t = Math.min(1, w.age);
    let r;
    let alpha;
    if (w.who === "user" || w.who === "see") {
      // Fly in from outside and get absorbed.
      const e = t * t;
      r = 3.1 - e * 2.0;
      alpha = Math.min(1, t * 6) * (1 - Math.max(0, (t - 0.8) / 0.2));
      if (t >= 0.95 && !w.pulsed) {
        w.pulsed = true;
        this.wordPulse(w.dir, 0.8);
      }
    } else {
      // Emerge from the surface and drift away.
      const e = 1 - Math.pow(1 - t, 3);
      r = 1.15 + e * 1.7;
      alpha = Math.min(1, t * 8) * (1 - t);
    }
    const p = w.dir.clone().multiplyScalar(r).add(this.root.position);
    w.sprite.position.copy(p);
    w.sprite.material.opacity = alpha * 0.9 * this.v.dim;
  }

  removeWord(w) {
    this.scene.remove(w.sprite);
    w.sprite.material.map.dispose();
    w.sprite.material.dispose();
    this.words.splice(this.words.indexOf(w), 1);
  }

  // ---- frame -------------------------------------------------------------------
  /** One animation step. `fixedDt` lets tests step the scene without real time passing. */
  frame(fixedDt) {
    if (fixedDt === undefined) {
      // At most 60 frames a second: 120 Hz screens would otherwise double the work for no visible gain.
      const now = performance.now();
      if (this.lastDraw && now - this.lastDraw < 15.5) return;
      if (this.lastDraw) this.perfCheck(now - this.lastDraw, now);
      this.lastDraw = now;
    }
    // Use real elapsed time (capped) so a slow or throttled tab stays in step with the conversation.
    const dt = fixedDt ?? Math.min(0.2, this.clock.getDelta());
    if (fixedDt) this.simTime = (this.simTime ?? this.clock.elapsedTime) + fixedDt;
    const t = fixedDt ? this.simTime : this.clock.elapsedTime;
    const v = this.v;
    const S = STATE[this.state];
    const M = MOODS[this.mood];

    // Colours: listening = your colour, thinking = violet, cut = red, otherwise Claude's mood.
    const pal =
      this.state === "listening" ? LISTEN_COLORS :
      this.state === "thinking" ? THINK_COLORS :
      this.state === "interrupted" ? CUT_COLORS : M;
    const k = 1 - Math.exp(-dt * (this.state === "interrupted" ? 14 : 3.5));
    this.colA.lerp(srgb(pal.a), k);
    this.colB.lerp(srgb(pal.b), k);
    this.eqMat.color.copy(this.colA);

    for (const key of ["amp", "scan", "bloom", "spread", "pull", "ring", "sweep", "wire", "pts"]) v[key] = damp(v[key], S[key], 4, dt);
    v.speed = damp(v.speed, M.speed, 2, dt);
    v.freq = damp(v.freq, M.freq, 2, dt);
    v.moodAmp = damp(v.moodAmp, M.amp, 2, dt);
    v.dim = damp(v.dim, 1 - this.dimTarget * 0.55, 5, dt);
    v.hover = damp(v.hover, this.hoverTarget, 6, dt);

    // Audio level (fast attack, slow release) and spectrum.
    const raw = Math.min(1, (this.levelFn() || 0) * 7);
    this.prevLevel = this.level;
    this.level = damp(this.level, raw, raw > this.level ? 20 : 5, dt);
    if (this.specFn) this.specFn(this.rawSpec);
    else this.rawSpec.fill(0);
    const data = this.specTex.image.data;
    let bass = 0;
    for (let i = 0; i < BANDS; i++) {
      const target = this.rawSpec[i];
      this.spec[i] = damp(this.spec[i], target, target > this.spec[i] ? 25 : 6, dt);
      data[i * 4] = Math.min(255, this.spec[i] * 255);
      if (i < 8) bass += this.spec[i] / 8;
    }
    this.specTex.needsUpdate = true;

    // Syllable onsets throw a ripple from the side the sound is "coming from".
    if ((this.state === "listening" || this.state === "speaking") && this.level - this.prevLevel > 0.06 && this.level > 0.2) {
      const dir = new THREE.Vector3((Math.random() - 0.5) * 1.4, (Math.random() - 0.5) * 1.4, this.state === "listening" ? 1 : -0.2);
      this.wordPulse(dir, 0.6);
    }

    // Mood beat: the rhythm of the orb's "body language".
    let beat = 0;
    if (M.beat === "breathe") beat = Math.sin(t * 1.2) * 0.02;
    else if (M.beat === "bounce") beat = Math.abs(Math.sin(t * 3.2)) * 0.035 - 0.015;
    else if (M.beat === "heart") {
      const ph = (t * 1.1) % 1;
      beat = (Math.exp(-Math.pow((ph - 0.1) * 18, 2)) + 0.6 * Math.exp(-Math.pow((ph - 0.3) * 18, 2))) * 0.05;
    } else if (M.beat === "pop") beat = Math.sin(t * 5) * 0.012;
    beat += this.moodPop * 0.12;
    this.moodPop = Math.max(0, this.moodPop - dt * 1.6);

    // Decays
    this.flashAmt = Math.max(0, this.flashAmt - dt * 3.5);
    this.glitch = Math.max(0, this.glitch - dt * 2.2);
    this.spike = Math.max(0, this.spike - dt * 2.5);
    this.kick = Math.max(0, this.kick - dt * 1.8);
    this.shake = Math.max(0, this.shake - dt * 3);
    for (const p of this.pulses) if (p.w < 1) p.w = Math.min(1, p.w + dt / 1.4);

    this.phase += dt * v.speed * (1 + this.level * 1.8) * (this.state === "thinking" ? 1.6 : 1);

    // Uniforms
    const u = this.u;
    u.uTime.value = t;
    u.uPhase.value = this.phase;
    u.uAmp.value = v.amp * v.moodAmp;
    u.uFreq.value = v.freq;
    u.uLevel.value = this.level;
    u.uBass.value = bass;
    u.uSpike.value = this.spike;
    u.uBeat.value = beat;
    u.uHoverAmt.value = v.hover * (1 + this.level);
    u.uScan.value = v.scan;
    u.uGlow.value = 1 + this.level * 0.5;
    u.uDim.value = v.dim;
    u.uFlash.value = this.flashAmt * 0.7;
    u.uWire.value = v.wire;
    u.uSpread.value = v.spread;
    u.uPull.value = v.pull;
    u.uKick.value = this.kick * this.kick;
    u.uOpacity.value = 0.7 * v.pts;

    // Spin: drag inertia + idle drift; curious mood adds a head-tilt.
    if (!this.drag) this.spinVel.multiplyScalar(Math.exp(-dt * 2.2));
    const drift = 0.08 * v.speed + (this.state === "thinking" ? 0.35 : 0);
    const q = new THREE.Quaternion();
    q.setFromAxisAngle(new THREE.Vector3(1, 0, 0), this.spinVel.x * dt * 0.05);
    this.spin.quaternion.premultiply(q);
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), this.spinVel.y * dt * 0.05 + drift * dt);
    this.spin.quaternion.premultiply(q);
    this.root.rotation.z = M.beat === "tilt" ? Math.sin(t * 0.9) * 0.12 : damp(this.root.rotation.z, 0, 2, dt);

    // Rings
    for (const r of this.rings) {
      r.mat.uniforms.uRot.value += dt * r.speed * (1 + v.ring * 4) * (1 + this.level * 2);
      r.mat.uniforms.uSweep.value = v.sweep * 1.2;
      r.mat.uniforms.uSweepRot.value += dt * (0.4 + v.ring * 0.4);
    }

    // Equaliser bars (mirrored left/right so it reads as one shape)
    const total = BANDS * 2;
    const ringR = 1.95 + this.level * 0.15;
    for (let i = 0; i < total; i++) {
      const a = (i / total) * Math.PI * 2 + Math.PI / 2;
      const b = i < BANDS ? i : total - 1 - i;
      const s = this.spec[b];
      const len = 0.025 + s * 0.38 + this.level * 0.04;
      const d = this.eqDummy;
      d.position.set(Math.cos(a) * ringR, Math.sin(a) * ringR, 0);
      d.rotation.set(0, 0, a - Math.PI / 2);
      d.scale.set(1 + s, len, 1);
      d.updateMatrix();
      this.eq.setMatrixAt(i, d.matrix);
    }
    this.eq.instanceMatrix.needsUpdate = true;
    this.eqMat.opacity = (0.25 + v.spread * 0.5 + this.level * 0.4) * v.dim;

    // Shock rings
    for (const s of this.shocks) {
      if (s.age >= 1) continue;
      s.age = Math.min(1, s.age + dt / 0.9);
      const sc = 1.05 + s.age * 2.4 * s.power;
      s.mesh.scale.setScalar(sc);
      s.mesh.material.opacity = (1 - s.age) * 0.8;
      if (s.age >= 1) s.mesh.visible = false;
    }

    // Words
    for (const w of [...this.words]) {
      this.updateWord(w, dt);
      if (w.age >= 1) this.removeWord(w);
    }

    // Camera: gentle parallax towards the pointer + shake on interrupt.
    this.updateHover();
    this.ndcSmooth.lerp(this.ndc, 1 - Math.exp(-dt * 3));
    const sh = this.lite ? 0 : this.shake * this.shake * 0.12;
    this.camera.position.set(
      this.ndcSmooth.x * 0.35 + (Math.random() - 0.5) * sh,
      this.ndcSmooth.y * 0.25 + (Math.random() - 0.5) * sh,
      this.baseZ - this.level * 0.25,
    );
    this.camera.lookAt(0, this.root.position.y * 0.6, 0);
    this.dust.rotation.y += dt * 0.01;

    // Post
    this.bloom.strength = (v.bloom * 0.55 + this.level * 0.2 + this.flashAmt * 0.9) * v.dim;
    this.glitchPass.uniforms.uAmt.value = this.glitch * (this.lite ? 0.3 : 1);
    this.glitchPass.uniforms.uTime.value = t;

    if (!this.hasSize) this.resize();
    if (this.hasSize) this.composer.render(dt);
  }
}

// Text sprite for a single word, in a monospace "terminal" style.
function makeWordSprite(text, color) {
  const fontPx = 40;
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d");
  const font = `600 ${fontPx}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width) + 24;
  c.width = w;
  c.height = fontPx + 20;
  ctx.font = font;
  ctx.textBaseline = "middle";
  ctx.fillStyle = `rgb(${color[0]},${color[1]},${color[2]})`;
  ctx.shadowColor = ctx.fillStyle;
  ctx.shadowBlur = 10;
  ctx.fillText(text, 12, c.height / 2);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const sprite = new THREE.Sprite(mat);
  const h = 0.15;
  sprite.scale.set((h * c.width) / c.height, h, 1);
  return sprite;
}
