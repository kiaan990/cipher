// Compares how quickly two Claude models start answering, using Cipher's real prompt.
// Usage: npm run test:models            (claude-haiku-4-5 vs claude-haiku-5-5, 8 rounds)
//        npm run test:models -- 12 claude-haiku-4-5 claude-sonnet-5-5
// Talks to Anthropic directly (a few cents), so the running app isn't touched.
import Anthropic from "@anthropic-ai/sdk";
import { config } from "../server/config.js";
import { SYSTEM_PROMPT } from "../server/turn.js";

const rounds = Number(process.argv[2]) || 8;
const models = process.argv.slice(3).length ? process.argv.slice(3) : ["claude-haiku-4-5", "claude-haiku-5-5"];
const QUESTIONS = ["Hey, how's it going?", "What's a good name for a cat?", "Why is the sky blue?", "Can you remind me what we talked about?"];
const client = new Anthropic({ apiKey: config.anthropicKey });
const median = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

async function once(model: string, q: string): Promise<{ first: number; total: number; out: number }> {
  const t0 = performance.now();
  let first = 0;
  const stream = client.messages.stream({
    model,
    max_tokens: 200,
    thinking: { type: "disabled" },
    system: [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
    messages: [{ role: "user", content: q }],
  });
  for await (const e of stream) if (!first && e.type === "content_block_delta" && e.delta.type === "text_delta") first = performance.now() - t0;
  const msg = await stream.finalMessage();
  return { first, total: performance.now() - t0, out: msg.usage.output_tokens };
}

const times: Record<string, { first: number[]; total: number[]; out: number[] }> = {};
for (const m of models) {
  times[m] = { first: [], total: [], out: [] };
  await once(m, "Hi").catch((err) => console.log(`${m}: ${err.message}`)); // fills the prompt cache; not counted
}
for (let i = 0; i < rounds; i++) {
  for (const m of models) {
    try {
      const r = await once(m, QUESTIONS[i % QUESTIONS.length]);
      times[m].first.push(r.first);
      times[m].total.push(r.total);
      times[m].out.push(r.out);
    } catch (err) {
      console.log(`${m}: ${(err as Error).message}`);
    }
  }
}
for (const m of models) {
  const t = times[m];
  if (!t.first.length) continue;
  console.log(`${m.padEnd(20)} first word: median ${Math.round(median(t.first))} ms (fastest ${Math.round(Math.min(...t.first))}, slowest ${Math.round(Math.max(...t.first))})   whole reply: ${Math.round(median(t.total))} ms   ${Math.round(median(t.out))} tokens   n=${t.first.length}`);
}
