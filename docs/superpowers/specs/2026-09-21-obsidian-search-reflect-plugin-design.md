# Obsidian Search and Reflect Plugin Design

**Status:** Proposed

## Goal

Create a native Obsidian plugin that provides a workspace dashboard for
searching, browsing, reading, and reflecting over the shared Obsidian memory
service through its existing Streamable HTTP MCP endpoint.

## Decisions

- Use the existing MCP endpoint at `http://127.0.0.1:8765/mcp` by default.
- Implement an MCP client in the plugin rather than adding a second REST API.
- Keep the first release read-only: no note creation, page writes, deletes, or
  automatic persistence of reflection results.
- Show reflection results only in the dashboard, including the source page
  paths returned by `memory_reflect`.
- Store the endpoint URL in plugin settings so users can change it without
  rebuilding the plugin.
- Keep plugin source isolated under `obsidian-plugin/` so the Python MCP server
  remains independently installable.

## User experience

The plugin registers an `Open memory workspace` command and a ribbon/action
entry. It opens a dedicated workspace leaf containing three views:

1. **Search** — query input, optional type/tags/path filters, result cards, and
   a result action that opens the selected page in Obsidian.
2. **Browse** — catalog of memory pages grouped by folder or page type, with a
   page detail area powered by `memory_read`.
3. **Reflect** — question input, result area, and source links. Reflection is
   explicitly read-only and does not create a note.

The dashboard shows loading, empty, offline, and server-error states inline.
The user can retry a failed request without reopening the workspace.

## Architecture

The plugin is a TypeScript Obsidian plugin built with a small Vite/esbuild
toolchain. Its modules have focused responsibilities:

- `src/main.ts` owns the Obsidian plugin lifecycle, settings, commands, and
  workspace view registration.
- `src/mcpClient.ts` implements the minimal Streamable HTTP MCP lifecycle:
  initialize the session, send `tools/call` requests, preserve the session
  identifier, parse JSON/text tool results, and surface protocol errors.
- `src/types.ts` defines the settings, MCP envelopes, and memory result types
  used by the client and UI.
- `src/view.ts` renders the dashboard and coordinates user actions with the
  client. It must not contain transport details.
- `styles.css` contains scoped dashboard styles that use Obsidian CSS
  variables, so the view follows light/dark themes and avoids hard-coded
  application colors.

The client calls these MCP tools:

- `memory_search` for Search, with query and optional metadata filters.
- `memory_list` for Browse.
- `memory_read` for page detail.
- `memory_reflect` for Reflect.

Page links should use Obsidian's vault API where possible. If a returned path
does not exist in the current vault, the UI should show it as a non-openable
source label instead of failing the whole result.

## MCP transport behavior

The client sends JSON-RPC requests by HTTP `POST` to the configured endpoint
with `Accept: application/json, text/event-stream` and
`Content-Type: application/json`. On initialization it sends the MCP protocol
version and client capabilities, then stores the returned `Mcp-Session-Id`.
Subsequent requests include that session header. The client supports both a
plain JSON response and a single-event SSE response because Streamable HTTP
servers may choose either representation.

The client must not send credentials by default. The default endpoint is
loopback-only, matching the repository's security guidance. Requests have a
bounded timeout, and protocol/application errors are converted into messages
safe to display in the dashboard.

## Testing and verification

- Unit-test MCP envelope creation, session-header handling, JSON parsing, SSE
  parsing, tool-result extraction, timeout, and protocol-error behavior.
- Unit-test view rendering for loading, empty, results, source links, and
  offline/error states using a fake MCP client.
- Run the plugin TypeScript build and test suite.
- If Obsidian is available, reload the plugin with the Obsidian CLI, inspect
  developer errors, and verify the workspace view and command manually.
- Verify that the Python MCP server tests remain green; the plugin must not
  change server behavior.

## Scope boundaries

This release does not add write operations, note saving, authentication,
remote-network defaults, semantic search changes, or a second server API.
