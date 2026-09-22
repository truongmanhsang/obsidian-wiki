"""Unit tests for universal wiki page structure validation."""

import pytest

from obsidian_memory_core.wiki.structure import validate_page_structure


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
        "---\ntype: source\nupdated: 2026-09-19\nextract_status: pending\n---\n\nCaptured source text.\n",
        "source",
    )
    assert result["valid"] is True


def codes(result):
    return {issue["code"] for issue in result["errors"]}


def test_reports_heading_and_profile_errors_with_lines():
    content = "---\ntype: decision\nupdated: 2026-09-19\ntags: []\naliases: []\n---\n\n# Bad\n\n## Context\n\n## Context\n\n#### Decision\n\n"
    result = validate_page_structure(content, "decision")
    assert result["valid"] is False
    assert {"duplicate_heading", "empty_section", "heading_level_skip", "missing_profile_section"} <= codes(result)
    assert all(issue["line"] is None or issue["line"] >= 1 for issue in result["errors"])


def test_reports_missing_frontmatter_and_h1():
    result = validate_page_structure("Body without frontmatter.\n", "concept")
    assert result["valid"] is False
    assert {"missing_frontmatter", "missing_h1", "missing_profile_section"} <= codes(result)


def test_reports_multiple_h1_and_invalid_wikilink():
    content = (
        "---\ntype: concept\nupdated: 2026-09-19\ntags: []\naliases: []\n---\n\n"
        "# First\n\nSummary.\n\n# Second\n\n## Core Content\n\nBody.\n\n"
        "## Related\n\n- [[concepts/unclosed\n"
    )
    result = validate_page_structure(content, "concept")
    assert {"multiple_h1", "invalid_wikilink"} <= codes(result)


def test_lint_downgrades_profile_findings_to_warnings():
    content = "---\ntype: concept\nupdated: 2026-09-19\ntags: []\naliases: []\n---\n\n# Legacy\n\nOld body.\n"
    result = validate_page_structure(content, "concept", mode="lint")
    warning_codes = {issue["code"] for issue in result["warnings"]}
    assert result["valid"] is True
    assert "missing_profile_section" in warning_codes


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


def test_terminal_navigation_sections_allow_at_most_ten_wikilinks():
    related = "\n".join(f"- [[concepts/related-{i}|Related {i}]]" for i in range(11))
    content = (
        "---\n"
        "type: concept\n"
        "updated: 2026-09-22\n"
        "tags: [test]\n"
        "aliases: [Link Limit]\n"
        "---\n\n"
        "# Link Limit\n\n"
        "## Summary\n\nSummary.\n\n"
        "## Core Content\n\nDetails.\n\n"
        f"## Related\n\n{related}\n"
    )

    strict = validate_page_structure(content, "concept", mode="strict", expected_title="Link Limit")
    lint = validate_page_structure(content, "concept", mode="lint", expected_title="Link Limit")

    assert any(issue["code"] == "too_many_section_links" for issue in strict["errors"])
    assert any(issue["code"] == "too_many_section_links" for issue in lint["warnings"])
