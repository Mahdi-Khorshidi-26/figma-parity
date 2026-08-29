---
description: Implement a Figma design as code with verified pixel parity — walks every node, ledgers every property, renders and diffs the result, and won't claim done until it's measured
disable-model-invocation: false
---

Implement the Figma design at: $ARGUMENTS

Use the `figma-parity` skill and follow every phase in order. Its rules are not
optional. In particular:

1. **Do not call `get_design_context` on a screen or page root.** Call
   `get_metadata` first to get the tree, then descend and extract subtree by
   subtree. A single call on a root truncates and silently loses detail — that
   is the entire failure this skill exists to prevent.
2. **Write each extraction unit into `.figma-parity/ledger.md` before
   extracting the next one**, and record the total node count on the
   `Coverage:` line.
3. **Render the result and pixel-diff it** against the Figma export. Act on the
   numbered diff regions, and read each region's fill density — a large
   `sparse` region is one layout shift hiding every smaller defect inside it,
   so fix it and re-measure before concluding anything.
4. **Dispatch the `figma-parity-auditor` subagent** before you consider
   stopping. It checks what a pixel diff structurally cannot see: hover and
   disabled states, other breakpoints, hardcoded hex where a token was
   specified, hand-drawn icons, and accessibility.
5. **Do not declare this complete yourself.** Completion means: every ledger row
   resolved, no unjustified deviations, coverage fully walked, diff regions
   under threshold, and the auditor clean. If you cannot finish something,
   write it as a `✖` row with the reason.

An honest "8 of 213 rows unresolved, here they are" is a success. A false
"complete" is the one unacceptable outcome.

If no Figma URL was given, ask for one — including a `node-id` if possible.
