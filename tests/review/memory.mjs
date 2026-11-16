// Memory: does what Cipher learns in one conversation change what it does in the next?
// (There is no "dreaming" or consolidation step in the code to test; this tests the
// memory that does exist.) Run against the isolated test copy, which has its own memory file.
// Usage: PORT=3111 DATA_DIR=<the test copy's data folder> node tests/review/memory.mjs
import fs from "node:fs";
import path from "node:path";
import { connect, typed, sleep, save, PORT } from "./lib.mjs";
const file = path.join(process.env.DATA_DIR ?? "", "memory.json");
const items = () => {
  try {
    const j = JSON.parse(fs.readFileSync(file, "utf8"));
    return (Array.isArray(j) ? j : j.items ?? []).map((m) => m.text);
  } catch {
    return [];
  }
};
const about = (re) => items().filter((t) => re.test(t));
const fresh = async (label, text, wait = 7000) => {
  const c = await connect(label);
  await c.start();
  const r = await typed(c, text);
  await sleep(wait); // the note-taking call runs after the reply
  await c.close();
  console.log(`- ${text}\n    -> ${r.reply.slice(0, 200)}`);
  return r.reply;
};
const out = { before: items().length };
out.told = await fresh("mem-tell", "By the way, my sister Priya just moved to Toronto, and she's allergic to peanuts.");
out.stored_after_telling = about(/priya|sister/i);
console.log("    stored:", out.stored_after_telling);
out.recall_new_conversation = await fresh("mem-recall", "Where does my sister live?", 1500);
out.recalled = /toronto/i.test(out.recall_new_conversation);
out.corrected = await fresh("mem-correct", "Actually my sister Priya moved again. She lives in Boston now, not Toronto.");
out.stored_after_correction = about(/priya|sister/i);
console.log("    stored:", out.stored_after_correction);
out.recall_after_correction = await fresh("mem-recall2", "Remind me, which city is my sister in?", 1500);
out.correct_after_correction = /boston/i.test(out.recall_after_correction) && !/toronto/i.test(out.recall_after_correction);
out.forget = await fresh("mem-forget", "Please forget that my sister is allergic to peanuts.");
out.stored_after_forget = about(/peanut|allerg/i);
out.claimed_forgotten = /forg|won'?t (keep|remember)|removed|gone|done/i.test(out.forget);
console.log("    still stored about the allergy:", out.stored_after_forget);
out.preference = await fresh("mem-pref", "From now on, whenever I ask you for a number, give me just the number and nothing else. Remember that.");
out.stored_preference = about(/number/i);
out.preference_used_later = await fresh("mem-pref2", "How many days are there in a week?", 1500);
out.followed_preference = /^\W*(7|seven)\W*$/i.test(out.preference_used_later.trim());
out.after = items().length;
console.log(JSON.stringify({ recalled: out.recalled, correct_after_correction: out.correct_after_correction, claimed_forgotten: out.claimed_forgotten, still_stored_after_forget: out.stored_after_forget.length, stored_preference: out.stored_preference, followed_preference: out.followed_preference, items_before: out.before, items_after: out.after }, null, 1));
save(`memory-${PORT}-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}`, out);
process.exit(0);
