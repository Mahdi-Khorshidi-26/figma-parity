"""Read Figma comments — the pin threads people leave on a design.

Comments are not part of the document tree, so no MCP tool returns them and
`get_design_context` never sees them. They live only behind Figma's REST API,
which needs a token. That makes this the one optional, opt-in piece of the
plugin: without `FIGMA_TOKEN` set, everything else still works and the skill
reports that comments were not read rather than implying there were none.

Why bother: a comment is often the only place a constraint exists. "This is the
disabled state", "copy is placeholder", "8px not 12, we changed this" — none of
that is in the geometry, and a pixel diff can never recover it.

Stdlib only, read-only, and the token is never logged or written to disk.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API = "https://api.figma.com/v1/files/{file_key}/comments"
TOKEN_VARS = ("FIGMA_TOKEN", "FIGMA_ACCESS_TOKEN", "FIGMA_PERSONAL_ACCESS_TOKEN")

NO_TOKEN = 3
"""Distinct exit code: not configured, which is not the same as failed."""

SETUP_HELP = """\
No Figma token found, so comments were not read.

Comments are the one thing the Figma MCP cannot reach — they live outside the
document tree, behind Figma's REST API. Everything else in figma-parity works
without this.

To enable them, create a read-only token:
  Figma -> Settings -> Security -> Personal access tokens -> Generate new token
  Give it the `file_comments:read` scope. Nothing else is needed.

Then export it before running:
  export FIGMA_TOKEN=figd_...

The token is read from the environment, never written to disk and never logged.
"""


@dataclass
class Comment:
    id: str
    message: str
    author: str
    created_at: str
    node_id: str | None
    resolved: bool
    parent_id: str

    @property
    def is_reply(self) -> bool:
        return bool(self.parent_id)


@dataclass
class CommentSet:
    comments: list[Comment] = field(default_factory=list)

    def unresolved(self) -> list[Comment]:
        return [c for c in self.comments if not c.resolved]

    def for_nodes(self, node_ids: set[str], include_resolved: bool = False) -> list[Comment]:
        """Comments pinned to one of these nodes.

        A comment pinned to the canvas rather than a layer has no node_id; those
        are returned too, because a floating note about the screen is still a
        requirement — it just cannot be attributed to a row.
        """
        pool = self.comments if include_resolved else self.unresolved()
        return [c for c in pool if c.node_id is None or c.node_id in node_ids]

    def threads(self) -> dict[str, list[Comment]]:
        """Root comment id -> its replies, in order."""
        out: dict[str, list[Comment]] = {c.id: [] for c in self.comments if not c.is_reply}
        for c in self.comments:
            if c.is_reply and c.parent_id in out:
                out[c.parent_id].append(c)
        return out


def token_from_env() -> str | None:
    for name in TOKEN_VARS:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _parse(payload: dict[str, Any]) -> CommentSet:
    out: list[Comment] = []
    for raw in payload.get("comments", []) or []:
        meta = raw.get("client_meta") or {}
        # A layer-pinned comment carries node_id; a canvas-pinned one is just x/y.
        node_id = meta.get("node_id") if isinstance(meta, dict) else None
        out.append(
            Comment(
                id=str(raw.get("id", "")),
                message=(raw.get("message") or "").strip(),
                author=((raw.get("user") or {}).get("handle") or "unknown"),
                created_at=(raw.get("created_at") or "")[:10],
                node_id=str(node_id) if node_id else None,
                resolved=bool(raw.get("resolved_at")),
                parent_id=str(raw.get("parent_id") or ""),
            )
        )
    return CommentSet(comments=out)


def fetch(file_key: str, token: str | None = None, timeout: float = 20.0) -> CommentSet:
    """Fetch every comment on a file. Raises RuntimeError with a readable cause."""
    token = token or token_from_env()
    if not token:
        raise PermissionError(SETUP_HELP)

    request = urllib.request.Request(
        API.format(file_key=file_key),
        headers={"X-Figma-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _parse(json.load(response))
    except urllib.error.HTTPError as exc:
        # Never echo the token, and never echo the body verbatim — it can be long.
        if exc.code in (401, 403):
            raise RuntimeError(
                "Figma rejected the token (HTTP %d). Check it has not expired and "
                "carries the `file_comments:read` scope." % exc.code
            ) from exc
        if exc.code == 404:
            raise RuntimeError(
                "Figma returned 404 for that file key — either it does not exist, "
                "or this token's account cannot open it."
            ) from exc
        raise RuntimeError(f"Figma returned HTTP {exc.code} fetching comments.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach api.figma.com: {exc.reason}") from exc


def to_markdown(comments: CommentSet, node_ids: set[str] | None = None) -> str:
    """Ledger-ready rows. Every comment starts open — someone wrote it on purpose."""
    selected = (
        comments.for_nodes(node_ids) if node_ids is not None else comments.unresolved()
    )
    if not selected:
        total = len(comments.comments)
        if total:
            return (
                f"## Comments\n\nNone open. ({total} comment(s) on the file, all "
                f"resolved or outside this node.)\n"
            )
        return "## Comments\n\nNone on this file.\n"

    replies = comments.threads()
    lines = [
        "## Comments",
        "",
        "Pinned discussion from the Figma file. Each is a requirement until shown "
        "otherwise — resolve it in the design, or record why it does not apply.",
        "",
        "| node | author | comment | status | note |",
        "|---|---|---|---|---|",
    ]
    for c in selected:
        if c.is_reply:
            continue
        text = c.message.replace("|", "\\|").replace("\n", " ")
        follow = replies.get(c.id, [])
        if follow:
            text += f"  _({len(follow)} repl{'y' if len(follow) == 1 else 'ies'})_"
        lines.append(f"| {c.node_id or '(canvas)'} | {c.author} | {text} | ☐ | |")
    return "\n".join(lines) + "\n"
