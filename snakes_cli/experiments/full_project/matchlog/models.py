"""U1: Data models for the matchlog CLI.

Defines the core dataclasses used to represent matches, statistics,
and the overall match log. Zero dependencies beyond the Python standard library.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Match:
    """A single match record against an opponent.

    Attributes:
        opponent: Name or identifier of the opponent.
        result: Match outcome — one of "win", "loss", "draw", or "draw(win)".
        played_at: ISO 8601 datetime string when the match was played.
        notes: Optional free-form notes about the match.
    """

    opponent: str
    result: str  # "win" | "loss" | "draw" | "draw(win)"
    played_at: str  # ISO datetime string
    notes: str = ""


@dataclass
class Stats:
    """Aggregated statistics derived from a match log.

    Attributes:
        total: Total number of matches played.
        wins: Number of wins.
        losses: Number of losses.
        draws: Number of draws (including draw(win)).
        win_rate: Win percentage as a float between 0.0 and 100.0.
        current_streak: Length of the current streak. Positive for wins,
            negative for losses, 0 if no streak or last match was a draw.
        streak_type: "win", "loss", or "none" — type of the current streak.
        longest_win_streak: All-time longest consecutive win streak.
        longest_loss_streak: All-time longest consecutive loss streak.
        h2h: Per-opponent head-to-head stats, keyed by opponent name.
            Each value is a dict with keys "wins", "losses", "draws".
    """

    total: int
    wins: int
    losses: int
    draws: int
    win_rate: float  # 0.0 – 100.0
    current_streak: int  # positive = win streak, negative = loss streak, 0 = none
    streak_type: str  # "win" | "loss" | "none"
    longest_win_streak: int
    longest_loss_streak: int
    h2h: Dict[str, dict]  # {opponent: {"wins": int, "losses": int, "draws": int}}


@dataclass
class MatchLog:
    """A collection of matches forming a match log.

    Attributes:
        matches: List of Match instances in chronological order (oldest first).
    """

    matches: List[Match] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Quick smoketest — run this file directly to verify models instantiate cleanly.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    m = Match(
        opponent="Alice",
        result="win",
        played_at="2026-08-06T14:30:00",
        notes="Great game!",
    )
    print("Match:", m)

    stats = Stats(
        total=1,
        wins=1,
        losses=0,
        draws=0,
        win_rate=100.0,
        current_streak=1,
        streak_type="win",
        longest_win_streak=1,
        longest_loss_streak=0,
        h2h={"Alice": {"wins": 1, "losses": 0, "draws": 0}},
    )
    print("Stats:", stats)

    log = MatchLog(matches=[m])
    print("MatchLog matches:", log.matches)
    print("models.py — OK")
