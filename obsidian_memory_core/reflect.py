"""Provider adapters for standalone memory reflection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_GROUNDING_INSTRUCTIONS = (
    " For questions about a relationship or attribute, identify the subject and "
    "relationship requested, then use only a source statement that explicitly "
    "connects that subject to the answer. Do not substitute the page owner's "
    "identity or another mentioned person's name for the requested relationship. "
    "If the sources do not explicitly establish the connection, say so."
)


class ReflectProvider(Protocol):
    def reflect(self, query: str, pages: list[dict[str, Any]]) -> str:
        """Synthesize a grounded answer from retrieved wiki pages."""


def _extract_text(payload: Any) -> str:
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                return _extract_text(content)
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        for key in ("output", "content", "message"):
            value = payload.get(key)
            text = _extract_text(value)
            if text:
                return text
    elif isinstance(payload, list):
        parts = []
        for item in payload:
            text = _extract_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    elif isinstance(payload, str):
        return payload.strip()
    return ""


class OpenAICompatibleProvider:
    """Standalone Chat Completions provider; no Hermes runtime is required."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.api_key = (api_key or os.environ.get("OBSIDIAN_MEMORY_API_KEY", "")).strip()
        self.model = (model or os.environ.get("OBSIDIAN_MEMORY_REFLECT_MODEL", "")).strip()
        self.base_url = (
            base_url
            or os.environ.get("OBSIDIAN_MEMORY_API_BASE_URL", "")
            or DEFAULT_OPENAI_BASE_URL
        ).rstrip("/")
        self.timeout = timeout

    def reflect(self, query: str, pages: list[dict[str, Any]]) -> str:
        if not self.api_key:
            raise RuntimeError("OBSIDIAN_MEMORY_API_KEY is required for API reflection")
        if not self.model:
            raise RuntimeError("OBSIDIAN_MEMORY_REFLECT_MODEL is required for API reflection")
        context = "\n\n".join(
            f"SOURCE: {page['path']}\n{page['content']}" for page in pages
        )
        instructions = (
            "You are the reflection layer for an Obsidian knowledge wiki. "
            "Answer only from the supplied sources; synthesize across sources, "
            "distinguish facts from uncertainty, and say when they do not establish "
            "an answer. Be concise and do not invent facts or citations."
            + _GROUNDING_INSTRUCTIONS
        )
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": f"Question:\n{query}\n\nSources:\n{context}"},
                ],
                "temperature": 0.2,
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"API reflection request failed with HTTP {exc.code}") from exc
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise RuntimeError("API reflection request failed") from exc
        text = _extract_text(payload)
        if not text:
            raise RuntimeError("API reflection returned no text")
        return text


def _extract_sse_text(response: Any) -> str:
    """Collect text deltas from a Codex Responses SSE stream."""
    parts: list[str] = []
    completed: Any = None
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
        elif event.get("type") == "response.completed":
            completed = event.get("response")
    return "".join(parts).strip() or _extract_text(completed)


class CodexProvider:
    """Use the existing Codex CLI OAuth session without Hermes auth storage."""

    def __init__(
        self,
        *,
        auth_path: str | Path | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.auth_path = Path(
            auth_path
            or os.environ.get("CODEX_AUTH_PATH", "")
            or DEFAULT_CODEX_AUTH_PATH
        ).expanduser()
        self.model = (model or os.environ.get("OBSIDIAN_MEMORY_REFLECT_MODEL", "")).strip()
        self.base_url = (
            base_url
            or os.environ.get("OBSIDIAN_MEMORY_REFLECT_BASE_URL", "")
            or DEFAULT_CODEX_BASE_URL
        ).rstrip("/")
        self.timeout = timeout

    def _credentials(self) -> tuple[str, str]:
        if not self.auth_path.is_file():
            raise RuntimeError(
                f"Codex CLI auth file not found: {self.auth_path}; run `codex login`"
            )
        try:
            payload = json.loads(self.auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Unable to read Codex CLI auth file: {self.auth_path}") from exc
        tokens = payload.get("tokens") if isinstance(payload, dict) else None
        access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
        account_id = tokens.get("account_id") if isinstance(tokens, dict) else None
        if not isinstance(access_token, str) or not access_token.strip():
            raise RuntimeError("Codex CLI auth file has no usable access token; run `codex login`")
        return access_token.strip(), str(account_id or "").strip()

    def reflect(self, query: str, pages: list[dict[str, Any]]) -> str:
        if not self.model:
            raise RuntimeError(
                "OBSIDIAN_MEMORY_REFLECT_MODEL is required when using the Codex provider"
            )
        access_token, account_id = self._credentials()
        context = "\n\n".join(
            f"SOURCE: {page['path']}\n{page['content']}" for page in pages
        )
        instructions = (
            "You are the reflection layer for an Obsidian knowledge wiki. "
            "Answer the user's question only from the supplied sources. "
            "Synthesize across sources, distinguish facts from uncertainty, and "
            "say when the sources do not establish an answer. Be concise. "
            "Do not invent citations or facts."
            + _GROUNDING_INSTRUCTIONS
        )
        request = Request(
            f"{self.base_url}/responses",
            data=json.dumps({
                "model": self.model,
                "instructions": instructions,
                "input": [{
                    "role": "user",
                    "content": f"Question:\n{query}\n\nSources:\n{context}",
                }],
                "store": False,
                "stream": True,
            }).encode("utf-8"),
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "User-Agent": "obsidian-memory/0.1.0",
                "originator": "obsidian-memory",
                **({"ChatGPT-Account-ID": account_id} if account_id else {}),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                text = _extract_sse_text(response)
        except HTTPError as exc:
            raise RuntimeError(f"Codex reflection request failed with HTTP {exc.code}") from exc
        except (OSError, URLError) as exc:
            raise RuntimeError("Codex reflection request failed") from exc
        if not text:
            raise RuntimeError("Codex reflection returned no text")
        return text


__all__ = ["CodexProvider", "OpenAICompatibleProvider", "ReflectProvider"]
