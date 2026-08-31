# Multilingual Search Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve accented/unaccented Latin-script search recall while preserving Unicode-aware retrieval for non-Latin scripts and keeping displayed page content unchanged.

**Architecture:** Add one shared `normalize_search()` utility. Use it for query tokens, keyword scoring, exact title/alias checks, and an indexed FTS search projection composed from title, stem, body, aliases, tags, and `search_terms`; retain original title/body columns for output and snippets.

**Tech Stack:** Python 3.11+, SQLite FTS5, Unicode `unicodedata`, pytest.

## Global Constraints

- Always apply NFKC, Unicode case folding, and whitespace normalization for every script.
- Remove combining marks only when they belong to Latin-script text.
- Preserve original page content for display, exact matching, and snippets.
- Keep existing API result shapes and embedding behavior unchanged.
- Rebuild the FTS database safely when the normalized projection schema changes.

---

### Task 1: Add normalization regression tests

**Files:**
- Modify: `tests/test_obsidianwiki.py`

**Interfaces:**
- Consumes: the future `normalize_search()` helper from `obsidian_memory_core.wiki.intent`.
- Produces: failing tests that define Latin diacritic folding, Unicode normalization, and non-Latin preservation.

- [ ] **Step 1: Add unit tests for the normalizer**

Add tests covering composed/decomposed text, case folding, whitespace, Vietnamese/Latin folding, and a non-Latin string containing combining marks. The assertions should call `normalize_search()` directly and verify that original strings are not modified by the helper.

- [ ] **Step 2: Add search integration tests**

Create a temporary vault page whose title/body uses `cà phê`, then assert that `MemoryStore.search()` finds it for both `cà phê` and `ca phe`. Add a page with searchable alias/tag metadata and assert those fields also match. Add a non-Latin page and assert its normal search still returns it.

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_obsidianwiki.py -k 'normalize or accent or multilingual' -v
```

Expected: collection succeeds and the new tests fail because `normalize_search()` and normalized indexing are not implemented.

### Task 2: Implement the shared Unicode normalizer

**Files:**
- Modify: `obsidian_memory_core/wiki/intent.py`

**Interfaces:**
- Consumes: arbitrary query/page field strings.
- Produces: `normalize_search(text: str) -> str`, used by all retrieval paths.

- [ ] **Step 1: Implement `normalize_search()`**

Use this behavior:

```python
def normalize_search(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    value = unicodedata.normalize("NFD", value)
    output = []
    last_base_is_latin = False
    for char in value:
        category = unicodedata.category(char)
        if category.startswith("M"):
            if last_base_is_latin:
                continue
            output.append(char)
            continue
        output.append(char)
        last_base_is_latin = unicodedata.name(char, "").startswith("LATIN")
    return re.sub(r"\s+", " ", "".join(output)).strip()
```

Keep the helper in `intent.py` beside `query_tokens()` and import it from consumers rather than creating another normalizer.

- [ ] **Step 2: Update tokenization to normalize before token extraction**

Make `query_tokens()` call `normalize_search()` before applying `TOKEN_RE`. Preserve its current return type and minimum token length behavior.

- [ ] **Step 3: Run the unit tests**

Run:

```bash
python3 -m pytest tests/test_obsidianwiki.py -k 'normalize or accent or multilingual' -v
```

Expected: direct normalizer tests pass; integration tests involving FTS projection remain failing until Task 3.

### Task 3: Apply normalization consistently to keyword and FTS retrieval

**Files:**
- Modify: `obsidian_memory_core/wiki/search.py`
- Modify: `obsidian_memory_core/wiki/vault.py`
- Modify: `obsidian_memory_core/wiki/fts.py`
- Test: `tests/test_obsidianwiki.py`

**Interfaces:**
- Consumes: `normalize_search()` and existing page metadata.
- Produces: consistent normalized candidates from keyword and FTS paths without changing result dictionaries.

- [ ] **Step 1: Add a normalized page projection helper**

Build one string from title, stem, body, aliases, tags, and `search_terms`, then normalize that string. Use the helper for keyword body/title/tag comparisons and for `page_anchor_score()` text comparisons while retaining original page fields for output.

- [ ] **Step 2: Extend the FTS schema with `search_projection`**

Add an indexed `search_projection` column to `SCHEMA`. Populate it in `build_fts_db()` from the normalized page projection. Keep `title` and `body` columns unchanged for snippets and result presentation. Because the schema is created with `IF NOT EXISTS`, make `ensure_fresh()` detect a missing projection column/table shape and call `build_fts_db()` so old databases rebuild safely.

- [ ] **Step 3: Normalize FTS queries and metadata matching**

Normalize the query before `_fts_rows()` builds its OR expression. Ensure aliases, tags, and `search_terms` can match through `search_projection`. Update exact title/alias matching to compare normalized candidates in addition to original exact candidates, with original exact matches retaining the stronger anchor signal.

- [ ] **Step 4: Keep snippets original**

Continue selecting snippets from `page["body"]`/stored FTS `body`; never expose the normalized projection in result text.

- [ ] **Step 5: Run focused integration tests**

Run:

```bash
python3 -m pytest tests/test_obsidianwiki.py -k 'normalize or accent or multilingual or hybrid' -v
```

Expected: all focused tests pass, including FTS, keyword, alias, and non-Latin cases.

### Task 4: Verify regression safety and document behavior

**Files:**
- Modify: `README.md` only if the public search behavior needs documenting.
- Test: `tests/test_obsidianwiki.py`

- [ ] **Step 1: Run the full test suite**

Run:

```bash
python3 -m pytest -q
```

Expected: all existing and new tests pass.

- [ ] **Step 2: Run static compilation and diff checks**

Run:

```bash
python3 -m compileall -q .
git diff --check
```

Expected: both commands exit successfully.

- [ ] **Step 3: Inspect the final diff**

Confirm that page files are not rewritten, result shapes are unchanged, original snippets remain readable, and no embedding model or dependency was added.

- [ ] **Step 4: Commit the implementation**

```bash
git add obsidian_memory_core/wiki/intent.py obsidian_memory_core/wiki/search.py obsidian_memory_core/wiki/vault.py obsidian_memory_core/wiki/fts.py tests/test_obsidianwiki.py README.md
git commit -m "feat: normalize multilingual search text"
```

## Self-review

- Spec coverage: all scope, architecture, ranking, compatibility, and testing requirements map to Tasks 1–4.
- Placeholder scan: no TBD/TODO or unspecified implementation steps remain.
- Type consistency: `normalize_search(text: str) -> str` is the single shared interface; existing search result types remain unchanged.
