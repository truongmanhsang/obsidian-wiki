# LLM-Generated Dynamic Hubs and Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a missing wiki hub and missing/blank-vault index with the configured LLM, then reuse existing hubs and indexes without regeneration.

**Architecture:** Keep lint detection deterministic and move hub discovery to `lint_hub`, `lint_keywords`, and `lint_priority` frontmatter. Add a small LLM generation module that returns validated hub/index proposals; `WikiVault` orchestrates bootstrap, orphan linking, and index persistence while preserving deterministic fallbacks. Expose explicit `fix`/`dry_run` arguments through the direct provider and MCP facade.

**Tech Stack:** Python 3.11+, existing `WikiVault`/`MemoryStore` classes, Hermes `agent.oneshot.run_oneshot`, PyYAML-compatible frontmatter conventions, pytest.

## Global Constraints

- No semantic category keyword or hub path may remain hard-coded in the resolver.
- Generate a hub or index only when the artifact is missing; reuse valid existing artifacts as-is.
- Treat the untouched skeleton `index.md` as missing during first-write bootstrap.
- Never overwrite an existing hub page or a valid existing index.
- Validate every LLM path, link, frontmatter field, and duplicate before writing.
- LLM failure must not fail the original page write; use the deterministic fallback.
- `dry_run` must return proposals without writing files.
- Use the existing write lock and atomic-write helpers.
- Keep `sources/` read-only and do not store credentials, prompts, or raw LLM output in the wiki.
- Preserve the user’s existing uncommitted changes in `lint.py`, `vault.py`, and `tests/test_obsidianwiki.py`.

## File Map

- Create: `obsidian_memory_core/wiki/generation.py` — LLM request/response parsing and proposal validation helpers.
- Modify: `obsidian_memory_core/wiki/lint.py` — dynamic hub discovery and LLM-backed missing-hub proposal flow.
- Modify: `obsidian_memory_core/wiki/vault.py` — bootstrap orchestration, navigation-root handling, and write-time integration.
- Modify: `obsidian_memory_core/wiki/index.py` — preserve existing indexes and render deterministic fallback indexes only when needed.
- Modify: `obsidian_memory_core/store.py` — expose safe `fix_orphans` behavior to MCP callers.
- Modify: `mcp_server.py` — add explicit `fix` and `dry_run` arguments to `memory_lint`.
- Modify: `__init__.py` — pass lint fix arguments through the direct provider/MCP adapter schema.
- Modify: `tests/test_obsidianwiki.py` — unit, integration, and failure-path coverage.
- Modify: `README.md` — document hub frontmatter, first-write generation, reuse policy, and dry-run usage.

---

### Task 1: Replace hard-coded category rules with dynamic hub discovery

**Files:**
- Modify: `obsidian_memory_core/wiki/lint.py:8-55`
- Modify: `obsidian_memory_core/wiki/vault.py:1342-1348`
- Test: `tests/test_obsidianwiki.py:903-925`

**Interfaces:**
- Consumes: loaded page dictionaries containing `rel`, `title`, `ptype`, `body`, and `meta`.
- Produces: `_hub_for_orphan(vault, orphan_rel, title="", ptype="", tags=None, body="") -> str | None` and `discover_hubs(vault) -> list[dict]`.

- [ ] **Step 1: Write failing tests for frontmatter-defined hubs**

Add tests to `TestLint`:

```python
def test_orphan_fix_discovers_hub_from_frontmatter(self, provider):
    _call(provider, action="write", page="concepts/trading-hub",
          content=("---\n"
                   "lint_hub: true\n"
                   "lint_keywords: [trade, freqtrade, mt5]\n"
                   "lint_priority: 100\n"
                   "---\n\n# Trading Hub\n\nTrading topics.\n"))
    hub = provider._get_vault()._hub_for_orphan(
        "entities/gold-mt5-bot.md", title="Gold MT5 Bot", ptype="entity",
        tags=["automation"], body="MT5 trading system"
    )
    assert hub == "concepts/trading-hub.md"

def test_non_hub_page_keywords_are_ignored(self, provider):
    _call(provider, action="write", page="concepts/trading-notes",
          content=("---\n"
                   "lint_keywords: [trade]\n"
                   "---\n\n# Trading Notes\n\nNotes.\n"))
    _call(provider, action="write", page="concepts/obsidian-wiki-index",
          content="# Index\n\nNavigation.\n")
    assert provider._get_vault()._hub_for_orphan(
        "entities/gold-mt5-bot.md", title="Gold MT5 Bot", body="trading"
    ) == "concepts/obsidian-wiki-index.md"

def test_hub_priority_wins_and_path_breaks_ties(self, provider):
    for page, priority in (("concepts/z-trading-hub", 10), ("concepts/a-trading-hub", 10),
                           ("concepts/high-trading-hub", 20)):
        _call(provider, action="write", page=page,
              content=(f"---\nlint_hub: true\nlint_keywords: [trade]\n"
                       f"lint_priority: {priority}\n---\n\n# Hub\n"))
    assert provider._get_vault()._hub_for_orphan(
        "entities/trade-bot.md", title="Trade Bot", body="trade"
    ) == "concepts/high-trading-hub.md"
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run:

```bash
pytest tests/test_obsidianwiki.py::TestLint::test_orphan_fix_discovers_hub_from_frontmatter tests/test_obsidianwiki.py::TestLint::test_non_hub_page_keywords_are_ignored tests/test_obsidianwiki.py::TestLint::test_hub_priority_wins_and_path_breaks_ties -v
```

Expected: FAIL because the current resolver still reads `_CATEGORY_RULES` and does not discover `lint_hub` metadata.

- [ ] **Step 3: Implement dynamic discovery and deterministic selection**

In `lint.py`, replace `_CATEGORY_RULES` with helpers equivalent to:

```python
def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("'\"").lower() for item in text.split(",") if item.strip()]

def discover_hubs(vault) -> list[dict]:
    hubs = []
    for page in vault.load_pages():
        meta = page.get("meta", {})
        if not _as_bool(meta.get("lint_hub")):
            continue
        keywords = _as_list(meta.get("lint_keywords"))
        if not keywords or not page["path"].exists():
            continue
        try:
            priority = int(str(meta.get("lint_priority", "0")).strip() or "0")
        except ValueError:
            priority = 0
        hubs.append({"path": page["rel"], "keywords": keywords,
                     "priority": priority, "page": page})
    return sorted(hubs, key=lambda hub: (-hub["priority"], hub["path"].lower()))
```

Build the orphan haystack from the existing path/title/type/tags/body inputs,
match normalized keyword substrings as the current behavior does, and return
the first matching discovered hub. Keep only the generic fallback for an
unmatched orphan; remove semantic category paths from Python source.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run the three tests from Step 2. Expected: PASS.

- [ ] **Step 5: Run the existing lint suite**

```bash
pytest tests/test_obsidianwiki.py::TestLint -v
```

Expected: PASS, including the user’s existing semantic-routing tests after
updating their hub fixtures to use `lint_hub` frontmatter.

- [ ] **Step 6: Commit the resolver change**

```bash
git add obsidian_memory_core/wiki/lint.py obsidian_memory_core/wiki/vault.py tests/test_obsidianwiki.py
git commit -m "feat: discover orphan hubs from frontmatter"
```

### Task 2: Add a validated LLM generation boundary

**Files:**
- Create: `obsidian_memory_core/wiki/generation.py`
- Test: `tests/test_obsidianwiki.py` in a new `TestLLMGeneration` class

**Interfaces:**
- Consumes: an orphan page, existing hub summaries, or an authoritative page manifest.
- Produces: `generate_hub_proposal(context, run_llm=None) -> dict` and `generate_index_proposal(manifest, run_llm=None) -> dict`.

- [ ] **Step 1: Write failing tests for proposal parsing and rejection**

Add tests using injected `run_llm` callables, not a live model:

```python
def test_hub_proposal_requires_safe_concept_path(self):
    from obsidian_memory_core.wiki.generation import generate_hub_proposal
    proposal = generate_hub_proposal(
        {"pages": [{"path": "entities/gold-bot.md", "title": "Gold Bot"}]},
        run_llm=lambda _: {"path": "../../secrets.md", "title": "Bad", "keywords": ["gold"]},
    )
    assert proposal["error"] == "invalid_path"

def test_index_proposal_rejects_unknown_wikilink(self):
    from obsidian_memory_core.wiki.generation import generate_index_proposal
    result = generate_index_proposal(
        [{"path": "entities/gold-bot.md", "title": "Gold Bot", "type": "entity"}],
        run_llm=lambda _: {"content": "---\ntype: index\n---\n\n[[entities/missing]]"},
    )
    assert result["error"] == "invalid_link"

def test_llm_exception_returns_fallback_error(self):
    from obsidian_memory_core.wiki.generation import generate_hub_proposal
    result = generate_hub_proposal({}, run_llm=lambda _: (_ for _ in ()).throw(TimeoutError()))
    assert result["error"] == "llm_unavailable"
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

```bash
pytest tests/test_obsidianwiki.py::TestLLMGeneration -v
```

Expected: FAIL because `generation.py` does not exist.

- [ ] **Step 3: Implement the generation boundary**

Implement lazy use of Hermes’ configured runtime:

```python
def _default_run_llm(prompt: str):
    from agent.oneshot import run_oneshot
    return run_oneshot(
        instructions=prompt,
        user_input="",
        task="memory_navigation_generation",
        max_tokens=1800,
        temperature=0.2,
        timeout=90.0,
    )
```

`generate_hub_proposal` must request and normalize JSON fields `path`,
`title`, `body`, `keywords`, and `priority`; require a relative `.md` path
under `concepts/`; reject path traversal, empty titles, empty keywords,
duplicate keywords, and existing target paths; and return either the validated
proposal or `{ "error": <stable_code> }`.

`generate_index_proposal` must accept a manifest, request Markdown, require
the index frontmatter contract, extract every wikilink, and reject links that
do not resolve to a manifest path or the allowed generated navigation targets.
Use `yaml.safe_load` only for validating generated frontmatter and never write
the raw response before validation.

- [ ] **Step 4: Run the focused tests and verify they pass**

```bash
pytest tests/test_obsidianwiki.py::TestLLMGeneration -v
```

Expected: PASS.

- [ ] **Step 5: Commit the generation boundary**

```bash
git add obsidian_memory_core/wiki/generation.py tests/test_obsidianwiki.py
git commit -m "feat: validate LLM wiki navigation proposals"
```

### Task 3: Generate missing hubs and reuse existing hubs

**Files:**
- Modify: `obsidian_memory_core/wiki/lint.py:55-160`
- Modify: `obsidian_memory_core/wiki/vault.py:1349-1468`
- Test: `tests/test_obsidianwiki.py` in `TestLint` and `TestLLMGeneration`

**Interfaces:**
- Consumes: `discover_hubs`, `generate_hub_proposal`, and the existing
  `fix_orphans(vault, dry_run=False, run_llm=None)` entry point.
- Produces: a fix result containing `generated_hubs`, `reused_hubs`,
  `generation_errors`, `dry_run`, and the existing lint-after result.

- [ ] **Step 1: Write failing tests for blank-vault generation and reuse**

Add tests with a fake generator that records calls:

```python
def test_first_write_generates_one_hub_when_no_hub_exists(self, provider, monkeypatch):
    calls = []
    def fake_hub(context):
        calls.append(context)
        return {"path": "concepts/trading-hub.md", "title": "Trading Hub",
                "body": "# Trading Hub\n\nTrading topics.\n",
                "keywords": ["trade", "mt5"], "priority": 100}
    monkeypatch.setattr("obsidian_memory_core.wiki.lint.generate_hub_proposal", fake_hub)
    _call(provider, action="write", page="entities/gold-mt5-bot",
          content="# Gold MT5 Bot\n\nTrade automation.\n")
    assert len(calls) == 1
    assert (provider._get_vault().root / "concepts/trading-hub.md").exists()

def test_matching_existing_hub_is_reused_without_llm(self, provider, monkeypatch):
    _call(provider, action="write", page="concepts/trading-hub",
          content=("---\nlint_hub: true\nlint_keywords: [trade]\n---\n\n# Trading Hub\n"))
    calls = []
    monkeypatch.setattr("obsidian_memory_core.wiki.lint.generate_hub_proposal",
                        lambda _: calls.append(True))
    _call(provider, action="write", page="entities/trade-bot",
          content="# Trade Bot\n\nTrade system.\n")
    assert calls == []
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

```bash
pytest tests/test_obsidianwiki.py::TestLint::test_first_write_generates_one_hub_when_no_hub_exists tests/test_obsidianwiki.py::TestLint::test_matching_existing_hub_is_reused_without_llm -v
```

Expected: FAIL because orphan healing does not call the generator.

- [ ] **Step 3: Implement missing-hub generation and safe persistence**

In `fix_orphans`, discover hubs before processing each orphan. If a matching
hub exists, append only the new navigation bullet and record it in
`reused_hubs`. If no match exists, call `generate_hub_proposal` with the
orphan metadata and existing hub manifest. Validate that the proposed path is
new, write it with `_atomic_write_text`, and add its `lint_hub` frontmatter
before inserting the orphan link. Record stable errors instead of raising.

For `dry_run=True`, return the validated proposal in `plan` and do not create
the hub or alter the existing hub text. Ensure generated `lint_hub` pages are
navigation roots and are excluded from the orphan-healing recursion.

Keep the current deterministic generic fallback when proposal generation is
unavailable. Do not call the LLM again for an existing matching hub.

- [ ] **Step 4: Run the focused tests and verify they pass**

```bash
pytest tests/test_obsidianwiki.py::TestLint -v
```

Expected: PASS.

- [ ] **Step 5: Commit hub generation**

```bash
git add obsidian_memory_core/wiki/lint.py obsidian_memory_core/wiki/vault.py tests/test_obsidianwiki.py
git commit -m "feat: generate missing wiki hubs with LLM"
```

### Task 4: Generate the index only when missing and reuse it afterward

**Files:**
- Modify: `obsidian_memory_core/wiki/index.py:7-100`
- Modify: `obsidian_memory_core/wiki/vault.py:220-240, 640-680, 800-830`
- Modify: `obsidian_memory_core/wiki/generation.py`
- Test: `tests/test_obsidianwiki.py` in a new `TestLLMIndexLifecycle` class

**Interfaces:**
- Consumes: `generate_index_proposal(manifest, run_llm=None) -> dict` and
  `WikiVault.is_blank_vault() -> bool`.
- Produces: `WikiVault.ensure_index_generated(was_blank: bool, run_llm=None) -> dict`.

- [ ] **Step 1: Write failing tests for placeholder replacement and reuse**

```python
def test_blank_first_write_replaces_skeleton_index_with_llm_index(self, provider, monkeypatch):
    generated = []
    monkeypatch.setattr(
        "obsidian_memory_core.wiki.vault.generate_index_proposal",
        lambda manifest: generated.append(manifest) or {
            "content": "---\ntype: index\nupdated: 2026-09-10\n---\n\n# LLM Index\n\n- [[entities/first-page|First Page]]\n"
        },
    )
    _call(provider, action="write", page="entities/first-page",
          content="# First Page\n\nFirst content.\n")
    index = (provider._get_vault().root / "index.md").read_text()
    assert "# LLM Index" in index
    assert generated

def test_existing_index_is_reused_after_new_page(self, provider, monkeypatch):
    _call(provider, action="write", page="entities/first-page",
          content="# First Page\n\nFirst content.\n")
    index_path = provider._get_vault().root / "index.md"
    original = index_path.read_text()
    calls = []
    monkeypatch.setattr("obsidian_memory_core.wiki.vault.generate_index_proposal",
                        lambda _: calls.append(True))
    _call(provider, action="write", page="entities/second-page",
          content="# Second Page\n\nSecond content.\n")
    assert calls == []
    assert index_path.read_text() == original
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

```bash
pytest tests/test_obsidianwiki.py::TestLLMIndexLifecycle -v
```

Expected: FAIL because the current write path deterministically rebuilds the
index on every write and has no LLM bootstrap step.

- [ ] **Step 3: Implement blank-vault detection and conditional generation**

Add `is_blank_vault()` based on curated pages returned by `load_pages()`;
exclude `sources/` and generated navigation files. Capture `was_blank` before
the first page write. Keep `ensure_skeleton()` able to create the basic index
placeholder, but replace it with the validated LLM index after the first
meaningful write.

Change the write path so it does not call the deterministic `rebuild_index()`
unconditionally. After the page and any generated hub are persisted, call
`ensure_index_generated(was_blank=was_blank)`. It must:

- call the LLM when `index.md` is absent or `was_blank` is true;
- pass the complete authoritative manifest;
- atomically write only validated LLM content;
- preserve any existing non-placeholder index;
- use the current deterministic renderer as a fallback if generation fails;
- return/log a stable error without failing the page write.

Keep `rebuild_index()` available for explicit maintenance and fallback use,
but do not use it to overwrite an established index during ordinary writes.

- [ ] **Step 4: Add navigation-root regression tests**

Verify that a generated hub and `index.md` do not appear as repeated orphan
fix targets, and that the index validator accepts only canonical manifest
links. Include an LLM failure test that asserts the page remains on disk and
the deterministic fallback index is present.

- [ ] **Step 5: Run the focused and full tests**

```bash
pytest tests/test_obsidianwiki.py::TestLLMIndexLifecycle -v
pytest -q
```

Expected: both commands pass.

- [ ] **Step 6: Commit index lifecycle behavior**

```bash
git add obsidian_memory_core/wiki/index.py obsidian_memory_core/wiki/vault.py obsidian_memory_core/wiki/generation.py tests/test_obsidianwiki.py
git commit -m "feat: bootstrap and reuse LLM wiki index"
```

### Task 5: Expose safe auto-fix through the shared MCP and direct APIs

**Files:**
- Modify: `obsidian_memory_core/store.py:100-105`
- Modify: `mcp_server.py:76-115`
- Modify: `__init__.py:170-215, 640-660`
- Test: `tests/test_obsidianwiki.py` in provider/MCP tests

**Interfaces:**
- Consumes: `MemoryStore.vault.fix_orphans(dry_run=...)`.
- Produces: `memory_lint(fix: bool = False, dry_run: bool = True) -> dict` and
  direct `obsidian_wiki(action="lint", fix=True, dry_run=True)` behavior.

- [ ] **Step 1: Write failing API tests**

```python
def test_mcp_memory_lint_accepts_fix_and_dry_run(self, monkeypatch):
    import mcp_server
    calls = []
    monkeypatch.setattr(mcp_server._store().__class__, "fix_orphans",
                        lambda self, dry_run=False: calls.append(dry_run) or {"fixed": 0})
    result = mcp_server.memory_lint(fix=True, dry_run=True)
    assert result["fix_orphans"] == {"fixed": 0}
    assert calls == [True]
```

Add a direct-provider test confirming `fix` is retained when MCP access is
disabled and that the MCP adapter receives both arguments when enabled.

- [ ] **Step 2: Run the focused tests and verify the expected failure**

```bash
pytest tests/test_obsidianwiki.py -k "memory_lint or lint_fix" -v
```

Expected: FAIL because `memory_lint` has no parameters and the current MCP
argument allow-list drops all lint options.

- [ ] **Step 3: Implement the API wiring**

Add to `MemoryStore`:

```python
def fix_orphans(self, dry_run: bool = False) -> dict[str, Any]:
    with self._write_lock():
        return self.vault.fix_orphans(dry_run=dry_run)
```

Change the MCP tool signature to:

```python
@mcp.tool()
def memory_lint(fix: bool = False, dry_run: bool = True) -> dict[str, Any]:
    store = _store(prepare=fix and not dry_run)
    if not fix:
        return store.lint()
    return {"lint": store.lint(),
            "fix_orphans": store.fix_orphans(dry_run=dry_run)}
```

Update the direct provider schema to include boolean `fix` and `dry_run`, and
change the MCP allow-list for `lint` to `{ "fix", "dry_run" }`. Keep the
default read-only behavior when `fix` is omitted.

- [ ] **Step 4: Run API tests and full regression tests**

```bash
pytest tests/test_obsidianwiki.py -k "memory_lint or lint_fix" -v
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit API exposure**

```bash
git add obsidian_memory_core/store.py mcp_server.py __init__.py tests/test_obsidianwiki.py
git commit -m "feat: expose safe lint auto-fix through MCP"
```

### Task 6: Document the user-facing workflow and verify the branch

**Files:**
- Modify: `README.md:20-40, 830-840`
- Test: `tests/test_obsidianwiki.py` full suite

- [ ] **Step 1: Write the documentation examples**

Document that only hub pages carry routing metadata:

```yaml
---
type: concept
lint_hub: true
lint_keywords: [trade, trading, freqtrade, mt5]
lint_priority: 100
---
```

Document the lifecycle: first meaningful write in a blank vault generates the
missing hub and index through the configured LLM; later writes reuse existing
artifacts; a missing artifact is the only generation trigger; `dry_run` shows
proposals without writing.

- [ ] **Step 2: Run formatting and repository verification**

```bash
git diff --check
pytest -q
```

Expected: no whitespace errors and all tests pass.

- [ ] **Step 3: Inspect the final diff for scope and accidental overwrites**

```bash
git status --short
git diff --stat HEAD~5..HEAD
git diff -- obsidian_memory_core/wiki/lint.py obsidian_memory_core/wiki/vault.py obsidian_memory_core/wiki/index.py obsidian_memory_core/wiki/generation.py obsidian_memory_core/store.py mcp_server.py __init__.py README.md
```

Confirm the pre-existing user edits are retained and no vault files, secrets,
or generated runtime artifacts were committed.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain LLM-generated wiki navigation"
```

## Completion Checklist

- [ ] Dynamic hub discovery is frontmatter-driven and contains no semantic rule table.
- [ ] Blank-vault first write generates a validated hub and index when an LLM is available.
- [ ] Existing hubs and indexes are reused without regeneration.
- [ ] LLM failures preserve page writes and use deterministic fallbacks.
- [ ] Dry-run is non-mutating.
- [ ] MCP and direct APIs expose explicit auto-fix controls.
- [ ] Full pytest suite passes.
