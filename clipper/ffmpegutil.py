"""Locate external binaries: PATH first, then the interpreter's own bin dir
(a venv's streamlink/whisper-cli sit next to python even when the venv isn't
'activated'), then imageio-ffmpeg's bundled ffmpeg."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def find_tool(name: str) -> str | None:
    override = os.environ.get(f"CLIPWATCH_{name.upper().replace('-', '_')}")
    if override and Path(override).isfile():
        return override
    hit = shutil.which(name)
    if hit:
        return hit
    cand = Path(sys.executable).parent / name
    return str(cand) if cand.exists() else None


def find_ffmpeg() -> str | None:
    override = os.environ.get("CLIPWATCH_FFMPEG")
    if override and os.path.isfile(override):
        return override
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
