"""Checks for build / audit / reconcile detection.

Getting this wrong is expensive in opposite directions: rebuilding a finished
screen destroys working code, and auditing a half-built one silently skips
everything that was never written.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.mode import detect  # noqa: E402

TREE = """
<frame id="1:1" name="Screen" width="1440" height="900">
  <frame id="1:2" name="Header" width="1440" height="64" />
  <frame id="1:3" name="Body" width="1440" height="700" />
  <frame id="1:4" name="Card" width="400" height="200" />
  <frame id="1:5" name="Footer" width="1440" height="136" />
</frame>
"""


def _project(files: dict[str, str]) -> tuple[Path, Path]:
    d = Path(tempfile.mkdtemp())
    (d / "tree.xml").write_text(TREE)
    for name, body in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d, d / "tree.xml"


def test_empty_project_means_build():
    d, tree = _project({})
    r = detect(d, tree)
    assert r.mode == "build", r.report()


def test_fully_implemented_means_audit():
    d, tree = _project({
        "src/Screen.tsx": '<div data-node-id="1:1"><h1 data-node-id="1:2" /></div>',
        "src/Body.tsx": '<div data-node-id="1:3"><div data-node-id="1:4" /></div>',
        "src/Footer.tsx": '<footer data-node-id="1:5" />',
    })
    r = detect(d, tree)
    assert r.mode == "audit", r.report()
    assert len(r.matched) == 5


def test_half_implemented_means_reconcile():
    d, tree = _project({
        "src/Screen.tsx": '<div data-node-id="1:1"><h1 data-node-id="1:2" /></div>',
    })
    r = detect(d, tree)
    assert r.mode == "reconcile", r.report()
    assert "do not rewrite working code" in r.reason


def test_a_single_stray_reference_is_not_an_implementation():
    nodes = ['<frame id="9:0" name="Root" width="1440" height="900">']
    nodes += [f'<text id="9:{i}" name="t" width="10" height="10" />' for i in range(1, 60)]
    nodes.append("</frame>")
    d = Path(tempfile.mkdtemp())
    (d / "tree.xml").write_text("\n".join(nodes))
    (d / "stray.tsx").write_text('<div data-node-id="9:7" />')
    r = detect(d, d / "tree.xml")
    assert r.mode == "build", r.report()


def test_node_ids_from_a_different_design_do_not_count():
    d, tree = _project({"src/Other.tsx": '<div data-node-id="88:88" />'})
    r = detect(d, tree)
    assert r.matched == set()
    assert r.mode == "build"


def test_node_modules_and_build_output_are_ignored():
    d, tree = _project({
        "node_modules/pkg/x.tsx": '<div data-node-id="1:1" data-node-id="1:2" />',
        "dist/bundle.js": 'data-node-id="1:3"',
    })
    r = detect(d, tree)
    assert r.matched == set(), "vendored and generated code must not count as yours"
    assert r.mode == "build"


def test_absence_of_evidence_is_flagged_as_low_confidence():
    """Built-without-node-ids and never-built look identical. Say so."""
    d, tree = _project({"src/Screen.tsx": "<div className='screen'>hand written</div>"})
    r = detect(d, tree)
    assert r.mode == "build"
    assert not r.confident
    assert "look identical from here" in r.report()


def test_attribute_spellings_all_parse():
    d, tree = _project({
        "a.tsx": 'data-node-id="1:1"',
        "b.tsx": "data-node-id='1:2'",
        "c.tsx": 'data-node-id={"1:3"}',
        "d.html": 'data-node-id = "1:4"',
    })
    r = detect(d, tree)
    assert r.matched == {"1:1", "1:2", "1:3", "1:4"}, r.matched


def test_report_lists_the_files_to_look_at():
    d, tree = _project({"src/Screen.tsx": '<div data-node-id="1:1" />'})
    assert "src/Screen.tsx" in detect(d, tree).report()


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
