# General Reflect Retrieval: Rank Fusion and Relevant Sections

**Date:** 2026-09-23  
**Status:** Approved for implementation

## Goal

Improve `memory_reflect` recall across question types by retrieving candidates independently from lexical FTS, keyword search, and semantic embeddings, combining their rankings with Reciprocal Rank Fusion (RRF), then giving the LLM the most relevant Markdown sections rather than whole pages.

## Current failure mode

`memory_reflect` currently calls the same hybrid search used by general search and limits its result set before reading pages. That hybrid combines scores from different retrieval methods on incompatible scales. A relevant page can fall outside the small result limit, and sending whole pages gives the model substantial unrelated text when a page is long. Increasing the candidate count alone would still leave score-scale and long-page noise problems.

## Proposed flow

1. Load one eligible page snapshot and honor the current curated-page/source policy.
2. Run independent FTS, keyword, and embedding retrieval over that snapshot with a broader candidate pool.
3. Fuse channel ranks by path with RRF, using deterministic tie-breaking and preserving exact identity/phrase signals as high-confidence evidence.
4. For the fused candidates, split Markdown into heading-aware sections. Score sections using query relevance, selecting a bounded number per page and globally.
5. Pass the selected excerpts, their original page paths, and the original query to the configured reflection provider. The standalone MCP provider calls an OpenAI-compatible API directly and must not depend on Hermes runtime/auth.
6. Return the pages that actually contributed excerpts in `sources`.

## Design constraints

- This applies to all Reflect queries; it must not introduce person-, family-, finance-, or other topic-specific rules.
- Search UI ranking and its precise multiword behavior remain unchanged.
- Preserve filters and current source inclusion behavior for Reflect.
- Avoid an FTS database schema migration. Existing page embeddings may be reused for candidate retrieval; section selection can be performed per request.
- Keep original page provenance for each excerpt and do not imply that an excerpt is a separate source.
- Bound candidate count, excerpt count, per-page excerpt length, and total context size to control latency and prompt size.
- Empty or malformed Markdown still yields a safe bounded fallback excerpt.
- Reflection remains grounded: the LLM may answer only from supplied excerpts and should state when they do not establish the answer.
- Standalone MCP/Reflect runs in the container without importing or requiring Hermes. API credentials, model, and optional compatible base URL are supplied through environment configuration.

## Approaches considered

- Increase only the existing hybrid-search limit. This is small but retains incompatible score fusion and whole-page context noise.
- Use RRF across lexical/semantic candidate lists and heading-aware excerpt selection. This adds a Reflect-specific retrieval stage while leaving Search behavior stable, and directly addresses both candidate recall and evidence precision. This is the selected approach.

## Testing and acceptance

- Unit tests verify RRF ordering is independent of raw score scales, candidates unique by path, and deterministic ties.
- Tests verify heading-aware splitting, relevant section selection, context bounds, and source-path preservation.
- End-to-end regression fixtures include exact facts, paraphrases, multilingual queries, broad synthesis, irrelevant lexical noise, and long pages where a relevant fact appears below the first section.
- Confirm the prior “Ba tôi tên gì?” miss is recovered through the profile page as one regression case, alongside unrelated topic cases to demonstrate the retrieval is general.
- Existing Search ranking, precise phrase behavior, and source policy tests continue to pass.
- Verify the live MCP Reflect response after rebuilding the service.

## Out of scope

- Changing Search UI ranking or semantic thresholds.
- Adding topic-specific synonym dictionaries or hard-coded entity rules.
- Adding a new vector database, persistent chunk index, or automatic page migration.
- Changing Search's provider configuration or LLM model.
