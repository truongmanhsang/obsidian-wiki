# AGENTS.md — Obsidian Wiki Memory Usage

Instructions for Codex, Claude Code, AGY, and other coding agents working with this repository or its connected knowledge base.

## Purpose

Use the Obsidian Wiki as the shared, durable memory layer for project facts, decisions, people, environments, lessons, workflows, and reusable answers.

The wiki is not a scratchpad and must not become a dump of transient logs.

## MCP connection

Preferred transport: the shared local Streamable HTTP server.

```text
http://127.0.0.1:8765/mcp
```

The server must point to the same vault for every client:

```text
OBSIDIAN_VAULT_PATH=/absolute/path/to/agent-vault
```

Typical client configuration:

```json
{
  "mcpServers": {
    "obsidian_wiki": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

For a stdio-only client:

```json
{
  "mcpServers": {
    "obsidian_wiki": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["/absolute/path/to/obsidianwiki/mcp_server.py"],
      "env": {
        "OBSIDIAN_VAULT_PATH": "/absolute/path/to/agent-vault"
      }
    }
  }
}
```

AGY example:

```bash
agy mcp add obsidian_wiki http://127.0.0.1:8765/mcp
agy mcp list
```

Restart the client after changing MCP configuration. Keep the server bound to localhost unless authentication and network exposure are explicitly configured.

## Available wiki tools

Use the native MCP tools:

- `memory_search(query, limit)` — find relevant curated pages.
- `memory_read(page)` — read one page completely and obtain its revision.
- `memory_reflect(query, limit)` — synthesize relevant pages with the configured LLM.
- `memory_list(limit)` — inspect catalog and page statistics.
- `memory_write(page, content, note, expected_revision)` — create or update a curated page.
- `memory_lint()` — check broken links, orphan pages, duplicates, and stale claims.
- `memory_log(limit)` — inspect recent wiki operations.

## Required read workflow

Before answering a question that may depend on stored knowledge:

1. Call `memory_search` with focused keywords.
2. Call `memory_read` for the strongest relevant page or pages.
3. For comparisons, recommendations, summaries, or "why/how" questions, call `memory_reflect`.
4. Treat `sources/` pages as evidence, not curated conclusions.
5. Never guess page contents when a read can retrieve them.

Use `memory_reflect` when reasoning across multiple pages. Use `memory_read` to verify exact names, dates, paths, metrics, and configuration values before reporting them.

## Required write workflow

Only write durable information:

- confirmed facts about projects, tools, systems, people, or environments;
- settled decisions and the reason for each decision;
- reusable lessons and workflows;
- standing preferences and behavior rules;
- reusable comparison or recommendation answers.

Do not write:

- temporary task progress;
- ordinary small talk;
- unverified assumptions;
- raw tool output;
- credentials, API keys, tokens, passwords, cookies, or private secrets;
- unstable paths or values unless they are a documented environment fact.

Before creating a page:

1. Call `memory_search` to check for duplicates.
2. Prefer updating an existing canonical page over creating another page.
3. Put the page in the correct folder:
   - `entities/` — projects, tools, systems, products
   - `people/` — specific people worth remembering
   - `decisions/` — settled choices with reasons
   - `environment/` — machine, server, deployment, and stable path facts
   - `concepts/` — lessons, explanations, and workflows
   - `preferences/` — standing user or agent rules
   - `answers/` — reusable synthesized comparisons and recommendations
4. Use English by default unless the user requests another language.
5. Include valid frontmatter with `type`, `updated`, `tags`, and `aliases`.
6. Include a `## Related` section with full-path wikilinks where relevant.
7. Preserve source provenance and distinguish facts from advice.

## Safe update protocol

For an existing page:

1. Call `memory_read(page)`.
2. Keep the returned `revision` unchanged while preparing the update.
3. Merge the new information into the complete page content without deleting valid sections.
4. Call `memory_write(..., expected_revision=<revision>)`.
5. If a revision conflict occurs, read the page again, merge again, and retry once.
6. Verify the final page with `memory_read(page)`.

Never bypass optimistic concurrency and never overwrite a page blindly.

## Sources are read-only

`source/` and `sources/` contain raw or imported evidence. Do not write to them through `memory_write`. Store durable conclusions in a curated folder and link back to the source when appropriate.

## After writes

For meaningful changes:

1. Read the target page back.
2. Run `memory_lint()`.
3. Check that new pages are linked and that no duplicate page was created.
4. Report the exact page paths changed and any remaining lint problems.

A successful tool response alone is not proof that the intended content was saved; verify by reading the target.

## Agent behavior rules

- Use the wiki tools directly; do not use filesystem tools to edit vault pages.
- Do not edit `index.md` or `log.md` manually; the wiki write path maintains them.
- Do not store secrets in the wiki or in this file.
- Do not claim a backtest, deployment, upload, or external write succeeded without real verification.
- For trading knowledge, preserve the exact symbol, broker, currency, contract, model, timeframe, date range, and drawdown context.
- For code changes, keep repository source and tests generic; do not hardcode personal names, companies, or private domain examples unless they are required by the product behavior.
- Keep the wiki canonical: update existing pages instead of creating near-duplicates.

## Mandatory Proactive Memory Logging Rule

**UNIVERSAL REQUIREMENT FOR ALL CODING & RESEARCH AGENTS (Codex, Claude Code, AGY, Gemini, etc.) ACROSS ALL PROJECTS:**

Agents must **PROACTIVELY and AUTOMATICALLY** trigger memory consolidation into Obsidian Wiki **without waiting for user prompts or reminders**:

1. **Empirical Experiments, Sweeps & Benchmarks (Any Project/Domain)**:
   - Whenever an optimization, model training run, parameter sweep, benchmark, or backtest produces meaningful conclusions (breakthrough winners, high-efficiency configs, or notable failures/rejections), the agent **MUST immediately call `memory_write`** to record the exact environment, parameters, performance metrics, and actionable lessons learned into the corresponding `concepts/` or `entities/` page before concluding its turn.
2. **Settled Architectural & Technical Decisions**:
   - Whenever a key technical choice, architectural pattern, framework, data structure, or workflow approach is settled or rejected (with rationale), record it immediately in `decisions/` or `concepts/`.
3. **Standing User Preferences & Safety Constraints**:
   - Whenever the user expresses a standing preference, operating constraint, safety ceiling (e.g., "drawdown must be < 10k"), or negative rule (e.g., "do not modify core code"), the agent **MUST immediately update `preferences/`** via `memory_write`.
4. **Non-Obvious Bug Discoveries, Root Causes & Fixes**:
   - Whenever a non-trivial bug, system quirk, API edge-case, or environment pitfall is diagnosed and solved, persist the root cause and remedy into `concepts/` or `environment/`.
5. **Never Defer to End of Session**:
   - Do not postpone durable logging to the end of a conversation or wait for the user to ask "did you save this to memory?". Consolidate and persist knowledge dynamically as discoveries occur.

## Minimal examples

### Search and read

```text
memory_search({"query": "deployment retry policy", "limit": 5})
memory_read({"page": "concepts/retry-policy"})
```

### Reflect

```text
memory_reflect({"query": "Which deployment approach is recommended and why?", "limit": 8})
```

### Create

```text
memory_write({
  "page": "concepts/example-workflow",
  "content": "---\ntype: concept\nupdated: YYYY-MM-DD\ntags: [workflow]\naliases: [Example Workflow]\n---\n\n# Example Workflow\n\nDurable workflow details.\n\n## Related\n\n- [[entities/example-project|Example Project]]\n",
  "note": "Record durable workflow",
  "expected_revision": null
})
```

### Update

```text
page = memory_read({"page": "concepts/example-workflow"})
memory_write({
  "page": "concepts/example-workflow",
  "content": "<complete merged page content>",
  "note": "Merge newly verified workflow details",
  "expected_revision": page.revision
})
```

## Verification checklist

- [ ] MCP server is reachable.
- [ ] Search was performed before relying on wiki knowledge.
- [ ] Exact claims were verified with `memory_read`.
- [ ] Reflection was used for synthesis when appropriate.
- [ ] Existing pages were checked before creating new ones.
- [ ] Updates used `expected_revision`.
- [ ] No secrets or transient state were written.
- [ ] The target was read back after writing.
- [ ] `memory_lint()` was run after meaningful writes.
