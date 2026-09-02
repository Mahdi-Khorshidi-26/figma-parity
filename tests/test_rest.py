"""Checks for the REST fallback.

This exists because get_metadata can fail deterministically on a large node,
which stops the whole run at Phase 0. The conversion must produce exactly the
tree shape the rest of the pipeline already understands, or the fallback is no
fallback at all. No network here — only the conversion is tested.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.rest import NO_TOKEN, SETUP_HELP, to_xml  # noqa: E402
from figma_parity.tree import parse  # noqa: E402

PAYLOAD = {
    "nodes": {
        "2751:1998": {
            "document": {
                "id": "2751:1998",
                "name": "Landing web 1920",
                "type": "SECTION",
                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 11063, "height": 4300},
                "children": [
                    {
                        "id": "2751:2002",
                        "name": "Landing",
                        "type": "FRAME",
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1920, "height": 4000},
                        "children": [
                            {
                                "id": "2751:2003",
                                "name": 'Hero "quoted" & <tagged>',
                                "type": "TEXT",
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 800, "height": 64},
                            },
                            {
                                "id": "2751:2004",
                                "name": "Nav",
                                "type": "INSTANCE",
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1920, "height": 80},
                            },
                        ],
                    },
                    {
                        "id": "2894:2321",
                        "name": "Landing",
                        "type": "FRAME",
                        "absoluteBoundingBox": {"x": 2000, "y": 0, "width": 1920, "height": 4000},
                    },
                ],
            }
        }
    }
}


def test_converts_into_a_tree_the_pipeline_can_parse():
    tree = parse(to_xml(PAYLOAD, "2751:1998"))
    assert tree.total == 5, tree.total
    assert tree.root and tree.root.id == "2751:1998"
    assert tree.root.width == 11063


def test_figma_types_map_onto_the_metadata_tags():
    tree = parse(to_xml(PAYLOAD, "2751:1998"))
    tags = {n.id: n.tag for n in tree.nodes}
    assert tags["2751:1998"] == "section"
    assert tags["2751:2002"] == "frame"
    assert tags["2751:2003"] == "text"
    assert tags["2751:2004"] == "instance", "INSTANCE must map, or component dedup breaks"


def test_names_with_quotes_and_angle_brackets_survive():
    """quoteattr would single-quote this, and tree.py would read an empty name —
    which silently corrupts component dedup, since it groups by name."""
    tree = parse(to_xml(PAYLOAD, "2751:1998"))
    node = tree.get("2751:2003")
    assert node is not None, "the node after the quoted name went missing"
    assert '"quoted"' in node.name and "<tagged>" in node.name, node.name
    assert tree.total == 5, "a broken escape would split the tag and invent a node"


def test_hyphenated_node_ids_resolve():
    """Figma URLs spell ids with a hyphen; the API answers with a colon."""
    assert parse(to_xml(PAYLOAD, "2751-1998")).total == 5


def test_nesting_and_depth_are_preserved():
    tree = parse(to_xml(PAYLOAD, "2751:1998"))
    assert tree.get("2751:2003").depth == 2
    assert tree.get("2894:2321").depth == 1
    assert tree.descendants("2751:2002") == {"2751:2003", "2751:2004"}


def test_the_classifier_reads_the_converted_tree_correctly():
    """End to end: the fallback must reach the same verdict the MCP path would."""
    kind, reason = parse(to_xml(PAYLOAD, "2751:1998")).classify()
    assert kind == "variant-set", (kind, reason)
    assert "1920" in reason


def test_a_missing_node_says_which_ones_came_back():
    try:
        to_xml(PAYLOAD, "9:9")
    except RuntimeError as exc:
        assert "2751:1998" in str(exc), "must name what was returned, to debug the id"
        return
    raise AssertionError("a missing node must raise, not return an empty tree")


def test_missing_token_is_setup_not_failure():
    assert NO_TOKEN == 3
    assert "file_content:read" in SETUP_HELP
    assert "never written to disk" in SETUP_HELP


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
