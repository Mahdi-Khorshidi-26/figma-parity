"""Checks for the completion gate.

The gate is the reason this project exists: the model must not be able to
declare itself finished. Every test here is an attempt to sneak an incomplete
run past it.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.ledger import summarize  # noqa: E402

HEADER = "Coverage: nodes {done}/{total}\n\n| prop | expected | status | note |\n|---|---|---|---|\n"


def _ledger(rows, done=2, total=2):
    return HEADER.format(done=done, total=total) + "\n".join(rows) + "\n"


def _write(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "ledger.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_open_row_blocks_completion():
    p = _write(_ledger([
        "| font-size | 18px | ☑ | |",
        "| color | #1A1A1A | ☐ | |",
    ]))
    s = summarize(p)
    assert s.total == 2, s.total
    assert s.todo == 1
    assert not s.complete, "one ☐ must block completion"


def test_all_done_with_full_coverage_completes():
    p = _write(_ledger([
        "| font-size | 18px | ☑ | |",
        "| color | #1A1A1A | ☑ | |",
    ]))
    s = summarize(p)
    assert s.done == 2
    assert s.coverage_complete
    assert s.complete, s.report()


def test_deviation_without_reason_does_not_pass():
    """The obvious cheat: flip every ☐ to ⚠ and call it done."""
    p = _write(_ledger([
        "| font-size | 18px | ⚠ | |",
        "| color | #1A1A1A | ⚠ | |",
    ]))
    s = summarize(p)
    assert len(s.unjustified) == 2, s.unjustified
    assert not s.complete, "unjustified deviations must not satisfy the gate"


def test_deviation_with_written_reason_passes():
    p = _write(_ledger([
        "| font-size | 18px | ☑ | |",
        "| color | #1A1A1A | ⚠ | design token maps to #1B1B1B in our palette |",
    ]))
    s = summarize(p)
    assert s.unjustified == [], s.unjustified
    assert s.complete, s.report()


def test_blocked_needs_a_reason_too():
    p = _write(_ledger([
        "| font-family | Söhne | ✖ | |",
        "| color | #1A1A1A | ☑ | |",
    ]))
    assert not summarize(p).complete
    p2 = _write(_ledger([
        "| font-family | Söhne | ✖ | font not licensed in this project |",
        "| color | #1A1A1A | ☑ | |",
    ]))
    assert summarize(p2).complete


def test_partial_traversal_blocks_even_when_all_rows_ticked():
    """Every extracted row done, but the tree was never fully walked.
    This is Mahdi's exact failure: it looks finished because what it
    missed was never written down."""
    p = _write(_ledger([
        "| font-size | 18px | ☑ | |",
        "| color | #1A1A1A | ☑ | |",
    ], done=12, total=47))
    s = summarize(p)
    assert s.todo == 0
    assert not s.coverage_complete
    assert not s.complete, "partial traversal must block completion"


def test_missing_coverage_line_is_not_proof_of_coverage():
    p = _write("| prop | expected | status | note |\n|---|---|---|---|\n| a | b | ☑ | |\n")
    assert not summarize(p).complete


def test_missing_ledger_is_incomplete():
    s = summarize(Path(tempfile.mkdtemp()) / "nope.md")
    assert not s.exists
    assert not s.complete
    assert "NO LEDGER" in s.report()


def test_empty_ledger_is_incomplete():
    p = _write(HEADER.format(done=0, total=0))
    assert not summarize(p).complete


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
