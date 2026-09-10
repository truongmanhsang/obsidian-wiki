# Remove Semantic Hubs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove semantic hub behavior while retaining explicit orphan auto-fix through the root `index.md`.

**Architecture:** Keep the existing LLM index-generation boundary and conditional index lifecycle. Simplify lint repair to a deterministic root-index navigation update, and make the linter count root-index links as inbound edges. Remove hub-specific generation, routing metadata, exports, tests, and curated vault artifacts.

**Tech Stack:** Python 3.11+, pytest, PyYAML, existing atomic-write/log helpers, native Obsidian Wiki MCP tools for vault migration.

## Global Constraints

- Do not modify `sources/` pages in `/Volumes/DATA/agent-vault`.
- Do not delete ordinary notes merely because their name or prose contains “hub”.
- Delete only the known semantic hub artifact `concepts/trading-hub.md` and obsolete hub metadata/documentation.
- Keep `fix: true` explicit and keep `dry_run: true` as the default for fix requests.
- Keep LLM index generation only for a missing index or untouched blank-vault placeholder.
- Never call an LLM for orphan routing or create a hub page.
- Use atomic writes and the existing `MemoryStore` write lock for persisted navigation changes.
- Preserve existing user changes; do not reset or checkout files.

---

### Task 1: Replace hub-based orphan repair with root-index repair

**Files:**
- Modify: `obsidian_memory_core/wiki/lint.py`
- Modify: `obsidian_memory_core/wiki/vault.py`
- Modify: `obsidian_memory_core/wiki/frontmatter.py`
- Modify: `obsidian_memory_core/wiki/__init__.py`
- Test: `tests/test_obsidianwiki.py`

**Interfaces:**
- Consumes: `WikiVault.load_pages()`, `WikiVault.index_path`, `first_summary_line()`, `WIKILINK_RE`, and `_atomic_write_text()`.
- Produces: `fix_orphans(vault, dry_run=False) -> dict` with `orphans`, `fixed`, `dry_run`, `plan`, `index_updated`, `lint_after`, and `broken_links_after` fields; no hub fields or hub callback.

- [ ] **Step 1: Write failing tests for generic root-index fixing**

Add tests that create an orphan page and assert:

```python
def test_orphan_fix_dry_run_targets_root_index(provider):
    _call(provider, action="write", page="entities/orphan-page",
          content="# Orphan Page\n\nStandalone content.\n")
    vault = provider._get_vault()
    before = vault.index_path.read_text(encoding="utf-8")
    result = vault.fix_orphans(dry_run=True)
    assert result["dry_run"] is True
    assert result["plan"][0]["index"] == "index.md"
    assert vault.index_path.read_text(encoding="utf-8") == before

def test_orphan_fix_updates_root_index_and_is_idempotent(provider):
    _call(provider, action="write", page="entities/orphan-page",
          content="# Orphan Page\n\nStandalone content.\n")
    vault = provider._get_vault()
    first = vault.fix_orphans(dry_run=False)
    assert first["fixed"] == 1
    assert "[[entities/orphan-page|Orphan Page]]" in vault.index_path.read_text()
    second = vault.fix_orphans(dry_run=False)
    assert second["fixed"] == 0
```

Also add a regression assertion that a write containing `lint_hub`,
`lint_keywords`, and `lint_priority` does not persist those keys.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
PYTHONPATH=/Users/truongmanhsang/.hermes/hermes-agent .venv/bin/pytest -q tests/test_obsidianwiki.py::TestLint::test_orphan_fix_dry_run_targets_root_index tests/test_obsidianwiki.py::TestLint::test_orphan_fix_updates_root_index_and_is_idempotent
```

Expected: FAIL because the current fixer selects a semantic hub/generic concept page and does not expose an `index` plan field.

- [ ] **Step 3: Implement the deterministic index fixer**

Remove `discover_hubs`, `_matching_hub`, `_hub_for_orphan`, the
`generate_hub_proposal` import, all hub-generation branches, and hub result
fields from `wiki/lint.py`. Build one plan entry per orphan:

```python
entry = {
    "orphan": rel,
    "title": title,
    "summary": summary,
    "index": "index.md",
}
```

In apply mode, insert missing bullets under a dedicated `## Auto-linked`
section in `index.md`, using `_atomic_write_text(vault.index_path, text)` and
`vault.append_log("LINT", "auto-linked ... to index.md", quiet=True)`. Compare
canonical link targets by stem/path so repeated calls do not duplicate bullets.
Return the post-fix lint result and preserve the existing dry-run behavior.

Update `_lint_impl()` to parse the root index before checking orphans and add
`index.md` to the inbound set for each valid canonical link. Remove the
`lint_hub` exemption. Remove `lint_keywords` from both frontmatter parsers,
remove hub metadata preservation in `write_page`, and remove `_hub_for_orphan`
from the package re-exports and the `WikiVault` wrapper.

- [ ] **Step 4: Run focused tests**

Run the two generic fixer tests and the existing API tests:

```bash
PYTHONPATH=/Users/truongmanhsang/.hermes/hermes-agent .venv/bin/pytest -q tests/test_obsidianwiki.py::TestLint tests/test_obsidianwiki.py::test_mcp_memory_lint_accepts_fix_and_dry_run tests/test_obsidianwiki.py::test_direct_lint_fix_defaults_to_dry_run
```

Expected: PASS.

- [ ] **Step 5: Commit the orphan-fix removal**

```bash
git add obsidian_memory_core/wiki/lint.py obsidian_memory_core/wiki/vault.py obsidian_memory_core/wiki/frontmatter.py obsidian_memory_core/wiki/__init__.py tests/test_obsidianwiki.py
git commit -m "feat: route orphan fixes through root index"
```

### Task 2: Remove hub generation and index-manifest hub metadata

**Files:**
- Modify: `obsidian_memory_core/wiki/generation.py`
- Modify: `obsidian_memory_core/wiki/vault.py`
- Modify: `tests/test_obsidianwiki.py`

**Interfaces:**
- Consumes: existing `generate_index_proposal(manifest, run_llm=None) -> dict`.
- Produces: an index-only generation module and manifest without hub fields.

- [ ] **Step 1: Write failing tests for index-only generation**

Replace hub proposal tests with an assertion that the module no longer exports
the hub API and add a manifest assertion:

```python
def test_generation_module_exports_only_index_proposal():
    import obsidian_memory_core.wiki.generation as generation
    assert not hasattr(generation, "generate_hub_proposal")

def test_index_manifest_has_no_hub_metadata(provider):
    manifest = provider._get_vault()._index_manifest()
    assert all("lint_hub" not in page for page in manifest)
```

- [ ] **Step 2: Run focused tests and verify failure**

```bash
PYTHONPATH=/Users/truongmanhsang/.hermes/hermes-agent .venv/bin/pytest -q tests/test_obsidianwiki.py::TestLLMGeneration::test_generation_module_exports_only_index_proposal tests/test_obsidianwiki.py::TestLLMGeneration::test_index_manifest_has_no_hub_metadata
```

Expected: FAIL because the hub API and manifest field still exist.

- [ ] **Step 3: Remove hub generation code**

Delete `_hub_prompt`, `_safe_hub_path`, `generate_hub_proposal`, and hub-only
normalization code from `generation.py`; keep `_default_run_llm`, index prompt,
payload parsing, index validation, and `generate_index_proposal`. Remove the
`lint_hub` field from `WikiVault._index_manifest()`.

- [ ] **Step 4: Remove hub-specific lifecycle tests and add no-call coverage**

Delete `TestLLMHubLifecycle` and all frontmatter hub-routing tests. Add a test
that monkeypatches the former hub-generation location if present or simply
asserts that a page write creates no new `*-hub.md` page and that `index.md`
generation remains the only navigation LLM call.

- [ ] **Step 5: Run the generation and lifecycle tests**

```bash
PYTHONPATH=/Users/truongmanhsang/.hermes/hermes-agent .venv/bin/pytest -q tests/test_obsidianwiki.py::TestLLMGeneration tests/test_obsidianwiki.py::TestLLMIndexLifecycle
```

Expected: PASS.

- [ ] **Step 6: Commit the generation removal**

```bash
git add obsidian_memory_core/wiki/generation.py obsidian_memory_core/wiki/vault.py tests/test_obsidianwiki.py
git commit -m "refactor: remove semantic hub generation"
```

### Task 3: Update plugin documentation and public descriptions

**Files:**
- Modify: `README.md`
- Modify: `__init__.py`
- Modify: `obsidian_memory_core/wiki/index.py`
- Test: `tests/test_obsidianwiki.py` only if public schema assertions need updates.

**Interfaces:**
- Consumes: the root-index-only lint behavior from Tasks 1–2.
- Produces: documentation that describes index generation/reuse and explicit
  root-index orphan fixes without semantic hubs.

- [ ] **Step 1: Remove obsolete hub documentation**

Replace the README navigation section with:

```markdown
### LLM-generated index

The configured LLM generates the root `index.md` only when it is missing or is
the untouched blank-vault placeholder. Existing indexes are reused. Lint orphan
fixes are explicit and add validated links to `index.md`; `dry_run` defaults to
true for fix requests.
```

Update the module and tool descriptions so they no longer promise hub creation
or reuse. Keep `fix` and `dry_run` in the public schema.

- [ ] **Step 2: Run documentation/schema regression tests**

```bash
PYTHONPATH=/Users/truongmanhsang/.hermes/hermes-agent .venv/bin/pytest -q tests/test_obsidianwiki.py::test_mcp_memory_lint_accepts_fix_and_dry_run tests/test_obsidianwiki.py::test_mcp_provider_forwards_lint_fix_arguments tests/test_obsidianwiki.py::test_direct_lint_fix_defaults_to_dry_run
```

Expected: PASS.

- [ ] **Step 3: Commit documentation changes**

```bash
git add README.md __init__.py obsidian_memory_core/wiki/index.py tests/test_obsidianwiki.py
git commit -m "docs: describe root-index navigation"
```

### Task 4: Migrate the target vault through native wiki tools

**Files:**
- Modify through native wiki MCP: `/Volumes/DATA/agent-vault/index.md` only as needed.
- Delete through native wiki MCP: `/Volumes/DATA/agent-vault/concepts/trading-hub.md`.
- Update through native wiki MCP: curated documentation pages that describe semantic hubs.
- Do not modify: `/Volumes/DATA/agent-vault/sources/**`.

**Interfaces:**
- Consumes: current revisions from `memory_read`, exact hub-page links, and the
  root-index fixer behavior.
- Produces: a vault without the semantic hub page or active hub documentation,
  with reachable trading destinations and a clean lint report.

- [ ] **Step 1: Read and record revisions before mutation**

Use `memory_read` for `concepts/trading-hub.md`,
`concepts/obsidian-wiki-lint.md`, and
`concepts/obsidian-wiki-retrieval-and-search.md`. Inspect the root `index.md`
with the native Obsidian CLI or the vault’s native file API if required; do not
use shell writes.

- [ ] **Step 2: Preview root-index orphan repair**

Call the native lint tool with:

```json
{"fix": true, "dry_run": true}
```

Confirm that any plan targets `index.md` and that no hub generation proposal is
returned.

- [ ] **Step 3: Preserve useful trading navigation and delete the hub**

Ensure the destinations linked by `concepts/trading-hub.md` are represented in
the root index, then call the native page-delete operation with the exact
revision returned by `memory_read`. Do not delete destination pages.

- [ ] **Step 4: Remove obsolete curated documentation**

Update the lint and retrieval documentation pages to describe the root index
only. Use `memory_write` with each page’s expected revision, then read each
page back to verify.

- [ ] **Step 5: Apply and verify lint repair**

Call:

```json
{"fix": true, "dry_run": false}
```

Then call `memory_lint({})`. Expected: `clean: true`, no orphan/broken-link
problems, and no generated hub pages.

- [ ] **Step 6: Commit only if the vault is a tracked repository change**

The vault is a separate repository. If the native API creates a tracked
working-tree change, inspect it and commit only the intended deletion and
documentation/index changes; never commit unrelated vault changes.

### Task 5: Full verification

**Files:** None.

- [ ] **Step 1: Search production code for removed hub symbols**

```bash
! rg -n "generate_hub|discover_hubs|lint_hub|lint_keywords|lint_priority|_hub_for_orphan|semantic hub" obsidian_memory_core __init__.py mcp_server.py
```

Expected: no output.

- [ ] **Step 2: Run the complete test suite and whitespace check**

```bash
PYTHONPATH=/Users/truongmanhsang/.hermes/hermes-agent .venv/bin/pytest -q
git diff --check
git status --short
```

Expected: all tests pass, no whitespace errors, and only intentional tracked
changes remain.

## Related

- `docs/superpowers/specs/2026-09-10-remove-semantic-hubs-design.md`
- [[concepts/obsidian-wiki-lint|Obsidian Wiki Lint]]
