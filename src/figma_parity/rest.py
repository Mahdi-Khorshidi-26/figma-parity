"""Fetch a node tree from Figma's REST API, as a fallback for get_metadata.

`get_metadata` is a single point of failure. Everything in Phase 1 depends on
having the child node ids, and when that call fails there is no way to guess
them — frame ids in a real file are non-sequential, so the descent simply
cannot start.

That is not hypothetical. A tester hit it on a large section: the MCP response
truncated at the same byte offset on four consecutive attempts, while a sibling
node of similar size returned cleanly. Per-node, deterministic, and fatal — the
run stopped at Phase 0 with nothing to show.

This module is the way out. The REST API returns the same tree as plain JSON
with no streaming layer to truncate, and it emits the identical XML shape
`tree.py` already parses, so every downstream step — classify, mode, coverage —
works unchanged. It needs the same read-only FIGMA_TOKEN that comments.py uses.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .comments import NO_TOKEN, TOKEN_VARS, token_from_env  # noqa: F401  (re-exported)

API = "https://api.figma.com/v1/files/{file_key}/nodes"

SETUP_HELP = """\
No Figma token found, so the REST fallback is unavailable.

This is only needed when get_metadata fails — usually a truncated response on a
large node. A read-only token lets the tree be fetched a second way:

  Figma -> Settings -> Security -> Personal access tokens -> Generate new token
  Scope: file_content:read  (file_comments:read too, if you also want comments)

  export FIGMA_TOKEN=figd_...

The token is read from the environment, never written to disk and never logged.
"""

# Figma node types -> the tag names get_metadata uses, so both paths produce
# trees that classify() and covered_by() treat identically.
TYPE_TAGS = {
    "FRAME": "frame",
    "GROUP": "frame",
    "SECTION": "section",
    "CANVAS": "canvas",
    "DOCUMENT": "document",
    "TEXT": "text",
    "INSTANCE": "instance",
    "COMPONENT": "symbol",
    "COMPONENT_SET": "symbol",
    "RECTANGLE": "rectangle",
    "ROUNDED_RECTANGLE": "rounded-rectangle",
    "VECTOR": "vector",
    "ELLIPSE": "ellipse",
    "LINE": "vector",
    "POLYGON": "vector",
    "STAR": "vector",
    "BOOLEAN_OPERATION": "vector",
    "SLICE": "slice",
}


def _tag(node_type: str) -> str:
    return TYPE_TAGS.get(node_type.upper(), node_type.lower().replace("_", "-"))


def _attr(value: str) -> str:
    """Quote an attribute value, always with double quotes.

    Not `xml.sax.saxutils.quoteattr`. That switches to *single* quotes when the
    value contains a double quote — perfectly valid XML, but `tree.py` reads
    names with `name="([^"]*)"`, which only matches the double-quoted form. A
    layer called `Say "hello" now` would therefore parse with an empty name.

    An empty name is not a cosmetic loss: component dedup groups instances by
    name, so every affected instance collapses into one bucket and coverage is
    silently wrong. Escaping the quote instead keeps one spelling, always
    matchable.
    """
    escaped = (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'"{escaped}"'


def fetch_nodes(
    file_key: str,
    node_id: str,
    depth: int | None = None,
    token: str | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Raw REST response for one node subtree."""
    token = token or token_from_env()
    if not token:
        raise PermissionError(SETUP_HELP)

    params = {"ids": node_id}
    if depth is not None:
        params["depth"] = str(depth)
    url = f"{API.format(file_key=file_key)}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"X-Figma-Token": token, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                f"Figma rejected the token (HTTP {exc.code}). Check it has not expired "
                f"and carries the `file_content:read` scope."
            ) from exc
        if exc.code == 404:
            raise RuntimeError(
                "Figma returned 404 — the file key is wrong, or this token's account "
                "cannot open that file."
            ) from exc
        raise RuntimeError(f"Figma returned HTTP {exc.code} fetching the tree.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach api.figma.com: {exc.reason}") from exc


def to_xml(payload: dict[str, Any], node_id: str) -> str:
    """Convert a REST node payload into the XML shape get_metadata returns."""
    nodes = payload.get("nodes") or {}
    # Figma accepts "1-2" and answers with "1:2"; accept either spelling back.
    entry = nodes.get(node_id) or nodes.get(node_id.replace("-", ":")) or {}
    document = entry.get("document")
    if not document:
        available = ", ".join(sorted(nodes)) or "none"
        raise RuntimeError(
            f"No document returned for node {node_id}. Nodes present: {available}"
        )

    lines: list[str] = []

    def walk(node: dict[str, Any], depth: int) -> None:
        tag = _tag(node.get("type", ""))
        box = node.get("absoluteBoundingBox") or {}
        attrs = [
            f"id={_attr(node.get('id', ''))}",
            f"name={_attr(node.get('name', ''))}",
        ]
        for key, attr in (("x", "x"), ("y", "y"), ("width", "width"), ("height", "height")):
            value = box.get(key)
            if value is not None:
                attrs.append(f'{attr}="{value:g}"')
        pad = "  " * depth
        children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
        if children:
            lines.append(f"{pad}<{tag} {' '.join(attrs)}>")
            for child in children:
                walk(child, depth + 1)
            lines.append(f"{pad}</{tag}>")
        else:
            lines.append(f"{pad}<{tag} {' '.join(attrs)} />")

    walk(document, 0)
    return "\n".join(lines) + "\n"


def fetch_tree_xml(
    file_key: str, node_id: str, depth: int | None = None, token: str | None = None
) -> str:
    return to_xml(fetch_nodes(file_key, node_id, depth=depth, token=token), node_id)
