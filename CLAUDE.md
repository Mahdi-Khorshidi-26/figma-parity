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

**The model never decides it is finished.** `ledger.summarize()` reads the
ledger off disk and `tree.py` counts the design's nodes independently, so both
halves of the verdict are computed from files rather than taken from the
agent's word. A confident final message has no effect on the outcome. If you
change one thing in this codebase, do not change that.

The corollary is easy to lose: **any number the gate consumes must come from
the design or the filesystem, never from prose the model wrote.** Coverage was
once read from a `Coverage: nodes N/M` line the model authored about itself —
that is the exact mistake to avoid re-introducing.

---

## Architecture

There is no service. This is a Claude Code plugin: the skill drives the loop,
and three small Python modules hold the parts a model must not be trusted with.

```
/figma-parity <url>   in the user's own project
      │
      ▼
  SKILL.md ── Phase 0 classify · 1 descend · 2 implement · 3 diff · 4 audit · 5 loop
      │
      ├── scripts/parity.py classify   → tree.py    what kind of node is this?
      ├── scripts/parity.py diff       → diff.py    two PNGs -> regions + heatmap
      └── scripts/parity.py coverage   → ledger.py  THE GATE
                                          + tree.py  coverage derived from the
                                                     design, not self-reported
```

Everything runs in the user's project directory. Nothing is written outside
their `.figma-parity/`, and nothing needs an API key.

### Why the commands use `${CLAUDE_PLUGIN_ROOT}`

The skill executes inside the **user's** project, not this repo, so a relative
`src/` path or `python -m figma_parity...` resolves to nothing. Every runnable
command must be an absolute path under `${CLAUDE_PLUGIN_ROOT}`, which Claude
Code sets to this plugin's directory. `scripts/parity.py` puts its own `src/`
on `sys.path`, so it works from any cwd.

`skills/` and `agents/` sit at the repo root (plugin layout) with
`.claude/skills` and `.claude/agents` as **symlinks** back to them. One copy,
two consumers: Claude Code reads the symlinks while you develop here, and the
plugin loader reads the real directories when installed. Edit the real ones.

---

## Layout

```
.claude-plugin/plugin.json     makes this repo loadable as a plugin
.mcp.json                      figma MCP only (browser MCP deliberately not bundled)
commands/figma-parity.md       the /figma-parity entry point
skills/figma-parity/
  SKILL.md                     the 5-phase workflow — the actual product
  references/rendering.md      per-stack render + screenshot recipes
agents/figma-parity-auditor.md independent auditor subagent
scripts/parity.py              the CLI the skill calls, via ${CLAUDE_PLUGIN_ROOT}
src/figma_parity/
  tree.py                      parses the design tree — derives coverage
  ledger.py                    parses ledger.md — enforces the gate
  diff.py                      two PNGs -> % diff, regions, heatmap
tests/                         plain-assert tests, no framework
```

That is the whole thing. `classify` and `coverage` are stdlib-only; only the
pixel diff pulls in pillow and numpy. **Keep it that way** — a design plugin
that makes people install a web server to compare two PNGs invites exactly the
suspicion this project should not attract.

Per-run artifacts are written into the **target** project at `.figma-parity/`:
`ledger.md`, `tree.xml`, `figma/`, `render/`, `diff/`.

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

- **No elevated permissions, ever.** Nothing here should need Full Disk
  Access, accessibility access, or admin rights. A change that would is the
  wrong change.
- **No network beyond Figma and Claude.** The official Figma MCP endpoint reads
  the design; Claude does the work. No analytics, no telemetry, nothing
  reported back to this repo.
- **Write only inside the user's `.figma-parity/`**, and gitignore it before
  writing. Their extractions are theirs.

---

## Privacy rules for this repo

- **No real Figma file keys, ever.** A key names a real, often client-owned
  document. Test against your own designs locally and commit none of it.
- **No run artifacts.** No screenshots, ledgers, renders or diffs from anyone's
  runs get committed here. They live in the user's own `.figma-parity/`.
- **No bundled code-executing MCP servers.** `.mcp.json` declares the official
  Figma HTTP endpoint only. A browser MCP spawns `npx`, which downloads and runs
  code on the user's machine — that has to be their explicit choice.
- **No elevated permissions.** Nothing here should ever need Full Disk Access,
  accessibility access, or admin rights. If a change would, it is the wrong
  change.

## Gotchas

- **`.claude/skills` and `.claude/agents` are symlinks.** Edit `skills/` and
  `agents/` at the repo root.
- **Never let a `get_design_context` call run on a screen root.** That is where
  detail dies. The skill forbids it; keep it forbidden.
- `pytest` is not installed. Tests are plain asserts run directly.

---

## Commands

```bash
pip install pillow numpy             # only the pixel diff needs these
```

```bash
for t in tests/*.py; do PYTHONPATH=src python3 "$t"; done
```


---

## References

| What | Where |
|---|---|
| Claude Code plugins | https://code.claude.com/docs/en/plugins |
| Figma MCP server docs | https://developers.figma.com/docs/figma-mcp-server/ |
| Bundled `figma-design-to-code` skill (Phase 2 delegates to it) | `~/.claude/plugins/cache/claude-plugins-official/figma/2.2.81/skills/figma-design-to-code/SKILL.md` |
| Figma MCP tool set | `mcp__plugin_figma_figma__*` — `get_metadata`, `get_design_context`, `get_screenshot`, `get_variable_defs` |

**Model policy:** `claude-opus-5` at effort `xhigh`. Do not downgrade the model
to save cost — that is the operator's decision, set via `FIGMA_PARITY_MODEL`.
