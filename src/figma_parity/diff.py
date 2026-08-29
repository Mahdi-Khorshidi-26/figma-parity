"""Pixel-diff a rendered UI against its Figma export.

This is the *objective measure* in the parity loop. The model does not get to
decide whether the implementation matches; this module does, and it reports
WHERE it differs so the next iteration has something concrete to fix.

CLI:
    python -m figma_parity.diff FIGMA.png RENDER.png [--out DIR] [--tol N] [--threshold PCT]

Exit code 0 = at or under threshold, 1 = over threshold (or size mismatch).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ModuleNotFoundError as exc:  # optional: only the pixel diff needs these
    raise SystemExit(
        f"figma-parity: the pixel diff needs {exc.name}.\n"
        f"  pip install pillow numpy\n"
        f"Everything else - tree walk, ledger, completion gate - works without "
        f"it; the skill falls back to ledger-only mode and says so."
    ) from exc

# --- Calibration knobs -------------------------------------------------------
# ponytail: these are knobs, not constants. Figma's rasterizer and a browser's
# never agree pixel-for-pixel on text, so a real implementation never reaches
# 0.00%. A loop that demands perfection never terminates. Tune per project.

TOL = 12
"""Per-channel 0-255 delta at or below which two pixels count as equal.
Absorbs antialiasing and font-hinting noise. Raise for text-heavy UIs."""

THRESHOLD_PCT = 0.5
"""Percentage of differing pixels at or below which a render passes."""

CELL = 16
"""Clustering grid size in pixels. Differing pixels are grouped into cells,
then adjacent cells merge into regions. Smaller = more, tighter regions."""

MIN_CELL_HITS = 4
"""A grid cell needs this many differing pixels to count as active. Kills
isolated speckle from subpixel rendering."""
# -----------------------------------------------------------------------------


@dataclass
class Region:
    """A rectangle of the image where the two inputs disagree."""

    x: int
    y: int
    w: int
    h: int
    pixels: int

    @property
    def density(self) -> float:
        """Fraction of the box that actually differs.

        This is what separates a *shift* from a *substitution*. A moved border
        or reflowed text fills its box sparsely (low density); a missing block
        or a recoloured panel fills it densely. Without this the two look
        identical in the report, and a global shift hides every smaller defect
        inside one enormous region.
        """
        area = self.w * self.h
        return self.pixels / area if area else 0.0

    @property
    def shape(self) -> str:
        if self.density >= 0.5:
            return "solid"      # a block differs outright — missing/extra/recoloured
        if self.density >= 0.15:
            return "partial"
        return "sparse"         # outlines/text moved — usually a layout shift

    def __str__(self) -> str:
        return (f"({self.x},{self.y}) {self.w}x{self.h} — {self.pixels} px "
                f"· {self.density:.0%} fill · {self.shape}")


@dataclass
class DiffResult:
    figma_size: tuple[int, int]
    render_size: tuple[int, int]
    size_mismatch: bool
    diff_pixels: int
    total_pixels: int
    regions: list[Region] = field(default_factory=list)
    heatmap_path: Path | None = None
    threshold_pct: float = THRESHOLD_PCT

    @property
    def pct(self) -> float:
        return 100.0 * self.diff_pixels / self.total_pixels if self.total_pixels else 0.0

    @property
    def passed(self) -> bool:
        # A size mismatch is a defect in its own right, never "close enough".
        return not self.size_mismatch and self.pct <= self.threshold_pct

    def report(self) -> str:
        lines = []
        verdict = "PASS" if self.passed else "FAIL"
        lines.append(f"{verdict}  {self.pct:.3f}% differing ({self.diff_pixels:,}/{self.total_pixels:,} px) "
                     f"· threshold {self.threshold_pct}%")
        if self.size_mismatch:
            lines.append(
                f"  ! SIZE MISMATCH: figma {self.figma_size[0]}x{self.figma_size[1]} "
                f"vs render {self.render_size[0]}x{self.render_size[1]} — fix this first, "
                f"the region list below is unreliable until sizes agree."
            )
        if not self.regions:
            lines.append("  no diff regions")
        else:
            lines.append(f"  {len(self.regions)} region(s), largest first:")
            for i, r in enumerate(self.regions, 1):
                lines.append(f"   {i:>2}. {r}")
            big = self.regions[0]
            if big.shape == "sparse" and big.w * big.h > 0.25 * self.total_pixels:
                lines.append(
                    "  NOTE: the largest region is sparse and covers much of the frame — "
                    "that is a global layout shift (padding/margin/size), not many separate "
                    "defects. Fix it and re-measure; smaller defects are currently hidden "
                    "inside it and will only surface once the shift is gone."
                )
        if self.heatmap_path:
            lines.append(f"  heatmap: {self.heatmap_path}")
        return "\n".join(lines)


def _load_rgb(path: str | Path) -> np.ndarray:
    """Load a PNG as HxWx3 uint8, flattening alpha onto white."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return np.asarray(img.convert("RGB"), dtype=np.uint8)


def _diff_mask(a: np.ndarray, b: np.ndarray, tol: int) -> np.ndarray:
    """Boolean HxW mask of differing pixels over the union of both canvases.

    Area covered by only one image counts as differing — a render that is
    short or narrow is missing content, not merely a different size.
    """
    ha, wa = a.shape[:2]
    hb, wb = b.shape[:2]
    h, w = max(ha, hb), max(wa, wb)
    ho, wo = min(ha, hb), min(wa, wb)

    mask = np.zeros((h, w), dtype=bool)
    delta = np.abs(a[:ho, :wo].astype(np.int16) - b[:ho, :wo].astype(np.int16)).max(axis=2)
    mask[:ho, :wo] = delta > tol
    mask[ho:, :] = True  # rows present in only one image
    mask[:, wo:] = True  # columns present in only one image
    return mask


def _clusters(mask: np.ndarray, cell: int, min_cell_hits: int) -> list[Region]:
    """Group differing pixels into rectangular regions, largest first.

    Downsamples to a coarse grid, flood-fills adjacent active cells
    (8-connectivity), then tightens each component's box to the actual
    differing pixels inside it.
    """
    h, w = mask.shape
    gh, gw = -(-h // cell), -(-w // cell)  # ceil division

    padded = np.zeros((gh * cell, gw * cell), dtype=bool)
    padded[:h, :w] = mask
    counts = padded.reshape(gh, cell, gw, cell).sum(axis=(1, 3))
    active = counts >= min_cell_hits

    regions: list[Region] = []
    seen = np.zeros_like(active)
    for sy in range(gh):
        for sx in range(gw):
            if not active[sy, sx] or seen[sy, sx]:
                continue
            # Iterative flood fill; recursion would blow the stack on big diffs.
            stack = [(sy, sx)]
            seen[sy, sx] = True
            cells = []
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < gh and 0 <= nx < gw and active[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))

            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            y0, y1 = min(ys) * cell, min((max(ys) + 1) * cell, h)
            x0, x1 = min(xs) * cell, min((max(xs) + 1) * cell, w)

            # Tighten the box to pixels that actually differ.
            sub = mask[y0:y1, x0:x1]
            rows = np.flatnonzero(sub.any(axis=1))
            cols = np.flatnonzero(sub.any(axis=0))
            if rows.size == 0 or cols.size == 0:
                continue
            ty0, ty1 = y0 + int(rows[0]), y0 + int(rows[-1]) + 1
            tx0, tx1 = x0 + int(cols[0]), x0 + int(cols[-1]) + 1
            regions.append(
                Region(x=tx0, y=ty0, w=tx1 - tx0, h=ty1 - ty0, pixels=int(sub.sum()))
            )

    regions.sort(key=lambda r: r.pixels, reverse=True)
    return regions


def _heatmap(base: np.ndarray, mask: np.ndarray, regions: list[Region], out: Path) -> Path:
    """Write a PNG: the render, faded, with differing pixels in red and
    numbered boxes around each region."""
    h, w = mask.shape
    canvas = np.full((h, w, 3), 255, dtype=np.uint8)
    bh, bw = base.shape[:2]
    canvas[:bh, :bw] = base
    canvas = (canvas.astype(np.uint16) + 255 * 2) // 3  # fade toward white
    canvas = canvas.astype(np.uint8)
    canvas[mask] = (255, 40, 40)

    img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(img)
    for i, r in enumerate(regions, 1):
        draw.rectangle([r.x, r.y, r.x + r.w - 1, r.y + r.h - 1], outline=(0, 90, 255), width=2)
        draw.text((r.x + 3, max(0, r.y - 12)), str(i), fill=(0, 90, 255))

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def compare(
    figma_png: str | Path,
    render_png: str | Path,
    out_dir: str | Path | None = None,
    tol: int = TOL,
    threshold_pct: float = THRESHOLD_PCT,
    cell: int = CELL,
    min_cell_hits: int = MIN_CELL_HITS,
) -> DiffResult:
    """Compare a Figma export against a rendered screenshot."""
    a = _load_rgb(figma_png)
    b = _load_rgb(render_png)

    mask = _diff_mask(a, b, tol)
    regions = _clusters(mask, cell, min_cell_hits)

    heatmap_path = None
    if out_dir is not None:
        heatmap_path = _heatmap(b, mask, regions, Path(out_dir) / "heatmap.png")

    return DiffResult(
        figma_size=(a.shape[1], a.shape[0]),
        render_size=(b.shape[1], b.shape[0]),
        size_mismatch=a.shape[:2] != b.shape[:2],
        diff_pixels=int(mask.sum()),
        total_pixels=int(mask.size),
        regions=regions,
        heatmap_path=heatmap_path,
        threshold_pct=threshold_pct,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pixel-diff a render against a Figma export.")
    p.add_argument("figma", help="PNG exported from Figma")
    p.add_argument("render", help="PNG screenshot of the implemented UI")
    p.add_argument("--out", help="directory to write heatmap.png into")
    p.add_argument("--tol", type=int, default=TOL, help=f"per-channel tolerance (default {TOL})")
    p.add_argument("--threshold", type=float, default=THRESHOLD_PCT,
                   help=f"pass threshold in %% (default {THRESHOLD_PCT})")
    args = p.parse_args(argv)

    result = compare(args.figma, args.render, out_dir=args.out,
                     tol=args.tol, threshold_pct=args.threshold)
    print(result.report())
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
