#!/usr/bin/env python3
"""figma-parity command line, runnable from anywhere.

The skill runs inside the *user's* project, not inside this repo, so nothing
here may assume the current directory. Invoke it by absolute path:

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" <command> ...

Commands:
    fetch-tree <file-key> <node-id>      tree via REST, when get_metadata fails
    classify  <tree.xml>                 what kind of node this is
    mode      <tree.xml> <project-dir>    build / audit / reconcile
    coverage  <ledger.md> [tree.xml]     the completion gate's verdict
    comments  <file-key> [tree.xml]      Figma pin threads as ledger rows
    snippet                              JS to dump computed styles from the page
    measure   <ledger.md> <actual.json>  exact spacing/sizing check
    diff      <figma.png> <render.png>   pixel diff  [--out DIR] [--tol N] [--threshold PCT]

Use `measure` for spacing and sizing, not `diff`. A 4px padding change moves
every border on screen and the pixel diff reports one useless blob; `measure`
reports "gap: design says 12px, browser rendered 8px".

Only `diff` needs pillow and numpy. `classify`, `coverage` and `comments` are
pure stdlib, so the tree walk, the ledger and the gate all work with no installs
at all. `comments` additionally needs a read-only FIGMA_TOKEN, and exits 3 with
setup instructions when there isn't one.
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


def _fetch_tree(argv: list[str]) -> int:
    from figma_parity.rest import NO_TOKEN, fetch_tree_xml

    if len(argv) < 2:
        print(
            "usage: parity.py fetch-tree <file-key> <node-id> [depth]\n\n"
            "Use this when get_metadata fails or truncates. It returns the same tree\n"
            "through Figma's REST API, which has no streaming layer to cut short.",
            file=sys.stderr,
        )
        return 2
    depth = int(argv[2]) if len(argv) > 2 else None
    try:
        print(fetch_tree_xml(argv[0], argv[1], depth=depth), end="")
    except PermissionError as exc:
        print(str(exc), file=sys.stderr)
        return NO_TOKEN
    except RuntimeError as exc:
        print(f"figma-parity: {exc}", file=sys.stderr)
        return 1
    return 0


def _mode(argv: list[str]) -> int:
    from figma_parity.mode import detect

    if len(argv) < 2:
        print("usage: parity.py mode <tree.xml> <project-dir>", file=sys.stderr)
        return 2
    print(detect(argv[1], argv[0]).report())
    return 0


def _coverage(argv: list[str]) -> int:
    from figma_parity.ledger import summarize

    if not argv:
        print("usage: parity.py coverage <ledger.md> [tree.xml]", file=sys.stderr)
        return 2
    summary = summarize(argv[0], argv[1] if len(argv) > 1 else None)
    print(summary.report())
    return 0 if summary.complete else 1


def _comments(argv: list[str]) -> int:
    from figma_parity.comments import NO_TOKEN, fetch, to_markdown

    if not argv:
        print("usage: parity.py comments <file-key> [tree.xml]", file=sys.stderr)
        return 2

    node_ids: set[str] | None = None
    if len(argv) > 1 and Path(argv[1]).exists():
        from figma_parity.tree import parse

        node_ids = parse(argv[1]).node_ids

    try:
        found = fetch(argv[0])
    except PermissionError as exc:  # no token: not configured, not broken
        print(str(exc), file=sys.stderr)
        return NO_TOKEN
    except RuntimeError as exc:
        print(f"figma-parity: {exc}", file=sys.stderr)
        return 1

    print(to_markdown(found, node_ids))
    return 0


def _snippet(argv: list[str]) -> int:
    from figma_parity.measure import browser_snippet

    print(browser_snippet())
    return 0


def _measure(argv: list[str]) -> int:
    from figma_parity.measure import compare

    if len(argv) < 2:
        print(
            "usage: parity.py measure <ledger.md> <actual.json>\n\n"
            "Get actual.json by running `parity.py snippet` in the page with your\n"
            "browser tooling and saving the result. Elements must carry\n"
            "data-node-id attributes, or there is nothing to line the ledger up with.",
            file=sys.stderr,
        )
        return 2
    result = compare(argv[0], argv[1])
    print(result.report())
    return 0 if result.passed else 1


def _diff(argv: list[str]) -> int:
    from figma_parity.diff import main as diff_main

    return diff_main(argv)


COMMANDS = {
    "fetch-tree": _fetch_tree,
    "classify": _classify,
    "mode": _mode,
    "coverage": _coverage,
    "comments": _comments,
    "snippet": _snippet,
    "measure": _measure,
    "diff": _diff,
}


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
