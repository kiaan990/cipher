import { EventEmitter } from "node:events";
import WebSocket from "ws";
import { config } from "./config.js";
import { listening } from "./listening.js";

export interface TranscriptEvent {
  transcript: string;
  isFinal: boolean;
  speechFinal: boolean;
}

/**
 * One streaming connection to Deepgram's live transcription API.
 * Emits: "open", "transcript" (TranscriptEvent), "speechStarted", "utteranceEnd", "error" (string), "close".
 * Input audio: 16 kHz mono 16-bit little-endian PCM.
 */
export class DeepgramStream extends EventEmitter {
  private ws: WebSocket | null = null;
  private keepAlive: NodeJS.Timeout | null = null;
  private pending: Buffer[] = [];
  private closedByUs = false;
  /** True when the server refused the connection in a way a retry won't fix. */
  fatal = false;

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): void {
    const params = new URLSearchParams({
      model: config.deepgramModel,
      language: "en",
      encoding: "linear16",
      sample_rate: "16000",
      channels: "1",
      interim_results: "true",
      smart_format: "true",
      no_delay: "true", // don't hold back finals while smart_format waits for more digits
      punctuate: "true",
      // ms of silence that marks the end of a turn. Short, for fast replies: if the user was
      // only pausing, the session quietly cancels the reply and waits for the rest.
      endpointing: "150",
      utterance_end_ms: "1000", // fallback end-of-turn signal in noisy rooms
      vad_events: "true",
      // Keep "mm-hmm", "uh-huh", "um": they tell a listening "yeah" from a real interruption,
      // and an "um" at the end shows you're not finished.
      filler_words: "true",
    });
    // Listen out for the wake phrase, so it's recognised reliably ("Hey Claude", not "hey cloud").
    for (const term of listening.keyterms()) params.append(config.deepgramModel.startsWith("nova-3") ? "keyterm" : "keywords", term);
    const ws = new WebSocket(`wss://api.deepgram.com/v1/listen?${params}`, {
      headers: { Authorization: `Token ${config.deepgramKey}` },
    });
    this.ws = ws;

    ws.on("open", () => {
      for (const chunk of this.pending) ws.send(chunk);
      this.pending = [];
      // Deepgram closes idle streams after ~10 s, e.g. while the mic is muted.
      this.keepAlive = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "KeepAlive" }));
      }, 4000);
      this.emit("open");
    });

    ws.on("unexpected-response", (req, res) => {
      const code = res.statusCode ?? 0;
      // Retrying won't fix a bad key, an empty balance or a bad request.
      this.fatal = code >= 400 && code < 500 && code !== 408 && code !== 429;
      let body = "";
      res.on("data", (c: Buffer) => (body += c.toString()).length > 2000 && res.destroy());
      const finish = () => {
        this.emit("error", httpErrorMessage(code, body, String(res.headers["dg-error"] ?? "")));
        this.clearTimer();
        if (this.ws === ws) {
          this.ws = null;
          if (!this.closedByUs) this.emit("close");
        }
      };
      res.once("end", finish);
      res.once("close", () => res.readableEnded || finish());
      req.on("error", () => {});
    });

    ws.on("message", (data, isBinary) => {
      if (isBinary) return;
      let msg: any;
      try {
        msg = JSON.parse(data.toString());
      } catch {
        return;
      }
      if (msg.type === "Results") {
        const transcript: string = msg.channel?.alternatives?.[0]?.transcript ?? "";
        this.emit("transcript", {
          transcript,
          isFinal: Boolean(msg.is_final),
          speechFinal: Boolean(msg.speech_final),
        } satisfies TranscriptEvent);
      } else if (msg.type === "SpeechStarted") {
        this.emit("speechStarted");
      } else if (msg.type === "UtteranceEnd") {
        this.emit("utteranceEnd");
      } else if (msg.type === "Error" || msg.err_msg) {
        this.emit("error", `Deepgram reported a problem: ${msg.description ?? msg.err_msg ?? "unknown error"}`);
      }
    });

    ws.on("error", (err) => {
      if (this.closedByUs) return; // we hung up ourselves, e.g. ending during the handshake
      // "unexpected-response" already reported HTTP failures.
      if (!String(err.message).includes("Unexpected server response")) {
        this.emit("error", networkErrorMessage(err as NodeJS.ErrnoException));
      }
    });

    ws.on("close", (code, reason) => {
      if (this.ws !== ws) return; // already handled
      this.clearTimer();
      this.ws = null;
      if (this.closedByUs) return;
      // 1000 is a normal close. Anything else carries Deepgram's reason, e.g. "NET-0001".
      if (code !== 1000 && code !== 1005) {
        const why = reason.toString().trim();
        console.warn(`[deepgram] stream closed (code ${code}${why ? `: ${why}` : ""})`);
      }
      this.emit("close");
    });
  }

  send(chunk: Buffer): void {
    const ws = this.ws;
    if (!ws) return;
    if (ws.readyState === WebSocket.OPEN) ws.send(chunk);
    else if (ws.readyState === WebSocket.CONNECTING && this.pending.length < 100) this.pending.push(chunk);
  }

  close(): void {
    this.closedByUs = true;
    this.clearTimer();
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    try {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "CloseStream" }));
        ws.close();
      } else {
        ws.terminate();
      }
    } catch {
      /* already closed */
    }
  }

  private clearTimer(): void {
    if (this.keepAlive) clearInterval(this.keepAlive);
    this.keepAlive = null;
  }
}

/** Plain-language reason for an HTTP refusal of the streaming connection. */
function httpErrorMessage(code: number, body: string, dgError: string): string {
  let detail = dgError;
  try {
    const j = JSON.parse(body);
    detail = j.err_msg || j.message || j.reason || detail;
  } catch {
    /* not JSON */
  }
  detail = String(detail).trim().slice(0, 200);
  const suffix = detail ? ` (Deepgram says: ${detail})` : "";
  if (code === 401) return `Deepgram rejected the API key. Check DEEPGRAM_API_KEY in .env, then restart npm start.${suffix}`;
  if (code === 402) return `Your Deepgram account is out of credit. Add credit at console.deepgram.com.${suffix}`;
  if (code === 403 && /model/i.test(detail)) return `Your Deepgram account can't use the "${config.deepgramModel}" model. Remove DEEPGRAM_MODEL from .env to use nova-3.${suffix}`;
  if (code === 403) return `This Deepgram key isn't allowed to transcribe. Create a key with Member access at console.deepgram.com.${suffix}`;
  if (code === 429) return `Deepgram is rate limiting this account (too many connections at once). Close other tabs running the app.${suffix}`;
  if (code === 400) return `Deepgram refused the request settings.${suffix}`;
  return `Deepgram connection failed (HTTP ${code}).${suffix}`;
}

/** Plain-language reason for a network-level failure reaching Deepgram. */
function networkErrorMessage(err: NodeJS.ErrnoException): string {
  const c = err.code ?? "";
  if (c === "ENOTFOUND" || c === "EAI_AGAIN") return "Can't reach Deepgram: no internet connection, or DNS can't find api.deepgram.com.";
  if (c === "ECONNREFUSED" || c === "ECONNRESET" || c === "ETIMEDOUT" || c === "ENETUNREACH")
    return `Can't reach Deepgram (${c}). Check your internet connection, VPN or firewall.`;
  if (/certificate|self.signed|CERT_|UNABLE_TO/i.test(`${c} ${err.message}`))
    return "Couldn't make a secure connection to Deepgram. A school/work network, VPN or antivirus may be intercepting HTTPS. Try another network.";
  return `Deepgram connection error: ${err.message}`;
}
