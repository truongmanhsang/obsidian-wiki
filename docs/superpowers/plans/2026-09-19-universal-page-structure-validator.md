# Universal Wiki Page Structure Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce readable Markdown structure for every Obsidian Wiki page type on curated writes/appends, while reporting existing legacy violations through lint without rewriting them.

**Architecture:** Add a pure `structure.py` validator with universal Markdown rules and type-specific section profiles. Run it after `WikiVault.write_page` finishes frontmatter normalization and before any filesystem/backlink mutation; run the same validator across all pages during lint. Preserve existing link, frontmatter, duplicate, revision, and generated-backlink behavior.

**Tech Stack:** Python 3.11, pytest, existing frontmatter parser, regex-based Markdown heading scanner, `WikiVault`, `MemoryStore`, direct provider, and FastMCP adapter.

## Global Constraints

- No new runtime dependencies.
- New curated pages and all curated updates/appends use strict validation.
- Existing legacy pages are linted but not automatically rewritten.
- Generated `## Linked from` sections are excluded from authored-content structure checks.
- Validation must occur before page bytes, backlinks, index metadata, or logs are mutated.
- Source pages remain read-only through normal memory writes and retain source-specific validation.
- Existing result shapes remain compatible; validation errors may add structured details.
- Do not edit the Obsidian vault directly; tests use temporary vaults.

---

### Task 1: Build the pure universal structure validator

**Files:**
- Create: `obsidian_memory_core/wiki/structure.py`
- Create: `tests/test_structure.py`

**Interfaces:**
- Produces `validate_page_structure(content: str, page_type: str, *, mode: str = "strict", expected_title: str | None = None) -> dict[str, object]`.
- Returns `{"valid": bool, "mode": str, "errors": list[dict], "warnings": list[dict]}`.
- Each issue has `code`, `message`, and `line` keys; `line` is an integer or `None`.
- Defines universal profile data for `entity`, `person`, `decision`, `environment`, `concept`, `answer`, `preference`, and `source`.
- Internal helpers have these signatures: `scan_headings(body: str) -> list[dict[str, object]]`, `add_frontmatter_issues(meta: dict, errors: list[dict]) -> None`, `add_heading_issues(headings: list[dict], body: str, expected_title: str | None, errors: list[dict]) -> None`, `add_profile_issues(page_type: str, headings: list[dict], body: str, mode: str, errors: list[dict], warnings: list[dict]) -> None`, and `add_link_syntax_issues(body: str, errors: list[dict]) -> None`.

- [ ] **Step 1: Write failing validator tests for valid page profiles.**

Create `tests/test_structure.py` with a small helper that builds valid pages using canonical frontmatter and headings. Cover every page type:

```python
def page(page_type, title, sections):
    body = [f"# {title}", "", "Introductory summary.", ""]
    for heading, text in sections:
        body.extend([f"## {heading}", "", text, ""])
    return (
        "---\n"
        f"type: {page_type}\n"
        "updated: 2026-09-19\n"
        "tags:\n  - test\n"
        "aliases:\n  - Test Page\n"
        "---\n\n"
        + "\n".join(body)
    )


@pytest.mark.parametrize("page_type,sections", [
    ("concept", [("Core Content", "A durable explanation."), ("Related", "- [[concepts/other]]")]),
    ("decision", [("Context", "The problem."), ("Decision", "Choose the tested approach."), ("Rationale", "It is safer."), ("Related", "- [[concepts/other]]")]),
    ("answer", [("Answer", "The answer."), ("Evidence", "Verified evidence."), ("Related", "- [[concepts/other]]")]),
    ("entity", [("Details", "Entity facts."), ("Related", "- [[concepts/other]]")]),
    ("person", [("Details", "Person facts."), ("Related", "- [[concepts/other]]")]),
    ("environment", [("Scope", "Machine scope."), ("Configuration", "Stable configuration."), ("Related", "- [[concepts/other]]")]),
    ("preference", [("Preference", "Use concise output."), ("Rationale", "It is easier to review."), ("Related", "- [[concepts/other]]")]),
])
def test_valid_curated_profiles(page_type, sections):
    result = validate_page_structure(page(page_type, "Test Page", sections), page_type)
    assert result["valid"] is True
    assert result["errors"] == []


def test_source_profile_does_not_require_curated_sections():
    result = validate_page_structure(
        "---\ntype: source\nupdated: 2026-09-19\ntags: []\naliases: []\n---\n\nCaptured source text.\n",
        "source",
    )
    assert result["valid"] is True
```

- [ ] **Step 2: Run the new tests and confirm the expected red failure.**

Run: `pytest tests/test_structure.py -q`  
Expected: FAIL because `obsidian_memory_core/wiki/structure.py` and `validate_page_structure` do not exist.

- [ ] **Step 3: Write failing tests for universal structural errors and stable issue codes.**

Add tests for missing frontmatter, missing/multiple H1, skipped heading levels, duplicate headings, empty sections, missing profile sections, malformed links, and generated backlinks:

```python
def codes(result):
    return {issue["code"] for issue in result["errors"]}


def test_reports_heading_and_profile_errors_with_lines():
    content = "---\ntype: decision\nupdated: 2026-09-19\ntags: []\naliases: []\n---\n\n# Bad\n\n## Context\n\n## Context\n\n#### Decision\n\n"
    result = validate_page_structure(content, "decision")
    assert result["valid"] is False
    assert {"duplicate_heading", "empty_section", "heading_level_skip", "missing_profile_section"} <= codes(result)
    assert all(issue["line"] is None or issue["line"] >= 1 for issue in result["errors"])


def test_generated_linked_from_section_is_excluded():
    content = page("concept", "Test Page", [("Core Content", "Explanation."), ("Related", "")])
    content += "\n## Linked from\n\n- [[concepts/source-page|source-page]]\n"
    result = validate_page_structure(content, "concept")
    assert "duplicate_heading" not in codes(result)


def test_extra_domain_sections_are_allowed():
    result = validate_page_structure(
        page("concept", "Experiment", [
            ("Core Content", "Summary."),
            ("Setup", "Parameters."),
            ("Results", "Measured result."),
            ("Findings", "Lesson."),
            ("Reproducibility", "Command and date."),
            ("Related", "- [[concepts/other]]"),
        ]),
        "concept",
    )
    assert result["valid"] is True
```

- [ ] **Step 4: Run the error tests and confirm they fail for the missing implementation.**

Run: `pytest tests/test_structure.py -q`  
Expected: FAIL with import/attribute errors, not fixture assertion errors.

- [ ] **Step 5: Implement `structure.py` with a fence-aware heading scanner and profiles.**

Implement the minimum behavior required by the tests:

```python
HEADING_RE = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>\S(?:.*\S)?)\s*$")

PROFILES = {
    "concept": (("summary", "overview"), ("core content", "explanation")),
    "decision": (("context",), ("decision",), ("rationale",)),
    "answer": (("answer", "recommendation"), ("evidence", "basis")),
    "entity": (("overview", "identity"), ("details", "facts")),
    "person": (("identity", "overview"), ("details", "facts")),
    "environment": (("scope",), ("configuration", "facts")),
    "preference": (("preference",), ("rationale",)),
    "source": (),
}

TERMINAL_HEADINGS = {"related", "sources", "linked from"}


def validate_page_structure(content, page_type, *, mode="strict", expected_title=None):
    errors = []
    warnings = []
    meta, body = parse_frontmatter(content)
    headings = scan_headings(body)
    add_frontmatter_issues(meta, errors)
    add_heading_issues(headings, body, expected_title, errors)
    add_profile_issues(page_type, headings, body, mode, errors, warnings)
    add_link_syntax_issues(body, errors)
    return {
        "valid": not errors,
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
    }
```

The implementation must treat an introductory paragraph between H1 and the first H2 as satisfying a profile’s first summary/overview group. It must ignore the body of fenced code blocks, normalize heading names with `casefold()` and collapsed whitespace, and report line numbers from the original content. Use `mode="lint"` to downgrade legacy-only profile failures to warnings while retaining malformed Markdown as errors.

- [ ] **Step 6: Run the validator tests and refactor only while green.**

Run: `pytest tests/test_structure.py -q`  
Expected: all validator tests pass.

- [ ] **Step 7: Commit the isolated validator.**

Run:

```bash
git add obsidian_memory_core/wiki/structure.py tests/test_structure.py
git commit -m "feat: add universal wiki structure validator"
```

### Task 2: Enforce validation before curated writes and appends

**Files:**
- Modify: `obsidian_memory_core/wiki/vault.py:15-90, 669-860`
- Modify: `obsidian_memory_core/store.py:120-280`
- Modify: `tests/test_core.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- `WikiVault.write_page` calls `validate_page_structure` after final frontmatter canonicalization and before `_atomic_write_text`.
- `MemoryStore.append` validates the merged document before delegating to `WikiVault.write_page`; `write_page` remains the final safety gate.
- A `StructureValidationError(WikiVaultError)` carries `page`, `report`, and a stable formatted message.

- [ ] **Step 1: Add red integration tests for write rejection and no mutation.**

Add tests using the existing temporary provider fixture:

```python
def test_write_rejects_invalid_structure_without_creating_file(provider):
    result = _call(provider, action="write", page="concepts/bad-structure",
                    content="# Bad Structure\n\nOnly an intro.\n")
    assert result["error"]
    assert "missing_profile_section" in result["error"]
    assert not (provider._get_vault().root / "concepts/bad-structure.md").exists()


def test_write_accepts_valid_concept_structure(provider):
    result = _call(
        provider,
        action="write",
        page="concepts/good-structure",
        content=(
            "# Good Structure\n\nSummary.\n\n"
            "## Core Content\n\nDurable content.\n\n"
            "## Related\n\n- [[concepts/other]]\n"
        ),
    )
    assert result["status"] == "created"
```

- [ ] **Step 2: Run the focused integration tests and verify the red behavior.**

Run: `pytest tests/test_core.py -k 'structure' -q`  
Expected: FAIL because `write_page` does not yet invoke the validator.

- [ ] **Step 3: Add `StructureValidationError` and invoke the validator before filesystem mutation.**

Import `validate_page_structure` into `vault.py`, define the exception next to `WikiVaultError`, and after the existing frontmatter normalization has rebuilt `content` and before `is_new = not path.exists()` do:

```python
report = validate_page_structure(
    content,
    ptype,
    mode="strict",
    expected_title=self.page_title(body, path.stem),
)
if not report["valid"]:
    raise StructureValidationError(path.relative_to(self.root).as_posix(), report)
```

The exception message must include the page path and each issue code/message. The validation must happen before `_atomic_write_text`, backlink refresh, category navigation, index generation, or logging.

- [ ] **Step 4: Make append validation cover the merged terminal-section result.**

In `MemoryStore.append`, preserve the existing revision and idempotency checks, build `merged`, determine the page type from its folder/frontmatter, and call the same validator before `self.vault.write_page`. Allow `StructureValidationError` to propagate as `MemoryWriteError` compatibility because it subclasses `WikiVaultError`; do not change revision behavior.

- [ ] **Step 5: Add red/green tests for append behavior and generated backlinks.**

Test that an invalid section is rejected without changing the revision, while a valid section is inserted before `## Related` and the generated `## Linked from` section remains accepted:

```python
def test_append_rejects_invalid_merged_document_without_mutation(provider):
    created = _call(provider, action="write", page="concepts/append-structure",
                    content="# Append Structure\n\nSummary.\n\n## Core Content\n\nOriginal.\n\n## Related\n")
    revision = _call(provider, action="read", page="concepts/append-structure")["revision"]
    result = _call(provider, action="append", page="concepts/append-structure",
                   content="## Core Content\n\nDuplicate heading.\n",
                   expected_revision=revision)
    assert "duplicate_heading" in result["error"]
    assert _call(provider, action="read", page="concepts/append-structure")["revision"] == revision


def test_append_keeps_terminal_sections_at_end(provider):
    _call(provider, action="write", page="concepts/append-order",
          content="# Append Order\n\nSummary.\n\n## Core Content\n\nOriginal.\n\n## Related\n")
    revision = _call(provider, action="read", page="concepts/append-order")["revision"]
    result = _call(provider, action="append", page="concepts/append-order",
                   content="## Findings\n\nNew finding.\n",
                   expected_revision=revision)
    assert result["status"] == "updated"
    text = _call(provider, action="read", page="concepts/append-order")["content"]
    assert text.index("## Findings") < text.index("## Related")
```

- [ ] **Step 6: Update direct provider and MCP error serialization.**

Catch `StructureValidationError` before the generic `WikiVaultError` handler in `__init__.py` and return:

```json
{
  "error": "structure_validation",
  "message": "concepts/example.md: missing_profile_section (required: core content or explanation)",
  "page": "concepts/example.md",
  "validation": {"valid": false, "mode": "strict", "errors": [], "warnings": []}
}
```

Add the same explicit response behavior to `mcp_server.py` `memory_write` and `memory_append`, while leaving revision and generic wiki errors unchanged. Add adapter tests asserting the stable error code and report.

- [ ] **Step 7: Run focused tests and commit the write-path integration.**

Run: `pytest tests/test_core.py tests/test_mcp.py -k 'structure or append or write' -q`  
Expected: all selected tests pass.

Commit:

```bash
git add obsidian_memory_core/wiki/vault.py obsidian_memory_core/store.py __init__.py mcp_server.py tests/test_core.py tests/test_mcp.py
git commit -m "feat: enforce page structure on wiki writes"
```

### Task 3: Add structure findings to lint without rewriting legacy pages

**Files:**
- Modify: `obsidian_memory_core/wiki/vault.py:1280-1430`
- Modify: `obsidian_memory_core/wiki/lint.py` only if the compatibility wrapper needs a new result key
- Modify: `tests/test_core.py`

**Interfaces:**
- `WikiVault.lint()` returns the existing problem categories plus `structure`.
- `structure` is a list of objects containing `path`, `errors`, and `warnings`.
- Lint does not write page bytes, backlinks, indexes, or logs.

- [ ] **Step 1: Write the failing lint test.**

Create a legacy malformed page directly in a temporary vault, run lint, and assert it is reported without modification:

```python
def test_lint_reports_structure_errors_without_rewriting(tmp_path):
    from obsidian_memory_core.wiki.vault import WikiVault

    vault = WikiVault(str(tmp_path / "vault"))
    vault.ensure_skeleton()
    path = vault.root / "concepts/legacy.md"
    original = "# Legacy\n\nOld content without the required profile sections.\n"
    path.write_text(original, encoding="utf-8")

    result = vault.lint()

    assert result["problems"]["structure"]
    finding = next(item for item in result["problems"]["structure"] if item["path"] == "concepts/legacy.md")
    assert "missing_profile_section" in {issue["code"] for issue in finding["errors"]}
    assert path.read_text(encoding="utf-8") == original
```

- [ ] **Step 2: Run the lint test and verify it fails because `structure` is absent.**

Run: `pytest tests/test_core.py -k 'lint_reports_structure' -q`  
Expected: FAIL with a missing `structure` problem key.

- [ ] **Step 3: Add lint validation for every page type.**

Initialize `problems["structure"] = []`, call `validate_page_structure(page["text"], page["ptype"], mode="lint", expected_title=page["title"])` for every loaded page, and append only reports containing errors or warnings:

```python
report = validate_page_structure(
    page["text"],
    page["ptype"],
    mode="lint",
    expected_title=page["title"],
)
if report["errors"] or report["warnings"]:
    problems["structure"].append({
        "path": page["rel"],
        "errors": report["errors"],
        "warnings": report["warnings"],
    })
```

Do not call any write/index/backlink method from the lint loop.

- [ ] **Step 4: Add lint tests for valid pages, sources, and generated backlinks.**

Assert valid strict pages are absent from `problems["structure"]`, source pages are evaluated by the source profile, and pages with generated `## Linked from` sections do not receive false duplicate/empty-section findings.

- [ ] **Step 5: Run lint-focused tests and commit.**

Run: `pytest tests/test_core.py -k 'lint or orphan or broken_link' -q`  
Expected: all selected tests pass and existing lint categories remain present.

Commit:

```bash
git add obsidian_memory_core/wiki/vault.py obsidian_memory_core/wiki/lint.py tests/test_core.py
git commit -m "feat: report page structure violations in lint"
```

### Task 4: Align templates, fixtures, documentation, and full verification

**Files:**
- Modify: `obsidian_memory_core/wiki/vault.py:90-125` templates
- Modify: `README.md` page write/lint documentation
- Modify: `tests/test_core.py` minimal-page fixtures that now need valid structure
- Modify: `tests/test_mcp.py` adapter fixtures that create curated pages

**Interfaces:**
- Existing `ENTITY_TEMPLATE` and `CONCEPT_TEMPLATE` produce pages accepted by strict validation.
- Documentation explains that curated write/append operations reject structure errors and lint reports legacy pages.

- [ ] **Step 1: Update built-in templates to satisfy their profiles.**

Ensure the entity template includes `## Details` and `## Related`, and the concept template includes a summary paragraph, `## Core Content`, and `## Related`. Keep the existing frontmatter fields and generated-link behavior intact.

- [ ] **Step 2: Convert test fixtures to valid minimal pages.**

Replace repeated minimal bodies such as `# A\n\nBody.\n` with type-appropriate helpers containing the required sections. Keep intentionally malformed fixtures unchanged and update their assertions to expect `structure_validation` errors.

- [ ] **Step 3: Document the new behavior in README.**

Add a concise “Page structure validation” section describing universal rules, type profiles, strict writes/appends, non-destructive lint findings, stable error codes, and the fact that Markdown is never auto-reformatted.

- [ ] **Step 4: Run the complete test suite.**

Run: `pytest -q`  
Expected: all tests pass with zero failures.

- [ ] **Step 5: Run a temporary-vault smoke test.**

Exercise the real public path in a temporary vault:

```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from obsidian_memory_core import MemoryStore

with TemporaryDirectory() as directory:
    store = MemoryStore(Path(directory) / "vault")
    store.ensure_ready()
    page = store.write(
        "concepts/smoke",
        "# Smoke\n\nSummary.\n\n## Core Content\n\nValidated.\n\n## Related\n",
    )
    assert page["status"] == "created"
    lint = store.lint()
    assert not [x for x in lint["problems"]["structure"] if x["path"] == "concepts/smoke.md"]
PY
```

- [ ] **Step 6: Run final verification and review the diff.**

Run:

```bash
git diff --check
git status --short --branch
git log -4 --oneline
```

Confirm only the planned validator, integration, tests, templates, and README changes exist. Then request code review before merging or delivering the implementation.

- [ ] **Step 7: Commit documentation and fixture updates.**

```bash
git add obsidian_memory_core/wiki/vault.py README.md tests
git commit -m "docs: document universal wiki page structure rules"
```

## Requirement Coverage

- Universal validator module and stable reports: Task 1.
- All curated page types and source behavior: Task 1 and Task 3.
- Strict validation before file/backlink mutation: Task 2.
- Append validation after terminal-section merge: Task 2.
- Non-destructive legacy lint: Task 3.
- Structured direct/MCP error responses: Task 2.
- Templates, fixtures, README, full suite, and smoke test: Task 4.
