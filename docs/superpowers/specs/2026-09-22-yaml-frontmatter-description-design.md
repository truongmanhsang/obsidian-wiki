# YAML Frontmatter and Description-Aware Memory Design

**Date:** 2026-09-22  
**Status:** Approved for implementation

## Goal

Make page metadata safe and extensible while preserving the current Obsidian Wiki contract. Frontmatter will be parsed as YAML, unknown metadata will round-trip through page updates, and an optional `description` will become the preferred summary in generated indexes, search results, and the UI.

## Scope

### In scope

- Replace the duplicated hand-written frontmatter parsing logic with one safe YAML parser.
- Preserve the required metadata fields already used by the plugin:
  - `type`
  - `updated`
  - `tags`
  - `aliases`
- Accept optional fields, including nested mappings and lists, without requiring existing pages to change.
- Preserve unknown frontmatter fields when a page is written back.
- Treat `description` as the preferred page summary, with the current first-body-line behavior as fallback.
- Make description available to index generation, search projections/results, snippets, and the UI.
- Add regression tests for valid nested YAML, legacy pages, round-tripping, and description fallback behavior.

### Out of scope

- No trust or freshness ranking changes in this phase.
- No requirement for `sources`, `verified`, `status`, or `stale_after` on old or new pages.
- No automatic migration of existing Markdown pages.
- No replacement of SQLite/FTS5 or Obsidian wikilinks.
- No change to the current folder-derived page type contract.

## Metadata contract

`parse_frontmatter` will return a mapping plus the Markdown body. A valid YAML mapping is parsed with `yaml.safe_load`, so nested mappings/lists and scalar values are retained without constructing Python objects.

The parser will normalize compatibility-sensitive values where needed:

- `type` remains a string and continues to drive page validation.
- `updated` remains representable as the existing ISO date string, including when YAML parses an unquoted date as a date value.
- `tags` and `aliases` continue to accept the existing list forms and remain available to current validation/index code.
- `description`, when present, is treated as an optional string summary.
- Other keys are retained as parsed YAML values.

If a legacy or malformed frontmatter block cannot be parsed as a YAML mapping, the parser will use a safe compatibility fallback for the existing scalar/list syntax. It will not execute YAML tags or arbitrary constructors. Existing structural validation remains responsible for rejecting missing or invalid required fields.

## Write behavior

Page writes will:

1. Parse the existing frontmatter into a metadata mapping.
2. Update only the managed core fields (`type`, `updated`, `tags`, and `aliases`) according to the current write contract.
3. Preserve all other metadata keys and nested values.
4. Serialize the complete mapping back to safe YAML while keeping the established readable formatting for core list fields.

Pages without frontmatter will continue to receive the required core fields. Pages without `description` will remain valid and will use the existing body-derived summary.

## Summary and search flow

The canonical summary helper will prefer a non-empty `meta.description` and otherwise return the existing first non-empty body line. That helper will be used by:

- deterministic/generated index entries;
- LLM index manifests;
- search result snippets when no more specific body match is available;
- the API result shape consumed by the Obsidian plugin UI.

The full metadata projection will continue to feed search indexing, which means `description` is searchable without a separate database migration. Search results will expose the description explicitly while retaining existing fields and ranking behavior.

Trust/freshness fields may be parsed and preserved now, but their ranking and display policy will be implemented in a later phase.

## Error handling and compatibility

- Safe YAML parsing must never execute arbitrary constructors.
- A malformed frontmatter block must not crash page discovery; the compatibility parser provides the same best-effort behavior as before, after which existing validation decides whether the page is usable.
- Old pages without `description` must produce the same summary and remain searchable.
- Unknown fields must survive a write/read round trip, including nested data.
- The parser should have one canonical implementation so `WikiVault` and other callers cannot drift.

## Test strategy

Tests will be written before implementation for:

- nested YAML mappings/lists and Unicode values;
- legacy scalar, inline-list, and block-list frontmatter;
- safe handling of malformed/non-mapping YAML;
- preservation of unknown fields through `write_page`;
- description-first index summaries;
- description search projection/result fields and snippet fallback;
- unchanged behavior for pages without descriptions;
- regression coverage for the existing metadata phrase ranking behavior.

## Acceptance criteria

- Existing required-field validation and old pages continue to work.
- A page containing nested optional metadata can be read and written without losing that metadata.
- A page description appears in generated index summaries, search results, and the UI’s rendered result content.
- Search ranking behavior is unchanged except for the intentional searchable description field and summary/snippet improvements.
- Focused tests pass, and the known unrelated FastMCP registration-helper test remains clearly identified if still present.
