// Dreaming, end to end, against a stand-in for the model (no API calls, no cost).
//   npm run test:dream
// Uses a throwaway data folder, so your real memory is never touched.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

process.env.DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "cipher-dream-"));
process.env.ANTHROPIC_API_KEY = "test-key-not-used";
process.env.DREAM_IDLE_MIN = "20";

const { memory } = await import("../server/memory.js");
const { transcripts, spokenWords } = await import("../server/transcripts.js");
const { wiki, slugify } = await import("../server/wiki.js");
const { dreamer } = await import("../server/dream.js");
const { recall } = await import("../server/recall.js");
type DreamModel = import("../server/dream.js").DreamModel;

/** A model that answers each step from a script and remembers what it was asked. */
function scripted(answers: Record<string, (user: string) => unknown>): DreamModel & { asked: Record<string, string[]> } {
  const asked: Record<string, string[]> = {};
  return {
    asked,
    async ask<T>(step: string, _system: string, user: string) {
      (asked[step] ??= []).push(user);
      const answer = answers[step];
      if (!answer) throw new Error(`unexpected step: ${step}`);
      return { data: answer(user) as T, usage: { input: 0, output: 0 } }; // a model that reports no tokens must still count
    },
  };
}
const idOf = (text: string): string => memory.list().find((i) => i.text === text)!.id;
const texts = (): string[] => memory.list().map((i) => i.text);

test("transcripts keep spoken words only, and can be searched", () => {
  assert.equal(spokenWords("Sure thing. [did: opened Safari] [mood: happy]"), "Sure thing.");
  assert.equal(transcripts.record("s1", "[Background job 3 finished]\nok\n[End of background note]", "Done."), 0);
  const a = transcripts.record("s1", "My sister Maya is getting married in Lisbon in June", "Oh, lovely! [mood: happy]");
  const b = transcripts.record("s1", "I need to book flights for it", "Want me to look? [mood: curious]");
  assert.ok(a > 0 && b > a);
  assert.equal(transcripts.get(a)!.assistant, "Oh, lovely!");
  assert.deepEqual(transcripts.around(b, 1).map((e) => e.id), [a, b]);
  assert.equal(transcripts.search("wedding in lisbon")[0].id, a);
  assert.deepEqual(transcripts.search("'; DROP TABLE exchanges; --"), []); // odd input is harmless
  assert.equal(transcripts.count(), 2);
});

test("page names are always safe file names", () => {
  assert.equal(slugify("Maya's Wedding!"), "maya-s-wedding");
  assert.equal(slugify("../../etc/passwd"), "etc-passwd");
  assert.equal(slugify("!!!"), "");
  assert.equal(wiki.write("../escape", "x", "y"), false);
  assert.equal(wiki.read("../escape"), null);
});

test("verify: confirms, corrects and removes facts against their exchange", async () => {
  const heard = transcripts.record("s2", "My dog is called Macks, no sorry, Max, M A X", "Got it, Max. [mood: happy]");
  const joke = transcripts.record("s2", "Ha, imagine if I moved to Mars", "That'd be a commute. [mood: playful]");
  await memory.apply({
    add: [
      { text: "Their dog is called Macks.", src: heard },
      { text: "They are moving to Mars.", src: joke },
      { text: "Their sister is called Maya.", src: 1 },
      { text: "They like tea.", src: 99999 }, // its exchange is gone: can't be checked
    ],
  });
  const model = scripted({
    verify: () => ({
      verdicts: [
        { id: idOf("Their dog is called Macks."), verdict: "corrected", text: "Their dog is called Max.", reason: "they spelled it out" },
        { id: idOf("They are moving to Mars."), verdict: "unsupported", text: "", reason: "a joke" },
        { id: idOf("Their sister is called Maya."), verdict: "supported", text: "", reason: "" },
        { id: "not-a-real-id", verdict: "unsupported", text: "", reason: "made up" },
      ],
    }),
    reflect: () => ({ add: [], remove: [], notes: [] }),
  });
  dreamer.useModel(model);
  const record = await dreamer.dream("light");

  assert.equal(record.status, "done");
  assert.ok(model.asked.verify[0].includes("M A X"), "the model is shown the exchange the fact came from");
  assert.equal(dreamer.records(1)[0].id, record.id, "the dream is recorded");
  assert.ok(!model.asked.verify[0].includes("They like tea."), "a fact with no transcript is not sent");
  assert.deepEqual(texts().sort(), ["Their dog is called Max.", "Their sister is called Maya.", "They like tea."]);
  assert.ok(memory.list().find((i) => i.text === "Their dog is called Max.")!.checked);
  assert.ok(memory.list().find((i) => i.text === "Their sister is called Maya.")!.checked);
  assert.ok(memory.forgotten().includes("They are moving to Mars."), "a wrong fact is not learned again");

  // Checked facts are not sent a second time.
  const again = scripted({ reflect: () => ({ add: [], remove: [], notes: [] }) });
  dreamer.useModel(again);
  await dreamer.dream("light");
  assert.equal(again.asked.verify, undefined);
});

test("reflect: reads only new exchanges, adds what was missed, never re-adds forgotten facts", async () => {
  const before = transcripts.newestId;
  const plan = transcripts.record("s3", "For the Lisbon trip I want to fly out on the twelfth and stay near Alfama", "Nice, Alfama's lovely. [mood: happy]");
  transcripts.record("s3", "Oh and I've gone vegetarian this year", "Good to know. [mood: calm]");
  const model = scripted({
    reflect: (user) => {
      assert.ok(user.includes("Alfama") && user.includes("vegetarian"));
      assert.ok(!user.includes("M A X"), "exchanges from before the last dream are not re-read");
      assert.ok(user.includes("- They are moving to Mars."), "the forgotten list is shown");
      return {
        add: [
          { text: "They are vegetarian.", src: plan + 1, reason: "a lasting preference" },
          { text: "They are moving to Mars.", src: plan, reason: "should be refused" },
        ],
        remove: [{ id: idOf("They like tea."), reason: "test" }],
        notes: [
          { page: "lisbon-trip", title: "Lisbon trip", text: "Flying out on the twelfth.", src: plan },
          { page: "lisbon-trip", title: "Lisbon trip", text: "Wants to stay near Alfama.", src: plan },
          { page: "../..", title: "!!!", text: "nowhere to go", src: plan },
        ],
      };
    },
  });
  dreamer.useModel(model);
  const record = await dreamer.dream("light");

  assert.equal(record.status, "done");
  assert.ok(before > 0);
  assert.ok(texts().includes("They are vegetarian."));
  assert.ok(!texts().includes("They are moving to Mars."));
  assert.ok(!texts().includes("They like tea."));
  const added = memory.list().find((i) => i.text === "They are vegetarian.")!;
  assert.equal(added.src, plan + 1);
  assert.ok(added.checked, "a fact written from the transcript itself needs no second check");
  const page = wiki.read("lisbon-trip")!;
  assert.equal(page.title, "Lisbon trip");
  assert.match(page.body, /Flying out on the twelfth\..*\n- Wants to stay near Alfama\./);
  assert.equal(wiki.list().length, 1, "a note with no usable page name is dropped");
  assert.equal(dreamer.status().newExchanges, 0);
});

test("recall finds pages and past conversations", () => {
  const out = recall.run({ type: "tool_use", id: "t1", name: "recall", input: { about: "Lisbon trip" } } as any);
  const text = String(out.content);
  assert.match(text, /From your notes on "Lisbon trip"/);
  assert.match(text, /From past conversations/);
  assert.match(String(recall.run({ type: "tool_use", id: "t2", name: "recall", input: { about: "quantum zebras" } } as any).content), /Nothing found/);
});

test("organise: merges, moves detail to pages, and refuses unsafe changes", async () => {
  await memory.apply({
    add: [{ text: "Their dog Max is a beagle." }, { text: "Max the dog is a beagle." }, { text: "Their flight to Lisbon is on the twelfth." }, { text: "They work as a nurse." }],
  });
  const model = scripted({
    reflect: () => ({ add: [], remove: [], notes: [] }),
    organise: (user) => {
      assert.ok(user.includes('page "lisbon-trip"'));
      return {
        reword: [{ id: idOf("Their dog is called Max."), text: "Their dog Max is a beagle.", reason: "merge" }],
        remove: [
          { id: idOf("Their dog Max is a beagle."), kind: "duplicate", page: "", reason: "same fact" },
          { id: idOf("Max the dog is a beagle."), kind: "duplicate", page: "", reason: "same fact" },
          { id: idOf("Their flight to Lisbon is on the twelfth."), kind: "moved", page: "lisbon-trip", reason: "trip detail" },
          { id: idOf("They work as a nurse."), kind: "moved", page: "no-such-page", reason: "should be refused" },
        ],
        pages: [
          { page: "lisbon-trip", title: "Lisbon trip", body: "Trip to Lisbon for [[maya]]'s wedding. Flying out on the twelfth; staying near Alfama.", reason: "tidy" },
          { page: "maya", title: "Maya", body: "Their sister. Getting married in Lisbon in June. See [[lisbon-trip]].", reason: "new page" },
        ],
        delete_pages: [],
      };
    },
  });
  dreamer.useModel(model);
  const record = await dreamer.dream("deep");

  assert.equal(record.status, "done");
  assert.deepEqual(texts().sort(), ["Their dog Max is a beagle.", "Their sister is called Maya.", "They are vegetarian.", "They work as a nurse."]);
  assert.ok(!memory.forgotten().includes("Max the dog is a beagle."), "merged facts are not marked as wrong");
  assert.match(wiki.read("lisbon-trip")!.body, /\[\[maya\]\]/);
  assert.deepEqual(wiki.brokenLinks(), []);
  assert.match(wiki.describe(), /Lisbon trip; Maya/);

  // Undo puts the list and the pages back, and keeps what was learned afterwards.
  await memory.apply({ add: [{ text: "They started running." }] });
  const undone = await dreamer.undo();
  assert.equal(undone?.id, record.id);
  assert.ok(texts().includes("Their flight to Lisbon is on the twelfth."));
  assert.ok(texts().includes("Their dog is called Max."));
  assert.ok(texts().includes("Max the dog is a beagle."));
  assert.ok(texts().includes("They started running."));
  assert.equal(wiki.read("maya"), null);
  assert.match(wiki.read("lisbon-trip")!.body, /^- Flying out/);
  assert.equal(await dreamer.undo(record.id), null, "a dream is undone only once");
});

test("organise never drops a large part of memory in one go", async () => {
  const count = memory.list().length;
  dreamer.useModel(
    scripted({
      reflect: () => ({ add: [], remove: [], notes: [] }),
      organise: () => ({ reword: [], pages: [], delete_pages: [], remove: memory.list().map((i) => ({ id: i.id, kind: "outdated", page: "", reason: "runaway" })) }),
    }),
  );
  await memory.apply({ add: Array.from({ length: 20 }, (_, n) => ({ text: `Filler fact number ${n}.` })) });
  const record = await dreamer.dream("deep");
  assert.equal(memory.list().length, count + 20);
  assert.ok(record.steps.at(-1)!.changes.some((c) => c.what === "skipped" && /looked like a mistake/.test(c.reason ?? "")));
});

test("a dry run changes nothing", async () => {
  transcripts.record("s4", "I'm learning Portuguese", "Boa sorte! [mood: happy]");
  const before = JSON.stringify([memory.list(), wiki.list().map((p) => p.body), dreamer.status().newExchanges]);
  dreamer.useModel(
    scripted({
      reflect: () => ({ add: [{ text: "They are learning Portuguese.", src: transcripts.newestId, reason: "new" }], remove: [], notes: [{ page: "portuguese", title: "Portuguese", text: "Started learning.", src: transcripts.newestId }] }),
      organise: () => ({ reword: [], pages: [], delete_pages: [], remove: [{ id: memory.list()[0].id, kind: "outdated", page: "", reason: "test" }] }),
    }),
  );
  const record = await dreamer.dream("deep", { dry: true });
  assert.ok(record.dry);
  assert.ok(record.steps.flatMap((s) => s.changes).some((c) => c.what === "added" && c.detail === "They are learning Portuguese."));
  assert.equal(JSON.stringify([memory.list(), wiki.list().map((p) => p.body), dreamer.status().newExchanges]), before);
});

test("a dream gives way when a conversation starts, and a failed step stops the rest", async () => {
  let release!: () => void;
  const held = new Promise<void>((r) => (release = r));
  let organised = false;
  dreamer.useModel({
    async ask<T>(step: string) {
      if (step === "reflect") await held;
      if (step === "organise") organised = true;
      return { data: { add: [], remove: [], notes: [], reword: [], pages: [], delete_pages: [], verdicts: [] } as T, usage: { input: 1, output: 1 } };
    },
  });
  const running = dreamer.dream("deep");
  dreamer.touch(); // someone starts talking mid-dream
  release();
  const record = await running;
  assert.equal(record.status, "interrupted");
  assert.equal(organised, false);

  dreamer.useModel(scripted({ reflect: () => { throw new Error("network down"); } }));
  transcripts.record("s4", "One more thing to say", "Mm-hm. [mood: calm]");
  const failed = await dreamer.dream("deep");
  assert.equal(failed.status, "failed");
  assert.equal(failed.steps.at(-1)!.error, "network down");
  assert.ok(dreamer.status().newExchanges > 0, "exchanges a failed dream did not read are still waiting");
});

test("dreams wait for quiet, and are skipped while memory is off", () => {
  const now = Date.now();
  assert.equal(dreamer.due(now), null, "not while someone was just talking");
  assert.notEqual(dreamer.due(now + 26 * 60 * 60 * 1000), null, "due after a long quiet spell");
  memory.setEnabled(false);
  assert.equal(dreamer.due(now + 26 * 60 * 60 * 1000), null);
  memory.setEnabled(true);
});
