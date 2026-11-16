"""yt-clipper Clip Watcher — command line interface.

  python -m clipper doctor              check what's installed
  python -m clipper watch               wait for live, record, cut, rank and caption
  python -m clipper chatlog             log chat only
  python -m clipper analyze chat.log    print spikes (the free replacement for the paid LLM step)
  python -m clipper cut stream.ts ...   cut clips from a finished recording
  python -m clipper caption clip.mp4    whisper.cpp captions for one clip
  python -m clipper demo                end-to-end proof on synthetic data (no live stream needed)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

from . import __version__, captions, finalize, watch
from .config import load
from .ffmpegutil import find_ffmpeg, find_tool
from .irc import ChatLogger



def _print_spikes(chat_log: str, cfg, show_virality: bool = False) -> int:
    analysis = finalize.analyze(chat_log, cfg)
    print(f"messages : {analysis['message_count']}")
    if not analysis["spikes"]:
        print("spikes   : none (chat never hit 3x its trailing 5-minute average)")
        return 0
    for i, s in enumerate(analysis["spikes"], 1):
        print(
            f"spike {i}: {datetime.fromtimestamp(s.start).isoformat(timespec='seconds')} -> "
            f"{datetime.fromtimestamp(s.end).isoformat(timespec='seconds')}  "
            f"peak {s.peak_count} msg/bucket, {s.buckets} bucket(s)"
        )
    for j, (a, b) in enumerate(analysis["windows"], 1):
        print(
            f"window {j}: {datetime.fromtimestamp(a).isoformat(timespec='seconds')} -> "
            f"{datetime.fromtimestamp(b).isoformat(timespec='seconds')}  ({b - a:.0f}s)"
        )
    if show_virality:
        from . import virality as _vir

        entries = [
            {
                "clip": f"<window-{j}>",
                "start_iso": datetime.fromtimestamp(a).isoformat(timespec="seconds"),
                "duration_seconds": b - a,
            }
            for j, (a, b) in enumerate(analysis["windows"], 1)
        ]
        bucket = int(cfg.section("spike").get("bucket_seconds", 10))
        _vir.print_ranked(_vir.score_clips(analysis["messages"], entries, bucket_seconds=bucket))
    return 0


def _tool_on_path(name: str):
    return find_tool(name)


def cmd_doctor(cfg) -> int:
    ok = True

    def check(name, found, hint):
        nonlocal ok
        status = "OK " if found else "MISSING"
        if not found:
            ok = False
        print(f"  [{status}] {name}" + ("" if found else f"  -> {hint}"))

    print("Clip Watcher doctor\n")
    check("python >= 3.11", sys.version_info >= (3, 11), "install Python 3.11+")
    streamlink = _tool_on_path("streamlink")
    check("streamlink", bool(streamlink), "pip3 install --user streamlink  (or: scripts/install.sh)")
    if streamlink:
        print(f"         streamlink: {streamlink}")
    try:
        import pytchat  # noqa: F401

        print("  [OK ] pytchat (YouTube live chat)")
    except ImportError:
        platform = cfg.get("source", "platform", default="twitch")
        status = "MISSING" if platform == "youtube" else "missing (only needed for YouTube)"
        print(f"  [{status}] pytchat  -> pip3 install pytchat  (or: scripts/install.sh)")
    ffmpeg = find_ffmpeg()
    check("ffmpeg", bool(ffmpeg), "sudo apt install ffmpeg   (or: pip3 install imageio-ffmpeg)")
    if ffmpeg:
        print(f"         ffmpeg: {ffmpeg}")
    check("whisper-cli", bool(captions.find_whisper_cli()), "build whisper.cpp, see scripts/install.sh")
    model = Path(cfg.get("paths", "whisper_model", default="./models/ggml-medium.en.bin")).expanduser()
    check(f"whisper model ({model})", model.exists(), "see README#captions for the (free) download")
    ch = cfg.channel
    print(f"\nchannel: {ch if ch != 'your_channel_here' else 'NOT SET (edit config.toml)'}")
    print(f"config : {cfg.source or '(built-in defaults — copy config.example.toml to config.toml)'}")
    return 0 if ok else 1


def cmd_analyze(cfg, args) -> int:
    return _print_spikes(args.chat_log, cfg, show_virality=args.virality)


def cmd_chatlog(cfg, args) -> int:
    channel = args.channel or cfg.require_channel()
    out = Path(args.out)
    stop = threading.Event()
    logger = ChatLogger(channel, out)
    print(f"Logging #{channel} chat to {out} — Ctrl+C to stop. (Anonymous, read-only.)")
    try:
        logger.run(stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


def cmd_cut(cfg, args) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found (see: python -m clipper doctor)")
    channel = args.channel or cfg.require_channel()
    rec_start = args.rec_start or Path(args.recording).stat().st_mtime - Path(args.recording).stat().st_size / 1_000_000
    clips_dir = Path(cfg.get("paths", "clips_dir", default="./clips")).expanduser()
    finalize.finalize(cfg, Path(args.recording), Path(args.chat_log), rec_start, clips_dir, ffmpeg)
    return 0


def cmd_shorts(cfg, args) -> int:
    from . import shorts as _shorts

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found (see: python -m clipper doctor)")
    mode = args.mode or cfg.get("shorts", "mode", default="blur")
    out = _shorts.to_vertical(ffmpeg, args.clip, args.out, mode)
    print(f"vertical Short written: {out}")
    return 0


def cmd_caption(cfg, args) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found (see: python -m clipper doctor)")
    model = cfg.get("paths", "whisper_model", default="./models/ggml-medium.en.bin")
    result = captions.caption_clip(ffmpeg, args.clip, model, language=cfg.get("captions", "language", default="en"),
                                   burn_in=not args.no_burn)
    print(json.dumps(result, indent=2))
    return 0 if not result.get("skipped") else 1


def cmd_demo(cfg, args) -> int:
    from .demo import run_demo

    return run_demo(cfg, keep=args.keep)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipper", description="Free, local Twitch Clip Watcher")
    p.add_argument("--config", help="path to config.toml (default: ./config.toml or ~/.config/clipwatch/config.toml)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check dependencies and config").set_defaults(func=lambda c, a: cmd_doctor(c))
    sp = sub.add_parser("watch", help="wait for live, record, auto-clip, rank and caption")
    sp.add_argument("--url", help="YouTube live stream URL (overrides source.platform)")
    sp.add_argument("--name", help="label for filenames/credits on YouTube (default: youtube_live)")
    sp.set_defaults(func=lambda c, a: watch.cmd_watch(c, a))

    sp = sub.add_parser("chatlog", help="log chat only")
    sp.add_argument("--channel", help="override configured channel")
    sp.add_argument("--out", default="chat.log")
    sp.set_defaults(func=cmd_chatlog)

    sp = sub.add_parser("analyze", help="print spikes in a chat.log")
    sp.add_argument("chat_log")
    sp.add_argument("--virality", action="store_true", help="also print the virality ranking/genre tags per window")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("cut", help="cut clips from a finished recording + chat.log")
    sp.add_argument("recording", help="stream.ts from a previous session")
    sp.add_argument("chat_log")
    sp.add_argument("--channel")
    sp.add_argument("--rec-start", type=float, default=None,
                    help="unix time the recording started (default: estimated from file mtime/size)")
    sp.set_defaults(func=cmd_cut)

    sp = sub.add_parser("shorts", help="render a vertical 9:16 Shorts MP4 from a clip")
    sp.add_argument("clip")
    sp.add_argument("--mode", choices=["blur", "crop"], default=None,
                    help="blur = blurred fill (default), crop = full-bleed center crop")
    sp.add_argument("--out", help="output path (default: <clip>_shorts.mp4)")
    sp.set_defaults(func=cmd_shorts)

    sp = sub.add_parser("caption", help="whisper.cpp captions for one clip")
    sp.add_argument("clip")
    sp.add_argument("--no-burn", action="store_true", help="produce the .srt only, don't burn it in")
    sp.set_defaults(func=cmd_caption)

    sp = sub.add_parser("demo", help="end-to-end proof on synthetic data")
    sp.add_argument("--keep", action="store_true", help="keep demo artifacts in ./demo-out")
    sp.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load(args.config)
    return args.func(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
