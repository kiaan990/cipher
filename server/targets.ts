/**
 * Knowing what a spoken name points at, before acting on it.
 *
 * Speech recognition mishears names ("get hub dot com"), and the model then acts on the
 * wrong one with full confidence. Two cheap checks stop most of that:
 *
 *   websites  a host that doesn't exist is never opened; a host Cipher has not opened
 *             before is confirmed once, out loud, and remembered after that
 *   apps      an app name that isn't installed is refused, with the closest real names
 *
 * The names learned here are also given to speech recognition as words to listen for.
 */
import dns from "node:dns/promises";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { config } from "./config.js";

const FILE = path.join(config.dataDir, "known-targets.json");

/** Sites common enough that asking "did you mean…" would only be annoying. */
const COMMON = (
  "google.com youtube.com apple.com icloud.com github.com gitlab.com stackoverflow.com wikipedia.org amazon.com amazon.co.uk " +
  "netflix.com spotify.com x.com twitter.com facebook.com instagram.com linkedin.com reddit.com whatsapp.com tiktok.com " +
  "openai.com chatgpt.com anthropic.com claude.ai claude.com notion.so notion.com figma.com slack.com discord.com zoom.us " +
  "microsoft.com office.com live.com outlook.com bing.com dropbox.com stripe.com paypal.com vercel.com netlify.com " +
  "railway.app railway.com digitalocean.com cloudflare.com supabase.com npmjs.com pypi.org docker.com medium.com substack.com " +
  "nytimes.com bbc.com bbc.co.uk theguardian.com cnn.com imdb.com ebay.com etsy.com airbnb.com booking.com uber.com " +
  "maps.google.com gmail.com twitch.tv vimeo.com soundcloud.com pinterest.com quora.com yahoo.com duckduckgo.com " +
  "elevenlabs.io deepgram.com perplexity.ai huggingface.co shopify.com canva.com trello.com asana.com linear.app " +
  "developer.mozilla.org mozilla.org archive.org weather.com espn.com hulu.com disneyplus.com primevideo.com"
).split(" ");

export type HostCheck = "known" | "new" | "missing";

class Targets {
  private hosts = new Set<string>();
  private listeners = new Set<() => void>();
  private apps: { at: number; names: string[] } = { at: 0, names: [] };

  constructor() {
    try {
      const saved = JSON.parse(fs.readFileSync(FILE, "utf8"));
      for (const h of saved.hosts ?? []) if (typeof h === "string") this.hosts.add(h);
    } catch {
      /* nothing learned yet */
    }
  }

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** The host of something handed to `open`, or "" if it isn't a public website. */
  hostOf(target: string): string {
    let host = "";
    try {
      const url = new URL(/^[a-z][a-z0-9+.-]*:/i.test(target) ? target : `https://${target}`);
      if (!/^https?:$/.test(url.protocol)) return "";
      host = url.hostname.toLowerCase().replace(/^www\./, "");
    } catch {
      return "";
    }
    // Local addresses and bare machine names are the user's own business.
    if (!host.includes(".") || host.endsWith(".local") || host.endsWith(".localhost") || /^[\d.]+$/.test(host) || host.includes(":")) return "";
    return host;
  }

  private familiar(host: string): boolean {
    const match = (known: string) => host === known || host.endsWith(`.${known}`);
    return COMMON.some(match) || [...this.hosts].some(match);
  }

  /** Is this host one we know, one that exists but is new, or one that doesn't exist? */
  async check(host: string): Promise<HostCheck> {
    if (!host || this.familiar(host)) return "known";
    const resolves = (name: string) =>
      Promise.race([
        dns.lookup(name).then(
          () => "yes" as const,
          (err: NodeJS.ErrnoException) => (err.code === "ENOTFOUND" ? ("no" as const) : ("unsure" as const)),
        ),
        new Promise<"unsure">((r) => setTimeout(() => r("unsure"), 2500)),
      ]);
    const found = await resolves(host);
    if (found === "yes") return "new";
    if (found === "unsure") return "new";
    // Nothing resolves when the Mac is offline; don't blame the name for that.
    return (await resolves("apple.com")) === "yes" ? "missing" : "new";
  }

  /** The user confirmed this host (or it opened fine): don't ask about it again. */
  learn(host: string): void {
    if (!host || this.familiar(host)) return;
    this.hosts.add(host);
    try {
      fs.mkdirSync(path.dirname(FILE), { recursive: true });
      fs.writeFileSync(FILE, JSON.stringify({ hosts: [...this.hosts].slice(-300) }, null, 2), { mode: 0o600 });
    } catch (err) {
      console.warn(`[targets] couldn't save: ${(err as Error).message}`);
    }
    for (const fn of this.listeners) fn();
  }

  /** Names of the apps installed on this Mac (without ".app"). */
  appNames(): string[] {
    if (Date.now() - this.apps.at < 120_000) return this.apps.names;
    const names = new Set<string>();
    const dirs = ["/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities", path.join(os.homedir(), "Applications")];
    for (const dir of dirs) {
      try {
        for (const f of fs.readdirSync(dir)) if (f.endsWith(".app")) names.add(f.slice(0, -4));
      } catch {
        /* folder not there */
      }
    }
    this.apps = { at: Date.now(), names: [...names].sort() };
    return this.apps.names;
  }

  /** Installed apps whose names are nearest to `name`, best first. */
  closestApps(name: string, count = 3): string[] {
    const want = squash(name);
    return this.appNames()
      .map((app) => {
        const have = squash(app);
        const contains = have.includes(want) || want.includes(have);
        return { app, score: contains ? 0.5 : distance(want, have) / Math.max(want.length, have.length, 1) };
      })
      .filter((x) => x.score <= 0.5)
      .sort((a, b) => a.score - b.score)
      .slice(0, count)
      .map((x) => x.app);
  }

  /** Names worth telling speech recognition about: apps, and sites opened before. */
  keyterms(limit = 60): string[] {
    const sites = [...this.hosts].slice(-15).map((h) => h.split(".").slice(0, -1).join(" "));
    // Short, ordinary words ("Mail", "Notes") are heard fine already.
    const apps = this.appNames().filter((n) => n.length >= 5 && n.length <= 30 && /^[\w .+-]+$/.test(n));
    return [...new Set([...sites, ...apps])].filter(Boolean).slice(0, limit);
  }
}

const squash = (s: string) => s.toLowerCase().replace(/\.app$/, "").replace(/[^a-z0-9]/g, "");

function distance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const keep = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = keep;
    }
  }
  return row[b.length];
}

export const targets = new Targets();
