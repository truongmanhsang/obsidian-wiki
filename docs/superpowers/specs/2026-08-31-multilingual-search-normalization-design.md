# Multilingual Search Normalization Design

## Goal

Improve search recall for accented and unaccented Latin-script queries while preserving correct behavior for non-Latin scripts. Search normalization must be applied consistently across lexical and FTS retrieval without changing stored page content or displayed snippets.

## Scope

- Normalize queries and searchable page fields: title, stem, body, aliases, tags, and `search_terms`.
- Apply Unicode NFKC normalization, Unicode case folding, and whitespace normalization for every script.
- Remove combining marks only for Latin-script text.
- Preserve original page text for display, exact matching, and snippets.
- Add regression tests for Vietnamese and other accented Latin text, Unicode case folding, and non-Latin text.

## Approaches considered

### Global combining-mark removal

Normalize every script with NFD and remove all `Mn` characters. This is simple, but can change meaning in Arabic and other scripts. Rejected for safety.

### Latin-aware shared normalization (recommended)

Use one shared normalizer for all search input and fields. Always apply NFKC, case folding, and whitespace cleanup; remove combining marks only when the text contains Latin-script characters. Keep original content beside the normalized projection. This gives the requested Vietnamese recall while minimizing cross-language semantic changes.

### Language-specific normalization registry

Select normalization rules from page/query language metadata. This is the most precise long-term option, but the vault currently does not require reliable language metadata. Defer until the shared baseline is measured.

## Architecture and data flow

`normalize_search()` will live in the shared intent/search utility layer. The FTS index will include a normalized search projection built from the searchable fields, while retaining original title/body columns for result display. Keyword scoring and exact title/alias checks will use the same normalized representation. Search results and snippets remain based on original text.

The implementation should avoid repeatedly normalizing the same page during one request. Existing page snapshots and FTS rebuild logic should be reused where possible. Existing embedding behavior is out of scope; normalization improves lexical retrieval and the text used to identify exact/anchor matches.

## Ranking behavior

Exact matches against original text retain the strongest priority. Normalized matches improve candidate recall but must not outrank an exact original title or alias solely because of accent folding. Existing semantic and recency scoring remains unchanged initially.

## Error handling and compatibility

Non-string inputs are converted using the existing query handling conventions. Empty normalized queries return no results. Existing page files, frontmatter, APIs, and result shapes remain backward compatible. Existing FTS databases must rebuild or migrate safely when the normalized projection schema changes.

## Testing

Add tests proving:

- `"cà phê"` finds content indexed as `"ca phe"` and vice versa.
- Unicode case variants match consistently.
- NFKC-equivalent forms match.
- Non-Latin text remains searchable without stripping meaningful marks.
- FTS and keyword paths return consistent candidates.
- Existing exact title/alias ranking and snippets remain stable.

Success means improved accented/unaccented Latin recall with no regression in exact matching, non-Latin retrieval, or result format.

## Related

- [[concepts/obsidian-wiki-retrieval-and-search|Obsidian Wiki Retrieval and Search]]
- [[entities/obsidianwiki-plugin|obsidianwiki Plugin]]
