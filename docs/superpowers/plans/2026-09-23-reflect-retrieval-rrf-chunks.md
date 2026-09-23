# General Reflect Retrieval Improvements Implementation Plan

> **For agentic workers:** Execute inline using the approved plan and keep the steps in checkbox form. Use test-driven development for every behavior change.

**Goal:** Improve Reflect retrieval across query types by fusing independent lexical and embedding ranks with RRF and sending only relevant bounded Markdown sections to the reflection model.

**Architecture:** Add `obsidian_memory_core/wiki/reflect_retrieval.py` as a Reflect-only retrieval layer. It will take one filtered page snapshot, query FTS/keyword/embedding independently, fuse candidates by path with RRF, retain exact identity/phrase precedence, split candidates into heading-aware chunks, score chunks with multilingual embeddings plus lexical relevance, and return bounded excerpts grouped by original page. `memory_reflect` will call this layer; Search continues using the existing hybrid path. The standalone MCP adapter will call an OpenAI-compatible API directly; no Hermes runtime/auth is required.

**Tech Stack:** Python 3.11, SQLite FTS5, existing FastEmbed multilingual model, pytest, FastMCP.

## Global Constraints

- Apply the retrieval changes to all Reflect queries; no topic-specific synonym or entity rules.
- Leave Search UI ranking, precise multiword behavior, and thresholds unchanged.
- Preserve current curated-only source policy and existing filters.
- Do not add an FTS schema migration, persistent chunk store, or vector database.
- Keep each excerpt linked to its original page path.
- Bound candidates, sections per page, excerpt size, and total context size.
- If embeddings are unavailable, fall back to deterministic lexical section scores without failing Reflect.
- Configure standalone reflection with API key/model/base URL environment variables; remove the Hermes runtime fallback while retaining the separate optional Codex provider.
- Preserve unrelated workspace state, including existing untracked `artifacts/` content; do not commit without an explicit user request.

## File map

- `obsidian_memory_core/wiki/reflect_retrieval.py` — new RRF, Markdown section splitting, section scoring, and bounded excerpt assembly.
- `mcp_server.py` — replace the current Search-then-read loop in `memory_reflect` with the new retrieval function.
- `tests/test_reflect_retrieval.py` — new focused unit and integration tests for rank fusion, section extraction, bounds, and all-channel recall.
- `tests/test_mcp.py` — assert Reflect sends selected excerpts, groups sections by canonical path, and returns only contributing sources.

## Task 1: Add RRF and heading-section tests, then implement the retrieval primitives

**Interfaces produced:**

```python
reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    *,
    limit: int,
    pages_by_path: dict[str, dict] | None = None,
) -> list[dict]

split_markdown_sections(page: dict, *, max_chars: int) -> list[dict]
```

Each candidate contains at least `path`, `title`, and `type`; each section contains `path`, `title`, `heading`, and `content`.

**Files:** Create `tests/test_reflect_retrieval.py`; create `obsidian_memory_core/wiki/reflect_retrieval.py`.

- [x] Write tests showing a page present near the top of multiple channels outranks a page present once, duplicate paths collapse, ties are deterministic, and exact title/alias matches remain ahead of non-exact candidates even when channel score scales differ.
- [x] Attempt the initial red run; pytest collection was blocked by the host's missing `hermes_platform` path. Focused tests were subsequently run with the Hermes checkout on `PYTHONPATH`.
- [x] Write `reciprocal_rank_fusion` using `1 / (rrf_k + rank)` per list (default `rrf_k=60`), aggregating by path. Use pages metadata for `exact_page_match`; preserve phrase match evidence; sort exact first, then fused score, then case-folded title and path.
- [x] Add tests and implement Markdown splitting that ignores heading markers inside fenced code blocks, retains preamble text, includes heading context in each chunk, and breaks oversized sections on paragraph boundaries while keeping each chunk within `max_chars`.
- [x] Run focused retrieval tests; all primitive tests pass.

## Task 2: Add failing tests and implement section relevance scoring and context bounds

**Interface produced:**

```python
select_reflect_excerpts(
    query: str,
    pages: list[dict],
    *,
    embedder=None,
    max_sections_per_page: int = 2,
    max_excerpt_chars: int = 1800,
    max_total_chars: int = 12000,
) -> list[dict]
```

Returns one record per contributing page: `{"path": ..., "content": ...}`. `content` consists of the best selected heading chunks for that page, preserving headings and source-local order.

**Files:** `tests/test_reflect_retrieval.py`; `obsidian_memory_core/wiki/reflect_retrieval.py`.

- [x] Add tests where the relevant fact is below an unrelated first section, where a query matches semantically but not by shared words, where one long page cannot exceed the excerpt budget, and where an empty page returns a safe bounded fallback.
- [x] Implement an injectable embedder path that encodes the query and bounded candidate sections in one call, cosine-scores section vectors, and combines semantic score with normalized lexical token/phrase coverage. If no embedder is available or embedding fails, use lexical scores only.
- [x] Limit sections per page, fairly sample across long pages, enforce per-section and aggregate character budgets, and group excerpts under one original `path`.
- [x] Run focused retrieval tests; primitive and section tests pass.

## Task 3: Integrate independent candidate retrieval into `memory_reflect`

**Interface produced:**

```python
retrieve_reflect_excerpts(
    vault,
    query: str,
    *,
    candidate_limit: int = 48,
    result_limit: int = 8,
    filters: dict | None = None,
) -> list[dict]
```

**Files:** `obsidian_memory_core/wiki/reflect_retrieval.py`, `mcp_server.py`, `tests/test_reflect_retrieval.py`, `tests/test_mcp.py`.

- [x] Add an integration fixture with a relevant answer buried below unrelated content and unrelated lexical-noise pages; assert the relevant page is present in bounded excerpts.
- [x] Verify the personal fact live against the canonical profile, alongside synthetic semantic and broad-query tests, without topic-specific production rules.
- [x] Confirm retrieval failure mode from live channel ranks: Search's 0.25 embedding cutoff dropped the relevant profile (cosine 0.179), and an early global chunk cap excluded later candidates. Reflect now uses a wider embedding pool and fair section sampling.
- [x] Implement candidate retrieval using one `vault.load_pages()` snapshot plus `page_matches_filters`, independent FTS/keyword/embedding lists, RRF, and section selection.
- [x] Preserve exact title/alias and phrase precedence, exclude sources by default through existing filter normalization, and fall back to available channels when FTS or embeddings fail.
- [x] Replace `memory_reflect`'s hybrid search and full-page `store.read()` loop with excerpt retrieval. Return only contributing page paths.
- [x] Run focused retrieval/MCP/core tests; all pass.

## Task 4: Run regression suite and validate live behavior

**Files:** no new files unless a test exposes a scoped defect.

- [x] Run the full Python suite: 180 passed; one unrelated date-sensitive ingest assertion expects 2026-09-22 while runtime date is 2026-09-23.
- [x] Run Python compilation and `git diff --check`.
- [x] Rebuild the `obsidian-memory` and `obsidian-memory-web` services; both report healthy.
- [x] Call live MCP Reflect for the prior missed fact and an English/Vietnamese embedding tradeoff query; inspect answers and source paths.
- [x] Record the general retrieval design and confirmed causes in the canonical wiki page via revision-checked MCP append, read it back, and run `memory_lint()` (existing unrelated lint findings remain).

## Acceptance checklist

- Reflect fuses independent FTS, keyword, and embedding rankings without comparing their raw score scales.
- A relevant section deep in a page reaches the model within the context budget.
- Selected excerpts preserve original paths and returned `sources` include only contributing pages.
- Reflect handles embedding unavailability safely through lexical fallback.
- Existing Search behavior and source policy remain unchanged.
- Python regression tests pass except any explicitly identified pre-existing unrelated failure; live MCP Reflect demonstrates the recovered case and a separate general query.
