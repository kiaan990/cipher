import { Agent, fetch as undiciFetch } from "undici";

/**
 * Kept-alive HTTPS connections to Anthropic and ElevenLabs.
 * Node's built-in fetch drops idle connections after 4 s, so almost every reply
 * paid for a fresh TLS handshake before the first word. All API calls go through
 * `httpFetch`, which reuses connections for up to a minute of idle time.
 */
const agent = new Agent({
  keepAliveTimeout: 60_000,
  keepAliveMaxTimeout: 5 * 60_000,
  connect: { timeout: 10_000 },
});

export const httpFetch = ((input: any, init?: any) =>
  undiciFetch(input, { ...init, dispatcher: agent })) as unknown as typeof fetch;

const WARM_URLS = ["https://api.anthropic.com/v1/models", "https://api.elevenlabs.io/", "https://api.deepgram.com/"];
let lastWarm = 0;

/**
 * Make sure a connection to each API is open, so the next real request can start
 * immediately. Cheap: an unauthenticated request that sends no API key.
 * Called when a session starts, when the user starts speaking, and every 20 s.
 */
export function warmConnections(): void {
  const now = Date.now();
  if (now - lastWarm < 2000) return;
  lastWarm = now;
  for (const url of WARM_URLS) {
    httpFetch(url, { method: "HEAD", signal: AbortSignal.timeout(5000) })
      .then((r) => r.arrayBuffer())
      .catch(() => {});
  }
}
