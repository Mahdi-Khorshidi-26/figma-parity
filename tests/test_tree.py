"""Checks for the derived-coverage tree.

The point of tree.py is that the model cannot inflate its own coverage score.
Most of these tests are attempts to do exactly that.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from figma_parity.tree import MAX_UNIT_NODES, Tree, ledger_node_ids, parse
except ModuleNotFoundError:  # staged, pre-install
    from tree import MAX_UNIT_NODES, Tree, ledger_node_ids, parse  # type: ignore

SMALL = """
<frame id="1:1" name="Card" width="400" height="300">
  <text id="1:2" name="Title" width="200" height="24" />
  <text id="1:3" name="Body" width="200" height="60" />
</frame>
"""

SCREEN = """
<frame id="2:1" name="Home" width="1440" height="900">
  <instance id="2:2" name="Header" width="1440" height="64">
    <text id="2:3" name="Logo" width="100" height="40" />
  </instance>
  <instance id="2:4" name="Header" width="1440" height="64">
    <text id="2:5" name="Logo" width="100" height="40" />
  </instance>
</frame>
"""

DOCUMENT = """
<frame id="3:1" name="Spec" width="1000" height="20000">
  <text id="3:2" name="Overview" width="800" height="60" />
</frame>
"""

BREAKPOINTS = """
<frame id="4:1" name="Page" width="1440" height="1200">
  <frame id="4:2" name="FAQs" width="1440" height="1000" />
  <frame id="4:3" name="FAQs" width="1024" height="1000" />
  <frame id="4:4" name="FAQs" width="390" height="1000" />
</frame>
"""


def test_parses_shape_and_depth():
    t = parse(SMALL)
    assert t.total == 3, t.total
    assert t.max_depth == 1, t.max_depth
    assert t.root and t.root.id == "1:1"
    assert t.get("1:2").name == "Title"


def test_naming_a_small_node_covers_its_subtree():
    t = parse(SMALL)
    assert len(t.covered_by({"1:1"})) == 3


def test_naming_a_huge_node_does_not_inflate_coverage():
    """The cheat this module exists to stop: claim the root, claim everything."""
    nodes = ['<frame id="9:0" name="Root" width="1000" height="1000">']
    for i in range(1, MAX_UNIT_NODES + 20):
        nodes.append(f'<text id="9:{i}" name="t{i}" width="10" height="10" />')
    nodes.append("</frame>")
    t = parse("\n".join(nodes))

    covered = t.covered_by({"9:0"})
    assert len(covered) == 1, (
        f"naming an unextractable {t.total}-node root must cover only itself, got {len(covered)}"
    )
    assert not t.covered_by(set())


def test_one_instance_covers_its_siblings():
    t = parse(SCREEN)
    covered = t.covered_by({"2:2"})
    assert "2:4" in covered, "the second Header instance should be covered by the first"
    assert "2:5" in covered, "and its subtree"


def test_unrelated_component_is_not_covered():
    xml = SCREEN.replace('id="2:4" name="Header"', 'id="2:4" name="Footer"')
    t = parse(xml)
    covered = t.covered_by({"2:2"})
    assert "2:4" not in covered, "a different component must not be covered by dedup"


def test_classify_document():
    kind, reason = parse(DOCUMENT).classify()
    assert kind == "document", kind
    assert "taller than wide" in reason


def test_classify_breakpoint_set():
    kind, reason = parse(BREAKPOINTS).classify()
    assert kind == "breakpoint-set", kind
    assert "descending widths" in reason


def test_classify_component_and_screen():
    assert parse(SMALL).classify()[0] == "component"
    assert parse(SCREEN).classify()[0] == "screen"


def test_ledger_node_ids_extraction():
    text = "| 4183:32365 | thing | ☑ |\nsee also 4551:38827 and not-an-id 12-34"
    assert ledger_node_ids(text) == {"4183:32365", "4551:38827"}


def test_empty_tree_is_safe():
    t = Tree()
    assert t.total == 0
    assert t.classify()[0] == "unknown"
    assert t.covered_by({"1:1"}) == set()


def test_real_dashboard_tree_if_present():
    """Regression against the actual 572-node design, when it's around."""
    sample = Path("/tmp/fp/node.xml")
    if not sample.exists():
        return
    t = parse(sample)
    assert t.total == 572, t.total
    assert t.classify()[0] == "document"
    assert len(t.covered_by({"4183:32365"})) == 1, "root claim must not inflate"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
