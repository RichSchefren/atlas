/*
 * Atlas Memory — Obsidian plugin
 *
 * Talks to the Atlas API at http://localhost:9879. Two responsibilities:
 *
 *   1. Sidebar pane that lists pending adjudications. Click an entry
 *      to open the underlying markdown file in the editor.
 *   2. Save-listener for files under ATLAS_ADJUDICATION_DIR. When you
 *      save with a checkbox checked (Accept / Reject / Adjust /
 *      Demote_core), POST adjudication.resolve to Atlas and let the
 *      server archive the file.
 *
 * Spec: PHASE-5-AND-BEYOND.md § 1.2-ALT (the Donnie path)
 */

import {
  App, ItemView, MarkdownView, Plugin, PluginSettingTab,
  Setting, TFile, WorkspaceLeaf, Notice,
} from "obsidian";

const ATLAS_VIEW_TYPE = "atlas-adjudication-view";

interface AtlasSettings {
  apiUrl: string;
  adjudicationDir: string;
  agentId: string;
}

const DEFAULT_SETTINGS: AtlasSettings = {
  apiUrl: "http://localhost:9879",
  adjudicationDir: "00 Atlas/adjudication",
  agentId: "rich",
};

interface AdjudicationEntry {
  filename: string;
  path: string;
  size_bytes: number;
}

export default class AtlasMemoryPlugin extends Plugin {
  settings: AtlasSettings;
  view: AtlasAdjudicationView | null = null;

  async onload() {
    await this.loadSettings();

    // Register the sidebar view
    this.registerView(
      ATLAS_VIEW_TYPE,
      (leaf) => (this.view = new AtlasAdjudicationView(leaf, this)),
    );

    // Ribbon icon → opens the sidebar view
    this.addRibbonIcon("brain", "Atlas Memory", () => {
      this.activateView();
    });

    // Save-listener for adjudication files
    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (file instanceof TFile && this.isAdjudicationFile(file)) {
          this.handleAdjudicationSave(file);
        }
      }),
    );

    // Settings tab
    this.addSettingTab(new AtlasSettingTab(this.app, this));

    new Notice("Atlas Memory plugin loaded");
  }

  onunload() {
    this.app.workspace.detachLeavesOfType(ATLAS_VIEW_TYPE);
  }

  async loadSettings() {
    this.settings = Object.assign(
      {}, DEFAULT_SETTINGS, await this.loadData(),
    );
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  async activateView() {
    this.app.workspace.detachLeavesOfType(ATLAS_VIEW_TYPE);
    await this.app.workspace.getRightLeaf(false).setViewState({
      type: ATLAS_VIEW_TYPE,
      active: true,
    });
    this.app.workspace.revealLeaf(
      this.app.workspace.getLeavesOfType(ATLAS_VIEW_TYPE)[0],
    );
  }

  isAdjudicationFile(file: TFile): boolean {
    return file.path.startsWith(this.settings.adjudicationDir)
      && file.extension === "md";
  }

  async handleAdjudicationSave(file: TFile) {
    const text = await this.app.vault.read(file);
    const proposalId = this.extractFrontmatterValue(text, "proposal_id");
    if (!proposalId) return;

    const decision = this.detectCheckedDecision(text);
    if (!decision) return;

    const adjustedConfidence = decision === "adjust"
      ? this.extractAdjustedConfidence(text)
      : null;

    try {
      const resp = await fetch(
        `${this.settings.apiUrl}/tools/adjudication.resolve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            params: {
              proposal_id: proposalId,
              decision,
              actor: this.settings.agentId,
              ...(adjustedConfidence !== null
                ? { adjusted_confidence: adjustedConfidence } : {}),
            },
          }),
        },
      );
      if (resp.ok) {
        const body = await resp.json();
        new Notice(
          `Atlas: ${decision} ${proposalId} ` +
          `(applied=${body.result?.applied ?? "?"})`,
        );
        if (this.view) await this.view.refresh();
      } else {
        new Notice(`Atlas error: ${resp.status} ${await resp.text()}`);
      }
    } catch (err) {
      new Notice(`Atlas unreachable at ${this.settings.apiUrl}: ${err}`);
    }
  }

  extractFrontmatterValue(text: string, key: string): string | null {
    const match = text.match(/^---\s*\n([\s\S]+?)\n---\s*\n/);
    if (!match) return null;
    for (const line of match[1].split("\n")) {
      const idx = line.indexOf(":");
      if (idx === -1) continue;
      if (line.slice(0, idx).trim() === key) {
        return line.slice(idx + 1).trim();
      }
    }
    return null;
  }

  detectCheckedDecision(text: string): string | null {
    // Match the "Pick one and save:" checkboxes from
    // _format_adjudication_markdown:
    //   - [ ] **Accept** ...
    //   - [x] **Reject** ...
    const checks = [
      [/^- \[x\] \*\*Accept\*\*/im, "accept"],
      [/^- \[x\] \*\*Reject\*\*/im, "reject"],
      [/^- \[x\] \*\*Adjust\*\*/im, "adjust"],
      [/^- \[x\] \*\*Demote core conviction\*\*/im, "demote_core"],
    ] as const;
    for (const [re, decision] of checks) {
      if (re.test(text)) return decision;
    }
    return null;
  }

  extractAdjustedConfidence(text: string): number | null {
    const m = text.match(
      /^- \[x\] \*\*Adjust\*\* — set confidence to:\s*([0-9.]+)/im,
    );
    if (!m) return null;
    const val = parseFloat(m[1]);
    return Number.isFinite(val) ? val : null;
  }

  async fetchPendingAdjudications(): Promise<AdjudicationEntry[]> {
    try {
      const resp = await fetch(
        `${this.settings.apiUrl}/tools/adjudication.queue`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ params: { limit: 50 } }),
        },
      );
      if (!resp.ok) return [];
      const body = await resp.json();
      return body?.result?.entries ?? [];
    } catch {
      return [];
    }
  }
}

class AtlasAdjudicationView extends ItemView {
  plugin: AtlasMemoryPlugin;

  constructor(leaf: WorkspaceLeaf, plugin: AtlasMemoryPlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType() { return ATLAS_VIEW_TYPE; }
  getDisplayText() { return "Atlas Adjudications"; }
  getIcon() { return "brain"; }

  async onOpen() {
    await this.refresh();
  }

  async refresh() {
    const container = this.containerEl.children[1];
    container.empty();
    container.createEl("h3", { text: "Atlas — Pending Adjudications" });
    container.createEl("p", {
      text: "Open an entry, check the decision box, save the file. " +
            "Atlas applies the AGM revision and archives the markdown.",
    });

    const entries = await this.plugin.fetchPendingAdjudications();
    if (entries.length === 0) {
      container.createEl("p", { text: "(queue is empty)" });
      return;
    }

    const list = container.createEl("ul");
    for (const e of entries) {
      const item = list.createEl("li");
      const link = item.createEl("a", { text: e.filename });
      link.addEventListener("click", async () => {
        const file = this.app.vault.getAbstractFileByPath(e.path);
        if (file instanceof TFile) {
          await this.app.workspace.getLeaf(true).openFile(file);
        }
      });
    }

    const refreshBtn = container.createEl("button", { text: "Refresh" });
    refreshBtn.addEventListener("click", () => this.refresh());
  }
}

class AtlasSettingTab extends PluginSettingTab {
  plugin: AtlasMemoryPlugin;

  constructor(app: App, plugin: AtlasMemoryPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Atlas Memory settings" });

    new Setting(containerEl)
      .setName("Atlas API URL")
      .setDesc("Where the Atlas FastAPI server is listening.")
      .addText((text) => text
        .setPlaceholder("http://localhost:9879")
        .setValue(this.plugin.settings.apiUrl)
        .onChange(async (value) => {
          this.plugin.settings.apiUrl = value || DEFAULT_SETTINGS.apiUrl;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Adjudication directory")
      .setDesc("Vault-relative path Atlas writes adjudication entries to.")
      .addText((text) => text
        .setPlaceholder("00 Atlas/adjudication")
        .setValue(this.plugin.settings.adjudicationDir)
        .onChange(async (value) => {
          this.plugin.settings.adjudicationDir = value || DEFAULT_SETTINGS.adjudicationDir;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Agent ID")
      .setDesc("Recorded as `actor` on every resolution.")
      .addText((text) => text
        .setPlaceholder("rich")
        .setValue(this.plugin.settings.agentId)
        .onChange(async (value) => {
          this.plugin.settings.agentId = value || DEFAULT_SETTINGS.agentId;
          await this.plugin.saveSettings();
        }),
      );
  }
}
