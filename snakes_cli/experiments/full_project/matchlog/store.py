"""U2: JSON persistence layer for the matchlog CLI.

Provides the Store class for loading, saving, and updating a match log
via a JSON file on disk. All writes are atomic (write-to-temp-then-rename).
Zero dependencies beyond the Python standard library.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import List

from matchlog.models import Match, MatchLog


class Store:
    """JSON-backed persistence for a MatchLog.

    Reads and writes a MatchLog to a single JSON file. If the file does not
    exist, operations treat the log as empty.

    Attributes:
        path: Filesystem path to the JSON data file.
    """

    def __init__(self, path: str = "matchlog.json") -> None:
        """Initialise the store.

        Args:
            path: Path to the JSON file used for persistence.
                  Defaults to ``matchlog.json`` in the current directory.
        """
        self.path: str = path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> MatchLog:
        """Load the match log from disk.

        Returns:
            A ``MatchLog`` instance. If the file does not exist or cannot
            be parsed, an empty ``MatchLog`` is returned.
        """
        if not os.path.isfile(self.path):
            return MatchLog()

        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return MatchLog()

        matches: List[Match] = [
            Match(
                opponent=item["opponent"],
                result=item["result"],
                played_at=item["played_at"],
                notes=item.get("notes", ""),
            )
            for item in data.get("matches", [])
        ]
        return MatchLog(matches=matches)

    def save(self, log: MatchLog) -> None:
        """Persist *log* to disk atomically.

        Writes serialised JSON to a temporary file in the same directory
        as *self.path*, then renames it over the target file. This
        guarantees that readers never see a partially-written file.

        Args:
            log: The ``MatchLog`` instance to persist.
        """
        data: dict = {
            "matches": [
                {
                    "opponent": m.opponent,
                    "result": m.result,
                    "played_at": m.played_at,
                    "notes": m.notes,
                }
                for m in log.matches
            ]
        }

        dir_name = os.path.dirname(self.path) or "."
        # Write to a temp file in the same directory so that rename is
        # guaranteed to be atomic (same filesystem).
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dir_name,
            delete=False,
            prefix=".matchlog_",
            suffix=".tmp",
        ) as tmp:
            tmp_path = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())

        os.replace(tmp_path, self.path)  # atomic rename on all platforms

    def add_match(self, match: Match) -> None:
        """Append a single match to the log and persist immediately.

        Args:
            match: The ``Match`` to record.
        """
        log = self.load()
        log.matches.append(match)
        self.save(log)


# ---------------------------------------------------------------------------
# Quick smoketest — run this file directly to verify the store works.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import datetime

    test_path = "__test_matchlog_store__.json"

    # Clean up from any previous run
    try:
        os.remove(test_path)
    except FileNotFoundError:
        pass

    # 1. Load a non-existent store → empty log
    store = Store(path=test_path)
    log = store.load()
    assert len(log.matches) == 0, "Expected empty log for new store"
    print("1. Empty load — OK")

    # 2. Add matches
    store.add_match(
        Match(
            opponent="Bob",
            result="win",
            played_at=datetime.datetime.now().isoformat(),
            notes="First match!",
        )
    )
    store.add_match(
        Match(
            opponent="Bob",
            result="loss",
            played_at=datetime.datetime.now().isoformat(),
        )
    )
    store.add_match(
        Match(
            opponent="Carol",
            result="draw",
            played_at=datetime.datetime.now().isoformat(),
            notes="Close one",
        )
    )

    # 3. Reload and verify
    store2 = Store(path=test_path)
    log2 = store2.load()
    assert len(log2.matches) == 3, f"Expected 3 matches, got {len(log2.matches)}"
    assert log2.matches[0].opponent == "Bob"
    assert log2.matches[0].result == "win"
    assert log2.matches[1].result == "loss"
    assert log2.matches[2].opponent == "Carol"
    assert log2.matches[2].result == "draw"
    print("2. Add and reload — OK")

    # 4. Verify JSON file looks right
    with open(test_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    assert len(raw["matches"]) == 3
    print("3. JSON structure — OK")

    # Cleanup
    os.remove(test_path)

    print("store.py — ALL OK")
