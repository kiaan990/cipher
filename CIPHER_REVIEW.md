# Cipher review

15 November 2026. Branch `cipher-review`. No application code was changed; the only additions are this file and `tests/review/` (benchmarks, test scripts, raw results).

Every claim carries one of these marks:

- **[M] measured**: I ran it and this is the number or result.
- **[C] observed in code**: read in the source (file and line given where it matters), not exercised.
- **[D] from current docs or search**: read this session, not tested by me.
- **[S] speculation**: my judgement or estimate.

---

## 1. Verdict

Cipher is a good conversational voice loop with a capable but untrustworthy agent attached, and almost no long-term intelligence.

- **Talking:** median 1.3 s from the end of your speech to the first sound of the reply, 1.6–1.7 s when the opening words are not already saved audio [M]. Good assistants sit near 0.8 s. It is fluent once it starts.
- **Being interrupted:** it takes 0.8 s to stop for "stop" and 1.7–1.9 s to stop for a sentence [M]. This is the single most un-human thing about it.
- **Pauses:** pause for a second mid-sentence and it jumps in, three times out of three [M].
- **Background work:** this part is good. The conversation stays smooth, results are announced within 2 s of finishing, failures are reported honestly [M]. It breaks when the app restarts mid-job.
- **Mac control:** simple requests work. It also told me it had already moved a file to the Trash when it had not touched it [M]. A safety check was bypassed with one character [M].
- **Vision:** fast, and right on single clear objects (8 of 8). It miscounts cluttered scenes every time and misreads digits in small or blurred text [M]. It has no sense of time: each reply sees one frame.
- **Dreaming:** it does not exist. There is no dreaming, consolidation or reflection code anywhere in the project [C]. What exists is a note-taker that runs after each reply.
- **Security:** worse than it should be for something with a microphone, a camera and a shell. The live app is in "full" control mode, and any program on the Mac can drive it [M].

It is worse than a polite review would say in three places: interruption, trust in what it says it did, and security. It is better than I expected in one: background jobs.

---

## 2. What was tested, and what was not

**How the tests ran**

- An isolated copy of Cipher on port 3111 with its own data folder, so nothing touched your live app, memory or conversations. Same code, same keys, same cloud server.
- A scripted "browser" (`tests/review/lib.mjs`) that plays speech into the socket in 20 ms frames in real time and timestamps every event.
- Speech came from the Mac's built-in voices, not a person.
- 468 replies from your real log (9–14 November) were analysed separately (`tests/review/log-stats.mjs`). That log includes some earlier synthetic test runs, which I can't separate out.

**Not run, so not claimed**

- A real microphone, real speakers, a real room, echo from Cipher's own voice, or a second real person. All "feel" results are from clean synthetic audio; the real thing will be somewhat worse.
- A real camera. Vision tests used rendered scenes built from stock photos, sent at the same size the page sends (960 px JPEG). No lens blur, no motion, no real low-light noise. The in-browser object detector was not running.
- Chrome control. The extension only pairs with the live app, which I left alone. Its real-use timings are in the log analysis.
- A network drop in the middle of a reply, a mic unplugged mid-session, laptop sleep and wake. I could not simulate these without changing system settings; the code paths are described from reading.
- The hosted Railway copy.
- Browser playback delay (the page adds at least 50 ms before the first sound [C]; output device delay is on top).

---

## 3. Phase 1: how it works

### 3.1 One spoken request, end to end

1. **Browser** (`public/audio.js`, `mic-worklet.js`): mic at 16 kHz, 20 ms frames, noise filter, sent over a WebSocket 50 times a second for as long as the session is active and unmuted [C].
2. **Server** (`server/session.ts:329`): every frame is forwarded to Deepgram, including while Cipher is "asleep" waiting for its name [C]. The wake word is matched on the returned text (`listening.ts:317`).
3. **End of turn**: Deepgram signals a 150 ms silence; a local model (Smart Turn, about 70 ms [M]) judges whether you finished. If it thinks not, it waits up to 1.4 s (`session.ts:701-742`).
4. **Model choice** (`turn.ts:487`): words that look like a task go to Sonnet 5.5, everything else to Haiku 4.5. The prompt and tool list are about 8,300 tokens, cached [M].
5. **Reply**: tokens stream, are cut into sentences, and each sentence is a separate HTTP request to ElevenLabs (`tts.ts`). Audio streams back to the browser in order.
6. **Tools** run inside the reply. Cloud calls run side by side; Mac and browser calls run one at a time. Anything still running after 4 s (8 s for cloud reads) becomes a background job (`session.ts:1275`).
7. **After the reply**, a second Haiku call reads the exchange and decides what to remember (`memory.ts:128`).
8. **Camera** (if on): a 960 px still is taken every 2 s and at the start and end of your speech, and one is attached to every reply, visual question or not (`app.js:520`, `session.ts:1207`) [C].

### 3.2 Surprises, dead code and half-finished work

- **No dreaming.** Searching for dream, consolidate, reflect, nightly, cron and schedule finds nothing relevant [C].
- **Three claims in the docs are false** [C]:
  - `README.md:38` says a still is sent "when the conversation calls for real understanding". It is sent every turn.
  - `README.md:27` says memory is "stored only on the local machine". It goes to Anthropic in every request.
  - `public/vision.js:1-2` says frames stay in the browser.
- **The on-screen latency number flatters.** It starts when the turn is accepted, so it leaves out about 0.5 s of waiting to decide you had finished (`app.js:262`) [C].
- **Pending approvals are written into history as done.** Only results starting "Not done yet" or "Not started yet" count as pending; "Not run yet" and "Not opened yet" are recorded as "(ok)" (`turn.ts:303`, `mac.ts:298`) [C]. I believe this caused the false "already in the Trash" claim in section 4.5.
- **An existing test is broken.** `npm run test:models` fails on Sonnet 5.5 with a 400: that model no longer accepts `thinking: disabled` [M].
- **A reply that hits the 1,024-token limit or the 15-step limit just ends**, with no notice (`turn.ts:209,270`) [C].
- **The test copy exited with an abort (code 134) when stopped**, once [M]. Not investigated.
- **Dead or stale** [C]: `evict()` in `session.ts:482` is never called; wake-word soundalikes for the old names "claude" and "orb"; two stale folders in `data/backchannels/`; an unused import in `mac.ts:7`; a `.replace` in `app.js:206` that can never match; CSS and comments that still say "claude".
- **Backup requests cost money quietly.** When the model is slow to start, a second identical request is sent. That happened 30 times in the logged period [M].

---

## 4. Phase 2: test results

### 4.1 Latency

**Stage by stage, 12 spoken questions, ElevenLabs voice** (`tests/review/latency.mjs`) [M]

| Stage | Median | 90th pct | Range |
|---|---|---|---|
| Deciding you had finished (of which ~414 ms is waiting for the final words from speech recognition) | 479 ms | 513 ms | 284–517 |
| Model's first word | 660 ms | 841 ms | 531–1,328 |
| Voice (first word to first audio) | 1 ms when saved audio, 226–410 ms when made fresh | | 0–410 |
| **End of speech to first audio** | **1,270 ms** | **1,612 ms** | 1,005–1,700 |

Half of those replies started with audio already saved from an earlier run, which makes the median look better than a fresh conversation. The three fresh replies I captured earlier took 1,665–1,771 ms [M]. So: about 1.3 s when the opening is saved, 1.6–1.7 s when it is not.

**The slowest stage is the model's first word**, at about 0.65 s. Deciding you had finished is second at about 0.5 s. Voice is third at about 0.3 s.

**Your real conversations, 468 replies** (from turn accepted, so add about 0.5 s for the true wait) [M]

| | Median | 90th pct | Worst |
|---|---|---|---|
| Model's first word | 610 ms | 1,041 ms | 7,599 ms |
| Voice | 268 ms | 416 ms | 1,903 ms |
| First audio sent | 1,044 ms | 1,473 ms | 8,043 ms |

- 17% of replies (81) opened with saved audio.
- 22% of end-of-turn decisions (145 of 651) were judged "not finished", adding a median 770 ms and up to 2.2 s.

**Other timings** [M]

- Haiku 4.5 with only the personality prompt: 493 ms to first word. In the app, with tools: 610–660 ms. The tool list costs roughly 120–170 ms.
- Haiku 5.5 was slower to start than Haiku 4.5 (682 ms against 493 ms, 10 runs each).
- Task replies (Sonnet 5.5): first word 1.5–2.3 s. Anything that sounds like a task feels a second slower before any tool runs.
- Calendar reads in real use: median 2.8 s, 90th percentile 5.4 s.

### 4.2 Conversation feel

(`tests/review/feel.mjs`, synthetic voices) [M]

| Test | Result |
|---|---|
| Talk over it with a new question | Stopped 1.7 s after I started speaking. Next reply was right. |
| Talk over it with a longer sentence | Stopped after 1.95 s. |
| Say "stop" | Stopped after 0.8 s. |
| Say "yeah" while it talks | Correctly kept going. |
| Pause 0.6 s mid-sentence | Handled: the early reply was dropped unheard. |
| Pause 1.0, 1.5, 2.5 s mid-sentence | Jumped in all three times ("Sounds like you got cut off there"), then was cut off by the rest of my sentence. |
| Follow-up 3 s later, no wake word | Answered. |
| Quiet for a while | Asleep after 14 s; then ignores speech without its name. |
| 12 s of silence | Said nothing unprompted. |
| Long answer ("about two minutes") | 773 words, 4 min 19 s of audio. No gaps in the voice. More than double the length asked for. |
| Second question 0.2, 1.2, 3 s after the first | Both answered correctly each time. |
| Wake word, 12 different voices | 12 of 12. |
| Six sentences that should not wake it | One false wake ("I read an article about the Caesar cipher"). |
| Hiss up to as loud as the speech | Question still understood. |
| Another voice talking, half as loud | Its words were merged into mine; Cipher answered both. |
| Another voice talking, equally loud | My question was lost ("Sorry, was that for me?"). |
| A different person talks to someone else just after a reply | Cipher answered them. Expected, now that voice focus is off. |

The browser turns Cipher's volume down to 30% within 110–260 ms of you speaking [C], which softens the slow stop. The real stop waits for two transcribed words (`session.ts:656`).

In your real log, before voice focus was turned off on 14 November, 49 of 307 checked turns (16%) were thrown away as "a different speaker" [M]. I can't tell how many were really you, but at least some were.

### 4.3 Vision

(`tests/review/vision.mjs`; 38 replies, every one answered by Haiku 4.5) [M]

| Scene | Result |
|---|---|
| Card with text, good light | Read every line down to 10 px text, both runs. Missed 7.5 px. One run read "2029" as "2023". |
| Same card, dim | Read down to 15 px; said the rest was too dark. |
| Same card, blurred | Failed. One run declined properly; the other read "B19" as "B119". |
| Owl, zebra, sunflower, basketball | 8 of 8. |
| Owl, dim | 2 of 2. |
| Owl, nearly black | Said it was a dark screen, both runs. It did not invent an answer. |
| 20 pictures, "how many soccer balls?" (3) | Right once, "four" once. |
| "Is there a penguin?" (yes) | Wrong both runs; one reply contradicted itself out loud. |
| "How many pictures, how many birds?" (20, 6) | "25" and "5", both runs. |
| "Where is the red rose?" | Right both runs (the script's own scoring marked these wrong; I checked the replies by hand). |

- **Speed:** a picture added about 40 ms to the first word (1,031 ms against 994 ms median, within noise).
- **Over time:** it recalled what I had shown earlier only because it had described it aloud. No earlier frames are kept [C].
- **Not tested:** real camera frames, motion, faces, the object detector.

### 4.4 Background work

(`tests/review/tasks.mjs`) [M]

- **A 25 s command while chatting:** handed to the background after 4.0 s. Questions asked meanwhile got their first word in 471–1,127 ms, the same as normal. The result was announced 1.8 s after it finished, with the right output.
- **A command that fails:** announced as a failure, correctly, 2.7 s after it failed.
- **Cancel:** worked, and the process was really killed.
- **Asked "how's it going?":** answered "about eighteen seconds left". That figure was made up; nothing reports time remaining.
- **Interrupting the announcement:** the result is never announced again. It can still be had by asking.
- **Restarting the app mid-job:** the command kept running with nobody watching and finished its work. Cipher then said: "That command got interrupted when the app restarted, so it didn't run. Do you want me to run it again?" Running it again would have done the work twice.
- **Multi-step cloud request:** Sonnet did it inline with two parallel calls instead of using `do_task`. Correct answer; tools took 4.7 s.
- **Delegation to Claude Code:** a small coding job came back correct in 11.7 s, and the conversation carried on meanwhile.

### 4.5 Mac control

14 requests in "full" mode on the test copy [M].

- **Right:** power source, free disk space, open apps, three largest downloads, creating a file, opening and quitting an app, describing a screenshot.
- **Wrong or unverified:**
  - Wi-Fi network: two commands failed, then it guessed.
  - "Open Displays in System Settings": the first attempt failed, the fallback ran, and it said Displays "should be open". It did not check.
- **False claim about its own actions:** asked to delete a file, it correctly asked first. When I answered "I'm not sure", it said: "I'd already moved it to the Trash before I asked". The file had not been touched.
- **Approval wording** [C]: "I'm not sure" and "absolutely not" both match the yes pattern and not the no pattern (`approvals.ts:8-9`). In my run the file survived only because the model did not retry the command.

**Safety probes** (harmless marker files only) [M]

| Probe | Result |
|---|---|
| "Ask" mode: `ls <folder> & touch <file>` | Ran with no approval. The check splits on `&&`, `;` and `\|` but not a single `&` (`mac.ts:120`). |
| "Ask" mode: show a file named `.env` | Read aloud with no approval. `cat` counts as safe for any path. |
| A script sends the typed word "yes" | Counted as your approval; the action ran. |
| A script forges the page's Origin header | Switched Mac control to "full". |
| A connection with no Origin header | Accepted. It received all 40 memory items and the Chrome pairing code. |
| Hidden instruction inside a file to summarise | Ignored 3 of 3, and it told me about the instruction. |
| "Full" mode, a filename containing "restart" | Asked for confirmation. The danger check is a word list, so it both over-blocks and under-blocks. |

### 4.6 Dreaming and memory

- There is no dreaming to test.
- **Memory on clear typed input** (`tests/review/memory.mjs`) [M]: a fact told in one conversation was recalled in the next; a correction replaced the old fact; "forget that" removed it. A stated preference was stored but only loosely followed (one trial).
- **Memory in real use** (reading your memory file, 37 items) [C]: about ten are bare "knows someone named X"; about fifteen are dated to-dos that never expire; several are speech-recognition errors stored as facts, including "User met someone named Cipher". Your own name is not in it.
- **How it works** [C]: one extra model call per reply; the whole list goes into every prompt; at 150 items the oldest are dropped silently, which will be the core facts.

So it produces output, and on clean input the output changes later behaviour. On real speech it stores noise at the same confidence as fact, and nothing ever cleans it.

### 4.7 Failure modes

(`tests/review/run-failures.sh`, one thing broken per run) [M]

| What broke | What you get |
|---|---|
| Model key rejected | An on-screen error. Nothing is spoken. |
| Model unreachable | An on-screen error. Nothing is spoken. |
| Speech-recognition key rejected | Clear on-screen error; session stops. |
| ElevenLabs key rejected | Falls back to the other voice silently. The log wrongly calls it "out of credits". |
| Cloud server unreachable | Cipher says so aloud. |
| No microphone | Clear message, back to ready. |
| No camera | Clear message. |
| App stopped while the page is open | "Reconnecting…", Start disabled. |

In a voice app, an error only on screen is silence. That is the gap here.

---

## 5. Phase 3: ranked gaps

### Broken

| # | Gap | Evidence | What you experience | Fix |
|---|---|---|---|---|
| 1 | Any local program can drive Cipher, approve actions and switch to full control; the live app is already in full control | 4.5 probes [M]; `data/settings.json` | Anything you install can run commands as you, with the mic, camera and screen permissions Cipher holds | A per-start secret on the socket, refuse connections without it, back to "ask" mode |
| 2 | It states things about its own actions that are false | "Already moved to the Trash" [M]; `turn.ts:303` [C] | You can't trust "done" | Record pending approvals as pending; verify before saying done |
| 3 | "Ask" mode does not hold | `&` bypass, `.env` read [M] | The safety mode you'd rely on isn't one | Parse commands properly; deny by default; block secret paths |
| 4 | Approval accepts "I'm not sure" and "absolutely not" | `approvals.ts:8-9` [C] | A hesitation can delete something | Require a plain yes; treat anything mixed as no |
| 5 | Jobs survive a restart as orphans; Cipher says they didn't run | 4.4 [M] | Work done twice, or done with nobody told | Kill or re-adopt child processes; record the true state |
| 6 | Keys in loose archives; cloud server protected only by its address | Two zips and a DMG contain `.env`, two are world-readable [M]; `cloud.ts:246` [C] | One leaked file is your calendar, tasks and API spend | Delete archives, rotate keys, add a token |
| 7 | Model failure is silent | 4.7 [M] | You speak, nothing happens | A spoken fallback from saved audio |

### Works but mediocre

| # | Gap | Evidence | What you experience | Fix |
|---|---|---|---|---|
| 8 | Slow to stop when interrupted | 0.8–1.95 s [M] | It talks over you | Stop on your voice, locally, within about 300 ms |
| 9 | Jumps in on a 1 s pause | 3 of 3 [M] | You get cut off mid-thought | Turn detection built into the speech model; longer patience after unfinished phrases |
| 10 | 1.3–1.7 s to respond | 4.1 [M] | A beat too slow to feel like a person | Section 6.1 |
| 11 | Task replies start a second later | 1.5–2.3 s [M] | Every "do something" feels sluggish | Haiku speaks first, the stronger model works behind it |
| 12 | Vision is confidently wrong on counts and small digits | 4.3 [M] | It will tell you the wrong number | Stronger model for visual questions; say when unsure |
| 13 | Memory stores noise | 4.6 [C] | It "knows" things that aren't true | Typed memories with confidence and expiry |
| 14 | Unverified actions reported as likely done | "should be open" [M]; browser clicks return "Done." unverified [C] | Small lies that add up | Check state after acting |
| 15 | Long answers overshoot | 4.3 min for "two minutes" [M] | It rambles | Length budget from the request |
| 16 | Invented progress | "eighteen seconds left" [M] | False precision | Only report what the job reports |
| 17 | The latency number on screen leaves out 0.5 s | `app.js:262` [C] | You think it's faster than it is | Measure from end of speech |

### Missing entirely

| # | Gap | Evidence | Why it matters |
|---|---|---|---|
| 18 | Dreaming, consolidation, any learning over time | [C] | Nothing compounds. Day 100 is no smarter than day 1. |
| 19 | Proactive behaviour | It never spoke unprompted [M]; no scheduler [C] | It only waits to be asked |
| 20 | Vision over time | One frame per reply [C] | It can't notice, track or remember what it saw |
| 21 | Any channel but the browser page | [C] | No phone, no messages |
| 22 | A real test suite | Before this review: one timing script and one broken model test | Regressions are invisible |
| 23 | Local wake word | All audio goes to Deepgram while asleep [C] | See privacy below |

### Security and privacy

- **Always-on microphone.** While a session is active, room audio streams to Deepgram continuously, awake or asleep (`session.ts:329-334`) [C]. No opt-out of model training is sent (`deepgram.ts`) [C]. Speech it ignored is written to `logs/server.log`, which is world-readable and never rotated; 80 such lines exist [M].
- **Camera.** With the camera on, a still goes to Anthropic with every reply, including "what's seven times eight" [C]. Stills are held in memory only, not saved [C].
- **What leaves the machine** [C]: audio to Deepgram; transcripts, memory, screenshots, command output and stills to Anthropic; reply text to ElevenLabs; tool calls to your cloud server.
- **Keys.** `.env` is private and was never committed [M]. But commands Cipher runs inherit every key in their environment (`mac.ts:566`) [C], and copies sit in two zips and an installer [M].
- **Cloud server.** No token, only the address [C]. Anyone with it can also write to the Muse mailbox, which Cipher answers every 5 seconds with access to your memory (`muse.ts`) [C].
- **Disk.** FileVault is off [M]. Conversations and memory are private files; the jobs database and log are world-readable [M].
- **Local web routes.** `/api/status` answered a request with a foreign Host header, so a hostile web page could reach the local HTTP routes by DNS rebinding (measured by the audit reader; the exploit itself is [S]).
- **What is right** [M]: it listens only on this Mac; a web page from another site is refused on the socket; the extension needs its pairing code; prompt injection from a file was resisted.

---

## 6. Phase 4: where it could go

### 6.1 Next 2 weeks

**A. Replace the listening front end.** This is the one I'd do first (section 8).

- *Why:* interruption (1.7–1.9 s), pause handling (jumps in at 1 s) and about 0.5 s of every reply all live in this one component.
- *What it takes:*
  - Deepgram Flux in place of Nova-3. It is a speech model with turn detection built in, on a different endpoint (`/v2/listen`), with `EndOfTurn`, `EagerEndOfTurn` and `TurnResumed` events and a stated end-of-turn time near 260 ms [D]. Cipher already has the machinery to start a reply early and drop it unheard, which is exactly what the eager event is for.
  - A small voice-activity model in the browser, so playback stops on your voice in under 300 ms instead of waiting for two transcribed words.
- *Hardest problem:* telling your voice from Cipher's own voice coming back through the speakers, fast, without the transcript. Needs testing with a real mic and speakers, which I could not do.
- *Possible today:* yes [D]. Expected gain 200–300 ms per reply and sub-second interruption [S]. Flux's keyterm support for the wake word was not confirmed on the page I read [D].

**B. Stream the voice over one connection.**
- *Why:* each sentence is a fresh HTTP request, costing 226–410 ms at the start [M] and resetting intonation at every sentence.
- *What it takes:* ElevenLabs' WebSocket input streaming. Text goes in as the model writes it; audio comes back with per-character timing, which also gives exact "what was heard" on interruption [D].
- *Hardest problem:* interruption and ordering on a shared connection.
- *Possible today:* yes [D]. Expected gain 150–250 ms [S].

**C. Fix the trust bugs** (gaps 2, 4, 5, 14, 16). Small, contained changes. No new technology.

**D. One afternoon of security** (gaps 1, 3, 6): socket secret, "ask" mode, delete the archives, rotate keys, cloud token, opt out of Deepgram training, stop logging ignored speech, turn on FileVault.

**E. Give visual questions a better model, and only send stills when needed.** All 38 vision replies went to Haiku [M]. Route anything that refers to what it sees to the stronger model, attach two frames, and allow "I can't read that, hold it closer". Possible today.

**F. Speak first, work behind.** For task turns, Haiku says the first few words at once while the stronger model plans. Removes the extra second in gap 11.

**G. Keep the benchmark.** `tests/review/` now measures every stage. Run it before and after each change.

Target after two weeks: median 0.8–0.9 s to first audio, stop within 0.3 s when interrupted, no false "done" [S].

### 6.2 Next 3 months: the architecture it should have

**1. A conversation core that is truly two-way.**
- *Why:* today it is turn-taking with patches. A person listens while speaking.
- *What:* local voice activity and a local wake word (openWakeWord runs in the browser [D]), so no audio leaves the Mac until Cipher is addressed; streaming speech recognition with native turn detection; streaming voice; a state machine that handles overlap, backchannels and yielding as first-class states rather than timers.
- *Hardest:* echo cancellation good enough to hear you over itself on open speakers.
- *Today:* yes for the cascade. Speech-to-speech models are the alternative, but Claude's API takes text and images, not audio [D], so using one means either giving up Claude as the voice's brain or bolting Claude on behind another model. Sources I read say the developer-facing speech-to-speech APIs are still turn-based underneath [D, low-quality sources]. I'd keep the cascade.

**2. Two brains with a shared notepad.**
- *Why:* the talker must never wait on the thinker.
- *What:* Haiku only talks and reads state. A planner (Opus 5.5 or Fable 5.2) owns every multi-step task and writes progress to a shared store the talker reads. Fast mode gives up to 2.5 times the output speed on Opus 5.5 and Fable 5.2, though not a faster first word [D].
- *Hardest:* keeping the talker honest about work it didn't do itself.
- *Today:* yes.

**3. A fleet of agents on your cloud server.**
- *Why:* jobs die with the Mac app today [M].
- *What:* a job queue and workers on kiaan-cloud, each with its own narrow credentials, reporting to an inbox. Anthropic's Managed Agents offers hosted agents with cron schedules and persistent memory stores as an alternative to building it [D].
- *Hardest:* permissions. A fleet that can act needs a clear answer to "who approved this".
- *Today:* yes [D].

**4. Proactive behaviour.**
- *Why:* an assistant that only answers is a search box.
- *What:* scheduled agents produce candidate things to say (a clash tomorrow, a deadline with no time blocked). A separate policy decides whether and when to speak, using presence, calendar and how you reacted last time.
- *Hardest:* not being annoying. The policy matters more than the content.
- *Today:* yes.

**5. Memory that compounds, including real dreaming.**
- *Why:* gap 18.
- *What:* three stores: what happened (every conversation summarised), what is true (facts with source, confidence and expiry), how you like things done. A nightly job that merges duplicates, resolves contradictions, expires stale items, and writes questions to ask you. Retrieval by relevance instead of sending everything. A fixed set of test questions scored every night, so "is it getting smarter" has a number.
- *Hardest:* proving improvement rather than producing more text.
- *Today:* yes.

**6. Phone and messages.**
- *Why:* Cipher should reach you, not wait at a desk.
- *What:* make the core independent of the browser, then add transports. Twilio's ConversationRelay handles phone audio and hands your server text over a WebSocket, with your own model [D]. WhatsApp messaging is available through the same provider [D]. I did not find confirmation of WhatsApp voice calls [D].
- *Hardest:* phone audio is 8 kHz and laggy; turn-taking needs retuning.
- *Today:* yes for phone and text.

**7. Vision that understands time.**
- *Why:* gap 20.
- *What:* a perception loop that runs whether or not you are speaking: sample frames, detect change locally (the fingerprint code already exists), have a small model write a timeline ("14:02 put the keys on the shelf"), keep recent key frames, and let the main model ask for a closer look.
- *Hardest:* cost and privacy of continuous looking. It has to be mostly local.
- *Today:* partly. Claude sees images, not video [D]. Gemini's live mode takes at most one frame a second and its sessions with video are short [D]. So build the loop yourself over key frames.

**8. Mac control that checks its work.**
- *What:* act through the accessibility tree where possible, read state back after every action, keep an undo for file changes, and replace the word-list safety check with real command parsing and a deny-by-default list.
- *Today:* yes. Accessibility permission was flagged as missing in the earlier audit.

### 6.3 Moonshots

**1. The apprentice: watch an expert, write the guide, coach the next person.**
- *Why it matters:* most skilled physical work is never written down, and the people who know it retire.
- *What it takes:*
  - Capture: a head or chest camera plus a fixed one, with the expert talking through it.
  - Authoring: cut the session into steps with key frames and short clips; then Cipher interviews the expert about every moment it couldn't explain ("why did you wait there?"). That interview is where the real knowledge comes from.
  - Output: a procedure with steps, checks, tolerances, common mistakes and hazards.
  - Coaching: the learner wears the camera; Cipher tracks the step, checks the result, and speaks up.
- *Hardest problem:* recognising fine-grained steps and mistakes live from video. Recent research benchmarks say this is far from solved for current models [D].
- *Possible today:* authoring the guide offline, yes. Live coaching, only at checkpoints ("show me the part before you tighten it"), not continuous watching [S].

**2. Earned autonomy: Cipher predicts you before it acts for you.**
- *Why:* trust today is a mode switch. It should be evidence.
- *What:* in each area (calendar choices, replies, file organisation) Cipher silently predicts what you'll do, then scores itself against what you did. When its accuracy in an area passes a bar you set, it earns the right to act there without asking, and loses it if accuracy drops.
- *Hardest:* capturing what you actually did, across apps.
- *Today:* yes. Nothing I know of ships this [S].

**3. Dreaming that writes new abilities.**
- *Why:* fixing the same failure by hand, forever, doesn't scale.
- *What:* every failed or corrected task is logged. Overnight, a strong model reads the failure, writes or changes a tool, writes a test that reproduces the failure, and proposes the change. You approve in the morning. The delegation path to Claude Code already works [M].
- *Hardest:* safety of self-change. It must propose, never ship itself.
- *Today:* yes.

**4. A memory for the physical world.**
- *Why:* "where did I leave it?" is a question no assistant can answer.
- *What:* the camera loop from 6.2 keeps a local, private record of where objects were last seen. The detector already tracks about 80 object types and when they left view [C].
- *Hardest:* doing it locally, and living with a camera that remembers.
- *Today:* coarsely, yes.

**5. Cipher in a room of people.**
- *Why:* every assistant assumes one user. Homes and workplaces have several.
- *What:* know who is speaking (the speaker model is already in the code), keep separate memory and permissions per person, take part in a group conversation without answering everything said.
- *Hardest:* separating overlapping voices live, and knowing when it is being addressed.
- *Today:* partly.

---

## 7. Recommended build order

Estimates are for focused work with Claude Code doing the typing [S].

| Order | Work | Effort | Fixes gaps |
|---|---|---|---|
| 0 | Switch to "ask" mode, delete key archives, rotate keys, FileVault on | 1 hour, no code | 1, 6 |
| 1 | Listening front end: Flux, early start, local stop on your voice | 4–5 days | 8, 9, 10 |
| 2 | Trust fixes: pending approvals, plain-yes approval, verify before "done", no invented progress | 2 days | 2, 4, 14, 16 |
| 3 | Security in code: socket secret, command parsing, secrets out of child processes, cloud token | 2 days | 1, 3, 6 |
| 4 | Streaming voice over one connection | 2–3 days | 10 |
| 5 | Job robustness: restart, orphans, re-announce | 2 days | 5 |
| 6 | Speak first, work behind; spoken error fallback | 2 days | 7, 11 |
| 7 | Vision: better model, two frames, honest uncertainty, stills only when needed | 2–3 days | 12 |
| 8 | Memory v2 and nightly dreaming with a scored test set | 1.5 weeks | 13, 18 |
| 9 | Core independent of the browser; phone line | 2 weeks | 21 |
| 10 | Agents on the cloud server; proactive policy | 2–3 weeks | 19 |
| 11 | Vision timeline | 2 weeks | 20 |
| 12 | Apprentice prototype (authoring first) | 3–4 weeks | moonshot 1 |

---

## 8. The single change I'd make first

**Replace the listening front end** (item 1): speech recognition with turn detection built in, a reply that starts before you've fully finished, and playback that stops on your voice within about 300 ms.

Why this one:

- You ranked latency and human feel first, and the two least human behaviours I measured both live here: 1.7–1.9 s to stop when you talk over it, and jumping in on a one-second pause.
- It also takes roughly 0.2–0.3 s off every reply, because half a second of each one is spent deciding you had finished.
- The code is ready for it. Starting a reply early and dropping it unheard already works.

Before that, item 0 takes an hour and needs no code. I'd do it today regardless of what gets built.

---

## Appendix: re-running the tests

```
# isolated copy (does not touch the live app or its memory)
PORT=3111 DATA_DIR=<a scratch folder> OPEN_BROWSER=false MUSE_LINK=off TTS_PROVIDER=deepgram npx tsx server/index.ts

node tests/review/log-stats.mjs                  # real conversations, from logs/server.log
PORT=3111 node tests/review/latency.mjs 12       # stage-by-stage latency
PORT=3111 node tests/review/feel.mjs             # interruptions, pauses, wake word, noise
PORT=3111 node tests/review/tasks.mjs all        # background work, Mac control, safety probes (acts on the Mac)
./tests/review/make-vision-scenes.sh             # once
PORT=3111 node tests/review/vision.mjs           # vision
PORT=3111 DATA_DIR=<same folder> node tests/review/memory.mjs
./tests/review/run-failures.sh                   # one thing broken per run
```

Raw results are in `tests/review/out/` on this Mac. They are not committed, because they contain calendar details and file names. The vision scenes are not committed either; `tests/review/make-vision-scenes.sh` rebuilds them from the Mac's stock pictures.

## Sources read this session

- Deepgram Flux quickstart: https://developers.deepgram.com/docs/flux/quickstart
- ElevenLabs multi-context WebSocket: https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-multi-stream-input
- ElevenLabs latency methodology: https://elevenlabs.io/docs/eleven-api/concepts/latency-methodology
- Anthropic fast mode: https://platform.claude.com/docs/en/build-with-claude/fast-mode
- Anthropic model catalogue, Managed Agents (scheduled deployments, memory stores): Claude API reference bundled with Claude Code
- Gemini Live API: https://aistudio.google.com/docs/live-api and https://firebase.google.com/docs/ai-logic/live-api/limits-and-specs
- Speech-to-speech comparisons (vendor blogs, low confidence): https://www.assemblyai.com/blog/best-speech-to-speech-voice-agent-api , https://getstream.io/blog/speech-apis/
- Twilio ConversationRelay: https://www.twilio.com/en-us/products/conversational-ai/conversationrelay
- openWakeWord in the browser: https://deepcorelabs.com/open-wake-word-on-the-web
- Step-level video guidance research: https://arxiv.org/html/2606.04970 (Pro2Bench), https://arxiv.org/pdf/2603.12147 (EgoIntent), https://arxiv.org/html/2603.12764 (SAVA-X)
