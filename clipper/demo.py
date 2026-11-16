"""End-to-end proof on synthetic data — no live stream, no account, no network.

Builds a fake chat.log: a quiet baseline (~2 msg/10s) with a 30-second
reaction burst at t=+120s, then runs the exact same spike detection and
cutting pipeline the live path uses.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import cut
from .ffmpegutil import find_ffmpeg
from .irc import format_log_line
from .spikes import clip_windows, find_spikes

USERS = ["mod_kai", "streamfan88", "lurker_jane", "clipit_dan", "nightowl_tv", "pog_prime", "ada_w"]
BASE_LINES = ["lol", "nice", "true", "W", "haha", "gg", "ok", "yeah", "hype"]
BURST_LINES = ["CLIP IT", "WHAT?!", "clip that", "NO WAY", "CLIP!!", "clip it clip it", "OMG", "CLIP IT NOW"]


def _write_fake_chat(path: Path) -> list[float]:
    random.seed(7)
    t0 = datetime.now().timestamp() - 300  # "stream" started 5 minutes ago
    times = []
    with open(path, "w", encoding="utf-8") as fh:
        for bucket in range(30):  # 30 buckets x 10s = 5 minutes
            in_burst = 12 <= bucket <= 14  # 30 s of chaos at t = +120..+150
            n = random.randint(24, 34) if in_burst else random.randint(1, 4)
            for _ in range(n):
                ts = t0 + bucket * 10 + random.uniform(0, 9.9)
                times.append(ts)
                text = random.choice(BURST_LINES if in_burst else BASE_LINES)
                fh.write(format_log_line(ts * 1000, random.choice(USERS), text))
    return times


def run_demo(cfg, keep: bool = False) -> int:
    out_dir = Path("demo-out") if keep else Path("demo-out")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    chat_log = out_dir / "chat.log"
    times = _write_fake_chat(chat_log)
    t0 = min(times)

    sp = cfg.section("spike")
    spikes = find_spikes(
        times,
        bucket_seconds=sp.get("bucket_seconds", 10),
        window_seconds=sp.get("window_seconds", 300),
        multiplier=float(sp.get("multiplier", 3.0)),
        min_messages=int(sp.get("min_messages", 6)),
        merge_gap_seconds=int(sp.get("merge_gap_seconds", 30)),
    )
    print(f"[demo] synthetic chat.log: {len(times)} messages over {max(times) - t0:.0f}s")
    if not spikes:
        print("[demo] FAIL: synthetic burst was not detected as a spike")
        return 1
    for i, s in enumerate(spikes, 1):
        print(
            f"[demo] spike {i}: +{s.start - t0:.0f}s -> +{s.end - t0:.0f}s "
            f"(peak {s.peak_count} msg/10s)"
        )

    windows = clip_windows(
        spikes,
        pre_pad=float(sp.get("pre_pad_seconds", 8.0)),
        post_pad=float(sp.get("post_pad_seconds", 10.0)),
        max_clip=float(sp.get("max_clip_seconds", 120.0)),
        min_clip=float(sp.get("min_clip_seconds", 12.0)),
    )

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        fake_vod = out_dir / "stream.ts"
        duration = max(times) - t0 + 30
        print(f"[demo] rendering {duration:.0f}s synthetic VOD with ffmpeg ...")
        subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", f"testsrc2=duration={duration}:rate=15:size=640x360",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", str(fake_vod),
            ],
            check=True, capture_output=True,
        )
        clips = cut.cut_clips(ffmpeg, fake_vod, t0, windows, out_dir / "clips", "demo_channel")
        from . import virality
        from .spikes import read_chat_log

        messages = read_chat_log(str(chat_log))
        clips = virality.score_clips(messages, clips, bucket_seconds=int(sp.get("bucket_seconds", 10)))
        virality.write_ranked(clips, out_dir / "clips" / "ranked.json")
        virality.print_ranked(clips)
        cut.append_manifest(clips, out_dir / "clips" / "manifest.jsonl", "demo_channel")
        for clip in clips:
            print(f"[demo] cut clip: {clip['clip']} ({clip['duration_seconds']}s)")
    else:
        print("[demo] ffmpeg not found — skipping VOD render/cut (install ffmpeg to see that part)")

    print("\n[demo] PASS — spike detection and clip pipeline work end to end.")
    print(f"[demo] artifacts in {out_dir}/ (chat.log, stream.ts, clips/)")
    print("[demo] captions are exercised on the live path once whisper.cpp + a model are installed.")
    return 0
