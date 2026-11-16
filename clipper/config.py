"""Configuration loading for the Clip Watcher.

Precedence (highest wins):
  1. explicit path passed to load()
  2. ./config.toml
  3. ~/.config/clipwatch/config.toml
  4. built-in defaults below
"""

from __future__ import annotations

import copy
import os
import sys
import tomllib
from pathlib import Path

DEFAULTS = {
    "twitch": {
        # The channel to watch, without the leading '#'.
        "channel": "your_channel_here",
        "quality": "best",
        # Seconds streamlink waits between "you're not live yet" retries.
        "retry_streams": 30,
    },
    "paths": {
        # Raw recordings + chat.log live here: work_dir/<channel>/<session>/
        "work_dir": "./work",
        # Finished clips land here.
        "clips_dir": "./clips",
        # whisper.cpp ggml model used for captions.
        "whisper_model": "./models/ggml-medium.en.bin",
    },
    "spike": {
        "bucket_seconds": 10,          # the post's unit: messages per 10 seconds
        "window_seconds": 300,         # "the last 5 minutes" trailing average
        "multiplier": 3.0,             # spike = 3x the trailing average
        "min_messages": 6,             # never call it a spike on near-silence
        "merge_gap_seconds": 30,       # glue spiking buckets <=30s apart into one moment
        "pre_pad_seconds": 8.0,        # chat reacts AFTER the moment: start the cut before the spike
        "post_pad_seconds": 10.0,      # let the reaction tail play out
        "max_clip_seconds": 120.0,     # hard cap per clip
        "min_clip_seconds": 12.0,      # ignore insubstantial cuts
    },
    "source": {
        # "twitch" or "youtube" (or pass --url on the command line for YouTube)
        "platform": "twitch",
    },
    "youtube": {
        # the YouTube live stream to watch, e.g. https://www.youtube.com/watch?v=VIDEO_ID
        "url": "",
        "name": "youtube_live",        # label used in filenames and credits
    },
    "virality": {
        "enabled": True,               # rank cut clips 0-100, tag genres, write clips/ranked.json
        "max_clips": 0,                # 0 = caption everything; N = caption only the N recommended clips
    },
    "shorts": {
        "enabled": True,               # also render *_shorts.mp4 vertical 9:16 for every clip
        "mode": "blur",                # "blur" = blurred-fill background; "crop" = center 9:16 crop
    },
    "captions": {
        "enabled": True,               # whisper.cpp is free and local
        "burn_in": True,               # bake subtitles into a *.captioned.mp4
        "language": "en",
    },
}

_SEARCH = [
    Path.cwd() / "config.toml",
    Path.home() / ".config" / "clipwatch" / "config.toml",
]


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, data: dict, source: Path | None):
        self.data = data
        self.source = source

    def get(self, *keys, default=None):
        node = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def section(self, name: str) -> dict:
        return dict(self.data.get(name, {}))

    @property
    def channel(self) -> str:
        return str(self.get("twitch", "channel", default="")).lstrip("#").strip().lower()

    def require_channel(self) -> str:
        ch = self.channel
        if not ch or ch == "your_channel_here":
            sys.exit(
                "No channel configured.\n"
                "  1. cp config.example.toml config.toml\n"
                "  2. edit config.toml and set twitch.channel = \"some_channel\"\n"
                "     (the name in twitch.tv/<name>, no leading '#')\n"
            )
        return ch


def load(path: str | os.PathLike | None = None) -> Config:
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            sys.exit(f"config not found: {p}")
        return Config(_merge(DEFAULTS, tomllib.loads(p.read_text())), p)

    for candidate in _SEARCH:
        if candidate.exists():
            return Config(_merge(DEFAULTS, tomllib.loads(candidate.read_text())), candidate)
    return Config(copy.deepcopy(DEFAULTS), None)
