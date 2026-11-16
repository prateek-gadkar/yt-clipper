"""Shorts conversion — landscape stream clips -> vertical 9:16 MP4s.

Two modes:
  blur (default) — the 16:9 frame fills 1080x1920 with a blurred copy of
                   itself behind it (standard Shorts look, nothing gets cropped)
  crop           — center-crop 9:16 (full-bleed, but the sides of the screen —
                   usually HUD/minimap — are lost; best for close-up action)
"""

from __future__ import annotations

from pathlib import Path

_CROP_FILTER = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos,setsar=1"

_BLUR_FILTER = (
    "[0:v]split=2[bg][fg];"
    "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
    "boxblur=luma_radius=25:luma_power=2,crop=1080:1920[bg2];"
    "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg2];"
    "[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1"
)


def build_command(ffmpeg: str, src: str | Path, out: str | Path, mode: str = "blur") -> list[str]:
    src, out = str(src), str(out)
    base = [ffmpeg, "-y", "-i", src]
    if mode == "crop":
        return base + ["-vf", _CROP_FILTER, "-c:a", "copy",
                       "-preset", "veryfast", "-crf", "23", out]
    if mode == "blur":
        return base + ["-filter_complex", _BLUR_FILTER, "-map", "0:a?", "-c:a", "copy",
                       "-preset", "veryfast", "-crf", "23", out]
    raise ValueError(f"unknown shorts mode: {mode!r} (expected 'blur' or 'crop')")


def to_vertical(ffmpeg: str, src: str | Path, out: str | Path | None = None, mode: str = "blur") -> Path:
    import subprocess

    src = Path(src)
    if out is None:
        out = src.with_name(src.stem + "_shorts.mp4")
    out = Path(out)
    subprocess.run(build_command(ffmpeg, src, out, mode), check=True, capture_output=True)
    return out
