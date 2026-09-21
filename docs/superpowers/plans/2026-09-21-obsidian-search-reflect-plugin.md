# Obsidian Search and Reflect Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Obsidian workspace plugin that searches, browses, reads, and reflects over the existing Streamable HTTP MCP server.

**Architecture:** Create an isolated TypeScript plugin under `obsidian-plugin/`. A focused MCP client owns JSON-RPC/Streamable HTTP transport and a workspace view owns the Search, Browse, and Reflect dashboard. The plugin calls only existing `memory_search`, `memory_list`, `memory_read`, and `memory_reflect` tools.

**Tech Stack:** TypeScript, Obsidian plugin API, esbuild, Vitest, DOM APIs, native `fetch`.

## Global Constraints

- Default endpoint: `http://127.0.0.1:8765/mcp`.
- First release is read-only; do not call `memory_write`, `memory_append`, or `memory_delete`.
- Reflection is displayed only and never saved automatically.
- Do not add a REST API or change Python MCP behavior.
- Use Obsidian CSS variables and support light/dark themes.
- Do not send credentials by default.

---

### Task 1: Scaffold the isolated Obsidian plugin

**Files:**
- Create: `obsidian-plugin/package.json`
- Create: `obsidian-plugin/tsconfig.json`
- Create: `obsidian-plugin/esbuild.config.mjs`
- Create: `obsidian-plugin/manifest.json`
- Create: `obsidian-plugin/src/main.ts`
- Create: `obsidian-plugin/src/types.ts`
- Create: `obsidian-plugin/tests/setup.ts`

**Interfaces:**
- Produces a buildable plugin package with entrypoint `main.js` and stylesheet `styles.css`.
- `PluginSettings` must include `endpoint: string` with default `http://127.0.0.1:8765/mcp`.

- [ ] **Step 1: Write package and compiler configuration**

Create scripts `build`, `dev`, and `test`; configure TypeScript for strict
checking, ES2020, DOM types, and no output because esbuild bundles the plugin.
Configure the manifest with id `obsidian-memory-workspace`, name `Memory
Workspace`, version `0.1.0`, minimum Obsidian version `1.5.0`, and desktop
support.

- [ ] **Step 2: Define shared types**

In `src/types.ts`, define:

```ts
export const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/mcp";
export interface PluginSettings { endpoint: string; }
export interface SearchFilters {
  type?: string;
  tags?: string[];
  path_prefix?: string;
  include_sources?: boolean;
}
export interface SearchHit { path: string; title?: string; score?: number; excerpt?: string; [key: string]: unknown; }
export interface SearchResult { results: SearchHit[]; total?: number; [key: string]: unknown; }
export interface MemoryPage { path: string; content: string; revision?: string; [key: string]: unknown; }
export interface ReflectResult { query?: string; reflection?: string; sources?: Array<{ path: string }>; error?: string; message?: string; }
```

- [ ] **Step 3: Install dependencies and verify the scaffold**

Add a minimal `src/main.ts` export so esbuild has an entrypoint, then run
`cd obsidian-plugin && npm install && npm test && npm run build`.
Expected: Vitest exits successfully and esbuild emits `main.js`.

- [ ] **Step 4: Commit the scaffold**

```bash
git add obsidian-plugin
git commit -m "feat: scaffold obsidian memory workspace plugin"
```

### Task 2: Implement and test the Streamable HTTP MCP client

**Files:**
- Create: `obsidian-plugin/src/mcpClient.ts`
- Create: `obsidian-plugin/tests/mcpClient.test.ts`

**Interfaces:**
- `McpClient` constructor accepts `endpoint: string` and optional `fetcher: typeof fetch`.
- `initialize(): Promise<void>` initializes the MCP session.
- `callTool<T>(name: string, arguments_: Record<string, unknown>): Promise<T>` calls one MCP tool.

- [ ] **Step 1: Write failing transport tests**

Use a fake fetch implementation to assert that initialization sends JSON-RPC
`initialize`, stores `Mcp-Session-Id`, and adds that header to the next request.
Add tests for JSON responses, one-event SSE responses, JSON-RPC errors, non-OK
responses, and timeout/abort errors.

- [ ] **Step 2: Run focused tests and verify RED**

Run `cd obsidian-plugin && npx vitest run tests/mcpClient.test.ts`.
Expected: failures report that `McpClient` is missing or does not implement the
expected request behavior.

- [ ] **Step 3: Implement the minimal client**

Use `POST`, `Content-Type: application/json`, and `Accept: application/json,
text/event-stream`. Send protocol version `2025-03-26`, empty capabilities,
and client info during initialization. Parse direct JSON or the first `data:`
SSE event. Extract text from MCP `result.content` blocks and JSON-decode a text
block when possible. Throw display-safe `Error` objects for protocol and
transport failures.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run `cd obsidian-plugin && npx vitest run tests/mcpClient.test.ts`.
Expected: all transport tests pass.

- [ ] **Step 5: Commit the client**

```bash
git add obsidian-plugin/src/mcpClient.ts obsidian-plugin/tests/mcpClient.test.ts
git commit -m "feat: add streamable http mcp client"
```

### Task 3: Build the Obsidian workspace view

**Files:**
- Create: `obsidian-plugin/src/view.ts`
- Create: `obsidian-plugin/styles.css`
- Create: `obsidian-plugin/tests/view.test.ts`

**Interfaces:**
- `MemoryWorkspaceView extends ItemView` implements `getViewType()`, `getDisplayText()`, and `onOpen()`.
- Constructor receives `McpClient`, `App`, and a settings save callback.

- [ ] **Step 1: Write failing view tests**

Using a fake client, test that the view renders Search, Browse, and Reflect
tabs; a search result card shows its returned path; an empty result shows an
empty state; a reflection renders the answer and source path; and a rejected
request renders an error with a Retry button.

- [ ] **Step 2: Run focused view tests and verify RED**

Run `cd obsidian-plugin && npx vitest run tests/view.test.ts`.
Expected: failures report that `MemoryWorkspaceView` is missing.

- [ ] **Step 3: Implement the dashboard**

Render a root element with `memory-workspace` class and three tab buttons. Keep
one active panel mounted at a time. Search calls:

```ts
client.callTool<SearchResult>("memory_search", {
  query,
  limit: 20,
  ...(filters.type ? { type: filters.type } : {}),
  ...(filters.path_prefix ? { path_prefix: filters.path_prefix } : {})
});
```

Browse calls `memory_list` and renders page paths; selecting a page calls
`memory_read`. Reflect calls `memory_reflect` with `{ query, limit: 8 }` and
renders only the returned reflection and source labels. Add loading, empty,
offline/error, and retry states. For an existing vault path, open the note
through `app.workspace.openLinkText`; otherwise render a disabled source label.

- [ ] **Step 4: Add theme-aware styles**

Use Obsidian variables such as `--background-primary`, `--background-secondary`,
`--text-normal`, `--text-muted`, `--interactive-accent`, and
`--background-modifier-border`. Include responsive grid/card styles without
external CSS frameworks.

- [ ] **Step 5: Run focused view tests and verify GREEN**

Run `cd obsidian-plugin && npx vitest run tests/view.test.ts`.
Expected: all view behavior tests pass.

- [ ] **Step 6: Commit the workspace view**

```bash
git add obsidian-plugin/src/view.ts obsidian-plugin/styles.css obsidian-plugin/tests/view.test.ts
git commit -m "feat: add obsidian memory workspace view"
```

### Task 4: Wire plugin lifecycle, settings, and commands

**Files:**
- Create: `obsidian-plugin/src/main.ts`
- Create: `obsidian-plugin/src/settings.ts`
- Modify: `obsidian-plugin/src/types.ts`
- Create: `obsidian-plugin/tests/main.test.ts`

**Interfaces:**
- Register view type `memory-workspace`.
- Register command `Open memory workspace`.
- Expose a settings tab with an endpoint text field and Restore default button.

- [ ] **Step 1: Write failing lifecycle tests**

Test default settings, `loadData()` overrides, and `onload()` registrations
with an Obsidian test double.

- [ ] **Step 2: Run focused lifecycle tests and verify RED**

Run `cd obsidian-plugin && npx vitest run tests/main.test.ts`.
Expected: failures report missing plugin lifecycle exports or registrations.

- [ ] **Step 3: Implement lifecycle and settings**

Create `MemoryWorkspacePlugin`. In `onload()`, load settings, create an
`McpClient`, register the view, and add the command. `activateView()` should
reuse an existing leaf when possible and otherwise create a right-sidebar
leaf. Use `addSettingTab` for the endpoint field, save on change, and pass the
same client instance to new views.

- [ ] **Step 4: Run tests and verify GREEN**

Run `cd obsidian-plugin && npx vitest run tests/main.test.ts`.
Expected: lifecycle and settings tests pass.

- [ ] **Step 5: Commit plugin wiring**

```bash
git add obsidian-plugin/src/main.ts obsidian-plugin/src/settings.ts obsidian-plugin/src/types.ts obsidian-plugin/tests/main.test.ts
git commit -m "feat: wire obsidian memory workspace plugin"
```

### Task 5: Document installation and verify end-to-end behavior

**Files:**
- Modify: `README.md`
- Modify: `obsidian-plugin/manifest.json` if packaging metadata needs adjustment

- [ ] **Step 1: Add installation instructions**

Document building with `cd obsidian-plugin && npm install && npm run build`,
copying `main.js`, `manifest.json`, and `styles.css` into the vault's
`.obsidian/plugins/obsidian-memory-workspace/` directory, enabling the plugin,
and setting the MCP endpoint if it differs from the loopback default.

- [ ] **Step 2: Run all plugin and Python tests**

Run:

```bash
cd obsidian-plugin && npm test && npm run build
cd .. && pytest -q
```

Expected: plugin tests, plugin build, and the existing Python suite all exit
with status 0.

- [ ] **Step 3: Verify in Obsidian when available**

Run `obsidian plugin:reload id=obsidian-memory-workspace`, then
`obsidian dev:errors` and `obsidian dev:console level=error`. Open the command
palette, launch `Open memory workspace`, and inspect the dashboard with
`obsidian dev:dom selector=".memory-workspace" text`.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md obsidian-plugin
git commit -m "docs: document obsidian memory workspace plugin"
```
