/**
 * What day it is.
 *
 * Claude has no clock. Asked to "put it on Tuesday" it used to invent a date (once, a
 * year and ten months in the past). Every reply is now told the current date and time
 * and given a table of the coming days, and dates that come back from the cloud server
 * are labelled with their weekday, so no date arithmetic is left to the model.
 */
import { config } from "./config.js";

const TZ = config.timezone;

const parts = (d: Date): Record<string, string> =>
  Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(d).map((p) => [p.type, p.value]));

/** Today's date where the user is, as YYYY-MM-DD. */
export function today(now = new Date()): string {
  const p = parts(now);
  return `${p.year}-${p.month}-${p.day}`;
}

/** A calendar date some days after another (both YYYY-MM-DD). */
export function addDays(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Whole days from one calendar date to another (negative if `to` is earlier). */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86_400_000);
}

const isDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(`${s}T12:00:00Z`));

/** "2026-11-17" -> "Tuesday, November 17, 2026" ("" if it isn't a date). */
export function longDate(date: string): string {
  if (!isDate(date)) return "";
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(new Date(`${date}T12:00:00Z`));
}

const weekday = (date: string) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "long" }).format(new Date(`${date}T12:00:00Z`));
const short = (date: string) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" }).format(new Date(`${date}T12:00:00Z`));

/** "today", "tomorrow", "in 6 days", "3 days ago". */
export function relative(date: string, from = today()): string {
  const n = daysBetween(from, date);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

/** The date part of whatever the model passed as a date or time ("" if there isn't one). */
export function dateOf(value: unknown): string {
  const m = /^\s*(\d{4}-\d{2}-\d{2})/.exec(String(value ?? ""));
  return m && isDate(m[1]) ? m[1] : "";
}

/** The note given to Claude with every message: now, and the next two weeks by weekday. */
export function nowNote(now = new Date()): string {
  const t = today(now);
  const time = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" }).format(now);
  const days: string[] = [];
  for (let i = 1; i <= 14; i++) {
    const d = addDays(t, i);
    days.push(`${short(d)} = ${d}`);
  }
  return [
    `[Clock, added by the app, not said by the user. Right now it is ${longDate(t)}, ${time} (${TZ}). Today is ${t}.`,
    `The coming days: ${days.join("; ")}.`,
    `Take every date from this list, never from memory. "Next Tuesday" and "this Friday" mean the nearest one ahead in the list unless they say otherwise.]`,
  ].join(" ");
}

/**
 * A line naming the weekday of every date in some text from the cloud server, so
 * "2026-11-17" is said as "Tuesday the 17th" and not guessed.
 */
export function weekdayLegend(text: string, limit = 40): string {
  const found = [...new Set(text.match(/\b20\d{2}-\d{2}-\d{2}\b/g) ?? [])].filter(isDate).sort();
  if (!found.length) return "";
  const t = today();
  // Nearest dates first when there are too many to list.
  const near = found.sort((a, b) => Math.abs(daysBetween(t, a)) - Math.abs(daysBetween(t, b))).slice(0, limit).sort();
  return `[Weekdays for the dates above (today is ${weekday(t)} ${t}): ${near.map((d) => `${d} = ${weekday(d)}, ${relative(d, t)}`).join("; ")}]`;
}
