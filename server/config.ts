import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT_DIR = path.resolve(here, "..");

// override: the keys in .env win over any same-named variables already set in the shell
// (an old DEEPGRAM_API_KEY exported in ~/.zshrc would otherwise be used instead).
dotenv.config({ path: path.join(ROOT_DIR, ".env"), override: true, quiet: true });

const env = (name: string, fallback = ""): string => (process.env[name] ?? "").trim() || fallback;

// Hosted mode: running on a cloud server (Railway sets RAILWAY_ENVIRONMENT) instead of
// your own Mac. Then a password is required, it listens on the network, and Mac and
// Chrome control are switched off.
const hosted = env("HOSTED") === "true" || Boolean(process.env.RAILWAY_ENVIRONMENT);

export const config = {
  port: Number(env("PORT", "3000")),
  hosted,
  /** Password for the hosted version's sign-in page. */
  appPassword: env("APP_PASSWORD"),
  /** Where memory and settings are saved (on Railway, point this at a volume). */
  dataDir: env("DATA_DIR", path.join(ROOT_DIR, "data")),
  openBrowser: !hosted && env("OPEN_BROWSER", "true") !== "false",

  anthropicKey: env("ANTHROPIC_API_KEY"),

  /** Your cloud server's MCP address and access token (optional). Cipher can look things up and, with your OK, make changes there. */
  cloudMcpUrl: env("KIAAN_MCP_URL"),
  cloudMcpToken: env("KIAAN_MCP_TOKEN"),
  /** The fast model that does the talking. */
  anthropicModel: env("ANTHROPIC_MODEL", "claude-haiku-4-5"),
  /**
   * A more careful model, used for the replies where Cipher has to get something done
   * (calendar, tasks, deadlines). "off" (or the same name as ANTHROPIC_MODEL) uses one model for everything.
   */
  toolModel: env("ANTHROPIC_TOOL_MODEL", "claude-sonnet-5-5"),
  /** The model behind `do_task`: multi-step work done in the background. */
  workerModel: env("WORKER_MODEL", "claude-opus-5-5"),
  /** The user's time zone, for "today" and "next Tuesday". On a hosted server the machine's own zone is not theirs. */
  timezone: validZone(env("TIMEZONE")) || (hosted ? "America/New_York" : Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York"),
  /** "deletes" (default): only deleting on the cloud server asks first. "all": every change asks first. */
  cloudConfirm: env("CLOUD_CONFIRM", "deletes").toLowerCase() === "all" ? ("all" as const) : ("deletes" as const),
  /**
   * The link with Muse (Meta's assistant, which uses the same cloud server): Cipher answers
   * messages Muse leaves there. On by default on your Mac, off on the hosted copy so the
   * two don't both answer. MUSE_LINK=on / off overrides.
   */
  museLink: env("MUSE_LINK") ? /^(on|true|1|yes)$/i.test(env("MUSE_LINK")) : !hosted,
  /** The calendar new events go in when none fits better. */
  cloudDefaultCalendar: env("CLOUD_DEFAULT_CALENDAR", ""),

  deepgramKey: env("DEEPGRAM_API_KEY"),
  deepgramModel: env("DEEPGRAM_MODEL", "nova-3"),
  /** Deepgram Aura voice, used when ElevenLabs is out of credits (or TTS_PROVIDER=deepgram). */
  deepgramVoice: env("DEEPGRAM_VOICE", "aura-2-thalia-en"),
  ttsProvider: (["auto", "elevenlabs", "deepgram"].includes(env("TTS_PROVIDER", "auto").toLowerCase())
    ? env("TTS_PROVIDER", "auto").toLowerCase()
    : "auto") as "auto" | "elevenlabs" | "deepgram",

  elevenKey: env("ELEVENLABS_API_KEY"),
  // "Laura", a default ElevenLabs voice that free-plan accounts can use over the API.
  elevenVoiceId: env("ELEVENLABS_VOICE_ID", "FGY2WhTYpPnrIDTdsKH5"),
  elevenModelId: env("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"),
  /** 0–1. Lower sounds more expressive and human, higher more even. */
  elevenStability: clamp01(Number(env("ELEVENLABS_STABILITY", "0.38")), 0.38),
  /** 0–1. A little style exaggeration adds emotion; too much adds latency and wobble. */
  elevenStyle: clamp01(Number(env("ELEVENLABS_STYLE", "0.2")), 0.2),

  /**
   * Semantic end-of-turn detection (Smart Turn, an open model from Hugging Face, run
   * locally). "on" waits when you pause mid-thought instead of replying straight away.
   */
  smartTurn: env("SMART_TURN", "on").toLowerCase() !== "off",
  /** Longest silence to wait for you to carry on when Smart Turn thinks you're mid-thought (ms). */
  smartTurnMaxWaitMs: Number(env("SMART_TURN_MAX_WAIT_MS", "1400")) || 1400,
  /** Quiet "mm-hmm" / "yeah" while you're mid-thought, like a listener on a call. */
  backchannels: env("BACKCHANNELS", "on").toLowerCase() !== "off",
};

function validZone(zone: string): string {
  if (!zone) return "";
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return zone;
  } catch {
    console.warn(`TIMEZONE "${zone}" isn't a time zone name (use one like America/New_York). Ignoring it.`);
    return "";
  }
}

function clamp01(n: number, fallback: number): number {
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : fallback;
}

/** Names of required keys that are not set in .env. */
export function missingKeys(): string[] {
  const missing: string[] = [];
  if (!config.anthropicKey) missing.push("ANTHROPIC_API_KEY");
  if (!config.deepgramKey) missing.push("DEEPGRAM_API_KEY");
  // ElevenLabs is optional: without it, Deepgram's voice speaks.
  return missing;
}
