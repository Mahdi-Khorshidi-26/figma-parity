"""Configuration and the filesystem trust boundary.

`project_path` arrives over HTTP and is handed to an agent running with
`acceptEdits` and `Bash`. Everything in this file exists so that an HTTP
request cannot point that agent at arbitrary parts of the disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# The Agent SDK reads credentials from the PROCESS environment and does not
# load .env itself. Loading here, at import, is what makes ANTHROPIC_API_KEY
# visible to it. Removing this line breaks auth in a way that looks like a
# bad key rather than a missing one.
load_dotenv()


class ConfigError(RuntimeError):
    pass


def _split_roots(raw: str) -> list[Path]:
    return [Path(p.strip()).expanduser().resolve()
            for p in raw.split(os.pathsep) if p.strip()]


@dataclass
class Settings:
    api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    allowed_roots: list[Path] = field(
        default_factory=lambda: _split_roots(os.getenv("FIGMA_PARITY_ALLOWED_ROOTS", ""))
    )
    host: str = field(default_factory=lambda: os.getenv("FIGMA_PARITY_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("FIGMA_PARITY_PORT", "8787")))

    # Agent knobs
    model: str = field(default_factory=lambda: os.getenv("FIGMA_PARITY_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.getenv("FIGMA_PARITY_EFFORT", "xhigh"))
    max_iterations: int = field(
        default_factory=lambda: int(os.getenv("FIGMA_PARITY_MAX_ITERATIONS", "5"))
    )
    # Hard spend ceiling per run, enforced by the Agent SDK. This runs on real
    # credits and an agentic loop with a 5-iteration cap can still be long.
    max_budget_usd: float | None = field(
        default_factory=lambda: (
            float(os.environ["FIGMA_PARITY_MAX_BUDGET_USD"])
            if os.getenv("FIGMA_PARITY_MAX_BUDGET_USD") else 5.0
        )
    )

    # Parity knobs — mirrored from diff.py so they are tunable without editing code.
    # ponytail: a text-heavy UI never reaches 0.00%; these are dials, not truths.
    tol: int = field(default_factory=lambda: int(os.getenv("FIGMA_PARITY_TOL", "12")))
    threshold_pct: float = field(
        default_factory=lambda: float(os.getenv("FIGMA_PARITY_THRESHOLD_PCT", "0.5"))
    )

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set. Put it in .env at the repo root "
                "(see .env.example). The Agent SDK reads it from the process "
                "environment; config.py loads .env at import."
            )
        return self.api_key

    def validate_project_path(self, raw: str | Path) -> Path:
        """Resolve a caller-supplied project path, or refuse it.

        Refuses anything outside FIGMA_PARITY_ALLOWED_ROOTS. `.resolve()` runs
        before the check, so `..` traversal and symlinks are normalised away
        and cannot escape a root.
        """
        if not self.allowed_roots:
            raise ConfigError(
                "FIGMA_PARITY_ALLOWED_ROOTS is empty, so every path is refused. "
                "Set it in .env to the directories this service may write to."
            )

        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise ConfigError(f"project_path is not an existing directory: {path}")

        for root in self.allowed_roots:
            if path == root or root in path.parents:
                return path

        raise ConfigError(
            f"project_path {path} is outside every allowed root "
            f"({', '.join(str(r) for r in self.allowed_roots)})."
        )


# Environment variables that redirect the Agent SDK away from the Anthropic API
# or away from OUR key. The SDK spawns the Claude Code CLI and inherits the whole
# environment (`inherited_env = {k: v for k, v in os.environ.items()
# if k != "CLAUDECODE"}` in subprocess_cli.py), so anything set in the shell that
# launched this service is silently adopted by the agent.
#
# This bit us for real: a Claude Code session exports
# ANTHROPIC_BASE_URL=http://127.0.0.1:1337 and ANTHROPIC_AUTH_TOKEN. The SDK
# inherited both, tried the dead local proxy, and failed with "Connection
# refused" — never reaching the configured key at all.
#
# The connection error was the lucky outcome. Had that proxy been running, the
# run would have succeeded against the WRONG endpoint and billed the WRONG
# credential, with nothing in the output to say so. Auth precedence puts
# ANTHROPIC_AUTH_TOKEN ahead of ANTHROPIC_API_KEY, and an empty value still
# counts as set — so these must be REMOVED, not blanked.
_HIJACKING_VARS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    # Alias redirection: these remap "opus"/"sonnet"/"haiku" to other models.
    # Removed so the configured model string means exactly what it says.
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)


def isolate_anthropic_env(cfg: "Settings") -> list[str]:
    """Strip inherited Anthropic routing/credential vars and pin our own key.

    Call this before constructing a ClaudeSDKClient. Returns the names that were
    actually removed so the caller can log them — a silent fix here would hide
    the fact that the ambient environment was trying to redirect the run.
    """
    removed = [k for k in _HIJACKING_VARS if k in os.environ]
    for key in removed:
        os.environ.pop(key, None)
    os.environ["ANTHROPIC_API_KEY"] = cfg.require_api_key()
    return removed


settings = Settings()
