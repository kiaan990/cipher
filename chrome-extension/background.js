// Cipher Bridge: connects this Chrome to the Cipher app running on this Mac
// (ws://127.0.0.1:<port>/ext) and carries out its requests: list tabs, open pages,
// read them, click, type, scroll, screenshot. Every request comes from the app's
// server, which checks with the user before anything that sends, buys or deletes.

const KEEPALIVE_MS = 20_000;
let ws = null;
let keepalive = null;
/** The tab Claude is working in (the last one it opened or used). */
let workTab = null;

// ---- connection --------------------------------------------------------------------------

async function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
  let { code } = await chrome.storage.local.get("code");
  if (!parseCode(code)) {
    // Loaded from the voice-orb folder on this Mac: the app leaves its pairing code
    // next to the extension, so there's nothing to paste.
    try {
      code = (await (await fetch(chrome.runtime.getURL("pairing.json"))).json()).code;
      if (parseCode(code)) await chrome.storage.local.set({ code });
    } catch {
      /* no file: the user pastes the code in the popup */
    }
  }
  const parsed = parseCode(code);
  if (!parsed) return setStatus("needs_code", "No pairing code. Paste it below.");
  setStatus("connecting");
  // First check the app is reachable at all, so the popup can say what's wrong.
  try {
    const r = await fetch(`http://127.0.0.1:${parsed.port}/api/status`, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (err) {
    return setStatus("unreachable", `Can't reach the app at 127.0.0.1:${parsed.port} (${err?.message || err}). Is npm start running?`);
  }
  const sock = new WebSocket(`ws://127.0.0.1:${parsed.port}/ext?token=${encodeURIComponent(parsed.token)}`);
  ws = sock;
  sock.onopen = () => {
    setStatus("connected");
    sock.send(JSON.stringify({ type: "hello", version: chrome.runtime.getManifest().version }));
    clearInterval(keepalive);
    // Messages keep the extension's service worker awake while connected.
    keepalive = setInterval(() => sock.readyState === WebSocket.OPEN && sock.send(JSON.stringify({ type: "ping" })), KEEPALIVE_MS);
  };
  sock.onmessage = async (e) => {
    let msg;
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }
    if (msg.type !== "cmd") return;
    let reply;
    try {
      reply = { type: "result", id: msg.id, ok: true, result: await handle(msg.cmd, msg.args || {}) };
    } catch (err) {
      reply = { type: "result", id: msg.id, ok: false, error: String(err?.message || err) };
    }
    if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify(reply));
  };
  sock.onclose = (e) => {
    if (ws === sock) ws = null;
    clearInterval(keepalive);
    setStatus("disconnected", e.code === 1006 ? "The app refused the connection. The pairing code may be wrong: copy it again from Settings." : `Closed (${e.code}).`);
  };
  sock.onerror = () => {};
}

/** Pairing code from the app's Settings: "<port>-<token>". */
function parseCode(code) {
  const m = /^\s*(\d{2,5})-([a-f0-9]{32,64})\s*$/i.exec(code || "");
  return m ? { port: Number(m[1]), token: m[2] } : null;
}

async function setStatus(status, detail = "") {
  await chrome.storage.local.set({ status, detail, statusAt: Date.now() });
  chrome.action.setBadgeText({ text: status === "connected" ? "ON" : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#34d399" });
}

chrome.runtime.onInstalled.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => a.name === "reconnect" && connect());
chrome.storage.onChanged.addListener((changes) => {
  if (changes.code) {
    try {
      ws?.close();
    } catch {
      /* closed */
    }
    ws = null;
    connect();
  }
});
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "reconnect") connect();
});
connect();

// ---- commands ----------------------------------------------------------------------------

async function handle(cmd, args) {
  switch (cmd) {
    case "tabs": {
      const tabs = await chrome.tabs.query({});
      return tabs
        .filter((t) => !isOrbPage(t.url))
        .map((t) => ({ id: t.id, title: t.title, url: t.url, active: t.active, working: t.id === workTab }));
    }
    case "open": {
      const url = String(args.url || "");
      if (!/^https?:\/\//i.test(url)) throw new Error("Only http and https addresses can be opened.");
      let tab;
      if (args.tabId || (args.sameTab && workTab)) {
        tab = await chrome.tabs.update(await tabFor(args), { url });
      } else {
        // In the background, so the Cipher page stays in front.
        tab = await chrome.tabs.create({ url, active: Boolean(args.show) });
      }
      workTab = tab.id;
      await waitForLoad(tab.id);
      const t = await chrome.tabs.get(tab.id);
      return { tabId: t.id, title: t.title, url: t.url };
    }
    case "read": {
      const tabId = await tabFor(args);
      workTab = tabId;
      return { tabId, ...(await inPage(tabId, snapshotPage, [Number(args.maxChars) || 12000])) };
    }
    case "click": {
      const tabId = await tabFor(args);
      const r = await inPage(tabId, clickRef, [Number(args.ref)]);
      await sleep(700);
      await waitForLoad(tabId);
      return r;
    }
    case "type": {
      const tabId = await tabFor(args);
      const r = await inPage(tabId, typeRef, [Number(args.ref), String(args.text ?? ""), Boolean(args.submit)]);
      if (args.submit) {
        await sleep(700);
        await waitForLoad(tabId);
      }
      return r;
    }
    case "scroll": {
      const tabId = await tabFor(args);
      return inPage(tabId, scrollPage, [args.direction === "up" ? "up" : "down"]);
    }
    case "back": {
      const tabId = await tabFor(args);
      await chrome.tabs.goBack(tabId);
      await waitForLoad(tabId);
      return { ok: true };
    }
    case "show": {
      const tabId = await tabFor(args);
      const t = await chrome.tabs.update(tabId, { active: true });
      await chrome.windows.update(t.windowId, { focused: true });
      return { ok: true };
    }
    case "screenshot": {
      const tabId = await tabFor(args);
      const t = await chrome.tabs.get(tabId);
      if (!t.active) throw new Error("That tab is in the background, so it can't be captured. Use browser_read instead, or browser_show first.");
      const dataUrl = await chrome.tabs.captureVisibleTab(t.windowId, { format: "jpeg", quality: 70 });
      return { tabId, jpeg: await shrink(dataUrl, 1280) };
    }
    default:
      throw new Error(`Unknown command ${cmd}`);
  }
}

function isOrbPage(url) {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(url || "");
}

/** The tab to act on: the one asked for, else Claude's working tab, else the tab you're looking at. */
async function tabFor(args) {
  if (args.tabId) return Number(args.tabId);
  if (workTab) {
    try {
      await chrome.tabs.get(workTab);
      return workTab;
    } catch {
      workTab = null;
    }
  }
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (active && !isOrbPage(active.url)) return active.id;
  throw new Error("No tab to work in. Open a page first with browser_open.");
}

async function inPage(tabId, func, args) {
  const [res] = await chrome.scripting.executeScript({ target: { tabId }, func, args });
  const r = res?.result;
  if (r?.error) throw new Error(r.error);
  return r;
}

async function waitForLoad(tabId, timeoutMs = 10_000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const t = await chrome.tabs.get(tabId).catch(() => null);
    if (!t || t.status === "complete") break;
    await sleep(150);
  }
  await sleep(400); // let scripts on the page settle
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function shrink(dataUrl, maxWidth) {
  const blob = await (await fetch(dataUrl)).blob();
  const bmp = await createImageBitmap(blob);
  const scale = Math.min(1, maxWidth / bmp.width);
  const c = new OffscreenCanvas(Math.round(bmp.width * scale), Math.round(bmp.height * scale));
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  const out = await c.convertToBlob({ type: "image/jpeg", quality: 0.72 });
  const bytes = new Uint8Array(await out.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

// ---- functions that run inside the page ----------------------------------------------------
// (Each is copied into the page on its own, so it can't use anything outside itself.)

/** Page text plus a numbered list of things that can be clicked or typed into. */
function snapshotPage(maxChars) {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && cs.opacity !== "0";
  };
  for (const el of document.querySelectorAll("[data-orb-ref]")) el.removeAttribute("data-orb-ref");
  const sel = [
    "a[href]", "button", "input:not([type=hidden])", "textarea", "select", "summary",
    "[role=button]", "[role=link]", "[role=tab]", "[role=menuitem]", "[role=option]", "[role=checkbox]",
    "[role=row]", "[role=textbox]", "[role=combobox]", "[contenteditable='']", "[contenteditable=true]",
  ].join(",");
  const elements = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (n >= 250) break;
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const role =
      el.getAttribute("role") ||
      (el.isContentEditable ? "textbox" : tag === "a" ? "link" : tag === "input" ? `input:${type || "text"}` : tag);
    const value = tag === "input" && type !== "password" ? el.value : "";
    const label = (el.getAttribute("aria-label") || el.innerText || value || el.placeholder || el.title || el.name || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, role === "row" ? 200 : 100);
    n++;
    el.setAttribute("data-orb-ref", String(n));
    elements.push({
      ref: n,
      role,
      label,
      sensitive: type === "password" || /^cc-|one-time-code/.test(el.autocomplete || ""),
    });
  }
  const full = (document.body?.innerText || "").replace(/\n{3,}/g, "\n\n");
  return { title: document.title, url: location.href, text: full.slice(0, maxChars), truncated: full.length > maxChars, elements };
}

function clickRef(ref) {
  const el = document.querySelector(`[data-orb-ref="${ref}"]`);
  if (!el) return { error: `Element ${ref} isn't on the page any more. Read the page again.` };
  el.scrollIntoView({ block: "center" });
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
  }
  el.click();
  return { ok: true };
}

function typeRef(ref, text, submit) {
  const el = document.querySelector(`[data-orb-ref="${ref}"]`);
  if (!el) return { error: `Element ${ref} isn't on the page any more. Read the page again.` };
  if ((el.type || "").toLowerCase() === "password" || /^cc-|one-time-code/.test(el.autocomplete || "")) {
    return { error: "Won't type into password, card or verification-code fields. The user has to do that themselves." };
  }
  el.scrollIntoView({ block: "center" });
  el.focus();
  if (el.isContentEditable) {
    document.execCommand("selectAll", false);
    document.execCommand("insertText", false, text);
  } else {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  if (submit) {
    const key = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true };
    el.dispatchEvent(new KeyboardEvent("keydown", key));
    el.dispatchEvent(new KeyboardEvent("keypress", key));
    el.dispatchEvent(new KeyboardEvent("keyup", key));
    if (el.form?.requestSubmit) el.form.requestSubmit();
  }
  return { ok: true };
}

function scrollPage(direction) {
  window.scrollBy({ top: (direction === "up" ? -1 : 1) * window.innerHeight * 0.8 });
  return { ok: true, atBottom: window.innerHeight + window.scrollY >= document.body.scrollHeight - 4 };
}
