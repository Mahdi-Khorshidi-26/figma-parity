# Resolving a render method

Phase 3 needs one thing: a PNG of the implemented UI at a known width and
scale. How to get it depends on the project. Detect, don't assume.

## Detection order

Probe the target project in this order and stop at the first match.

| Signal | Stack | Render method |
|---|---|---|
| `next` in package.json deps | Next.js | dev server + browser |
| `vite` + `react`/`vue`/`svelte` | Vite SPA | dev server + browser |
| `@storybook/*` | Storybook | story URL + browser |
| `expo` / `react-native` | Expo / RN | iOS Simulator screenshot |
| `layout/theme.liquid` or `sections/*.liquid` | Shopify theme | `shopify theme dev` + browser |
| `index.html` at root, no framework | Static | `file://` URL + browser |
| none of the above | unknown | **ledger-only mode** |

## Browser-rendered stacks

1. **Start the dev server.** Read the `scripts` block for the real command
   (`npm run dev`, `pnpm dev`, `yarn dev`). Run it in the background and wait
   for the port to answer before screenshotting — a screenshot of a
   still-compiling page is a false diff and will send the loop chasing ghosts.
2. **Set the viewport to the Figma frame's width** and `deviceScaleFactor: 2`.
   The Figma export must be requested at matching pixel dimensions, or the diff
   reports a size mismatch and every region is meaningless.
3. **Clip to the component**, not the whole page — screenshot the element whose
   bounding box corresponds to the Figma node. A full-page shot diffed against
   a single-frame export is noise.
4. **Wait for fonts and images.** `document.fonts.ready`, and let images settle.
   A screenshot taken during font swap diffs against everything.
5. **Freeze motion.** Disable animations and transitions before the shot, or
   consecutive runs disagree with each other:

```css
*, *::before, *::after {
  animation: none !important;
  transition: none !important;
  caret-color: transparent !important;
}
```

Playwright MCP is declared in `.mcp.json`, so both Claude Code and the Agent SDK
have browser tools available. Save output to `.figma-parity/render/<node>.png`.

## Interactive states

The default-state screenshot cannot show hover, focus, or disabled. For each
state row in the ledger, drive the element into that state and take a separate
screenshot. Hover and focus are driven with real browser input; `disabled`,
`loading`, `error`, and `empty` usually need a prop or fixture. If a state
cannot be reached, that is a `✖` row with the reason — not a silent skip.

## Expo / React Native

Screenshots come from the iOS Simulator rather than a browser. Boot the
simulator, launch the app, navigate to the screen, capture. Slower and harder
to clip precisely: prefer diffing the full screen against a full-frame Figma
export rather than trying to clip a component.

## Ledger-only mode

When no render method resolves — no dev server, a component that cannot be
reached in isolation, a broken build — **say so explicitly and continue.** The
ledger still forces complete extraction and per-property implementation, which
is most of the value. What is lost is the pixel measurement, so:

- Record it in `## Unresolved` at the top of the ledger.
- The run may reach ledger-complete but **must not be reported as
  pixel-verified.** Those are different claims and conflating them is exactly
  the dishonesty this whole design exists to prevent.
