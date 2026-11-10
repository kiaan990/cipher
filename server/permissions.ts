import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type express from "express";
import { config } from "./config.js";

/**
 * macOS permissions the background service needs for full Mac control, checked and
 * requested from the service itself, so macOS lists the right program ("node") and
 * the user only has to switch it on.
 *
 *  automation     control apps with AppleScript (Finder, System Events…)
 *  accessibility  click and type in other apps (System Events GUI scripting)
 *  screen         take screenshots to see the screen
 */

type Which = "automation" | "accessibility" | "screen";

const SETTINGS_PANES: Record<Which, string> = {
  automation: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
  accessibility: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
  screen: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
};

function run(file: string, args: string[], timeoutMs = 60_000): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    execFile(file, args, { timeout: timeoutMs }, (err, stdout, stderr) => {
      resolve({ ok: !err, out: `${stdout}${stderr}`.trim() });
    });
  });
}

const osa = (script: string, timeoutMs?: number) => run("/usr/bin/osascript", ["-e", script], timeoutMs);

async function screenAllowed(): Promise<boolean> {
  const file = path.join(os.tmpdir(), `voice-orb-perm-${process.pid}.png`);
  try {
    const r = await run("/usr/sbin/screencapture", ["-x", "-t", "png", file], 15_000);
    return r.ok && fs.existsSync(file) && fs.statSync(file).size > 0;
  } finally {
    fs.rm(file, { force: true }, () => {});
  }
}

/** Current state, without asking the user anything that isn't already decided. */
export async function permissionStatus(): Promise<Record<Which, boolean>> {
  const [automation, accessibility, screen] = await Promise.all([
    // Reading the startup disk name is harmless; it fails only if Automation is denied.
    osa('tell application "Finder" to get name of startup disk', 8000).then((r) => r.ok),
    osa('tell application "System Events" to get UI elements enabled', 8000).then((r) => r.ok && /true/.test(r.out)),
    screenAllowed(),
  ]);
  return { automation, accessibility, screen };
}

/** Make macOS ask (or list the service in Settings), and open the right Settings page if it's still off. */
export async function requestPermission(which: Which): Promise<boolean> {
  if (which === "automation") {
    // Each app asks once: "node" wants to control Finder / System Events.
    const a = await osa('tell application "Finder" to get name of startup disk');
    const b = await osa('tell application "System Events" to get name of first process');
    if (a.ok && b.ok) return true;
  } else if (which === "accessibility") {
    // An empty keystroke does nothing, but makes macOS add the service to the Accessibility list.
    await osa('tell application "System Events" to keystroke ""', 10_000);
    const r = await osa('tell application "System Events" to get UI elements enabled', 8000);
    if (r.ok && /true/.test(r.out)) return true;
  } else if (which === "screen") {
    if (await screenAllowed()) return true;
  }
  await run("/usr/bin/open", [SETTINGS_PANES[which]], 10_000);
  return false;
}

/** /api/permissions (GET status, POST {which} to request). Only on your own Mac. */
export function installPermissionRoutes(app: express.Express): void {
  if (config.hosted) return;
  // Only the app's own page may call these (a custom header can't be sent by other websites
  // without a CORS preflight, which this server never approves).
  const guard: express.RequestHandler = (req, res, next) => {
    if (req.get("x-voice-orb") !== "1") return res.status(403).json({ error: "forbidden" });
    next();
  };
  app.get("/api/permissions", guard, async (_req, res) => {
    res.json(await permissionStatus());
  });
  // macOS applies Screen Recording only to newly started programs: exit and let the
  // background service start a fresh copy (it restarts itself within seconds).
  app.post("/api/restart", guard, (_req, res) => {
    res.json({ restarting: true });
    setTimeout(() => process.kill(process.pid, "SIGTERM"), 300);
  });
  app.post("/api/permissions/:which", guard, async (req, res) => {
    const which = req.params.which as Which;
    if (!(which in SETTINGS_PANES)) return res.status(404).json({ error: "unknown permission" });
    const granted = await requestPermission(which);
    res.json({ which, granted, status: await permissionStatus() });
  });
}
