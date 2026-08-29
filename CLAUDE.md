# figma-parity

An agentic service that implements a Figma design as code and **proves** it
matches, instead of asserting it does.

Give it a Figma link and a project path. It walks the design tree to every
leaf, records each property in a ledger, implements it, renders the result,
pixel-diffs the render against the design, has an independent auditor check
the work, and loops until the result is measurably correct — or reports
exactly what it could not finish.

---

## Why this exists

Every model, at every effort level, loses detail implementing a Figma design.
That is not a capability problem, and a better prompt does not fix it. There
are four structural causes:

1. **The output is never observed.** Ordinary workflows compare *what the model
   meant to write* against the design. The code is never rendered, so any CSS
   that behaves differently than predicted is invisible by construction.
2. **Nothing forces enumeration.** One `get_design_context` call on a screen
   root returns a blob that truncates or gets skimmed. The loss is silent.
3. **No external stop condition.** The model judging "does it match?" is the
   same model that wants to be finished.
4. **Context decay.** Design context + code + screenshots exhaust the window;
   properties extracted early are compacted away before implementation ends.

Each countermeasure targets one cause:

| Cause | Countermeasure | Where it lives |
|---|---|---|
| 1. Output unobserved | Render, screenshot, pixel-diff | `src/figma_parity/diff.py` |
| 2. No enumeration | Recursive descent + a row per property | `skills/figma-parity/SKILL.md` |
| 3. No stop condition | **Gate enforced in Python** | `src/figma_parity/ledger.py` |
| 4. Context decay | Write to disk before extracting the next unit | `SKILL.md` Phase 1 |

### The one rule that matters most

**The model never decides it is finished.** `runner.evaluate_gate()` reads the
ledger off disk and computes completeness itself. A confident final message
from the agent has no effect on the verdict. If you change one thing in this
codebase, do not change that.

---

## Architecture

```
POST /runs {figma_url, project_path}
      │
      ▼
  server.py ──── validates project_path against the allowlist   ← trust boundary
      │
      ▼
  runner.py ──── ClaudeSDKClient(
      │              cwd = target project,
      │              plugins = [this repo, loaded as a local plugin],
      │              mcp_servers = figma + playwright,
      │              permission_mode = "acceptEdits",
      │              model = claude-opus-5, effort = xhigh,
      │              max_budget_usd = hard spend cap)
      │
      ├── streams events ──► GET /runs/{id}/events  (SSE)
      │
      └── THE GATE (Python, not the model):
             ledger.complete  AND  no error
```

### Why this repo is loaded as a *plugin*

The agent's `cwd` is the **target project**, so `setting_sources=["project"]`
would read that project's `.claude/`, not ours — the skill would never load.
`plugins=[{"type": "local", "path": REPO_ROOT}]` makes the skill and the
auditor available regardless of `cwd`.

That is why `skills/` and `agents/` sit at the repo root (plugin layout) with
`.claude/skills` and `.claude/agents` as **symlinks** back to them. One copy,
two consumers: Claude Code reads the symlinks while you develop here; the Agent
SDK reads the plugin at runtime. Edit the real directories, never the symlinks.

---

## Layout

```
.claude-plugin/plugin.json     makes this repo loadable as a plugin
.mcp.json                      figma + playwright MCP servers
skills/figma-parity/
  SKILL.md                     the 5-phase workflow — the actual product
  references/rendering.md       per-stack render + screenshot recipes
agents/figma-parity-auditor.md  independent auditor subagent
src/figma_parity/
  config.py                    env, path allowlist, tunable knobs
  server.py                    FastAPI: /health, /runs, SSE events
  runner.py                    Agent SDK orchestration + the gate
  ledger.py                    parses ledger.md — enforces the gate
  diff.py                      two PNGs -> % diff, regions, heatmap
tests/                         plain-assert tests, no framework
```

Per-run artifacts are written into the **target** project at `.figma-parity/`:
`ledger.md`, `figma/`, `render/`, `diff/`.

---

## The ledger

External memory and completion gate in one file. Status vocabulary:

| | meaning |
|---|---|
| `☐` | not yet implemented |
| `☑` | implemented and verified |
| `⚠` | deliberate deviation — **reason required** |
| `✖` | blocked — **reason required** |

A `⚠` or `✖` with no written reason is counted as **still open**. Without that
check the gate is trivially gamed by flipping every `☐` to `⚠`.

The ledger's `Coverage: nodes N/M` line is checked separately: every row can be
ticked while the tree was only half walked. That is the exact failure this
project exists to catch, and `test_partial_traversal_blocks_even_when_all_rows_ticked`
pins it.

---

## Calibration knobs — pixel-perfect never means 0.00%

Figma's rasterizer and a browser's disagree on text antialiasing *everywhere*.
A loop that demands a zero diff never terminates. These are dials, not truths:

| Knob | Default | Meaning |
|---|---|---|
| `FIGMA_PARITY_TOL` | 12 | per-channel 0-255 delta treated as equal |
| `FIGMA_PARITY_THRESHOLD_PCT` | 0.5 | differing-pixel % that still passes |
| `FIGMA_PARITY_MAX_ITERATIONS` | 5 | fix-and-remeasure cap |
| `FIGMA_PARITY_MAX_BUDGET_USD` | 5.0 | hard spend ceiling per run |

**Act on the diff regions, not the percentage.** Each region is a numbered box
with coordinates and a heatmap. The percentage is only the gate.

---

## Security

- **The server binds `127.0.0.1` and has no authentication.** That is safe only
  because nothing off-machine can reach it. It holds an API key and runs an
  agent with `acceptEdits` and `Bash`. **If you ever change the bind address,
  add authentication first.**
- **`FIGMA_PARITY_ALLOWED_ROOTS` is the trust boundary.** `project_path`
  arrives over HTTP. `config.validate_project_path()` resolves it (collapsing
  `..` and symlinks) and refuses anything outside the allowlist. An empty
  allowlist refuses everything — fail closed, deliberately.
- **`.env` is gitignored.** Never commit a key.

---

## Gotchas

- **The Agent SDK does not read `.env`.** It reads the *process* environment.
  `config.py` calls `load_dotenv()` at import, which is what makes the key
  visible. Removing that line produces an auth error that looks like a bad key
  rather than a missing one.
- **`.claude/skills` and `.claude/agents` are symlinks.** Edit `skills/` and
  `agents/` at the repo root.
- **Never let a `get_design_context` call run on a screen root.** That is where
  detail dies. The skill forbids it; keep it forbidden.
- `pytest` is not installed. Tests are plain asserts run directly.

---

## Commands

```bash
python3 -m pip install -e .          # install deps
cp .env.example .env                 # then fill in ANTHROPIC_API_KEY
PYTHONPATH=src python3 -m figma_parity.server    # serve on 127.0.0.1:8787
```

```bash
PYTHONPATH=src python3 tests/test_diff.py && PYTHONPATH=src python3 tests/test_ledger.py && PYTHONPATH=src python3 tests/test_config.py
```

```bash
curl -X POST localhost:8787/runs -H 'content-type: application/json' \
  -d '{"figma_url":"https://www.figma.com/design/KEY/FAQ?node-id=1-2","project_path":"/path/to/project"}'
```

---

## References

| What | Where |
|---|---|
| Agent SDK Python reference | https://code.claude.com/docs/en/agent-sdk/python |
| Agent SDK subagents | https://code.claude.com/docs/en/agent-sdk/subagents |
| Agent SDK plugins | https://code.claude.com/docs/en/agent-sdk/plugins |
| Figma MCP server docs | https://developers.figma.com/docs/figma-mcp-server/ |
| Bundled `figma-design-to-code` skill (Phase 2 delegates to it) | `~/.claude/plugins/cache/claude-plugins-official/figma/2.2.81/skills/figma-design-to-code/SKILL.md` |
| Figma MCP tool set | `mcp__plugin_figma_figma__*` — `get_metadata`, `get_design_context`, `get_screenshot`, `get_variable_defs` |

**Model policy:** `claude-opus-5` at effort `xhigh`. Do not downgrade the model
to save cost — that is the operator's decision, set via `FIGMA_PARITY_MODEL`.
