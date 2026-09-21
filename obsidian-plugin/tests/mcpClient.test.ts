import { describe, expect, it, vi } from "vitest";
import { McpClient } from "../src/mcpClient";

const jsonResponse = (value: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json", ...headers },
  });

describe("McpClient", () => {
  it("initializes a session and sends its session id on tool calls", async () => {
    const requests: RequestInit[] = [];
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(init ?? {});
      if (requests.length === 1) {
        return jsonResponse(
          { jsonrpc: "2.0", id: 1, result: { protocolVersion: "2025-03-26" } },
          { "Mcp-Session-Id": "session-1" },
        );
      }
      return jsonResponse({
        jsonrpc: "2.0",
        id: 2,
        result: { content: [{ type: "text", text: JSON.stringify({ results: [] }) }] },
      });
    });

    const client = new McpClient("http://127.0.0.1:8765/mcp", fetcher);
    await client.initialize();
    const result = await client.callTool<{ results: unknown[] }>("memory_search", { query: "test" });

    expect(result).toEqual({ results: [] });
    expect(JSON.parse(String(requests[0].body))).toMatchObject({
      jsonrpc: "2.0",
      method: "initialize",
    });
    expect(new Headers(requests[1].headers).get("Mcp-Session-Id")).toBe("session-1");
    expect(JSON.parse(String(requests[1].body))).toMatchObject({
      method: "tools/call",
      params: { name: "memory_search", arguments: { query: "test" } },
    });
  });

  it("parses a single-event SSE response", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ jsonrpc: "2.0", id: 1, result: {} }))
      .mockResolvedValueOnce(
        new Response(
          `event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: 2, result: { content: [{ type: "text", text: "hello" }] } })}\n\n`,
          { headers: { "content-type": "text/event-stream" } },
        ),
      );

    const client = new McpClient("http://localhost/mcp", fetcher);
    await expect(client.callTool<string>("memory_reflect", { query: "hello" })).resolves.toBe("hello");
  });

  it("surfaces JSON-RPC and HTTP errors", async () => {
    const rpcError = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ jsonrpc: "2.0", id: 1, result: {} }))
      .mockResolvedValueOnce(jsonResponse({ jsonrpc: "2.0", id: 2, error: { message: "bad request" } }));
    const client = new McpClient("http://localhost/mcp", rpcError);
    await expect(client.callTool("memory_search", {})).rejects.toThrow("bad request");

    const httpError = vi.fn().mockResolvedValue(new Response("offline", { status: 503 }));
    const offlineClient = new McpClient("http://localhost/mcp", httpError);
    await expect(offlineClient.initialize()).rejects.toThrow("MCP request failed (503)");
  });
});
