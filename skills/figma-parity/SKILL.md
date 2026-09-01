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
  the real bytes into the project. Those URLs expire in ~7 days, so committed
  code must never point at one. Anything hand-drawn is wrong.
- **Every ledger row carries the node id it came from.** Coverage is computed
  from those ids, not from the `Coverage:` line — a row without an id is a row
  that counts for nothing.
- **Quote every shell path.** Project directories contain spaces (and sometimes
  a trailing space). `cd "$DIR"`, never `cd $DIR`.

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

### Classify the node BEFORE planning anything

Save the raw `get_metadata` response to `.figma-parity/tree.xml`, then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" classify .figma-parity/tree.xml
```

`${CLAUDE_PLUGIN_ROOT}` is set for you and points at this plugin. Use it for
every command below — you are running inside the *user's* project, so a bare
`python -m figma_parity...` or a relative `src/` path will not resolve.

| kind | what it means | what to do |
|---|---|---|
| `screen` | a viewport-width frame | implement it — the normal path |
| `component` | a small subtree | implement just this component |
| `breakpoint-set` | sibling frames, same name, descending widths | ONE responsive screen — confirm, then implement once with breakpoints |
| `document` | far taller than wide — a spec sheet | **STOP and ask.** This is documentation *about* a UI, not the UI |

**A `document` is the trap.** A 4169x31764px specification sheet contains prose
describing a screen plus mockups of it. Implementing it literally produces a
wall of text nobody wanted. When the classifier says `document`, ask the user
whether they want (a) the UI the document describes, or (b) the document
itself — and do not guess.

Saving `tree.xml` is also what lets the gate derive coverage instead of
believing the `Coverage:` line. Skip it and the run can only ever be
self-reported.

### Read the comments on the design

Figma comments — the pin threads people leave on the canvas — are **not part of
the document tree**, so no MCP tool returns them and `get_design_context` never
sees them. They are frequently where the real constraint lives: *"this is the
disabled state"*, *"copy is placeholder"*, *"8px not 12, we changed this"*.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" comments <fileKey> .figma-parity/tree.xml
```

Append the output to the ledger. Every open comment is a `☐` row — someone
typed it on purpose, so it is a requirement until you have either satisfied it
or written down why it does not apply. Resolved threads are skipped; replies are
folded into their parent rather than becoming separate rows.

This needs a read-only `FIGMA_TOKEN` and is the **only** part of the skill that
does. **Exit code 3 means no token was set, which is not a failure** — carry on,
and say in your summary that comments were not read. Never let silence imply the
design carried no discussion.

### Resolve the render method

Detect the stack and pick how the built UI will be screenshotted — see
[references/rendering.md](references/rendering.md). If no render method can be
resolved, **say so explicitly and continue in ledger-only mode.** Degraded is
acceptable; silently skipping verification is not.

### Create the working directory

`.figma-parity/` inside the target project: `ledger.md`, `tree.xml`, `figma/`,
`render/`, `diff/`.

**Add `.figma-parity/` to the project's `.gitignore` before writing anything
into it.** These are the user's own extractions — their design exports, their
screenshots, their ledger. They belong on their machine and must never end up
in a commit, in this skill's repo, or anywhere shared. Write nothing outside
this folder, and never write back into the plugin's own directory.

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

**The ledger must exist before the second extraction.** After the first
`get_design_context` returns, write its rows to `.figma-parity/ledger.md` and
confirm the file is on disk before calling the tool again. A run that extracts
five sections and then writes one ledger at the end has already lost whatever
the context dropped along the way — which is the failure this phase exists to
prevent.

**Text layer names are their content.** Figma names a text node after the text
it holds, so `get_metadata` alone yields every string in the design. Read them
out of `tree.xml` rather than spending a `get_design_context` call per label.

**Budget the descent.** Each `get_design_context` on a rich component costs
several thousand tokens of context. Extract components, not instances; if a
tree has more than ~15 unique components, extract the ones that carry the
screen's substance first and record the rest as `☐` with a note, rather than
running out of context halfway and losing everything.

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
per value, because a row is what gets ticked. Work this list; a property you do
not look for is a property you will not notice is missing.

**Text** — font-family, font-size, font-weight, line-height, letter-spacing,
color, text-align, vertical-align, text-transform, text-decoration,
font-style, truncation / max-lines, white-space, list style, and the literal
copy itself (retyped text is a defect).

**Box** — width, height, min/max width and height, aspect ratio, padding on
each of the four sides *individually*, margin, border-radius per corner,
corner smoothing, overflow / clip-content, opacity, rotation, z-order.

**Layout** — auto-layout direction, gap (row and column separately), spacing
mode (packed vs space-between), padding, alignment on both axes, wrap, sizing
per axis (hug / fill / fixed), and for absolutely positioned children their
constraints (pin left/right/top/bottom, centre, scale). **Constraints are the
usual reason a layout is right at one width and wrong at another.**

**Fill** — solid colour, or for a gradient: type (linear/radial/angular/
diamond), every stop with its position and colour, and the angle. For an image
fill: the scale mode (fill / fit / crop / tile), focal point, and rotation.
Multiple stacked fills each get a row.

**Stroke** — colour, width per side if they differ, alignment
(inside/centre/outside — this changes the box's rendered size), dash pattern,
and cap/join.

**Effects** — drop shadow and inner shadow (x, y, blur, spread, colour, and
whether it is behind translucent fills), layer blur, background blur. Each
effect is its own row; a stack of three shadows is three rows.

**Blend mode** — on the layer and on individual fills. Easy to miss and
impossible to recover from a screenshot.

**Component** — for an instance: which main component, every variant property
and its value, and any override that differs from the main component. Figma
flags when an instance's layout differs from its main — that difference is
always a row.

**Asset** — the exported source, intrinsic size, rendered size, and the export
scale.

Run `get_variable_defs` **once** for the file's token map, and prefer the token
name over the raw value in the `expected` column — record both:
`var(--text-primary) #1A1A1A`. A raw hex where a token exists is a defect even
when the pixels match, because the next theme change will break it.

### Sources you must consult, not just get_design_context

`get_design_context` is the main source but it is not the only one, and the
things it omits are exactly the ones that get lost:

| Source | What it adds | When |
|---|---|---|
| `get_code_connect_map` | the codebase component a Figma component is **already mapped to** | **First, before writing any component.** A mapped component must be used, not reimplemented — this outranks every other hint |
| `get_variable_defs` | the token map | once per file |
| `get_motion_context` | transitions, easing, duration, animated properties | whenever a node is animated or `get_design_context` says to call it |
| `download_assets` | the real exported bytes for images and SVGs | for every icon and image — never hand-author vector data |
| `search_design_system` / `get_libraries` | existing library components to reuse | before creating anything that looks like a shared component |
| `get_shader_fill` / `get_shader_effect` | shader-based fills and effects | when `list_shader_fills` / `list_shader_effects` report any |

**Motion is a first-class requirement, not a flourish.** A design with a 200ms
ease-out on a hover has that written down somewhere; if you do not extract it,
it is silently gone and no diff will ever tell you. Record duration, easing,
delay, and the properties that animate — each as its own row.

### States and breakpoints are invisible to a pixel diff

The rendered default state cannot reveal a missing hover style. Enumerate them
explicitly into the ledger's own tables from the component's variants and from
any interactive prototype links: hover, focus, active, disabled, loading,
error, empty, expanded/collapsed, selected. Each is a row.

### Designer notes are requirements, not decoration

**Dev Mode annotations** arrive inside `get_design_context` alongside the
layout and colour data. They are where a designer puts what the geometry cannot
express — *"this is disabled until the form validates"*, *"copy is placeholder,
final text from legal"*, *"8px not 12, we changed this"*.

**Record every annotation as its own `☐` row**, attached to the node it sits
on. An annotation read and then not written down is lost exactly like any other
property — and it is usually the most important thing on the node, because
someone typed it deliberately.

An annotation that is an instruction (*"use the new icon"*) becomes a row you
tick when you have done it. An annotation that is a question or a decision the
design has not settled (*"should this scroll?"*) becomes a `✖` row with the
reason, and is surfaced to the user — do not silently pick an answer.

**Figma comments** — the pin threads people leave on the canvas — are a
different thing and do **not** come through the MCP. See Phase 0 for reading
them; when they are unavailable, say so rather than implying the design carried
no discussion.

### Screenshots

`get_screenshot` per unit and for the root. It returns a short-lived URL plus
curl instructions — **download via curl into `.figma-parity/figma/`**. Do not
request base64 inline; it costs enormously more context for the same pixels.

---

## Phase 2 — Build, audit, or reconcile

**Do not assume you are starting from nothing.** Ask the project:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" mode .figma-parity/tree.xml .
```

It reports which of the design's nodes already appear in the code and returns
one of three modes. Getting this wrong is expensive in both directions:
rebuilding a finished screen destroys working code, and auditing a half-built
one silently skips everything that was never written.

### `build` — nothing is there yet

Implement from scratch, following the translation rules below.

**If the report says low confidence, stop and ask.** No `data-node-id` anywhere
means either the screen genuinely does not exist, or it was built by hand
without the attribute — and those are indistinguishable from the outside.
Rebuilding over someone's working screen because you could not see it is the
worst outcome available here.

### `audit` — it is already built

**Do not rebuild it.** Extract the design into the ledger exactly as Phase 1
describes — every expected value still has to be written down before anything
can be compared against it — then:

1. Make sure the existing elements carry `data-node-id`. Add it where missing;
   it changes no behaviour and it is the only link between a rendered element
   and its design node.
2. Run the measure step in Phase 3.
3. Report the numeric mismatches and fix **only** those.

The user asked what is wrong, not for a new version of their screen. Ask before
touching anything not on the list.

### `reconcile` — some of it exists

The common case, and the one that needs the most care. Do both jobs and keep
them apart:

- **Audit what exists.** Measure it, report drift, fix what is measurably wrong.
- **Build only what is missing.** The nodes absent from the report are the work.
- **Do not rewrite working code** because it is not how you would have written
  it. A component that measures correctly is correct.

Report the two halves separately in your summary, so the user can see what was
changed versus what was added.

### Translation rules (all three modes)

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

### Measure the numbers before you compare the pictures

**A pixel diff is the wrong instrument for spacing and sizing.** Change one
container's padding by 4px and every border on the screen moves; the diff
collapses that into a single enormous sparse region that says "something
shifted" — which cannot answer *"is this gap 12 or 16?"*. Worse, in ledger-only
mode there is no diff at all, so nothing measures the built UI and the only
"check" left is the model comparing the design against code it wrote itself.
That is a memory test, not a verification.

The browser already knows the answer exactly. Ask it:

1. **Put `data-node-id` on the elements you build.** Without it there is nothing
   to line a ledger row up against. This is not decoration — it is what makes
   the implementation measurable.

2. **Dump the computed styles** by running this in the page and saving the
   result to `.figma-parity/actual.json`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" snippet
```

3. **Compare the numbers:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" measure \
  .figma-parity/ledger.md .figma-parity/actual.json
```

You get arithmetic, not opinion:

```
FAIL  47/48 measured values match (1 mismatch)
  4:1911
    gap: design says 12px, browser rendered 8px   (ledger line 84)
```

No threshold, no antialiasing, no judgement — and it points at the exact ledger
row. Hex and `rgb()` are compared as the same colour, `var(--s-600) 24px`
compares as 24px, and sub-pixel rounding is not reported as a bug.

**Fix what this reports before looking at any pixel diff.** A spacing error
found here is also the cause of most of the diff's noise.

### Then the pixel diff, for what numbers cannot see

1. Render the implemented UI and screenshot it per `references/rendering.md`,
   at the Figma frame's width and `deviceScaleFactor: 2`.
2. Export the Figma node at matching pixel dimensions (`get_screenshot` with
   `maxDimension` set to the render's long edge).
3. Run the diff:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" diff \
  .figma-parity/figma/<node>.png .figma-parity/render/<node>.png --out .figma-parity/diff
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/parity.py" coverage .figma-parity/ledger.md
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
| node | prop | expected | status | note |
|---|---|---|---|---|
| 4:1911 | font-size | 18px | ☐ | |
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

Every row is one checkable value, and every row names its node. `ledger.py`
counts the boxes; `tree.py` counts which of the design's nodes those ids
actually account for. Both numbers are computed from disk, neither is taken
from the model's word — which is why a row without a node id is worse than no
row at all.

**Status is always second-to-last, note always last.** The reason for a `⚠` or
`✖` is read from the final column; put the status there instead and a perfectly
good justification is invisible to the gate.
