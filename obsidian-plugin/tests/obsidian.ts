import { vi } from "vitest";

export class ItemView {
  leaf: any;
  containerEl = document.createElement("div");
  constructor(leaf: any) {
    this.leaf = leaf;
  }
}

export class Notice {
  constructor(public readonly message: string) {}
}

export class Plugin {
  app: any;
  registerView = vi.fn();
  addCommand = vi.fn();
  addRibbonIcon = vi.fn();
  addSettingTab = vi.fn();
  registerEvent = vi.fn();
  loadData = async () => null;
  saveData = async () => undefined;
  constructor(app: any) {
    this.app = app;
  }
}

export class PluginSettingTab {
  containerEl = document.createElement("div") as any;
  constructor(public app: any, public plugin: any) {}
}

export class Setting {
  constructor(_container: HTMLElement) {}
  setName() { return this; }
  setDesc() { return this; }
  addText(callback: (text: any) => void) { callback({ setPlaceholder: () => this, setValue: () => this, onChange: () => this }); return this; }
  addButton(callback: (button: any) => void) { callback({ setButtonText: () => this, onClick: () => this }); return this; }
}
