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
