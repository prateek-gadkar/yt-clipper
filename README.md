# yt-clipper — the Clip Watcher, built for you personally, $0

A free, fully local clone of "The Clip Watcher": a one-folder tool that
**records a live stream from second one — Twitch or YouTube — watches chat
react in real time, finds the moments where chat erupts, and cuts + captions +
ranks clips automatically — no accounts, no subscriptions, no API bills.**

The original post's most expensive step — "paste chat.log into Claude Code and
ask it to find the spikes" — is replaced here by a **deterministic local spike
detector** implementing the exact same recipe:

> count messages per 10 seconds → flag any bucket that is **3× the trailing
> 5-minute average** (with a sanity floor), merge adjacent spiking buckets
> into one moment.

That is plain statistics, not intelligence — so it costs nothing and never
leaves your machine.

## Cost breakdown (vs. the post)

| Piece | Post's cost | This repo |
|---|---|---|
| streamlink (record) | free | free |
| Twitch IRC chat read (anonymous `justinfan` nick) | free | free |
| YouTube live chat read (`pytchat`, no API key) | — | free |
| Spike detection ("ask Claude Code") | **paid** | **free, built in** |
| Virality ranking + genre tagging | — | free, built in |
| ffmpeg (cut) | free | free |
| whisper.cpp captions (`whisper-cli` + ggml model) | free | free |
| **Total** | paid | **$0, forever** |

## Quick start

```bash
git clone <this-repo-url> && cd yt-clipper

./scripts/install.sh            # apt: ffmpeg; venv: streamlink + pytchat; builds whisper.cpp; downloads the model
cp config.example.toml config.toml
$EDITOR config.toml             # point it at a channel (Twitch) or a live URL (YouTube) — see below

source .venv/bin/activate
python -m clipper doctor        # every line should say [OK]
python -m clipper watch         # ← the "while you sleep" command
```

`watch` does the whole loop by itself:

1. **Waits for live** — `streamlink --retry-streams 30 --retry-max 0` polls
   until the stream goes live, then starts recording
   `work/<label>/<session>/stream.ts`.
2. **Reads chat from second one** — Twitch: anonymous, read-only IRC
   (`justinfan<random>`, no login). YouTube: `pytchat`, no API key. Every
   message timestamped into `chat.log`.
3. **Stream ends** → spikes detected locally → ffmpeg cuts one clip per moment
   into `clips/` → every clip **scored 0–100 for virality and tagged by genre**
   (`clips/ranked.json`) → whisper.cpp transcribes + burns subtitles in →
   `clips/manifest.jsonl` updated with credits.

Leave it running overnight. `Ctrl+C` still finalizes what it has.

## Install & run — the short version

```bash
./scripts/install.sh          # do once
cp config.example.toml config.toml && $EDITOR config.toml
source .venv/bin/activate
python -m clipper doctor      # sanity check
python -m clipper watch       # go to sleep; wake up to captioned, ranked clips
```

To run **without** installing the whisper model (captions auto-skip):
just install streamlink + ffmpeg via pip/apt; everything else is optional.
`requirements.txt` is the minimal pip list. `scripts/install.sh` does the
full heavy install including whisper.cpp.

## Twitch (default)

```toml
[source]
platform = "twitch"
[twitch]
channel = "some_channel"      # the name in twitch.tv/<name>, no leading '#'
```
```bash
python -m clipper watch
```

## YouTube live too

Same pipeline, two changes — the live-chat reader (pytchat instead of IRC) and
the recorder URL (streamlink reads YouTube live fine):

```toml
[source]
platform = "youtube"
[youtube]
url  = "https://www.youtube.com/watch?v=VIDEO_ID"   # the LIVE stream URL
name = "streamerhandle"                              # label for filenames/credits
```
```bash
python -m clipper watch
# or one-off without editing config:
python -m clipper watch --url https://www.youtube.com/watch?v=VIDEO_ID --name streamerhandle
```

Notes:

- `pytchat` reads live chat **only while the stream is live** — same inherent
  constraint as the Twitch model. No API key, no OAuth, read-only.
- YouTube live chat timestamps come from YouTube itself, so spike detection is
  equally accurate.
- `python -m clipper analyze chat.log --virality` previews the ranking without
  cutting anything.

## Virality ranking (the honest version)

`clipper/virality.py` scores every cut clip **0–100** from chat energy alone —
free, local, heuristic:

| Component | Weight | What it captures |
|---|---|---|
| Peak rate | 25 | loudest 10s bucket in the window (saturates at ~60 msgs/10s) |
| Prominence | 25 | burst chat rate vs the stream's baseline rate (saturates ~6×) |
| Keyword intensity | 20 | fraction of burst messages matching an emotional lexicon |
| Duration fit | 15 | gaussian sweet spot around 45s — Shorts territory |
| Volume | 15 | total messages in the window, log scale |

Each clip is also **genre-tagged** from the chat inside its window:

| Genre | What it means | Example chat markers |
|---|---|---|
| `hype` | BEST plays / clutches | "CLIP IT", "insane", "clutch", "gg", "W" |
| `worst` | THROWS / blunders / disappointment | "worst", "throw", "choke", "L", "disappointing" |
| `surprise` | shock moments / plot twists | "no way", "HOW?!", "wait what", "OMG" |
| `fail` | glitches & bugs | "bug", "glitch", "broken", "desync" |
| `funny` | comedy | "lol", "lmao", "kek", "xd" |

Output: `clips/ranked.json` — every clip with `rank`, `score`, `genres`,
`components`, and a `recommended` flag. **Recommended = overall top 3 + the
best clip of each genre**, so your upload queue covers BEST / WORST /
SURPRISING / FAIL / FUNNY instead of five copies of the same hype play.
`clips/manifest.jsonl` carries the same data for the full cut set.

`virality.max_clips = N` in config captions only the N recommended clips
(captioning is the slow step; cutting is cheap). `0` captions everything.

**What this cannot do:** guarantee views. Nobody's tool can — virality depends
on timing, thumbnail, title, audio, the streamer's fanbase, and luck. What it
does is sort 60 mediocre candidates into "post these first" with reasons, tag
every genre so your channel looks varied, and remove the 3 a.m. decision
fatigue. That's the edge. Post ★ clips in rank order, stagger uploads, and
watch which genre your audience actually clicks — then tune the lexicons in
`virality.py` to your niche.

## Verify it without a live stream

```bash
python -m clipper demo     # synthesizes chat + a test VOD, runs the real pipeline
```

You should see a detected spike, the virality ranking with genre tags, a
rendered fake VOD, and a real cut clip in `demo-out/clips/`.

## Commands

```
python -m clipper watch [--url URL] [--name LABEL]   # the whole loop (above)
python -m clipper chatlog            # chat logging only
python -m clipper analyze chat.log [--virality]      # print spikes + cut windows (+ ranking)
python -m clipper cut stream.ts chat.log [--rec-start UNIXTS]
python -m clipper caption clip.mp4 [--no-burn]
python -m clipper doctor             # dependency/config health check
python -m clipper demo               # synthetic end-to-end proof
```

## How the spike detection works

`clipper/spikes.py`:

1. Bucket all chat messages into fixed windows (default **10 s**).
2. For each bucket, compute the trailing average over the previous
   **300 s (5 minutes)**. Buckets already flagged as spikes are excluded from
   that average, so a burst doesn't hide the next bucket of the same burst.
3. Flag a bucket when it is **≥ 3×** that trailing average **and** at least
   `min_messages` (default 6) strong. (The floor stops a one-message whisper
   on a dead channel from tripping the multiplier.)
4. Merge flagged buckets separated by ≤ `merge_gap_seconds` (30 s) into one
   "moment".

Chat reacts **after** the play happens, so cuts start
`pre_pad_seconds` (8 s) *before* the spike and run `post_pad_seconds` (10 s)
past the last spiking bucket, capped at `max_clip_seconds` (120 s).

All of this is tunable in `config.toml` under `[spike]`.

## Captions (whisper.cpp, free)

```bash
# already done by scripts/install.sh; manual steps for reference:
git clone --depth 1 https://github.com/ggml-org/whisper.cpp ~/whisper.cpp
cmake -B ~/whisper.cpp/build -S ~/whisper.cpp -DCMAKE_BUILD_TYPE=Release
cmake --build ~/whisper.cpp/build -j
ln -sf ~/whisper.cpp/build/bin/whisper-cli ~/.local/bin/whisper-cli
mkdir -p models && cd models
curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin
```

Per clip: ffmpeg extracts 16 kHz mono WAV → `whisper-cli -osrt` produces a
`.srt` → with `burn_in = true` a `<name>.captioned.mp4` is rendered with the
subtitles baked in (needs an ffmpeg built with libass, which Debian's and
imageio-ffmpeg's are).

Smaller/faster models (`ggml-base.en.bin` ~140 MB, `ggml-small.en.bin` ~460 MB)
are drop-in replacements — set `paths.whisper_model` accordingly. Captioning is
skipped gracefully if whisper-cli or the model is missing; the clips still cut fine.

## Posting these clips to YouTube: the copyright reality

You asked: *"so I can post these clips on YT without facing copyright acts,
right?"* — the honest answer is **no, not automatically.** Read this before
launch week:

**The footage belongs to the creator.** A Twitch stream or YouTube live is the
streamer's copyrighted performance, captured on tape — plus any licensed music
playing in it. Uploading a clip = making a copy and publicly displaying it.
Credit and a link are courtesy, **not a license**. None of the following is a
shield:

- "I credited the streamer" — reduces drama, gives no rights.
- "It's a Short, only 45 seconds" — length doesn't matter.
- "Everyone else does it" — Content ID doesn't care how common the infringement is.
- "Fair use" — a defense you raise *after* a lawsuit/strike, judged case by
  case. It is not a pre-upload checkbox. Commentary/criticism can qualify, but
  "raw clip + captions" is not criticism.

**What actually happens on YouTube:** Rights Manager/Content ID scans your
upload against reference files. Match → the claimant chooses: monetize it (ad
revenue goes to them), mute it, or block it worldwide — or, if you've
accumulated strikes, suspend the channel. Streamer music is the #1 trigger;
many clip channels get muted for the background track alone.

**The playbooks that actually work:**

1. **Get the streamer's permission.** For launch week, most streamers are
   *begging* for clip channels — they grow from it. DM them: "I run a clip
   channel, my tool picks the 3x-chat moments automatically, want your clips
   posted with full credit + link?" Many say yes, some want revenue share —
   that's fine, it's legal and durable. Ask *before* you upload.
2. **Clip your own footage.** Your own GTA 6 PS5/Xbox gameplay recorded by you
   is *your* video. Game publishers (Rockstar included) have historically
   tolerated/monetized fan gameplay videos within their fan-content policies —
   read Rockstar's current policy and avoid copyrighted music in your VODs.
   Your own stream + this same tool watching *your* chat is the lowest-risk,
   highest-loyalty clip source that exists.
3. **Use the creator's official clips.** Twitch's native Clip button creates
   clips the streamer sees and can delete; re-uploading them to YT still needs
   permission, but asking for *those* is the easiest yes.
4. **Add real commentary/analysis.** A talking-head reaction or breakdown can
   be genuinely transformative — still not a guarantee, but it's the legal
   posture fair use is actually built on.
5. **Personal use only, for everything else.** Watching, cutting, and studying
   clips privately is fine. The line is *public upload + monetization*.

This is not legal advice — I'm a coding assistant, not a lawyer, and copyright
law depends on your jurisdiction (you're in India; Indian Copyright Act fair
dealing is even narrower than US fair use for this kind of thing). For a
monetized English-language channel, a one-hour consult with an IP attorney is
cheaper than one terminated channel. And remember the tool's built-in rule:
**clip, credit, and link the creator — and ask before you post their footage.**

### The GTA 6 launch plan (Nov 19, 2026)

GTA VI launches **Thursday, November 19, 2026** — three days from today, on
PS5/Xbox. Launch weekend is the one window where clip channels get outsized
reach, because everyone searches the same keywords at once. How to compete
without eating strikes:

- **Be the fastest, not the loudest.** This tool cuts, captions and ranks
  clips while the streamer is still live. Being first with a clean 45s Short
  beats being third with a better thumbnail.
- **Cover every genre.** The ranker is built for exactly this launch: clutch
  missions (`hype`/BEST), catastrophic fails (`fail`), hilarious ragdolls
  (`funny`), impossible moments (`surprise`), rage-quits and terrible decisions
  (`worst`) — post one of *each* per day, ranked order, and let analytics tell
  you which genre your audience rewards. Your competition will post ten
  versions of the same hype play; you'll have the full spectrum.
- **Your own first-playthrough VODs are the gold.** Record your first session,
  point `clipper` at your own stream, and your clips are yours to post with
  zero permission questions. That's the unfair advantage nobody can strike.
- **Partner early.** Streamers going live at midnight launch need clip
  channels *that week*. A permission DM sent today beats a DMCA tomorrow.

## The one rule (unchanged)

Clip, credit, and link the creator — and get permission before publicly
reposting their footage. The tool embeds the credit in every clip's metadata
and in `clips/manifest.jsonl`. What you do with it after that is the legal
judgment call described above.

## Honest limitations

- **Works only while the live stream is live** — inherent to the model.
- `watch` blocks until the stream ends (or you Ctrl+C, which still finalizes).
- Stream-copy cuts may begin up to one keyframe early; the 8s pre-pad hides it.
- Spike detection is statistics, not taste: emote storms trigger it (fine),
  quiet brilliance doesn't (tune `min_messages`/`multiplier`).
- Virality ranking is a chat-energy heuristic — post-order advice, not a
  prophecy. Genre tagging depends on English chat lexicons; extend
  `GENRE_LEXICONS` in `virality.py` for your community's emotes/slang.
- whisper.cpp needs ~1.5 GB disk for the model and real CPU/GPU for speed.
- YouTube live chat can lag/drop during extreme raids; pytchat auto-retries.

## Project layout

```
clipper/
  cli.py        argparse front-end (watch / chatlog / analyze / cut / caption / doctor / demo)
  watch.py      wait-for-live → record → finalize orchestrator (Twitch + YouTube)
  irc.py        anonymous read-only Twitch IRC chat logger (auto-reconnect)
  ytchat.py     YouTube live chat logger via pytchat (no API key)
  spikes.py     the deterministic spike detector + clip-window planner
  virality.py   0-100 virality scoring, genre tagging, ★ recommendation
  cut.py        ffmpeg stream-copy cutting + credit manifest
  captions.py   whisper.cpp transcription + subtitle burn-in
  finalize.py   recording + chat.log → ranked, captioned clips
  config.py     config.toml loading (defaults + your overrides)
  demo.py       synthetic end-to-end proof, no live stream required
scripts/install.sh   one-shot free installer (Debian/Ubuntu)
tests/               unittest suite (python -m unittest discover -s tests)
```

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python -m clipper demo
```
