/**
 * Puts a timestamp on every log line, so a moment in a conversation can be found in
 * logs/server.log afterwards. Import this first, before anything else logs.
 * Lines that already carry a turn number ("turn 12") keep it: time plus turn id is
 * enough to follow one reply through speech recognition, Claude, tools and voice.
 */
const stamp = (): string => {
  const d = new Date();
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
};

for (const level of ["log", "info", "warn", "error"] as const) {
  const original = console[level].bind(console);
  console[level] = (...args: unknown[]) => {
    // Keep blank spacer lines blank, and leading newlines in front of the stamp.
    if (!args.length || (args.length === 1 && args[0] === "")) return original(...args);
    if (typeof args[0] === "string") {
      const lead = args[0].match(/^\n+/)?.[0] ?? "";
      return original(`${lead}${stamp()} ${args[0].slice(lead.length)}`, ...args.slice(1));
    }
    return original(stamp(), ...args);
  };
}

export {};
