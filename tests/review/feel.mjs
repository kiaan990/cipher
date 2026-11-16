// Conversation feel: interruptions, pauses mid-sentence, silence and the wake word, long
// answers, back-to-back questions, background noise. Spoken with the Mac's voices straight
// into the app's socket: no real mic, speaker, room echo or second person.
// Usage: PORT=3111 node tests/review/feel.mjs [scenario ...]   (no names = all)
import { connect, ask, tts, silence, concat, noise, mix, rms, sleep, longestStall, save, PORT } from "./lib.mjs";

const want = process.argv.slice(2);
const results = {};
const say = (...a) => console.log(...a);
async function scenario(name, fn) {
  if (want.length && !want.includes(name)) return;
  say(`\n=== ${name} ===`);
  const c = await connect(name);
  await c.start();
  try {
    results[name] = await fn(c);
  } catch (err) {
    results[name] = { error: String(err?.stack ?? err) };
    say("ERROR", err);
  }
  await c.close();
  await sleep(500);
}
const q = (text, voice) => concat(tts(text, voice), silence(300));

// --- interruptions ---------------------------------------------------------------------
await scenario("barge-in", async (c) => {
  const out = [];
  for (const [label, words] of [["a new question", "Wait, what's two plus two?"], ["stop", "Stop."], ["only yeah", "Yeah."], ["a longer sentence", "Actually never mind that, tell me about boats instead."]]) {
    const before = c.events.length;
    void c.speak(q("Cipher, explain in detail how airplanes stay in the air."));
    const firstAudio = await c.waitFor((m) => m.type === "tts_sentence_end" || m.type === "assistant_done", 20000);
    await sleep(2500); // Cipher has been talking for a couple of seconds
    const t = c.lastTurn();
    const pcm = q(words);
    const spoke = c.speak(pcm);
    const stopped = await c.waitFor((m) => m.type === "interrupted" || m.type === "ack", 6000);
    await spoke;
    const start = c.speechStartAt;
    const lateAudio = t.audioAt.filter(([at]) => stopped && at > stopped._t + 50).reduce((s, [, b]) => s + b, 0);
    const next = await c.settle(30000);
    const row = {
      interruption: label,
      result: stopped ? stopped.type : "kept talking (nothing within 6 s)",
      stop_ms_after_you_started: stopped ? stopped._t - start : null,
      stop_ms_after_you_finished: stopped ? stopped._t - c.lastLoudAt : null,
      audio_still_sent_after_stop_s: +(lateAudio / 48000).toFixed(2),
      next_reply: next && next.id !== t.id ? next.text.slice(0, 90) : "(none)",
      heard: c.events.slice(before).filter((m) => m.type === "user_turn").map((m) => m.text),
    };
    out.push(row);
    say(JSON.stringify(row));
    c.send({ type: "reset" });
    await sleep(1500);
  }
  return out;
});

// --- pause in the middle of a sentence ---------------------------------------------------
await scenario("mid-sentence-pause", async (c) => {
  const out = [];
  for (const gap of [600, 1000, 1500, 2500]) {
    const before = c.events.length;
    const pcm = concat(tts("Cipher, I'm trying to decide between"), silence(gap), tts("pizza and sushi for dinner tonight."), silence(300));
    await c.speak(pcm);
    const last = await c.settle(30000, 2500);
    const ev = c.events.slice(before);
    const replies = [...c.turns.values()].filter((t) => ev.some((m) => m.turnId === t.id && m.type === "thinking"));
    const row = {
      pause_ms: gap,
      turns_taken: ev.filter((m) => m.type === "user_turn").map((m) => m.text),
      replies_started: replies.length,
      replies_dropped_unheard: ev.filter((m) => m.type === "turn_cancelled").length,
      replies_heard: replies.filter((t) => t.audioBytes > 0 && !t.turn_cancelled).map((t) => t.text.slice(0, 80)),
      interrupted_mid_reply: ev.filter((m) => m.type === "interrupted").length,
      listener_sounds: ev.filter((m) => m.type === "backchannel").length,
    };
    out.push(row);
    say(JSON.stringify(row));
    c.send({ type: "reset" });
    await sleep(1500);
  }
  return out;
});

// --- silence, sleep and the wake word ----------------------------------------------------
await scenario("silence-and-wake", async (c) => {
  const out = {};
  let r = await ask(c, q("What's the capital of France?"));
  out.asleep_no_wake_word = r.answered ? `ANSWERED: ${r.reply.slice(0, 50)}` : `not answered (${r.why})`;
  r = await ask(c, q("Cipher, what's the capital of France?"));
  out.with_wake_word = r.answered ? `answered: ${r.reply.slice(0, 50)}` : `NOT answered (${r.why})`;
  await c.settle(15000);
  await sleep(3000);
  r = await ask(c, q("And what about Spain?"));
  out.follow_up_3s_later_no_wake_word = r.answered ? `answered: ${r.reply.slice(0, 50)}` : `NOT answered (${r.why})`;
  await c.settle(15000);
  const asleepMsg = c.waitFor((m) => m.type === "wake" && m.waiting === true, 40000);
  const t0 = Date.now();
  const w = await asleepMsg;
  out.seconds_of_quiet_before_it_sleeps = w ? Math.round((w._t - t0) / 1000) : "never within 40 s";
  r = await ask(c, q("And Italy?"));
  out.follow_up_after_sleeping = r.answered ? `ANSWERED: ${r.reply.slice(0, 50)}` : `not answered (${r.why})`;
  // 12 s of nothing at all while awake: does it say anything on its own?
  r = await ask(c, q("Cipher, hello."));
  await c.settle(15000);
  const n = c.events.length;
  await sleep(12000);
  out.spoke_unprompted_in_12s_of_silence = c.events.slice(n).some((m) => m.type === "thinking");
  say(JSON.stringify(out, null, 1));
  return out;
});

// --- which voices wake it, and what wakes it by mistake -----------------------------------
await scenario("wake-word", async (c) => {
  const voices = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tessa", "Fred", "Kathy", "Ralph", "Flo", "Eddy", "Grandma"];
  const woke = [];
  for (const v of voices) {
    c.send({ type: "reset" });
    // Make sure it is asleep first.
    await c.waitFor((m) => m.type === "wake" && m.waiting === true, 22000);
    const r = await ask(c, concat(tts("Cipher, what day comes after Monday?", v), silence(300)), { timeout: 20000 });
    const heard = r.heard ?? c.events.filter((m) => m.type === "transcript").pop()?.text ?? "";
    woke.push({ voice: v, woke: r.answered, heard_as: heard.slice(0, 50) });
    say(v.padEnd(9), r.answered ? "woke" : `DID NOT WAKE (${r.why})`, "|", heard.slice(0, 50));
    await c.settle(12000);
  }
  const traps = ["I need to decipher this message before lunch.", "The cyber attack was all over the news.", "Sigh, for the last time, I said no.", "She bought a new siphon for the fish tank.", "My cousin Seraphina is visiting on Friday.", "I read an article about the Caesar cipher yesterday."];
  const falseWakes = [];
  for (const t of traps) {
    await c.waitFor((m) => m.type === "wake" && m.waiting === true, 22000);
    const r = await ask(c, q(t), { timeout: 20000 });
    falseWakes.push({ said: t, woke: r.answered, reply: r.answered ? r.reply.slice(0, 60) : "" });
    say(r.answered ? "WOKE BY MISTAKE" : "stayed asleep", "|", t);
    if (r.answered) await c.settle(12000);
  }
  return { woke, falseWakes };
});

// --- a long answer ----------------------------------------------------------------------
await scenario("long-answer", async (c) => {
  const r = await ask(c, q("Cipher, tell me a story about a lighthouse keeper. Make it long, about two minutes."), { timeout: 180000 });
  const t = r.turn;
  const row = {
    wait_for_first_audio_ms: r.eos_to_audio,
    words: r.reply.split(/\s+/).length,
    audio_seconds: r.audio_s,
    longest_gap_where_voice_ran_dry_ms: longestStall(t),
    text_finished_ms_after_start: t.tTextDone - t.tThinking,
    ended_mid_sentence: !/[.!?…"]\s*$/.test(r.reply.trim()),
    last_words: r.reply.trim().slice(-80),
  };
  say(JSON.stringify(row, null, 1));
  return row;
});

// --- questions on top of each other ------------------------------------------------------
await scenario("back-to-back", async (c) => {
  const out = [];
  for (const delay of [200, 1200, 3000]) {
    const before = c.events.length;
    await c.speak(q("Cipher, what's the capital of Japan?"));
    await c.waitFor((m) => m.type === "user_turn", 8000);
    await sleep(delay);
    await c.speak(q("And how many people live there?"));
    await c.settle(40000, 2500);
    const ev = c.events.slice(before);
    const turns = [...c.turns.values()].filter((t) => ev.some((m) => m.turnId === t.id && m.type === "thinking"));
    const row = {
      second_question_ms_after_first_was_taken: delay,
      turns_taken: ev.filter((m) => m.type === "user_turn").map((m) => m.text),
      replies: turns.map((t) => `${t.turn_cancelled ? "[dropped unheard] " : t.interrupted ? "[cut off] " : ""}${t.text.slice(0, 70)}`),
    };
    out.push(row);
    say(JSON.stringify(row));
    c.send({ type: "reset" });
    await sleep(1500);
  }
  return out;
});

// --- background noise ---------------------------------------------------------------------
await scenario("noise", async (c) => {
  const out = [];
  const speech = tts("Cipher, how many minutes are in three hours?");
  const level = rms(speech);
  const babble = tts("And in other news tonight, the city council voted to approve the new transit plan after months of debate, while local businesses say they are worried about the construction along the main street.", "Daniel");
  const cases = [
    ["quiet room", concat(speech, silence(300))],
    ["hiss, speech 10x louder (20 dB)", mix(concat(silence(600), speech, silence(1500)), noise(8000, level / 10))],
    ["hiss, speech 3x louder (10 dB)", mix(concat(silence(600), speech, silence(1500)), noise(8000, level / 3.16))],
    ["hiss as loud as the speech (0 dB)", mix(concat(silence(600), speech, silence(1500)), noise(8000, level))],
    ["another voice talking, half as loud", mix(concat(silence(600), speech, silence(2500)), babble, 0.5)],
    ["another voice talking, equally loud", mix(concat(silence(600), speech, silence(2500)), babble, 1)],
  ];
  for (const [label, pcm] of cases) {
    const r = await ask(c, pcm, { timeout: 30000 });
    const row = { room: label, answered: r.answered, heard_as: r.heard ?? `(${r.why})`, right_answer: /180|one hundred (and )?eighty/i.test(r.reply), wait_ms: r.eos_to_audio, reply: r.reply.slice(0, 60) };
    out.push(row);
    say(JSON.stringify(row));
    await c.settle(20000, 2500);
    c.send({ type: "reset" });
    await sleep(1500);
  }
  // Someone else talking (no wake word) right after Cipher answered: does it answer them too?
  await ask(c, q("Cipher, hello."));
  await c.settle(15000);
  const r = await ask(c, concat(tts("So anyway I told him the meeting was moved to Thursday and he was not happy about it.", "Daniel"), silence(300)), { timeout: 20000 });
  out.push({ room: "a different voice talks to someone else just after a reply", answered_them: r.answered, reply: r.reply?.slice(0, 80) ?? "" });
  say(JSON.stringify(out[out.length - 1]));
  return out;
});

save(`feel-${PORT}-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}`, results);
process.exit(0);
