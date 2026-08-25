"""Declarative config surface for the obsidianwiki memory plugin.

Rendered by the generic desktop panel; storage is the flat_json backend
(plugins.obsidian-wiki block in config.yaml).
"""

from plugins.memory.config_schema import (
    KIND_BOOL,
    KIND_NUMBER,
    KIND_TEXT,
    ProviderConfigSchema,
    ProviderField,
)

CONFIG_SCHEMA = ProviderConfigSchema(
    name="obsidianwiki",
    label="Obsidian Wiki",
    docs_url="https://help.obsidian.md/",
    fields=(
        ProviderField(
            key="vault_path",
            label="Vault path",
            kind=KIND_TEXT,
            default="~/Documents/agent-vault",
            description=(
                "Path to the Obsidian vault used as the wiki "
                "(entities/, people/, decisions/, environment/, concepts/, preferences/, answers/, sources/)."
            ),
            inline=True,
        ),
        ProviderField(
            key="prefetch_limit",
            label="Prefetch limit",
            kind=KIND_NUMBER,
            default="3",
            description="Max wiki hits injected into context per turn.",
            inline=True,
        ),
        ProviderField(
            key="prefetch_min_query_chars",
            label="Min query length",
            kind=KIND_NUMBER,
            default="10",
            description="Skip recall for shorter queries.",
        ),
        ProviderField(
            key="inject_index_on_start",
            label="Inject catalog",
            kind=KIND_BOOL,
            default="true",
            description=(
                "List wiki pages in the system prompt at session start."
            ),
            inline=True,
        ),
    ),
)
