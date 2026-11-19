"""Local captions via whisper.cpp (free, offline) + optional burn-in.

Pipeline:
  1. ffmpeg extracts a 16 kHz mono WAV from the clip
  2. whisper-cli transcribes it to .srt
  3. if burn_in: ffmpeg renders *.captioned.mp4 with the subtitles baked in

Everything runs on your machine. No API keys, no accounts, no cost.

Failure policy: captioning is best-effort. Any failure returns a dict with a
human-readable reason in `skipped` (or raises CaptionError for misuse) — it
must never crash the finalize pipeline and take the clips down with it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _tail(raw: bytes | str | None, limit: int = 800) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return raw.strip()[-limit:]


def find_whisper_cli() -> str | None:
    import sys
    from pathlib import Path as _Path

    for name in ("whisper-cli", "whisper-cpp"):
        hit = shutil.which(name)
        if hit:
            return hit
        candidates = [
            _Path(sys.executable).parent / name,          # same venv/bin
            _Path.home() / ".local" / "bin" / name,        # install.sh symlinks here
        ]
        for cand in candidates:
            if cand.exists():
                return str(cand)
    return None


def _subs_filter_escape(path: str) -> str:
    # ffmpeg filtergraph escaping for the subtitles filter filename
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def caption_clip(
    ffmpeg: str,
    clip: str | Path,
    model: str | Path,
    language: str = "en",
    burn_in: bool = True,
    whisper_cli: str | None = None,
) -> dict:
    clip = Path(clip)
    model = Path(model)
    result = {"srt": None, "captioned": None, "skipped": None}

    cli = whisper_cli or find_whisper_cli()
    if cli is None:
        result["skipped"] = "whisper-cli not found (build whisper.cpp — see scripts/install.sh)"
        return result
    if not model.exists():
        result["skipped"] = f"whisper model not found at {model} (see README#captions)"
        return result

    wav = clip.with_suffix(".wav")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(clip), "-ar", "16000", "-ac", "1", str(wav)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        result["skipped"] = f"ffmpeg WAV extraction failed (exit {exc.returncode}): {_tail(exc.stderr)}"
        return result

    out_base = clip.with_suffix("")  # whisper appends .srt
    try:
        subprocess.run(
            [cli, "-m", str(model), "-f", str(wav), "-osrt", "-of", str(out_base), "-l", language],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        result["skipped"] = (
            f"whisper-cli exited {exc.returncode}: "
            f"{_tail(exc.stderr) or _tail(exc.stdout) or 'no output — the model file is the prime suspect; check it with ls -lh'}"
        )
        result["wav"] = str(wav)  # keep it around so the run can be reproduced
        return result

    srt = clip.with_suffix(".srt")
    wav.unlink(missing_ok=True)
    result["srt"] = str(srt) if srt.exists() else None

    if burn_in and result["srt"]:
        out = clip.with_name(clip.stem + ".captioned.mp4")
        try:
            subprocess.run(
                [
                    ffmpeg, "-y", "-i", str(clip),
                    "-vf", f"subtitles={_subs_filter_escape(str(srt.resolve()))}",
                    "-c:a", "copy", str(out),
                ],
                check=True, capture_output=True,
            )
            result["captioned"] = str(out)
        except subprocess.CalledProcessError as exc:
            result["skipped"] = f"subtitle burn-in failed (exit {exc.returncode}): {_tail(exc.stderr)} (the .srt was still produced)"
    return result
