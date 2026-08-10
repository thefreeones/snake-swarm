"""U5: CLI entry point for the matchlog tool.

Defines the argument parser with three subcommands (*add*, *stats*, *list*)
and the ``main()`` function that wires them together. Zero dependencies
beyond the Python standard library and sibling matchlog modules.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from matchlog.commands.add import add_match
from matchlog.commands.stats import compute_stats
from matchlog.store import Store


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with subcommands.

    Returns:
        An ``ArgumentParser`` ready for ``parse_args()``.
    """
    parser = argparse.ArgumentParser(
        prog="matchlog",
        description="Track 1v1 match records — add, review, and analyse your results.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- add ----------------------------------------------------------------
    add_parser = sub.add_parser("add", help="Record a new match")
    add_parser.add_argument(
        "opponent",
        help="Name or identifier of the opponent",
    )
    add_parser.add_argument(
        "--result",
        required=True,
        choices=["win", "loss", "draw", "draw(win)"],
        help="Match outcome",
    )
    add_parser.add_argument(
        "--notes",
        default="",
        help="Optional free-form notes about the match",
    )

    # ---- stats --------------------------------------------------------------
    stats_parser = sub.add_parser("stats", help="Show aggregate statistics")
    stats_parser.add_argument(
        "opponent",
        nargs="?",
        default=None,
        help="Show head-to-head stats for a specific opponent (omit for overview)",
    )

    # ---- list ---------------------------------------------------------------
    list_parser = sub.add_parser("list", help="List recent matches")
    list_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Number of recent matches to display (default: 10)",
    )

    return parser


def _format_played_at(iso_str: str) -> str:
    """Extract a human-readable ``YYYY-MM-DD HH:MM`` string from an ISO datetime.

    Args:
        iso_str: ISO 8601 datetime string, e.g. ``"2026-08-06T14:30:00+00:00"``.

    Returns:
        A string like ``"2026-08-06 14:30"``.
    """
    return iso_str[:16].replace("T", " ")


def _cmd_add(store: Store, args: argparse.Namespace) -> None:
    """Handle the ``add`` subcommand."""
    match = add_match(store, args.opponent, args.result, args.notes)
    dt = _format_played_at(match.played_at)
    print(f"Recorded: {dt} | {match.result} vs {match.opponent}")


def _cmd_stats(store: Store, args: argparse.Namespace) -> None:
    """Handle the ``stats`` subcommand."""
    log = store.load()
    stats = compute_stats(log.matches)

    if args.opponent is not None:
        # Head-to-head for a specific opponent
        opponent = args.opponent
        if opponent in stats.h2h:
            h = stats.h2h[opponent]
            print(f"vs {opponent}: {h['wins']}W {h['losses']}L {h['draws']}D")
        else:
            print(f"No matches recorded against {opponent!r}.")
        return

    # Overview
    print(f"Total:    {stats.total}")
    print(f"Wins:     {stats.wins}")
    print(f"Losses:   {stats.losses}")
    print(f"Draws:    {stats.draws}")
    print(f"Win Rate: {stats.win_rate:.1f}%")

    if stats.streak_type == "none":
        print("Streak:   -")
    else:
        label = f"{abs(stats.current_streak)}{stats.streak_type[0].upper()}"
        print(f"Streak:   {label}")


def _cmd_list(store: Store, args: argparse.Namespace) -> None:
    """Handle the ``list`` subcommand."""
    log = store.load()
    recent = log.matches[-args.limit :]  # last N, newest last
    for m in reversed(recent):  # newest first
        dt = _format_played_at(m.played_at)
        print(f"{dt} | {m.result} vs {m.opponent}")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "add": _cmd_add,
    "stats": _cmd_stats,
    "list": _cmd_list,
}


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Parse command-line arguments and dispatch to the matching handler.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    store_path = os.environ.get("MATCHLOG_PATH", "matchlog.json")
    store = Store(path=store_path)

    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(store, args)


# ---------------------------------------------------------------------------
# Smoketest — run this file directly to exercise the three subcommands.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import shutil
    import tempfile

    test_dir = tempfile.mkdtemp(prefix="matchlog_test_")
    test_db = os.path.join(test_dir, "matchlog.json")
    os.environ["MATCHLOG_PATH"] = test_db

    print("=== U5 smoketest ===\n")

    # 1. add Alice win
    print("1. add Alice --result win")
    main(["add", "Alice", "--result", "win"])

    # 2. add Bob loss
    print("\n2. add Bob --result loss")
    main(["add", "Bob", "--result", "loss"])

    # 3. stats overview
    print("\n3. stats (overview)")
    main(["stats"])

    # 4. list
    print("\n4. list")
    main(["list"])

    # 5. verify JSON exists
    assert os.path.isfile(test_db), "matchlog.json was not created"
    print(f"\n5. JSON file exists at {test_db} — OK")

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)
    print("\ncli.py — ALL OK")
