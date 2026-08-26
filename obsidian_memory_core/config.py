"""Shared configuration defaults for every Obsidian Wiki adapter."""
from __future__ import annotations

import os
from pathlib import Path

def default_vault_path() -> str:
    """Return the OS-neutral fallback used by standalone processes."""
    return str(Path.home() / "Documents" / "agent-vault")


DEFAULT_VAULT_PATH = default_vault_path()


def vault_path(config: dict | None = None) -> str:
    """Resolve the vault for a process.

    Precedence is explicit Hermes plugin config, environment, then the
    portable fallback. A standalone MCP server cannot read Hermes plugin
    config, so it must receive OBSIDIAN_VAULT_PATH in its environment.
    """
    config = config or {}
    return str(config.get("vault_path") or os.environ.get("OBSIDIAN_VAULT_PATH") or default_vault_path())


__all__ = ["DEFAULT_VAULT_PATH", "vault_path"]
