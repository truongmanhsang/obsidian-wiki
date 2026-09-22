from obsidian_memory_core.wiki.links import WIKILINK_RE
from obsidian_memory_core.wiki.sections import limit_section_wikilinks


def test_limit_section_wikilinks_keeps_first_ten_and_preserves_prose():
    links = "\n".join(f"- [[concepts/item-{i}|Item {i}]]" for i in range(12))
    markdown = f"# Page\n\n## Related\n\nContext stays.\n{links}\n"

    trimmed = limit_section_wikilinks(markdown, "Related")
    section = trimmed.split("## Related", 1)[1]

    assert len(WIKILINK_RE.findall(section)) == 10
    assert "Context stays." in section
    assert "item-9" in section
    assert "item-10" not in section
    assert "item-11" not in section


def test_limit_section_wikilinks_is_noop_when_already_within_limit():
    markdown = (
        "# Page\n\n## Related\n\n"
        "- [[concepts/a|A]]\n"
        "- [[concepts/a|A again]]\n"
        "- [[concepts/b|B]]\n"
    )

    assert limit_section_wikilinks(markdown, "Related") == markdown
