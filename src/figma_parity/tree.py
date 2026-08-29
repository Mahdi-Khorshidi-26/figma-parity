"""Parse a saved Figma `get_metadata` response into a node tree.

This module exists to remove the model from the coverage calculation.

Before it, the completion gate read a `Coverage: nodes 572/572` line that the
*model itself wrote* — the gate was checking a claim against nothing. A model
that walked five nodes could write 572/572 and the gate would pass it.

Now the agent saves the raw `get_metadata` output to disk and this module
counts the nodes in that file. Coverage becomes a fact Python derives from the
design, cross-referenced against the node ids that actually appear in the
ledger. The model can no longer inflate its own score.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)\b([^>]*?)(/?)>")
NODE_ID_RE = re.compile(r"\b\d+:\d+\b")

# A frame this much taller than it is wide is a specification sheet or a long
# scrolling document, not a screen. Real screens sit well under this.
_DOCUMENT_ASPECT = 5.0

# A ledger entry covers its whole subtree only when that subtree is small
# enough to have been ONE real extraction call. Above this, naming the node
# covers only the node itself.
#
# Without this cap the gate is trivially defeated: write the root node id in
# the ledger and every descendant counts as covered — which is absurd, because
# the root is precisely the node too large to extract. That is the failure this
# project exists to catch, so it must not be re-introduced by the checker.
MAX_UNIT_NODES = 40

# At or above this width a frame is viewport-sized, so it is a screen however
# few nodes it happens to contain. Node count alone misclassifies a sparse
# 1440px layout as a "component".
_SCREEN_MIN_WIDTH = 1024.0


@dataclass
class Node:
    id: str
    tag: str
    name: str
    width: float
    height: float
    depth: int
    parent: str | None
    ancestors: tuple[str, ...]


@dataclass
class Tree:
    nodes: list[Node] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._by_id = {n.id: n for n in self.nodes}
        self._children: dict[str, list[str]] = {}
        for n in self.nodes:
            if n.parent:
                self._children.setdefault(n.parent, []).append(n.id)

    @property
    def total(self) -> int:
        return len(self.nodes)

    @property
    def node_ids(self) -> set[str]:
        return set(self._by_id)

    @property
    def max_depth(self) -> int:
        return max((n.depth for n in self.nodes), default=0)

    @property
    def types(self) -> Counter:
        return Counter(n.tag for n in self.nodes)

    @property
    def root(self) -> Node | None:
        return self.nodes[0] if self.nodes else None

    def get(self, node_id: str) -> Node | None:
        return self._by_id.get(node_id)

    def descendants(self, node_id: str) -> set[str]:
        out: set[str] = set()
        stack = list(self._children.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in out:
                continue
            out.add(current)
            stack.extend(self._children.get(current, []))
        return out

    @property
    def instances(self) -> list[Node]:
        return [n for n in self.nodes if n.tag == "instance"]

    @property
    def unique_components(self) -> dict[str, list[str]]:
        """Component name -> every instance id carrying that name."""
        out: dict[str, list[str]] = {}
        for n in self.instances:
            out.setdefault(n.name, []).append(n.id)
        return out

    def covered_by(self, ledger_ids: set[str]) -> set[str]:
        """Nodes accounted for, given the node ids that appear in the ledger.

        Implements the skill's dedup rule honestly: extracting a node covers its
        subtree, and extracting one instance of a component covers every other
        instance of that component (and their subtrees). Everything else must be
        named in the ledger explicitly.
        """
        covered: set[str] = set()
        for node_id in ledger_ids & self.node_ids:
            covered.add(node_id)
            kids = self.descendants(node_id)
            # Only a plausibly-extractable subtree is covered wholesale.
            if len(kids) <= MAX_UNIT_NODES:
                covered |= kids

        # One extracted instance stands in for its siblings — but again only
        # when that component is small enough to have been extracted at once.
        covered_names = {n.name for n in self.instances if n.id in covered}
        for name in covered_names:
            for inst_id in self.unique_components.get(name, []):
                kids = self.descendants(inst_id)
                if len(kids) <= MAX_UNIT_NODES:
                    covered.add(inst_id)
                    covered |= kids
        return covered

    def classify(self) -> tuple[str, str]:
        """Guess what this node actually is, and say why.

        Kinds: 'component', 'screen', 'document', 'breakpoint-set', 'unknown'.
        This exists because the loop previously treated a 4169x31764px
        specification sheet as a screen and "implemented" a wall of prose.
        """
        root = self.root
        if root is None:
            return "unknown", "empty tree"

        w, h = root.width, root.height
        top = [n for n in self.nodes if n.parent == root.id]

        if w > 0 and h / w >= _DOCUMENT_ASPECT:
            return (
                "document",
                f"root is {w:.0f}x{h:.0f} — {h / w:.0f}x taller than wide, so this is a "
                f"specification sheet or long scrolling document, not a screen",
            )

        frame_kids = [n for n in top if n.tag in ("frame", "instance")]
        if len(frame_kids) >= 2:
            widths = sorted((n.width for n in frame_kids), reverse=True)
            names = {n.name for n in frame_kids}
            if len(names) <= 2 and widths[0] > 0 and widths[-1] / widths[0] < 0.75:
                return (
                    "breakpoint-set",
                    f"{len(frame_kids)} sibling frames sharing a name at descending widths "
                    f"({', '.join(f'{x:.0f}' for x in widths)}) — responsive variants of one "
                    f"screen, not separate screens",
                )

        if w >= _SCREEN_MIN_WIDTH:
            return "screen", f"{self.total} nodes at {w:.0f}x{h:.0f} — viewport-width frame"
        if self.total <= 30:
            return "component", f"{self.total} nodes, {w:.0f}x{h:.0f} — a single component"
        return "screen", f"{self.total} nodes, {w:.0f}x{h:.0f}"


def parse(source: str | Path) -> Tree:
    """Parse saved get_metadata XML. Accepts a path or the raw text."""
    text = str(source)
    path = Path(text) if len(text) < 4096 else None
    if path is not None and path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")

    nodes: list[Node] = []
    stack: list[str] = []
    for m in _TAG_RE.finditer(text):
        closing, tag, attrs, self_closing = m.groups()
        if closing:
            if stack:
                stack.pop()
            continue
        found_id = re.search(r'\bid="([^"]*)"', attrs)
        if not found_id:
            continue
        node_id = found_id.group(1)
        found_name = re.search(r'\bname="([^"]*)"', attrs)
        name = html.unescape(found_name.group(1)) if found_name else ""

        def _num(key: str) -> float:
            found = re.search(rf'\b{key}="([-\d.]+)"', attrs)
            return float(found.group(1)) if found else 0.0

        nodes.append(
            Node(
                id=node_id,
                tag=tag,
                name=name,
                width=_num("width"),
                height=_num("height"),
                depth=len(stack),
                parent=stack[-1] if stack else None,
                ancestors=tuple(stack),
            )
        )
        if not self_closing:
            stack.append(node_id)
    return Tree(nodes=nodes)


def ledger_node_ids(ledger_text: str) -> set[str]:
    """Every Figma node id mentioned anywhere in a ledger."""
    return set(NODE_ID_RE.findall(ledger_text))
