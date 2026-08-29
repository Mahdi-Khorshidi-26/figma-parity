---
name: figma-parity
description: Implement a Figma design as code with verified pixel parity. Use whenever a Figma link is given and the design must be implemented completely — walks the node tree to its leaves, records every property in a ledger, renders the result, pixel-diffs it against the design, and loops until it provably matches. Use instead of a single-pass implementation whenever detail loss matters.
---

# Figma → Code with Verified Parity

A single pass over a Figma design silently loses detail. This skill replaces
"implement it and check the boxes" with a measured loop that cannot report
success until the work is provably done.

## Why this exists — the four failure modes

Every one of these is structural. A more capable model does not fix any of them.

1. **The output is never observed.** Ordinary workflows compare *what the model
   meant to write* against the design. They never render the code and look at
   what the browser actually painted, so any CSS that behaves differently than
   predicted is invisible.
2. **Nothing forces enumeration.** One `get_design_context` call on a screen
   root returns a blob that truncates or gets skimmed. Detail loss is silent.
3. **No external stop condition.** The model judging "does it match?" is the
   same model that wants to be finished.
4. **Context decay.** Design context + code + screenshots exhaust the window.
   Properties extracted early are compacted away before implementation ends.

The countermeasures are, in order: render and diff · recursive descent ·
a completion gate in code · write to disk immediately.

## Non-negotiable rules

- **Never call `get_design_context` on a whole screen or page root.** That is
  where detail dies. Descend first (Phase 1).
- **Write each unit to the ledger before extracting the next.** Not at the end.
  The ledger is what survives context compaction.
- **Never mark the run complete yourself.** `ledger.py` and `diff.py` decide.
- **A `⚠` or `✖` row requires a written reason.** A status with no reason is
  counted as still open; it is not an escape hatch.
- **Never invent an icon.** Icons and images come back as asset URLs — download
  the real bytes. Anything hand-drawn is wrong.

---

## Phase 0 — Orient

### Resolve the URL to a starting node

Four shapes arrive; all must work:

| URL shape | Example | What to do |
|---|---|---|
| File only | `/design/KEY/FAQ` | `get_metadata` at the file root, list the pages, ask which to implement |
| Page node | `?node-id=0-1` | `get_metadata` → enumerate top-level frames; each is usually a breakpoint variant |
| Canvas / frame | `?node-id=1-2` | The normal case. This is a screen — descend it |
| Deep component | `?node-id=4-1911` | Implement just that subtree; still descend it |

`fileKey` is the segment after `/design/`; `nodeId` is `node-id` with `-` read
as `:`. Parameter mechanics live on the `get_design_context` tool description —
follow them there rather than restating.

**Sibling frames are usually breakpoints, not separate screens.** A canvas
holding `FAQs / FAQs / FAQs` at descending widths is one responsive page in
three variants. Confirm with the user before implementing them as three pages,
and record each as a row in the ledger's Responsive table.

### Resolve the render method

Detect the stack and pick how the built UI will be screenshotted — see
[references/rendering.md](references/rendering.md). If no render method can be
resolved, **say so explicitly and continue in ledger-only mode.** Degraded is
acceptable; silently skipping verification is not.

### Create the working directory

`.figma-parity/` inside the target project: `ledger.md`, `figma/`, `render/`,
`diff/`. Add it to the project's `.gitignore`.

---

## Phase 1 — Recursive descent

*Countermeasure for failure modes 2 and 4. This is the core of the skill.*

### The traversal

1. `get_metadata(fileKey, nodeId)` — cheap, structural, gives the whole tree
   with node ids, types, names, and size estimates. **Do this first, always.**
2. Record the total node count in the ledger's `Coverage:` line. This number is
   what the completion gate checks against — an unstated coverage line counts
   as no coverage.
3. Walk the tree depth-first. For each node:

```
walk(node):
    if node is an instance of a component already extracted:
        write a reference row pointing at that component; do NOT re-extract
    elif estimated_tokens(node) <= UNIT_BUDGET:
        get_design_context(node)        # this node is an extraction unit
        append its rows to ledger.md    # BEFORE moving on
    else:
        extract_container_properties(node)   # see the warning below
        for child in node.children:
            walk(child)
```

`UNIT_BUDGET` ≈ **15–20k tokens**. Figma reports a per-node estimate; use it.

### Two traps that make descent lose more than it saves

**Splitting a parent drops the parent's own layout.** When you descend into a
node's children instead of extracting the node, you must *still* record that
node's own auto-layout properties — direction, gap, padding, alignment,
distribution, sizing mode, constraints. These live on the container, not on any
child. Skipping them is the single most common way a correctly-extracted set of
children still assembles into a wrong layout.

**Component instances repeat.** A page with 20 `Question` instances does not
need 20 extractions. Extract the main component once, record its properties,
then for each instance record only its *overrides* (the text it carries, any
variant/state difference). Figma flags when an instance's layout differs from
its main component — when it does, that difference is a row.

### What to extract per node

Every leaf property becomes its own row. Not "typography: heading" — one row
per value, because a row is what gets ticked:

- Text: font-family, size, weight, line-height, letter-spacing, color, align, transform, decoration
- Box: width, height, padding (each side), margin, border-radius (each corner), border, shadow, opacity, overflow
- Layout: direction, gap, justify, align, wrap, sizing (hug/fill/fixed), position, z-order
- Fill/stroke: color or gradient, plus the token name where one exists
- Asset: source URL, intrinsic size, rendered size

Also run `get_variable_defs` **once** for the file's token map, and prefer the
token name over the raw hex in the `expected` column — record both:
`var(--text-primary) #1A1A1A`.

### States and breakpoints are invisible to a pixel diff

The rendered default state cannot reveal a missing hover style. Enumerate them
explicitly into the ledger's own tables from the component's variants and from
any interactive prototype links: hover, focus, active, disabled, loading,
error, empty, expanded/collapsed, selected. Each is a row.

### Screenshots

`get_screenshot` per unit and for the root. It returns a short-lived URL plus
curl instructions — **download via curl into `.figma-parity/figma/`**. Do not
request base64 inline; it costs enormously more context for the same pixels.

---

## Phase 2 — Implement

Load the bundled **`figma-design-to-code`** skill and follow its translation
rules — component and token reuse, hint priority, and the asset rules are
already specified there and should not be restated or contradicted. This skill
owns the *loop*; that one owns the *translation*.

Two additions:

- **Tick ledger rows as they land**, in batches as each section is built.
- When the project's design system genuinely conflicts with the Figma value,
  that is a `⚠` row **with the reason written in the note column** — not a
  silent substitution and not a `☑`.

---

## Phase 3 — Render and measure

*Countermeasure for failure mode 1.*

1. Render the implemented UI and screenshot it per `references/rendering.md`,
   at the Figma frame's width and `deviceScaleFactor: 2`.
2. Export the Figma node at matching pixel dimensions (`get_screenshot` with
   `maxDimension` set to the render's long edge).
3. Run the diff:

```bash
python -m figma_parity.diff .figma-parity/figma/<node>.png .figma-parity/render/<node>.png --out .figma-parity/diff
```

Read the output as follows:

- **A size mismatch is a defect.** Fix it before trusting any region below it.
- **Act on the regions, not the percentage.** Each region is a numbered box
  with coordinates; the heatmap shows them visually. The percentage is only the
  gate.
- **It will never read 0.00%.** Figma's rasterizer and a browser's disagree on
  text antialiasing everywhere. `TOL` and the threshold are tunable knobs. Do
  not chase zero — chase empty region lists.
- **Read each region's fill density, not just its size.** Every region is
  reported as `sparse`, `partial`, or `solid`:
  - `solid` (≥50% fill) — a block differs outright: a missing element, an extra
    one, or a recoloured panel. Act on it directly.
  - `sparse` (<15% fill) — outlines and text moved inside a large box. That is
    a **layout shift** (padding, margin, gap, size), not many separate defects.

- **A large sparse region hides everything inside it.** When one shifted
  container moves every child, all those differences merge into a single blob
  and smaller defects become invisible until the shift is gone. `diff.py`
  prints an explicit NOTE when it detects this. When you see it: fix the
  layout shift first, then **re-measure before concluding anything** — the
  next defect only surfaces on the following pass. Never read "1 region" as
  "1 problem".

Repeat for every breakpoint and every state the ledger lists.

---

## Phase 4 — Independent audit

*Countermeasure for failure mode 3.*

Dispatch the **`figma-parity-auditor`** subagent. Give it the Figma screenshot,
the rendered screenshot, the heatmap, the ledger path, and the files written.
It has fresh context and did not write the code, so it has no stake in the work
being finished. It reports defects; it never fixes them.

Do not skip this because the diff looked clean. The diff cannot see a wrong
font family that happens to have identical metrics, a hardcoded hex where a
token was required, or a missing `aria-label`.

---

## Phase 5 — Loop, then exit honestly

Fix → re-render → re-diff → re-audit. Exit only when **all three** hold:

```bash
python -c "import sys; sys.path.insert(0,'src'); from figma_parity.ledger import summarize; print(summarize('.figma-parity/ledger.md').report())"
```

1. `ledger.summarize().complete` is true — no open rows, no unjustified
   deviations, and coverage fully walked
2. `diff.py` exits 0 for every breakpoint and state
3. The auditor returns no defects

**Hard cap: 5 iterations.** On hitting it, stop and report precisely what still
differs — which rows are open, which regions remain, what the auditor found.

> Reporting parity that was not measured is the one unrecoverable failure of
> this skill. An honest "8 of 213 rows unresolved, here they are" is a success.
> A false "complete" destroys the only thing this loop is for.

---

## Ledger format

Status vocabulary — `☐` todo · `☑` verified · `⚠` deviation *(reason required)*
· `✖` blocked *(reason required)*.

```markdown
# Parity Ledger — FAQs
Figma: https://figma.com/design/KEY/FAQ?node-id=1-2 · Node: 1:2 · Extracted: 2026-08-29
Coverage: nodes 47/47

## Components
| component | node | instances | extracted |
|---|---|---|---|
| Menu / Desktop Header | 3:958 | 3 | ☑ |
| Question | 4:1911 | 24 | ☑ |

### 4:1911 — Questions Column / Question Block / Question (INSTANCE)
| prop | expected | status | note |
|---|---|---|---|
| font-size | 18px | ☐ | |
| line-height | 24px | ☐ | |
| color | var(--text-primary) #1A1A1A | ☐ | |
| padding-y | 16px | ☐ | |

## States
| element | state | expected | status | note |
|---|---|---|---|---|
| Question | expanded | answer visible, chevron 180° | ☐ | |
| Question | collapsed | answer hidden | ☐ | |

## Responsive
| breakpoint | source frame | node | status | note |
|---|---|---|---|---|
| Large | FAQs (desktop) | 1:2 | ☐ | |
| Medium | FAQs (tablet) | 1:3 | ☐ | |
| Small | FAQs (mobile) | 1:4 | ☐ | |

## Unresolved
```

Every row is one checkable value. `ledger.py` counts the boxes, and that count
is the gate — which is why a vague row is worse than no row.
