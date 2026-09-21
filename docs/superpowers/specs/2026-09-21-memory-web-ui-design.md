# Memory Web UI Design

**Date:** 2026-09-21
**Status:** Approved for implementation planning

## Goal

Add a separate React/Vite web application that makes the Obsidian memory service
pleasant to search, browse, read, and reflect over using the existing Python
memory store and reflection provider.

## Product direction

The UI is a calm knowledge workspace: search-first, polished, spacious, and
usable in both light and dark themes. It should feel like a durable personal
knowledge tool rather than an admin console or a chat-only interface.

## Architecture

The frontend lives under `web/` as a Vite + React + TypeScript application. A
thin JSON API adapter in the Python service exposes the store operations the UI
needs. The adapter reuses `MemoryStore` and the existing reflection path; it
does not duplicate vault access, search, page validation, or reflection logic.

MCP tools remain unchanged. During local development, Vite proxies `/api` to
the Python HTTP server. The API exposes normalized relative wiki paths and
never exposes absolute vault filesystem paths.

## API surface

The web API provides:

- `GET /api/search?q=&limit=&type=&tag=` — search durable memory with optional
  type and tag filters.
- `GET /api/pages` — list the memory catalog and stats.
- `GET /api/pages/{path}` — read one curated wiki page by relative path.
- `POST /api/reflect` with `{ "query": string, "limit": number }` — synthesize
  relevant pages using the existing reflection provider.

The API validates query and limit inputs, constrains page paths through the
existing store, and returns stable JSON errors with 400, 404, or 500 status
codes.

## Experience

### Shell

Use a two-column desktop layout with a soft cream light canvas or charcoal dark
canvas. The left rail contains the Memory brand, Search, Browse, Reflect, and a
small vault-stat summary. On narrow screens the rail becomes a top bar.

### Search

Search is the default view and visual center of gravity. It has a large command-
style input, filter chips for page type and tags, and result cards containing
title, relative path, snippet, type badge, updated date, and a restrained
relevance cue. `/` focuses search.

### Browse

Browse loads the page catalog and displays stats, filters, and page cards grouped
or filterable by type. Selecting a card opens the page detail view.

### Reflect

Reflect provides a question composer and an answer panel. `Cmd/Ctrl + Enter`
submits the question. The response includes the reflection plus a “Sources
used” list whose paths open the corresponding page detail. Loading states feel
like a live synthesis without requiring streaming transport.

### Page detail

Page detail presents readable Markdown content, metadata, and related/source
links, with an obvious back-to-results action. It is read-only in this scope.

### Visual language

Use restrained serif display headings, clean sans-serif interface text, a muted
blue/teal accent, warm surfaces, rounded cards, subtle borders, and light focus
and hover motion. Include skeleton loading states, useful empty states, and
inline recoverable API error banners.

## Data flow

Search submits a query to `/api/search`, which delegates to
`MemoryStore.search`; the UI keeps active filters in local state and renders
normalized results. Browse calls `/api/pages`, derives type groupings client-
side, and loads full content only after a page is selected. Reflect posts the
question to `/api/reflect`, which delegates to the existing reflection path and
returns the answer and source paths. Errors preserve the user's query and offer
retry.

## Testing and verification

- Python API tests cover search, list, read, reflect, validation, page-path
  safety, and error responses.
- React tests cover initial loading, search results, filters, page navigation,
  reflection success/error, and the key empty/loading states.
- The frontend production build must pass.
- The existing Python test suite must remain green.
- The local development flow and API proxy configuration must be documented.

## Scope boundaries

This feature does not add page editing, deletion, authentication, graph
visualization, real-time streaming, or changes to MCP tool contracts. It uses
the configured vault and reflection provider already supported by the service.
