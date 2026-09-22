# Implementation Plan: Safe YAML Frontmatter and Description-Aware Search

**Goal:** Replace duplicated hand-written frontmatter parsing with safe YAML parsing, preserve optional metadata on writes, and make `description` the preferred summary across indexing, search, and the Obsidian UI without changing trust/freshness ranking.

**Architecture:** Introduce one canonical frontmatter parse/serialize module used by `WikiVault`; keep the existing required metadata contract and folder-derived type validation; derive summaries through a shared helper; enrich search/API results from page metadata so no FTS schema migration is required; update the plugin renderer only where needed to display the new result field.

**Tech Stack:** Python 3, PyYAML `safe_load`/safe serialization, SQLite/FTS5, FastAPI/FastMCP, TypeScript Obsidian plugin, pytest.

**Global Constraints:** Preserve current `type`, `updated`, `tags`, and `aliases` behavior; keep old pages valid without migration; preserve unknown/nested YAML fields on writes; do not implement trust/freshness ranking in this phase; do not overwrite unrelated existing working-tree changes; write tests before production code; verify focused tests and document the known unrelated FastMCP registration-helper failure if it remains.

## Task 1: Map the current metadata, index, search, and UI contracts

**Files to inspect:**

- `obsidian_memory_core/wiki/frontmatter.py`
- `obsidian_memory_core/wiki/vault.py`
- `obsidian_memory_core/wiki/index.py`
- `obsidian_memory_core/wiki/intent.py`
- `obsidian_memory_core/wiki/search.py`
- `obsidian_memory_core/store.py` and `mcp_server.py`
- `obsidian-plugin/src/main.ts` and related renderer files
- `tests/test_core.py`, `tests/test_search.py`, and relevant plugin tests

**Steps:**

1. Record the exact current parser, write, summary, search result, API, and UI boundaries.
2. Identify all callers of the duplicate `WikiVault.parse_frontmatter` method and the shared parser.
3. Confirm the smallest compatible result-shape/UI change needed to expose `description`.
4. Check the current working tree and avoid staging or rewriting the unrelated multilingual embedding changes.

**Verification:** `rg` confirms the call graph and `git diff` confirms unrelated edits remain untouched.

## Task 2: Add red tests for safe parsing and metadata round-tripping

**Files:**

- `tests/test_frontmatter.py` (new if no suitable focused module exists)
- `tests/test_core.py`

**Steps:**

1. Add a test proving nested mappings/lists and Unicode metadata are returned by `yaml.safe_load` as data, not flattened strings.
2. Add tests for legacy scalar fields and inline/block `tags` and `aliases`.
3. Add a malformed/non-mapping YAML test proving parsing is safe and compatibility fallback does not execute constructors.
4. Add a write/read regression test proving optional nested fields and `description` survive a page write while managed core fields are updated normally.
5. Run only these tests and confirm they fail for the current implementation.

**Expected red state:** nested metadata is currently lost or flattened and write-back drops unknown keys; description summary/result assertions are not yet satisfied.

## Task 3: Implement the canonical safe YAML parser and serializer

**Files:**

- `obsidian_memory_core/wiki/frontmatter.py`
- `obsidian_memory_core/wiki/vault.py`
- `obsidian_memory_core/wiki/structure.py` only if type normalization needs a compatibility adjustment

**Steps:**

1. Keep the existing frontmatter boundary detection, but parse the YAML body with `yaml.safe_load`.
2. Normalize YAML date/datetime values and compatibility-sensitive core fields so existing validation and callers retain their current string/list contract.
3. Retain a safe legacy fallback for malformed or non-mapping frontmatter; never use unsafe YAML loaders or constructors.
4. Add a serializer that orders the four managed core fields consistently, preserves optional keys and nested values, allows Unicode, and avoids silently dropping unknown metadata.
5. Remove the duplicate parser implementation from `WikiVault` and route all callers through the canonical module.
6. Update `write_page` to parse existing metadata, update only managed fields, and serialize the complete metadata mapping.
7. Run the new parser/write tests and existing frontmatter/core tests until green.

## Task 4: Make description the canonical summary and search projection

**Files:**

- `obsidian_memory_core/wiki/index.py`
- `obsidian_memory_core/wiki/vault.py`
- `obsidian_memory_core/wiki/intent.py`
- `obsidian_memory_core/wiki/search.py`
- relevant tests

**Steps:**

1. Add one summary helper that returns a trimmed non-empty `description`, otherwise the existing first non-empty body line.
2. Use it for deterministic index entries and the LLM index manifest.
3. Ensure `description` remains in the metadata search projection without changing existing ranking weights.
4. Add `description` to search result data and use it as the snippet fallback when no body match is available.
5. Preserve the existing metadata phrase ranking regression fix and add/retain an assertion that description metadata does not demote a stronger lexical/metadata match.
6. Run focused index/search/core tests and inspect result payloads for old pages without descriptions.

## Task 5: Expose and render description in the web/API and Obsidian plugin UI

**Files:**

- `obsidian_memory_core/store.py` and `mcp_server.py`
- `obsidian-plugin/src/main.ts` and the exact result-card/component files found in Task 1
- plugin tests or fixture snapshots, if present

**Steps:**

1. Confirm the store/MCP API passes through the enriched search result without breaking existing clients.
2. Render `description` in the existing result card/row using the current scrollable result container and styling conventions.
3. Keep the UI safe for missing descriptions and long Unicode text; avoid changing the removed Browse tab behavior or existing scroll layout.
4. Add a focused UI/API regression check if the project has an executable plugin test path; otherwise verify the built bundle and inspect the rendered DOM through the available Obsidian/plugin tooling.

## Task 6: Full verification and handoff

**Files:** no new source files unless verification reveals a narrowly scoped fix.

**Steps:**

1. Run focused Python tests for parser, write, index, search, and MCP/API behavior.
2. Run the plugin typecheck/build/test command documented by the repository.
3. Run the full Python suite and record any remaining unrelated failure separately; do not claim a completely green suite if the known FastMCP registration-helper test still fails.
4. Run `git diff --check` and inspect the final diff for accidental edits to the pre-existing multilingual embedding work.
5. Rebuild/restart the Docker service only if the implementation is intended to be deployed in the local compose environment, then verify health and a live search request.
6. Record the durable implementation decision and any non-obvious parser/search bug fix in the Obsidian Wiki using the required MCP workflow, then read back and lint the target page.

## Execution order

Tasks 1–2 are investigation and red-test setup. Tasks 3–5 are sequential because the parser contract feeds summaries, search results, and UI rendering. Task 6 is the final verification gate.

## Expected outcome

Existing pages continue to work unchanged; pages may add arbitrary safe YAML metadata; metadata survives write/read round trips; `description` is searchable and appears as the preferred summary in indexes, search results, and the UI; trust/freshness semantics remain intentionally deferred.
