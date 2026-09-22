# Obsidian-Native Memory Workspace UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the Memory Workspace plugin into an Obsidian-native Search/Reflect view with theme-safe cards, clear states, and independently scrollable result regions.

**Architecture:** Keep the existing `MemoryWorkspaceView` and MCP client boundaries. Improve the view structure with focused render/state helpers, send `precise: true` only for Search, and express all visual treatment through `styles.css` using Obsidian theme variables and native controls.

**Tech Stack:** TypeScript, Obsidian plugin API, native DOM elements, CSS custom properties, Vitest, TypeScript compiler, esbuild, Obsidian CLI.

## Global Constraints

- Reuse Obsidian theme variables and native control styles; do not hard-code light/dark colors.
- Do not add external fonts, icon packs, images, CSS frameworks, or runtime dependencies.
- Keep Search curated-only by default; source pages remain opt-in.
- Keep Search `precise: true`; keep Reflect semantic through `memory_reflect` without the precise flag.
- Preserve independent scrolling for Search results and Reflect output.
- Do not reintroduce Browse or change the MCP endpoint/retrieval contract.
- Keep native keyboard submission, accessible labels, visible focus states, and retryable errors.

---

### Task 1: Lock the view contract with focused tests

**Files:**
- Modify: `obsidian-plugin/tests/view.test.ts`
- Reference: `obsidian-plugin/src/view.ts`

**Interfaces:**
- Consumes: `MemoryWorkspaceView` and the existing mocked `McpClient.callTool` test seam.
- Produces: regression coverage for the final DOM hooks and request payloads used by the styling work.

- [ ] **Step 1: Extend the view test fixture with a result shape that exercises metadata and actions**

Use a result containing `path`, `title`, `snippet`, `score`, and `match`, plus a mocked vault file so the Open page action is enabled.

```ts
const result = {
  path: "people/example.md",
  title: "Example Person",
  snippet: "A useful fact",
  score: 0.92,
  match: "exact",
};
```

- [ ] **Step 2: Add assertions for the native Search structure and precise request**

After opening the view and submitting `useful`, assert the following selectors/text:

```ts
expect(view.containerEl.querySelector(".memory-workspace-header")).toBeTruthy();
expect(view.containerEl.querySelector(".memory-search-toolbar")).toBeTruthy();
expect(view.containerEl.querySelector(".memory-results-count")).toBeTruthy();
expect(view.containerEl.querySelector(".memory-card-meta")).toBeTruthy();
expect(view.containerEl.textContent).toContain("Exact match");
expect(callTool).toHaveBeenCalledWith(
  "memory_search",
  expect.objectContaining({ query: "useful", include_sources: false, precise: true }),
);
```

- [ ] **Step 3: Add assertions for Reflect loading/output/error states**

Cover the existing success and error tests with the planned hooks:

```ts
expect(view.containerEl.querySelector(".memory-reflect-output")).toHaveAttribute("aria-live", "polite");
expect(view.containerEl.querySelector(".memory-reflection-card")).toBeTruthy();
expect(view.containerEl.querySelector(".memory-sources-list")).toBeTruthy();
```

Keep the existing retry assertion and add a check that the error region has `role="alert"`.

- [ ] **Step 4: Run the focused tests and confirm they fail against the current DOM**

Run:

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki/obsidian-plugin
npm test -- --run tests/view.test.ts
```

Expected: FAIL because the new semantic class names, metadata, count, and accessibility attributes do not yet exist.

- [ ] **Step 5: Commit the test contract**

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki
git add obsidian-plugin/tests/view.test.ts
git commit -m "test: define native memory workspace UI contract"
```

### Task 2: Refine the TypeScript view structure and states

**Files:**
- Modify: `obsidian-plugin/src/view.ts`
- Modify: `obsidian-plugin/src/types.ts` only if the result metadata needs a typed optional field.
- Test: `obsidian-plugin/tests/view.test.ts`

**Interfaces:**
- Consumes: `McpClient.callTool<SearchResult>` and `McpClient.callTool<ReflectResult>`.
- Produces: stable DOM hooks including `.memory-search-toolbar`, `.memory-results-count`, `.memory-card-meta`, `.memory-reflection-card`, `.memory-sources-list`, and accessible state regions.

- [ ] **Step 1: Add small DOM helpers for attributes and result metadata**

Keep the existing `element` helper and add a focused helper that applies attributes without introducing a framework:

```ts
const withAttributes = (node: HTMLElement, attributes: Record<string, string>): HTMLElement => {
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
};
```

Use it for `aria-label`, `aria-live`, `role`, and `title` attributes.

- [ ] **Step 2: Give Search its semantic toolbar and result region**

Change the form class to `memory-toolbar memory-search-toolbar`, preserve the existing inputs and source checkbox, and add an empty result count element beside the result region. The initial count should be visually hidden or empty until a response arrives.

The Search call must remain:

```ts
this.client.callTool<SearchResult>("memory_search", {
  query: this.searchQuery,
  limit: 20,
  precise: true,
  ...Object.fromEntries(Object.entries(this.searchFilters).filter(([, value]) => value !== undefined)),
});
```

Set the result region to `role="region"`, `aria-label="Search results"`, and `aria-live="polite"`.

- [ ] **Step 3: Add result count and metadata without changing result ordering**

After a successful response, update the count text to `${response.results.length} memories` and render each card. In `renderHit`, show a compact metadata row only when score or match exists:

```ts
const meta = element("div", "memory-card-meta");
if (hit.match) meta.appendChild(element("span", "memory-match-badge", formatMatch(hit.match)));
if (typeof hit.score === "number") meta.appendChild(element("span", "memory-score", `${Math.round(hit.score * 100)}% match`));
```

Use a small local `formatMatch` mapping for `exact`, `phrase`, `anchor`, and `embedding`; unknown values should be title-cased rather than discarded.

- [ ] **Step 4: Add semantic Reflect output hooks and state attributes**

Set the Reflect output to `role="region"`, `aria-label="Reflection result"`, and `aria-live="polite"`. Render the reflection text inside `.memory-reflection-card`; render source chips inside `.memory-sources-list`. Keep source paths as text and preserve the current source order.

- [ ] **Step 5: Make loading, empty, and error states accessible and consistent**

Use a shared state class with `role="status"` for loading/empty states. Give retryable errors `role="alert"`; keep the Retry button and callback behavior unchanged. Empty Search must continue to say `No matching memories found.` and empty Reflect must continue to say `Enter a question to reflect.`

- [ ] **Step 6: Run tests and type checking**

Run:

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki/obsidian-plugin
npm test -- --run tests/view.test.ts
npx tsc --noEmit
```

Expected: all view tests pass and TypeScript exits with code 0.

- [ ] **Step 7: Commit the view changes**

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki
git add obsidian-plugin/src/view.ts obsidian-plugin/src/types.ts obsidian-plugin/tests/view.test.ts
git commit -m "feat: refine native memory workspace view"
```

### Task 3: Apply the Obsidian-native visual system

**Files:**
- Modify: `obsidian-plugin/styles.css`
- Reference: `obsidian-plugin/src/view.ts`

**Interfaces:**
- Consumes: the semantic class hooks from Task 2 and Obsidian theme variables.
- Produces: a polished dark/light-compatible layout with clear hierarchy and independently scrollable Search/Reflect regions.

- [ ] **Step 1: Establish pane-safe shell and typography tokens**

Use only Obsidian variables for colors and add local spacing/radius/shadow custom properties on `.memory-workspace`. Keep the content width readable while allowing the view to use narrow panes:

```css
.memory-workspace {
  --memory-radius: 10px;
  --memory-gap: 12px;
  min-height: 100%;
  padding: clamp(18px, 3vw, 34px);
  color: var(--text-normal);
  background: var(--background-primary);
}
```

Add `box-sizing: border-box` for all plugin descendants and preserve native text/input sizing.

- [ ] **Step 2: Style header and tabs as native Obsidian navigation**

Keep the header compact, use muted eyebrow text, and give tabs a transparent native button surface with an accent underline and visible `:focus-visible` outline. Avoid gradients and fixed RGB colors.

- [ ] **Step 3: Style Search toolbar and filter hierarchy**

Make `.memory-search-toolbar` a two-level responsive grid: the query input spans the available row; type/path/source/button controls wrap beneath it. Use native inputs/buttons, modest border radius, and `var(--background-modifier-border)` for separators.

- [ ] **Step 4: Style cards, badges, excerpts, and actions**

Use a subtle secondary background and border for `.memory-card`, emphasize title text, keep paths muted, clamp long metadata visually without hiding content from accessibility, and style the Open page button as a quiet native action. Match badges to `--interactive-accent` with theme-safe text/background variables.

- [ ] **Step 5: Style shared states and Reflect output**

Create a consistent dashed state container for loading/empty/error. Give `.memory-reflection-card` a callout-like accent edge, readable line height, and preserved whitespace. Make `.memory-sources-list` wrap chips cleanly without overflowing the pane.

- [ ] **Step 6: Preserve independent scrolling and narrow-pane behavior**

Keep:

```css
.memory-results,
.memory-reflect-output {
  max-height: min(60vh, 560px);
  overflow-y: auto;
  overscroll-behavior: contain;
}
```

Add a media query for narrow panes that collapses the toolbar to one column and reduces horizontal padding without changing the scroll behavior.

- [ ] **Step 7: Build and run the plugin tests**

Run:

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki/obsidian-plugin
npm test
npx tsc --noEmit
npm run build
```

Expected: all tests pass, TypeScript succeeds, and esbuild produces `main.js`.

- [ ] **Step 8: Commit the visual changes**

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki
git add obsidian-plugin/styles.css
git commit -m "feat: polish native memory workspace styling"
```

### Task 4: Install and verify in the active Obsidian vault

**Files:**
- Modify generated installed artifacts: `/Volumes/DATA/agent-vault/.obsidian/plugins/obsidian-memory-workspace/main.js` and `styles.css`
- Verify: active Obsidian Memory Workspace view

**Interfaces:**
- Consumes: the production build from Task 3.
- Produces: a verified active plugin with no runtime errors and visually correct Search/Reflect states.

- [ ] **Step 1: Copy the production bundle into the active vault**

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki
cp obsidian-plugin/main.js obsidian-plugin/styles.css /Volumes/DATA/agent-vault/.obsidian/plugins/obsidian-memory-workspace/
```

- [ ] **Step 2: Reload and inspect runtime errors**

```bash
obsidian plugin:reload id=obsidian-memory-workspace
obsidian dev:errors
```

Expected: reload succeeds and `dev:errors` reports no plugin errors.

- [ ] **Step 3: Exercise Search and Reflect through the live view**

Verify these exact interactions:

1. Open Search and confirm source inclusion is unchecked.
2. Search `girlfriend` and confirm the canonical person result remains visible with metadata and Open page action.
3. Search a missing multiword phrase and confirm the empty state is readable and contained.
4. Switch to Reflect, submit `đầu tư`, and confirm the reflection plus source chips render inside the scrollable output region.
5. Resize the pane narrow enough to trigger the responsive layout and confirm controls wrap without horizontal overflow.

- [ ] **Step 4: Inspect DOM and capture a screenshot for visual QA**

```bash
obsidian dev:dom selector=".memory-workspace" text
obsidian dev:screenshot path=/tmp/obsidian-memory-workspace-ui.png
```

Check that the DOM contains `.memory-search-toolbar`, `.memory-results`, `.memory-reflection-card`, and `.memory-reflect-output`, and that no Browse tab exists.

- [ ] **Step 5: Commit only source changes if generated artifacts are ignored**

```bash
cd /Volumes/DATA/.hermes/plugins/obsidianwiki
git status --short
git diff --check
```

The source commits from Tasks 1–3 are the deliverable. Installed generated artifacts are verified in the active vault even if repository ignore rules exclude `main.js` and `styles.css`.
