# obsidianwiki

Hermes memory provider backed by an **Obsidian wiki vault** - the LLM-wiki
pattern (Karpathy-style) as a first-class `MemoryProvider`.

The agent's long-term knowledge lives in a plain Obsidian vault the user can
read and edit in the Obsidian app at any time (iCloud-synced). The plugin
enforces wiki discipline automatically, so the agent cannot let the vault rot.

## What it enforces

| Rule | How |
|------|-----|
| Index-first | prefetch() scores pages against each turn; system prompt carries a live catalog |
| No drift | every `write` regenerates index.md stats/bullets and appends to log.md |
| Typed pages | folder decides type: entities/, concepts/, sources/, answers/ |
| Read-only sources | write_page rejects anything under sources/ |
| No orphans | lint reports pages with zero inbound wikilinks |
| Fresh claims | lint flags pages whose `updated` is older than their last log mention |

## Tool surface (obsidian_wiki)

- read - full page content (+ similar-page suggestions on miss)
- search - token-scored scan with snippets
- list - stats + catalog
- write - create/update page; frontmatter `type`/`updated` derived from
  folder and stamped automatically; index + log updated in the same call
- lint - orphans, broken links, missing frontmatter, stale claims
- log - recent operation tail

## Config (config.yaml)

```yaml
plugins:
  obsidian-wiki:
    vault_path: "/path/to/agent-vault"
    prefetch_limit: 3
    prefetch_min_query_chars: 10
    inject_index_on_start: true
```

Activate with:

```bash
hermes config set memory.provider obsidianwiki
hermes memory status   # verify
```

Restart the session/gateway after switching providers.

## Session ingest pipeline

The plugin captures completed user/assistant sessions into
`sources/sessions/YYYY/MM/DD/<session-id>.md`, then asynchronously extracts
only durable knowledge into curated wiki pages.

### Cron exclusion

Sessions whose ID starts with `cron_`, or whose hook platform is `cron`, are
operational runs and are never captured or extracted.

### Extraction status

Each captured session source has a bookkeeping property in frontmatter:

```yaml
extract_status: pending
```

The lifecycle is:

- `pending` - captured, waiting for extraction
- `success` - extraction completed and at least one wiki page was created or updated
- `skip` - extraction completed but no durable knowledge was found, or all proposals were duplicates
- `fail` - the LLM, JSON parsing, or a wiki write failed

Successful/skipped sources also retain the legacy `extracted: YYYY-MM-DD`
marker for backlog compatibility. The transcript itself remains unchanged;
only extraction bookkeeping is updated.

### Extraction tracking

Every run produces a unique `run_id` and a machine-readable audit record at:

```text
~/.hermes/logs/wiki-extract-audit.jsonl
```

The audit record includes:

- source session IDs
- raw proposal count
- duplicate/rejection count
- final extraction status
- each applied page
- proposal `action` (`create` or `update`)
- write result (`created`, `updated`, or `error`)
- title, summary, and reason

The vault `log.db` also receives an aggregated `REFLECT` record such as:

```text
extract from 1 session(s): 2 page(s) written; status=success
```

The end-of-session hook captures first and launches extraction in the
background after the host reports a completed session. The hook reads lifecycle
fields from both top-level payloads and Hermes shell-hook `extra` payloads.
Failures are fail-open: they are logged and do not block the user response.

### Privacy and local configuration

Session sources contain verbatim user/assistant dialogue. When extraction is
enabled, the selected transcript and matching wiki pages are sent to Hermes'
auxiliary `run_oneshot` model. Operators should confirm the configured model's
privacy and retention policy before enabling this hook for sensitive data.
Set `WIKI_INGEST_DISABLE=1` to disable capture/extraction from the hook. The
capture, extraction, and backlog scripts accept `OBSIDIAN_VAULT_PATH` so they
can target the same vault as the plugin configuration; `HERMES_STATE_DB`,
`HERMES_SRC`, `HERMES_PYTHON`, `WIKI_AUDIT_LOG`, and `WIKI_BACKLOG_STATE` are
available for non-default local layouts. Runtime logs and state files are
created owner-only where possible.

### Manual commands

```bash
# Capture one session
python3 scripts/wiki_session_capture.py --session <session-id> --force

# Extract one captured session with the Hermes virtualenv
~/.hermes/hermes-agent/venv/bin/python scripts/wiki_session_extract.py \
  --sessions YYYY/MM/DD/<session-id>.md --apply

# Inspect the latest detailed extraction event
 tail -1 ~/.hermes/logs/wiki-extract-audit.jsonl | python3 -m json.tool
```

## Design notes

- Pure stdlib for the wiki provider; no network, no API keys, no embedding model.
- Prefetch returns nothing for trivial (<10 chars) queries and only surfaces
  strong matches (score >= 2), so noise stays out of context.
- Writes are explicit-only: no auto-extraction mid-turn, because curated
  UPDATE-instead-of-duplicate pages beat raw dumps. The built-in `memory`
  tool remains the short-pointer layer; the wiki holds full detail.
- Lives in `$HERMES_HOME/plugins/obsidianwiki/` (user-installed) so
  hermes-agent updates never clobber it.
- **Documentation rule:** every functional change to this plugin must be
  reflected in this README.

## Shared memory core and MCP server

The repository also exposes the same wiki operations to external coding
agents through `obsidian_memory_core` and `mcp_server.py`:

```text
obsidian_memory_core
        ▲
        │
 Hermes plugin       MCP server
                            │
                   local stdio first
                            │
                   HTTP later if needed
```

The MCP adapter supports `memory_search`, `memory_read`, `memory_list`,
`memory_lint`, `memory_log`, and `memory_write`. Writes use an exclusive lock,
safe vault paths, and an optional `expected_revision` SHA-256 check to reject
stale updates from concurrent agents. Never store credentials, API keys,
tokens, or passwords in the vault.

Run locally over stdio:

```bash
OBSIDIAN_VAULT_PATH=/path/to/agent-vault \
  /path/to/python mcp_server.py
```

Run HTTP during development with FastMCP:

```bash
fastmcp run mcp_server.py:mcp --transport http --host 127.0.0.1 --port 8000
```

The Hermes plugin currently retains its native compatibility surface while
sharing the vault implementation. The next cleanup can move the remaining
Hermes-specific façade methods onto `MemoryStore` without changing clients.

### Standalone use without Hermes

The MCP server is a standalone entry point. It does **not** require Hermes
Agent, the Hermes gateway, or the Hermes memory provider to be running. Any
MCP client that supports stdio or Streamable HTTP can use the same vault,
including Codex, Claude Code, Claude Desktop, Cursor, and AGY.

Only the native Hermes plugin depends on Hermes-specific modules. The shared
`obsidian_memory_core` package and `mcp_server.py` are independent of that
plugin integration.

### Install the standalone MCP server

Clone the repository and create a dedicated virtual environment:

```bash
git clone git@github.com:truongmanhsang/obsidian-wiki.git
cd obsidian-wiki
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

The package declares `fastmcp` as its dependency. Verify the installation:

```bash
.venv/bin/fastmcp inspect mcp_server.py:mcp
```

Expected result includes:

```text
Server:  obsidian-memory
Tools:  6
```

### Configure the vault path

Set `OBSIDIAN_VAULT_PATH` to the absolute path of the vault that contains
`entities/`, `people/`, `concepts/`, and the other wiki folders:

```bash
export OBSIDIAN_VAULT_PATH="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/agent-vault"
```

The server falls back to that macOS iCloud path when the variable is omitted,
but an explicit path is recommended for portable setups and for clients that
launch processes with a restricted environment.

### Run with stdio locally

For a direct smoke test, start the server with:

```bash
OBSIDIAN_VAULT_PATH="/absolute/path/to/agent-vault" \
  .venv/bin/python mcp_server.py
```

The process waits for MCP messages on stdin/stdout. Do not send ordinary text
to it and do not use the server's stdout for application logging.

The usual workflow is to configure the command in an MCP client rather than
launch it manually.

### Codex configuration

Add the following MCP server entry to the Codex MCP configuration supported by
your installation. Use absolute paths because GUI-launched clients may not
load the same shell `PATH` as Terminal:

```json
{
  "mcpServers": {
    "obsidian-memory": {
      "command": "/absolute/path/to/obsidian-wiki/.venv/bin/python",
      "args": [
        "/absolute/path/to/obsidian-wiki/mcp_server.py"
      ],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/absolute/path/to/agent-vault"
      }
    }
  }
}
```

If the package is installed into a dedicated environment with the console
script available, the command can instead be:

```json
{
  "mcpServers": {
    "obsidian-memory": {
      "command": "/absolute/path/to/obsidian-wiki/.venv/bin/obsidian-memory-mcp",
      "env": {
        "OBSIDIAN_VAULT_PATH": "/absolute/path/to/agent-vault"
      }
    }
  }
}
```

Restart the Codex MCP session after changing its configuration. Ask Codex to
list the available MCP tools; it should discover `memory_search`,
`memory_read`, `memory_list`, `memory_lint`, `memory_log`, and `memory_write`.

### Claude Code, Claude Desktop, Cursor, and AGY

Use the same MCP server command and environment. The exact configuration file
location differs by client, but the logical configuration is the same:

```json
{
  "mcpServers": {
    "obsidian-memory": {
      "command": "/absolute/path/to/obsidian-wiki/.venv/bin/python",
      "args": ["/absolute/path/to/obsidian-wiki/mcp_server.py"],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/absolute/path/to/agent-vault"
      }
    }
  }
}
```

Do not copy the macOS example paths literally if the repository or vault is
in another location. Keep the vault path outside the repository when
possible.

### MCP tool reference

| Tool | Input | Behavior |
|------|-------|----------|
| `memory_search` | `query`, optional `limit` | Search durable wiki pages |
| `memory_read` | `page` | Read a page and return its `revision` |
| `memory_list` | optional `limit` | Return catalog, types, and statistics |
| `memory_lint` | none | Check links, orphans, and wiki health |
| `memory_log` | optional `limit` | Return recent operation logs |
| `memory_write` | `page`, `content`, optional `note`, `expected_revision` | Create or safely update a page |

### Safe write workflow

For a new page, call `memory_write` directly:

```json
{
  "page": "concepts/java-conventions",
  "content": "# Java Conventions\n\nUse constructor injection.\n",
  "note": "Durable convention discovered during coding"
}
```

For an existing page, always use read-then-write:

```text
1. memory_read(page) -> save the returned revision
2. Edit the complete page content
3. memory_write(page, content, expected_revision=revision)
4. If revision_conflict is returned, read the page again and merge changes
```

Example update payload:

```json
{
  "page": "concepts/java-conventions",
  "content": "# Java Conventions\n\nUse constructor injection and immutable DTOs.\n",
  "expected_revision": "sha256-returned-by-memory_read",
  "note": "Added a second confirmed convention"
}
```

The server rejects an update to an existing page when `expected_revision` is
missing or stale. This prevents one coding agent from silently overwriting
another agent's changes. Every write also goes through the shared core's
exclusive lock.

Allowed write folders are `entities/`, `people/`, `decisions/`,
`environment/`, `concepts/`, `answers/`, and `preferences/`. The `sources/`
folder is intentionally read-only.

### Agent instructions recommendation

Add a short instruction to the coding agent's `AGENTS.md`, `CLAUDE.md`, or
project instructions:

```text
Before starting a coding task, call memory_recall or memory_search with the
project name and relevant technical terms. Read relevant pages before making
architectural decisions. After discovering durable project facts or reusable
conventions, use memory_write. Do not store secrets, credentials, temporary
progress, or raw debug logs.
```

This server currently exposes `memory_search`, not a separate
`memory_recall` tool; use `memory_search` for the recall step.

### HTTP mode for later multi-machine use

Run a local HTTP endpoint during development:

```bash
OBSIDIAN_VAULT_PATH="/absolute/path/to/agent-vault" \
  .venv/bin/fastmcp run mcp_server.py:mcp \
  --transport http --host 127.0.0.1 --port 8000
```

The MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

For a remote deployment, do not bind this server publicly without adding
authentication, HTTPS or a private network such as Tailscale, access control,
rate limiting, and backups. The current server is intended for local stdio
use first; HTTP is the next deployment layer, not an internet-facing default.

### Troubleshooting standalone mode

- `ModuleNotFoundError: fastmcp`: activate the dedicated `.venv` or run
  `.venv/bin/python -m pip install -e .` again.
- No tools discovered: use absolute paths and verify with
  `.venv/bin/fastmcp inspect mcp_server.py:mcp`.
- Vault not found: set `OBSIDIAN_VAULT_PATH` to the vault root, not its
  `entities/` subfolder.
- Update rejected with `revision_conflict`: call `memory_read` again and
  retry using the latest revision.
- Do not expose `sources/` for writes; it is immutable raw-source storage.

This section describes the standalone MCP path. Hermes users can continue to
use the native `obsidian_wiki` provider, which now shares the same core write
and revision safety.
