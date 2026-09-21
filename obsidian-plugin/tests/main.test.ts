import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../src/settings";
import MemoryWorkspacePlugin from "../src/main";

describe("MemoryWorkspacePlugin", () => {
  it("provides the local MCP endpoint as the default setting", () => {
    expect(DEFAULT_SETTINGS).toEqual({ endpoint: "http://127.0.0.1:8765/mcp" });
  });

  it("loads settings and registers the workspace view and command", async () => {
    const plugin = new MemoryWorkspacePlugin({} as any, {} as any);
    vi.spyOn(plugin, "loadData").mockResolvedValue({ endpoint: "http://localhost:9999/mcp" });
    await plugin.onload();

    expect(plugin.settings.endpoint).toBe("http://localhost:9999/mcp");
    expect(plugin.registerView).toHaveBeenCalledWith("memory-workspace", expect.any(Function));
    expect(plugin.addCommand).toHaveBeenCalledWith(expect.objectContaining({ id: "open-memory-workspace" }));
  });
});
