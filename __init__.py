"""obsidianwiki - a Hermes memory provider backed by an Obsidian wiki vault.

Implements the LLM-wiki pattern (Karpathy-style) as a first-class
MemoryProvider: the agent's long-term knowledge lives in a plain Obsidian
vault the user can read and edit at any time, and the provider enforces the
wiki discipline automatically:

- index-first recall: prefetch() matches the turn against index.md + pages
- every page write updates index.md and appends to log.md (no drift)
- typed pages (entity/person/decision/environment/concept/source/answer/preference) in fixed folders, frontmatter
  enforced on write
- sources/ is read-only; lint reports orphans, broken links, stale claims

Config (config.yaml):
  plugins:
    obsidian-wiki:
      vault_path: "/path/to/agent-vault"   # required
      prefetch_limit: 3                    # max wiki hits injected per turn
      prefetch_min_query_chars: 10         # skip trivial queries
      inject_index_on_start: true          # system prompt lists top pages

No network, no API keys, no embedding model - pure stdlib file operations.

This plugin lives in $HERMES_HOME/plugins/obsidianwiki/ (user-installed),
so hermes-agent updates never clobber it.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider, RecallStatus
from tools.registry import tool_error

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:  # submodule import when loaded as a package
    from .obsidian_memory_core import MemoryStore, RevisionConflict
    from .obsidian_memory_core.wiki import WikiVault, WikiVaultError
except ImportError:  # pragma: no cover - flat import fallback
    from obsidian_memory_core import MemoryStore, RevisionConflict  # type: ignore
    from obsidian_memory_core.wiki import WikiVault, WikiVaultError  # type: ignore

logger = logging.getLogger(__name__)

_GLYPH = "📖"

_DEFAULT_VAULT = str(Path.home() / "Documents" / "agent-vault")


def _load_plugin_config() -> dict:
    try:
        from hermes_cli.config import load_config_readonly, cfg_get

        config = load_config_readonly()
        return cfg_get(
            config, "plugins", "obsidian-wiki", default={}
        ) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

WIKI_TOOL_SCHEMA = {
    "name": "obsidian_wiki",
    "description": (
        "Read and write the agent's long-term Obsidian wiki. The wiki is the "
        "source of truth for durable knowledge about entities (projects, "
        "tools, systems) and concepts (lessons, workflows). Actions: read "
        "(full page), search (keyword scan), list (catalog from index.md), "
        "write (create/update a page - index and log update automatically), "
        "lint (orphans, broken links, contradictions), log (recent "
        "operations). Pages live in entities/, people/, decisions/, "
        "environment/, concepts/, preferences/, answers/; sources/ is "
        "read-only (ingest notes go to concepts/). Standing user rules "
        "belong in preferences/."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "search", "list", "write", "lint", "log"],
                "description": "Wiki operation to perform.",
            },
            "page": {
                "type": "string",
                "description": (
                    "Page path relative to the vault root, e.g. "
                    "'entities/my-project' or 'concepts/my-lesson.md'. "
                    "Required for read/write."
                ),
            },
            "query": {
                "type": "string",
                "description": "Search query. Required for search.",
            },
            "content": {
                "type": "string",
                "description": (
                    "Full markdown content for write (frontmatter optional - "
                    "type/updated are derived from the folder if omitted)."
                ),
            },
            "note": {
                "type": "string",
                "description": "One-line note recorded in log.md for writes.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results for search/list (default 5).",
            },
            "expected_revision": {
                "type": "string",
                "description": "SHA-256 revision from read for safe concurrent updates.",
            },
        },
        "required": ["action"],
    },
}


class ObsidianWikiMemoryProvider(MemoryProvider):
    """MemoryProvider over an Obsidian wiki vault (LLM-wiki pattern)."""

    def __init__(self, config: dict | None = None):
        self._config = config or _load_plugin_config()
        self._store: Optional[MemoryStore] = None
        self._vault: Optional[WikiVault] = None
        self._session_id = ""
        self._last_recall_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "obsidianwiki"

    def is_available(self) -> bool:
        try:
            from pathlib import Path

            vault = self._get_vault()
            # Available when the vault exists or can be created (parent dir
            # writable/existing) - ensure_skeleton() is idempotent.
            return vault.exists() or vault.root.parent.is_dir()
        except Exception:
            return False

    def unavailable_reason(self) -> str:
        from pathlib import Path

        vault = str(self._config.get("vault_path", _DEFAULT_VAULT))
        parent = str(Path(vault).expanduser().parent)
        return f"vault not found and parent missing: {vault} (parent: {parent})"

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._get_vault().ensure_skeleton()

    def shutdown(self) -> None:
        self._store = None
        self._vault = None

    def backup_paths(self) -> List[str]:
        return [str(self._config.get("vault_path", _DEFAULT_VAULT))]

    def _get_vault(self) -> WikiVault:
        if self._vault is None:
            self._store = MemoryStore(str(self._config.get("vault_path", _DEFAULT_VAULT)))
            self._vault = self._store.vault
        return self._vault

    # ------------------------------------------------------------------
    # Config surface (desktop generic panel)
    # ------------------------------------------------------------------

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "vault_path",
                "description": "Path to the Obsidian wiki vault",
                "default": _DEFAULT_VAULT,
            },
            {
                "key": "prefetch_limit",
                "description": "Max wiki hits injected per turn",
                "default": "3",
            },
            {
                "key": "prefetch_min_query_chars",
                "description": "Skip prefetch below this query length",
                "default": "10",
            },
            {
                "key": "inject_index_on_start",
                "description": "List catalog in system prompt at session start",
                "default": "true",
                "choices": ["true", "false"],
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        from pathlib import Path

        config_path = Path(hermes_home) / "config.yaml"
        try:
            import yaml

            from hermes_cli.config import read_user_config_raw

            existing = read_user_config_raw(config_path)
            existing.setdefault("plugins", {})
            existing["plugins"]["obsidian-wiki"] = values
            with open(config_path, "w", encoding="utf-8") as fh:
                yaml.dump(existing, fh, default_flow_style=False)
            self._config = dict(values)
            self._vault = None
        except Exception as e:
            logger.warning("obsidianwiki save_config failed: %s", e)

    # ------------------------------------------------------------------
    # Prompt / recall surface
    # ------------------------------------------------------------------

    def system_prompt_block(self) -> str:
        try:
            vault = self._get_vault()
            if not vault.exists():
                return ""
            stats = vault.stats()
            total = sum(stats.values())
            lines = [
                "# Obsidian Wiki Memory",
                "",
                f"Active. Vault: `{vault.root}` ({total} pages: "
                + ", ".join(f"{v} {k}" for k, v in stats.items() if v)
                + ").",
                "",
                "The wiki is the source of truth for durable knowledge.",
                "Follow these wiki rules:",
                "- Read this catalog first; use action=search before answering "
                "questions that may touch stored entities, people, decisions, "
                "preferences, concepts, or lessons.",
                "- Use action=read for full page content and action=list for "
                "catalog/stats; do not guess page contents.",
                "- Durable knowledge belongs in the wiki. Use action=write "
                "to create or update the existing page; check for duplicates "
                "and update instead of creating a second page.",
                "- Write full detail to the wiki first, then keep only a short "
                "pointer in the built-in memory layer when needed.",
                "- Use the correct folder/type: entities, people, decisions, "
                "environment, concepts, preferences, or answers. Ingested "
                "raw notes belong under sources/ and sources/ is read-only.",
                "- Every page needs valid frontmatter: type, updated (YYYY-MM-DD), "
                "tags, and aliases. Pages are English by default unless the "
                "user explicitly requests another language.",
                "- Keep pages cross-linked with full-path wikilinks such as "
                "[[people/example|Example]]. Avoid orphan pages.",
                "- index.md and log.md are maintained automatically; never "
                "hand-edit them through other tools mid-session.",
                "- For reusable synthesized comparisons, rankings, or 'which is "
                "best' answers, save/update an answers/ page with comparison, "
                "recommendation, alternatives, and sources.",
                "- Never store passwords, API keys, tokens, or other secrets in "
                "the wiki. Run action=lint when checking vault health.",
                "Use the obsidian_wiki tool:",
                "- action=search, read, list, write, lint, or log as appropriate",
            ]
            if str(self._config.get("inject_index_on_start", "true")).lower() in (
                "1", "true", "yes",
            ):
                catalog = self._index_catalog(vault)
                if catalog:
                    lines.append("")
                    lines.append("Catalog:")
                    lines.extend(catalog)
            return "\n".join(lines)
        except Exception as e:
            logger.debug("obsidianwiki system_prompt_block failed: %s", e)
            return ""

    @staticmethod
    def _index_catalog(vault: WikiVault, limit_per_type: int = 6) -> List[str]:
        catalog = []
        for page in vault.load_pages():
            if len([c for c in catalog]) >= limit_per_type * 4:
                break
            summary = ""
            for line in page["body"].splitlines():
                s = line.strip()
                if s and not s.startswith(("#", ">", "---", "|")):
                    summary = s[:120]
                    break
            catalog.append(
                f"- [[{page['rel']}|{page['title']}]] ({page['ptype']}) "
                f"{summary}"
            )
        return catalog

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        min_chars = int(self._config.get("prefetch_min_query_chars", 10))
        if not isinstance(query, str) or len(query.strip()) < min_chars:
            return ""
        try:
            vault = self._get_vault()
            if not vault.exists():
                return ""
            limit = int(self._config.get("prefetch_limit", 3))
            context = vault.prefetch_context(query, limit=limit)
            hits = context.count("[[") if context else 0
            self._last_recall_count = hits
            if context:
                vault.append_log(
                    "QUERY", f"recall hit for: {query.strip()[:80]}", quiet=True
                )
            return context
        except Exception as e:
            logger.debug("obsidianwiki prefetch failed: %s", e)
            return ""

    def recall_status(self) -> Optional[RecallStatus]:
        if self._last_recall_count > 0:
            return RecallStatus(
                provider_label="Obsidian Wiki",
                count=self._last_recall_count,
                glyph=_GLYPH,
            )
        return None

    def sync_turn(
        self, user_content: str, assistant_content: str, *, session_id: str = ""
    ) -> None:
        # Wiki grows through explicit tool writes only; auto-extraction would
        # violate the curated-page rule (UPDATE instead of duplicates).
        pass

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [WIKI_TOOL_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name != "obsidian_wiki":
            return tool_error(f"Unknown tool: {tool_name}")
        try:
            vault = self._get_vault()
            if not vault.exists():
                return tool_error(self.unavailable_reason())
            action = args.get("action", "")
            if action == "read":
                return self._handle_read(vault, args)
            if action == "search":
                return self._handle_search(vault, args)
            if action == "list":
                return self._handle_list(vault, args)
            if action == "write":
                return self._handle_write(vault, args)
            if action == "lint":
                # --fix support: lint with fix=true auto-links orphans
                if args.get("fix") or args.get("fix_orphans"):
                    dry = bool(args.get("dry_run"))
                    res = vault.fix_orphans(dry_run=dry)
                    return json.dumps({"lint": vault.lint(), "fix_orphans": res}, indent=2)
                return json.dumps(vault.lint(), indent=2)
            if action == "log":
                tail = vault.log_tail(int(args.get("limit", 30)))
                return json.dumps({"log_tail": tail})
            return tool_error(f"Unknown action: {action}")
        except RevisionConflict as e:
            return json.dumps({"error": "revision_conflict", "message": str(e)})
        except WikiVaultError as e:
            return tool_error(str(e))
        except Exception as e:
            logger.exception("obsidian_wiki failed")
            return tool_error(f"wiki error: {e}")

    # -- handlers -------------------------------------------------------

    def _handle_read(self, vault: WikiVault, args: dict) -> str:
        page = args.get("page", "")
        if not page:
            return tool_error("read requires 'page'")
        try:
            result = self._store.read(page) if self._store else None
        except WikiVaultError:
            result = None
        if result is None:
            path = vault.safe_resolve(page)
            if path.suffix != ".md":
                path = path.with_suffix(".md")
            relative = path.relative_to(vault.root)
            allowed = {"entities", "people", "decisions", "environment", "concepts", "answers", "preferences"}
            if len(relative.parts) < 2 or relative.parts[0] not in allowed:
                return tool_error("only wiki pages in an allowed content folder are accessible")
            import re as _re

            norm = lambda s: _re.sub(r"[^a-z0-9]", "", s.lower())
            wanted = norm(path.stem)
            close = [
                p["rel"]
                for p in vault.load_pages()
                if wanted and (
                    wanted in norm(p["stem"]) or norm(p["stem"]) in wanted
                )
            ]
            err = {"error": f"page not found: {page}"}
            if close:
                err["similar"] = close[:8]
            return json.dumps(err)
        return json.dumps(result, ensure_ascii=False)

    def _handle_search(self, vault: WikiVault, args: dict) -> str:
        query = args.get("query", "")
        if not query:
            return tool_error("search requires 'query'")
        results = vault.search(query, limit=int(args.get("limit", 5)))
        vault.append_log("QUERY", f"search: {query.strip()[:80]}", quiet=True)
        return json.dumps({"results": results, "count": len(results)},
                          ensure_ascii=False)

    def _handle_list(self, vault: WikiVault, args: dict) -> str:
        stats = vault.stats()
        pages = [
            {
                "path": p["rel"],
                "title": p["title"],
                "type": p["ptype"],
                "updated": p["updated"],
            }
            for p in vault.load_pages()
        ]
        return json.dumps(
            {"stats": stats, "pages": pages[: int(args.get("limit", 50))]},
            ensure_ascii=False,
        )

    def _handle_write(self, vault: WikiVault, args: dict) -> str:
        page = args.get("page", "")
        content = args.get("content", "")
        if not page:
            return tool_error("write requires 'page' (e.g. concepts/my-note)")
        allow_dup = bool(args.get("allow_duplicate") or args.get("allowDuplicate"))
        if self._store is None:
            self._store = MemoryStore(str(self._config.get("vault_path", _DEFAULT_VAULT)))
        result = self._store.write(page, content, note=args.get("note", ""),
                                   expected_revision=args.get("expected_revision"),
                                   allow_duplicate=allow_dup)
        return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register the obsidianwiki memory provider with the plugin system."""
    ctx.register_memory_provider(ObsidianWikiMemoryProvider())
