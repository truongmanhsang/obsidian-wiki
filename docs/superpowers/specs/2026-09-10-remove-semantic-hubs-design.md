# Remove Semantic Hubs and Use the Root Index

## Goal

Remove semantic hub behavior from the Obsidian Wiki plugin and the connected
vault while retaining explicit lint orphan auto-fix through the root
`index.md`.

## Scope

This change will:

- remove hub discovery and keyword/priority routing from lint;
- remove LLM hub proposal generation and hub-specific validation;
- remove hub metadata preservation and hub exemptions from page/lint logic;
- keep LLM index generation and existing-index reuse unchanged;
- make orphan auto-fix append validated links to the root `index.md`;
- count root-index links as inbound links when lint evaluates orphans;
- remove hub-specific tests and replace them with generic index-fix tests;
- delete the actual `concepts/trading-hub.md` page from `/Volumes/DATA/agent-vault`;
- remove obsolete semantic-hub documentation from curated wiki pages;
- leave `sources/` transcripts untouched because they are read-only evidence.

Normal notes are not deleted merely because their prose or filename contains the
word “hub”; only the known semantic hub artifact and obsolete hub metadata/docs
are in scope.

## Code Design

### Generation boundary

`obsidian_memory_core/wiki/generation.py` will retain only index proposal
generation and validation. Hub prompt, path validation, and hub proposal APIs
will be removed.

### Lint behavior

`wiki/lint.py` will use one generic orphan destination: root `index.md`.
`fix_orphans` will:

1. collect orphan pages deterministically;
2. propose one canonical root-index bullet per orphan;
3. return the plan unchanged in dry-run mode;
4. atomically update `index.md` only in apply mode;
5. report fixed paths and the post-fix lint result.

No LLM call will be made for orphan routing. Existing index content will be
preserved and new orphan bullets will be added in a dedicated generated
section. The root index is navigation metadata, not a curated page, so its
update will use the existing atomic write helper and log the operation.

The linter will parse root `index.md` links as navigation inbound edges while
continuing to ignore generated backlink sections and raw `sources/` pages.
Hub-specific orphan exemptions and hub result fields will be removed.

### Page writes

Page writes will no longer preserve or interpret `lint_hub`, `lint_keywords`,
or `lint_priority`. Existing frontmatter normalization will continue to keep
the required `type`, `updated`, `tags`, and `aliases` fields. The existing
conditional LLM index lifecycle remains:

- generate an index only when missing or replacing the untouched blank-vault
  placeholder;
- reuse an existing index for ordinary writes, edits, and deletes.

## Vault Migration

Before deleting `concepts/trading-hub.md`, the migration will inspect its
links and preserve useful navigation by ensuring those destinations remain
reachable from `index.md` where necessary. The hub page itself will then be
deleted with revision protection through the native wiki API.

Curated documentation pages that describe semantic hubs or hub generation will
be updated to describe the root-index-only model. Raw `sources/` pages will not
be modified.

## Compatibility and Failure Handling

- `lint` without `fix` remains report-only.
- `fix: true` remains explicit, with dry-run defaulting to true.
- Invalid index content or an unavailable index-generation LLM still falls
  back to the deterministic index renderer.
- Root-index update failures must not silently delete or rewrite curated pages.
- No hub-related LLM call, file creation, or metadata preservation remains.

## Testing

Tests will cover:

1. no hub generation call during first or later page writes;
2. hub metadata is not preserved by normal writes;
3. orphan dry-run proposes root-index links without changing files;
4. apply mode updates root `index.md` and clears those orphan findings;
5. repeated fixes are idempotent;
6. existing LLM index generation/reuse behavior remains intact;
7. invalid index proposals continue to be rejected;
8. the complete test suite passes with no live LLM calls.

## Acceptance Criteria

- No semantic-hub implementation symbols or routing metadata handling remain in
  production code.
- `fix_orphans` targets only root `index.md` and never creates a hub page.
- `/Volumes/DATA/agent-vault/concepts/trading-hub.md` is removed.
- Curated wiki documentation no longer presents semantic hubs as active
  behavior; raw source transcripts remain unchanged.
- Existing index generation/reuse semantics are preserved.
- Full tests pass and the target vault is lint-clean after migration.

## Related

- [[concepts/obsidian-wiki-lint|Obsidian Wiki Lint]]
- [[concepts/obsidian-wiki-index|Obsidian Wiki Memory Index]]
