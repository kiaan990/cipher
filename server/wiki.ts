/**
 * Longer notes: a small set of linked pages, one per subject (a person, a project,
 * a trip), that Cipher writes while "dreaming" (see dream.ts).
 *
 * Long-term memory (memory.ts) is a short list that is read out to Claude on every
 * reply, so it has to stay small. Detail that doesn't belong there lives here instead,
 * and Cipher looks it up when a conversation calls for it (see recall.ts).
 *
 * Stored only on this computer, as plain text files in data/wiki/, so they can be
 * opened and read. Pages link to each other with [[page-name]].
 */
import fs from "node:fs";
import path from "node:path";
import { config } from "./config.js";
import { writeDurably } from "./memory.js";

export interface Page {
  slug: string;
  title: string;
  body: string;
  updatedAt: number;
}

const DIR = path.join(config.dataDir, "wiki");
export const MAX_PAGES = 60;
export const MAX_PAGE_CHARS = 6000;
const SLUG = /^[a-z0-9][a-z0-9-]{0,47}$/;
const LINK = /\[\[([a-z0-9][a-z0-9-]{0,47})\]\]/g;

/** A page name that is safe to use as a file name, or "" if the text has nothing usable. */
export function slugify(text: string): string {
  const s = text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .replace(/-+$/, "");
  return SLUG.test(s) ? s : "";
}

class Wiki {
  list(): Page[] {
    let files: string[];
    try {
      files = fs.readdirSync(DIR).filter((f) => f.endsWith(".md"));
    } catch {
      return [];
    }
    return files
      .map((f) => this.read(f.slice(0, -3)))
      .filter((p): p is Page => p !== null)
      .sort((a, b) => a.slug.localeCompare(b.slug));
  }

  read(slug: string): Page | null {
    if (!SLUG.test(slug)) return null;
    const file = path.join(DIR, `${slug}.md`);
    try {
      const text = fs.readFileSync(file, "utf8");
      const m = text.match(/^# (.*)\n+/);
      return { slug, title: (m?.[1] ?? slug).trim(), body: (m ? text.slice(m[0].length) : text).trim(), updatedAt: fs.statSync(file).mtimeMs };
    } catch {
      return null;
    }
  }

  /** Create or replace a page. Returns false when the name or content can't be saved. */
  write(slug: string, title: string, body: string): boolean {
    const text = body.trim().slice(0, MAX_PAGE_CHARS);
    if (!SLUG.test(slug) || !text) return false;
    if (!this.read(slug) && this.list().length >= MAX_PAGES) return false;
    const heading = title.replace(/\s+/g, " ").trim().slice(0, 80) || slug;
    writeDurably(path.join(DIR, `${slug}.md`), `# ${heading}\n\n${text}\n`);
    return true;
  }

  remove(slug: string): void {
    if (SLUG.test(slug)) fs.rmSync(path.join(DIR, `${slug}.md`), { force: true });
  }

  clear(): void {
    fs.rmSync(DIR, { recursive: true, force: true });
  }

  /** Links that point at a page that doesn't exist, as [from, to] pairs. */
  brokenLinks(pages = this.list()): [string, string][] {
    const known = new Set(pages.map((p) => p.slug));
    const out: [string, string][] = [];
    for (const p of pages) for (const m of p.body.matchAll(LINK)) if (!known.has(m[1])) out.push([p.slug, m[1]]);
    return out;
  }

  /** The pages that best match some words, best first, with the part that matched. */
  search(text: string, limit = 3): { page: Page; excerpt: string }[] {
    const words = [...new Set(text.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? [])];
    if (!words.length) return [];
    return this.list()
      .map((page) => {
        const title = page.title.toLowerCase();
        const body = page.body.toLowerCase();
        let score = 0;
        let first = -1;
        for (const w of words) {
          if (title.includes(w) || page.slug.includes(w)) score += 5;
          const at = body.indexOf(w);
          if (at >= 0) {
            score += 1 + Math.min(3, body.split(w).length - 2);
            if (first < 0 || at < first) first = at;
          }
        }
        const start = Math.max(0, first - 200);
        const excerpt = page.body.length <= 1200 ? page.body : `${start ? "…" : ""}${page.body.slice(start, start + 1200)}…`;
        return { page, excerpt, score };
      })
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, limit);
  }

  /** A line for Claude's instructions saying which pages exist, or "" when there are none. */
  describe(): string {
    const pages = this.list();
    if (!pages.length) return "";
    return `You also keep longer notes on: ${pages.map((p) => p.title).join("; ")}. They are not shown here: use recall to read them.`;
  }
}

export const wiki = new Wiki();
