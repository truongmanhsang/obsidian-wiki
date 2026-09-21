import { ItemView, Notice } from "obsidian";
import type { App, WorkspaceLeaf } from "obsidian";
import type { McpClient } from "./mcpClient";
import type { MemoryPage, ReflectResult, SearchFilters, SearchHit, SearchResult } from "./types";

export const MEMORY_VIEW_TYPE = "memory-workspace";

interface ListResult {
  pages?: Array<{ path: string; title?: string; type?: string; updated?: string }>;
}

const element = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export class MemoryWorkspaceView extends ItemView {
  private activeTab: "search" | "browse" | "reflect" = "search";
  private root!: HTMLElement;
  private searchQuery = "";
  private searchFilters: SearchFilters = {};

  constructor(leaf: WorkspaceLeaf, private readonly client: McpClient) {
    super(leaf);
  }

  getViewType(): string {
    return MEMORY_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "Memory Workspace";
  }

  async onOpen(): Promise<void> {
    this.containerEl.innerHTML = "";
    this.root = element("div", "memory-workspace");
    this.containerEl.appendChild(this.root);
    this.renderShell();
  }

  async onClose(): Promise<void> {
    this.containerEl.innerHTML = "";
  }

  private renderShell(): void {
    this.root.innerHTML = "";
    const header = element("header", "memory-workspace-header");
    header.appendChild(element("div", "memory-eyebrow", "OBSIDIAN MEMORY"));
    header.appendChild(element("h1", "memory-title", "Memory Workspace"));
    header.appendChild(element("p", "memory-subtitle", "Search, browse, and reflect over your durable knowledge."));
    this.root.appendChild(header);

    const tabs = element("nav", "memory-tabs");
    for (const [tab, label] of [["search", "Search"], ["browse", "Browse"], ["reflect", "Reflect"]] as const) {
      const button = element("button", `memory-tab ${this.activeTab === tab ? "is-active" : ""}`, label);
      button.dataset.tab = tab;
      button.addEventListener("click", () => {
        this.activeTab = tab;
        this.renderShell();
      });
      tabs.appendChild(button);
    }
    this.root.appendChild(tabs);

    const panel = element("section", "memory-panel");
    this.root.appendChild(panel);
    if (this.activeTab === "search") this.renderSearch(panel);
    if (this.activeTab === "browse") void this.renderBrowse(panel);
    if (this.activeTab === "reflect") this.renderReflect(panel);
  }

  private renderSearch(panel: HTMLElement): void {
    panel.appendChild(element("h2", "memory-panel-title", "Find a memory"));
    panel.appendChild(element("p", "memory-panel-copy", "Search curated pages across the shared knowledge vault."));
    const form = element("form", "memory-toolbar");
    const input = element("input", "memory-search-input") as HTMLInputElement;
    input.type = "search";
    input.placeholder = "Search memories…";
    input.value = this.searchQuery;
    input.setAttribute("aria-label", "Search memories");
    const type = element("input", "memory-search-type") as HTMLInputElement;
    type.placeholder = "Type (optional)";
    type.value = this.searchFilters.type ?? "";
    const path = element("input", "memory-search-path") as HTMLInputElement;
    path.placeholder = "Path prefix (optional)";
    path.value = this.searchFilters.path_prefix ?? "";
    const button = element("button", "memory-search-submit", "Search");
    button.type = "submit";
    form.append(input, type, path, button);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.searchQuery = input.value.trim();
      this.searchFilters = { type: type.value.trim() || undefined, path_prefix: path.value.trim() || undefined };
      void this.runSearch(panel);
    });
    panel.appendChild(form);
    panel.appendChild(element("div", "memory-results"));
  }

  private async runSearch(panel: HTMLElement): Promise<void> {
    const results = panel.querySelector<HTMLElement>(".memory-results");
    if (!results) return;
    results.innerHTML = "";
    results.appendChild(element("div", "memory-loading", "Searching…"));
    try {
      const response = await this.client.callTool<SearchResult>("memory_search", {
        query: this.searchQuery,
        limit: 20,
        ...Object.fromEntries(Object.entries(this.searchFilters).filter(([, value]) => value !== undefined)),
      });
      results.innerHTML = "";
      if (!response.results?.length) {
        results.appendChild(element("div", "memory-empty", "No matching memories found."));
        return;
      }
      response.results.forEach((hit) => results.appendChild(this.renderHit(hit)));
    } catch (error) {
      this.renderError(results, error, () => void this.runSearch(panel));
    }
  }

  private renderHit(hit: SearchHit): HTMLElement {
    const card = element("article", "memory-card");
    card.appendChild(element("div", "memory-card-path", hit.path));
    if (hit.title) card.appendChild(element("h3", "memory-card-title", hit.title));
    if (hit.excerpt) card.appendChild(element("p", "memory-card-excerpt", hit.excerpt));
    const open = element("button", "memory-card-open", "Open page");
    const file = this.app.vault.getAbstractFileByPath(hit.path);
    if (!file) {
      open.disabled = true;
      open.title = "This source is not present in the current vault";
    } else {
      open.addEventListener("click", () => this.app.workspace.openLinkText(hit.path, "", true));
    }
    card.appendChild(open);
    return card;
  }

  private async renderBrowse(panel: HTMLElement): Promise<void> {
    panel.appendChild(element("h2", "memory-panel-title", "Browse the vault"));
    panel.appendChild(element("p", "memory-panel-copy", "Explore the pages currently indexed by memory."));
    const list = element("div", "memory-results");
    list.appendChild(element("div", "memory-loading", "Loading catalog…"));
    panel.appendChild(list);
    try {
      const response = await this.client.callTool<ListResult>("memory_list", { limit: 100 });
      list.innerHTML = "";
      if (!response.pages?.length) {
        list.appendChild(element("div", "memory-empty", "No pages found."));
        return;
      }
      response.pages.forEach((page) => {
        const button = element("button", "memory-list-item");
        button.appendChild(element("strong", "memory-list-path", page.path));
        button.appendChild(element("span", "memory-list-meta", [page.type, page.updated].filter(Boolean).join(" · ")));
        button.addEventListener("click", () => void this.openPage(page.path));
        list.appendChild(button);
      });
    } catch (error) {
      this.renderError(list, error, () => void this.renderBrowse(panel));
    }
  }

  private renderReflect(panel: HTMLElement): void {
    panel.appendChild(element("h2", "memory-panel-title", "Reflect across memories"));
    panel.appendChild(element("p", "memory-panel-copy", "Ask a grounded question. Results stay in this workspace and are never saved automatically."));
    const form = element("form", "memory-toolbar memory-reflect-form");
    const input = element("textarea", "memory-reflect-input") as HTMLTextAreaElement;
    input.placeholder = "What would you like to understand?";
    input.rows = 3;
    const button = element("button", "memory-reflect-submit", "Reflect");
    button.type = "submit";
    form.append(input, button);
    const output = element("div", "memory-reflect-output");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.runReflect(input.value.trim(), output);
    });
    panel.append(form, output);
  }

  private async runReflect(query: string, output: HTMLElement): Promise<void> {
    output.innerHTML = "";
    if (!query) {
      output.appendChild(element("div", "memory-empty", "Enter a question to reflect."));
      return;
    }
    output.appendChild(element("div", "memory-loading", "Reflecting…"));
    try {
      const response = await this.client.callTool<ReflectResult>("memory_reflect", { query, limit: 8 });
      output.innerHTML = "";
      if (response.error) throw new Error(response.message || response.error);
      output.appendChild(element("div", "memory-reflection", response.reflection || "No reflection returned."));
      if (response.sources?.length) {
        const sources = element("div", "memory-sources");
        sources.appendChild(element("div", "memory-sources-title", "Sources"));
        response.sources.forEach((source) => sources.appendChild(element("span", "memory-source", source.path)));
        output.appendChild(sources);
      }
    } catch (error) {
      this.renderError(output, error, () => void this.runReflect(query, output));
    }
  }

  private renderError(container: HTMLElement, error: unknown, retry: () => void): void {
    container.innerHTML = "";
    const box = element("div", "memory-error");
    box.appendChild(element("div", "memory-error-message", error instanceof Error ? error.message : "Memory request failed"));
    const button = element("button", "memory-retry", "Retry");
    button.addEventListener("click", retry);
    box.appendChild(button);
    container.appendChild(box);
  }

  private async openPage(path: string): Promise<void> {
    try {
      const page = await this.client.callTool<MemoryPage>("memory_read", { page: path });
      const file = this.app.vault.getAbstractFileByPath(path);
      if (file) this.app.workspace.openLinkText(path, "", true);
      else new Notice(`${page.path || path} is not in the current vault`);
    } catch {
      new Notice(`Could not read ${path}`);
    }
  }
}
