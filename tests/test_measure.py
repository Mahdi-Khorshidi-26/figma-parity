"""Checks for measured-value comparison.

This is the instrument for "is that gap 12 or 16", so the tests that matter are
the ones proving a small spacing error is caught and that unit/colour spelling
differences are not reported as errors.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.measure import (  # noqa: E402
    LENGTH_TOLERANCE_PX,
    browser_snippet,
    canonical_property,
    compare,
    parse_expected,
    values_match,
)

LEDGER = """\
Coverage: nodes 3/3

| node | prop | expected | status | note |
|---|---|---|---|---|
| 1:2 | padding-top | 16px | ☑ | |
| 1:2 | gap | 12px | ☑ | |
| 1:2 | color | var(--color-charcoal) #433B3F | ☑ | |
| 1:2 | font-size | 18px | ☑ | |
| 1:3 | height | 64px | ☑ | |
"""


def _run(actual: dict) -> "object":
    d = Path(tempfile.mkdtemp())
    (d / "ledger.md").write_text(LEDGER, encoding="utf-8")
    (d / "actual.json").write_text(json.dumps(actual))
    return compare(d / "ledger.md", d / "actual.json")


def test_a_four_pixel_spacing_error_is_caught():
    """The exact complaint: a design is built, a gap is wrong, nothing notices."""
    r = _run({
        "1:2": {"padding-top": "16px", "gap": "8px", "color": "rgb(67, 59, 63)",
                "font-size": "18px"},
        "1:3": {"height": "64px"},
    })
    assert not r.passed
    assert len(r.mismatches) == 1, [str(m) for m in r.mismatches]
    m = r.mismatches[0]
    assert (m.node, m.prop, m.expected, m.actual) == ("1:2", "gap", "12px", "8px")
    assert m.line_no == 6, "must point at the ledger line so it can be fixed"


def test_everything_correct_passes():
    r = _run({
        "1:2": {"padding-top": "16px", "gap": "12px", "color": "rgb(67, 59, 63)",
                "font-size": "18px"},
        "1:3": {"height": "64px"},
    })
    assert r.passed, r.report()
    assert r.checked == 5 and r.matched == 5


def test_hex_and_rgb_are_the_same_colour():
    assert values_match("#433B3F", "rgb(67, 59, 63)")
    assert values_match("#FFF", "rgb(255, 255, 255)")
    assert values_match("var(--color-charcoal) #433B3F", "rgb(67, 59, 63)")
    assert not values_match("#433B3F", "rgb(255, 0, 0)")


def test_rgba_and_spaced_syntax_parse():
    assert values_match("#433B3F", "rgba(67, 59, 63, 1)")
    assert values_match("#433B3F", "rgb(67 59 63 / 1)")


def test_subpixel_rounding_is_not_a_bug():
    assert values_match("64px", "64.00px")
    assert values_match("64px", f"{64 + LENGTH_TOLERANCE_PX / 2:.2f}px")
    assert not values_match("64px", "66px"), "2px is a real error, not rounding"


def test_a_token_name_does_not_defeat_the_comparison():
    """Ledger rows record both token and raw value; the browser reports neither."""
    assert values_match("var(--s-600) 24px", "24px")


def test_missing_data_node_id_is_reported_not_silently_passed():
    r = _run({"1:2": {"padding-top": "16px", "gap": "12px",
                      "color": "rgb(67, 59, 63)", "font-size": "18px"}})
    assert "1:3" in r.missing_nodes
    assert "data-node-id" in r.report()


def test_property_not_in_the_dump_is_unmeasured_not_a_failure():
    r = _run({"1:2": {"padding-top": "16px"}, "1:3": {"height": "64px"}})
    assert r.passed, "absent measurements must not be reported as mismatches"
    assert len(r.unmeasured) == 3


def test_design_vocabulary_maps_to_css():
    assert canonical_property("Font Size") == "font-size"
    assert canonical_property("padding-y") == "padding-top"
    assert canonical_property("radius") == "border-radius"
    assert canonical_property("Fill") == "background-color"


def test_only_rows_with_a_real_node_id_are_measured():
    rows = parse_expected(LEDGER)
    assert len(rows) == 5
    assert all(":" in node for _, node, _, _ in rows)
    # header and separator rows must not be mistaken for data
    assert not parse_expected("| node | prop | expected |\n|---|---|---|\n")


def test_browser_snippet_is_valid_shape():
    js = browser_snippet()
    assert "data-node-id" in js
    assert "getComputedStyle" in js
    assert "padding-top" in js
    assert js.strip().startswith("(()") and js.strip().endswith(")()")


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
