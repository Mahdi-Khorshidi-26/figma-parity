"""Checks for the parity loop's objective measure.

No framework — run directly:  python tests/test_diff.py
If diff.py can be fooled, every conclusion built on it is worthless, so these
cover the cases that actually matter: a planted defect must be found, and
antialiasing noise must NOT be reported as one.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from figma_parity.diff import TOL, compare  # noqa: E402


def _png(path, arr):
    Image.fromarray(arr.astype("uint8")).save(path)


def _blank(h=200, w=300, value=250):
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_identical_images_report_nothing():
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.png"
        b = Path(d) / "b.png"
        _png(a, _blank())
        _png(b, _blank())
        r = compare(a, b)
        assert r.diff_pixels == 0, r.diff_pixels
        assert r.regions == [], r.regions
        assert r.pct == 0.0
        assert r.passed
        assert not r.size_mismatch


def test_planted_square_is_found_with_correct_box():
    """The seeded-defect case: paint a 20x20 block and demand it be located."""
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.png"
        b = Path(d) / "b.png"
        base = _blank()
        _png(a, base)
        broken = base.copy()
        broken[40:60, 30:50] = (255, 0, 0)
        _png(b, broken)

        r = compare(a, b)
        assert len(r.regions) == 1, f"expected 1 region, got {len(r.regions)}"
        reg = r.regions[0]
        assert (reg.x, reg.y, reg.w, reg.h) == (30, 40, 20, 20), reg
        assert reg.pixels == 400, reg.pixels
        assert not r.passed, "a 400px block must not pass"


def test_subtolerance_noise_is_ignored():
    """Font rasterization differs everywhere by a little. That is not a defect."""
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.png"
        b = Path(d) / "b.png"
        base = _blank(value=128)
        _png(a, base)
        rng = np.random.default_rng(0)
        noise = rng.integers(-(TOL - 2), TOL - 1, size=base.shape)
        _png(b, np.clip(base.astype(int) + noise, 0, 255))

        r = compare(a, b)
        assert r.diff_pixels == 0, f"sub-tolerance noise leaked through: {r.diff_pixels}px"
        assert r.regions == []
        assert r.passed


def test_size_mismatch_is_a_defect_not_a_resize():
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.png"
        b = Path(d) / "b.png"
        _png(a, _blank(h=200, w=300))
        _png(b, _blank(h=180, w=300))  # render 20px short

        r = compare(a, b)
        assert r.size_mismatch
        assert not r.passed, "a short render must never pass"
        assert r.diff_pixels == 20 * 300, r.diff_pixels
        assert r.regions, "the missing band must surface as a region"


def test_regions_sorted_largest_first():
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.png"
        b = Path(d) / "b.png"
        base = _blank()
        _png(a, base)
        broken = base.copy()
        broken[10:20, 10:20] = (0, 0, 0)      # small, 100px
        broken[100:140, 100:180] = (0, 0, 0)  # large, 3200px
        _png(b, broken)

        r = compare(a, b)
        assert len(r.regions) == 2, [str(x) for x in r.regions]
        assert r.regions[0].pixels == 3200, r.regions[0]
        assert r.regions[1].pixels == 100, r.regions[1]


def test_heatmap_is_written():
    with tempfile.TemporaryDirectory() as d:
        a = Path(d) / "a.png"
        b = Path(d) / "b.png"
        base = _blank()
        _png(a, base)
        broken = base.copy()
        broken[40:60, 30:50] = (255, 0, 0)
        _png(b, broken)

        r = compare(a, b, out_dir=d)
        assert r.heatmap_path and r.heatmap_path.exists()


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
