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

## What this does on your machine

Worth stating plainly, because a design tool that reads your files deserves the
scrutiny:

**It needs no system permissions.** No Full Disk Access, no accessibility
access, no admin rights, no login items - nothing that prompts your OS for
elevated trust. If something asks you for that while using this, it is not this.

**What it reads:** the Figma file you paste a link to, and the project folder
you point it at. Nothing else.

**What it writes:** a `.figma-parity/` folder inside *your* project, holding
your ledger, your Figma exports, your renders and diffs. The skill adds it to
your `.gitignore` on the first run, so your extractions never end up in your
commits. Nothing is written outside that folder.

**What talks to the network:** the official Figma MCP endpoint
(`https://mcp.figma.com/mcp`) to read your design, and Claude itself. That is
the whole list - no analytics, no telemetry, nothing reported back to this repo.

**Nothing from anyone else's runs ships here.** No screenshots, no sample
ledgers, no Figma file keys. `evals/cases.json` holds placeholders only - you
fill in links to designs you own, and results land in `evals/results/`, which is
gitignored. A Figma file key names a real, often client-owned document, so none
belongs in a shared repo.

**Optional extras, and what skipping them costs:**

| Feature | Needs | If you skip it |
|---|---|---|
| Tree walk, ledger, completion gate | nothing | - |
| Pixel diff | `pip install pillow numpy` | ledger-only mode, and it says so |
| Screenshotting your built UI | a browser MCP you add yourself | ledger-only mode |
| Headless HTTP service | your own Anthropic API key | ignore it; the plugin never uses it |

The browser MCP is **deliberately not bundled**. Shipping it would silently
register a server that downloads and executes code from npm on your machine the
first time it runs. That is reasonable software, but not something a design
plugin should arrange on your behalf without asking. If you want the pixel diff,
add it yourself:

```json
{ "mcpServers": { "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] } } }
```

## Install

> **No Anthropic API key required.** The plugin runs on whatever Claude
> subscription you already have. There is no account to create, no key to
> paste, and nothing bills to the author. The optional Python service further
> down is a separate, headless path — ignore it unless you want one.

### 1. Add the marketplace and install

Inside a Claude Code session:

```
/plugin marketplace add Mahdi-Khorshidi-26/figma-parity
```
```
/plugin install figma-parity@figma-parity
```

Or from a terminal, if you prefer:

```bash
claude plugin marketplace add Mahdi-Khorshidi-26/figma-parity
```
```bash
claude plugin install figma-parity@figma-parity
```

Restart Claude Code, then:

```
/figma-parity https://www.figma.com/design/KEY/File?node-id=1-2
```

That's it. The skill, the slash command, and the auditor subagent are all
active.

### Keeping it up to date

Installed plugins do **not** update themselves. To pull the latest version:

```bash
claude plugin marketplace update figma-parity
```

Worth doing before you report a bug — an old copy can look installed while its
commands quietly fail.

### 2. What it needs from you

| Requirement | Why | Without it |
|---|---|---|
| **Figma MCP** — the official `figma` plugin, signed in to your Figma account | reads the design | nothing works |
| **Python 3.10+** | the tree walk, ledger and completion gate | those are stdlib-only, so a stock Python is enough |
| `pillow` and `numpy` | the pixel diff *only* | falls back to ledger-only |
| **A browser MCP** (e.g. `playwright`) | screenshots your built UI | falls back to ledger-only |

Signing in to Figma is the one hard requirement. Everything else degrades
gracefully and says so.

```bash
pip install pillow numpy
```

**Ledger-only mode** still walks the whole tree, records every property, and
implements against that list — you lose the pixel measurement, not the
thoroughness. It tells you when it degrades rather than pretending.

### Optional: the headless service

Only if you want to drive this from automation rather than interactively. This
path *does* need an Anthropic API key, because it runs the agent itself via the
Claude Agent SDK instead of using your Claude Code session.

```bash
git clone https://github.com/Mahdi-Khorshidi-26/figma-parity
cd figma-parity && python3 -m pip install -e .
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
>
> It also strips inherited `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` from
> the environment before starting the agent. The Agent SDK inherits the whole
> environment, so without this a stray proxy or token in your shell silently
> redirects the run to the wrong endpoint on the wrong credential.

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
