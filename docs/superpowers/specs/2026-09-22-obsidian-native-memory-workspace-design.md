# Obsidian-Native Memory Workspace UI

**Date:** 2026-09-22  
**Status:** Design approved in conversation; implementation pending spec review

## Goal

Polish the native Obsidian Memory Workspace plugin without changing its MCP contract or retrieval behavior. The result should feel like a calm, built-in Obsidian view in both dark and light themes, with Search remaining the primary workflow and Reflect remaining easy to read.

## Design direction

Use Obsidian-native styling rather than a separate web-app visual language:

- Reuse theme variables such as `--background-primary`, `--background-secondary`, `--background-modifier-border`, `--text-normal`, `--text-muted`, `--interactive-accent`, and native control styles.
- Keep the visual density moderate: compact header, generous but not excessive spacing, and readable cards.
- Avoid external fonts, icon packs, images, CSS frameworks, and hard-coded light/dark colors.
- Make dark/light behavior and compatibility with community themes a first-class constraint.

## Layout

### Shared shell

- A compact header with a small eyebrow, title, and one-line description.
- Native-style Search and Reflect tabs with a clear active indicator.
- A centered content column that adapts to the available Obsidian pane width.
- No Browse tab and no new navigation surface.

### Search

- Query input is the dominant control and occupies the full available row when possible.
- Type and path filters form a secondary row.
- Source inclusion remains an explicit checkbox and defaults to off.
- Search uses `precise: true`, preserving exact/phrase matching and avoiding unrelated semantic neighbors.
- Results are displayed in an independently scrollable region.
- Each result card presents path, title, match/score metadata when useful, excerpt, and an Open page action.
- Empty, loading, and error states use the same visual container language as result cards.

### Reflect

- A clear question textarea with a native primary action.
- A separate independently scrollable output region.
- Reflection text is presented in a callout-like panel with readable line height and preserved paragraphs.
- Source paths appear as compact native-looking chips below the reflection.
- Reflect continues using semantic retrieval through `memory_reflect`; the UI does not send Search's precise-mode flag.

## Component boundaries

Keep the current view implementation, but organize rendering around small focused methods/components:

- `renderShell`: shared header, tabs, and panel host.
- `renderSearch`: search copy, toolbar, result region, and result count/state.
- `renderHit`: one result card and its open action.
- `renderReflect`: question form and reflection output region.
- Shared state helpers for loading, empty, and retryable error presentation.

No new runtime dependency is needed. Existing `McpClient`, `SearchResult`, and `ReflectResult` interfaces remain the integration boundary.

## Behavior and accessibility

- Preserve the current endpoint/session recovery behavior.
- Preserve independent scrolling for Search results and Reflect output.
- Keep native keyboard form submission.
- Add or preserve accessible labels for query, filters, source toggle, result region, and reflection output.
- Use `aria-live` where it improves announcement of loading, empty, and error transitions without making the UI noisy.
- Keep focus indicators visible through theme variables.

## Verification

- Update plugin view tests for the native layout, default curated-only Search, source toggle, result cards, and empty/error states.
- Run plugin unit tests.
- Run TypeScript type checking.
- Build the production plugin bundle.
- Install the built bundle into the active vault and reload it with the Obsidian CLI.
- Check `obsidian dev:errors`, inspect the DOM, and capture a screenshot in the active Obsidian vault for visual verification.
- Verify both Search and Reflect regions remain scrollable after the visual changes.

## Scope exclusions

- No MCP endpoint or retrieval algorithm redesign.
- No Browse tab reintroduction.
- No external design system or framework.
- No automatic creation or promotion of new memory pages.
- No changes to Docker compose beyond what is required to run the existing plugin build.
