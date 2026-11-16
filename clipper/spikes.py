"""Spike detection — the free replacement for the post's
"ask Claude Code to read chat.log" step.

Algorithm (exactly the post's recipe, made deterministic):
  * bucket chat into fixed-width windows (default 10 seconds)
  * for every bucket, compute the trailing average over the previous
    N seconds (default 300 = "the last 5 minutes")
  * flag the bucket when it is >= `multiplier` x that trailing average
    and at least `min_messages` strong (so dead channels don't false-positive)
  * merge flagged buckets separated by short gaps into single "moments"
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Spike:
    start: float        # unix seconds — first spiking bucket opens
    end: float          # unix seconds — last spiking bucket closes
    peak_time: float    # unix seconds — midpoint of the loudest bucket
    peak_count: int     # messages in the loudest bucket
    buckets: int        # how many buckets the moment spans


def read_chat_log(path: str):
    """Read a TSV chat log (ms, iso, user, message) -> sorted [(unix_ts, user, text)]."""
    msgs = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t", 3)
            if len(parts) < 4:
                continue
            try:
                ts_ms = float(parts[0])
            except ValueError:
                continue
            msgs.append((ts_ms / 1000.0, parts[2], parts[3]))
    msgs.sort(key=lambda m: m[0])
    return msgs


def find_spikes(
    times,
    bucket_seconds: int = 10,
    window_seconds: int = 300,
    multiplier: float = 3.0,
    min_messages: int = 6,
    merge_gap_seconds: int = 30,
) -> list[Spike]:
    times = list(times)
    if not times:
        return []

    t0 = math.floor(min(times))
    bucket_seconds = max(1, int(bucket_seconds))
    nb = int((max(times) - t0) // bucket_seconds) + 1
    counts = [0] * nb
    for t in times:
        i = int((t - t0) // bucket_seconds)
        if 0 <= i < nb:
            counts[i] += 1

    win = max(1, int(window_seconds) // bucket_seconds)
    gap_buckets = max(0, round(merge_gap_seconds / bucket_seconds))

    flags = [False] * nb
    for i in range(nb):
        lo = max(0, i - win)
        if lo == i:
            # no trailing history yet — "3x the last 5 minutes" is undefined,
            # so don't cry wolf in the first buckets of a log
            continue
        trailing = counts[lo:i]
        # a burst inflates the trailing average — measure "normal" against
        # the non-spiking buckets only, so sustained hype stays detected
        normal = [counts[j] for j in range(lo, i) if not flags[j]]
        avg = sum(normal) / len(normal) if normal else sum(trailing) / len(trailing)
        c = counts[i]
        if c >= min_messages and c >= multiplier * avg and c > avg:
            flags[i] = True

    spikes: list[Spike] = []
    i = 0
    while i < nb:
        if not flags[i]:
            i += 1
            continue
        last = i
        while True:
            k = last + 1
            while k < nb and not flags[k]:
                k += 1
            if k < nb and (k - last - 1) <= gap_buckets:
                last = k
            else:
                break
        peak_idx = max(range(i, last + 1), key=lambda x: counts[x])
        spikes.append(
            Spike(
                start=t0 + i * bucket_seconds,
                end=t0 + (last + 1) * bucket_seconds,
                peak_time=t0 + (peak_idx + 0.5) * bucket_seconds,
                peak_count=counts[peak_idx],
                buckets=last - i + 1,
            )
        )
        i = last + 1
    return spikes


def clip_windows(
    spikes,
    pre_pad: float = 8.0,
    post_pad: float = 10.0,
    max_clip: float = 120.0,
    min_clip: float = 12.0,
):
    """Turn spikes into (start_unix, end_unix) cut windows.

    Chat reacts a few seconds AFTER the moment, so we start the cut
    `pre_pad` seconds before the spike and let it run `post_pad` past
    the last spiking bucket. Overlapping windows are merged.
    """
    windows = []
    for s in spikes:
        start = s.start - pre_pad
        end = s.end + post_pad
        if end - start > max_clip:
            end = start + max_clip
        windows.append([start, end])

    windows.sort(key=lambda w: w[0])
    merged: list[list[float]] = []
    for w in windows:
        if merged and w[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], w[1])
        else:
            merged.append(list(w))
    return [(a, b) for a, b in merged if b - a >= min_clip]
