"""Decide whether to build, audit, or reconcile — by looking, not by asking.

Three situations arrive and they need different work:

  build      nothing exists yet; implement the design from scratch
  audit      it is already built; measure it and report what drifted
  reconcile  some of it exists; finish the gaps AND check what is there

The third is the common one in a real codebase and the easiest to get wrong.
Told "implement this", an agent rebuilds a screen that is 80% done and throws
away working code. Told "check this", it audits the 80% and never notices the
20% that was never built. Both are wrong, and neither announces itself.

The signal is `data-node-id`: the attribute that ties a rendered element back to
its design node, and the same one `measure.py` needs. Its presence is evidence,
its absence is only weak evidence — plenty of real code is correct and simply
never carried the attribute — so an empty result reports low confidence rather
than asserting nothing exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .tree import Tree, parse as parse_tree

NODE_ID_ATTR = re.compile(r"""data-node-id\s*=\s*["'{]?\s*["']?(\d+:\d+)""")

SOURCE_SUFFIXES = {
    ".tsx", ".jsx", ".ts", ".js", ".mjs", ".vue", ".svelte", ".astro",
    ".html", ".liquid", ".erb", ".php", ".swift", ".kt", ".dart", ".xml",
}
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".cache", "vendor",
    "__pycache__", ".venv", "venv", "coverage", ".figma-parity", ".turbo",
}

# Above this share of the design's nodes present in code, treat it as built.
AUDIT_THRESHOLD = 0.80
# Below this, treat it as greenfield.
BUILD_THRESHOLD = 0.05


@dataclass
class ModeResult:
    mode: str
    reason: str
    matched: set[str] = field(default_factory=set)
    total: int = 0
    files: list[Path] = field(default_factory=list)
    scanned: int = 0

    @property
    def ratio(self) -> float:
        return len(self.matched) / self.total if self.total else 0.0

    @property
    def confident(self) -> bool:
        """Whether the evidence is strong enough to act on without asking."""
        return bool(self.matched) or self.scanned == 0

    def report(self) -> str:
        lines = [
            f"mode:     {self.mode}",
            f"reason:   {self.reason}",
            f"evidence: {len(self.matched)}/{self.total} design nodes found in "
            f"{self.scanned} source file(s)",
        ]
        if self.files:
            lines.append("files:")
            for f in self.files[:10]:
                lines.append(f"  {f}")
            if len(self.files) > 10:
                lines.append(f"  ... and {len(self.files) - 10} more")
        if not self.confident:
            lines.append("")
            lines.append(
                "NOTE: no data-node-id attributes were found anywhere. That means "
                "either this really is unbuilt, or it was built without them — those "
                "look identical from here. Confirm with the user before rebuilding "
                "a screen that may already exist."
            )
        return "\n".join(lines)


def scan(project_dir: str | Path, tree: Tree) -> tuple[set[str], list[Path], int]:
    """Find which of the design's node ids appear in the project's source."""
    root = Path(project_dir)
    matched: set[str] = set()
    hit_files: list[Path] = []
    scanned = 0
    known = tree.node_ids

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = {m for m in NODE_ID_ATTR.findall(text) if m in known}
        if found:
            matched |= found
            hit_files.append(path.relative_to(root))
    return matched, hit_files, scanned


def detect(project_dir: str | Path, tree_path: str | Path) -> ModeResult:
    tree = parse_tree(tree_path)
    matched, files, scanned = scan(project_dir, tree)
    result = ModeResult(mode="", reason="", matched=matched, total=tree.total,
                        files=files, scanned=scanned)

    if not matched:
        result.mode = "build"
        result.reason = (
            "no design nodes are referenced anywhere in the project — nothing to "
            "audit, so implement from scratch"
        )
    elif result.ratio >= AUDIT_THRESHOLD:
        result.mode = "audit"
        result.reason = (
            f"{result.ratio:.0%} of the design's nodes already appear in the code — "
            f"this is built, so measure it and report what drifted rather than "
            f"rebuilding it"
        )
    elif result.ratio < BUILD_THRESHOLD:
        result.mode = "build"
        result.reason = (
            f"only {result.ratio:.0%} of the design is referenced, which is closer to "
            f"a stray leftover than an implementation"
        )
    else:
        result.mode = "reconcile"
        result.reason = (
            f"{result.ratio:.0%} of the design is implemented and the rest is not. "
            f"Audit what exists, build only what is missing, and do not rewrite "
            f"working code"
        )
    return result
