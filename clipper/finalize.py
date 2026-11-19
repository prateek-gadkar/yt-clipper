"""Turn a finished (recording, chat.log) pair into ranked clips + a credit manifest."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import captions, cut, virality
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
    return {"messages": msgs, "message_count": len(msgs), "spikes": spikes, "windows": windows}


def finalize(cfg, stream_ts: Path, chat_log: Path, rec_start_unix: float, clips_dir: Path,
             ffmpeg: str, source_url: str | None = None, credit: str | None = None, label: str | None = None) -> dict:
    channel = label or cfg.channel
    result = analyze(str(chat_log), cfg)
    vir_cfg = cfg.section("virality")
    summary = {
        "messages": result["message_count"],
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
    clips = cut.cut_clips(ffmpeg, stream_ts, rec_start_unix, result["windows"], clips_dir,
                          channel, source_url=source_url, credit=credit)

    if vir_cfg.get("enabled", True):
        bucket = int(cfg.section("spike").get("bucket_seconds", 10))
        clips = virality.score_clips(result["messages"], clips, bucket_seconds=bucket)
        virality.write_ranked(clips, Path(clips_dir) / "ranked.json")
        virality.print_ranked(clips)

    # captioning is the expensive step — cap it if the user asked for it
    max_clips = int(vir_cfg.get("max_clips", 0) or 0)
    to_caption = clips
    if max_clips > 0 and len(clips) > max_clips:
        to_caption = [c for c in clips if c["virality"]["recommended"]][:max_clips]
        skipped = [c for c in clips if c not in to_caption]
        for c in skipped:
            c["captions"] = {"skipped": f"not in top-{max_clips} recommended selection (virality.max_clips)"}
        print(f"\nCaptioning top {len(to_caption)} recommended clip(s); "
              f"{len(skipped)} uncaptioned (set virality.max_clips = 0 to caption everything).")

    cap_cfg = cfg.section("captions")
    if cap_cfg.get("enabled", True):
        model = cfg.get("paths", "whisper_model", default="./models/ggml-medium.en.bin")
        for clip in to_caption:
            print(f"Captioning {clip['clip']} ...")
            try:
                clip["captions"] = captions.caption_clip(
                    ffmpeg,
                    clip["clip"],
                    model,
                    language=cap_cfg.get("language", "en"),
                    burn_in=bool(cap_cfg.get("burn_in", True)),
                )
            except Exception as exc:  # captions are best-effort — never kill the run
                clip["captions"] = {"skipped": f"unexpected caption error: {exc}"}
            if clip["captions"].get("skipped"):
                print(f"  captions skipped: {clip['captions']['skipped']}")

    shorts_cfg = cfg.section("shorts")
    if shorts_cfg.get("enabled", False):
        from . import shorts as _shorts

        mode = shorts_cfg.get("mode", "blur")
        for clip in clips:
            captioned = (clip.get("captions") or {}).get("captioned")
            src = captioned or clip["clip"]  # Shorts keep the burned-in subs when available
            out = Path(clips_dir) / (Path(clip["clip"]).stem + "_shorts.mp4")
            try:
                print(f"Shorts render ({mode}) {out.name} ...")
                _shorts.to_vertical(ffmpeg, src, out, mode)
                clip["shorts"] = str(out)
            except Exception as exc:
                print(f"  shorts render failed: {exc}")
                clip["shorts"] = None

        if vir_cfg.get("enabled", True):
            # rewrite so ranked.json carries the shorts paths too
            virality.write_ranked(clips, Path(clips_dir) / "ranked.json")

    cut.append_manifest(clips, Path(clips_dir) / "manifest.jsonl", channel)

    for clip in clips:
        summary["clips"].append(clip)
    print(f"Manifest: {Path(clips_dir) / 'manifest.jsonl'}")
    if vir_cfg.get("enabled", True):
        print(f"Ranked : {Path(clips_dir) / 'ranked.json'}  (post in rank order; ★ = recommended)")
    return summary
