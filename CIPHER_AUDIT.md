# Cipher audit

Date: 9 November 2026. Scope: the code in `/Users/thelab/voice-orb` as it runs on the Mac mini (launchd service on `127.0.0.1:3000`), plus kiaan-cloud seen from outside. No code was changed.

How to read this: **[V]** means I verified it (ran it, measured it, or read the line). **[I]** means I inferred it. **[U]** means I could not test it.

Limits of the testing:
- All live tests used a synthetic voice (macOS `say`) sent straight into the local WebSocket. No real microphone, speaker, room echo or Wi-Fi hop was involved, so real-world latency is somewhat worse than the numbers here and echo/barge-in quality is untested.
- The Mac mini screen was locked during the Mac-control tests. Several failures below come from that, which is itself a finding: Cipher has no idea when the screen is locked.
- `ssh kiaan-cloud` does not resolve on the Mac mini, so the droplet was checked only from outside and through its own `server_status` tool.

---

## 1. Verdict

Cipher is a competent conversational voice loop with a weak agent bolted on. The talking part is well built: streaming at every stage, a real turn-detection model, barge-in, backchannels, prompt caching, a hedge for slow model starts. The acting part is not: every tool runs inline inside the spoken turn, there is no job system, no delegation, no verification, and no awareness of the Mac's state. It confidently told me dark mode was off (it is on) and that no apps were open (16 were) because it looked at a screenshot of a locked screen.

The core design choice, a cascaded pipeline (Deepgram → Claude → ElevenLabs) rather than a speech-to-speech model, is **right** and should stay. Speech-to-speech models are still weaker at tool calling, cost several times more, and are not faster than a tuned cascade. You also want Claude doing the work. What is wrong is the layer above it: **one turn = one blocking loop**. That single choice is what stops Cipher from doing big tasks, from talking while it works, and from being reachable over a phone line or WhatsApp.

Measured today: median 1.3 s from the end of your speech to the first audio (1.1 s when the opening phrase is cached, 1.5–1.7 s when it is not), with a tail to 2–3 s. Good voice agents sit near 0.8 s. The gap is mostly endpointing (≈0.5 s) and per-sentence TTS requests (≈0.3–0.6 s), both fixable without changing the architecture.

Mac control: 12 representative tasks, 5 clean successes, 2 partial, 5 failures or wrong answers. Simple shell tasks are fast (2–3 s). Anything needing the GUI, the screen, or more than 30 seconds fails.

Security is the area I would not leave as it is: the cloud hub is protected only by a secret URL, the Mac is in "full" control mode and any WebSocket message can switch modes, and a zip containing all keys is world-readable in your home folder.

**The three changes that would improve it most**

1. **A job system with delegation.** Tools that take more than a couple of seconds become background jobs that survive the turn, report progress by voice, and can be handed to Claude Code on the Mac mini. This unlocks big tasks, removes dead air, and is the foundation for phone and WhatsApp.
2. **Make actions grounded and checked.** Detect locked screen, grant Accessibility, prefer reading state over screenshots, confirm the target before navigating or sending, verify the result before saying "done". This turns 5/12 into something you can trust.
3. **Cut 400–500 ms from every reply.** Faster end-of-turn detection, streaming TTS over one connection, and starting the model before the turn is fully committed. Target: p50 ≤ 0.9 s, p95 ≤ 1.5 s.

Close behind: one afternoon of security fixes (section 6, quick wins).

---

## 2. Architecture today

```
 MacBook / any browser                     Mac mini (launchd: com.voiceorb.server, 127.0.0.1:3000)
┌──────────────────────────┐   WebSocket  ┌────────────────────────────────────────────────────────┐
│ public/app.js (1,789 l.) │   /ws        │ Node 22 + tsx, Express + ws   (server/, ~7,000 lines)  │
│  mic → AudioWorklet      │──PCM 16 kHz─▶│ session.ts  one Session per socket                     │
│  16 kHz, 20 ms frames    │   20 ms      │   ├─ Deepgram nova-3 (streaming WS)  ───────▶ Deepgram │
│  RNNoise, browser AEC    │              │   ├─ Smart Turn v3.2 (ONNX, local, ~70 ms)             │
│  RMS "loud" signal       │◀─PCM 24 kHz──│   ├─ wake word "Cipher", voice focus (speaker match)   │
│  playback queue, orb UI  │   + JSON     │   ├─ turn.ts → claude-haiku-4-5 (streaming) ─▶ Anthropic│
│  camera: COCO detect +   │   events     │   │     tool loop: awaited inline, max 15 steps        │
│  JPEG still per message  │              │   ├─ TTS: ElevenLabs flash v2.5, 1 HTTP req/sentence   │
└──────────────────────────┘              │   │     fallback Deepgram aura-2; phrase cache         │
                                          │   ├─ memory.ts (2nd Haiku call → data/memory.json)     │
 Chrome on the Mac mini                   │   └─ tools                                             │
┌──────────────────────────┐  extension   │        mac.ts   run_command (zsh -lc, 30 s), AppleScript│
│ Cipher extension         │◀────────────▶│                 screenshot, app_control                │
│ tabs/open/read/click/type│              │        browser.ts  via Chrome extension                │
└──────────────────────────┘              │        cloud.ts    MCP client ─────────────────────────┼──┐
                                          │        vision.ts   camera still → Claude               │  │
                                          └────────────────────────────────────────────────────────┘  │
                                                                                                      │ HTTPS, secret URL
 Railway (hosted copy, password-gated, no Mac control)                                                ▼
                                                              kiaan-cloud (DigitalOcean, 1 vCPU / 2 GB, nyc1)
                                                              Caddy :443 → kiaan-mcp (16 tools: calendar, tasks,
                                                              briefs, Perplexity, activity log), kiaan-dashboard,
                                                              hermes-gateway
```

**One turn, end to end** [V from code and logs unless marked]

| # | Stage | Where | What happens |
|---|---|---|---|
| 1 | Capture | Browser | `getUserMedia` with echo cancellation and AGC → AudioWorklet → RNNoise → 16 kHz PCM in 20 ms frames |
| 2 | Uplink | Browser → Mac mini | Binary WebSocket frames on `/ws`. From the MacBook this hop is Wi-Fi or the Railway copy [I]; my tests were loopback |
| 3 | Transcription | Mac mini → Deepgram | nova-3 streaming, `endpointing=150`, `utterance_end_ms=1000` (`deepgram.ts:29–53`) |
| 4 | End of turn | Mac mini | Smart Turn v3.2 runs on the audio tail (p50 69 ms). If "unfinished", waits up to 1.4 s more (`session.ts:598–639`) |
| 5 | Gating | Mac mini | Wake word check, then speaker "focus" check against the voice that woke it (`session.ts:748–780`) |
| 6 | Model | Mac mini → Anthropic | `claude-haiku-4-5`, streaming, thinking off, max 1,024 tokens, cached system prompt + tools (~5.9k tokens). A second identical request is fired if nothing arrives in 900 ms (`turn.ts:339–413`) |
| 7 | Tools | Mac mini | Each tool call is `await`ed in order inside the turn (`turn.ts:199–204`). A short preamble ("Checking.") is spoken first for lookups |
| 8 | Synthesis | Mac mini → ElevenLabs | Text is cut into sentences; each sentence is a separate HTTP request for `pcm_24000`. Common openers come from a local phrase cache |
| 9 | Downlink + playback | Mac mini → Browser | PCM frames over the same WebSocket; browser queues and plays; reports `playback` state back for barge-in |
| 10 | After the turn | Mac mini | History saved as text only (tool results dropped, `session.ts:108–110`); a second Haiku call extracts memories |

There is no queue, no worker, no database, no test suite (`package.json` has `start`, `dev`, `typecheck` only), and the project is not in git.

---

## 3. Measurements

### 3.1 Latency

**From the server log, 342 real turns** (time from "turn committed", so endpointing is not included) [V]

| Metric | p50 | p90 | p95 | max |
|---|---|---|---|---|
| Claude first words | 578 ms | 927 | 1,243 | 7,599 |
| First audio sent | 1,043 ms | 1,395 | 1,888 | 8,043 |
| First audio, last 100 turns | 962 ms | 1,469 | 3,094 | |
| TTS first byte | 280 ms | | 546 | |
| Smart Turn inference | 69 ms | | 92 | |

26 of 342 turns took over 1.5 s to first audio; 11 took over 2.5 s. Smart Turn judged 117 of 475 endpoints "unfinished" and waited a median 770 ms more (up to 2.2 s). The hedge request fired 5 times and won all 5.

**Live, end of speech → first audio, 10 runs** (synthetic voice, loopback) [V]

| Run | End of speech → commit | Commit → first text | Commit → first audio | **End of speech → audio** | Note |
|---|---|---|---|---|---|
| a1 | 553 | 1,119 | 1,459 | **2,012** | first turn after connect |
| a2 | 479 | 554 | 663 | **1,142** | cached opener |
| b2 | 519 | 818 | 1,160 | **1,679** | |
| c2 | 472 | 536 | 882 | **1,354** | |
| a3 | 376 | 576 | 664 | **1,040** | cached opener |
| b3 | 505 | 590 | 1,173 | **1,678** | |
| c3 | 443 | 561 | 670 | **1,113** | cached opener |
| a4 | 387 | 533 | 640 | **1,027** | cached opener |
| b4 | 489 | 575 | 989 | **1,478** | |
| c4 | 450 | 622 | 799 | **1,249** | cached opener |

Median ≈ 1.3 s. With a cached opener ≈ 1.1 s; with fresh TTS ≈ 1.5–1.7 s; first turn 2.0 s.

**Budget per stage (median, fresh TTS)**

| Stage | Today | Evidence | Reachable | How |
|---|---|---|---|---|
| End of speech → turn committed | ~475 ms | live runs | 250–300 ms | Deepgram Flux turn detection, or tighter settings |
| Commit → model first words | ~575 ms | logs + live | 350–450 ms | start the model on the "probably finished" signal; test Haiku 5.5 |
| First words → first phrase ready | 100–360 ms | live runs | ~50 ms | flush on the first clause, not the first sentence |
| TTS first byte | ~280 ms | logs | 100–150 ms | one streaming TTS connection instead of a request per sentence |
| Browser playback buffer | not measured | [U] | | measure in the browser |
| **Total** | **~1.3–1.6 s** | | **~0.8–0.9 s** | |

Not measured: real mic/speaker round trip, MacBook → Mac mini over Wi-Fi, the Railway copy, echo cancellation quality, barge-in reaction time with real audio.

### 3.2 Mac control reliability

Mac control was in "full" mode. Screen locked. Times are from the end of the request to the spoken result. [V]

| # | Task | Result | Time | What happened |
|---|---|---|---|---|
| 1 | Open Calculator | ✅ | 2.2 s | Confirmed running |
| 2 | Free disk space | ✅ | 2.3 s | "96 gigabytes", correct |
| 3 | What files are on my desktop (×2) | ❌ ❌ | 33 s | `ls ~/Desktop` hung to the 30 s timeout both times. 30 s of silence, then a made-up explanation ("might be set to hide files"). Listing that folder hangs from any shell on this machine right now; cause not found, probably a privacy prompt waiting behind the lock screen [I] |
| 4 | Is dark mode on | ❌ wrong | 4 s | Took a screenshot and said "No" from the wallpaper. Dark mode is on. One `defaults read` would have answered it |
| 5 | Create a file, read it back | ✅ | 3.3 s | Worked, but speech-to-text dropped a word so the file got a different name |
| 6 | Delete that file | ✅ asked first | 2.5 s | Correctly asked for approval even in full mode |
| 6b | "Yes, go ahead" | ⚠️ | 1.2 s | Approval accepted and command run; failed on the name mismatch from task 5; reported honestly |
| 7 | Open example dot com | ❌ wrong site | 6 s | Heard "Open Exam .com", opened a parked for-sale domain and read it out |
| 8 | Screenshot: which app is in front | ❌ wrong | 5 s | "No app windows are open." 16 apps were open; the screenshot was the lock-screen wallpaper |
| 9 | TextEdit: new document, type a line | ⚠️ | 9.7 s | AppleScript syntax error, then "not allowed to send keystrokes" (Accessibility not granted), then wrote a file and opened it instead. Said "Done". Narrated every attempt |
| 10 | Run `sleep 45`, tell me when done | ❌ | 33 s | Killed at 30 s. Honest about why. No way to run it longer |
| 11 | Run `sleep 20`, then ask something else mid-way (×2) | ❌ | 22 s | The second question was thrown away both times as a "different speaker" (similarity 0.52 and 0.49, same synthetic voice). Cipher was deaf for 20 s |
| 12 | Open Wikipedia, read the main heading | ✅ | 4.8 s | Correct. Browser extension path is fast (open 1.1 s, read 17 ms) |

Score: 5 clean, 2 partial, 5 failed or wrong (counting each numbered task once).

Not tested: sending messages or email, changing system settings, arranging windows, anything on a real unlocked screen with a real voice. Delegation was not tested because it does not exist.

### 3.3 Cost

Token averages per model step from the log: 670 new + 5,887 cached + 634 cache-written input, 44 output. 76 of 84 recent steps hit the cache. [V]

Estimate for one hour of active conversation (about 120 replies) [I, from verified list prices]:

| Item | Today | Note |
|---|---|---|
| Claude Haiku 4.5 | ~$0.35 | $0.0023 per step |
| ElevenLabs Flash v2.5 | ~$0.80 | ~20k characters at $0.04/1k; the biggest line |
| Deepgram nova-3 | ~$0.46 | $0.0077 per minute of open stream |
| **Total** | **~$1.60/hour** | |

Haiku 4.5 is now a legacy tier. Haiku 5.5 lists at one tenth the price, which would take the model line to about $0.04/hour. Its first-token speed with tools needs testing before switching. A speech-to-speech model would cost roughly 3–5× the whole cascade.

The log shows 50 lines about ElevenLabs quota or credits. The fallback to Deepgram's voice works, but the voice changes mid-conversation.

---

## 4. Findings

Effort: S under a day, M a few days, L a week or more.

### A. Latency and feel

**A1. Endpointing costs about half a second on every turn.**
Evidence: live runs, 376–553 ms from end of speech to commit; Deepgram `endpointing=150` then a final transcript then Smart Turn. A quarter of endpoints are judged unfinished and wait a further 0.8–2.2 s.
Impact: the single largest fixed delay.
Fix: move to Deepgram Flux (turn detection built into the recogniser, about 260 ms, same price as nova-3, and an early "probably done" event) and keep Smart Turn only as a tiebreaker; or as a smaller step, start the model call on the early signal and cancel it if the user continues.
Effort M. Risk: more false starts; needs the real-voice test set from D4.

**A2. TTS is one HTTP request per sentence.**
Evidence: TTS first byte p50 280 ms, p95 546 ms; first phrase waits for a full sentence (100–360 ms after first words).
Impact: 300–600 ms on every uncached reply, plus small gaps and prosody resets between sentences.
Fix: one streaming TTS connection per reply (ElevenLabs stream-input WebSocket), flush on the first clause. Keep the phrase cache.
Effort M. Risk: low.

**A3. The tail is long.**
Evidence: p95 1.9 s over all turns, 3.1 s over the last 100; max 8 s; the hedge fired only 5 times in 342 turns but won every time.
Impact: one reply in ten feels broken.
Fix: lower the hedge to about 500 ms, add a spoken filler when nothing has been said by 1.2 s, and add timestamps to the log so the cause of each slow turn can be traced.
Effort S. Risk: slightly higher model cost.

**A4. The first turn after connecting is slow (2.0 s).**
Fix: on connect, warm the Anthropic cache and the TTS connection with a tiny request. Effort S.

**A5. Cipher narrates its work despite the prompt telling it not to.**
Evidence: "I'll check that for you.", "I'll open Chrome and Wikipedia for you. Now let me read what's on the page.", "Let me fix that. Let me try a different approach" (tasks 9 and 12). The prompt (`turn.ts:12–34`) asks for a few words then the result.
Impact: sounds like a chatbot, and adds seconds.
Fix: have the server speak the preamble (it already does for cloud lookups) and tell the model that anything it writes before a tool call is not spoken. Suppress pre-tool text in code rather than relying on the prompt.
Effort S. Risk: low.

**A6. Mid-sentence false endpoints.**
Evidence: task 8 committed at "…which app is in", started a reply, cancelled, restarted.
Fix: covered by A1.

**A7. Barge-in, echo and backchannels are untested with real audio.** [U]
The logic exists (`session.ts:553`, `660–692`). Its quality depends on the browser's echo canceller and cannot be judged with synthetic input. Needs a 15-minute session with you at the MacBook speaker, with timestamps on.

**A8. Cascaded vs speech-to-speech: keep the cascade.**
Checked: OpenAI gpt-realtime-2.1, Gemini 3.8 Live, ElevenLabs Agents, Pipecat's current guidance. Speech-to-speech is not faster than a tuned cascade, is weaker at multi-step tool use, costs several times more, and there is no Claude speech model. The cascade also maps cleanly onto phone audio.

**A9. Audio transport is PCM over a WebSocket (TCP).**
Fine on a LAN. On a poor connection it will stall rather than degrade. WebRTC is the usual answer. Not worth doing until you use it away from home a lot. Ignore for now.

### B. Mac control and delegation

**B1. No awareness of machine state.**
Evidence: tasks 4 and 8, wrong answers from a lock-screen screenshot. `mac.ts:339` runs `screencapture -x` and passes the image on with no check.
Impact: confidently wrong answers, the worst kind.
Fix: check lock state before any screen or GUI tool and say "your Mac mini is locked" instead. Add cheap state tools (frontmost app, window list, appearance, volume, battery) so the model does not reach for a screenshot.
Effort S. Risk: none.

**B2. Accessibility permission is not granted; there is no GUI control.**
Evidence: `/api/permissions` returns `accessibility:false`; task 9 failed with error 1002. There is no click or accessibility-tree tool in `mac.ts` at all.
Impact: Cipher can run shell commands and scriptable apps and nothing else.
Fix: grant Accessibility to the server process (you, in System Settings). Then add a small accessibility tool set (find element, click, type, menu). Leave full screenshot-driven computer use to a delegated worker (B5); it is slow and around 40% reliable on macOS benchmarks, so it should never run inside a spoken turn.
Effort S for the permission, M for the tools.

**B3. A hard 30-second limit with silence.**
Evidence: tasks 3 and 10. `mac.ts` timeout 30 s; nothing is spoken while waiting.
Impact: dead air, then failure. No long command can ever run.
Fix: after 3–4 s, any tool is moved to a background job (C1) and Cipher says so.
Effort: part of C1.

**B4. No verification step.**
Evidence: task 9 said "Done" for something other than what was asked; task 7 read out the wrong site without noticing.
Fix: tool results should include a check (file exists, app frontmost, page title and URL). For navigation and anything outbound, repeat the heard target when confidence is low or the name is unusual ("Open openexam.com?").
Effort S–M.

**B5. No delegation.**
Evidence: no code path spawns an agent. The Mac mini has Claude Code installed and idle.
Impact: anything multi-step ("clean up my downloads", "find and summarise", "fix this repo") is done by Haiku with a shell and a 15-step cap, or not at all.
Fix: a `delegate` tool that starts `claude -p … --output-format stream-json` on the Mac mini as a job, streams progress events, and reports the result. Use `--resume` for follow-ups.
Effort M. Risk: permissions for the worker need thought (see E2).

**B6. Tool results are dropped from history.**
Evidence: `session.ts:108–110` saves text only.
Impact: "what was that second file again?" needs the tool to run again; after a restart Cipher forgets what it did.
Fix: keep a compact summary of each tool result in history. Effort S.

**B7. Speech-to-text errors turn into actions.**
Evidence: tasks 5 and 7.
Fix: Deepgram keyterm hints for names you use often; confirmation from B4.

### C. Big tasks in the background

**C1. There is no background. One turn, one loop.**
Evidence: `turn.ts:199–204` awaits each tool; a session has one `this.turn`; a new user turn calls `interrupt()` (`session.ts:790`), which aborts the running tools.
Impact: you cannot talk while Cipher works; starting to talk kills the work; nothing outlives the WebSocket or a restart.
Fix: a small job system.
- A job has an id, owner, status, progress lines, result, and where it runs.
- A tool that will be slow returns at once with "started job 12". The turn ends. The conversation goes on.
- Job events (progress, done, failed, needs approval) are fed into the session as system notes. Cipher speaks them at a natural gap, or immediately if you are idle, or sends them to WhatsApp if you have left.
- Jobs are stored on disk (SQLite) so they survive restarts.
- "What's running?", "cancel that", "how's it going?" are tools over the job table.
Effort L (about a week for a solid version). Risk: turn-taking around job announcements needs tuning.

**C2. Speaker focus makes Cipher deaf during work.**
Evidence: task 11, twice. A follow-up in the same voice was rejected at similarity 0.52 and 0.49 while a tool ran (`session.ts:775–780`). With a real voice the result may differ [U], but short utterances are exactly where speaker matching is weakest.
Impact: you cannot interrupt or cancel a running action by voice.
Fix: never gate on speaker match when the utterance starts with the wake word, and lower the bar for short utterances. Log the scores for a week before choosing a threshold.
Effort S. Risk: someone else saying "Cipher" can interrupt, which is acceptable.

**C3. Where jobs should run.**

| Kind of job | Run it on | Why |
|---|---|---|
| Quick lookups, calendar, tasks | in the turn | under 2 s |
| Mac actions on the mini | Mac mini, in-process | needs the local session |
| Long or multi-step work, code, research, files | Mac mini, Claude Code headless | always on, real CPU, your files |
| Scheduled and inbound work (reminders, WhatsApp, phone webhooks) | kiaan-cloud | public address, always reachable |
| Heavy compute | not kiaan-cloud | 1 vCPU and 2 GB, already 19% in swap |

Mac actions on the MacBook are not possible today: the server and its tools live on the mini. If you want Cipher to control the MacBook you are sitting at, the MacBook needs a small local agent that registers with the hub. See open question 2.

### D. Reliability, quality, cost

**D1. The process aborts on exit, often.**
Evidence: 35 `libc++abi … mutex lock failed` aborts against 48 startups in `logs/server.log`; last exit code 134. Probably the ONNX runtime being torn down during `process.exit` [I].
Impact: launchd restarts it, so it looks fine, but a crash on shutdown can lose the last save.
Fix: release the ONNX session before exit; add `uncaughtException` and `unhandledRejection` handlers (there are none).
Effort S.

**D2. Logs have no timestamps and there are no tests.**
Impact: nothing above could be traced to a time of day; every change is tested by talking to it.
Fix: timestamps and a turn id on every line; turn the scripts I used for this audit into a repeatable latency and task suite (D4); put the project in git.
Effort S each.

**D3. Memory stores noise.**
Evidence (earlier in this session): `data/memory.json` contains contradictions and trivia; extraction is a second Haiku call per turn with no review or expiry.
Fix: extract only on explicit "remember" or at session end, de-duplicate, and move memory to kiaan-cloud so phone and WhatsApp share it.
Effort M. Lower priority than A–C.

**D4. No regression suite for voice.**
Fix: record 30 of your own utterances once (commands, questions, pauses, interruptions) and replay them through the harness after each change. Gives real p50/p95 and task pass rates.
Effort S. This is the highest-value small item for everything else in this report.

**D5. Cost.** Fine at $1.60/hour. Two easy wins: test Haiku 5.5 (10× cheaper), and put ElevenLabs on a plan that does not run out mid-conversation.

**D6. Things to ignore for now:** camera and vision (works, rarely the bottleneck), wake word (works), the orb UI, WebRTC, code style. `session.ts` at 1,299 lines and `app.js` at 1,789 are large but will be split naturally by the C1 work.

### E. Security

**E1. The cloud hub is protected only by its URL.**
Evidence: `cloud.ts:54` sends no auth header unless a token is set, and none is. The URL returns 401 without the secret path [V], so it is not open, but the secret travels in every request line, sits in Railway's variables, and is inside the zip and the DMG.
Impact: anyone who gets the URL can read and change your calendar, tasks and briefs.
Fix: add a bearer token on the hub (Cipher already supports `KIAAN_MCP_TOKEN`), then rotate the URL.
Effort S. Risk: none.

**E2. Mac control is "full" and any client message can change the mode.**
Evidence: `data/settings.json` is `"macControl":"full"`; `session.ts:319–321` accepts `mac_mode` from any WebSocket message. The socket is localhost-only with an Origin check (`index.ts:72–76, 119`), which limits this to local processes and the browser page.
Impact: anything that can speak to the socket, including a web page Cipher is reading that manages to inject text into the conversation, has a shell on the Mac mini. There is no handling of untrusted page content anywhere in the prompts (I searched).
Fix: mode changes only from the settings UI with a confirmation; treat browser and cloud tool output as data in the prompt; keep "ask" as the default for anything that sends, deletes or installs.
Effort S.

**E3. A zip of all keys is world-readable.**
Evidence: `~/cipher-macbook.zip` is `-rw-r--r--`. `.env` itself is correctly `-rw-------`.
Fix: `chmod 600`, or delete it once the MacBook is set up. Effort: one command.

**E4. `/api/restart` needs only a header.**
Evidence: `permissions.ts:90–92`. Localhost only, so low risk. Fix with E2.

**E5. Voice approvals are a loose match.**
Evidence: `approvals.ts`, a global yes/no pattern with a 3-minute window. Worked correctly in task 6. A stray "yeah" within 3 minutes could approve something.
Fix: tie the approval to the question just asked and expire it after one turn. Effort S.

**E6. kiaan-cloud logs in as root over SSH.**
Evidence: `server_status` shows root logins from three addresses. Password login setting unknown [U]. fail2ban is running.
Fix: key-only login, a non-root user. Effort S, on the droplet.

### F. Readiness for phone calls and WhatsApp

Not ready, for three structural reasons:

1. **The voice loop is welded to the browser.** `Session` assumes 16 kHz PCM in and 24 kHz PCM out over its own WebSocket protocol, plus browser messages such as `playback` and `loud`. A phone leg is 8 kHz μ-law with no client to report playback.
2. **The server is on localhost on the Mac mini.** Phone and WhatsApp providers need a public HTTPS address. kiaan-cloud has one; the Mac mini does not.
3. **No identity or channel concept.** One global memory, one settings file, sessions keyed by a browser id. A caller, a WhatsApp chat and the orb need to be the same person with the same history, and strangers need to be nobody.

What is already right: the cascade, streaming at each stage, approvals for writes, and the MCP hub as the shared source of truth.

---

## 5. Target architecture

```
                         ┌───────────────────── kiaan-cloud (public edge + shared state) ─────────────────────┐
  Phone (Twilio) ───────▶│ Caddy :443                                                                          │
  WhatsApp (Twilio/Meta)▶│  ├─ /twilio/*  webhooks (signature checked) ─┐                                      │
                         │  ├─ kiaan-mcp  (calendar, tasks, briefs, +memory, +jobs)   token-protected          │
                         │  └─ relay: forwards channel traffic to the brain over a private link (Tailscale)    │
                         └───────────────────────────────────────────────┬─────────────────────────────────────┘
                                                                         │ private
  MacBook browser / orb ──── private link (Tailscale) ───────┐           │
                                                             ▼           ▼
                         ┌──────────────────────── Mac mini: Cipher core (always on) ────────────────────────┐
                         │ Channel adapters      browser-audio │ phone-audio (8 kHz μ-law) │ text (WhatsApp)  │
                         │        │                                                                           │
                         │ Conversation core     STT → turn detection → Claude → streaming TTS                │
                         │   (transport-agnostic; text channels skip STT/TTS)                                 │
                         │        │                                                                           │
                         │ Tool router ── fast tools: inline (<2 s)                                           │
                         │             └─ slow tools: Job system (SQLite) ──┬─ local Mac actions (AX, shell)  │
                         │                 progress/done events back into   ├─ Claude Code headless worker    │
                         │                 the conversation or to WhatsApp  └─ remote: MacBook agent (optional)│
                         └────────────────────────────────────────────────────────────────────────────────────┘
```

What changes versus today:

| Today | Target |
|---|---|
| `Session` = browser socket + audio + turn logic in one class | Conversation core with three thin adapters (browser, phone, text) |
| Tools awaited inside the turn; new speech aborts them | Fast tools inline; slow tools become jobs that outlive the turn |
| Haiku with a shell does everything | Haiku converses and routes; Claude Code on the mini does the heavy work |
| Per-sentence TTS requests; endpointing by timeout + model | One streaming TTS connection; recogniser-level turn detection; early model start |
| Server reachable on localhost only (plus a separate Railway copy) | One brain on the Mac mini, reached privately from your devices and through kiaan-cloud for phone and WhatsApp |
| Memory and history in local JSON files | Memory and jobs on the hub, shared by every channel |
| Cloud hub guarded by a secret URL | Token on the hub; webhook signatures checked; mode changes confirmed |

Why the brain stays on the Mac mini rather than moving to kiaan-cloud: the droplet has one core and is already swapping; the mini has the files, the apps and Claude Code; and keeping keys in one place is simpler. The cost is that if the mini is down, calls fail. kiaan-cloud should answer with a short "Cipher is offline" message in that case.

What stays: the cascade, Deepgram, Claude, ElevenLabs, the Chrome extension, the MCP hub, the approval model.

---

## 6. Roadmap

### Quick wins (each under a day), in order

| # | Change | Finding | Depends on |
|---|---|---|---|
| 1 | `chmod 600` the key zip; add a token to the hub and rotate its URL; key-only non-root SSH | E1, E3, E6 | you, for the droplet |
| 2 | Timestamps and turn ids in logs; put the project in git | D2 | |
| 3 | Record 30 real utterances; turn the audit scripts into a repeatable suite | D4 | 2 |
| 4 | Lock-screen check before screen/GUI tools; add cheap state tools | B1 | |
| 5 | Grant Accessibility to the server | B2 | you |
| 6 | Don't apply speaker focus to utterances that start with the wake word | C2 | |
| 7 | Suppress model text before tool calls; server speaks the preamble; filler at 1.2 s | A5, A3 | |
| 8 | Warm model cache and TTS on connect; hedge at 500 ms | A4, A3 | |
| 9 | Mode changes need confirmation; approvals bound to one question; mark tool output as untrusted in the prompt | E2, E4, E5 | |
| 10 | Clean shutdown and crash handlers | D1 | |
| 11 | Keep tool-result summaries in history | B6 | |
| 12 | Try Haiku 5.5 behind a setting; compare first-token time on the suite | D5 | 3 |

### Phase 1: background work (about 1–2 weeks)
1. Job system: table, events, the "slow tool becomes a job" rule, voice commands for status and cancel. (C1, B3)
2. Delegation to Claude Code on the Mac mini as a job type. (B5)
3. Result verification and target confirmation. (B4, B7)

Depends on quick wins 2, 3, 6.

### Phase 2: speed (about 1 week)
1. Streaming TTS over one connection, clause-level flush. (A2)
2. Deepgram Flux for turn detection, with early model start. (A1, A6)
3. Real-audio session to tune barge-in and echo. (A7)

Depends on quick win 3 so the gain can be proved. Can run alongside Phase 1; they touch different files.

### Phase 3: channels (about 2 weeks)
1. Split `Session` into core + browser adapter. No behaviour change.
2. Private link between your devices, the mini and kiaan-cloud; retire or keep the Railway copy (open question 3).
3. WhatsApp text adapter through kiaan-cloud. Simplest channel, and gives job results somewhere to go when you are away.
4. Phone adapter (Twilio Media Streams, 8 kHz), inbound to you first, then outbound calls with a per-call brief and approval.
5. Move memory to the hub with an owner id. (D3)

Depends on Phase 1 (jobs and events) and quick win 1 (hub security).

### Later, if wanted
GUI accessibility tool set (B2), MacBook local agent (C3), WebRTC transport (A9).

---

## 7. Open questions

1. **Who may Cipher phone, and may it speak as you?** Outbound AI calls to other people carry consent and disclosure rules (in the US, AI-voice calls generally need prior consent; this is not legal advice). *Recommendation:* start with calls to and from your own number only; then outbound calls to businesses, always opening with a disclosure, each call approved by you beforehand.

2. **Should Cipher control the MacBook you are sitting at, or only the Mac mini?** Today it can only touch the mini, which is usually locked and out of sight. *Recommendation:* mini only for now, used as the worker. Add a MacBook agent later if you find yourself asking for it.

3. **Keep the Railway copy?** It is a second deployment with its own keys and no Mac control. *Recommendation:* retire it once the MacBook can reach the mini privately. One brain is easier to secure and reason about.

4. **Private link: Tailscale or a public tunnel?** *Recommendation:* Tailscale between MacBook, mini and droplet. Nothing on the mini becomes public; only kiaan-cloud faces the internet.

5. **Leave Mac control on "full"?** *Recommendation:* yes for reading and opening things, but anything that sends, deletes, installs or pays always asks, in every mode, and the mode cannot be changed by a message.

6. **WhatsApp number.** A WhatsApp Business sender needs its own number and Meta approval, and can only message you freely within 24 hours of your last message (templates otherwise). *Recommendation:* a new Twilio number used for both voice and WhatsApp, about $1.15/month plus usage.

7. **Should the Mac mini stay unlocked?** GUI control and screenshots need an unlocked session. *Recommendation:* keep it unlocked with the display asleep, in a physically trusted place; if that is not acceptable, limit Cipher on the mini to shell, scriptable apps and delegated Claude Code, and say "locked" otherwise.

8. **Latency or patience?** Faster endpointing means Cipher will occasionally jump in during a pause. *Recommendation:* aim for 0.9 s median and tune on your recorded utterances; keep the "unfinished" wait but cap it at 1 s.

---

## Appendix: left behind by testing

- `~/Desktop/Cipher audit.txt` (6 bytes, created by Cipher in task 5). I could not remove it: moving or listing anything in `~/Desktop` hangs on the Mac mini at the moment (same fault as task 3). Worth looking at when the screen is unlocked; there may be a permission prompt waiting.
- Chrome tabs opened by Cipher: `openexam.com` and `wikipedia.org`.
- Calculator and TextEdit were quit; `/tmp/test.txt` removed. `data/memory.json` and `data/conversations.json` are unchanged from before the tests (compared).
- The service was not restarted and no project file other than this report was written.

## Appendix: sources checked (9 November 2026)

Anthropic model and pricing pages (Haiku 4.5 / 5.5, caching, computer use, Claude Code headless mode); Deepgram docs (nova-3, Flux, Aura-2 pricing); ElevenLabs docs (Flash v2.5, v3 Conversational, stream-input, Agents pricing); OpenAI Realtime and Gemini Live docs and pricing; Pipecat voice-agent guide and Smart Turn v3.2 release notes; Twilio pricing and docs (Voice, Media Streams, ConversationRelay, WhatsApp); MacArena benchmark results for computer use on macOS. Prices are list prices on that date.
