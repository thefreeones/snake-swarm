"""U4: Compute aggregate statistics from a list of Match records.

Provides the ``compute_stats`` function that derives a ``Stats``
object from a chronologically-ordered match list. Zero dependencies
beyond the Python standard library and sibling modules.
"""

from __future__ import annotations

from typing import Dict, List

from matchlog.models import Match, Stats


def compute_stats(matches: List[Match]) -> Stats:
    """Derive aggregate ``Stats`` from a list of ``Match`` instances.

    Matches are assumed to be in chronological order (oldest first).
    Computes win/loss/draw counts, win rate, current and longest
    streaks, and head-to-head breakdowns per opponent.

    Args:
        matches: A ``List[Match]`` in chronological order.

    Returns:
        A populated ``Stats`` dataclass instance.
    """
    total = len(matches)

    # --- Per-result counters -------------------------------------------------
    wins = 0
    losses = 0
    draws = 0  # includes both "draw" and "draw(win)"

    h2h: Dict[str, dict] = {}

    for m in matches:
        # Global tallies
        if m.result == "win":
            wins += 1
        elif m.result == "loss":
            losses += 1
        else:  # "draw" or "draw(win)"
            draws += 1

        # Head-to-head
        if m.opponent not in h2h:
            h2h[m.opponent] = {"wins": 0, "losses": 0, "draws": 0}
        if m.result == "win":
            h2h[m.opponent]["wins"] += 1
        elif m.result == "loss":
            h2h[m.opponent]["losses"] += 1
        else:
            h2h[m.opponent]["draws"] += 1

    # --- Win rate ------------------------------------------------------------
    deciders = wins + losses
    win_rate = (wins / deciders * 100.0) if deciders > 0 else 0.0

    # --- Streaks -------------------------------------------------------------
    current_streak = 0
    streak_type = "none"
    longest_win_streak = 0
    longest_loss_streak = 0

    if matches:
        # Current streak: scan backwards from most recent.
        # Determines the type from the last match, then counts backwards
        # while the result stays in the same "family".
        last = matches[-1]

        if last.result == "win":
            streak_type = "win"
        elif last.result == "loss":
            streak_type = "loss"
        # else "draw" / "draw(win)" → stay on "none", current_streak = 0

        if streak_type != "none":
            current_streak = 1
            for m in reversed(matches[:-1]):
                if m.result == streak_type:
                    current_streak += 1
                else:
                    break

        # Longest streaks: scan forward through the entire list.
        active_win = 0
        active_loss = 0

        for m in matches:
            if m.result == "win":
                active_win += 1
                active_loss = 0
                if active_win > longest_win_streak:
                    longest_win_streak = active_win
            elif m.result == "loss":
                active_loss += 1
                active_win = 0
                if active_loss > longest_loss_streak:
                    longest_loss_streak = active_loss
            else:
                # Draws reset both active streaks.
                active_win = 0
                active_loss = 0

    # -------------------------------------------------------------------------
    return Stats(
        total=total,
        wins=wins,
        losses=losses,
        draws=draws,
        win_rate=win_rate,
        current_streak=current_streak,
        streak_type=streak_type,
        longest_win_streak=longest_win_streak,
        longest_loss_streak=longest_loss_streak,
        h2h=h2h,
    )
