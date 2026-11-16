"""Anonymous, read-only Twitch chat logger.

IRC: irc.chat.twitch.tv:6667 — no account, no token.
NICK justinfan<random> is Twitch's well-known anonymous-read convention;
we only request the `tags` and `commands` capabilities so we get
tmi-sent-ts (server-side message timestamps) and RECONNECT notices.

Log format (one line per message, TSV, easy to parse):
    <unix_ms>\t<iso8601>\t<user>\t<message>
"""

from __future__ import annotations

import random
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6667


def parse_irc_line(line: str) -> dict:
    """Parse one raw IRC line into {tags, prefix, command, params}."""
    tags: dict[str, str] = {}
    rest = line.rstrip("\r\n")

    if rest.startswith("@"):
        head, _, rest = rest.partition(" ")
        for part in head[1:].split(";"):
            key, _, value = part.partition("=")
            tags[key] = value

    prefix = None
    if rest.startswith(":"):
        prefix, _, rest = rest[1:].partition(" ")

    command, _, rest = rest.partition(" ")
    params: list[str] = []
    rest = rest.strip()
    while rest:
        if rest.startswith(":"):
            params.append(rest[1:])
            rest = ""
        else:
            param, _, rest = rest.partition(" ")
            params.append(param)
            rest = rest.strip()
    return {"tags": tags, "prefix": prefix, "command": command.upper(), "params": params}


def clean_field(text: str) -> str:
    return " ".join(str(text).replace("\t", " ").replace("\n", " ").replace("\r", " ").split())


def format_log_line(ts_ms: int | float, user: str, message: str) -> str:
    ts_ms = int(ts_ms)
    iso = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{ts_ms}\t{iso}\t{clean_field(user)}\t{clean_field(message)}\n"


class ChatLogger:
    """Reconnecting anonymous chat reader. Stop it with a threading.Event."""

    def __init__(self, channel: str, log_path: str | Path, nick: str | None = None):
        self.channel = channel.lstrip("#").lower()
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.nick = nick or f"justinfan{random.randint(10000, 99999)}"

    @staticmethod
    def _send(sock: socket.socket, payload: str) -> None:
        sock.sendall(payload.encode("utf-8") + b"\r\n")

    def _session(self, stop_event, sock: socket.socket) -> None:
        sock.settimeout(60)
        self._send(sock, "CAP REQ :twitch.tv/tags twitch.tv/commands")
        self._send(sock, f"NICK {self.nick}")
        self._send(sock, f"USER {self.nick} 8 * :{self.nick}")

        joined = False
        buf = ""
        with open(self.log_path, "a", encoding="utf-8") as log:
            while not stop_event.is_set():
                try:
                    data = sock.recv(8192)
                except socket.timeout:
                    if joined:
                        try:
                            self._send(sock, "PING :keepalive")
                        except OSError:
                            return
                    continue
                if not data:
                    return  # server closed the connection -> outer loop reconnects

                buf += data.decode("utf-8", "replace")
                while "\r\n" in buf:
                    line, buf = buf.split("\r\n", 1)
                    if not line:
                        continue
                    try:
                        joined = self._handle(sock, line, log) or joined
                    except ConnectionError:
                        return

    def _handle(self, sock: socket.socket, line: str, log) -> bool:
        msg = parse_irc_line(line)
        cmd = msg["command"]

        if cmd == "PING":
            self._send(sock, f"PONG :{msg['params'][0] if msg['params'] else 'tmi.twitch.tv'}")
            return False
        if cmd == "001":  # RPL_WELCOME -> safe to join
            self._send(sock, f"JOIN #{self.channel}")
            return True
        if cmd == "RECONNECT":  # Twitch asked us to reconnect
            raise ConnectionError("server sent RECONNECT")
        if cmd != "PRIVMSG":
            return False

        tags = msg["tags"]
        user = (msg["prefix"] or "someone").split("!", 1)[0]
        if len(msg["params"]) < 2:
            return False
        text = msg["params"][1]
        ts_raw = tags.get("tmi-sent-ts")
        try:
            ts_ms = int(ts_raw) if ts_raw else int(time.time() * 1000)
        except ValueError:
            ts_ms = int(time.time() * 1000)

        log.write(format_log_line(ts_ms, user, text))
        log.flush()
        return False

    def run(self, stop_event) -> None:
        backoff = 2
        while not stop_event.is_set():
            try:
                with socket.create_connection((IRC_HOST, IRC_PORT), timeout=30) as sock:
                    backoff = 2
                    self._session(stop_event, sock)
            except (OSError, ConnectionError):
                pass
            if not stop_event.is_set():
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
