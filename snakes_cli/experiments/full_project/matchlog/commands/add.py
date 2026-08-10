"""U3: Add a match record to the match log.

Provides the ``add_match`` function for creating and persisting a new
Match through the Store abstraction. Zero dependencies beyond the
Python standard library and sibling modules.
"""

from __future__ import annotations

from datetime import datetime, timezone

from matchlog.models import Match

_VALID_RESULTS = frozenset({"win", "loss", "draw", "draw(win)"})


def add_match(store, opponent: str, result: str, notes: str = "") -> Match:
    """Record a new match and persist it through *store*.

    Args:
        store: A ``Store`` instance that provides ``store.add_match(match)``.
        opponent: Name or identifier of the opponent.
        result: Match outcome — must be one of ``"win"``, ``"loss"``,
            ``"draw"``, or ``"draw(win)"``.
        notes: Optional free-form notes (default ``""``).

    Returns:
        The newly created ``Match`` instance.

    Raises:
        ValueError: If *result* is not one of the recognised values.
    """
    if result not in _VALID_RESULTS:
        raise ValueError(
            f"Invalid result {result!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_RESULTS))}"
        )

    match = Match(
        opponent=opponent,
        result=result,
        played_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )

    store.add_match(match)
    return match
