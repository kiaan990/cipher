// Stage-by-stage reply latency: end of your speech -> words recognised -> turn accepted
// -> model's first word -> first audio. Spoken questions (Mac voice), one conversation.
// Usage: PORT=3111 node tests/review/latency.mjs [rounds]
import { connect, ask, tts, silence, concat, stats, save, sleep, PORT } from "./lib.mjs";
const QUESTIONS = [
  "Cipher, what's seven times eight?", "Cipher, what's the capital of Australia?", "Cipher, give me one word that rhymes with orange.",
  "Cipher, is a tomato a fruit?", "Cipher, how many days are in a leap year?", "Cipher, what colour do you get from blue and yellow?",
  "Cipher, who wrote Hamlet?", "Cipher, what's the opposite of hot?", "Cipher, how many legs does a spider have?", "Cipher, name one planet.",
  "Cipher, what's ten percent of two hundred?", "Cipher, what comes after Tuesday?",
];
const rounds = Number(process.argv[2]) || QUESTIONS.length;
const c = await connect("latency");
await c.start();
const rows = [];
for (let i = 0; i < rounds; i++) {
  const r = await ask(c, concat(tts(QUESTIONS[i % QUESTIONS.length]), silence(300)));
  rows.push(r);
  console.log(r.answered
    ? `${String(i + 1).padStart(2)}  wait ${String(r.eos_to_audio).padStart(5)} ms = decide-you-finished ${String(r.eos_to_turn).padStart(4)} (words in ${String(r.eos_to_last_words).padStart(4)}) + model ${String(r.turn_to_first_word).padStart(4)} + voice ${String(r.first_word_to_audio).padStart(4)}   "${r.heard}" -> "${r.reply.slice(0, 50)}"`
    : `${String(i + 1).padStart(2)}  NOT ANSWERED (${r.why})`);
  await sleep(1500);
}
const ok = rows.filter((r) => r.answered);
const col = (k) => stats(ok.map((r) => r[k]));
const summary = { port: PORT, answered: `${ok.length}/${rows.length}`, eos_to_last_words: col("eos_to_last_words"), eos_to_turn: col("eos_to_turn"), turn_to_first_word: col("turn_to_first_word"), first_word_to_audio: col("first_word_to_audio"), eos_to_audio: col("eos_to_audio") };
console.log("\n", JSON.stringify(summary, null, 1));
save(`latency-${PORT}-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}`, { summary, rows });
await c.close();
process.exit(0);
