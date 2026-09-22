"""Safe YAML frontmatter and description behavior tests."""

from obsidian_memory_core.wiki.frontmatter import parse_frontmatter
from obsidian_memory_core.wiki.vault import WikiVault


def test_parse_frontmatter_preserves_nested_yaml_and_normalizes_dates():
    meta, body = parse_frontmatter(
        """---
type: concept
updated: 2026-09-22
tags:
  - workflow
aliases: [YAML, Metadata]
description: Một mô tả ngắn
sources:
  - url: https://example.test/spec
    verified: true
    labels: [format, yaml]
generated:
  by: agent
  version: 2
---

# Safe metadata
"""
    )

    assert meta["type"] == "concept"
    assert meta["updated"] == "2026-09-22"
    assert meta["tags"] == ["workflow"]
    assert meta["aliases"] == ["YAML", "Metadata"]
    assert meta["description"] == "Một mô tả ngắn"
    assert meta["sources"] == [{
        "url": "https://example.test/spec",
        "verified": True,
        "labels": ["format", "yaml"],
    }]
    assert meta["generated"] == {"by": "agent", "version": 2}
    assert body == "# Safe metadata\n"


def test_parse_frontmatter_keeps_legacy_fields_when_yaml_is_malformed():
    meta, body = parse_frontmatter(
        """---
type: concept
updated: 2026-09-22
tags:
  - legacy
aliases:
  - Legacy page
description: [unterminated
---

# Legacy metadata
"""
    )

    assert meta["type"] == "concept"
    assert meta["updated"] == "2026-09-22"
    assert meta["tags"] == ["legacy"]
    assert meta["aliases"] == ["Legacy page"]
    assert meta["description"] == "[unterminated"
    assert body == "# Legacy metadata\n"


def test_write_page_round_trips_optional_nested_metadata_and_description(tmp_path):
    vault = WikiVault(str(tmp_path / "vault"))
    vault.ensure_skeleton()
    content = """---
type: concept
updated: 2020-01-01
tags:
  - workflow
aliases:
  - Safe metadata
description: A concise searchable overview
sources:
  - url: https://example.test/source
    verified: true
status: draft
---

# Safe metadata

## Summary

The page has a concise summary.

## Core Content

The body is intentionally different from the description.

## Related
"""

    vault.write_page("concepts/safe-metadata", content, quiet_log=True)

    page = next(page for page in vault.load_pages() if page["rel"] == "concepts/safe-metadata.md")
    assert page["meta"]["description"] == "A concise searchable overview"
    assert page["meta"]["sources"] == [{
        "url": "https://example.test/source",
        "verified": True,
    }]
    assert page["meta"]["status"] == "draft"

    manifest = vault._index_manifest()
    entry = next(item for item in manifest if item["path"] == "concepts/safe-metadata.md")
    assert entry["summary"] == "A concise searchable overview"
    vault.rebuild_index()
    assert "- [[concepts/safe-metadata.md|Safe metadata]] - A concise searchable overview" in vault.index_path.read_text()

    results = vault._keyword_search("searchable overview")
    assert results[0]["description"] == "A concise searchable overview"
    assert results[0]["snippet"] == "A concise searchable overview"

    hybrid_results = vault.search("searchable overview", precise=True)
    hybrid_hit = next(item for item in hybrid_results if item["path"] == "concepts/safe-metadata.md")
    assert hybrid_hit["description"] == "A concise searchable overview"
    assert hybrid_hit["snippet"] == "A concise searchable overview"
