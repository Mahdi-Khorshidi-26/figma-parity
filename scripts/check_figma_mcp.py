"""Diagnostic: can the Agent SDK actually reach the Figma MCP server?

This is the single highest-risk assumption in the whole design — the Figma MCP
uses OAuth, and an interactive Claude Code authorisation does not obviously
carry over to a headless SDK process. Answer that question on its own, cheaply,
before spending real money on a full parity run.

    PYTHONPATH=src python3 scripts/check_figma_mcp.py <figma-url>
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from figma_parity.config import isolate_anthropic_env, settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

PROMPT = """\
Call the Figma MCP tool `get_metadata` on this node and nothing else:

    {url}

Then report exactly three things and stop:
1. Did the call succeed, or what error came back?
2. How many nodes are in the returned tree?
3. The name and type of the top-level node.

Do NOT call get_design_context. Do NOT write any files. Do NOT implement
anything. This is a connectivity check only.
"""


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.figma.com/design/Jk3V1bpN1jEJMkCRAPLK2h/FAQ?node-id=4-1911&m=dev"
    )
    settings.require_api_key()
    hijacked = isolate_anthropic_env(settings)
    if hijacked:
        print("stripped inherited env: " + ", ".join(hijacked))
    print(f"node: {url}\nmodel: {settings.model} · budget cap: ${settings.max_budget_usd}\n")

    options = ClaudeAgentOptions(
        cwd=str(REPO_ROOT),
        setting_sources=["user"],       # inherit an already-authorised Figma MCP
        permission_mode="acceptEdits",
        model=settings.model,
        effort="low",                   # a connectivity check needs no deep thinking
        max_budget_usd=min(settings.max_budget_usd or 1.0, 1.0),
        max_turns=8,
        allowed_tools=[
            "mcp__figma__get_metadata",
            "mcp__plugin_figma_figma__get_metadata",
        ],
        mcp_servers={"figma": {"type": "http", "url": "https://mcp.figma.com/mcp"}},
    )

    saw_figma_tool = False
    async with ClaudeSDKClient(options=options) as client:
        await client.query(PROMPT.format(url=url))
        async for message in client.receive_response():
            if isinstance(message, SystemMessage):
                data = getattr(message, "data", {}) or {}
                servers = data.get("mcp_servers")
                if servers:
                    print("MCP servers reported at init:")
                    for s in servers:
                        print(f"  - {s.get('name')}: {s.get('status')}")
                    print()
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        print(f"  [tool] {block.name}")
                        if "figma" in block.name:
                            saw_figma_tool = True
                    elif isinstance(block, TextBlock) and block.text.strip():
                        print(block.text.strip())
            elif isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
                print(f"\ncost: ${cost:.4f}" if cost else "\ncost: n/a")

    print(f"\nfigma tool actually invoked: {saw_figma_tool}")
    return 0 if saw_figma_tool else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
