import { PluginSettingTab, Setting } from "obsidian";
import type { App, Plugin } from "obsidian";
import { DEFAULT_ENDPOINT, type PluginSettings } from "./types";

export const DEFAULT_SETTINGS: PluginSettings = {
  endpoint: DEFAULT_ENDPOINT,
};

export class MemorySettingTab extends PluginSettingTab {
  constructor(app: App, private readonly plugin: Plugin & { settings: PluginSettings; saveSettings(): Promise<void> }) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Memory Workspace" });
    new Setting(containerEl)
      .setName("MCP endpoint")
      .setDesc("Local Streamable HTTP endpoint used for search and reflection.")
      .addText((text) => {
        text.setPlaceholder(DEFAULT_ENDPOINT).setValue(this.plugin.settings.endpoint);
        text.onChange(async (value) => {
          this.plugin.settings.endpoint = value.trim() || DEFAULT_ENDPOINT;
          await this.plugin.saveSettings();
        });
      });
    new Setting(containerEl).addButton((button) =>
      button.setButtonText("Restore default").onClick(async () => {
        this.plugin.settings.endpoint = DEFAULT_ENDPOINT;
        await this.plugin.saveSettings();
        this.display();
      }),
    );
  }
}
