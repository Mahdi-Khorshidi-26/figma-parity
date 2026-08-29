"""Drive the Agent SDK through the parity loop, then judge the result in Python.

The agent does the work. This module decides whether the work is done — by
reading the ledger and the diff output off disk, never by believing the
agent's own summary. That separation is the point of the whole project.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from .config import Settings, settings as default_settings
from .ledger import LedgerSummary, summarize

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKDIR_NAME = ".figma-parity"

EventSink = Callable[[dict[str, Any]], Awaitable[None]] | None


PROMPT = """\
Implement this Figma design in the project at {project_path}:

    {figma_url}

Use the `figma-parity` skill and follow every phase in order. It is not
optional and its rules are not negotiable — in particular:

- Do NOT call get_design_context on the screen root. Walk the tree with
  get_metadata first and descend to the leaves.
- Write each extraction unit into {workdir}/ledger.md BEFORE extracting
  the next one.
- Record the total node count on the ledger's `Coverage:` line.
- Render the result and pixel-diff it with:
      python -m figma_parity.diff <figma.png> <render.png> --out {workdir}/diff
  (run it from {repo_root}, which is on your path via add_dirs)
- Dispatch the figma-parity-auditor subagent before you consider stopping.

You do not decide when this is finished. A separate process reads the ledger
and the diff output and decides. If you cannot complete something, write it as
a ✖ row with the reason — an honest incomplete run is a success, a false
"complete" is the one unacceptable outcome.

Maximum {max_iterations} fix-and-remeasure iterations.
"""


@dataclass
class RunResult:
    figma_url: str
    project_path: Path
    verified: bool = False
    ledger: LedgerSummary | None = None
    agent_summary: str = ""
    cost_usd: float | None = None
    turns: int | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"{'VERIFIED' if self.verified else 'NOT VERIFIED'} — {self.figma_url}",
            f"  project: {self.project_path}",
        ]
        if self.error:
            lines.append(f"  error: {self.error}")
        if self.ledger:
            lines.append("  " + self.ledger.report().replace("\n", "\n  "))
        if self.cost_usd is not None:
            lines.append(f"  cost: ${self.cost_usd:.4f} · turns: {self.turns}")
        return "\n".join(lines)


def _options(project_path: Path, cfg: Settings) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=str(project_path),
        # The skill and auditor live in THIS repo, not the target project, so a
        # project-scoped setting source would not find them. Loading this repo
        # as a local plugin makes them available whatever the cwd is.
        plugins=[{"type": "local", "path": str(REPO_ROOT)}],
        # Read the user's ~/.claude so an already-authorised Figma MCP
        # connection is inherited rather than re-authorised headlessly.
        setting_sources=["user"],
        add_dirs=[str(REPO_ROOT)],
        permission_mode="acceptEdits",
        model=cfg.model,
        effort=cfg.effort,
        max_budget_usd=cfg.max_budget_usd,
        allowed_tools=[
            "Read", "Write", "Edit", "Glob", "Grep", "Bash", "Agent", "TodoWrite",
        ],
        mcp_servers={
            "figma": {"type": "http", "url": "https://mcp.figma.com/mcp"},
            "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]},
        },
    )


def _describe(block: Any) -> dict[str, Any] | None:
    """Turn a content block into a small event dict, or None if not worth emitting."""
    if isinstance(block, TextBlock):
        text = block.text.strip()
        return {"type": "text", "text": text} if text else None
    if isinstance(block, ToolUseBlock):
        detail = ""
        if isinstance(block.input, dict):
            for key in ("file_path", "command", "nodeId", "pattern", "url"):
                if key in block.input:
                    detail = str(block.input[key])[:160]
                    break
        return {"type": "tool", "name": block.name, "detail": detail}
    if isinstance(block, ThinkingBlock):
        return None
    return None


def evaluate_gate(project_path: Path) -> LedgerSummary:
    """Read the ledger off disk and decide completeness.

    This never consults the agent's opinion. If the ledger is missing, the run
    is not verified regardless of how confident the final message sounded.
    """
    return summarize(project_path / WORKDIR_NAME / "ledger.md")


async def run_parity(
    figma_url: str,
    project_path: Path,
    cfg: Settings | None = None,
    on_event: EventSink = None,
) -> RunResult:
    cfg = cfg or default_settings
    cfg.require_api_key()

    result = RunResult(figma_url=figma_url, project_path=project_path)

    async def emit(event: dict[str, Any]) -> None:
        result.events.append(event)
        if on_event:
            await on_event(event)

    workdir = project_path / WORKDIR_NAME
    workdir.mkdir(parents=True, exist_ok=True)

    prompt = PROMPT.format(
        project_path=project_path,
        figma_url=figma_url,
        workdir=workdir,
        repo_root=REPO_ROOT,
        max_iterations=cfg.max_iterations,
    )

    await emit({"type": "status", "text": f"starting · {figma_url}"})

    try:
        async with ClaudeSDKClient(options=_options(project_path, cfg)) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        event = _describe(block)
                        if event:
                            await emit(event)
                elif isinstance(message, ResultMessage):
                    result.cost_usd = getattr(message, "total_cost_usd", None)
                    result.turns = getattr(message, "num_turns", None)
                    result.agent_summary = getattr(message, "result", "") or ""
    except Exception as exc:  # surfaced to the caller, never swallowed
        result.error = f"{type(exc).__name__}: {exc}"
        await emit({"type": "error", "text": result.error})

    # --- the gate ------------------------------------------------------------
    # The agent has stopped talking. Whether it succeeded is decided here.
    result.ledger = evaluate_gate(project_path)
    result.verified = result.error is None and result.ledger.complete
    await emit({
        "type": "verdict",
        "verified": result.verified,
        "ledger": result.ledger.report(),
    })
    return result


def run_parity_sync(figma_url: str, project_path: Path, cfg: Settings | None = None) -> RunResult:
    return asyncio.run(run_parity(figma_url, project_path, cfg))
