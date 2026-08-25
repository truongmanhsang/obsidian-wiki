"""wiki package - re-exports WikiVault and helpers for backward compat."""
from __future__ import annotations

from .vault import WikiVault, WikiVaultError, TYPE_DIRS, DIR_TYPES, SECTION_TITLES, VALID_TYPES, STOPWORDS, MAX_READ_CHARS, MAX_WRITE_CHARS, INDEX_HEADER, LOG_HEADER, ENTITY_TEMPLATE, CONCEPT_TEMPLATE
from .normalize import _normalize
from .frontmatter import FRONTMATTER_RE, parse_frontmatter, _parse_aliases_list, page_title
from .links import WIKILINK_RE, TOKEN_RE, _alias_map, _out_links, _inbound_links
from .index import first_summary_line, _existing_summaries, rebuild_index
from .log import append_log, log_tail
from .dedup import detect_duplicates
from .lint import lint, _hub_for_orphan, fix_orphans
from .search import search, prefetch_context

# For backward compat, also expose WikiVault.parse_frontmatter as staticmethod via vault class
__all__ = [
    "WikiVault", "WikiVaultError",
    "_normalize", "_parse_aliases_list",
    "WIKILINK_RE", "FRONTMATTER_RE", "TOKEN_RE",
    "TYPE_DIRS", "DIR_TYPES", "SECTION_TITLES", "VALID_TYPES",
    "first_summary_line", "_alias_map", "_out_links", "_inbound_links",
]
