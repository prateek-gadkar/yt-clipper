"""Cut highlight clips out of the raw recording with ffmpeg.

Cuts use stream-copy (-c copy) so there is no re-encode and no generational
loss; -ss before -i seeks to the nearest keyframe at or before the target.
Twitch keyframes land every couple of seconds and we pad cuts by several
seconds, so this is not noticeable in practice. Caption burn-in re-encodes
only the captioned copy.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path


def cut_clips(
    ffmpeg: str,
    src: str | Path,
    rec_start_unix: float,
    windows,
    clips_dir: str | Path,
    channel: str,
    source_url: str | None = None,
    credit: str | None = None,
):
    clips_dir = Path(clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for idx, (a, b) in enumerate(windows, start=1):
        offset = max(0.0, a - rec_start_unix)
        duration = b - a
        stamp = datetime.fromtimestamp(a).strftime("%Y%m%d_%H%M%S")
        out = clips_dir / f"{channel}_{stamp}_clip{idx}.mp4"
        url = source_url or f"https://www.twitch.tv/{channel}"
        if credit is None:
            credit = f"Clip from {channel}'s live stream - {url} - credit & link the creator"
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{offset:.2f}",
            "-t", f"{duration:.2f}",
            "-i", str(src),
            "-c", "copy",
            "-metadata", f"comment={credit}",
            "-movflags", "+faststart",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        results.append(
            {
                "clip": str(out),
                "offset_seconds": round(offset, 2),
                "duration_seconds": round(duration, 2),
                "start_iso": datetime.fromtimestamp(a).isoformat(timespec="seconds"),
                "source_url": url,
                "credit": credit,
            }
        )
    return results


def append_manifest(clips: list[dict], manifest_path: str | Path, channel: str) -> None:
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "a", encoding="utf-8") as fh:
        for clip in clips:
            entry = dict(clip)
            entry["channel"] = channel
            entry["tool"] = "yt-clipper clip-watcher (free, local)"
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
