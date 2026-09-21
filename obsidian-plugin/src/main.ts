import { Plugin } from "obsidian";
import type { WorkspaceLeaf } from "obsidian";
import { McpClient } from "./mcpClient";
import { MemoryWorkspaceView, MEMORY_VIEW_TYPE } from "./view";
import { DEFAULT_SETTINGS, MemorySettingTab } from "./settings";
import type { PluginSettings } from "./types";

export default class MemoryWorkspacePlugin extends Plugin {
  settings!: PluginSettings;
  client!: McpClient;

  async onload(): Promise<void> {
    this.settings = { ...DEFAULT_SETTINGS, ...(await this.loadData() ?? {}) };
    this.client = new McpClient(this.settings.endpoint);
    this.registerView(MEMORY_VIEW_TYPE, (leaf: WorkspaceLeaf) => new MemoryWorkspaceView(leaf, this.client));
    this.addCommand({
      id: "open-memory-workspace",
      name: "Open memory workspace",
      callback: () => void this.activateView(),
    });
    this.addRibbonIcon("brain", "Open memory workspace", () => void this.activateView());
    this.addSettingTab(new MemorySettingTab(this.app, this));
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
    this.client = new McpClient(this.settings.endpoint);
  }

  async activateView(): Promise<void> {
    const existing = this.app.workspace.getLeavesOfType(MEMORY_VIEW_TYPE)[0];
    const leaf = existing ?? this.app.workspace.getRightLeaf(false);
    if (!leaf) return;
    await leaf.setViewState({ type: MEMORY_VIEW_TYPE, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  onunload(): void {
    this.app.workspace.detachLeavesOfType(MEMORY_VIEW_TYPE);
  }
}
