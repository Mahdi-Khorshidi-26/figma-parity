"""Parse and gate on the parity ledger.

The ledger is the loop's external memory: every property of every Figma node
becomes a row with a status box. This module counts those boxes.

That count IS the completion gate. The model never decides it is finished —
`summarize()` does, from what is written on disk. This is the fix for the
failure mode where the same model that wants to be done is the one judging
whether it is done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .tree import Tree, ledger_node_ids, parse as parse_tree

TODO = "☐"      # ☐ not yet implemented
DONE = "☑"      # ☑ implemented and verified
DEVIATION = "⚠"  # ⚠ deliberate deviation — REASON REQUIRED
BLOCKED = "✖"   # ✖ cannot be done — REASON REQUIRED

STATUSES = (TODO, DONE, DEVIATION, BLOCKED)
_NEEDS_REASON = (DEVIATION, BLOCKED)

_COVERAGE_RE = re.compile(r"nodes\s+(\d+)\s*/\s*(\d+)", re.I)


@dataclass
class Row:
    line_no: int
    status: str
    cells: list[str]

    @property
    def label(self) -> str:
        return " · ".join(c for c in self.cells if c and c not in STATUSES)[:90]


@dataclass
class LedgerSummary:
    path: Path
    rows: list[Row] = field(default_factory=list)
    nodes_extracted: int = 0
    nodes_total: int = 0
    exists: bool = True
    # Derived from the saved design tree, NOT from anything the model wrote.
    # When these are set they override the self-reported numbers above.
    derived_covered: int | None = None
    derived_total: int | None = None

    def _count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def todo(self) -> int:
        return self._count(TODO)

    @property
    def done(self) -> int:
        return self._count(DONE)

    @property
    def deviations(self) -> int:
        return self._count(DEVIATION)

    @property
    def blocked(self) -> int:
        return self._count(BLOCKED)

    @property
    def unjustified(self) -> list[Row]:
        """⚠/✖ rows with no written reason.

        Without this check the gate is trivially gameable: flip every ☐ to ⚠
        and the run 'completes'. A deviation only counts as resolved when the
        reason is actually written down.
        """
        out = []
        for r in self.rows:
            if r.status in _NEEDS_REASON:
                note = " ".join(c for c in r.cells if c not in STATUSES).strip()
                # The note column is the last cell; a bare label is not a reason.
                if not r.cells or not r.cells[-1].strip() or r.cells[-1].strip() in STATUSES:
                    out.append(r)
                elif len(note) < 8:
                    out.append(r)
        return out

    @property
    def open_count(self) -> int:
        """Rows still standing between this run and honest completion."""
        return self.todo + len(self.unjustified)

    @property
    def coverage_derived(self) -> bool:
        """True when coverage came from the design tree rather than the model."""
        return self.derived_total is not None and self.derived_total > 0

    @property
    def overclaimed(self) -> bool:
        """The model claimed more coverage than the tree actually supports.

        This is the tell that a run wrote a flattering Coverage line. It is a
        hard failure, not a rounding difference.
        """
        if not self.coverage_derived or self.nodes_extracted <= 0:
            return False
        return self.nodes_extracted > (self.derived_covered or 0)

    @property
    def coverage_complete(self) -> bool:
        # Prefer the number Python derived from the design over the one the
        # model wrote about itself. An unstated coverage line is not proof.
        if self.coverage_derived:
            return not self.overclaimed and (self.derived_covered or 0) >= (self.derived_total or 0)
        return self.nodes_total > 0 and self.nodes_extracted >= self.nodes_total

    @property
    def complete(self) -> bool:
        return (
            self.exists
            and self.total > 0
            and self.open_count == 0
            and self.coverage_complete
        )

    def report(self) -> str:
        if not self.exists:
            return f"NO LEDGER at {self.path} — extraction never ran."
        verdict = "COMPLETE" if self.complete else "INCOMPLETE"
        lines = [
            f"{verdict}  {self.total} rows: {self.done} done · {self.todo} todo · "
            f"{self.deviations} deviation · {self.blocked} blocked",
        ]
        if self.coverage_derived:
            lines.append(
                f"  coverage: nodes {self.derived_covered}/{self.derived_total} "
                f"(derived from the design tree, not self-reported)"
                + ("" if self.coverage_complete else "  ← INCOMPLETE TRAVERSAL")
            )
            if self.overclaimed:
                lines.append(
                    f"  ! OVERCLAIMED: the ledger says {self.nodes_extracted} nodes but its node "
                    f"ids only account for {self.derived_covered}. The Coverage line is not "
                    f"evidence — the node ids in the rows are."
                )
        else:
            lines.append(
                f"  coverage: nodes {self.nodes_extracted}/{self.nodes_total} (SELF-REPORTED — "
                f"save get_metadata to .figma-parity/tree.xml to have this derived instead)"
                + ("" if self.coverage_complete else "  ← INCOMPLETE TRAVERSAL")
            )
        if self.unjustified:
            lines.append(f"  {len(self.unjustified)} deviation/blocked row(s) with no reason given:")
            for r in self.unjustified[:10]:
                lines.append(f"    line {r.line_no}: {r.label}")
        if self.todo:
            lines.append(f"  first open rows:")
            for r in [r for r in self.rows if r.status == TODO][:10]:
                lines.append(f"    line {r.line_no}: {r.label}")
        return "\n".join(lines)


def summarize(path: str | Path, tree_path: str | Path | None = None) -> LedgerSummary:
    """Read a ledger.md and report whether the run may honestly be called done.

    When the raw get_metadata response has been saved (default:
    `<ledger dir>/tree.xml`), coverage is computed from that file and the node
    ids appearing in the ledger — so the model cannot inflate its own score.
    """
    p = Path(path)
    if not p.exists():
        return LedgerSummary(path=p, exists=False)

    text = p.read_text(encoding="utf-8")
    summary = LedgerSummary(path=p)

    tree_file = Path(tree_path) if tree_path else p.parent / "tree.xml"
    if tree_file.exists():
        tree: Tree = parse_tree(tree_file)
        if tree.total:
            summary.derived_total = tree.total
            summary.derived_covered = len(tree.covered_by(ledger_node_ids(text)))

    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()

        if summary.nodes_total == 0 and "nodes" in stripped.lower():
            m = _COVERAGE_RE.search(stripped)
            if m:
                summary.nodes_extracted = int(m.group(1))
                summary.nodes_total = int(m.group(2))

        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        found = [c for c in cells if c in STATUSES]
        if len(found) != 1:
            continue  # header, separator, or a row without exactly one status
        summary.rows.append(Row(line_no=line_no, status=found[0], cells=cells))

    return summary
