"""YouTube Live chat logger — same TSV output as the Twitch logger.

Uses pytchat (free, no API key, no account) to read a YouTube live chat
read-only and writes lines in the exact same format as irc.py:

    <unix_ms>\t<iso8601>\t<user>\t<message>

So every downstream tool (spike detection, cutting, ranking, captions)
works unchanged for YouTube live streams. YouTube chat only exists while
the stream is live — same constraint as the Twitch model.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .irc import clean_field, format_log_line

_VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/live/|/shorts/|/embed/)([A-Za-z0-9_-]{11})"
)
_RAW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url_or_id: str) -> str:
    """Accepts watch URLs, youtu.be links, /live/ links, or a raw 11-char id."""
    url_or_id = (url_or_id or "").strip()
    if _RAW_ID_RE.match(url_or_id):
        return url_or_id
    match = _VIDEO_ID_RE.search(url_or_id)
    if not match:
        raise ValueError(
            f"could not extract a YouTube video id from: {url_or_id!r} "
            "(expected something like https://www.youtube.com/watch?v=VIDEO_ID)"
        )
    return match.group(1)


def chat_item_to_line(item) -> str | None:
    """Convert a pytchat chat item to our TSV line. Pure — unit-testable offline."""
    ts_ms = getattr(item, "timestamp", None)
    if not ts_ms:
        ts_ms = int(time.time() * 1000)
    author = getattr(item, "author", None)
    user = getattr(author, "name", None) if author else "viewer"
    message = getattr(item, "message", "") or ""
    message = message.strip()
    if not message:
        return None  # stickers / membership pings without text
    return format_log_line(int(ts_ms), user or "viewer", clean_field(message))


class YouTubeChatLogger:
    """Reconnecting YouTube live-chat reader. Stop it with a threading.Event."""

    def __init__(self, url_or_id: str, log_path: str | Path):
        self.video_id = extract_video_id(url_or_id)
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def run(self, stop_event) -> None:
        try:
            import pytchat  # noqa: WPS433 — lazy import, friendly error below
        except ImportError:
            print("[yt-chat] pytchat is not installed. Run: pip install pytchat")
            return

        while not stop_event.is_set():
            try:
                chat = pytchat.create(video_id=self.video_id, interruptable=False)
            except Exception as exc:  # invalid id, not live, network down
                print(f"[yt-chat] could not open chat for {self.video_id}: {exc}")
                return

            try:
                with open(self.log_path, "a", encoding="utf-8") as log:
                    while chat.is_alive() and not stop_event.is_set():
                        try:
                            items = chat.get().sync_items()
                        except Exception:
                            time.sleep(2)
                            continue
                        for item in items:
                            line = chat_item_to_line(item)
                            if line:
                                log.write(line)
                                log.flush()
            finally:
                try:
                    chat.terminate()
                except Exception:
                    pass
            if not stop_event.is_set():
                time.sleep(5)  # brief pause before reconnecting to chat
