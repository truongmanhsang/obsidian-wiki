"""Thin shim for backward compat - re-exports from wiki package.

Keeps wiki.py importable via direct file load (spec_from_file_location) and
preserves `import wiki` / `from wiki import WikiVault` paths after refactor
where the real implementation lives in wiki/vault.py and helpers.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure parent is on sys.path for absolute imports when loaded as standalone file
_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

try:
    # Preferred: absolute import via wiki package (works when plugin dir on sys.path)
    from wiki.vault import WikiVault, WikiVaultError
    from wiki.normalize import _normalize
    from wiki.frontmatter import FRONTMATTER_RE, parse_frontmatter, _parse_aliases_list
    from wiki.links import WIKILINK_RE, TOKEN_RE, _alias_map, _out_links, _inbound_links
    from wiki.index import INDEX_HEADER, first_summary_line
    from wiki.log import LOG_HEADER
    from wiki.vault import TYPE_DIRS, DIR_TYPES, SECTION_TITLES, VALID_TYPES, STOPWORDS, MAX_READ_CHARS, MAX_WRITE_CHARS, ENTITY_TEMPLATE, CONCEPT_TEMPLATE
    # Also expose functions for backward compat if imported as `import wiki`
    from wiki.vault import WikiVault as _WV
    # Ensure WikiVault.parse_frontmatter is available (it is on class)
    parse_frontmatter = _WV.parse_frontmatter  # type: ignore
except ImportError:
    try:
        # Fallback: relative package import when loaded as obsidianwiki.wiki (should not happen due to shadowing)
        from .wiki.vault import WikiVault, WikiVaultError  # type: ignore
        from .wiki.normalize import _normalize  # type: ignore
        from .wiki.frontmatter import FRONTMATTER_RE, parse_frontmatter, _parse_aliases_list  # type: ignore
        from .wiki.links import WIKILINK_RE, TOKEN_RE, _alias_map, _out_links, _inbound_links  # type: ignore
        from .wiki.index import INDEX_HEADER, first_summary_line  # type: ignore
        from .wiki.log import LOG_HEADER  # type: ignore
        from .wiki.vault import TYPE_DIRS, DIR_TYPES, SECTION_TITLES, VALID_TYPES, STOPWORDS, MAX_READ_CHARS, MAX_WRITE_CHARS, ENTITY_TEMPLATE, CONCEPT_TEMPLATE  # type: ignore
    except ImportError:
        pass

__all__ = [
    "WikiVault", "WikiVaultError",
    "_normalize", "_parse_aliases_list",
    "WIKILINK_RE", "FRONTMATTER_RE", "TOKEN_RE",
    "TYPE_DIRS", "DIR_TYPES", "SECTION_TITLES", "VALID_TYPES",
    "first_summary_line", "_alias_map", "_out_links",
]
