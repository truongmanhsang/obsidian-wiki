# FTS Database Migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development.

**Goal:** Add a reusable SQLite migration runner and use it to upgrade legacy wiki FTS databases to the multilingual `search_projection` schema.

**Architecture:** `obsidian_memory_core/db/migrations.py` owns ordered, transactional migrations and records applied versions in a metadata table. `wiki/fts.py` defines the FTS schema and migrations; search invokes the runner before rebuilding or querying. Legacy tables are rebuilt only by the numbered migration that requires it.

**Tech Stack:** Python 3.11+, SQLite, pytest.

## Global Constraints

- Preserve existing indexed page data by rebuilding from vault markdown.
- Keep `memory_reflect` behavior unchanged.
- Do not introduce a third-party migration dependency.
- Migration execution must be idempotent and transaction-safe.

### Task 1: Migration runner

**Files:**
- Create: `obsidian_memory_core/db/__init__.py`
- Create: `obsidian_memory_core/db/migrations.py`
- Test: `tests/test_obsidianwiki.py`

- [ ] Write tests for ordered execution, idempotence, and recorded versions.
- [ ] Implement `Migration` and `migrate()` with a `schema_migrations` table and one transaction per migration.
- [ ] Run migration tests.

### Task 2: FTS migration integration

**Files:**
- Modify: `obsidian_memory_core/wiki/fts.py`
- Test: `tests/test_obsidianwiki.py`

- [ ] Add a legacy FTS migration fixture and verify it upgrades to `search_projection`.
- [ ] Define FTS migrations using the shared runner.
- [ ] Remove the inline schema-drop condition from `build_fts_db()`.
- [ ] Run focused and full applicable tests.

### Task 3: Verification

- [ ] Run `git diff --check`.
- [ ] Run the local test suite and real MCP search/reflect smoke test.
- [ ] Commit the implementation.
