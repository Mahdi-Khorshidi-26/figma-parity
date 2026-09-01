"""Compare what the browser actually rendered against what the design specified.

The pixel diff is the wrong instrument for spacing and sizing. A 4px padding
change moves every border on the screen, merges into one enormous sparse region
and tells you "something shifted" — which is useless for "is this gap 12 or 16".
And in ledger-only mode there is no pixel diff at all, so nothing measures the
built UI whatsoever: the model ends up comparing Figma's number against the code
it just wrote, which is not a check, it is a memory test.

This module closes that. The browser can report the computed value of any
property on any element — `padding-top: 12px`, exactly, no rasterizer involved.
Compare that number to the ledger's expected number and a spacing bug is an
arithmetic fact rather than a judgement call.

Inputs:
  - the ledger, which already carries `| node | prop | expected | status | note |`
  - a JSON dump of computed styles keyed by node id, produced by running
    `browser_snippet()` in the page (elements carry `data-node-id`)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# How far a rendered length may sit from the specified one and still pass.
# Sub-pixel layout and rounding produce fractions; a real spacing bug does not
# hide inside half a pixel. ponytail: a knob, not a truth.
LENGTH_TOLERANCE_PX = 0.5

_LENGTH = re.compile(r"^(-?\d+(?:\.\d+)?)\s*px$", re.I)
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", re.I)
_RGB = re.compile(r"^rgba?\(([^)]+)\)$", re.I)
_NODE_ID = re.compile(r"^\d+:\d+$")

# Ledger rows are written in design vocabulary; the browser answers in CSS.
# Anything not listed here is compared under its own name.
ALIASES = {
    "font size": "font-size",
    "font weight": "font-weight",
    "line height": "line-height",
    "letter spacing": "letter-spacing",
    "text color": "color",
    "text colour": "color",
    "fill": "background-color",
    "background": "background-color",
    "bg": "background-color",
    "radius": "border-radius",
    "corner radius": "border-radius",
    "padding-y": "padding-top",
    "padding-x": "padding-left",
    "padding y": "padding-top",
    "padding x": "padding-left",
    "gap": "gap",
    "width": "width",
    "height": "height",
}

# Properties worth dumping. Keeping this tight keeps the JSON small and the
# comparison meaningful — computed style has hundreds of entries, nearly all noise.
MEASURED_PROPERTIES = [
    "width", "height",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "gap", "row-gap", "column-gap",
    "font-family", "font-size", "font-weight", "line-height", "letter-spacing",
    "color", "background-color",
    "border-radius", "border-top-width", "border-color",
    "display", "flex-direction", "align-items", "justify-content",
    "opacity", "text-transform", "text-align",
]


def canonical_property(name: str) -> str:
    key = name.strip().lower()
    return ALIASES.get(key, key)


def _as_length(value: str) -> float | None:
    m = _LENGTH.match(value.strip())
    return float(m.group(1)) if m else None


def _as_rgb(value: str) -> tuple[int, int, int] | None:
    v = value.strip()
    m = _HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    m = _RGB.match(v)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", " ").split(",")]
        if len(parts) == 1:
            parts = m.group(1).split()
        try:
            return tuple(int(round(float(p))) for p in parts[:3])  # type: ignore[return-value]
        except ValueError:
            return None
    return None


def values_match(expected: str, actual: str) -> bool:
    """Compare a design value to a rendered one, in whichever way is meaningful."""
    e, a = expected.strip(), actual.strip()
    if not e or not a:
        return False
    if e.lower() == a.lower():
        return True

    # A ledger value often carries a token name alongside the raw value:
    # "var(--color-charcoal) #433B3F". Any token in it is not the browser's answer.
    for candidate in re.findall(r"#[0-9a-fA-F]{3,6}|rgba?\([^)]*\)", e) or [e]:
        ec, ac = _as_rgb(candidate), _as_rgb(a)
        if ec and ac:
            return ec == ac

    # Same story for lengths: "var(--s-600) 24px" must still compare as 24px.
    al = _as_length(a)
    if al is not None:
        el = _as_length(e)
        if el is None:
            found = re.search(r"(-?\d+(?:\.\d+)?)\s*px\b", e, re.I)
            el = float(found.group(1)) if found else None
        if el is not None:
            return abs(el - al) <= LENGTH_TOLERANCE_PX

    if _NUMBER.match(e) and _NUMBER.match(a):
        return abs(float(e) - float(a)) <= 1e-6

    # A unitless line-height against a px one is only comparable with the font
    # size, which we do not have here; treat as unknown rather than a false fail.
    return False


@dataclass
class Mismatch:
    node: str
    prop: str
    expected: str
    actual: str
    line_no: int

    def __str__(self) -> str:
        return f"{self.node}  {self.prop}: expected {self.expected!r}, rendered {self.actual!r}"


@dataclass
class MeasureResult:
    checked: int = 0
    matched: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)
    unmeasured: list[tuple[str, str]] = field(default_factory=list)
    missing_nodes: set[str] = field(default_factory=set)

    @property
    def passed(self) -> bool:
        return not self.mismatches

    def report(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        lines = [
            f"{verdict}  {self.matched}/{self.checked} measured values match "
            f"({len(self.mismatches)} mismatch(es))"
        ]
        if self.mismatches:
            lines.append("")
            by_node: dict[str, list[Mismatch]] = {}
            for m in self.mismatches:
                by_node.setdefault(m.node, []).append(m)
            for node, items in by_node.items():
                lines.append(f"  {node}")
                for m in items:
                    lines.append(
                        f"    {m.prop}: design says {m.expected}, browser rendered "
                        f"{m.actual}   (ledger line {m.line_no})"
                    )
        if self.missing_nodes:
            lines.append("")
            lines.append(
                f"  {len(self.missing_nodes)} node(s) in the ledger were not found in the "
                f"page. Add data-node-id to the elements you built, or they cannot be "
                f"measured: " + ", ".join(sorted(self.missing_nodes)[:8])
            )
        if self.unmeasured:
            lines.append("")
            lines.append(
                f"  {len(self.unmeasured)} row(s) had no comparable rendered value "
                f"(not a CSS property, or not in the dump)."
            )
        return "\n".join(lines)


def parse_expected(ledger_text: str) -> list[tuple[int, str, str, str]]:
    """(line_no, node_id, property, expected) for every ledger row carrying a node id."""
    out: list[tuple[int, str, str, str]] = []
    for line_no, line in enumerate(ledger_text.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", s)[1:-1]]
        if len(cells) < 3 or not _NODE_ID.match(cells[0]):
            continue
        node, prop, expected = cells[0], cells[1], cells[2]
        if not prop or not expected or prop.lower() in ("prop", "property"):
            continue
        out.append((line_no, node, canonical_property(prop), expected))
    return out


def compare(ledger_path: str | Path, actual_path: str | Path) -> MeasureResult:
    ledger_text = Path(ledger_path).read_text(encoding="utf-8")
    actual: dict[str, dict[str, str]] = json.loads(Path(actual_path).read_text())
    actual = {k: {canonical_property(p): v for p, v in style.items()} for k, style in actual.items()}

    result = MeasureResult()
    for line_no, node, prop, expected in parse_expected(ledger_text):
        style = actual.get(node)
        if style is None:
            result.missing_nodes.add(node)
            continue
        rendered = style.get(prop)
        if rendered is None:
            result.unmeasured.append((node, prop))
            continue
        result.checked += 1
        if values_match(expected, rendered):
            result.matched += 1
        else:
            result.mismatches.append(Mismatch(node, prop, expected, rendered, line_no))
    return result


def browser_snippet(properties: list[str] | None = None) -> str:
    """JS to run in the page. Dumps computed styles keyed by data-node-id."""
    props = json.dumps(properties or MEASURED_PROPERTIES)
    return (
        "(() => {\n"
        f"  const PROPS = {props};\n"
        "  const out = {};\n"
        "  for (const el of document.querySelectorAll('[data-node-id]')) {\n"
        "    const id = el.getAttribute('data-node-id');\n"
        "    if (!id || out[id]) continue;\n"
        "    const cs = getComputedStyle(el);\n"
        "    const box = el.getBoundingClientRect();\n"
        "    const style = {};\n"
        "    for (const p of PROPS) style[p] = cs.getPropertyValue(p).trim();\n"
        "    style.width = box.width.toFixed(2) + 'px';\n"
        "    style.height = box.height.toFixed(2) + 'px';\n"
        "    out[id] = style;\n"
        "  }\n"
        "  return JSON.stringify(out, null, 1);\n"
        "})()"
    )
