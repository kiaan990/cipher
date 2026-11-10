import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import type http from "node:http";
import type express from "express";
import { config } from "./config.js";

/**
 * Password sign-in for the hosted version. One password (APP_PASSWORD); signing in sets
 * a signed, HttpOnly cookie that lasts 30 days. The cookie is signed with a key derived
 * from the password, so changing the password signs everyone out.
 */

const COOKIE = "orb_session";
const LIFETIME_MS = 30 * 24 * 60 * 60 * 1000;
const key = createHash("sha256").update(`voice-orb-session:${config.appPassword}`).digest();

export const authEnabled = Boolean(config.appPassword);

function sign(expires: number): string {
  const mac = createHmac("sha256", key).update(String(expires)).digest("base64url");
  return `${expires}.${mac}`;
}

function valid(token: string | undefined): boolean {
  if (!token) return false;
  const [exp, mac] = token.split(".");
  const expires = Number(exp);
  if (!Number.isFinite(expires) || expires < Date.now() || !mac) return false;
  const want = Buffer.from(sign(expires));
  const got = Buffer.from(token);
  return want.length === got.length && timingSafeEqual(want, got);
}

function cookieValue(req: http.IncomingMessage): string | undefined {
  for (const part of String(req.headers.cookie ?? "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === COOKIE) return v.join("=");
  }
  return undefined;
}

export function isSignedIn(req: http.IncomingMessage): boolean {
  return !authEnabled || valid(cookieValue(req));
}

function passwordMatches(given: string): boolean {
  // Compare hashes so the comparison takes the same time whatever the length.
  const a = createHash("sha256").update(given).digest();
  const b = createHash("sha256").update(config.appPassword).digest();
  return timingSafeEqual(a, b);
}

// At most 10 wrong passwords per address per 15 minutes.
const attempts = new Map<string, { count: number; since: number }>();
function tooMany(ip: string): boolean {
  const now = Date.now();
  const a = attempts.get(ip);
  if (!a || now - a.since > 15 * 60_000) return false;
  return a.count >= 10;
}
function failed(ip: string): void {
  const now = Date.now();
  const a = attempts.get(ip);
  if (!a || now - a.since > 15 * 60_000) attempts.set(ip, { count: 1, since: now });
  else a.count++;
}

// Needed to install the web app before signing in. None of these contain anything private.
const PUBLIC_PATHS = new Set(["/healthz", "/manifest.webmanifest", "/sw.js", "/offline.html"]);

/** Adds /login, /logout and protects everything else. */
export function installAuth(app: express.Express): void {
  if (!authEnabled) return;

  app.get("/login", (req, res) => {
    if (isSignedIn(req)) return res.redirect("/");
    res.type("html").send(loginPage(req.query.error === "1" ? "That password isn't right." : req.query.error === "2" ? "Too many tries. Wait 15 minutes." : ""));
  });

  app.post("/login", (req, res) => {
    let body = "";
    req.setEncoding("utf8");
    req.on("data", (c) => (body += c).length > 4096 && req.destroy());
    req.on("end", () => {
      const ip = req.ip ?? "unknown";
      if (tooMany(ip)) return res.redirect(303, "/login?error=2");
      const password = new URLSearchParams(body).get("password") ?? "";
      if (!passwordMatches(password)) {
        failed(ip);
        return res.redirect(303, "/login?error=1");
      }
      attempts.delete(ip);
      const expires = Date.now() + LIFETIME_MS;
      res.setHeader(
        "Set-Cookie",
        `${COOKIE}=${sign(expires)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${LIFETIME_MS / 1000}${config.hosted ? "; Secure" : ""}`,
      );
      res.redirect(303, "/");
    });
  });

  app.get("/logout", (_req, res) => {
    res.setHeader("Set-Cookie", `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${config.hosted ? "; Secure" : ""}`);
    res.redirect("/login");
  });

  app.use((req, res, next) => {
    if (PUBLIC_PATHS.has(req.path) || req.path.startsWith("/icons/") || isSignedIn(req)) return next();
    if (req.method === "GET" && (req.headers.accept ?? "").includes("text/html")) return res.redirect("/login");
    res.status(401).json({ error: "Sign in first." });
  });
}

function loginPage(error: string): string {
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Cipher · Sign in</title>
<link rel="manifest" href="/manifest.webmanifest" />
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
<link rel="icon" type="image/png" href="/icons/favicon-32.png" />
<meta name="theme-color" content="#06070c" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-title" content="Cipher" />
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px; background: radial-gradient(1200px 700px at 50% 30%, #121a33 0%, #06070c 60%); color: rgba(255,255,255,.94); font: 15px/1.4 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", system-ui, sans-serif; }
  .card { width: min(360px, 100%); padding: 28px 24px 24px; border-radius: 24px; background: rgba(22,24,34,.6); box-shadow: inset 0 0 0 .5px rgba(255,255,255,.14), 0 30px 80px rgba(0,0,0,.5); backdrop-filter: blur(24px); }
  .orb { width: 44px; height: 44px; border-radius: 50%; margin: 0 auto 16px; background: radial-gradient(circle at 35% 30%, #cfe0ff, #78a8ff 40%, #2a3f8f 75%); box-shadow: 0 0 40px rgba(120,168,255,.55); }
  h1 { margin: 0 0 4px; text-align: center; font: 600 20px/1.2 -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif; letter-spacing: -.01em; }
  p { margin: 0 0 20px; text-align: center; color: rgba(235,238,255,.6); font-size: 13.5px; }
  input { width: 100%; padding: 12px 14px; border-radius: 12px; border: 0; background: rgba(0,0,0,.4); box-shadow: inset 0 0 0 .5px rgba(255,255,255,.18); color: inherit; font: inherit; outline: none; }
  input:focus { box-shadow: inset 0 0 0 1.5px rgba(120,168,255,.9); }
  button { margin-top: 12px; width: 100%; padding: 12px; border: 0; border-radius: 12px; background: #78a8ff; color: #06070c; font: 600 15px/1 inherit; cursor: pointer; }
  .err { margin: 12px 0 0; color: #ff8a96; font-size: 13px; text-align: center; min-height: 1em; }
</style></head>
<body>
  <form class="card" method="post" action="/login">
    <div class="orb" aria-hidden="true"></div>
    <h1>Cipher</h1>
    <p>Enter your password to continue.</p>
    <input type="password" name="password" autocomplete="current-password" placeholder="Password" autofocus required aria-label="Password" />
    <button type="submit">Sign in</button>
    <div class="err" role="alert">${error}</div>
  </form>
</body></html>`;
}
