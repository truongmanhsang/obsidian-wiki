"""Shared configuration defaults for every Obsidian Wiki adapter."""
from __future__ import annotations

import os
import json
from pathlib import Path


def _obsidian_config_candidates() -> list[Path]:
    """Return platform-specific Obsidian config locations."""
    home = Path.home()
    candidates = [
        home / "Library/Application Support/obsidian/obsidian.json",  # macOS
        home / ".config/obsidian/obsidian.json",                     # Linux
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "obsidian/obsidian.json")    # Windows
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        candidates.append(Path(localappdata) / "obsidian/obsidian.json")
    return candidates


def _configured_vault() -> str | None:
    """Find the first vault registered in Obsidian's own config."""
    for config_path in _obsidian_config_candidates():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            vaults = data.get("vaults", {})
            for entry in vaults.values():
                path = entry.get("path") if isinstance(entry, dict) else None
                if path:
                    return str(Path(path).expanduser())
        except (OSError, ValueError, TypeError):
            continue
    return None


def default_vault_path() -> str:
    """Resolve a portable default; explicit configuration always wins."""
    return _configured_vault() or str(Path.home() / "Documents" / "agent-vault")


DEFAULT_VAULT_PATH = default_vault_path()


def vault_path(config: dict | None = None) -> str:
    """Resolve one vault path consistently across Hermes, MCP, and scripts."""
    config = config or {}
    return str(config.get("vault_path") or os.environ.get("OBSIDIAN_VAULT_PATH") or DEFAULT_VAULT_PATH)


__all__ = ["DEFAULT_VAULT_PATH", "vault_path"]
