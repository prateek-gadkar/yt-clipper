"""The 'while you sleep' command: wait for live -> record + log chat -> auto-clip."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import finalize
from .ffmpegutil import find_ffmpeg, find_tool
from .irc import ChatLogger


def cmd_watch(cfg) -> int:
    channel = cfg.require_channel()

    streamlink = find_tool("streamlink")
    if not streamlink:
        sys.exit("streamlink not found. Install it first: pip3 install --user streamlink  (or scripts/install.sh)")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found. Install it: sudo apt install ffmpeg  (or pip3 install imageio-ffmpeg)")

    session = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = Path(cfg.get("paths", "work_dir", default="./work")).expanduser() / channel / session
    clips_dir = Path(cfg.get("paths", "clips_dir", default="./clips")).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    stream_ts = work / "stream.ts"
    chat_log = work / "chat.log"

    quality = cfg.get("twitch", "quality", default="best")
    retry = int(cfg.get("twitch", "retry_streams", default=30))

    print(f"[clip-watcher] channel   : twitch.tv/{channel}")
    print(f"[clip-watcher] recording : {stream_ts}")
    print(f"[clip-watcher] chat log  : {chat_log}")
    print(f"[clip-watcher] waiting for the stream to go live (streamlink --retry-streams {retry}) ...")
    print("[clip-watcher] leave it running. Ctrl+C at any time — clips are still cut from what was recorded.")

    stop = threading.Event()
    logger = ChatLogger(channel, chat_log)
    chat_thread = threading.Thread(target=logger.run, args=(stop,), daemon=True, name="chat-logger")
    chat_thread.start()

    cmd = [
        streamlink,
        f"twitch.tv/{channel}",
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
            rec_start_unix = stream_ts.stat().st_mtime - stream_ts.stat().st_size / 1_000_000  # rough
        else:
            rec_start_unix = time.time()

    if not stream_ts.exists() or stream_ts.stat().st_size == 0:
        print("[clip-watcher] nothing was recorded (stream never went live?). Check the channel name.")
        return 1

    print(f"[clip-watcher] recording ended ({'interrupted by you' if interrupted else 'stream offline'}).")
    print(f"[clip-watcher] raw file: {stream_ts}  ({stream_ts.stat().st_size / 1_048_576:.1f} MB)")

    summary = finalize.finalize(cfg, stream_ts, chat_log, rec_start_unix, clips_dir, ffmpeg)
    print(f"[clip-watcher] done. {len(summary['clips'])} clip(s) in {clips_dir}")
    print("[clip-watcher] One rule: clip, credit and link the streamer. Credits are embedded in each clip "
          "(comment metadata) and listed in clips/manifest.jsonl.")
    return 0
