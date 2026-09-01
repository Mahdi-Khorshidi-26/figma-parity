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
ledgers, no Figma file keys — a file key names a real, often client-owned
document, so none belongs in a shared repo. Your extractions stay in your own
project's `.figma-parity/`, which the skill gitignores before writing to it.

The browser MCP is **deliberately not bundled**. Shipping it would silently
register a server that downloads and executes code from npm on your machine the
first time it runs. That is reasonable software, but not something a design
plugin should arrange on your behalf without asking. If you want the pixel diff,
add it yourself:

```json
{ "mcpServers": { "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] } } }
```

## Install

> **No Anthropic API key required.** It runs on whatever Claude subscription
> you already have. There is no account to create, no key to paste, and nothing
> bills to the author.

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
| **A browser MCP** (e.g. `playwright`) | measures your built UI and screenshots it | no spacing check, no pixel diff |
| `FIGMA_TOKEN` (read-only, optional) | reads Figma **comments** | comments are skipped, and it says so |

Signing in to Figma is the one hard requirement. Everything else degrades
gracefully and says so.

```bash
pip install pillow numpy
```

**Ledger-only mode** still walks the whole tree, records every property, and
implements against that list — you lose the pixel measurement, not the
thoroughness. It tells you when it degrades rather than pretending.

---

## It works out what kind of job this is

You do not have to say whether the screen exists. It checks, and picks one of
three:

| | when | what it does |
|---|---|---|
| **build** | none of the design appears in your code | implements from scratch |
| **audit** | it is already there | measures it, reports what drifted, changes nothing else |
| **reconcile** | some of it exists | audits what is there, builds only what is missing, leaves working code alone |

Getting this wrong is expensive in both directions — rebuilding a finished
screen throws away working code, and auditing a half-built one silently skips
everything that was never written. So it looks rather than assumes, and when the
evidence is weak (nothing in your code carries a `data-node-id`, which looks the
same whether the screen is unbuilt or just hand-written) it says so and asks
instead of guessing.

## Checking a screen you already built

You do not have to rebuild anything. Point it at a design and say *"check the
spacing on this"* — it extracts the design's values, reads the ones your browser
actually rendered, and reports the differences as arithmetic:

```
FAIL  47/48 measured values match (1 mismatch)
  4:1911
    gap: design says 12px, browser rendered 8px   (ledger line 84)
```

**This is not the pixel diff, and that distinction matters.** Change one
container's padding by 4px and every border on screen moves; a pixel diff
collapses that into a single blob that says "something shifted". Computed styles
answer the actual question — *is this gap 12 or 16* — exactly, with no
threshold and no antialiasing noise.

The one requirement is that your elements carry `data-node-id` attributes, which
is what links a rendered element back to its design node. The skill adds them
when it builds, and will add them to existing markup if you ask it to audit.

Hex and `rgb()` compare as the same colour, `var(--s-600) 24px` compares as
24px, and sub-pixel rounding is not reported as a bug.

## Reading Figma comments

Comments — the pin threads on the canvas — are **not part of the document
tree**, so no Figma MCP tool can reach them. They are often where the real
constraint lives: *"this is the disabled state"*, *"8px not 12, we changed
this"*. Reading them needs a read-only Figma token, the only optional
credential anywhere in this plugin:

> Figma → Settings → Security → Personal access tokens → Generate,
> scope `file_comments:read`

```bash
export FIGMA_TOKEN=figd_...
```

Every open comment becomes a `☐` row in the ledger — a requirement until you
satisfy it or write down why it does not apply. Resolved threads are skipped and
replies fold into their parent. Without the token everything else works
unchanged and the run states that comments were not read, rather than leaving
you to assume the design carried no discussion.

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
for t in tests/*.py; do PYTHONPATH=src python3 "$t"; done
```

Plain asserts, no framework — each file also runs on its own.

`skills/` and `agents/` are the real directories (plugin layout);
`.claude/skills` and `.claude/agents` are symlinks so Claude Code sees them
while developing here. Edit the real ones.

See [CLAUDE.md](CLAUDE.md) for architecture and design rationale.

## License

MIT
