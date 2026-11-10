import http from "node:http";
import path from "node:path";
import { exec } from "node:child_process";
import express from "express";
import { WebSocketServer } from "ws";
import { ROOT_DIR, config, missingKeys } from "./config.js";
import { ConversationStore, VoiceSession } from "./session.js";
import { browser } from "./browser.js";
import { voice } from "./tts.js";
import { preloadSmartTurn } from "./smartturn.js";
import { cloud } from "./cloud.js";
import { phrases } from "./tts.js";
import { installAuth, isSignedIn, authEnabled } from "./auth.js";
import { installPermissionRoutes } from "./permissions.js";
import { APP_VERSION } from "./version.js";

// Hosted on the internet without a password would let anyone use your API keys and
// talk to your memory. Refuse to start rather than risk that.
if (config.hosted && !authEnabled) {
  console.error("\n  Hosted mode needs a password. Set APP_PASSWORD in the host's variables, then redeploy.\n");
  process.exit(1);
}

const app = express();
if (config.hosted) app.set("trust proxy", 1); // behind the host's HTTPS proxy
app.disable("x-powered-by");
app.get("/healthz", (_req, res) => res.send("ok"));
installAuth(app);
installPermissionRoutes(app);
app.use(express.static(path.join(ROOT_DIR, "public")));
// Three.js for the 3D orb, served from node_modules so the app works offline.
app.use("/vendor/three", express.static(path.join(ROOT_DIR, "node_modules", "three")));
// transformers.js (on-device object detection) and its ONNX runtime files.
// RNNoise noise filter (runs in the browser).
app.use("/vendor/noise", express.static(path.join(ROOT_DIR, "node_modules", "@sapphi-red", "web-noise-suppressor", "dist")));
app.use("/vendor/transformers", express.static(path.join(ROOT_DIR, "node_modules", "@huggingface", "transformers", "dist")));
app.get("/api/status", (req, res) => {
  if (String(req.headers.origin ?? "").startsWith("chrome-extension://")) console.log("[chrome] extension reached the app");
  res.json({
    missingKeys: missingKeys(),
    model: config.anthropicModel,
    ...(config.hosted ? {} : { chrome: browser.connected, version: APP_VERSION, appDir: ROOT_DIR, dataDir: config.dataDir }),
  });
});

const server = http.createServer(app);
// Only this Mac's own page may connect. The app can control the computer, so other
// devices on the network and other websites (which could otherwise open a socket to
// localhost from your browser) are refused. The Chrome extension connects separately,
// on /ext, with its pairing code.
const ALLOWED_ORIGINS = new Set([`http://localhost:${config.port}`, `http://127.0.0.1:${config.port}`]);
const wss = new WebSocketServer({ noServer: true });
const extWss = new WebSocketServer({ noServer: true });
const isLocal = (req: http.IncomingMessage) => ["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(req.socket.remoteAddress ?? "");

server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  const origin = req.headers.origin;
  const refuse = () => {
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
  };
  if (config.hosted) {
    // On the internet: only a signed-in browser on this same site may connect.
    // (No Chrome extension or local tools in hosted mode.)
    // The host's proxy terminates HTTPS and says so in X-Forwarded-Proto.
    const proto = String(req.headers["x-forwarded-proto"] ?? "http").split(",")[0].trim();
    const sameSite = origin === `${proto}://${req.headers.host}`;
    if (url.pathname !== "/ws" || !sameSite || !isSignedIn(req)) return refuse();
    return wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, req));
  }
  if (!isLocal(req)) return refuse();
  if (url.pathname === "/ws") {
    // Browsers always send an Origin; local tools (like the test client) don't.
    if (origin && !ALLOWED_ORIGINS.has(origin)) return refuse();
    wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, req));
  } else if (url.pathname === "/ext") {
    if (!origin?.startsWith("chrome-extension://")) {
      console.warn(`[chrome] refused a connection from ${origin ?? "no origin"} (not an extension)`);
      return refuse();
    }
    if (!browser.checkToken(url.searchParams.get("token"))) {
      console.warn("[chrome] refused the extension: wrong pairing code (copy it again from Settings)");
      return refuse();
    }
    extWss.handleUpgrade(req, socket, head, (ws) => browser.attach(ws));
  } else {
    refuse();
  }
});
const store = new ConversationStore();

wss.on("connection", (ws, req) => {
  const url = new URL(req.url ?? "/ws", "http://localhost");
  const sessionId = (url.searchParams.get("session") || "default").slice(0, 64);
  const session = new VoiceSession(ws, store.get(sessionId));
  store.claim(sessionId, session);

  // Detect dead connections so the browser's reconnect logic can kick in.
  let alive = true;
  ws.on("pong", () => (alive = true));
  const ping = setInterval(() => {
    if (!alive) return ws.terminate();
    alive = false;
    ws.ping();
  }, 15000);

  ws.on("message", (data, isBinary) => session.handleMessage(data, isBinary));
  ws.on("close", () => {
    clearInterval(ping);
    session.close();
    store.release(sessionId, session);
  });
  ws.on("error", () => ws.terminate());
});

// On your Mac: listen on this computer only, never on the network. Hosted: listen for
// the host's proxy (which adds HTTPS); every page needs the password.
server.listen(config.port, config.hosted ? "0.0.0.0" : "127.0.0.1", () => {
  if (!config.hosted) browser.writePairingFile(config.port);
  const url = `http://localhost:${config.port}`;
  console.log(config.hosted ? `\n  Cipher running (hosted mode, port ${config.port}, password required)` : `\n  Cipher running at ${url}`);
  console.log(`  Model: ${config.anthropicModel}`);
  const missing = missingKeys();
  if (missing.length) {
    console.log(`\n  Missing keys in .env: ${missing.join(", ")}`);
    console.log("  The page will tell you which ones to add.\n");
  } else {
    console.log("  All API keys found.");
    void voice.checkCredits().then(() => console.log(""));
  }
  preloadSmartTurn();
  cloud.preload();
  // Common openers ("Oh, nice!", "Got it.") recorded ahead, so replies can start instantly.
  setTimeout(() => void phrases.warm(), 5000);
  if (config.openBrowser) {
    const cmd = process.platform === "darwin" ? "open" : process.platform === "win32" ? "start \"\"" : "xdg-open";
    exec(`${cmd} ${url}`, () => {});
  }
});

server.on("error", (err: NodeJS.ErrnoException) => {
  if (err.code === "EADDRINUSE") {
    console.error(`Port ${config.port} is already in use. Stop the other process or set PORT in .env.`);
    process.exit(1);
  }
  throw err;
});
