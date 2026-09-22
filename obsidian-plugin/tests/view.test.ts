import { describe, expect, it, vi } from "vitest";

vi.mock("obsidian", () => ({
  ItemView: class {
    leaf: any;
    app: any;
    containerEl = document.createElement("div");
    constructor(leaf: any) {
      this.leaf = leaf;
      this.app = leaf.app;
    }
  },
  MarkdownRenderer: { renderMarkdown: vi.fn(async (markdown: string, container: HTMLElement) => {
    container.textContent = markdown;
  }) },
}));

import { MarkdownRenderer } from "obsidian";
import { MemoryWorkspaceView } from "../src/view";

const makeView = (callTool: ReturnType<typeof vi.fn>) => {
  const app = {
    vault: { getAbstractFileByPath: vi.fn(() => ({ path: "concepts/example.md" })) },
    workspace: { openLinkText: vi.fn() },
  };
  const leaf = { app };
  return { app, view: new MemoryWorkspaceView(leaf as any, { callTool } as any) };
};

describe("MemoryWorkspaceView", () => {
  it("renders tabs and displays search results", async () => {
    const callTool = vi.fn().mockResolvedValue({
      results: [{
        path: "concepts/example.md",
        title: "Example",
        snippet: "A useful fact",
        score: 0.92,
        match: "exact",
      }],
    });
    const { view } = makeView(callTool);
    await view.onOpen();

    expect(view.containerEl.textContent).toContain("Search");
    expect(view.containerEl.textContent).toContain("Reflect");
    expect(view.containerEl.textContent).not.toContain("Browse");
    expect(view.containerEl.textContent).not.toContain("browse");
    expect(view.containerEl.querySelector(".memory-search-type")).toBeNull();
    expect(view.containerEl.querySelector(".memory-search-path")).toBeNull();

    const input = view.containerEl.querySelector<HTMLInputElement>(".memory-search-input")!;
    input.value = "useful";
    const sources = view.containerEl.querySelector<HTMLInputElement>(".memory-search-sources")!;
    expect(sources).toBeTruthy();
    expect(sources.checked).toBe(false);
    view.containerEl.querySelector<HTMLFormElement>(".memory-toolbar")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(view.containerEl.querySelector(".memory-workspace-header")).toBeTruthy();
    expect(view.containerEl.querySelector(".memory-search-toolbar")).toBeTruthy();
    expect(view.containerEl.querySelector(".memory-results-count")).toBeTruthy();
    expect(view.containerEl.querySelector(".memory-card-meta")).toBeTruthy();
    expect(view.containerEl.textContent).toContain("Exact match");
    expect(callTool).toHaveBeenCalledWith("memory_search", expect.objectContaining({
      query: "useful",
      include_sources: false,
      precise: true,
    }));
    expect(view.containerEl.textContent).toContain("concepts/example.md");
  });

  it("renders a reflection and its source labels", async () => {
    const callTool = vi.fn().mockResolvedValue({
      reflection: "The sources agree on a calm workflow.",
      sources: [{ path: "decisions/workflow.md" }],
    });
    const { view } = makeView(callTool);
    await view.onOpen();
    view.containerEl.querySelector<HTMLButtonElement>('[data-tab="reflect"]')!.click();

    const input = view.containerEl.querySelector<HTMLInputElement>(".memory-reflect-input")!;
    input.value = "What workflow is recommended?";
    view.containerEl.querySelector<HTMLFormElement>(".memory-reflect-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(callTool).toHaveBeenCalledWith("memory_reflect", { query: "What workflow is recommended?", limit: 8 });
    expect(MarkdownRenderer.renderMarkdown).toHaveBeenCalledWith(
      "The sources agree on a calm workflow.",
      expect.any(HTMLElement),
      "",
      view,
    );
    expect(view.containerEl.querySelector(".memory-reflect-output")?.getAttribute("aria-live")).toBe("polite");
    expect(view.containerEl.querySelector(".memory-reflection-card")).toBeTruthy();
    expect(view.containerEl.querySelector(".memory-sources-list")).toBeTruthy();
    expect(view.containerEl.textContent).toContain("The sources agree on a calm workflow.");
    expect(view.containerEl.textContent).toContain("decisions/workflow.md");
  });

  it("shows an inline retryable error", async () => {
    const callTool = vi.fn().mockRejectedValue(new Error("MCP offline"));
    const { view } = makeView(callTool);
    await view.onOpen();
    view.containerEl.querySelector<HTMLFormElement>(".memory-toolbar")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(view.containerEl.textContent).toContain("MCP offline");
    expect(view.containerEl.querySelector("[role='alert']")).toBeTruthy();
    expect(view.containerEl.querySelector(".memory-retry")).toBeTruthy();
  });
});
