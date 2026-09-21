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
