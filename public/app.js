import { Orb as Orb2D } from "./orb2d.js";
import { AudioEngine } from "./audio.js";
import { Vision, VISION_MODELS, sceneChange } from "./vision.js";

// ---- tuning -------------------------------------------------------------------
const FRAME_MS = 20; // mic frames from the worklet
const SPEECH_START_MS = 60; // to show the "listening" look
const SPEECH_END_MS = 500; // silence before the orb settles back
const SENTENCE_GAP_S = 0.14; // pause between spoken sentences
const WORD_MS = 330; // Cipher's words appear at roughly speaking pace
// Interrupt sensitivity: how long you must talk over Cipher, and how loud.
const SENSITIVITY = {
  low: { ms: 260, thinkingMs: 320, gain: 1.4 },
  normal: { ms: 160, thinkingMs: 220, gain: 1 },
  high: { ms: 110, thinkingMs: 160, gain: 0.75 },
};
const KEYS = [
  { name: "ANTHROPIC_API_KEY", service: "Anthropic" },
  { name: "DEEPGRAM_API_KEY", service: "Deepgram" },
  { name: "ELEVENLABS_API_KEY", service: "ElevenLabs" },
];
const MOOD_LABEL = {
  calm: "Calm", happy: "Happy", excited: "Excited", curious: "Curious", thoughtful: "Thoughtful",
  empathetic: "Empathetic", serious: "Serious", playful: "Playful", surprised: "Surprised",
};

// Listening state from the server (wake word, voice match).
let listenState = null;
let waitingWake = false;
let wakePhrase = "Cipher";

// ---- elements -------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const els = {
  body: document.body,
  canvas: $("orb"),
  island: $("island"),
  islandState: $("islandState"),
  islandMood: $("islandMood"),
  islandMeta: $("islandMeta"),
  setup: $("setup"),
  keyList: $("keyList"),
  userLine: document.querySelector(".caption.user"),
  assistantLine: document.querySelector(".caption.assistant"),
  user: $("userCaption"),
  assistant: $("assistantCaption"),
  hint: $("hint"),
  session: $("sessionBtn"),
  sessionLabel: $("sessionLabel"),
  mute: $("muteBtn"),
  stop: $("stopBtn"),
  transcriptBtn: $("transcriptBtn"),
  transcriptBadge: $("transcriptBadge"),
  sheet: $("transcriptSheet"),
  list: $("transcriptList"),
  empty: $("transcriptEmpty"),
  copy: $("copyBtn"),
  clear: $("clearBtn"),
  closeSheet: $("closeSheetBtn"),
  settingsBtn: $("settingsBtn"),
  settingsPop: $("settingsPop"),
  helpBtn: $("helpBtn"),
  helpPop: $("helpPop"),
  newChat: $("newChatBtn"),
  toasts: $("toasts"),
  tooltip: $("tooltip"),
  camera: $("cameraBtn"),
  camTile: $("camTile"),
  camVideo: $("camVideo"),
  camOverlay: $("camOverlay"),
  camLoading: $("camLoading"),
  camLoadingText: $("camLoadingText"),
  camBar: $("camBar"),
  camSees: $("camSees"),
  camMs: $("camMs"),
};

// ---- settings (remembered per browser) ---------------------------------------------
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const settings = { sensitivity: "normal", quality: reducedMotion ? "lite" : "full", words: true, captions: true, vision: "fast", stills: true, noiseFilter: true };
try {
  Object.assign(settings, JSON.parse(localStorage.getItem("voice-orb-settings") || "{}"));
} catch {}
function saveSettings() {
  try {
    localStorage.setItem("voice-orb-settings", JSON.stringify(settings));
  } catch {}
}

// ---- orb ----------------------------------------------------------------------------
// The 3D orb needs WebGL; fall back to the flat one if it isn't available.
let orb;
try {
  const { Orb3D } = await import("./orb3d.js");
  orb = new Orb3D(els.canvas);
} catch (err) {
  console.warn("3D orb unavailable, using the 2D orb:", err);
  orb = new Orb2D(els.canvas);
}

// ---- state ----------------------------------------------------------------------------
// One conversation per browser, kept across reloads and server restarts (the server
// saves it). "Start a new conversation" clears it.
const sessionId = (() => {
  try {
    const saved = localStorage.getItem("orb-conversation");
    if (saved && /^[\w-]{8,64}$/.test(saved)) return saved;
    const id = crypto.randomUUID();
    localStorage.setItem("orb-conversation", id);
    return id;
  } catch {
    return crypto.randomUUID();
  }
})();
let ws = null;
let reconnectDelay = 500;
let connected = false;
let missingKeys = null; // null until the server tells us
let active = false;
let starting = false;
let muted = false;
let audio = null;
let state = "idle";
let mood = "calm";
let interruptTimer = null;

let currentTurnId = 0;
const cutTurns = new Set();
let assistantText = "";
let userTurnAt = 0;
const firstAudioSeen = new Set();

const vad = { floor: 0.006, above: 0, below: 0, speaking: false, onsetSent: false, endSent: true };

// Words: yours fly in as you're transcribed; Cipher's appear in step with its voice.
let userWordsShown = 0;
let assistantPending = "";
const assistantWords = [];
let wordTimer = null;
let wordsShownThisTurn = 0;

// ---- WebSocket --------------------------------------------------------------------------
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?session=${sessionId}`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    reconnectDelay = 500;
    connected = true;
    // A new connection starts its turn ids from 1 again.
    cutTurns.clear();
    firstAudioSeen.clear();
    currentTurnId = 0;
    if (vision.on) send({ type: "vision", enabled: true });
    if (active) {
      send({ type: "start" });
      if (muted) send({ type: "mute", muted: true });
      if (wasDisconnected) toast({ title: "Reconnected", message: "You're back online.", kind: "ok", timeout: 2500 });
    }
    wasDisconnected = false;
    renderAll();
  };

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) onAudio(e.data);
    else onJson(JSON.parse(e.data));
  };

  ws.onclose = () => {
    ws = null;
    if (connected) wasDisconnected = true;
    connected = false;
    if (active) {
      audio?.stopPlayback();
      setState("idle");
    }
    renderAll();
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 8000);
  };
}
let wasDisconnected = false;

function send(msg) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function onAudio(buf) {
  const turnId = new DataView(buf).getUint32(0, true);
  if (!active || turnId !== currentTurnId || cutTurns.has(turnId)) return;
  if (!firstAudioSeen.has(turnId)) {
    firstAudioSeen.add(turnId);
    if (userTurnAt) setLatency(turnId, (performance.now() - userTurnAt) / 1000);
  }
  audio?.playPcm(buf.slice(4));
}

function onJson(msg) {
  switch (msg.type) {
    case "status":
      checkVersion(msg.version);
      if (msg.hosted && !document.body.dataset.hosted) {
        document.body.dataset.hosted = "1";
        // Wording for the cloud version: things are kept on your server, not "this Mac".
        for (const el of document.querySelectorAll(".field-help")) el.textContent = el.textContent.replace(/on this Mac/g, "on your private server").replace(/fully on this Mac/g, "fully private");
      }
      missingKeys = msg.missingKeys || [];
      renderAll();
      break;
    case "ready":
      renderIsland();
      break;
    case "backchannel_clips":
      audio?.loadCues(msg.clips || []);
      break;
    case "ack":
      // You said "yeah" while Cipher talked: you're listening, so bring its voice back up.
      vad.loudAt = 0;
      audio?.duck(false);
      break;
    case "backchannel":
      // A quiet "mm-hmm" while you're mid-thought. Not while muted, or once Cipher is replying.
      // (While a reply is still being prepared is fine: you haven't heard it yet.)
      // Never over your words: if you've already started talking again, skip it.
      if (active && !muted && !audio?.isPlaying && vad.above * FRAME_MS < 60) audio?.playCue(Number(msg.index) || 0);
      break;
    case "notice":
      flashIsland(msg.message);
      break;
    case "listening":
      listenState = msg;
      renderListening();
      break;
    case "wake":
      waitingWake = Boolean(msg.waiting);
      wakePhrase = msg.phrase || wakePhrase;
      document.body.dataset.wake = waitingWake ? "waiting" : "awake";
      orb.setDimmed(muted || waitingWake);
      if (!waitingWake && active) flashIsland("Awake");
      renderAll();
      break;
    case "ignored":
      // Speech without the wake word: nothing to show.
      if (els.userLine.classList.contains("live")) setUserCaption("", false);
      break;
    case "voice_rejected":
      setUserCaption("", false);
      flashIsland("Not your voice · ignored");
      break;
    case "voice_enroll":
      onEnroll(msg);
      break;
    case "transcript":
      setUserCaption(msg.text, !msg.final);
      feedUserWords(msg.text);
      break;
    case "user_turn":
      setUserCaption(msg.text, false);
      feedUserWords(msg.text);
      userWordsShown = 0;
      userTurnAt = performance.now();
      hideApproval(); // they answered, by voice or with a button
      if (msg.merged && lastYouMsg) {
        // Continuation of the sentence whose reply was just cancelled: one message, not two.
        lastYouMsg.bubble.textContent = msg.text;
        scrollTranscript();
      } else {
        lastYouMsg = addMessage("you", msg.text);
      }
      break;
    case "history":
      // The saved conversation, after a reload or restart: show it if the page is empty.
      if (!els.list.children.length) {
        for (const m of msg.messages || []) {
          const parts = addMessage(m.role === "user" ? "you" : "claude", m.text);
          if (m.role === "user") lastYouMsg = parts;
        }
      }
      break;
    case "memory": {
      const before = memoryState;
      memoryState = msg;
      renderMemory(msg.added || []);
      // Only announce changes made during the conversation, not the list arriving on connect.
      if (before && msg.added?.length) flashIsland(msg.added.length === 1 ? "Saved to memory" : `Saved ${msg.added.length} things to memory`);
      break;
    }
    case "mac":
      macMode = msg.mode;
      renderMac();
      break;
    case "mac_mode_confirm":
      // The server asks before lowering protection; only a yes here sends the code back.
      if (confirm("Let Cipher act on your Mac and in Chrome without asking first? It will still ask before sending, buying, deleting or shutting down.")) {
        send({ type: "mac_mode", mode: msg.mode, confirm: msg.code });
      }
      break;
    case "action":
      onAction(msg);
      break;
    case "chrome":
      renderChrome(msg);
      break;
    case "app_command":
      runAppCommand(msg);
      break;
    case "turn_cancelled": {
      // The user was only pausing; that reply never made a sound. Remove it quietly.
      cutTurns.add(msg.turnId);
      const m = claudeMsgs.get(msg.turnId);
      m?.li.remove();
      claudeMsgs.delete(msg.turnId);
      if (msg.turnId === currentTurnId) {
        assistantWords.length = 0;
        clearAssistantCaption();
        if (state === "thinking") setState("idle");
      }
      break;
    }
    case "thinking":
      stillTurnBegan();
      currentTurnId = msg.turnId;
      assistantText = "";
      assistantPending = "";
      assistantWords.length = 0;
      wordsShownThisTurn = 0;
      clearAssistantCaption();
      startCipherMessage(msg.turnId);
      if (!audio?.isPlaying) setState("thinking");
      break;
    case "mood":
      if (msg.turnId === currentTurnId && !cutTurns.has(msg.turnId)) {
        setMood(msg.mood);
        setMessageMood(msg.turnId, msg.mood);
      }
      break;
    case "assistant_delta":
      if (msg.turnId !== currentTurnId || cutTurns.has(msg.turnId)) break;
      assistantText += msg.text;
      queueAssistantWords(msg.text);
      setMessageText(msg.turnId, assistantText);
      break;
    case "tts_sentence_end":
      if (msg.turnId === currentTurnId && !cutTurns.has(msg.turnId)) audio?.addGap(typeof msg.pause === "number" ? Math.min(0.5, Math.max(0, msg.pause)) : SENTENCE_GAP_S);
      break;
    case "assistant_done":
      queueAssistantWords(" ");
      if (msg.failed && msg.turnId === currentTurnId) {
        flushAssistantWords();
        dropEmptyMessage(msg.turnId);
        if (!audio?.isPlaying) setState(vad.speaking ? "listening" : "idle");
      }
      break;
    case "tts_done":
      repliesDone.add(msg.turnId);
      // No audio came (e.g. a speech error): show the text and don't leave the orb on "thinking".
      if (msg.turnId === currentTurnId && !audio?.isPlaying) {
        flushAssistantWords();
        if (state === "thinking") setState("idle");
      }
      break;
    case "stopped":
      // The server couldn't keep the session going (e.g. a rejected key).
      endSession(false);
      break;
    case "interrupted":
      interrupt(msg.turnId, true);
      break;
    case "error":
      toast({ title: msg.source || "Error", message: msg.message, kind: "error" });
      if (state === "thinking") setState("idle");
      break;
  }
}

// ---- conversation ---------------------------------------------------------------------
async function startSession() {
  if (active || starting) return;
  if (missingKeys?.length) {
    pulse(els.setup);
    return;
  }
  if (!connected) {
    toast({ title: "Not connected", message: "Waiting for the server. Is npm start still running?", kind: "warn" });
    return;
  }
  starting = true;
  els.session.classList.add("busy");
  renderAll();
  try {
    audio = new AudioEngine({ onMicFrame, onPlaybackChange });
    await audio.start({ noiseFilter: settings.noiseFilter });
  } catch (err) {
    await audio?.stop().catch(() => {});
    audio = null;
    starting = false;
    els.session.classList.remove("busy");
    const denied = err?.name === "NotAllowedError" || err?.name === "SecurityError";
    const noMic = err?.name === "NotFoundError" || err?.name === "OverconstrainedError";
    const busyMic = err?.name === "NotReadableError";
    toast({
      title: denied ? "Microphone blocked" : noMic ? "No microphone found" : busyMic ? "Microphone in use" : "Couldn't start audio",
      message: denied
        ? "Allow microphone access from the icon in the address bar, then try again."
        : noMic
          ? "Connect a microphone or choose one in your system's sound settings, then try again."
          : busyMic
            ? "Another app is using the microphone. Close it and try again."
            : String(err?.message || err),
      kind: "error",
    });
    renderAll();
    return;
  }
  active = true;
  starting = false;
  els.session.classList.remove("busy");
  vad.above = vad.below = 0;
  vad.speaking = false;
  orb.setLevelSource(() => {
    if (!audio) return 0;
    if (audio.isPlaying) return audio.levelOut();
    return muted ? 0 : audio.levelIn();
  });
  orb.setSpectrumSource((out) => {
    if (!audio) return out.fill(0);
    if (audio.isPlaying) return audio.spectrum(out, "out");
    return muted ? out.fill(0) : audio.spectrum(out, "in");
  });
  send({ type: "start" });
  if (muted) send({ type: "mute", muted: true });
  setState("idle");
  renderAll();
}

async function endSession(notifyServer = true) {
  if (!active) return;
  active = false;
  if (notifyServer) send({ type: "stop" });
  if (currentTurnId) cutTurns.add(currentTurnId);
  const a = audio;
  audio = null;
  orb.setLevelSource(() => 0);
  orb.setSpectrumSource((out) => out.fill(0));
  assistantWords.length = 0;
  flushAssistantWords();
  await a?.stop();
  els.userLine.classList.remove("live");
  setState("idle");
  renderAll();
  if (reloadPending) location.reload(); // pick up the updated app
}

/** Silence Cipher now. `fromServer` means the server already aborted the reply. */
function interrupt(turnId = currentTurnId, fromServer = false) {
  if (!turnId || cutTurns.has(turnId)) return;
  cutTurns.add(turnId);
  // Tell the server first, so it still knows the audio was playing when it hears this.
  if (!fromServer) send({ type: "interrupt", turnId });
  // The caption advances in step with the voice, so it's our best record of what was heard.
  if (turnId === currentTurnId) send({ type: "heard", turnId, text: els.assistant.textContent });
  assistantWords.length = 0;
  assistantPending = "";
  audio?.stopPlayback(true);
  if (assistantText) els.assistantLine.classList.add("cut");
  markMessageCut(turnId);
  orb.flash();
  setState("interrupted");
  clearTimeout(interruptTimer);
  interruptTimer = setTimeout(() => {
    interruptTimer = null;
    if (active) setState("listening");
    else setState("idle");
  }, 340);
}

function claudeBusy() {
  return Boolean(audio?.isPlaying) || state === "thinking";
}

function onPlaybackChange(playing) {
  send({ type: "playback", playing });
  if (playing) setState("speaking");
  else {
    // Finished speaking normally: make sure every word made it into the caption.
    if (!cutTurns.has(currentTurnId)) flushAssistantWords();
    if (state === "speaking") setState(vad.speaking ? "listening" : "idle");
  }
}

// Runs every 20 ms with a fresh mic frame.
function onMicFrame(pcm, rms) {
  if (!active || !audio || muted) return;
  if (ws?.readyState === WebSocket.OPEN) ws.send(pcm);

  const sens = SENSITIVITY[settings.sensitivity] || SENSITIVITY.normal;
  const playing = audio.isPlaying;
  // While Cipher talks, require louder input so leftover echo isn't mistaken for you.
  const threshold = playing
    ? Math.max(0.03, vad.floor * 5, audio.levelOut() * 0.4) * sens.gain
    : Math.max(0.012, vad.floor * 3);

  if (rms > threshold) {
    vad.above++;
    vad.below = 0;
  } else {
    vad.below++;
    if (vad.below > 2) vad.above = 0; // tolerate a short dip mid-word
    if (!playing && !vad.speaking) vad.floor = vad.floor * 0.98 + Math.min(rms, 0.05) * 0.02;
  }
  const heardMs = vad.above * FRAME_MS;

  // Tell the server the moment you start (or resume) talking. If it has just started a
  // reply to half a sentence, it holds that reply back and drops it once your words arrive.
  if (!playing && heardMs >= SPEECH_START_MS && !vad.onsetSent) {
    vad.onsetSent = true;
    send({ type: "user_speaking" });
    vad.endSent = false;
    sendStill("start"); // what you're holding up as you start talking
  }
  if (vad.below * FRAME_MS >= 150) vad.onsetSent = false;
  // You've paused: this is the view your words are about. It reaches the server well before
  // it decides you've finished (that takes longer than this), so the reply sees this frame.
  if (!playing && !vad.endSent && vad.below * FRAME_MS >= 180) {
    vad.endSent = true;
    sendStill("pause");
  }

  // Something loud while Cipher talks: turn it down at once. It only stops if the server
  // hears actual words from you (not the TV, a cough or its own voice), see session.ts.
  if (playing && heardMs >= sens.ms) {
    // Once per burst: let the server check whose voice it is straight away.
    if (!audio.ducked || performance.now() - (vad.loudAt || 0) > 900) send({ type: "loud" });
    vad.loudAt = performance.now();
    audio.duck(true);
  } else if (audio.ducked && (!playing || performance.now() - (vad.loudAt || 0) > 900)) {
    audio.duck(false);
  }
  if (playing && heardMs >= sens.ms) return;
  if (state === "thinking" && heardMs >= sens.thinkingMs) {
    // Nothing has been said yet, so no interruption effect: the server cancels the
    // reply quietly if you keep talking, and answers everything you said.
    vad.speaking = true;
    return;
  }

  if (!vad.speaking && heardMs >= SPEECH_START_MS && !playing) vad.speaking = true;
  if (vad.speaking && vad.below * FRAME_MS >= SPEECH_END_MS) vad.speaking = false;

  if (!playing && !interruptTimer && (state === "idle" || state === "listening")) {
    setState(vad.speaking ? "listening" : "idle");
  }
}

function toggleMute(force) {
  if (!active) return;
  muted = force ?? !muted;
  els.mute.setAttribute("aria-pressed", String(muted));
  els.mute.setAttribute("aria-label", muted ? "Unmute microphone" : "Mute microphone");
  els.mute.dataset.tip = muted ? "Unmute" : "Mute";
  orb.setDimmed(muted || waitingWake);
  send({ type: "mute", muted });
  vad.above = vad.below = 0;
  vad.speaking = false;
  if (state === "listening") setState("idle");
  renderAll();
}

function newConversation() {
  if (claudeBusy() && currentTurnId) interrupt();
  send({ type: "reset" });
  els.list.replaceChildren();
  claudeMsgs.clear();
  lastYouMsg = null;
  actionRows.clear();
  hideApproval();
  setUserCaption("", false);
  clearAssistantCaption();
  setMood("calm");
  renderTranscriptChrome();
  closePopovers();
  toast({ title: "New conversation", message: "Cipher has forgotten the previous chat.", kind: "ok", timeout: 2500 });
}

// ---- words → captions and orb ------------------------------------------------------
function words(text) {
  return text.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w));
}

function feedUserWords(text) {
  const all = words(text);
  // Interim transcripts get revised; only fling words we haven't shown yet.
  if (settings.words) for (let i = userWordsShown; i < all.length; i++) orb.word(all[i], "user");
  userWordsShown = Math.max(userWordsShown, all.length);
}

function queueAssistantWords(delta) {
  assistantPending += delta;
  const parts = assistantPending.split(/\s+/);
  assistantPending = parts.pop() ?? ""; // last piece may be half a word
  for (const w of parts) if (w) assistantWords.push(w);
  if (!wordTimer && assistantWords.length) wordTimer = setInterval(releaseAssistantWord, WORD_MS);
}

function releaseAssistantWord() {
  if (!assistantWords.length) {
    clearInterval(wordTimer);
    wordTimer = null;
    return;
  }
  if (state !== "speaking") return;
  const w = assistantWords.shift();
  appendAssistantWord(w);
  if (settings.words && /[\p{L}\p{N}]/u.test(w)) orb.word(w, "assistant");
}

function flushAssistantWords() {
  if (assistantPending) {
    assistantWords.push(assistantPending);
    assistantPending = "";
  }
  while (assistantWords.length) appendAssistantWord(assistantWords.shift());
}

// ---- captions ---------------------------------------------------------------------------
function setUserCaption(text, live) {
  els.user.textContent = text;
  els.userLine.classList.toggle("live", live);
  els.userLine.dataset.empty = String(!text);
}

function clearAssistantCaption() {
  els.assistant.replaceChildren();
  els.assistantLine.classList.remove("cut");
  els.assistantLine.dataset.empty = "true";
}

function appendAssistantWord(w) {
  const span = document.createElement("span");
  span.className = "w";
  span.textContent = (wordsShownThisTurn ? " " : "") + w.replace(/[*_`#]/g, "");
  els.assistant.append(span);
  wordsShownThisTurn++;
  els.assistantLine.dataset.empty = "false";
}

// ---- transcript sheet ------------------------------------------------------------------
const claudeMsgs = new Map(); // turnId -> { li, bubble, meta, text, mood, cut, latency }
let lastYouMsg = null; // the latest "you" bubble, so a paused sentence's continuation joins it

function addMessage(who, text) {
  const li = document.createElement("li");
  li.className = `msg ${who}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = `${who === "you" ? "You" : "Cipher"} · ${timeNow()}`;
  li.append(bubble, meta);
  els.list.append(li);
  scrollTranscript();
  renderTranscriptChrome(true);
  return { li, bubble, meta };
}

function startCipherMessage(turnId) {
  const parts = addMessage("claude", "");
  parts.bubble.innerHTML = '<span class="typing" aria-label="Cipher is thinking"><i></i><i></i><i></i></span>';
  claudeMsgs.set(turnId, { ...parts, text: "", mood: null, cut: false, latency: null, time: timeNow() });
}

function setMessageText(turnId, text) {
  const m = claudeMsgs.get(turnId);
  if (!m) return;
  m.text = text;
  m.bubble.textContent = text.replace(/[*_`#]/g, "");
  scrollTranscript();
}

function setMessageMood(turnId, mood) {
  const m = claudeMsgs.get(turnId);
  if (!m) return;
  m.mood = mood;
  renderMeta(m);
}

function setLatency(turnId, seconds) {
  const m = claudeMsgs.get(turnId);
  if (m) {
    m.latency = seconds;
    renderMeta(m);
  }
  els.islandMeta.textContent = `${seconds.toFixed(1)}s`;
  els.islandMeta.hidden = false;
  renderIsland();
}

function markMessageCut(turnId) {
  const m = claudeMsgs.get(turnId);
  if (!m) return;
  if (!m.text.trim()) return dropEmptyMessage(turnId);
  m.cut = true;
  m.li.classList.add("cut");
  renderMeta(m);
}

function dropEmptyMessage(turnId) {
  const m = claudeMsgs.get(turnId);
  if (!m || m.text.trim()) return;
  m.li.remove();
  claudeMsgs.delete(turnId);
  renderTranscriptChrome();
}

function renderMeta(m) {
  m.meta.replaceChildren(document.createTextNode(`Cipher · ${m.time}`));
  if (m.mood) m.meta.append(chip(MOOD_LABEL[m.mood], moodRgb(m.mood)));
  if (m.cut) m.meta.append(chip("Interrupted", null, "cut"));
  if (m.latency != null) m.meta.append(document.createTextNode(`· ${m.latency.toFixed(1)}s`));
}

function chip(text, rgb, cls = "") {
  const c = document.createElement("span");
  c.className = `chip ${cls}`;
  if (rgb) c.style.setProperty("--c", rgb);
  c.textContent = text;
  return c;
}

// Same values as the body[data-mood] accents in styles.css.
const MOOD_RGB = {
  calm: "120 168 255", happy: "255 206 112", excited: "255 118 204", curious: "104 240 214", thoughtful: "176 152 255",
  empathetic: "255 160 178", serious: "196 210 232", playful: "172 248 120", surprised: "255 236 140",
};
const moodRgb = (m) => MOOD_RGB[m] || MOOD_RGB.calm;

function scrollTranscript() {
  els.list.scrollTop = els.list.scrollHeight;
}

function renderTranscriptChrome(newItem = false) {
  const has = els.list.children.length > 0;
  els.empty.hidden = has;
  els.copy.disabled = !has;
  els.clear.disabled = !has;
  if (newItem && !els.sheet.classList.contains("open")) els.transcriptBadge.hidden = false;
}

async function copyTranscript() {
  const lines = [...els.list.children].map((li) => {
    const who = li.classList.contains("you") ? "You" : "Cipher";
    const text = li.querySelector(".bubble").textContent.trim();
    return `${who}: ${text}${li.classList.contains("cut") ? " [interrupted]" : ""}`;
  });
  try {
    await navigator.clipboard.writeText(lines.join("\n\n"));
    els.copy.textContent = "Copied";
    els.copy.classList.add("done");
    setTimeout(() => {
      els.copy.textContent = "Copy";
      els.copy.classList.remove("done");
    }, 1600);
  } catch {
    toast({ title: "Couldn't copy", message: "Your browser blocked clipboard access.", kind: "warn" });
  }
}

function timeNow() {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function toggleSheet(force) {
  const open = force ?? !els.sheet.classList.contains("open");
  closePopovers();
  els.sheet.classList.toggle("open", open);
  els.sheet.setAttribute("aria-hidden", String(!open));
  els.sheet.inert = !open;
  els.transcriptBtn.setAttribute("aria-expanded", String(open));
  if (open) {
    els.transcriptBadge.hidden = true;
    scrollTranscript();
  }
}

// ---- mood / state / island -------------------------------------------------------------
function setMood(m) {
  if (!MOOD_LABEL[m]) return;
  const changed = m !== mood;
  mood = m;
  orb.setMood(m);
  document.body.dataset.mood = m;
  els.islandMood.textContent = MOOD_LABEL[m];
  if (changed) bump(els.island);
  renderIsland();
}

function setState(s) {
  state = s;
  orb.setState(s);
  document.body.dataset.state = s;
  renderAll();
}

let islandNotice = null;
let islandNoticeTimer = null;
function flashIsland(text) {
  islandNotice = text;
  clearTimeout(islandNoticeTimer);
  islandNoticeTimer = setTimeout(() => {
    islandNotice = null;
    renderIsland();
  }, 3500);
  renderIsland();
}

function islandLabel() {
  if (islandNotice) return islandNotice;
  if (!connected) return wasDisconnected ? "Reconnecting…" : "Connecting…";
  if (missingKeys?.length) return "Setup needed";
  if (starting) return "Starting mic…";
  if (state === "interrupted") return "Interrupted";
  if (state === "speaking") return "Speaking";
  if (state === "thinking") return "Thinking";
  if (!active) return "Ready";
  if (muted) return "Muted";
  if (waitingWake) return `Say “${wakePhrase}”`;
  return "Listening";
}

/** Update the island and animate its width to fit the new content. */
function renderIsland() {
  const label = islandLabel();
  const showMeta = !els.islandMeta.hidden && active && (state === "speaking" || state === "listening" || state === "idle");
  const metaVisible = els.islandMeta.dataset.visible === "true";
  if (els.islandState.textContent === label && showMeta === metaVisible) return;
  const island = els.island;
  const from = island.getBoundingClientRect().width;
  els.islandState.textContent = label;
  els.islandMeta.style.display = showMeta ? "" : "none";
  els.islandMeta.dataset.visible = String(showMeta);
  island.style.width = "auto";
  const to = island.getBoundingClientRect().width;
  island.style.width = `${from}px`;
  island.getBoundingClientRect(); // commit the start width
  island.style.width = `${to}px`;
}

function bump(el) {
  el.classList.remove("bump");
  void el.offsetWidth;
  el.classList.add("bump");
}

function pulse(el) {
  el.animate([{ transform: "translateX(0)" }, { transform: "translateX(-6px)" }, { transform: "translateX(6px)" }, { transform: "translateX(0)" }], {
    duration: 320,
    easing: "ease-in-out",
  });
}

// ---- render everything that depends on state -----------------------------------------
function renderAll() {
  const ready = connected && missingKeys !== null && !missingKeys.length;
  const b = document.body.dataset;
  b.active = String(active);
  b.ready = String(ready);
  b.muted = String(active && muted);
  b.conn = connected ? "online" : wasDisconnected ? "offline" : "connecting";
  b.captions = settings.captions ? "on" : "off";

  // Setup card
  if (missingKeys?.length) {
    els.keyList.replaceChildren(
      ...KEYS.map((k) => {
        const miss = missingKeys.includes(k.name);
        const li = document.createElement("li");
        li.className = miss ? "missing" : "ok";
        li.innerHTML = miss
          ? '<svg class="k-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5v5.5M12 16.5h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
          : '<svg class="k-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="currentColor" opacity=".2"/><path d="m8 12.5 2.7 2.7L16 9.8" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        const name = document.createElement("span");
        name.className = "k-name";
        name.textContent = k.name;
        const svc = document.createElement("span");
        svc.className = "k-svc";
        svc.textContent = k.service;
        li.append(name, svc);
        return li;
      }),
    );
    els.setup.hidden = false;
  } else {
    els.setup.hidden = true;
  }

  // Dock
  els.session.disabled = starting || (!active && !ready);
  els.sessionLabel.textContent = starting ? "Starting" : active ? "End" : "Start";
  const tip = active ? "End conversation" : "Start conversation";
  els.session.setAttribute("aria-label", tip);
  els.session.dataset.tip = tip;
  els.mute.disabled = !active;
  els.stop.disabled = !(active && claudeBusy());

  renderHint();
  renderIsland();
}

let hintKey = "";
const touchOnly = matchMedia("(pointer: coarse)").matches && !matchMedia("(pointer: fine)").matches;
function renderHint() {
  let html = "";
  if (missingKeys?.length || !connected) html = "";
  else if (!active) html = touchOnly ? "Tap the orb to start" : "Tap the orb or press <kbd>Space</kbd> to start";
  else if (muted) html = touchOnly ? "Microphone off" : "Microphone off · press <kbd>M</kbd> to unmute";
  else if (waitingWake && state !== "speaking" && state !== "thinking") html = `Say “${escapeHtml(wakePhrase)}” to talk`;
  else if (state === "speaking" || state === "thinking") html = touchOnly ? "Just start talking, or tap the orb, to interrupt" : "Just start talking, or press <kbd>Esc</kbd>, to interrupt";
  else if (state === "listening") html = "Listening…";
  else html = "Go ahead, I'm listening";
  if (html === hintKey) return;
  hintKey = html;
  els.hint.classList.add("swap");
  setTimeout(() => {
    if (hintKey !== html) return;
    els.hint.innerHTML = html;
    els.hint.classList.remove("swap");
  }, 160);
}

// ---- toasts ----------------------------------------------------------------------------
const ICONS = {
  warn: '<svg viewBox="0 0 24 24"><path d="M12 4 2.8 19.5h18.4L12 4Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 10v4.5M12 17.2h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  error: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5v5.5M12 16.5h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  ok: '<svg viewBox="0 0 24 24"><path d="m6 12.5 4 4L18 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};
function toast({ title, message = "", kind = "warn", timeout = 8000 }) {
  const key = `${title}|${message}`;
  const existing = [...els.toasts.children].find((t) => t.dataset.key === key);
  if (existing) {
    existing.animate([{ transform: "scale(1)" }, { transform: "scale(1.03)" }, { transform: "scale(1)" }], { duration: 300 });
    return;
  }
  const t = document.createElement("div");
  t.className = `toast glass ${kind}`;
  t.dataset.key = key;
  t.setAttribute("role", kind === "error" ? "alert" : "status");
  t.innerHTML = `<span class="toast-icon">${ICONS[kind] || ICONS.warn}</span><div class="toast-body"><div class="toast-title"></div><div class="toast-msg"></div></div><button class="toast-close" aria-label="Dismiss"><svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button>`;
  t.querySelector(".toast-title").textContent = title;
  t.querySelector(".toast-msg").textContent = message;
  if (!message) t.querySelector(".toast-msg").remove();
  const close = () => {
    if (t.classList.contains("out")) return;
    t.classList.add("out");
    setTimeout(() => t.remove(), 250);
  };
  t.querySelector(".toast-close").addEventListener("click", close);
  let timer = setTimeout(close, timeout);
  t.addEventListener("pointerenter", () => clearTimeout(timer));
  t.addEventListener("pointerleave", () => (timer = setTimeout(close, 3000)));
  els.toasts.append(t);
  while (els.toasts.children.length > 3) els.toasts.firstElementChild.remove();
}

// ---- popovers ----------------------------------------------------------------------------
const popovers = [
  { pop: els.settingsPop, btn: els.settingsBtn },
  { pop: els.helpPop, btn: els.helpBtn },
];
function togglePopover(pop, btn) {
  const open = pop.hidden;
  closePopovers();
  if (open) {
    pop.hidden = false;
    pop.classList.remove("closing");
    btn.setAttribute("aria-expanded", "true");
    if (pop === els.settingsPop) renderSettings();
  }
}
function closePopovers() {
  for (const { pop, btn } of popovers) {
    if (pop.hidden) continue;
    btn.setAttribute("aria-expanded", "false");
    pop.classList.add("closing");
    setTimeout(() => {
      if (pop.classList.contains("closing")) {
        pop.hidden = true;
        pop.classList.remove("closing");
      }
    }, 180);
  }
}

// ---- voice control of the app itself ------------------------------------------------------
// Cipher's app_control tool: the server asks, the page does it and confirms.
const repliesDone = new Set(); // turn ids whose speech has been fully sent
const SETTING_KEYS = {
  vision_model: ["vision", (v) => v],
  camera_stills: ["stills", (v) => v === "on"],
  captions: ["captions", (v) => v === "on"],
  floating_words: ["words", (v) => v === "on"],
  visual_effects: ["quality", (v) => v],
  interrupt_sensitivity: ["sensitivity", (v) => v],
};

/** Run `fn` once Cipher has finished saying this reply (so "goodbye" isn't cut off). */
function afterReply(turnId, fn) {
  const started = performance.now();
  const tick = () => {
    const finished = repliesDone.has(turnId) && !audio?.isPlaying;
    if (finished || performance.now() - started > 30_000) setTimeout(fn, 250);
    else setTimeout(tick, 150);
  };
  tick();
}

async function runAppCommand(cmd) {
  const reply = (ok, message) => send({ type: "app_command_result", id: cmd.id, ok, message });
  try {
    switch (cmd.action) {
      case "camera_on":
        if (!vision.on) await toggleCamera(true);
        return vision.on ? reply(true, "the camera is on") : reply(false, "the camera couldn't start (check the browser's camera permission)");
      case "camera_off":
        if (vision.on) await toggleCamera(false);
        return reply(true, "the camera is off");
      case "mute_microphone":
        afterReply(cmd.turnId, () => toggleMute(true));
        return reply(true, "the mic will mute as soon as you finish speaking");
      case "end_conversation":
        afterReply(cmd.turnId, () => endSession());
        return reply(true, "the conversation will end as soon as you finish speaking");
      case "new_conversation":
        afterReply(cmd.turnId, () => newConversation());
        return reply(true, "a new conversation will start as soon as you finish speaking");
      case "show_transcript":
        toggleSheet(true);
        return reply(true);
      case "hide_transcript":
        toggleSheet(false);
        return reply(true);
      case "open_settings":
        if (els.settingsPop.hidden) togglePopover(els.settingsPop, els.settingsBtn);
        return reply(true);
      case "close_panels":
        closePopovers();
        toggleSheet(false);
        return reply(true);
      case "change_setting": {
        const map = SETTING_KEYS[cmd.setting];
        if (!map) return reply(false, `unknown setting ${cmd.setting}`);
        settings[map[0]] = map[1](cmd.value);
        saveSettings();
        renderSettings();
        applySettings();
        flashIsland(`${cmd.setting.replace(/_/g, " ")}: ${cmd.value}`);
        return reply(true, `${cmd.setting.replace(/_/g, " ")} is now ${cmd.value}`);
      }
      default:
        return reply(false, `unknown action ${cmd.action}`);
    }
  } catch (err) {
    reply(false, String(err?.message || err));
  }
}

// ---- Mac permissions (Settings) -----------------------------------------------------------
const permsEls = { check: document.getElementById("permsCheck"), list: document.getElementById("permsList"), help: document.getElementById("permsHelp") };
async function permsCall(method, which = "") {
  const r = await fetch(`/api/permissions${which ? `/${which}` : ""}`, { method, headers: { "x-voice-orb": "1" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const j = await r.json();
  return j.status ?? j;
}
function renderPerms(status) {
  permsEls.list.hidden = false;
  let missing = false;
  for (const li of permsEls.list.children) {
    const ok = Boolean(status[li.dataset.perm]);
    li.classList.toggle("ok", ok);
    li.classList.toggle("no", !ok);
    missing ||= !ok;
  }
  permsEls.help.hidden = !missing;
}
permsEls.check.addEventListener("click", async () => {
  permsEls.check.textContent = "Checking…";
  try {
    renderPerms(await permsCall("GET"));
  } catch {
    toast({ title: "Couldn't check permissions", message: "Is the Cipher service running?", kind: "warn" });
  } finally {
    permsEls.check.textContent = "Check";
  }
});
document.getElementById("permsRestart").addEventListener("click", async () => {
  try {
    await fetch("/api/restart", { method: "POST", headers: { "x-voice-orb": "1" } });
    toast({ title: "Restarting Cipher", message: "It'll reconnect in a few seconds.", kind: "ok", timeout: 4000 });
  } catch {
    /* the page reconnects by itself */
  }
});
for (const li of permsEls.list.children) {
  li.querySelector("button").addEventListener("click", async () => {
    try {
      renderPerms(await permsCall("POST", li.dataset.perm));
    } catch {
      /* shown on next check */
    }
  });
}

// ---- performance report (for the server log, used by the diagnostic) ------------------------
const gpuName = (() => {
  try {
    const gl = document.createElement("canvas").getContext("webgl");
    const ext = gl?.getExtension("WEBGL_debug_renderer_info");
    return String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl?.getParameter(gl.RENDERER) || "unknown").slice(0, 120);
  } catch {
    return "unknown";
  }
})();
setInterval(() => {
  if (document.hidden) return;
  const orbPerf = globalThis.__orbPerf || {};
  send({
    type: "perf",
    fps: Math.round(orb?.fpsAvg ?? 0),
    level: orbPerf.level ?? 0,
    gpu: gpuName,
    camera: vision.on ? `${vision.status}${vision.lastMs ? ` ${vision.lastMs}ms` : ""}` : "off",
    screen: `${screen.width}x${screen.height}@${devicePixelRatio}`,
  });
}, 30_000);

// ---- installable web app ----------------------------------------------------------------
if ("serviceWorker" in navigator && window.isSecureContext && !new URLSearchParams(location.search).has("demo")) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// ---- updates ----------------------------------------------------------------------------
// After the app is updated and the server restarted, this page reconnects on its own but
// would keep running its old code. Reload to pick up the new version: straight away when
// idle, or as soon as the current conversation ends.
let appVersion = null;
let reloadPending = false;
function checkVersion(version) {
  if (!version) return;
  if (!appVersion) appVersion = version;
  if (version === appVersion || reloadPending) return;
  if (!active) return location.reload();
  reloadPending = true;
  toast({ title: "Cipher was updated", message: "It will refresh when you end this conversation.", kind: "ok", timeout: 6000 });
}

// ---- camera stills for Cipher -----------------------------------------------------------
// While the camera is on, the server always holds a recent still, attached to whatever you
// say next. Kept only for that reply, never stored. Three moments matter:
//   - a steady one every couple of seconds, so there is always something recent
//   - the moment you start talking: what you're holding up as you say "what's this?"
//   - the moment you pause: what the camera sees as you finish, which is what gets answered
// If the view changed in between (you showed something, then put it down), the picture
// from when you started is sent along too, so both are seen.
const STILL_EVERY_MS = 2000;
const STILL_CHANGED = 14; // fingerprint difference (0–255) that counts as a different view
const STILL_START_KEEP_MS = 12_000; // how long a "when you started" picture stays relevant
const stillAt = { start: null, sent: 0 };

function sendStill(moment = "tick") {
  if (!active || !settings.stills || !vision.on || document.hidden) return;
  const now = performance.now();
  if (stillAt.start && now - stillAt.start.at > STILL_START_KEEP_MS) stillAt.start = null;
  // The steady tick stands down while you're mid-sentence: onset and pause stills cover that.
  if (moment === "tick" && now - stillAt.sent < STILL_EVERY_MS - 100) return;
  const shot = vision.snapshot();
  if (!shot) return;
  stillAt.sent = now;
  if (moment === "start") {
    // Smaller copy of the opening view, only used if the view has changed by the time you finish.
    if (!stillAt.start) stillAt.start = { sig: shot.sig, jpeg: vision.snapshot(640, 0.72)?.jpeg ?? null, at: now };
    return send({ type: "vision_still", jpeg: shot.jpeg, moment });
  }
  const start = stillAt.start;
  const changed = start?.jpeg && sceneChange(start.sig, shot.sig) >= STILL_CHANGED;
  send({ type: "vision_still", jpeg: shot.jpeg, moment, ...(changed ? { earlier: start.jpeg, earlierAgoMs: Math.round(now - start.at) } : {}) });
}
/** A reply has begun: the next thing you say starts a new "when you started" picture. */
function stillTurnBegan() {
  stillAt.start = null;
}
setInterval(sendStill, STILL_EVERY_MS);

// ---- memory -----------------------------------------------------------------------------
let memoryState = null; // { enabled, items: [{ id, text, at }] } from the server
const memoryEls = {
  toggle: document.getElementById("memoryToggle"),
  list: document.getElementById("memoryList"),
  count: document.getElementById("memoryCount"),
  clear: document.getElementById("memoryClear"),
};

function renderMemory(fresh = []) {
  const m = memoryState;
  if (!m) return;
  memoryEls.toggle.checked = m.enabled;
  memoryEls.count.textContent = m.items.length ? String(m.items.length) : "";
  memoryEls.clear.hidden = !m.items.length;
  const items = [...m.items].reverse(); // newest first
  memoryEls.list.replaceChildren(
    ...items.map((item) => {
      const li = document.createElement("li");
      if (fresh.includes(item.text)) li.classList.add("fresh");
      const text = document.createElement("span");
      text.textContent = item.text;
      const del = document.createElement("button");
      del.setAttribute("aria-label", `Forget: ${item.text}`);
      del.innerHTML = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
      del.addEventListener("click", () => send({ type: "memory_delete", id: item.id }));
      li.append(text, del);
      return li;
    }),
  );
}

memoryEls.toggle.addEventListener("change", () => send({ type: "memory_enabled", enabled: memoryEls.toggle.checked }));
memoryEls.clear.addEventListener("click", () => {
  if (!confirm("Forget everything Cipher remembers about you? This can't be undone.")) return;
  send({ type: "memory_clear" });
});

// ---- Mac control ------------------------------------------------------------------------
let macMode = "ask";
const MAC_HELP = {
  off: "Cipher can't touch your Mac or Chrome.",
  ask: "Looking around and reading pages runs straight away. Anything that changes something waits for your OK.",
  full: "Cipher acts without asking, except sending, buying, deleting or shutting down. Passwords, sudo, calendars and task apps stay blocked.",
};

let chromeConnected = false;
function renderChrome({ connected, code }) {
  const box = document.querySelector(".chrome-ext");
  const was = chromeConnected;
  chromeConnected = connected;
  box.classList.toggle("on", connected);
  document.getElementById("chromeStatus").textContent = connected ? "Chrome extension: connected" : "Chrome extension: not connected";
  document.getElementById("chromeCode").textContent = code || "";
  if (connected && !was) {
    document.getElementById("chromeSetup").open = false;
    flashIsland("Chrome connected");
  }
}
document.getElementById("chromeCopy").addEventListener("click", async () => {
  const code = document.getElementById("chromeCode").textContent;
  try {
    await navigator.clipboard.writeText(code);
    toast({ title: "Pairing code copied", message: "Paste it into the Cipher Bridge extension.", kind: "ok", timeout: 2500 });
  } catch {
    toast({ title: "Couldn't copy", message: "Select the code and copy it by hand.", kind: "warn" });
  }
});
const macEls = {
  seg: document.getElementById("macMode"),
  help: document.getElementById("macHelp"),
  card: document.getElementById("approval"),
  purpose: document.getElementById("approvalPurpose"),
  reason: document.getElementById("approvalReason"),
  command: document.getElementById("approvalCommand"),
  allow: document.getElementById("approvalAllow"),
  deny: document.getElementById("approvalDeny"),
};
const actionRows = new Map(); // action id -> transcript row

function renderMac() {
  macEls.help.textContent = MAC_HELP[macMode] || "";
  if (!els.settingsPop.hidden) renderSettings();
}

macEls.seg.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b || b.dataset.value === macMode) return;
  if (b.dataset.value === "full") {
    send({ type: "mac_mode", mode: "full" }); // the server replies asking for confirmation
    return;
  }
  macMode = b.dataset.value;
  send({ type: "mac_mode", mode: macMode });
  renderMac();
});

const ACTION_LABEL = { running: "", done: "", failed: "Failed: ", blocked: "Blocked: ", needs_approval: "Waiting for your OK: " };

function onAction(a) {
  if (cutTurns.has(a.turnId)) return;
  const what = a.purpose || (a.kind === "take_screenshot" ? "look at your screen" : "use your Mac");
  let row = actionRows.get(a.id);
  if (!row) {
    row = document.createElement("li");
    row.className = "msg action";
    row.innerHTML = '<span class="act-dot" aria-hidden="true"></span><span class="act-text"></span>';
    els.list.append(row);
    actionRows.set(a.id, row);
  }
  row.dataset.status = a.status;
  const text = row.querySelector(".act-text");
  text.textContent = `${ACTION_LABEL[a.status] ?? ""}${what} `;
  if (a.command) {
    const code = document.createElement("code");
    code.textContent = a.kind === "run_applescript" ? "AppleScript" : a.kind === "app_control" ? "" : a.command.split("\n")[0].slice(0, 80);
    text.append(code);
  }
  row.title = [a.command, a.detail].filter(Boolean).join("\n\n");
  scrollTranscript();
  if (a.kind === "job") {
    // A background job: one row that follows it from start to finish.
    text.textContent = `${a.status === "running" ? "In the background: " : a.status === "done" ? "Finished: " : "Stopped: "}${what} `;
    if (a.status === "running" && a.detail) {
      const now = document.createElement("code");
      now.textContent = a.detail.slice(0, 80);
      text.append(now);
    }
    if (a.status === "running" && row.dataset.flashed) return;
    row.dataset.flashed = "1";
  }
  if (a.status === "running") flashIsland(what.charAt(0).toUpperCase() + what.slice(1));
  if (a.status === "needs_approval") showApproval(a, what);
}

function showApproval(a, what) {
  macEls.purpose.textContent = what;
  macEls.reason.textContent = `Needs your OK because ${a.detail || "it changes something on your Mac"}.`;
  macEls.command.textContent = a.kind === "run_command" ? `$ ${a.command}` : a.command;
  macEls.card.hidden = false;
  macEls.allow.focus({ preventScroll: true });
}
function hideApproval() {
  macEls.card.hidden = true;
}
macEls.allow.addEventListener("click", () => {
  hideApproval();
  send({ type: "say", text: "Yes, go ahead." });
});
macEls.deny.addEventListener("click", () => {
  hideApproval();
  send({ type: "say", text: "No, don't do that." });
});
renderMac();

// ---- settings UI ------------------------------------------------------------------------
function renderSettings() {
  for (const seg of document.querySelectorAll(".segmented")) {
    if (!seg.dataset.setting && seg.id !== "macMode") continue; // listening controls render themselves
    const key = seg.dataset.setting;
    const value = seg.id === "macMode" ? macMode : settings[key];
    const buttons = [...seg.querySelectorAll("button")];
    const idx = Math.max(0, buttons.findIndex((b) => b.dataset.value === value));
    buttons.forEach((b, i) => b.setAttribute("aria-checked", String(i === idx)));
    const thumb = seg.querySelector(".seg-thumb");
    thumb.style.width = `calc((100% - 4px) / ${buttons.length})`;
    thumb.style.transform = `translateX(${idx * 100}%)`;
  }
  for (const sw of document.querySelectorAll(".switch[data-setting]")) sw.checked = Boolean(settings[sw.dataset.setting]);
  renderListening();
}

function applySettings() {
  orb.setQuality?.(settings.quality);
  orb.setWordsEnabled?.(settings.words);
  if (!VISION_MODELS[settings.vision]) settings.vision = "fast";
  if (!settings.stills) send({ type: "vision_still", jpeg: null }); // drop any still the server holds
  vision.setModel(settings.vision);
  renderAll();
}

for (const seg of document.querySelectorAll(".segmented[data-setting]")) {
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    settings[seg.dataset.setting] = b.dataset.value;
    saveSettings();
    renderSettings();
    applySettings();
  });
}
for (const sw of document.querySelectorAll(".switch[data-setting]")) {
  sw.addEventListener("change", () => {
    settings[sw.dataset.setting] = sw.checked;
    saveSettings();
    applySettings();
  });
}

// ---- listening: noise filter, wake word, voice match -------------------------------

function escapeHtml(t) {
  return String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const lx = {
  wakeToggle: $("wakeToggle"),
  wakeRow: $("wakeRow"),
  wakePhrase: $("wakePhrase"),
  wakeAwake: $("wakeAwake"),
  focusToggle: $("focusToggle"),
  focusRow: $("focusRow"),
  voiceToggle: $("voiceToggle"),
  voiceRow: $("voiceRow"),
  voiceStrict: $("voiceStrict"),
  voiceEnroll: $("voiceEnrollBtn"),
  voiceForget: $("voiceForgetBtn"),
  voiceHelp: $("voiceHelp"),
  enroll: $("enroll"),
  enrollBar: $("enrollBar"),
  enrollDone: $("enrollDone"),
  enrollCancel: $("enrollCancel"),
};

function setSegmented(seg, value) {
  const buttons = [...seg.querySelectorAll("button")];
  const idx = Math.max(0, buttons.findIndex((b) => b.dataset.value === String(value)));
  buttons.forEach((b, i) => b.setAttribute("aria-checked", String(i === idx)));
  const thumb = seg.querySelector(".seg-thumb");
  thumb.style.width = `calc((100% - 4px) / ${buttons.length})`;
  thumb.style.transform = `translateX(${idx * 100}%)`;
}

const VOICE_HELP = "Answers only you: other people and the TV are ignored. Read three sentences once so it learns your voice. Kept only on this Mac.";
function renderListening() {
  const s = listenState;
  if (!s) return;
  lx.wakeToggle.checked = s.wakeWord;
  lx.wakeRow.dataset.off = String(!s.wakeWord);
  if (document.activeElement !== lx.wakePhrase) lx.wakePhrase.value = s.wakePhrase;
  wakePhrase = s.wakePhrase;
  setSegmented(lx.wakeAwake, [10, 15, 30, 60].includes(s.awakeSeconds) ? s.awakeSeconds : 15);
  lx.focusToggle.checked = s.focusSpeaker !== false;
  lx.focusRow.dataset.off = String(!s.wakeWord);
  lx.focusToggle.disabled = !s.wakeWord;
  lx.voiceToggle.checked = s.voiceMatch;
  lx.voiceRow.dataset.off = String(!s.voiceMatch && !s.enrolled);
  setSegmented(lx.voiceStrict, s.strictness);
  lx.voiceEnroll.textContent = s.enrolled ? "Re-record my voice" : "Teach it my voice";
  lx.voiceForget.hidden = !s.enrolled;
  let help = VOICE_HELP;
  if (s.model === "loading") help = "Loading the voice model (about 100 MB, downloaded once)…";
  else if (s.model === "failed") help = s.modelError || "The voice model couldn't load.";
  else if (s.voiceMatch && !s.enrolled) help = "Click “Teach it my voice” and read three sentences. Until then it answers anyone.";
  else if (s.voiceMatch && s.enrolled) help = "On: only your voice gets answers. If it ignores you, choose Relaxed or re-record.";
  lx.voiceHelp.textContent = help;
}

const sendListening = (patch) => send({ type: "listening", settings: patch });
lx.wakeToggle.addEventListener("change", () => sendListening({ wakeWord: lx.wakeToggle.checked, wakePhrase: lx.wakePhrase.value.trim() || "Cipher" }));
lx.focusToggle.addEventListener("change", () => sendListening({ focusSpeaker: lx.focusToggle.checked }));
lx.wakePhrase.addEventListener("change", () => {
  const p = lx.wakePhrase.value.trim();
  if (p) sendListening({ wakePhrase: p });
  else lx.wakePhrase.value = listenState?.wakePhrase || "Cipher";
});
lx.wakePhrase.addEventListener("keydown", (e) => {
  e.stopPropagation(); // typing here isn't a keyboard shortcut
  if (e.key === "Enter") lx.wakePhrase.blur();
});
lx.wakeAwake.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) sendListening({ awakeSeconds: Number(b.dataset.value) });
});
lx.voiceToggle.addEventListener("change", () => {
  sendListening({ voiceMatch: lx.voiceToggle.checked });
  if (lx.voiceToggle.checked && !listenState?.enrolled) startEnroll();
});
lx.voiceStrict.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) sendListening({ strictness: b.dataset.value });
});
lx.voiceForget.addEventListener("click", () => {
  send({ type: "voice_enroll", action: "forget" });
  sendListening({ voiceMatch: false });
  toast({ title: "Voice forgotten", message: "Your voiceprint was deleted. It answers anyone again.", kind: "ok", timeout: 3000 });
});
lx.voiceEnroll.addEventListener("click", () => startEnroll());

let enrollTimer = null;
let enrollStart = 0;
const ENROLL_MS = 20000;
async function startEnroll() {
  if (!active) await startSession();
  if (!active) return;
  if (muted) toggleMute(false);
  closePopovers();
  send({ type: "voice_enroll", action: "start" });
}
function stopEnroll(action) {
  clearInterval(enrollTimer);
  enrollTimer = null;
  lx.enroll.hidden = true;
  send({ type: "voice_enroll", action });
}
function onEnroll(msg) {
  if (msg.state === "recording") {
    lx.enroll.hidden = false;
    lx.enrollDone.disabled = false;
    enrollStart = performance.now();
    lx.enrollBar.style.width = "0%";
    clearInterval(enrollTimer);
    enrollTimer = setInterval(() => {
      const f = (performance.now() - enrollStart) / ENROLL_MS;
      lx.enrollBar.style.width = `${Math.min(100, f * 100)}%`;
      if (f >= 1) stopEnroll("stop");
    }, 200);
  } else if (msg.state === "working") {
    flashIsland("Learning your voice…");
  } else if (msg.state === "done") {
    toast({ title: "Voice learned", message: msg.message, kind: "ok", timeout: 4000 });
  } else if (msg.state === "error") {
    lx.enroll.hidden = true;
    clearInterval(enrollTimer);
    toast({ title: "Voice match", message: msg.message, kind: "warn" });
  }
}
lx.enrollDone.addEventListener("click", () => stopEnroll("stop"));
lx.enrollCancel.addEventListener("click", () => stopEnroll("cancel"));

// Noise filter: restart the microphone so the change applies now.
document.querySelector('.switch[data-setting="noiseFilter"]').addEventListener("change", async () => {
  if (!active || starting) return;
  if (claudeBusy() && currentTurnId) interrupt();
  await endSession();
  await startSession();
  flashIsland(settings.noiseFilter ? (audio?.noiseFilter ? "Noise filter on" : "Noise filter unavailable") : "Noise filter off");
});

// ---- camera: on-device object detection (transformers.js) ---------------------------
const vision = new Vision({
  video: els.camVideo,
  overlay: els.camOverlay,
  onStatus: renderCamera,
  onScene(objects) {
    send({ type: "vision", enabled: true, objects });
    renderSees(objects);
  },
  onAppear(o) {
    orb.see?.(o.label, o.x, o.y);
  },
});
let camBusy = false;
let camErrorShown = false;

async function toggleCamera(force) {
  const on = force ?? !vision.on;
  if (on === vision.on || camBusy) return;
  if (!on) {
    vision.stop();
    send({ type: "vision", enabled: false });
    els.camTile.classList.add("closing");
    setTimeout(() => {
      if (!vision.on) {
        els.camTile.hidden = true;
        els.camTile.classList.remove("closing");
      }
    }, 280);
    flashIsland("Camera off");
    return;
  }
  camBusy = true;
  camErrorShown = false;
  els.camTile.classList.remove("closing");
  els.camTile.hidden = false;
  try {
    await vision.start(settings.vision);
    const v = els.camVideo;
    if (v.videoWidth) els.camTile.style.setProperty("--cam-aspect", `${v.videoWidth} / ${v.videoHeight}`);
    send({ type: "vision", enabled: true });
    flashIsland("Camera on");
  } catch (err) {
    vision.stop();
    els.camTile.hidden = true;
    const name = err?.name;
    toast(
      name === "NotAllowedError"
        ? { title: "Camera blocked", message: "Allow camera access for this site in your browser's address bar, then try again.", kind: "error" }
        : name === "NotFoundError" || name === "OverconstrainedError"
          ? { title: "No camera found", message: "Connect a camera and try again.", kind: "error" }
          : name === "NotReadableError"
            ? { title: "Camera busy", message: "Another app is using the camera. Close it and try again.", kind: "error" }
            : { title: "Camera unavailable", message: err?.message || String(err), kind: "error" },
    );
  } finally {
    camBusy = false;
    renderCamera({ status: vision.status });
  }
}

function renderCamera(s) {
  const on = vision.on;
  els.camera.setAttribute("aria-pressed", String(on));
  els.camera.setAttribute("aria-label", on ? "Turn camera off" : "Turn camera on");
  els.camera.dataset.tip = on ? "Camera off" : "Camera";
  document.body.dataset.camera = on ? "on" : "off";
  els.camTile.dataset.status = s.status;

  const loading = s.status === "starting" || s.status === "loading";
  els.camLoading.hidden = !loading;
  if (s.status === "starting") {
    els.camLoadingText.textContent = "Starting camera";
    els.camBar.style.width = "0%";
    els.camSees.textContent = "Starting camera…";
  } else if (s.status === "loading") {
    const pct = Math.round((s.progress || 0) * 100);
    const m = VISION_MODELS[vision.model];
    els.camLoadingText.textContent = pct >= 100 ? "Warming up" : pct > 0 ? `Downloading ${m.label} · ${pct}%` : "Loading vision model";
    els.camBar.style.width = `${pct}%`;
    els.camSees.textContent = "Loading vision model…";
    els.camMs.textContent = "";
  } else if (s.status === "live") {
    if (s.ms != null) els.camMs.textContent = `${s.ms} ms`;
    if (els.camSees.textContent.endsWith("…")) els.camSees.textContent = "Looking…";
  } else if (s.status === "error") {
    els.camSees.textContent = "Vision model error";
    if (!camErrorShown) {
      camErrorShown = true;
      toast({ title: "Vision", message: s.message || "Object detection failed.", kind: "error" });
    }
  }
}

function plural(label) {
  if (label === "person") return "people";
  if (label === "mouse") return "mice";
  if (label === "knife") return "knives";
  if (/(s|sh|ch|x)$/.test(label)) return label + "es";
  return label + "s";
}

function renderSees(objects) {
  const counts = new Map();
  for (const o of objects) counts.set(o.label, (counts.get(o.label) || 0) + 1);
  if (!counts.size) {
    els.camSees.textContent = "Nothing recognised";
    return;
  }
  const parts = [document.createTextNode("Sees ")];
  [...counts].forEach(([label, n], i) => {
    if (i) parts.push(document.createTextNode(", "));
    const b = document.createElement("b");
    b.textContent = n > 1 ? `${n} ${plural(label)}` : label;
    parts.push(b);
  });
  els.camSees.replaceChildren(...parts);
}

els.camera.addEventListener("click", () => toggleCamera());

// ---- tooltips ------------------------------------------------------------------------------
let tipTimer = null;
let tipWarmUntil = 0;
function showTip(el) {
  const text = el.dataset.tip;
  if (!text || el.disabled) return;
  const tip = els.tooltip;
  tip.innerHTML = "";
  tip.append(document.createTextNode(text));
  if (el.dataset.key) {
    const k = document.createElement("kbd");
    k.textContent = el.dataset.key;
    tip.append(k);
  }
  tip.hidden = false;
  const r = el.getBoundingClientRect();
  const t = tip.getBoundingClientRect();
  const below = r.top < 120;
  const left = Math.min(innerWidth - t.width - 8, Math.max(8, r.left + r.width / 2 - t.width / 2));
  tip.style.left = `${left}px`;
  tip.style.top = `${below ? r.bottom + 10 : r.top - t.height - 10}px`;
}
function hideTip() {
  clearTimeout(tipTimer);
  if (!els.tooltip.hidden) tipWarmUntil = performance.now() + 400;
  els.tooltip.hidden = true;
}
for (const el of document.querySelectorAll("[data-tip]")) {
  el.addEventListener("pointerenter", (e) => {
    if (e.pointerType !== "mouse") return;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => showTip(el), performance.now() < tipWarmUntil ? 0 : 550);
  });
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("pointerdown", hideTip);
  el.addEventListener("focus", () => el.matches(":focus-visible") && showTip(el));
  el.addEventListener("blur", hideTip);
}

// ---- live mic level on the mute button ---------------------------------------------
function levelLoop() {
  const lvl = active && !muted && audio && !audio.isPlaying ? Math.min(1, audio.levelIn() * 9) : 0;
  els.mute.style.setProperty("--mic", lvl.toFixed(3));
  const busy = active && claudeBusy();
  if (els.stop.disabled === busy) els.stop.disabled = !busy;
  requestAnimationFrame(levelLoop);
}

// ---- wiring --------------------------------------------------------------------------------
els.session.addEventListener("click", () => (active ? endSession() : startSession()));
els.mute.addEventListener("click", () => toggleMute());
els.stop.addEventListener("click", () => claudeBusy() && interrupt());
els.transcriptBtn.addEventListener("click", () => toggleSheet());
els.closeSheet.addEventListener("click", () => toggleSheet(false));
els.copy.addEventListener("click", copyTranscript);
els.clear.addEventListener("click", newConversation);
els.newChat.addEventListener("click", newConversation);
els.settingsBtn.addEventListener("click", () => togglePopover(els.settingsPop, els.settingsBtn));
els.helpBtn.addEventListener("click", () => togglePopover(els.helpPop, els.helpBtn));

// Close popovers when clicking elsewhere.
document.addEventListener("pointerdown", (e) => {
  if (e.target.closest(".popover, #settingsBtn, #helpBtn")) return;
  closePopovers();
});

// Tap the orb: start a conversation, or cut Cipher off.
orb.onTap = () => {
  if (!active) startSession();
  else if (claudeBusy()) interrupt();
};

let spaceHandled = false;
addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
  const key = e.key;
  if (key === " " || e.code === "Space") {
    e.preventDefault();
    if (e.repeat) return;
    spaceHandled = true;
    active ? endSession() : startSession();
  } else if (key === "Escape") {
    const anyPop = popovers.some(({ pop }) => !pop.hidden);
    if (anyPop) closePopovers();
    else if (els.sheet.classList.contains("open")) toggleSheet(false);
    else if (active && claudeBusy()) interrupt();
  } else if (key === "m" || key === "M") {
    toggleMute();
  } else if (key === "v" || key === "V") {
    toggleCamera();
  } else if (key === "t" || key === "T") {
    toggleSheet();
  } else if (key === ",") {
    togglePopover(els.settingsPop, els.settingsBtn);
  } else if (key === "?" || key === "/") {
    togglePopover(els.helpPop, els.helpBtn);
  }
});
// Stop a focused button from also "clicking" on Space release.
addEventListener("keyup", (e) => {
  if ((e.key === " " || e.code === "Space") && spaceHandled) {
    e.preventDefault();
    spaceHandled = false;
  }
});

// Release the mic and server resources promptly when the tab closes.
addEventListener("pagehide", () => {
  send({ type: "stop" });
  vision.stop();
});

renderSettings();
applySettings();
renderTranscriptChrome();
setState("idle");
setMood("calm");
connect();
requestAnimationFrame(levelLoop);

// ---- demo: open /?demo to watch a scripted conversation ------------------------------
const demoMode = new URLSearchParams(location.search).get("demo");
if (demoMode !== null) runDemo();

async function runDemo() {
  window.__orb = orb; // handy for poking at the orb from the console
  window.__demo = { vision, renderCamera, renderSees, camTile: els.camTile, setState, setMood, toast, toggleSheet, onJson, setLatency, appendAssistantWord, interrupt, togglePopover: () => togglePopover(els.settingsPop, els.settingsBtn) };
  if (demoMode === "manual") return;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let fake = 0;
  let turn = 100;
  orb.setLevelSource(() => fake);
  orb.setSpectrumSource((out) => {
    for (let i = 0; i < out.length; i++) out[i] = fake * 6 * Math.max(0, 1 - i / out.length) * (0.5 + Math.random() * 0.7);
    return out;
  });
  const user = async (text) => {
    setState("listening");
    const list = text.split(" ");
    for (let i = 1; i <= list.length; i++) {
      onJson({ type: "transcript", text: list.slice(0, i).join(" "), final: false });
      fake = 0.05 + Math.random() * 0.05;
      await sleep(260);
    }
    fake = 0;
    onJson({ type: "user_turn", text });
  };
  const claude = async (text, m, cutAfter = 0) => {
    const id = ++turn;
    onJson({ type: "thinking", turnId: id });
    await sleep(900);
    onJson({ type: "mood", turnId: id, mood: m });
    onJson({ type: "assistant_delta", turnId: id, text });
    onJson({ type: "assistant_done", turnId: id });
    setState("speaking");
    setLatency(id, 0.9 + Math.random() * 0.5);
    const n = cutAfter || words(text).length;
    for (let i = 0; i < n; i++) {
      fake = 0.06 + Math.random() * 0.07;
      await sleep(WORD_MS);
    }
    fake = 0;
    if (cutAfter) {
      interrupt(id, true);
      await sleep(500);
    } else {
      flushAssistantWords();
      setState("idle");
    }
  };
  for (;;) {
    setState("idle");
    await sleep(1400);
    await user("What's the coolest thing about black holes?");
    await claude("Honestly, time itself slows down near them. Get close enough and the rest of the universe fast-forwards.", "excited");
    await sleep(600);
    await user("I've had a rough week, to be honest.");
    await claude("I'm sorry to hear that. Do you want to talk about what made it so hard?", "empathetic");
    await sleep(600);
    await user("Tell me a riddle");
    await claude("Sure. What has keys but can't open a single lock, and makes music when you", "playful", 9);
    await user("A piano!");
    await claude("You got it, and fast. Want a harder one?", "happy");
    await sleep(1200);
  }
}
