# Metadata-Aware Search and Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Obsidian Wiki search precision by indexing searchable metadata consistently, adding filters, and making exact title/stem/alias matches deterministic.

**Architecture:** Keep the existing SQLite FTS5 plus optional embedding architecture. Introduce a typed filter-normalization layer in the Python search helpers, apply filters against one request-scoped page snapshot before ranking, and carry the same options through MemoryStore, the MCP tool, and the Hermes provider facade. Exact title/stem/alias matches receive an explicit ranking tier while semantic and lexical scores remain unchanged for non-exact candidates.

**Tech Stack:** Python 3.11+, SQLite FTS5, SQLAlchemy, pytest, existing Hermes MCP/provider adapters.

## Global Constraints

- Preserve existing FTS5, keyword, embedding, recency, and snippet behavior for unfiltered searches.
- Keep raw `sources/` excluded by default; `include_sources=true` explicitly opts them in.
- Do not add a new database, embedding model, vector service, graph traversal, or external dependency.
- Filters use exact case-insensitive page type matching, all-requested-tags matching, ISO `YYYY-MM-DD` lower bound for `updated_after`, and normalized relative `path_prefix` matching.
- Exact title/stem/alias matches must outrank non-exact candidates, including embedding candidates.
- Preserve the current public result shape; only add `match: "exact"` when an exact identity match wins.
- Existing callers that pass only `query` and `limit` must behave as before.
- Use optimistic, read-only search operations; no vault writes are part of this feature.

---

### Task 1: Define search filters and exact identity helpers

**Files:**
- Modify: `obsidian_memory_core/wiki/search.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Produce `SearchFilters` as a typed mapping/dataclass accepted by the search stack.
- Produce `normalize_search_filters(filters)`.
- Produce `page_matches_filters(page, filters)`.
- Produce `exact_page_match(page, query) -> bool`.

- [ ] **Step 1: Write failing tests**

Add tests that construct pages with different types, tags, dates, and paths and assert:

```python
assert page_matches_filters(page, {"type": "person", "tags": ["family"]})
assert not page_matches_filters(page, {"type": "concept"})
assert page_matches_filters(page, {"tags": ["family", "profile"]})
assert page_matches_filters(page, {"updated_after": "2026-09-01"})
assert not page_matches_filters(page, {"path_prefix": "decisions/"})
assert exact_page_match(page, "Example Partner")
assert exact_page_match(page, "partner alias")
```

Also test `include_sources=False` rejects source pages and `include_sources=True` allows them.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_core.py -q -k "search_filter or exact_page_match"
```

Expected: collection succeeds and the new tests fail because the helpers do not exist.

- [ ] **Step 3: Implement the minimal helper layer**

In `obsidian_memory_core/wiki/search.py`:

- Define the accepted keys: `type`, `tags`, `updated_after`, `path_prefix`, `include_sources`.
- Normalize scalar type/tags inputs into casefolded lists.
- Normalize a path prefix to slash-separated relative form without a leading `./`.
- Validate `updated_after` as ISO `YYYY-MM-DD`.
- Match all requested tags.
- Exclude source pages unless explicitly included.
- Compare normalized query identity against page title, stem, and aliases.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run the same pytest command and expect all new helper tests to pass.

- [ ] **Step 5: Commit**

```bash
git add obsidian_memory_core/wiki/search.py tests/test_core.py
git commit -m "feat: define metadata search filters"
```

---

### Task 2: Apply one page snapshot, metadata filters, and exact ranking

**Files:**
- Modify: `obsidian_memory_core/wiki/fts.py`
- Modify: `obsidian_memory_core/wiki/vault.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Extend `WikiVault.search(query, limit=5, filters=None)`.
- Extend `hybrid_search(vault, query, limit=5, filters=None)`.
- Keep `_embedding_search` compatible while allowing the caller to pass the already filtered page snapshot.

- [ ] **Step 1: Write failing integration tests**

Add tests that create pages and assert:

1. Metadata-only terms remain searchable.
2. `type`, `tags`, `updated_after`, and `path_prefix` filters restrict results.
3. Source pages remain hidden by default and appear with `include_sources=True`.
4. An exact alias ranks above a semantically/lexically related generic page.
5. Search still returns the existing result keys for an unfiltered query.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_core.py -q -k "search_filter or metadata_only or exact_alias or include_sources"
```

Expected: the new integration tests fail because `search` does not accept filters and exact identity is not a ranking tier.

- [ ] **Step 3: Implement the minimal search changes**

- Load `vault.load_pages()` once per search request.
- Normalize filters once.
- Build an eligible page map before lexical, FTS, and embedding ranking.
- Filter FTS and keyword candidates against that map.
- Pass the eligible page list into embedding search so filtered-out pages cannot re-enter.
- Replace repeated `vault.load_pages()` calls in exact-match checks with the snapshot.
- Mark exact identity candidates internally, sort them ahead of non-exact candidates, then remove the internal field before returning.
- Preserve default source exclusion and all existing score/snippet fields.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run the same pytest command and expect all new integration tests to pass.

- [ ] **Step 5: Run the existing search regression tests**

```bash
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_core.py -q
```

Expected: all core tests pass.

- [ ] **Step 6: Commit**

```bash
git add obsidian_memory_core/wiki/fts.py obsidian_memory_core/wiki/vault.py tests/test_core.py
git commit -m "feat: apply metadata filters and exact search priority"
```

---

### Task 3: Expose filters through MemoryStore, MCP, and Hermes provider

**Files:**
- Modify: `obsidian_memory_core/store.py`
- Modify: `mcp_server.py`
- Modify: `__init__.py`
- Test: `tests/test_mcp.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Extend `MemoryStore.search(query, limit=5, filters=None)`.
- Extend the `search` action in `MemoryStore.call` to accept top-level filter fields.
- Extend `mcp_server.memory_search(query, limit=5, type=None, tags=None, updated_after=None, path_prefix=None, include_sources=False)`.
- Extend the generic Hermes `obsidian_wiki` schema and dispatch allowlist with the same filter fields.

- [ ] **Step 1: Write failing adapter tests**

Add tests that call:

```python
store.search("partner", filters={"type": "person"})
provider.handle_tool_call(
    "obsidian_wiki",
    {"action": "search", "query": "partner", "type": "person"},
)
```

and assert only person pages are returned. Add an MCP function-level test for explicit filter arguments when the compatible FastMCP environment is available.

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```bash
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_core.py tests/test_mcp.py -q -k "search_filter or filtered_search"
```

Expected: direct tests fail because the adapters drop or reject filter arguments. MCP import failures caused by the pre-existing FastMCP/MCP package mismatch remain environment failures, not feature failures.

- [ ] **Step 3: Implement adapter propagation**

- Pass a normalized filter dictionary from `MemoryStore.search` to `vault.search`.
- In `MemoryStore.call`, merge explicit top-level filter fields into the filter dictionary.
- Add filter properties and descriptions to `WIKI_TOOL_SCHEMA`.
- Include filter keys in the provider MCP allowlist.
- Pass filters through direct provider search.
- Add explicit MCP function parameters and a compact filters dictionary.
- Keep filter values out of write paths and preserve existing bounds on `limit`.

- [ ] **Step 4: Run adapter tests and verify they pass**

Run the focused command again. Direct provider/store tests must pass; report only the known external dependency failures for tests importing `mcp_server`.

- [ ] **Step 5: Commit**

```bash
git add obsidian_memory_core/store.py mcp_server.py __init__.py tests/test_core.py tests/test_mcp.py
git commit -m "feat: expose wiki search filters across adapters"
```

---

### Task 4: Document the search contract and run final verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_core.py`
- Test: `tests/test_mcp.py`

- [ ] **Step 1: Add documentation tests or contract assertions**

Add a small adapter contract assertion that filter keys are present in the generic tool schema and MCP search signature behavior is documented by the test inputs.

- [ ] **Step 2: Update README**

Document:

- supported filter fields and semantics;
- source exclusion by default;
- exact title/alias priority;
- example MCP/provider calls;
- unchanged hybrid embedding behavior.

- [ ] **Step 3: Run focused verification**

```bash
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m pytest tests/test_core.py -q
```

Expected: all core tests pass.

- [ ] **Step 4: Run the full suite**

```bash
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m pytest -q
```

Record exact passing/failing counts. The known FastMCP/MCP import mismatch must be reported separately if still present.

- [ ] **Step 5: Run static checks**

```bash
git diff --check
/Users/truongmanhsang/.hermes/hermes-agent/venv/bin/python -m compileall -q obsidian_memory_core mcp_server.py __init__.py
```

- [ ] **Step 6: Commit**

```bash
git add README.md tests/test_core.py tests/test_mcp.py
git commit -m "docs: document metadata-aware wiki search"
```

