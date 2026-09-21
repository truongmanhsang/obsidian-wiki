# Memory Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate React/Vite calm knowledge workspace backed by real JSON endpoints for memory search, browsing, page reading, and reflection.

**Architecture:** Add a small Starlette/Uvicorn HTTP adapter in `web_api.py` that delegates to `MemoryStore` and the existing `_run_reflection` path. Add a `web/` Vite React TypeScript SPA with a single app shell, view state for Search/Browse/Reflect/Page detail, and a typed API client. Keep MCP tools unchanged and use Vite's `/api` proxy during development.

**Tech Stack:** Python 3.11, Starlette, Uvicorn, pytest; Vite, React, TypeScript, Vitest, Testing Library, CSS modules/plain CSS.

## Global Constraints

- Preserve all existing MCP tool names, signatures, and behavior.
- Reuse `MemoryStore`; do not access vault files directly from the web layer.
- Expose only relative wiki paths to the browser.
- Keep writes, editing, deletion, authentication, graph visualization, streaming reflection, and other out-of-scope features out of this work.
- Use test-first development for every new behavior.
- Do not add secrets, absolute vault paths, or transient logs to the UI or wiki.

## File map

- Create `web_api.py`: Starlette routes, request validation, error mapping, and Uvicorn entrypoint.
- Modify `pyproject.toml`: add direct web API/runtime and test dependencies plus a `obsidian-memory-web-api` script.
- Modify `tests/test_mcp.py` or create `tests/test_web_api.py`: HTTP contract tests using a temporary vault and monkeypatched reflection.
- Create `web/package.json`: frontend scripts and dependencies.
- Create `web/tsconfig.json`, `web/tsconfig.node.json`, `web/vite.config.ts`, `web/index.html`: Vite/TypeScript setup and `/api` proxy.
- Create `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api.ts`, `web/src/types.ts`: app bootstrap, stateful shell, API client, and domain types.
- Create `web/src/styles.css`: theme tokens, responsive layout, cards, states, and motion.
- Create focused components under `web/src/components/`: `Sidebar`, `SearchView`, `BrowseView`, `ReflectView`, `PageView`, `ResultCard`, and shared loading/empty/error pieces.
- Create `web/src/test/setup.ts` and `web/src/App.test.tsx`: DOM test setup and interaction coverage.
- Modify `README.md`: installation, API server start, frontend start, and production build instructions.

---

### Task 1: Add the tested Python JSON API adapter

**Files:**
- Create: `web_api.py`
- Create: `tests/test_web_api.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `create_web_app(vault_path: str | None = None) -> Starlette`
- `GET /api/health -> {"ok": true}`
- `GET /api/search?q=<str>&limit=<int>&type=<str>&tag=<str> -> {"results": [...], "count": int}`
- `GET /api/pages?limit=<int> -> {"stats": {...}, "pages": [...]}`
- `GET /api/pages/{page_path} -> {"path": str, "content": str, "truncated": bool, "revision": str}`
- `POST /api/reflect` request `{ "query": str, "limit": int }` and response from `memory_reflect` shape.

- [ ] **Step 1: Write failing contract tests**

Create tests that construct the app with `tmp_path`, seed `MemoryStore` pages using `valid_page_content`, then verify:

```python
def test_search_endpoint_returns_filtered_results(client):
    response = client.get('/api/search?q=communication&type=people&limit=5')
    assert response.status_code == 200
    assert response.json()['count'] == 1
    assert response.json()['results'][0]['path'] == 'people/test-user.md'

def test_page_endpoint_rejects_paths_outside_curated_folders(client):
    response = client.get('/api/pages/../../etc/passwd')
    assert response.status_code in {400, 404}

def test_reflect_endpoint_returns_sources(client, monkeypatch):
    monkeypatch.setattr('web_api._run_reflection', lambda query, pages: 'Grounded answer')
    response = client.post('/api/reflect', json={'query': 'What matters?', 'limit': 3})
    assert response.status_code == 200
    assert response.json()['reflection'] == 'Grounded answer'
    assert response.json()['sources']

def test_reflect_endpoint_requires_non_empty_query(client):
    response = client.post('/api/reflect', json={'query': '   '})
    assert response.status_code == 400
    assert response.json()['error'] == 'invalid_query'
```

Use Starlette's `TestClient`; provide a fixture that creates the app with the temporary vault and seeds data before each test.

- [ ] **Step 2: Run the focused tests and confirm the expected red failures**

Run: `pytest tests/test_web_api.py -q`

Expected: collection or assertion failures because `web_api.py` and its routes do not exist yet.

- [ ] **Step 3: Implement the minimal API**

Add `create_web_app()` with Starlette `Route` handlers and `CORSMiddleware`. Resolve the vault from `vault_path()` when no explicit path is supplied. Use `MemoryStore.search`, `list`, and `read`. Import `_run_reflection` from `mcp_server` so the configured Hermes/Codex provider remains the single reflection implementation. Normalize errors into JSON `{ "error": code, "message": text }` with 400 for invalid input, 404 for missing pages, and 500 for unexpected service errors. Clamp `limit` to `1..50` for search/reflect and `1..500` for pages. Add `main()` that runs `uvicorn.run(create_web_app(), host='127.0.0.1', port=8787)` with `--host`, `--port`, and `--vault-path` CLI options.

- [ ] **Step 4: Add direct dependencies and run tests to green**

Add `starlette>=0.46,<1`, `uvicorn>=0.34,<1`, and test extras `httpx>=0.27,<1` to `pyproject.toml`; add the `obsidian-memory-web-api = "web_api:main"` script. Run: `pytest tests/test_web_api.py -q`. Expected: all API tests pass.

- [ ] **Step 5: Run the existing Python suite**

Run: `pytest -q`

Expected: all existing tests and new API tests pass.

- [ ] **Step 6: Commit**

```bash
git add web_api.py tests/test_web_api.py pyproject.toml
git commit -m "feat: add memory web API"
```

### Task 2: Scaffold the Vite React application and typed API client

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/types.ts`
- Create: `web/src/api.ts`
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`

**Interfaces:**
- `MemoryResult`, `MemoryPage`, `MemoryStats`, `SearchResponse`, `ReflectResponse`, and `ApiError` types in `web/src/types.ts`.
- `searchMemory(params): Promise<SearchResponse>`
- `listPages(limit?): Promise<{stats: MemoryStats; pages: MemoryPage[]}>`
- `readPage(path): Promise<MemoryPageDetail>`
- `reflectMemory(query, limit?): Promise<ReflectResponse>`

- [ ] **Step 1: Write a failing client test for the app shell**

Add `web/src/App.test.tsx` with a mocked `fetch` that returns a health-free initial state and assert the app renders the brand, Search/Browse/Reflect navigation, and the search input. Run `cd web && npm test -- --run` and confirm it fails because the app scaffold is missing.

- [ ] **Step 2: Create the minimal Vite/React project files**

Use React 18/19-compatible packages, TypeScript, Vite, Vitest, `@testing-library/react`, `@testing-library/jest-dom`, and `jsdom`. Configure `vite.config.ts` with `server.proxy = { '/api': 'http://127.0.0.1:8787' }`, `test.environment = 'jsdom'`, and `setupFiles = './src/test/setup.ts'`. Add scripts `dev`, `build`, `test`, and `preview`.

- [ ] **Step 3: Implement typed API wrappers**

Centralize `fetch` in a helper that parses JSON, throws an `ApiError` containing the response status and server message for non-2xx responses, and URL-encodes page paths with `encodeURIComponent`. Keep all endpoint paths under `/api` so the proxy works in development and same-origin deployment works in production.

- [ ] **Step 4: Implement the app shell state**

`App` owns `view: 'search' | 'browse' | 'reflect' | 'page'`, active search query/filters, selected page path, and theme state. Render a persistent `Sidebar` placeholder and route to placeholder view components. Add global `/` focus behavior only when the active element is not an input or textarea.

- [ ] **Step 5: Add baseline styles and run the test/build**

Add design tokens for warm light surfaces, charcoal dark surfaces, muted teal/blue accent, serif display headings, sans-serif UI text, rounded cards, and responsive breakpoints. Run `cd web && npm test -- --run` and `npm run build`. Expected: the shell test and production build pass.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat: scaffold memory workspace frontend"
```

### Task 3: Build search-first results and page detail

**Files:**
- Create: `web/src/components/Sidebar.tsx`
- Create: `web/src/components/ResultCard.tsx`
- Create: `web/src/components/SearchView.tsx`
- Create: `web/src/components/PageView.tsx`
- Create: `web/src/components/LoadingState.tsx`
- Create: `web/src/components/EmptyState.tsx`
- Create: `web/src/components/ErrorBanner.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/App.test.tsx`

**Interfaces:**
- `Sidebar({activeView, onNavigate, stats, theme, onToggleTheme})`
- `SearchView({initialQuery, onOpenPage, onReflect})`
- `PageView({path, onBack, onOpenPage})`
- `ResultCard({result, onOpen})`

- [ ] **Step 1: Write failing interaction tests**

Extend `App.test.tsx` with tests that mock `/api/search` and `/api/pages/{path}` and verify:

```tsx
it('submits search and opens a result page', async () => {
  render(<App />)
  await userEvent.type(screen.getByRole('searchbox'), 'retry policy')
  await userEvent.keyboard('{Enter}')
  expect(await screen.findByText('Deployment Retry Policy')).toBeVisible()
  await userEvent.click(screen.getByRole('button', {name: /deployment retry policy/i}))
  expect(await screen.findByRole('article')).toHaveTextContent('Retry deployments')
})

it('shows a recoverable search error', async () => {
  mockedFetch.mockRejectedValueOnce(new Error('API offline'))
  render(<App />)
  await userEvent.type(screen.getByRole('searchbox'), 'anything')
  await userEvent.keyboard('{Enter}')
  expect(await screen.findByRole('alert')).toHaveTextContent('API offline')
})
```

- [ ] **Step 2: Run the focused tests and verify red**

Run: `cd web && npm test -- --run src/App.test.tsx`

Expected: failures for missing search and page-detail behavior.

- [ ] **Step 3: Implement search view and result cards**

Render a hero heading, search input, type/tag filter chips, submit button, result count, and cards with title/path/snippet/type/date. Use a local submitted-query state so the input remains editable without triggering requests on every keystroke. Add a concise empty state with actions to Browse or Reflect.

- [ ] **Step 4: Implement page detail**

Load the selected page through `readPage`, render frontmatter/content in a readable article surface, show relative path and revision metadata, and provide a back button. Render content safely as plain text/Markdown-compatible blocks without using unsanitized `dangerouslySetInnerHTML`.

- [ ] **Step 5: Wire sidebar navigation, keyboard shortcut, loading, and errors**

Make Search, Browse, and Reflect buttons switch views. Use skeleton cards while requests are active, `role="alert"` for errors, and `aria-live="polite"` for result updates. Preserve query/filter state when navigating to and from a page.

- [ ] **Step 6: Run tests/build and commit**

Run: `cd web && npm test -- --run && npm run build`

Expected: all current frontend tests pass and the build succeeds.

```bash
git add web/src
git commit -m "feat: add search and page browsing views"
```

### Task 4: Build browse and reflect views

**Files:**
- Create: `web/src/components/BrowseView.tsx`
- Create: `web/src/components/ReflectView.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/App.test.tsx`

**Interfaces:**
- `BrowseView({onOpenPage})`
- `ReflectView({onOpenPage, initialQuery})`

- [ ] **Step 1: Write failing tests**

Add tests for browse loading and page selection, reflect success with source links, `Cmd/Ctrl + Enter` submission, and reflect failure preserving the entered question.

- [ ] **Step 2: Run focused tests and verify red**

Run: `cd web && npm test -- --run src/App.test.tsx`

Expected: failures for browse/reflect behavior.

- [ ] **Step 3: Implement BrowseView**

Call `listPages`, render stats for total pages and categories, expose type filter chips, and render page cards from the catalog. Empty and error states should use the shared components. Selecting a card calls `onOpenPage`.

- [ ] **Step 4: Implement ReflectView**

Render a question composer and submit button. Submit on `Cmd/Ctrl + Enter`, disable controls while loading, show a synthesis loading state, render the returned reflection text, and render source buttons that call `onOpenPage`. On failure, show the error while retaining the question and enabling retry.

- [ ] **Step 5: Integrate view state and cross-navigation**

Opening a result/source switches to page detail; “Reflect on this” from search seeds the reflect input; Back returns to the previous view and preserves its state.

- [ ] **Step 6: Run tests/build and commit**

Run: `cd web && npm test -- --run && npm run build`

Expected: all frontend tests pass and the build succeeds.

```bash
git add web/src
git commit -m "feat: add browse and reflection views"
```

### Task 5: Polish responsive UX and document the local workflow

**Files:**
- Modify: `web/src/styles.css`
- Modify: `web/src/App.test.tsx`
- Modify: `README.md`
- Modify: `.gitignore` if needed

- [ ] **Step 1: Write failing responsive/accessibility assertions**

Add tests that verify navigation buttons have accessible names, the main content has a landmark, error states use `role="alert"`, and the theme toggle updates its label/state. Keep viewport-specific layout assertions in CSS rather than brittle pixel tests.

- [ ] **Step 2: Run focused tests and verify red**

Run: `cd web && npm test -- --run src/App.test.tsx`

Expected: failures for any missing labels/landmarks/theme behavior.

- [ ] **Step 3: Implement final visual polish**

Complete light/dark theme variables, responsive rail-to-topbar layout, card hover/focus transitions, reduced-motion media query, keyboard-visible focus rings, readable line lengths, and narrow-screen single-column layouts. Ensure buttons and inputs retain sufficient contrast in both themes.

- [ ] **Step 4: Document setup and run commands**

Add a “Web UI” section to `README.md` with exact commands:

```bash
# terminal 1: API
OBSIDIAN_VAULT_PATH="/absolute/path/to/agent-vault" \
  .venv/bin/obsidian-memory-web-api --host 127.0.0.1 --port 8787

# terminal 2: frontend
cd web
npm install
npm run dev
```

Document the production build (`npm run build`) and explain that Vite proxies `/api` to port 8787 in development.

- [ ] **Step 5: Run full verification**

Run: `pytest -q`, `cd web && npm test -- --run`, and `cd web && npm run build`.

Expected: all Python tests pass, all frontend tests pass, and the production build completes without TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add web/src/styles.css web/src/App.test.tsx README.md .gitignore
git commit -m "docs: finish memory web UI workflow"
```

## Self-review checklist

- API behavior from the approved spec is covered in Task 1.
- Search, browse, reflect, page detail, loading, empty, error, keyboard, and responsive behavior are covered in Tasks 2–5.
- MCP contracts remain untouched by every task.
- No task relies on an undefined endpoint or component signature.
- No placeholders or unspecified “handle edge cases” steps remain.
