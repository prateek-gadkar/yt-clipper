"""Turn a finished (recording, chat.log) pair into captioned clips + a credit manifest."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import captions, cut
from .spikes import clip_windows, find_spikes, read_chat_log


def analyze(chat_log: str, cfg) -> dict:
    msgs = read_chat_log(chat_log)
    times = [m[0] for m in msgs]
    sp_cfg = cfg.section("spike")
    spikes = find_spikes(
        times,
        bucket_seconds=sp_cfg.get("bucket_seconds", 10),
        window_seconds=sp_cfg.get("window_seconds", 300),
        multiplier=float(sp_cfg.get("multiplier", 3.0)),
        min_messages=int(sp_cfg.get("min_messages", 6)),
        merge_gap_seconds=int(sp_cfg.get("merge_gap_seconds", 30)),
    )
    windows = clip_windows(
        spikes,
        pre_pad=float(sp_cfg.get("pre_pad_seconds", 8.0)),
        post_pad=float(sp_cfg.get("post_pad_seconds", 10.0)),
        max_clip=float(sp_cfg.get("max_clip_seconds", 120.0)),
        min_clip=float(sp_cfg.get("min_clip_seconds", 12.0)),
    )
    return {"messages": len(msgs), "spikes": spikes, "windows": windows}


def finalize(cfg, stream_ts: Path, chat_log: Path, rec_start_unix: float, clips_dir: Path, ffmpeg: str) -> dict:
    channel = cfg.channel
    result = analyze(str(chat_log), cfg)
    summary = {
        "messages": result["messages"],
        "spikes": [
            {
                "start_iso": datetime.fromtimestamp(s.start).isoformat(timespec="seconds"),
                "end_iso": datetime.fromtimestamp(s.end).isoformat(timespec="seconds"),
                "peak_count": s.peak_count,
                "buckets": s.buckets,
            }
            for s in result["spikes"]
        ],
        "clips": [],
    }

    if not result["windows"]:
        print("No chat spikes found — no clips cut.")
        return summary

    print(f"Found {len(result['spikes'])} spike(s) -> cutting {len(result['windows'])} clip(s)...")
    clips = cut.cut_clips(ffmpeg, stream_ts, rec_start_unix, result["windows"], clips_dir, channel)

    cap_cfg = cfg.section("captions")
    if cap_cfg.get("enabled", True):
        model = cfg.get("paths", "whisper_model", default="./models/ggml-medium.en.bin")
        for clip in clips:
            print(f"Captioning {clip['clip']} ...")
            clip["captions"] = captions.caption_clip(
                ffmpeg,
                clip["clip"],
                model,
                language=cap_cfg.get("language", "en"),
                burn_in=bool(cap_cfg.get("burn_in", True)),
            )
            if clip["captions"].get("skipped"):
                print(f"  captions skipped: {clip['captions']['skipped']}")

    cut.append_manifest(clips, Path(clips_dir) / "manifest.jsonl", channel)
    for clip in clips:
        summary["clips"].append(clip)
        print(f"  ✓ {clip['clip']}  ({clip['duration_seconds']}s)")
    print(f"Manifest: {Path(clips_dir) / 'manifest.jsonl'}")
    return summary
