import { ItemView, MarkdownRenderer } from "obsidian";
import type { App, WorkspaceLeaf } from "obsidian";
import type { McpClient } from "./mcpClient";
import type { ReflectResult, SearchFilters, SearchHit, SearchResult } from "./types";

export const MEMORY_VIEW_TYPE = "memory-workspace";

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

const withAttributes = (node: HTMLElement, attributes: Record<string, string>): HTMLElement => {
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
};

const state = (className: string, text: string): HTMLElement =>
  withAttributes(element("div", className, text), { role: "status" });

const formatMatch = (match: unknown): string => {
  const value = String(match ?? "").trim();
  if (!value) return "";
  const labels: Record<string, string> = {
    exact: "Exact match",
    phrase: "Phrase match",
    anchor: "Anchor match",
    embedding: "Semantic match",
  };
  return labels[value] ?? value.replace(/[-_]+/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
};

export class MemoryWorkspaceView extends ItemView {
  private activeTab: "search" | "browse" | "reflect" = "search";
  private root!: HTMLElement;
  private searchQuery = "";
  private searchFilters: SearchFilters = { include_sources: false };

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
    header.appendChild(element("p", "memory-subtitle", "Search and reflect over your durable knowledge."));
    this.root.appendChild(header);

    const tabs = element("nav", "memory-tabs");
    for (const [tab, label] of [["search", "Search"], ["reflect", "Reflect"]] as const) {
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
    if (this.activeTab === "reflect") this.renderReflect(panel);
  }

  private renderSearch(panel: HTMLElement): void {
    panel.appendChild(element("h2", "memory-panel-title", "Find a memory"));
    panel.appendChild(element("p", "memory-panel-copy", "Search curated pages across the shared knowledge vault."));
    const form = element("form", "memory-toolbar memory-search-toolbar");
    const input = element("input", "memory-search-input") as HTMLInputElement;
    input.type = "search";
    input.placeholder = "Search memories…";
    input.value = this.searchQuery;
    input.setAttribute("aria-label", "Search memories");
    const sourceLabel = element("label", "memory-search-source-toggle");
    const sources = element("input", "memory-search-sources") as HTMLInputElement;
    sources.type = "checkbox";
    sources.checked = this.searchFilters.include_sources === true;
    sourceLabel.append(sources, document.createTextNode(" Include source pages"));
    const button = element("button", "memory-search-submit", "Search");
    button.type = "submit";
    form.append(input, sourceLabel, button);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.searchQuery = input.value.trim();
      this.searchFilters = {
        include_sources: sources.checked,
      };
      void this.runSearch(panel);
    });
    panel.appendChild(form);
    const count = element("div", "memory-results-count");
    count.setAttribute("aria-live", "polite");
    panel.appendChild(count);
    const results = element("div", "memory-results");
    withAttributes(results, {
      role: "region",
      "aria-label": "Search results",
      "aria-live": "polite",
    });
    panel.appendChild(results);
  }

  private async runSearch(panel: HTMLElement): Promise<void> {
    const results = panel.querySelector<HTMLElement>(".memory-results");
    if (!results) return;
    results.innerHTML = "";
    results.appendChild(state("memory-loading", "Searching…"));
    try {
      const response = await this.client.callTool<SearchResult>("memory_search", {
        query: this.searchQuery,
        limit: 20,
        precise: true,
        ...Object.fromEntries(Object.entries(this.searchFilters).filter(([, value]) => value !== undefined)),
      });
      results.innerHTML = "";
      const count = panel.querySelector<HTMLElement>(".memory-results-count");
      if (count) count.textContent = `${response.results?.length ?? 0} memor${response.results?.length === 1 ? "y" : "ies"}`;
      if (!response.results?.length) {
        results.appendChild(state("memory-empty", "No matching memories found."));
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
    if (hit.match || typeof hit.score === "number") {
      const meta = element("div", "memory-card-meta");
      const match = formatMatch(hit.match);
      if (match) meta.appendChild(element("span", "memory-match-badge", match));
      if (typeof hit.score === "number") {
        meta.appendChild(element("span", "memory-score", `${Math.round(hit.score * 100)}% match`));
      }
      card.appendChild(meta);
    }
    const snippet = hit.excerpt ?? hit.snippet;
    if (snippet) card.appendChild(element("p", "memory-card-excerpt", snippet));
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
    const output = withAttributes(element("div", "memory-reflect-output"), {
      role: "region",
      "aria-label": "Reflection result",
      "aria-live": "polite",
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.runReflect(input.value.trim(), output);
    });
    panel.append(form, output);
  }

  private async runReflect(query: string, output: HTMLElement): Promise<void> {
    output.innerHTML = "";
    if (!query) {
      output.appendChild(state("memory-empty", "Enter a question to reflect."));
      return;
    }
    output.appendChild(state("memory-loading", "Reflecting…"));
    try {
      const response = await this.client.callTool<ReflectResult>("memory_reflect", { query, limit: 8 });
      output.innerHTML = "";
      if (response.error) throw new Error(response.message || response.error);
      const reflection = element("div", "memory-reflection-card");
      output.appendChild(reflection);
      await MarkdownRenderer.renderMarkdown(response.reflection || "No reflection returned.", reflection, "", this);
      if (response.sources?.length) {
        const sources = element("div", "memory-sources-list");
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
    const box = withAttributes(element("div", "memory-error"), { role: "alert" });
    box.appendChild(element("div", "memory-error-message", error instanceof Error ? error.message : "Memory request failed"));
    const button = element("button", "memory-retry", "Retry");
    button.addEventListener("click", retry);
    box.appendChild(button);
    container.appendChild(box);
  }

}
