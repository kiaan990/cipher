# Cipher

A live, low-latency voice conversation with Claude in your desktop browser. You talk, a 3D orb listens, Claude answers out loud, and you can cut in at any time. The orb reacts to the conversation itself: Claude's mood, every word either of you says, and the sound of both voices.

- **Speech-to-text:** Deepgram streaming (`nova-3`), with interim results and end-of-turn detection
- **LLM:** Anthropic Messages API, streamed, using Claude Haiku (`claude-haiku-4-5` by default, the fastest to start talking)
- **Text-to-speech:** ElevenLabs streaming (`eleven_flash_v2_5`), one request per sentence as soon as the sentence is written
- **Turn detection:** [Smart Turn v3.2](https://huggingface.co/pipecat-ai/smart-turn-v3) (open model from Hugging Face, 8 MB, runs locally) hears whether you've finished or are just pausing mid-thought, so Claude doesn't jump in on an "um…"
- **Listens like a person:** "mm-hmm", "yeah", "oh no", "oh wow" or a soft laugh in the gaps while you talk for a while; your own "yeah" doesn't cut it off; if you both start at once it says "sorry, go ahead"
- **Barge-in:** start talking while Claude speaks and it goes quiet within about 200 ms
- **Memory:** remembers you between conversations, stored only on this Mac
- **Mac control:** opens apps, manages files, runs commands and reads your screen, asking first before changing anything
- **Chrome control:** with the included extension, checks your email, reads and uses websites, and asks before sending or buying anything
- **Vision:** turn on the camera and Claude sees what you hold up (camera stills), plus live on-device object detection with [transformers.js](https://github.com/huggingface/transformers.js)

## Quick start

1. Install [Node.js](https://nodejs.org) 20 or newer.
2. Copy the example env file and add your keys:
   ```bash
   cp .env.example .env
   ```
   Then open `.env` and fill in `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY` (and optionally `ELEVENLABS_VOICE_ID`).
3. Install and run:
   ```bash
   npm install && npm start
   ```
4. Your browser opens at <http://localhost:3000>. Click **Start conversation**, allow the microphone, and talk.

Use headphones for the best experience. Speakers work too, thanks to echo cancellation, but headphones make interruptions more reliable.

If a key is missing, the page shows which one to add. Keys stay on the server and are never sent to the browser.

## Run it like an app on your Mac (always on)

Instead of keeping a terminal open, install Cipher as a background service and a Mac app:

```bash
./scripts/install-service.sh   # runs in the background, starts at login, restarts itself if it stops
./scripts/make-mac-app.sh      # builds "Cipher.app" in ~/Applications (Spotlight, Launchpad, Dock)
```

- **Cipher.app** opens the app in its own window (no tabs or address bar) and starts the service if it isn't running.
- The server log is in `logs/server.log`.
- After updating the code: `./scripts/restart-service.sh`. To remove the service: `./scripts/uninstall-service.sh` (memories and settings are kept).
- **macOS permissions:** the service runs as `node`, so macOS asks again the first time it controls an app; for screenshots, allow `node` under System Settings → Privacy & Security → Screen & System Audio Recording.

**What's saved, and where** (`data/`, all on your Mac):
- `memory.json`: long-term memories. Every save is written to a temporary file, forced onto the disk and then swapped in, so a crash or power cut can't leave it half-written. One backup per day is kept for 30 days in `data/backups/`; if the file is ever damaged, it's set aside and the newest backup is restored automatically.
- `conversations.json`: your recent conversations (last 20, up to 30 days), saved a few seconds after each change and on shutdown. After a restart or reload, Claude carries on the same conversation and the transcript shows it again. "Start a new conversation" clears it.
- Memory never stores passwords, codes, card, bank or ID numbers.

## Smoothness on laptops

The orb watches its own frame rate. On a Mac that can't keep up (a MacBook Air on battery, Low Power Mode, a big external display), it steps quality down by itself: softer resolution first, then fewer particles, then lighter effects; and back up after 20 s of smooth running (at most once a minute). It never draws more than 60 frames a second, even on 120 Hz screens. The camera detector waits at least as long as each detection takes, and slows to once a second when the orb has stepped down. The page reports its frame rate, quality level and graphics chip to the server log (`[perf]` lines).

## Installing on another Mac (installer)

```bash
./scripts/build-installer.sh    # makes build/Cipher Installer.dmg (~40 MB)
```

AirDrop the `.dmg` to the other Mac, open it and double-click **Install Cipher**. It installs the app to `~/Library/Application Support/Voice Orb` (memories in its `data` folder, kept across updates), sets up the background service and the Dock app, walks through macOS permissions (Automation, Accessibility, Screen Recording) and the Chrome extension. The other Mac needs Node.js 20.18 or newer; the installer says if it's missing. The installer isn't signed by Apple, so the first time use System Settings → Privacy & Security → **Open Anyway**. It contains your API keys from `.env`, so keep it private.

## Hosting it online (private, password-protected)

Run Cipher on [Railway](https://railway.com) so it's just a web address: no terminal, works on your phone too. Railway's Hobby plan is about $5 a month.

**Hosted mode** switches on automatically on Railway:
- Every page and connection needs your password (a sign-in page, then a 30-day cookie; 10 wrong tries locks that address out for 15 minutes).
- Mac control and the Chrome extension are switched off, because the server is in the cloud, not your Mac.
- Keys live in Railway's private Variables. `.env` is never uploaded (see `.railwayignore`).
- Memory is kept on a Railway volume mounted at `/data`, so it survives updates.

**First deploy** (run in the `voice-orb` folder):
```bash
brew install railway        # the Railway command-line tool
railway login               # opens your browser to sign in
railway init --name voice-orb
railway up --detach         # uploads the app and creates the service
railway service             # pick the voice-orb service
railway volume add --mount-path /data
./scripts/railway-setup.sh  # copies keys from .env and asks for your sign-in password
railway up --detach         # deploy with the settings
railway domain              # prints your https://….up.railway.app address
```

**Install it as an app** (works for the online version and on your Mac):
- **Chrome / Edge (Mac or PC):** open the site, then click the install icon at the right of the address bar (or ⋮ → Cast, save and share → Install page as app). It gets its own window and Dock/Start-menu icon.
- **iPhone / iPad (Safari):** Share → **Add to Home Screen**. It opens full-screen with the orb icon; allow the microphone the first time.
- **Android (Chrome):** ⋮ → **Install app**.
The app always loads the latest version (nothing is cached except a small "you're offline" page).

**Updating later:** `railway up --detach`. Open pages reload themselves to the new version.


| Control | What it does |
| --- | --- |
| **Start / End** (or <kbd>Space</kbd>) | Opens or closes the mic and the speech pipeline. |
| **Camera button** (or <kbd>V</kbd>) | Turns the camera on or off. A preview shows what the detector sees, with live boxes. |
| **Mic button** (or <kbd>M</kbd>) | Mutes your microphone. The ring around it shows your live mic level. |
| **Stop button** (or <kbd>Esc</kbd>) | Cuts Claude off. Just talking over Claude does the same. |
| **Tap the orb** | Starts a conversation, or interrupts Claude while it's thinking or speaking. |
| **Drag the orb** | Spins it. Hovering makes the surface bulge towards your cursor. |
| **Transcript** (or <kbd>T</kbd>) | The whole conversation, with each reply's mood, response time and any interruptions. Copy it or start a new chat. |
| **Settings** (or <kbd>,</kbd>) | Interrupt sensitivity, vision model, full or lite visual effects, floating words and live captions. Saved in your browser. |
| **Shortcuts** (or <kbd>?</kbd>) | Lists the keyboard shortcuts. |

**Voice control of the app itself.** Just ask: "turn on the camera", "turn the camera off", "mute yourself", "end the call", "start a new conversation", "show the transcript", "open settings", "switch to the accurate vision model", "turn off captions", "use lite effects", "set interruption sensitivity to high", "turn memory off", "set computer control to ask first". Muting, ending and starting a new conversation happen after Claude finishes its sentence. Unmute with the mic button or <kbd>M</kbd> (Claude can't hear you while muted). Switching computer control to **Full** by voice needs a spoken "yes".

The status pill at the top shows what's happening (Listening, Thinking, Speaking…), Claude's current mood and how long the last reply took to start. Captions reveal Claude's words in step with its voice.

Open <http://localhost:3000/?demo> to watch the orb play through a scripted conversation (no keys or mic needed).

## The orb

A Three.js scene (WebGL, with bloom and a glitch/chromatic post-effect):

- **Core:** a sphere whose surface is shaped by noise, your voice or Claude's voice, ripples and your cursor, with a glowing rim, scan lines and a geodesic lattice shell.
- **Particle cloud and radial equaliser:** both follow the live frequency spectrum of whoever is talking.
- **HUD rings:** spin faster and sweep while Claude is thinking.

How it reacts to the conversation:

| What happens | How the orb reacts |
| --- | --- |
| You speak | Turns cyan. The particles pull inward, and each word you say flies in and lands on the surface as a ripple. |
| Claude is thinking | Turns violet. The rings spin and sweep and the core churns. |
| Claude speaks | Takes the colour and body language of Claude's **mood**. Each word floats out of the surface in time with the voice. |
| You interrupt | Red-white flash, glitch tear, shockwave, camera shake, and the particle cloud is blown outward. |
| Idle | Breathes slowly in the colour of the last mood. |

**Moods.** Claude ends every reply with a hidden tag such as `[mood: curious]` (at the end rather than the start, so the voice doesn't wait for it; the orb changes mood a moment into the reply). The server strips it before the text is shown or spoken, and sends it to the browser. The moods are calm, happy, excited, curious, thoughtful, empathetic, serious, playful and surprised. Each has its own colours and motion: excited is fast and spiky, empathetic pulses like a heartbeat, curious tilts its head, serious is still and sharp, and so on. The HUD at the top shows the current state and mood.

If WebGL isn't available, the app falls back to the original 2D canvas orb.

## Vision (camera)

Press the camera button and Claude can see you. Hold something up and ask "what am I holding?", show it a page to read, or ask where something went.

Two things work together:

1. **Camera stills (what's there now).** While the camera is on, the browser keeps the server supplied with a small still (640 px JPEG, under a second old). It's attached to whatever you say next, so Claude sees exactly what you're showing it: objects, text, colours, faces. A still is used for that one reply only and never stored or kept in the conversation history. It adds no noticeable delay. Turn it off with **Settings → Claude sees camera stills** to keep video entirely on your Mac.
2. **On-device object detection (what comes and goes).** About four times a second, a background worker ([`public/vision-worker.js`](public/vision-worker.js)) runs an object-detection model with [transformers.js](https://github.com/huggingface/transformers.js) on your GPU (WebGPU) or CPU. It draws the live boxes on the preview, makes new objects fly into the orb, and tells Claude what's in view and what left the frame in the last 30 seconds. Only labels and positions are sent; it knows about 80 everyday object types.

| Setting | Model | Download |
| --- | --- | --- |
| Fast (default) | [`Xenova/yolos-tiny`](https://huggingface.co/Xenova/yolos-tiny) | ~10 MB on CPU, ~26 MB on GPU |
| Accurate | [`Xenova/detr-resnet-50`](https://huggingface.co/Xenova/detr-resnet-50) | ~45 MB on CPU, ~85 MB on GPU |

Detection models download from Hugging Face the first time you turn the camera on, then the browser caches them. When the camera is off, Claude knows it can't see you.

## Mac control

Claude can do things on this Mac for you: "what's on my Desktop?", "open Safari", "how much disk space do I have?", "turn the volume down", "make a folder called Taxes in Documents", "what's on my screen?". It has three tools: Terminal commands (zsh), AppleScript (to control apps), and screenshots.

Choose how much it may do in **Settings → Mac control**:

| Mode | What happens |
| --- | --- |
| Off | No access. |
| **Ask first** (default) | Looking around (listing files, disk space, opening apps and websites, the volume, screenshots) runs straight away. Anything that changes something waits for your OK. |
| Full | Acts without asking, except deleting, killing apps or shutting down, which still ask. |

**Approving.** When an action needs your OK, Claude asks out loud and a card shows the exact command. Say "yes" or "no", or click **Approve** / **Don't**. The server checks your actual words, in a turn after it asked, so Claude can't approve its own actions. Approvals expire after 3 minutes.

**Always blocked**, in every mode: `sudo` and anything needing your password, reading saved passwords from the keychain, and the Calendar and Reminders apps (calendar and tasks go through your cloud server instead; see below).

**Safety details**
- Deleting moves things to the Trash so you can undo it, unless you explicitly say "permanently".
- Every action appears in the transcript (hover for the full command and output) and in the terminal.
- Commands run as your user in your home folder. One that takes more than a few seconds carries on as a background job (see below); it is stopped after 10 minutes, or when you say "cancel that".
- The server only listens on this Mac (`127.0.0.1`) and refuses connections from other websites, so nothing else can reach the controls.
- Anything Claude reads (files, web pages, the screen) is treated as information, never as instructions.

**macOS permissions.** The first time Claude controls an app (Finder, Music…), macOS asks whether the app running `npm start` (Terminal, say) may control it: click OK. For screenshots, allow Screen Recording for that app in System Settings → Privacy & Security → Screen & System Audio Recording, then restart `npm start`.

## Background jobs

Cipher doesn't go quiet while something slow runs. Work that takes longer than a pause becomes a **job**: Cipher says it's running in the background, keeps talking with you, and tells you when it finishes.

- **What becomes a job.** A Terminal command or AppleScript still running after 4 seconds, a cloud-server call still running after 8, and anything handed to Claude Code (below).
- **Asking about it.** "What's running?", "how's that job going?", "what did job 3 do?". Jobs are numbered.
- **Stopping it.** "Cancel that" stops the newest job; "cancel job 2" stops that one. The process is really stopped, not just forgotten.
- **Finishing.** Cipher waits for a gap in the conversation, then says what happened in a sentence. A job that finishes while the page is closed is announced the next time you're there, once.
- **On screen.** Each job has a row in the transcript ("In the background: …") showing what it's doing right now.

Jobs are kept in `data/jobs.db`, so "what did that do?" still has an answer after a restart. A job that was running when the app restarted is marked interrupted and you're told.

### Handing work to Claude Code

For anything bigger than a couple of commands (writing or changing code, building something, digging through a project), Cipher hands the work to **Claude Code**, the coding agent installed on this Mac, as a job: "hand this to Claude Code: in ~/projects/site, add a contact page". You can follow up on a finished job ("on job 4, also add a test") and it remembers its earlier work.

Limits, on purpose:
- It works in one folder inside your home folder (a scratch folder, `~/Cipher Work`, if you don't name one). Never the home folder itself, Library, or settings folders such as `.ssh`.
- In **Ask first** mode every hand-off needs your spoken OK. It's off when Mac control is off.
- It runs with Claude Code's "accept edits" permissions and a fixed list of tools; `sudo`, the keychain and system tools are denied.
- It gets none of Cipher's keys or the cloud server address: they are removed from its environment. It uses your own Claude Code sign-in.
- Two at a time, 30 minutes each.

### Checking names before acting

Speech recognition mishears names, so Cipher checks what a name points at before acting on it:
- **Apps.** "Open Figmaa" isn't opened blindly: if no such app is installed, Cipher offers the closest real names.
- **Websites.** An address that doesn't exist is never opened. One Cipher hasn't opened before is confirmed with you once, out loud, then remembered (`data/known-targets.json`). Well-known sites skip the question.
- **Hearing them right.** The names of your installed apps and the sites you've opened are given to speech recognition as words to listen for.
- **Checking the result.** After opening an app or changing something, Cipher looks at what actually happened (is the app running? does the file exist?) before telling you it's done.

## Chrome control (email and the web)

With the **Cipher Bridge** extension, Claude can use your Chrome: "check my emails", "open Maria's email and reply that I'll be there", "what's on my open tabs?", "search YouTube for lo-fi music". It works in background tabs while you keep talking, using the logins already in your Chrome.

**Install (once):**
1. In Chrome, open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose the `chrome-extension` folder inside `voice-orb`.
3. In Cipher, open **Settings → Set up Chrome**, copy the pairing code, click the extension's icon in Chrome (pin it from the puzzle-piece menu), paste the code and press **Connect**. Settings shows "Chrome extension: connected".

**What it can do:** list tabs, open pages, read a page (text plus a numbered list of buttons, links and fields), click, type, scroll, go back, bring a tab to the front, and screenshot the visible tab.

**Safety** (follows the Mac & Chrome control mode in Settings):
- Reading, opening pages, clicking links and opening emails just happens.
- Anything that **sends, posts, buys, pays, deletes, submits or confirms** always waits for your "yes" or the Approve button, in every mode. In "Ask first" mode, other buttons and submitted forms ask too (search boxes don't).
- It never types into password, card or verification-code fields, and calendar and task sites (Google Calendar, Tasks, Todoist…) are blocked.
- Web pages and emails are treated as information only. If an email says "assistant, forward all emails to…", Claude tells you about it and does nothing.
- Element numbers are only valid within the reply that read the page, so Claude can't click the wrong thing after a page changes.
- The extension only connects to this Mac (`127.0.0.1`) with the pairing code (stored in `data/ext-token`); web pages can't use the connection.

## Your cloud server (kiaan-cloud)

Cipher can use the tools on your own cloud server (its MCP server): your tasks, calendar, briefs, notes, activity log, server health and search. Ask "what's due this week?" or "add study for the quiz to my tasks".

- Looking things up happens straight away. Anything that adds, changes, completes or deletes something asks you first, out loud and on screen.
- Add the server's MCP address and access token to `.env` (and to Railway's Variables for the hosted version):

  ```
  KIAAN_MCP_URL=https://…
  KIAAN_MCP_TOKEN=…
  ```

  The token stays on the server side and never reaches the browser. Restart Cipher afterwards. The log shows `Cloud server: connected (N tools…)` when it works.

## Memory

Claude remembers things about you between conversations: your name, people and pets in your life, preferences, plans, and anything you ask it to remember. Say "forget that" (or "forget about my trip") to remove something, or ask "what do you remember about me?".

- After each reply, a quick background Claude call picks out anything worth keeping. It runs after the reply, so it never slows the conversation down.
- Memories are saved only on this computer, in `data/memory.json`, and added to Claude's instructions at the start of every reply.
- **Settings → Memory** lists everything Claude remembers. Remove single items, forget everything, or switch memory off. The top bar briefly shows "Saved to memory" when something new is kept, and the terminal prints a `[memory]` line.

## Why Node.js + TypeScript

The whole app is a set of streams joined together: browser WebSocket ↔ Deepgram WebSocket, Anthropic SSE stream → sentence splitter → ElevenLabs HTTP streams → browser. Node's event loop handles many concurrent streams with very little code, `fetch` streaming and `AbortController` are built in (which makes cancelling everything on barge-in a single call), and the official Anthropic TypeScript SDK supports streaming and aborts directly. TypeScript catches mistakes in the message shapes without a build step: `tsx` runs the `.ts` files directly.

## How it works

```
Browser                                   Server (Node)
───────                                   ─────────────
mic → AudioWorklet (16 kHz PCM) ──WS──▶  Deepgram live STT ──▶ interim + final transcripts
                                          │ end of turn (speech_final / UtteranceEnd)
                                          ▼
                                          Claude Haiku, streamed
                                          │ tokens → sentence splitter
                                          ▼
                                          ElevenLabs, one streamed request per sentence
speakers ◀── Web Audio queue ◀────WS───── 24 kHz PCM chunks, tagged with a turn id
```

**Latency.** From the moment you stop talking, the first audio typically arrives in about 1.1 s: roughly 0.35 s for Deepgram to be sure you've finished, 0.45–0.6 s for Claude's first words, and 0.27 s for ElevenLabs to start speaking. To keep it there:

- Claude Haiku 4.5 is the fastest model still available (older Haikus are retired).
- Deepgram ends your turn after just 150 ms of silence. If you were only pausing mid-sentence and Claude hasn't started speaking yet, that reply is cancelled silently and your whole sentence is answered once you finish.
- The mood tag comes at the end of each reply, so it doesn't delay the first word (it used to cost about 0.2 s).

- Connections to Anthropic and ElevenLabs are kept open between replies and re-warmed the moment you start speaking, so no reply waits for a fresh secure handshake ([`server/net.ts`](server/net.ts)).
- The voice starts on the first short phrase (up to the first comma), not the whole first sentence.
- Each reply prints a timing line in the terminal, e.g. `[latency] turn 3: Claude first words 460 ms · first phrase ready 485 ms · first audio 754 ms`.

**Turn taking.** Deepgram sends interim transcripts while you talk (shown live in the caption). When it reports 150 ms of silence (`speech_final`), [Smart Turn v3.2](https://huggingface.co/pipecat-ai/smart-turn-v3) (BSD-2 licence, run on this machine with `onnxruntime-node`, ~30–70 ms) listens to the last 8 seconds of your voice and judges whether you finished or are pausing mid-thought ([`server/smartturn.ts`](server/smartturn.ts)). Finished: your turn goes to Claude straight away, with the last ~20 turns of history. Mid-thought ("so I was thinking we could, um…"): it waits up to 2.2 s for the rest; less when the model is unsure or the words read as a finished sentence. A transcript ending on a word nobody ends on ("and", "the", "because") also counts as unfinished. The model (8.7 MB) downloads once to `data/models/` and is checked against its published hash. The terminal prints a `[turn]` line for each decision.

**Listening like a person** ([`server/backchannel.ts`](server/backchannel.ts), [`server/session.ts`](server/session.ts)).
- *Listener sounds:* once you've talked for a few seconds, Cipher answers the short gaps between your phrases with a quiet sound that fits what you said: "mm-hmm", "yeah", "right" most of the time, "oh no" for bad news, "oh wow" for good news, "got it" for instructions, a soft laugh when you joke. Roughly every 4–9 seconds, never after a question, and never over your words (the page skips it if you've already started again). 22 clips, recorded once with ElevenLabs' expressive model in Cipher's voice and cached in `data/backchannels/`. They never enter the conversation.
- *Your "yeah" isn't an interruption:* "yeah", "mm-hmm", "right", "okay", "got it" while Cipher talks: its voice dips for a moment and carries on. "Stop", "wait" or a real sentence still stops it (about 0.75 s after you start).
- *Collisions:* if you both start at the same moment, Cipher stops; if you go quiet too, it says "sorry, go ahead" and keeps what you'd started saying, so it joins up with the rest.
- *Soft stops:* when you interrupt, its voice fades out over 0.15 s instead of cutting off.

Turn the listener sounds off with `BACKCHANNELS=off`.

**Streaming reply.** Claude's tokens are cut into sentences as they arrive. The first sentence goes to ElevenLabs straight away, and the next one is requested in parallel so there's no gap. Each request carries the text before and after it (`previous_text` / `next_text`), so the voice keeps one flowing intonation instead of restarting every sentence. Audio chunks are forwarded to the browser in order, with a pause shaped by the punctuation: barely any after a comma, a beat after a full stop, a little longer after a question or a trailing "…". Markdown is stripped before anything is spoken.

**Barge-in.** Two detectors run at once:

1. In the browser, a voice-activity check on the mic level. If you speak for 160 ms while Claude is talking (with a higher threshold during playback, so echo isn't mistaken for you), the browser stops all queued audio instantly and tells the server.
2. On the server, if Deepgram transcribes two or more words while Claude is busy, it interrupts too.

Either way the server aborts the Anthropic stream and every in-flight ElevenLabs request, marks the partial reply in the history as `[interrupted by the user]`, and keeps listening. Audio chunks carry a turn id, so any late audio from the cancelled reply is dropped.

**Echo cancellation.** The mic is opened with `echoCancellation`, `noiseSuppression` and `autoGainControl`. Claude's audio is played through an `<audio>` element (fed from Web Audio) because Chrome's echo canceller only removes audio played that way.

**Reconnects.** If the browser's WebSocket drops, it reconnects with backoff and restarts the session automatically; conversation history is kept on the server per browser tab. If Deepgram's connection drops, the server reopens it.

## Project structure

```
voice-orb/
├── server/
│   ├── index.ts       Express static server + WebSocket endpoint
│   ├── config.ts      Reads .env, reports missing keys
│   ├── session.ts     Per-tab session: turn taking, barge-in, history
│   ├── deepgram.ts    Streaming speech-to-text connection
│   ├── turn.ts        One Claude reply: streaming, system prompt, mood tag
│   ├── vision.ts      Turns camera detections into a scene note for Claude
│   ├── memory.ts      Long-term memory between conversations (data/memory.json)
│   ├── mac.ts         Mac control tools and the approval policy
│   ├── browser.ts     Chrome control: talks to the extension, browser tools and rules
│   ├── appcontrol.ts  Voice control of the app itself (camera, mute, settings…)
│   ├── approvals.ts   "Needs your OK" checks shared by Mac and Chrome control
│   ├── jobs.ts        Background jobs: slow work that carries on while you talk (data/jobs.db)
│   ├── delegate.ts    Hands bigger work to Claude Code as a background job
│   ├── targets.ts     Checks app and website names before acting on them
│   ├── version.ts     Lets open pages reload themselves after an update
│   ├── net.ts         Kept-alive HTTPS connections for low latency
│   ├── backchannel.ts listener sounds ("mm-hmm", "oh no", "sorry, go ahead"): made once, cached
│   ├── smartturn.ts   Smart Turn: "finished, or just pausing?" (local open model)
│   ├── tts.ts         Ordered, cancellable ElevenLabs streaming
│   └── text.ts        Sentence splitter and markdown stripper
├── public/
│   ├── index.html
│   ├── styles.css
│   ├── app.js         UI, WebSocket, local voice-activity detection
│   ├── audio.js       Mic capture and gapless PCM playback
│   ├── mic-worklet.js Downsamples the mic to 16 kHz PCM
│   ├── vision.js      Camera, frame capture, live box overlay
│   ├── vision-worker.js  transformers.js object detection (off the main thread)
│   ├── orb3d.js       The 3D orb (Three.js + shaders)
│   └── orb2d.js       2D fallback orb
├── chrome-extension/  The Cipher Bridge extension (load unpacked in Chrome)
├── mac-app/        Cipher.app launcher source and icon
├── scripts/        Background service, Mac app, installer and Railway scripts
├── installer/      The Mac installer (setup script, step-by-step app, instructions)
├── data/           Your memories, conversations and settings (created on first run)
├── .env.example
└── package.json
```

## Settings

All optional, in `.env`:

| Variable | Default | Notes |
| --- | --- | --- |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` | `claude-haiku-5-5` is newer. Measured here (`npm run test:models`): its first word arrives no sooner (about 505 ms against 510 ms) and it writes about twice as much, so spoken replies start slightly later. |
| `ELEVENLABS_VOICE_ID` | `FGY2WhTYpPnrIDTdsKH5` (Laura) | Any voice ID your plan allows. Free plans can only use ElevenLabs' default voices over the API, not library voices. |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | Flash is the lowest-latency model. |
| `ELEVENLABS_STABILITY` | `0.38` | 0–1. Lower is more expressive and human; higher is steadier. |
| `ELEVENLABS_STYLE` | `0.2` | 0–1. A little adds emotion; a lot adds wobble and latency. |
| `SMART_TURN` | `on` | `off` goes back to replying after any 150 ms pause. |
| `SMART_TURN_MAX_WAIT_MS` | `1400` | Longest wait for you to carry on when you sound mid-thought. |
| `BACKCHANNELS` | `on` | `off` stops the listener sounds ("mm-hmm", "yeah"…) while you talk. |
| `DEEPGRAM_MODEL` | `nova-3` | |
| `TTS_PROVIDER` | `auto` | `auto` uses ElevenLabs while it has credits, then switches to Deepgram's Aura voice (same Deepgram key). `elevenlabs` or `deepgram` forces one. |
| `DEEPGRAM_VOICE` | `aura-2-thalia-en` | Any Deepgram Aura voice, e.g. `aura-2-asteria-en`. |
| `JOB_AFTER_MS` | `4000` | How long a Mac command may run before it becomes a background job. |
| `CLOUD_JOB_AFTER_MS` | `8000` | The same, for cloud-server calls. |
| `DELEGATE_LIMIT_MIN` | `30` | Longest a job handed to Claude Code may run. |
| `DELEGATE_MODEL` | Claude Code's own default | Model for handed-off work, e.g. `sonnet`. |
| `DELEGATE_ALLOWED_TOOLS` | `Read,Edit,Write,Glob,Grep,Bash,WebSearch,WebFetch,TodoWrite` | Tools Claude Code may use without asking. |
| `CLAUDE_BIN` | found automatically | Path to the `claude` command, if it isn't in a usual place. |
| `CONFIRM_NEW_SITES` | `true` | `false` stops the one-time "did you mean…" check for websites Cipher hasn't opened before. |
| `NAME_HINTS` | `true` | `false` stops giving app and site names to speech recognition. |
| `PORT` | `3000` | |
| `OPEN_BROWSER` | `true` | Set to `false` to stop `npm start` opening a tab. |

Interruption sensitivity and pauses are constants at the top of `public/app.js` (`BARGE_IN_MS`, `SENTENCE_GAP_S`, …). Turn-end timing is in `server/deepgram.ts` (`endpointing`, `utterance_end_ms`).

## Testing

With the app running:

- `npm test` plays the recorded questions in `tests/audio/talk` at the app and prints, for each, how long it took from the end of speech to the first sound of the reply. Results are saved in `tests/out`.
- `node tests/run.mjs tasks` plays the task recordings. These really act on this Mac (open apps, add reminders), so run them on purpose.
- `node tests/run.mjs real` plays your own recordings: put 16 kHz mono 16-bit WAV files in `tests/audio/real`.
- `npm run test:models` compares how quickly two Claude models produce their first word.
- `PORT=3001 npm test` aims the tests at a second copy of the app on another port.

## Troubleshooting

- **"Missing API key" banner:** add the key to `.env` (not `.env.example`) and restart `npm start`.
- **Claude interrupts itself:** your speakers are leaking into the mic. Use headphones, lower the volume, or raise `BARGE_IN_MS` in `public/app.js`.
- **Claude replies before I finish:** short pauses are handled automatically, but if Claude often starts talking during long pauses, raise `endpointing` in `server/deepgram.ts` (e.g. `400`). Each 100 ms adds 100 ms to every reply.
- **ElevenLabs "exceeds your quota":** the free plan has 10,000 characters a month. The app switches to Deepgram's voice automatically (the terminal says which voice it's using at startup) and back to ElevenLabs after a restart once credits reset.
- **No audio but text appears:** check the error toast; usually an ElevenLabs key, quota or voice ID problem.
- **Camera blocked or "No camera found":** allow the camera from the address bar, and close other apps (Zoom, FaceTime) that may be using it.
- **Vision is slow:** your browser is probably running the model on the CPU. Use a recent Chrome or Edge (WebGPU), keep the Fast model, or close other heavy tabs.
- **A "Deepgram" error:** the message says exactly what's wrong (bad key, no credit, network blocked) and the same line is printed in the terminal running `npm start`. Keys in `.env` always win over variables exported in your shell, so an old `DEEPGRAM_API_KEY` in `~/.zshrc` can't interfere.
- **"No sound is reaching the app from your microphone":** the browser opened the mic but gets silence. Check System Settings → Sound → Input, and that the browser has microphone permission.
- **Replies feel slow:** watch the `[latency]` lines in the terminal. If "Claude first words" is over 1.5 s, your network or the API is slow; if "voice" is over 0.6 s, ElevenLabs is.
- **"Screenshot failed":** allow Screen Recording for Terminal (or whichever app runs `npm start`) in System Settings → Privacy & Security, then restart `npm start`.
- **"Not authorized to send Apple events":** macOS blocked control of an app. Allow it in System Settings → Privacy & Security → Automation.
- **Chrome extension not connecting:** make sure `npm start` is running, then copy the pairing code from Settings again (it's different on each computer). The extension retries every 30 seconds; click its icon to see the status.
- **"Vision model error":** the detector restarts itself a few times, then falls back to the CPU. Claude can still see camera stills while it's down. Reloading the page also fixes it.
- **Microphone blocked:** click the lock/mic icon in the address bar and allow the microphone. The page must be opened via `http://localhost`, not a LAN IP, for the browser to allow mic access over HTTP.

Tested in Chrome and Edge. Safari and Firefox should work, but their echo cancellation varies.
