import { DEFAULT_ENDPOINT } from "../src/types";
import { describe, expect, it } from "vitest";

describe("plugin defaults", () => {
  it("uses the local MCP endpoint by default", () => {
    expect(DEFAULT_ENDPOINT).toBe("http://127.0.0.1:8765/mcp");
  });
});
