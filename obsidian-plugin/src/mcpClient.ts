import { requestUrl } from "obsidian";

interface JsonRpcResponse {
  jsonrpc?: string;
  id?: number;
  result?: Record<string, unknown>;
  error?: { code?: number; message?: string; data?: unknown };
}

interface HttpResponse {
  ok: boolean;
  status: number;
  headers: Headers;
  text(): Promise<string>;
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<HttpResponse>;

const nativeFetcher: Fetcher = async (input, init) => {
  const headers: Record<string, string> = {};
  new Headers(init?.headers).forEach((value, key) => {
    headers[key] = value;
  });
  const response = await requestUrl({
    url: String(input),
    method: init?.method,
    headers,
    body: typeof init?.body === "string" ? init.body : undefined,
    throw: false,
  });
  return {
    ok: response.status >= 200 && response.status < 300,
    status: response.status,
    headers: new Headers(response.headers),
    text: async () => response.text,
  };
};

export class McpClient {
  private sessionId: string | undefined;
  private requestId = 0;
  private initialized = false;

  constructor(
    private readonly endpoint: string,
    private readonly fetcher: Fetcher = nativeFetcher,
    private readonly timeoutMs = 15_000,
  ) {}

  async initialize(): Promise<void> {
    if (this.initialized) return;

    await this.request({
      jsonrpc: "2.0",
      id: this.nextRequestId(),
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "obsidian-memory-workspace", version: "0.1.0" },
      },
    });
    this.initialized = true;
  }

  async callTool<T>(name: string, arguments_: Record<string, unknown>): Promise<T> {
    await this.initialize();
    const response = await this.request({
      jsonrpc: "2.0",
      id: this.nextRequestId(),
      method: "tools/call",
      params: { name, arguments: arguments_ },
    });

    const result = response.result;
    if (!result) return undefined as T;
    if ("structuredContent" in result) return result.structuredContent as T;

    const content = result.content;
    if (!Array.isArray(content)) return result as T;
    const textBlock = content.find(
      (block): block is { type: "text"; text: string } =>
        typeof block === "object" && block !== null && block.type === "text" && typeof block.text === "string",
    );
    if (!textBlock) return result as T;

    try {
      return JSON.parse(textBlock.text) as T;
    } catch {
      return textBlock.text as T;
    }
  }

  private nextRequestId(): number {
    this.requestId += 1;
    return this.requestId;
  }

  private async request(payload: Record<string, unknown>): Promise<JsonRpcResponse> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    const headers = new Headers({
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    });
    if (this.sessionId) headers.set("Mcp-Session-Id", this.sessionId);

    try {
      const response = await this.fetcher(this.endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const sessionId = response.headers.get("Mcp-Session-Id");
      if (sessionId) this.sessionId = sessionId;
      if (!response.ok) throw new Error(`MCP request failed (${response.status})`);

      const body = await response.text();
      const parsed = this.parseResponse(body, response.headers.get("content-type") ?? "");
      if (parsed.error) throw new Error(parsed.error.message || "MCP request failed");
      return parsed;
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("MCP request failed")) throw error;
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new Error("MCP request timed out");
      }
      throw error instanceof Error ? error : new Error("MCP request failed");
    } finally {
      clearTimeout(timeout);
    }
  }

  private parseResponse(body: string, contentType: string): JsonRpcResponse {
    if (contentType.includes("text/event-stream")) {
      const event = body
        .split(/\r?\n\r?\n/)
        .flatMap((chunk) => chunk.split(/\r?\n/))
        .find((line) => line.startsWith("data:"));
      if (!event) throw new Error("MCP returned an empty event stream");
      return JSON.parse(event.slice(5).trim()) as JsonRpcResponse;
    }
    return JSON.parse(body) as JsonRpcResponse;
  }
}
