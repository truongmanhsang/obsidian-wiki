# Universal Wiki Page Structure Validator Design

**Date:** 2026-09-19  
**Status:** Proposed

## Goal

Add a Python validator that enforces a predictable, readable Markdown structure for every curated Obsidian Wiki page type while preserving existing legacy pages until they are explicitly edited or migrated.

## Context

The current write path validates folder/type consistency, frontmatter, duplicate entities, links, and size, but it does not validate document structure. As a result, pages such as `concepts/gridspacing-ea-backtest-results.md` can accumulate long narrative sections, inconsistent heading depth, repeated section names, mixed metric conventions, and incomplete experiment records.

The validator must apply to all curated page types rather than hard-coding GridSpacing or trading-specific rules. Domain-specific structure belongs in page-type profiles and content metadata, not in a special-case page-name check.

## Design

### 1. Validation boundary

Create a focused module at `obsidian_memory_core/wiki/structure.py` with pure validation functions. The module must not write files, mutate Markdown, or depend on the vault. It receives page content and the resolved page type and returns a stable report:

```python
{
    "valid": bool,
    "mode": "strict" | "legacy" | "lint",
    "errors": [{"code": str, "message": str, "line": int | None}],
    "warnings": [{"code": str, "message": str, "line": int | None}],
}
```

The validator operates after frontmatter canonicalization has determined the final page type and before the final file write. It validates the complete resulting page for both `write` and `append`.

### 2. Universal rules

Strict curated pages must satisfy these rules:

- The page has valid frontmatter with `type`, `updated`, `tags`, and `aliases`.
- The body has exactly one level-one heading.
- The level-one heading is non-empty and is consistent with the page title/stem.
- Heading levels do not skip (for example, `##` cannot be followed by `####`).
- Heading names are non-empty and unique, case-insensitively, except for generated terminal sections handled by the backlink writer.
- Every non-terminal section contains meaningful non-whitespace content.
- The page contains a `## Related` section unless it is a source page; the section may contain zero links only when the page has no known related page.
- `## Linked from` is treated as generated metadata and is excluded from authoring checks.
- `## Sources` is treated as a terminal provenance section and may contain links or source references.
- Wikilinks in authored content have valid Markdown link syntax; existing link lint remains authoritative for canonical-path and unresolved-target checks because the pure validator does not depend on a vault.
- The page does not exceed the existing write-size limit.

The validator must report stable error codes rather than only free-form prose, including `missing_frontmatter`, `missing_h1`, `multiple_h1`, `heading_level_skip`, `duplicate_heading`, `empty_section`, `missing_related`, and `invalid_structure`.

### 3. Page-type profiles

Profiles specify required semantic sections without imposing one identical outline on every page. A profile can accept aliases for a section, but each required group must be represented at least once.

| Type | Required section groups | Recommended groups |
| --- | --- | --- |
| `concept` | `Summary`/`Overview`, `Core Content`/`Explanation` | `Examples`, `Caveats`, `Related` |
| `decision` | `Context`, `Decision`, `Rationale` | `Alternatives`, `Consequences`, `Related` |
| `answer` | `Answer`/`Recommendation`, `Evidence`/`Basis` | `Limitations`, `Related` |
| `entity` | `Overview`/`Identity`, `Details`/`Facts` | `Relations`, `Related` |
| `person` | `Identity`/`Overview`, `Details`/`Facts` | `Relations`, `Related` |
| `environment` | `Scope`, `Configuration`/`Facts` | `Validation`, `Operational Notes`, `Related` |
| `preference` | `Preference`, `Rationale` | `Constraints`, `Related` |
| `source` | source metadata and body | no curated `Related` requirement |

The profile checker is case-insensitive. It treats `Related`, `Sources`, and generated `Linked from` as reserved sections when evaluating semantic section uniqueness, while still checking `Related` as the universal required section for curated pages. It must allow additional domain sections, including experiment sections such as `Setup`, `Results`, `Findings`, and `Reproducibility`, without special-casing their subject matter.

For a backtest page, the generic concept profile therefore requires a summary/core-content shape, while domain-specific backtest fields remain ordinary structured content. A later optional domain schema may validate tables and metric units, but it is out of scope for this universal validator.

### 4. Strict and legacy modes

- New curated pages are validated in `strict` mode and rejected when errors exist.
- Updates and appends to existing pages validate the complete resulting page in `strict` mode; this prevents further degradation and requires the caller to repair a malformed page before adding content.
- Existing pages are not rewritten automatically. `lint` validates all pages in `lint` mode and reports errors as legacy findings.
- A future migration/formatter may convert legacy pages, but it is not part of this change.
- Source pages retain their existing read-only behavior and use the source profile.

The mode is an implementation detail of the call site; callers must not bypass validation by choosing a weaker mode for normal curated writes.

### 5. Write and append integration

Integrate validation into `WikiVault.write_page` after the final frontmatter/body normalization and before `_atomic_write_text`. The validator must see the exact content that would be persisted, including canonical frontmatter.

Integrate append validation in `MemoryStore.append` after terminal-section insertion has produced the merged document and before calling `write_page`. The existing optimistic revision check and full-page append protection remain unchanged.

On failure, raise `WikiVaultError`/`MemoryWriteError` with a compact summary containing the page path and each stable error code. The MCP adapter should return the existing structured error shape with the validation details included, without writing the file or backlink changes.

Add validation results to `lint` under a dedicated `structure` problem key, grouped by page path. Lint must continue reporting unrelated existing problems such as broken links and weak connectivity.

### 6. Compatibility and generated content

The validator must not inspect or reject the automatically generated `## Linked from` section. It must also preserve the current terminal-section insertion behavior for append operations.

Existing tests and helper fixtures that create minimal pages will be updated to use a small valid template. Tests that intentionally exercise malformed pages will assert validation errors explicitly.

No new runtime dependency is needed. Use the existing frontmatter parser, wikilink regex, page type constants, and date/size checks.

## Error handling

- Malformed Markdown structure returns deterministic validation errors; it does not attempt repair.
- A missing required semantic section identifies the accepted section names in the error message.
- A duplicate heading reports the normalized heading name and the first/repeated line numbers when available.
- A write failure occurs before any file or backlink mutation.
- Legacy lint findings never mutate the vault unless a separate future fix command is explicitly invoked.

## Testing strategy

Add unit tests for the pure validator covering:

- valid pages for every curated type;
- missing frontmatter fields;
- missing and multiple H1 headings;
- skipped heading levels;
- duplicate and empty sections;
- missing profile sections;
- generated `Linked from` exclusion;
- valid extra domain sections;
- source-page behavior;
- stable error codes and line numbers.

Add integration tests covering:

- `write` rejects an invalid new page and leaves no file/backlink mutation;
- `write` accepts a valid page and preserves canonical frontmatter;
- `append` rejects a merged invalid document;
- `append` accepts a valid section before terminal metadata sections;
- `lint` reports structure findings for legacy pages without modifying them;
- MCP responses expose validation details consistently.

Run the complete existing test suite and a real temporary-vault write/read/lint smoke test before claiming completion.

## Non-goals

- Automatically rewriting or reformatting Markdown.
- Enforcing domain-specific tables for backtests, finance, or trading.
- Replacing the existing link, frontmatter, duplicate, or size validation.
- Adding a database or search feature.
- Migrating every existing legacy page in this change.

## Open implementation notes

The implementation should keep the validator independent from `WikiVault` so future page profiles can be added without increasing write-path complexity. The first follow-up after this change can add a migration formatter for legacy pages, using the same profile definitions and error codes.
