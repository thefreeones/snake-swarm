"""U4: CLI entry point for the pystatic static analyser.

Defines the argument parser with two subcommands (*scan* and *rules*)
and the ``main()`` function that wires the full pipeline together.

Pipeline (scan command)
------------------------
1. Discover ``.py`` files under the target path.
2. ``scanner.get_ast_nodes(path)``  — parse each file → ``(tree, source)``.
3. Apply each enabled rule            — ``check_*(tree, source, filepath)`` → ``List[Issue]``.
4. ``reporter.aggregate(...)``       — merge all issues into a ``Report``.
5. ``reporter.to_markdown()``        — render report to Markdown.
   ``reporter.to_json()``            — render report to JSON.

Zero dependencies beyond the Python standard library and sibling
pystatic modules (scanner, rules, reporter).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

# ---------------------------------------------------------------------------
# Ensure the parent of the ``pystatic`` package is on sys.path so that
# sibling submodules are importable regardless of how this file is invoked
# (as ``python -m pystatic.cli``, ``python pystatic/cli.py``, or via an
# installed entry point).
# ---------------------------------------------------------------------------
_PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

# ---------------------------------------------------------------------------
# Optional imports — the sibling modules are built by other agents.
# The CLI degrades gracefully when they are not yet available so that at
# least ``pystatic rules`` and ``--help`` always work.
# ---------------------------------------------------------------------------
try:
    from pystatic.scanner import get_ast_nodes  # (path) -> (tree|None, source)
except ImportError:  # pragma: no cover
    get_ast_nodes = None  # type: ignore[assignment]

try:
    from pystatic.rules import ALL_RULES as RULES_REGISTRY
except ImportError:  # pragma: no cover
    RULES_REGISTRY: dict[str, object] = {}  # type: ignore[no-redef]

try:
    from pystatic.reporter import aggregate, to_markdown, to_json
except ImportError:  # pragma: no cover
    aggregate = None  # type: ignore[assignment]
    to_markdown = None  # type: ignore[assignment]
    to_json = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Rule metadata — human-readable descriptions for ``pystatic rules``.
# ---------------------------------------------------------------------------
_RULE_DESCRIPTIONS: dict[str, str] = {
    "bare-except": "Detect bare ``except:`` or ``except Exception`` clauses",
    "mutable-default": "Detect mutable default arguments (``[]`` / ``{}``)",
    "too-broad-try": "Detect ``try`` blocks that span more than 20 lines",
    "print-leftover": "Detect leftover ``print()`` debugging calls",
    "function-length": "Detect functions longer than 50 lines",
}

ALL_RULE_NAMES: tuple[str, ...] = tuple(_RULE_DESCRIPTIONS)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _discover_py_files(target: str) -> List[Path]:
    """Recursively collect all ``.py`` files under *target*.

    If *target* is a single ``.py`` file, returns a single-element list.
    Directories are walked recursively with ``os.walk``.

    Args:
        target: A file or directory path.

    Returns:
        Sorted list of ``Path`` objects ending in ``.py``.
    """
    p = Path(target).resolve()
    if p.is_file():
        return [p] if p.suffix == ".py" else []
    py_files: List[Path] = []
    for root, _dirs, files in os.walk(p):
        root_path = Path(root)
        for fname in files:
            if fname.endswith(".py"):
                py_files.append(root_path / fname)
    return sorted(py_files)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with subcommands.

    Returns:
        An ``ArgumentParser`` ready for ``parse_args()``.
    """
    parser = argparse.ArgumentParser(
        prog="pystatic",
        description="A mini static analyser for Python code — detect common "
                    "anti-patterns and print a structured report.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- scan ---------------------------------------------------------------
    scan_parser = sub.add_parser(
        "scan",
        help="Scan a file or directory for issues",
    )
    scan_parser.add_argument(
        "path",
        help="Path to a Python file or directory to scan",
    )
    scan_parser.add_argument(
        "--format",
        choices=["md", "json"],
        default="md",
        help="Output format (default: md)",
    )
    scan_parser.add_argument(
        "-o", "--output",
        default=None,
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    scan_parser.add_argument(
        "--rules",
        default=None,
        metavar="RULES",
        help="Comma-separated list of rules to enable "
             "(default: all).  Example: --rules bare-except,print-leftover",
    )

    # ---- rules --------------------------------------------------------------
    sub.add_parser(
        "rules",
        help="List all available static-analysis rules",
    )

    return parser


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _cmd_rules(args: argparse.Namespace) -> None:
    """Handle the ``rules`` subcommand — list all known rules.

    Uses the statically-defined ``_RULE_DESCRIPTIONS`` so this subcommand
    always works even when the rules module is not yet built.
    """
    print("Available rules:\n")
    for name in ALL_RULE_NAMES:
        desc = _RULE_DESCRIPTIONS[name]
        print(f"  {name:<20} {desc}")
    print(f"\n{len(ALL_RULE_NAMES)} rules total.")


def _cmd_scan(args: argparse.Namespace) -> None:
    """Handle the ``scan`` subcommand — run the full pipeline.

    1. Discover ``.py`` files under *path*.
    2. Parse each file with ``scanner.get_ast_nodes()`` → ``(tree, source)``.
    3. Run every enabled rule checker against each ``(tree, source, filepath)``.
    4. Aggregate all issues via ``reporter.aggregate()`` → ``Report``.
    5. Render to Markdown or JSON and emit.
    """
    # --- Resolve which rules to enable ---
    if args.rules is not None:
        enabled = [r.strip() for r in args.rules.split(",")]
        for r in enabled:
            if r not in _RULE_DESCRIPTIONS:
                print(
                    f"pystatic: unknown rule {r!r}. "
                    f"Run 'pystatic rules' to see available rules.",
                    file=sys.stderr,
                )
                sys.exit(1)
    else:
        enabled = list(ALL_RULE_NAMES)

    # --- Guard: check sibling modules exist ---
    if get_ast_nodes is None:
        print(
            "pystatic: scanner module not found — the analysis engine "
            "has not been built yet (it lives in pystatic.scanner).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not RULES_REGISTRY:
        print(
            "pystatic: rules module not found — the rule checkers "
            "have not been built yet (they live in pystatic.rules).",
            file=sys.stderr,
        )
        sys.exit(1)

    if aggregate is None or to_markdown is None or to_json is None:
        print(
            "pystatic: reporter module not found — the reporting engine "
            "has not been built yet (it lives in pystatic.reporter).",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Resolve the target ---
    target = args.path
    if not os.path.exists(target):
        print(f"pystatic: path does not exist: {target}", file=sys.stderr)
        sys.exit(1)

    # --- Step 1: discover .py files ---
    py_files = _discover_py_files(target)
    if not py_files:
        print(f"pystatic: no Python files found at {target}")
        sys.exit(0)

    # --- Step 2+3: parse each file and apply rules ---
    all_issues: list = []
    for filepath in py_files:
        tree, source = get_ast_nodes(str(filepath))
        if tree is None:
            # source holds the error message when tree is None
            print(f"pystatic: skip {filepath} — {source}", file=sys.stderr)
            continue

        for rule_name in enabled:
            checker = RULES_REGISTRY.get(rule_name)
            if checker is None:
                print(
                    f"pystatic: rule checker {rule_name!r} not found in "
                    f"rules module.",
                    file=sys.stderr,
                )
                continue
            try:
                issues = checker(tree, source, str(filepath))
                all_issues.extend(issues)
            except Exception as exc:
                print(
                    f"pystatic: rule {rule_name!r} failed on {filepath}: {exc}",
                    file=sys.stderr,
                )

    # --- Step 4: aggregate ---
    report = aggregate(all_issues)

    # --- Step 5: render ---
    if args.format == "json":
        output_text = to_json(report)
    else:
        output_text = to_markdown(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
            f.write("\n")
        print(f"Report written to {args.output}")
    else:
        print(output_text)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "scan": _cmd_scan,
    "rules": _cmd_rules,
}


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Parse command-line arguments and dispatch to the matching handler.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


# ---------------------------------------------------------------------------
# Smoketest — run ``python pystatic/cli.py`` to exercise the full pipeline.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import shutil
    import tempfile

    print("=== U4 smoketest ===\n")

    # 1. Show help
    print("1. pystatic --help")
    try:
        main(["--help"])
    except SystemExit:
        pass

    # 2. Rules subcommand
    print("\n2. pystatic rules")
    main(["rules"])

    # Locate test_samples relative to this file
    _cli_dir = Path(__file__).resolve().parent
    _samples_dir = _cli_dir.parent / "test_samples"

    # 3. Scan sample_dirty.py — should trigger at least one issue per rule
    _dirty = str(_samples_dir / "sample_dirty.py")
    print(f"\n3. pystatic scan {_dirty} --format json")
    main(["scan", _dirty, "--format", "json"])

    # 4. Scan sample_dirty.py with --rules (selective)
    print(f"\n4. pystatic scan {_dirty} --rules bare-except,print-leftover")
    main(["scan", _dirty, "--rules", "bare-except,print-leftover"])

    # 5. Scan sample_clean.py — should produce 0 issues
    _clean = str(_samples_dir / "sample_clean.py")
    print(f"\n5. pystatic scan {_clean}")
    main(["scan", _clean])

    # 6. Scan with --output to file
    _tmpdir = tempfile.mkdtemp(prefix="pystatic_test_")
    try:
        _out = os.path.join(_tmpdir, "report.md")
        print(f"\n6. pystatic scan {_dirty} --output {_out}")
        main(["scan", _dirty, "--output", _out])
        assert os.path.isfile(_out), "report.md was not created"
        with open(_out, encoding="utf-8") as f:
            assert "# pystatic 扫描报告" in f.read(), "report content missing"
        print(f"   ✓ {_out} created and contains valid report")
    finally:
        shutil.rmtree(_tmpdir, ignore_errors=True)

    print("\ncli.py — ALL OK")
