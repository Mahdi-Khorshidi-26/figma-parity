# figma-parity

**Figma-to-code that proves it matches — instead of asserting it does.**

Hand a model a Figma link for a whole page and it loses detail. The usual
workaround is to open the layer tree yourself and paste each component
separately so nothing gets skipped. This automates that walk, then *measures*
the result against the design and refuses to claim success until it's verified.

---

## The problem

Four things go wrong in a single-pass implementation. None are fixed by a more
capable model:

1. **The output is never observed.** The code is never rendered, so the model
   compares *what it meant to write* against the design. Any CSS that behaves
   differently than predicted is invisible by construction.
2. **Nothing forces enumeration.** One `get_design_context` call on a page root
   truncates. The loss is silent.
3. **No external stop condition.** The model judging "does it match?" is the
   same one that wants to be finished.
4. **Context decay.** Long designs exhaust the window, so details extracted
   early are forgotten before implementation ends.

## The loop

1. **Descend.** `get_metadata` for the tree, then extract subtree by subtree —
   never the screen root. Component instances are extracted once and referenced.
2. **Ledger.** Every property becomes a row with a status box, written to disk
   *as it's extracted*, so it survives context compaction.
3. **Implement**, ticking rows as they land.
4. **Render and diff.** Screenshot the built UI, pixel-diff it against the
   Figma export, act on the numbered diff regions.
5. **Audit.** A subagent with fresh context that didn't write the code checks
   what the diff structurally cannot see — states, breakpoints, design tokens,
   hand-drawn icons, accessibility.
6. **Loop**, then exit honestly. Capped at 5 iterations.

**The completion gate runs in code, not in the prompt.** A ledger row can be
`☐ todo`, `☑ done`, `⚠ deviation` or `✖ blocked` — and `⚠`/`✖` require a
written reason, so flipping every box to `⚠` doesn't pass. Coverage is checked
separately: every row can be ticked while only half the tree was walked, which
is exactly the failure this exists to catch.

An honest *"8 of 213 rows unresolved, here they are"* is a success. A false
*"complete"* is the only unacceptable outcome.

---

## Install

### As a Claude Code plugin — no server, no API key

This is all most people need. The skill, the slash command, and the auditor
subagent work inside Claude Code on your existing subscription.

```
/plugin marketplace add Mahdi-Khorshidi-26/figma-parity
```
```
/plugin install figma-parity@figma-parity
```

Then:

```
/figma-parity https://www.figma.com/design/KEY/File?node-id=1-2
```

Requires the [Figma MCP server](https://developers.figma.com/docs/figma-mcp-server/)
(the official `figma` plugin) for design access, and any browser MCP for the
render-and-diff step. Without a browser it still runs in **ledger-only mode** —
complete extraction and per-property implementation, minus the pixel
measurement. It will tell you when it does this rather than pretending.

For the pixel diff you also need Python with `pillow` and `numpy`:

```bash
pip install pillow numpy
```

### As a headless service — your own API key

Runs the same loop over HTTP on the Claude Agent SDK, for automation rather
than interactive use.

```bash
git clone https://github.com/Mahdi-Khorshidi-26/figma-parity
cd figma-parity
python3 -m pip install -e .
cp .env.example .env       # add ANTHROPIC_API_KEY and FIGMA_PARITY_ALLOWED_ROOTS
PYTHONPATH=src python3 -m figma_parity.server
```

```bash
curl -X POST localhost:8787/runs -H 'content-type: application/json' \
  -d '{"figma_url":"https://www.figma.com/design/KEY/File?node-id=1-2","project_path":"/path/to/app"}'
```

| Endpoint | |
|---|---|
| `GET /health` | config check |
| `POST /runs` | `{figma_url, project_path}` → `{run_id}` |
| `GET /runs/{id}` | status, verdict, ledger counts, cost |
| `GET /runs/{id}/events` | SSE progress stream (replays from the start) |

> **Security.** The server binds `127.0.0.1` and has no authentication. That's
> safe only because nothing off-machine can reach it — it holds an API key and
> runs an agent with file-write and shell access. `FIGMA_PARITY_ALLOWED_ROOTS`
> restricts which directories it may touch and **refuses everything when
> empty**. If you change the bind address, add authentication first.

---

## Tuning

Figma's rasterizer and a browser's never agree on text antialiasing, so a real
render never diffs to 0.00%. These are dials, not truths:

| Setting | Default | Meaning |
|---|---|---|
| `FIGMA_PARITY_TOL` | 12 | per-channel 0-255 delta treated as equal |
| `FIGMA_PARITY_THRESHOLD_PCT` | 0.5 | differing-pixel % that still passes |
| `FIGMA_PARITY_MAX_ITERATIONS` | 5 | fix-and-remeasure cap |
| `FIGMA_PARITY_MAX_BUDGET_USD` | 5.0 | hard spend ceiling per run |

**Act on the diff regions, not the percentage.** Each is a numbered box with a
fill density: `solid` means a block differs outright; `sparse` across a large
area means one layout shift is hiding every smaller defect inside it — fix it
and re-measure.

---

## Development

```bash
PYTHONPATH=src python3 tests/test_diff.py
PYTHONPATH=src python3 tests/test_ledger.py
PYTHONPATH=src python3 tests/test_config.py
```

Plain asserts, no framework. `evals/run_evals.py` measures extraction coverage
across a set of real Figma links — the number that catches "it looked finished
but only walked half the tree".

`skills/` and `agents/` are the real directories (plugin layout);
`.claude/skills` and `.claude/agents` are symlinks so Claude Code sees them
while developing here. Edit the real ones.

See [CLAUDE.md](CLAUDE.md) for architecture and design rationale.

## License

MIT
