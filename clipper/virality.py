"""Virality ranking — free, local heuristic.

Scores every cut clip 0-100 from chat energy alone (no API, no LLM, no
network). The ranking answers "which of these clips should I post first?" —
it cannot and does not guarantee views. What it does capture is what actually
correlates with clip performance: chat velocity, how extreme the spike was
relative to baseline, emotional keyword density, and a Shorts-friendly length.

Genre tagging ("best/worst/surprising/disappointing/funny/fail") comes from
lexicons matched against the chat inside each clip window — so your upload
queue always covers every genre instead of five copies of the same hype play.

Components (weights sum to 100):
  peak rate        25  — loudest 10s bucket in the window, saturates at 60 msgs
  prominence       25  — burst chat rate vs the stream's overall rate, saturates ~6x
  keyword intensity 20 — fraction of burst messages matching any genre lexicon
  duration fit     15  — gaussian sweet spot centered on 45s (Shorts territory)
  volume           15  — total messages in the window, log scale (saturates ~1000)
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

GENRE_LEXICONS: dict[str, list[str]] = {
    "hype": [
        "clip it", "clip that", "clip!", "insane", "clutch", "gg", "goat",
        "cracked", "pog", "pogchamp", "beautiful", "highlight", "godlike",
        "let's go", "lets go", "w win", "amazing play", "best play", "monka",
    ],
    "worst": [
        "worst", "trash", "throw", "threw", "choke", "choked", "awful",
        "garbage", "disappointing", "unlucky", "terrible", "blunder",
        "threw it", "attrocious", "yikes", "pain", "oof",
    ],
    "surprise": [
        "wtf", "no way", "how did", "how?!", "what?!", "wait what", "omg",
        "plot twist", "unbelievable", "wth", "??", "!!!", "unexpected",
        "bro WHAT", "i can't", "shut up",
    ],
    "fail": [
        "fail", "bug", "glitch", "error", "broken", "impossible", "desync",
        "softlock", "clip through", "hack",
    ],
    "funny": [
        "lol", "lmao", "haha", "kek", "xd", "dead", "im crying", "i'm crying",
        "rofl", "hilarious", "comedy",
    ],
}

# short standalone tokens worth a word-boundary match (e.g. "W", "L", "gg")
_WORD_TERMS = {
    "hype": ["w", "gg", "pog"],
    "worst": ["l"],
}

GENRE_LABELS = {
    "hype": "BEST (hype play)",
    "worst": "WORST (throw/blunder)",
    "surprise": "SURPRISING (shock/plot twist)",
    "fail": "FAIL (glitch/bug)",
    "funny": "FUNNY",
}

_LEXICON_RES = {
    genre: [re.compile(r"\b" + re.escape(t) + r"\b") if re.match(r"^[\w ]+$", t) else re.compile(re.escape(t))
            for t in terms]
    for genre, terms in GENRE_LEXICONS.items()
}
_WORD_RES = {
    genre: [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in terms]
    for genre, terms in _WORD_TERMS.items()
}


def genre_hits(text: str) -> set[str]:
    hits = set()
    lowered = text.lower()
    for genre, patterns in _LEXICON_RES.items():
        if any(p.search(lowered) for p in patterns):
            hits.add(genre)
    for genre, patterns in _WORD_RES.items():
        if any(p.search(lowered) for p in patterns):
            hits.add(genre)
    return hits


@dataclass
class WindowFeatures:
    duration: float
    burst_messages: int
    peak_bucket: int
    baseline_rate: float
    burst_rate: float
    prominence: float
    keyword_intensity: float
    genre_hits: dict[str, int]


def extract_features(messages, start: float, end: float, bucket_seconds: int = 10) -> WindowFeatures:
    if end <= start:
        end = start + 1.0
    burst = [m for m in messages if start <= m[0] < end]

    t_lo = messages[0][0] if messages else start
    t_hi = messages[-1][0] if messages else end
    span = max(t_hi - t_lo, 1e-6)
    baseline_rate = len(messages) / span
    burst_rate = len(burst) / (end - start)
    prominence = min(burst_rate / baseline_rate, 8.0) if baseline_rate > 0 else 8.0

    nb = max(1, int((end - start) // bucket_seconds) + 1)
    counts = [0] * nb
    for m in burst:
        i = int((m[0] - start) // bucket_seconds)
        counts[min(i, nb - 1)] += 1
    peak_bucket = max(counts) if counts else 0

    hits: dict[str, int] = {}
    keywordish = 0
    for m in burst:
        found = genre_hits(m[2])
        if found:
            keywordish += 1
            for g in found:
                hits[g] = hits.get(g, 0) + 1

    return WindowFeatures(
        duration=end - start,
        burst_messages=len(burst),
        peak_bucket=peak_bucket,
        baseline_rate=baseline_rate,
        burst_rate=burst_rate,
        prominence=prominence,
        keyword_intensity=(keywordish / len(burst)) if burst else 0.0,
        genre_hits=hits,
    )


def score_features(f: WindowFeatures) -> tuple[int, dict[str, float]]:
    c1 = min(1.0, f.peak_bucket / 60.0) * 25
    c2 = min(1.0, f.prominence / 6.0) * 25
    c3 = min(1.0, f.keyword_intensity / 0.6) * 20
    c4 = math.exp(-((f.duration - 45.0) ** 2) / (2 * 30.0**2)) * 15
    c5 = min(1.0, math.log10(f.burst_messages + 1) / 3.0) * 15
    components = {
        "peak_rate": round(c1, 1),
        "prominence": round(c2, 1),
        "keyword_intensity": round(c3, 1),
        "duration_fit": round(c4, 1),
        "volume": round(c5, 1),
    }
    return round(sum(components.values())), components


def _tag_genres(hits: dict[str, int], burst_messages: int) -> list[str]:
    if not hits:
        return ["general"]
    floor = max(2, int(0.15 * max(burst_messages, 1)))
    tagged = [g for g, n in hits.items() if n >= floor]
    if not tagged:  # keep the single loudest genre even below the floor
        tagged = [max(hits, key=hits.get)]
    return sorted(tagged, key=lambda g: hits[g], reverse=True)


def score_clips(messages, clip_entries, bucket_seconds: int = 10) -> list[dict]:
    """Score + rank cut clips. `clip_entries` items need clip/start_iso/duration_seconds.

    Adds virality: {score, rank, genres, genre_labels, recommended, components}.
    Returns the same list, sorted by score descending, ranks assigned.
    """
    try:
        from datetime import datetime
    except ImportError:  # pragma: no cover
        datetime = None

    scored = []
    for entry in clip_entries:
        start = datetime.fromisoformat(entry["start_iso"]).timestamp()
        end = start + float(entry.get("duration_seconds", 45))
        feats = extract_features(messages, start, end, bucket_seconds)
        score, components = score_features(feats)
        genres = _tag_genres(feats.genre_hits, feats.burst_messages)
        scored.append(
            {
                **entry,
                "virality": {
                    "score": score,
                    "genres": genres,
                    "genre_labels": [GENRE_LABELS.get(g, g) for g in genres],
                    "components": components,
                    "burst_messages": feats.burst_messages,
                    "peak_bucket_msgs": feats.peak_bucket,
                    "prominence": round(feats.prominence, 2),
                    "recommended": False,  # set by choose_recommended()
                },
            }
        )

    scored.sort(key=lambda e: e["virality"]["score"], reverse=True)
    for i, entry in enumerate(scored, start=1):
        entry["virality"]["rank"] = i
    choose_recommended(scored)
    return scored


def choose_recommended(scored: list[dict]) -> list[dict]:
    """Mark the clips worth posting: overall top 3 + the best clip of each genre.

    Guarantees your queue covers BEST / WORST / SURPRISING / FUNNY / FAIL —
    not five copies of the same hype play.
    """
    if not scored:
        return scored
    recommended: set[int] = set()
    for i, entry in enumerate(scored[:3]):  # overall top 3
        recommended.add(id(entry))
    seen_genres: set[str] = set()
    for entry in scored:  # top clip per genre
        for g in entry["virality"]["genres"]:
            if g not in seen_genres:
                recommended.add(id(entry))
                seen_genres.add(g)
    for entry in scored:
        entry["virality"]["recommended"] = id(entry) in recommended
    return scored


def write_ranked(scored: list[dict], path: str | Path) -> None:
    payload = [
        {
            "rank": e["virality"]["rank"],
            "score": e["virality"]["score"],
            "recommended": e["virality"]["recommended"],
            "genres": e["virality"]["genres"],
            "clip": e["clip"],
            "shorts": e.get("shorts"),
            "start_iso": e.get("start_iso"),
            "duration_seconds": e.get("duration_seconds"),
            "credit": e.get("credit"),
            "components": e["virality"]["components"],
        }
        for e in scored
    ]
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def print_ranked(scored: list[dict]) -> None:
    if not scored:
        return
    print("\nVIRALITY RANKING (post in this order — heuristic, not a guarantee)")
    print(f"  {'rk':>2}  {'score':>5}  {'genres':<34}  {'dur':>4}  clip")
    for e in scored:
        v = e["virality"]
        genres = ",".join(v["genres"])[:34]
        flag = "★" if v["recommended"] else " "
        print(f"  {v['rank']:>2}  {v['score']:>5}  {genres:<34}  {e.get('duration_seconds', 0):>3.0f}s  {flag} {Path(e['clip']).name}")
    print("  ★ = recommended (overall top 3 + best clip per genre)")
