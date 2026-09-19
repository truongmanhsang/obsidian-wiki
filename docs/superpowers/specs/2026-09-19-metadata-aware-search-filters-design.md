# Metadata-Aware Search and Filters Design

**Date:** 2026-09-19

## Goal

Improve Obsidian Wiki search precision without replacing the current FTS5/keyword/embedding architecture.

## Approved behavior

Search accepts optional filters:

- `type`: exact case-insensitive page type.
- `tags`: page must contain all requested tags, case-insensitively.
- `updated_after`: inclusive ISO `YYYY-MM-DD` lower bound.
- `path_prefix`: normalized vault-relative path prefix.
- `include_sources`: source pages remain excluded by default and are included only when true.

Search loads the page catalog once per request. The snapshot is used to filter FTS, keyword, and embedding candidates consistently. The metadata projection continues to index title, stem, body, aliases, tags, type, and custom searchable fields such as `search_terms`.

Exact normalized matches against a page title, stem, or alias receive a deterministic ranking tier above non-exact candidates. Existing score, snippet, result shape, embedding fallback, and unfiltered behavior remain compatible.

## API surface

The filter fields are exposed through:

- `WikiVault.search`
- `MemoryStore.search` and the `search` action
- `mcp_server.memory_search`
- the generic Hermes `obsidian_wiki` schema and dispatch

No new dependencies, vector database, embedding model, or graph traversal are introduced.

## Verification

Tests cover helper semantics, metadata-only retrieval, all filters, source opt-in, exact alias priority, adapter propagation, schema exposure, and unchanged unfiltered results. Core tests and static checks must pass. Existing FastMCP/MCP environment incompatibilities are reported separately if they prevent MCP imports.

