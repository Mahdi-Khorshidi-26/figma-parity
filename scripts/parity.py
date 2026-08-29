#!/usr/bin/env python3
"""figma-parity command line, runnable from anywhere.

The skill runs inside the *user's* project, not inside this repo, so nothing
here may assume the current directory. Invoke it by absolute path:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" <command> ...

Commands:
    classify  <tree.xml>                 what kind of node this is
    coverage  <ledger.md> [tree.xml]     the completion gate's verdict
    diff      <figma.png> <render.png>   pixel diff  [--out DIR] [--tol N] [--threshold PCT]

Only `diff` needs pillow and numpy. `classify` and `coverage` are pure stdlib,
so the tree walk, the ledger and the gate all work with no installs at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

# This file lives at <plugin>/scripts/, the package at <plugin>/src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _classify(argv: list[str]) -> int:
    from figma_parity.tree import parse

    if not argv:
        print("usage: parity.py classify <tree.xml>", file=sys.stderr)
        return 2
    tree = parse(argv[0])
    if not tree.total:
        print("empty tree — is that really the saved get_metadata response?", file=sys.stderr)
        return 1
    kind, reason = tree.classify()
    print(f"kind:       {kind}")
    print(f"reason:     {reason}")
    print(f"nodes:      {tree.total}")
    print(f"max depth:  {tree.max_depth}")
    print(f"types:      {dict(tree.types)}")
    print(f"components: {len(tree.unique_components)} unique from {len(tree.instances)} instances")
    if kind == "document":
        print(
            "\nSTOP: this is documentation *about* a UI, not the UI. Ask which the "
            "user wants built before implementing anything."
        )
    return 0


def _coverage(argv: list[str]) -> int:
    from figma_parity.ledger import summarize

    if not argv:
        print("usage: parity.py coverage <ledger.md> [tree.xml]", file=sys.stderr)
        return 2
    summary = summarize(argv[0], argv[1] if len(argv) > 1 else None)
    print(summary.report())
    return 0 if summary.complete else 1


def _diff(argv: list[str]) -> int:
    from figma_parity.diff import main as diff_main

    return diff_main(argv)


COMMANDS = {"classify": _classify, "coverage": _coverage, "diff": _diff}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    command = args.pop(0)
    if command not in COMMANDS:
        print(f"unknown command {command!r}; try one of {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    return COMMANDS[command](args)


if __name__ == "__main__":
    sys.exit(main())
