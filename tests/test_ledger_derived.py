"""The self-reported Coverage line must lose to the derived one."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from figma_parity.ledger import summarize  # noqa: E402

TREE = """
<frame id="1:1" name="Root" width="1440" height="900">
  <frame id="1:2" name="A" width="700" height="400"><text id="1:3" name="t" width="1" height="1" /></frame>
  <frame id="1:4" name="B" width="700" height="400"><text id="1:5" name="t" width="1" height="1" /></frame>
</frame>
"""
HEAD = "Coverage: nodes {n}/5\n\n| node | prop | expected | status | note |\n|---|---|---|---|---|\n"

def _run(rows, claimed, with_tree=True):
    d = Path(tempfile.mkdtemp())
    (d / "ledger.md").write_text(HEAD.format(n=claimed) + "\n".join(rows) + "\n")
    if with_tree:
        (d / "tree.xml").write_text(TREE)
    return summarize(d / "ledger.md")

def test_derived_coverage_beats_a_lying_coverage_line():
    s = _run(["| 1:2 | x | y | ☑ | |"], claimed=5)
    assert s.coverage_derived, "tree.xml present -> coverage must be derived"
    assert s.derived_total == 5
    assert s.derived_covered == 2, s.derived_covered
    assert s.overclaimed, "claiming 5 while ids account for 2 must be flagged"
    assert not s.complete

def test_full_coverage_from_real_ids_passes():
    rows = ["| 1:2 | x | y | ☑ | |", "| 1:4 | x | y | ☑ | |", "| 1:1 | root | y | ☑ | |"]
    s = _run(rows, claimed=5)
    assert s.derived_covered == 5, s.derived_covered
    assert not s.overclaimed
    assert s.complete, s.report()

def test_without_a_tree_it_says_self_reported():
    s = _run(["| 1:2 | x | y | ☑ | |"], claimed=5, with_tree=False)
    assert not s.coverage_derived
    assert "SELF-REPORTED" in s.report()

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn(); print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
