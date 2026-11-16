"""The 'while you sleep' command: wait for live -> record + log chat -> auto-clip, rank, caption.

Sources (pick one in config.toml, or override on the command line):
  * Twitch  — anonymous read-only IRC chat, channel from twitch.channel
  * YouTube — pytchat (no API key) reads the live chat, stream link from
              youtube.url or `--url https://www.youtube.com/watch?v=...`

Both pipelines write the identical chat.log TSV, so detection, cutting,
ranking and captioning are source-agnostic.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import finalize
from .ffmpegutil import find_ffmpeg, find_tool
from .irc import ChatLogger
from .ytchat import YouTubeChatLogger


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_") or "clip"


def cmd_watch(cfg, args=None) -> int:
    url_arg = getattr(args, "url", None) if args else None
    name_arg = getattr(args, "name", None) if args else None

    # ---- pick the source -------------------------------------------------
    if url_arg or cfg.get("source", "platform", default="twitch") == "youtube":
        platform = "youtube"
        url = (url_arg or cfg.get("youtube", "url", default="")).strip()
        if not url:
            sys.exit("No YouTube live URL configured.\n"
                     "  1. cp config.example.toml config.toml\n"
                     "  2. set source.platform = \"youtube\" and youtube.url = \"https://www.youtube.com/watch?v=...\"\n"
                     "     (or just run: python -m clipper watch --url <live-url>)\n")
        label = _slug(name_arg or cfg.get("youtube", "name", default="youtube_live"))
        record_url = url
        logger = None
    else:
        platform = "twitch"
        channel = cfg.require_channel()
        label = channel
        record_url = f"twitch.tv/{channel}"
        logger = None

    # ---- pre-flight checks ------------------------------------------------
    streamlink = find_tool("streamlink")
    if not streamlink:
        sys.exit("streamlink not found. Install it first: pip3 install --user streamlink  (or scripts/install.sh)")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found. Install it: sudo apt install ffmpeg  (or pip3 install imageio-ffmpeg)")

    session = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = Path(cfg.get("paths", "work_dir", default="./work")).expanduser() / label / session
    clips_dir = Path(cfg.get("paths", "clips_dir", default="./clips")).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    stream_ts = work / "stream.ts"
    chat_log = work / "chat.log"

    if platform == "youtube":
        logger = YouTubeChatLogger(record_url, chat_log)
        source_url = record_url
        credit = f"Clip from {label}'s YouTube live - {source_url} - credit & link the creator"
    else:
        logger = ChatLogger(label, chat_log)
        source_url = f"https://www.twitch.tv/{label}"
        credit = f"Clip from {label}'s live stream - {source_url} - credit & link the streamer"

    quality = cfg.get("youtube" if platform == "youtube" else "twitch", "quality",
                      default=cfg.get("twitch", "quality", default="best"))
    retry = int(cfg.get("twitch", "retry_streams", default=30))

    print(f"[clip-watcher] source    : {platform} ({record_url})")
    print(f"[clip-watcher] recording : {stream_ts}")
    print(f"[clip-watcher] chat log  : {chat_log}")
    print(f"[clip-watcher] waiting for the stream to go live (streamlink --retry-streams {retry}) ...")
    print("[clip-watcher] leave it running. Ctrl+C at any time — clips are still cut from what was recorded.")

    stop = threading.Event()
    chat_thread = threading.Thread(target=logger.run, args=(stop,), daemon=True, name="chat-logger")
    chat_thread.start()

    cmd = [
        streamlink,
        record_url,
        quality,
        "-o", str(stream_ts),
        "--retry-streams", str(retry),
        "--retry-max", "0",  # retry forever until live
    ]
    proc = subprocess.Popen(cmd)

    rec_start_unix: float | None = None
    interrupted = False
    try:
        while proc.poll() is None:
            if rec_start_unix is None and stream_ts.exists() and stream_ts.stat().st_size > 0:
                rec_start_unix = time.time()
                print(f"[clip-watcher] LIVE — recording started {datetime.fromtimestamp(rec_start_unix).isoformat(timespec='seconds')}")
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True
        print("\n[clip-watcher] Ctrl+C — finalizing what we have...")
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    finally:
        stop.set()
        chat_thread.join(timeout=10)

    if rec_start_unix is None:
        if stream_ts.exists() and stream_ts.stat().st_size > 0:
            st = stream_ts.stat()
            rec_start_unix = st.st_mtime - st.st_size / 1_000_000  # rough
        else:
            rec_start_unix = time.time()

    if not stream_ts.exists() or stream_ts.stat().st_size == 0:
        print("[clip-watcher] nothing was recorded (stream never went live?). Check the link/channel name.")
        return 1

    print(f"[clip-watcher] recording ended ({'interrupted by you' if interrupted else 'stream offline'}).")
    print(f"[clip-watcher] raw file: {stream_ts}  ({stream_ts.stat().st_size / 1_048_576:.1f} MB)")

    summary = finalize.finalize(cfg, stream_ts, chat_log, rec_start_unix, clips_dir, ffmpeg,
                                source_url=source_url, credit=credit, label=label)
    print(f"[clip-watcher] done. {len(summary['clips'])} clip(s) in {clips_dir}")
    print("[clip-watcher] Post smart: ranked.json lists the best bets first (★ = recommended,")
    print("               covering BEST/WORST/SURPRISING/FUNNY/FAIL). But remember: these are the")
    print("               creator's footage — get permission before re-uploading. See README#legal.")
    return 0
