# yt-clipper

**Automatically clip the moments a live stream's chat erupts — Twitch or YouTube —
and get them captioned, ranked and Shorts-ready. Fully local, fully free.**

yt-clipper waits for a stream to go live, records it from second one, watches
the chat in real time, and cuts a clip every time chat explodes. Each clip is
transcribed (whisper.cpp), scored 0–100 for virality with genre tags, rendered
as a vertical Short, and credited back to the creator. No accounts, no API
keys, no subscriptions — everything runs on your machine.

Inspired by the viral "Clip Watcher" concept for Twitch, with the paid
LLM-analysis step replaced by a deterministic local spike detector.

## Features

- **Waits for live, then records** — `streamlink --retry-streams` polls until
  the stream starts; captures everything from second one.
- **Reads chat for free** — Twitch via anonymous read-only IRC (`justinfan`
  nick, no login); YouTube via `pytchat` (no API key). Messages are logged
  with server-side timestamps.
- **Deterministic spike detection** — a bucket is flagged when it holds ≥ 3×
  the trailing 5-minute average (with a sanity floor); adjacent spiking
  buckets merge into one moment. Statistics, not guesswork.
- **Lossless cuts** — ffmpeg stream-copy, one clip per detected moment.
- **Captions** — whisper.cpp transcription to `.srt` + optional subtitle
  burn-in. Entirely offline.
- **Virality ranking** — every clip scored 0–100 from chat energy (peak rate,
  prominence, keyword intensity, duration fit, volume), genre-tagged
  (`hype`, `worst`, `surprise`, `fail`, `funny`), with "recommended" output —
  overall top clips + the best clip per genre.
- **Shorts-ready** — optional vertical 1080×1920 render of every clip
  (blurred-fill or center crop), audio copied through.
- **Credits built in** — the source creator's URL is embedded in clip
  metadata and logged to `clips/manifest.jsonl`.

## Requirements

- Linux or macOS; Windows via WSL 2 (Ubuntu recommended)
- Python ≥ 3.11, ffmpeg, curl, cmake + a C++ toolchain (whisper.cpp build)
- ~2 GB disk (Whisper model) plus 4–8 GB per stream hour at `best` quality
  (tune `twitch.quality` down if disk is tight)

## Install

```bash
git clone https://github.com/prateek-gadkar/yt-clipper.git
cd yt-clipper
./scripts/install.sh   # apt: ffmpeg; venv: streamlink + pytchat; whisper.cpp build; model download
```

Or the minimal path (captions auto-skip without the model):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# plus ffmpeg via your package manager, or: .venv/bin/pip install imageio-ffmpeg
```

## Quick start

```bash
cp config.example.toml config.toml
$EDITOR config.toml
source .venv/bin/activate
python -m clipper doctor    # dependency + config health check
python -m clipper watch     # waits for live → records → cuts → ranks → captions
```

Twitch:

```toml
[source]
platform = "twitch"
[twitch]
channel = "some_channel"    # the name in twitch.tv/<name>, no leading '#'
```

YouTube live:

```toml
[source]
platform = "youtube"
[youtube]
url  = "https://www.youtube.com/watch?v=VIDEO_ID"   # the LIVE stream URL
name = "streamerhandle"                              # label used in filenames/credits
```

```bash
python -m clipper watch
# one-off without config:
python -m clipper watch --url https://www.youtube.com/watch?v=VIDEO_ID --name streamerhandle
```

YouTube live quality names include the frame rate (`720p60`, `1080p60`); a
plain `720p` doesn't exist there. Run `streamlink <url>` to list a stream's
available qualities. As a safety net, if the requested quality can't start a
recording, `watch` automatically retries once with `best`.

`watch` waits for the stream to go live, records until it ends, then cuts,
ranks, captions and (optionally) renders Shorts versions automatically.
Interrupting with `Ctrl+C` still finalizes everything recorded so far.

## How it works

```
 live stream ──► streamlink ──► work/<label>/<session>/stream.ts
      │
      └─► chat (IRC / pytchat) ──► chat.log ──► spike detection ──► cut windows
                                                        │
                                     ffmpeg cut ◄───────┘
                                              │
                    ┌───────────────┬─────────┴───────┐
                    ▼               ▼                 ▼
               virality        whisper.cpp        Shorts render
              ranking          captions          1080×1920
```

Spike detection (`clipper/spikes.py`):

1. Bucket chat messages into fixed windows (default 10 s).
2. For each bucket, compute the trailing average over the previous 300 s
   (5 minutes). Buckets already flagged as spikes are excluded from that
   average, so a burst doesn't mask the rest of itself.
3. Flag a bucket when it is ≥ 3× that trailing average and ≥ `min_messages`
   (default 6) strong — the floor prevents near-silent channels from
   false-positive matches.
4. Merge flagged buckets separated by ≤ `merge_gap_seconds` (30 s) into a
   single moment.

Chat reacts after the play, so cuts start `pre_pad_seconds` (8 s) before the
spike and run `post_pad_seconds` (10 s) past the last spiking bucket, capped
at `max_clip_seconds` (120 s). All tunable in `config.toml` under `[spike]`.

## Virality ranking

Every cut clip is scored **0–100** from chat energy alone — no API, no LLM:

| Component | Weight | What it captures |
|---|---|---|
| Peak rate | 25 | loudest 10 s bucket in the window (saturates ~60 msgs) |
| Prominence | 25 | burst chat rate vs the stream's baseline (saturates ~6×) |
| Keyword intensity | 20 | fraction of burst messages matching the genre lexicons |
| Duration fit | 15 | gaussian sweet spot centered on 45 s |
| Volume | 15 | total messages in the window, log scale |

Each clip is tagged by genre from the chat inside its window:

| Genre | Meaning | Example markers |
|---|---|---|
| `hype` | best plays / clutches | "CLIP IT", "insane", "clutch", "gg", "W" |
| `worst` | throws / blunders | "worst", "throw", "choke", "disappointing" |
| `surprise` | shocks / plot twists | "no way", "HOW?!", "wait what", "OMG" |
| `fail` | glitches / bugs | "bug", "glitch", "broken", "desync" |
| `funny` | comedy | "lol", "lmao", "kek", "xd" |

Output: `clips/ranked.json` — every clip with `rank`, `score`, `genres`,
`components` and a `recommended` flag. **Recommended = overall top 3 + the
best clip of each genre**, so a batch covers different kinds of moments
rather than near-duplicates. Set `virality.max_clips = N` to caption only the
N recommended clips (cutting is cheap; captioning is the slow step).

This is a chat-energy heuristic — a post-order hint, not a prophecy. Token
sets live in `GENRE_LEXICONS` in `clipper/virality.py`; extend them for your
community's emotes and slang.

## Captions

```bash
# included in scripts/install.sh; manual steps for reference:
git clone --depth 1 https://github.com/ggml-org/whisper.cpp ~/whisper.cpp
cmake -B ~/whisper.cpp/build -S ~/whisper.cpp -DCMAKE_BUILD_TYPE=Release
cmake --build ~/whisper.cpp/build -j
ln -sf ~/whisper.cpp/build/bin/whisper-cli ~/.local/bin/whisper-cli
cd models && curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin
```

Per clip: ffmpeg extracts a 16 kHz mono WAV → `whisper-cli -osrt` produces a
`.srt` → with `burn_in = true` a `<name>.captioned.mp4` renders with subtitles
baked in (requires libass; Debian's and imageio-ffmpeg's ffmpeg include it).
Smaller models (`ggml-base.en.bin` ~140 MB, `ggml-small.en.bin` ~460 MB) are
drop-in replacements via `paths.whisper_model`. Captioning is skipped
gracefully if whisper-cli or the model is missing; cuts still proceed.

## Commands

```
python -m clipper watch [--url URL] [--name LABEL]   # the whole loop
python -m clipper chatlog            # chat logging only
python -m clipper analyze chat.log [--virality]      # spikes + windows (+ ranking)
python -m clipper cut stream.ts chat.log [--rec-start UNIXTS]
python -m clipper caption clip.mp4 [--no-burn]
python -m clipper shorts clip.mp4 [--mode blur|crop] # vertical 9:16 render
python -m clipper doctor             # dependency/config health check
python -m clipper demo               # end-to-end proof on synthetic data
```

## Credits & attribution

Every clip carries the source creator's URL in its metadata comment, and
`clips/manifest.jsonl` records the credit line, source URL and time range for
every cut. Clip, credit and link the creator.

## Copyright & reposting

Stream footage is its creator's copyrighted work. Crediting and linking the
creator is courtesy, not a license; automated rights matching (e.g. YouTube
Content ID) operates on audio/video regardless of whether you add credit, and
fair use/fair dealing is a case-by-case legal analysis, not a guarantee.
Respect the creator's rights and platform terms: get permission before
publicly reposting their footage, and treat private, personal use as the
safe default. This project is not legal advice — consult a qualified attorney
for questions about reposting content you don't own.

## Limitations

- Live streams only — it records the live feed; it cannot process past VODs.
- `watch` blocks until the stream ends (or you interrupt it).
- Stream-copy cuts may begin up to one keyframe early; the pre-pad hides it.
- Spike detection is statistics: emote storms trigger it, quiet brilliance
  doesn't. Tune `[spike]` in config.toml.
- The virality score is a heuristic, not a prediction of views.
- whisper.cpp needs ~1.5 GB disk for the model and CPU/GPU time per clip.
- YouTube live chat can lag or drop during traffic spikes; pytchat retries.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python -m clipper demo
```

Project layout:

```
clipper/
  cli.py        command-line interface (watch / chatlog / analyze / cut / caption / shorts / doctor / demo)
  watch.py      wait-for-live → record → finalize orchestrator (Twitch + YouTube)
  irc.py        anonymous read-only Twitch IRC chat logger
  ytchat.py     YouTube live chat logger via pytchat
  spikes.py     spike detection + clip-window planner
  virality.py   0–100 scoring, genre tagging, recommended selection
  shorts.py     vertical 9:16 Shorts rendering
  cut.py        ffmpeg stream-copy cutting + credit manifest
  captions.py   whisper.cpp transcription + subtitle burn-in
  finalize.py   recording + chat.log → ranked, captioned clips
  config.py     config.toml loading
  demo.py       synthetic end-to-end proof
scripts/install.sh   installer (Debian/Ubuntu)
tests/               unittest suite
```

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

Built on [streamlink](https://streamlink.github.io/),
[ffmpeg](https://ffmpeg.org/), [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
and [pytchat](https://github.com/taizan-hokuto/pytchat).
