# yt-clipper — the Clip Watcher, built for you personally, $0

A free, fully local clone of "The Clip Watcher": a one-folder tool that
**records a Twitch stream from second one, watches chat react in real time,
finds the moments where chat erupts, and cuts + captions clips automatically —
no accounts, no subscriptions, no API bills.**

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
| Spike detection ("ask Claude Code") | **paid** | **free, built in** |
| ffmpeg (cut) | free | free |
| whisper.cpp captions (`whisper-cli` + ggml model) | free | free |
| **Total** | paid | **$0, forever** |

## Quick start

```bash
git clone <this-repo-url> && cd yt-clipper

./scripts/install.sh            # apt: ffmpeg; venv: streamlink; builds whisper.cpp; downloads the model
cp config.example.toml config.toml
$EDITOR config.toml             # set twitch.channel = "some_channel"  (no leading '#')

source .venv/bin/activate
python -m clipper doctor        # every line should say [OK]
python -m clipper watch         # ← the "while you sleep" command
```

`watch` does the whole loop by itself:

1. **Waits for live** — `streamlink --retry-streams 30 --retry-max 0` polls
   until the channel goes live, then starts recording `work/<channel>/<session>/stream.ts`.
2. **Reads chat from second one** — anonymous, read-only IRC
   (`justinfan<random>`, no login), every message timestamped into `chat.log`.
3. **Stream ends** → spikes are detected locally → ffmpeg cuts one clip per
   moment into `clips/` → whisper.cpp transcribes each clip and (optionally)
   burns the subtitles in → `clips/manifest.jsonl` is updated with credits.

Leave it running overnight. If you `Ctrl+C` early, it finalizes whatever it
has instead of dying empty-handed.

## Verify it without a live stream

```bash
python -m clipper demo     # synthesizes chat + a test VOD, runs the real pipeline
```

You should see a detected spike, a rendered fake VOD, and a real cut clip in
`demo-out/clips/`.

## Commands

```
python -m clipper watch              # the whole loop (above)
python -m clipper chatlog            # chat logging only
python -m clipper analyze chat.log   # print spikes + cut windows (the free "ask Claude" step)
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
subtitles baked in (needs an ffmpeg built with libass, which Debian's is).

Smaller/faster models (`ggml-base.en.bin` ~140 MB, `ggml-small.en.bin` ~460 MB)
are drop-in replacements — set `paths.whisper_model` accordingly. Captioning is
skipped gracefully if whisper-cli or the model is missing; the clips still cut fine.

## The one rule: clip, credit, and link

Baked into the tool:

- every clip gets `comment` metadata: `Clip from <channel>'s live stream -
  https://www.twitch.tv/<channel> - credit & link the streamer`
- `clips/manifest.jsonl` records clip path, time range, source URL and the
  credit line for every cut — copy-paste it into your post/video description

Respect the streamer: credit and link them, and get their blessing before
re-uploading elsewhere. Twitch's own Clip button is the zero-permission
option; downloaded stream footage re-hosted without consent can violate
Twitch's Terms of Service and the streamer's rights (plus whatever music is
playing in the stream). This tool is built for personal use and for clipping
*with* creators, not for ripping and re-selling.

## Honest limitations

- **Works only while the channel is live** — that's inherent to the model.
  It records the live feed; it does not fetch past VODs.
- `watch` blocks until the stream ends (or you Ctrl+C). That's the intended
  "leave it running" behavior.
- Clips are cut with stream-copy, so a cut may begin up to one keyframe
  early; the 8 s pre-pad makes this invisible in practice.
- Spike detection is statistics, not taste: hype trains and emote storms will
  trigger it (usually what you want), and a quiet-but-brilliant play won't be.
- whisper.cpp needs ~1.5 GB disk for the model and real CPU/GPU for speed.

## Project layout

```
clipper/
  cli.py        argparse front-end (watch / analyze / cut / caption / doctor / demo)
  watch.py      wait-for-live → record → finalize orchestrator
  irc.py        anonymous read-only Twitch IRC chat logger (auto-reconnect)
  spikes.py     the deterministic spike detector + clip-window planner
  cut.py        ffmpeg stream-copy cutting + credit manifest
  captions.py   whisper.cpp transcription + subtitle burn-in
  finalize.py   recording + chat.log → clips pipeline
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
