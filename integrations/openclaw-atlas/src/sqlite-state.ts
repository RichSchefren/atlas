import { createHash } from "node:crypto";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import type { AtlasPluginStateEntry, AtlasPluginStateStore } from "./types.js";

type StoredRow = {
  key: string;
  value_json: string;
  created_at: number;
};

function expandHome(value: string): string {
  return value === "~" || value.startsWith("~/")
    ? join(homedir(), value.slice(2))
    : value;
}

function safeProfileDirectory(profile: string): string {
  if (/^[A-Za-z0-9_.-]+$/.test(profile) && profile !== "." && profile !== "..") {
    return profile;
  }
  const readable = profile.replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "") || "profile";
  const digest = createHash("sha256").update(profile).digest("hex").slice(0, 12);
  return `${readable.slice(0, 64)}-${digest}`;
}

export function resolveAtlasDatabasePath(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const override = env.OPENCLAW_STATE_DIR?.trim();
  let stateDir: string;
  if (override) {
    const expanded = expandHome(override);
    stateDir = isAbsolute(expanded) ? expanded : resolve(expanded);
  } else {
    const baseHome = env.OPENCLAW_HOME?.trim()
      ? resolve(expandHome(env.OPENCLAW_HOME.trim()))
      : homedir();
    const profile = env.OPENCLAW_PROFILE?.trim();
    stateDir =
      profile && profile.toLowerCase() !== "default"
        ? join(baseHome, `.openclaw-${safeProfileDirectory(profile)}`)
        : join(baseHome, ".openclaw");
  }
  return join(stateDir, "plugins", "atlas-memory", "atlas.sqlite");
}

export class SqliteState<T> implements AtlasPluginStateStore<T> {
  private readonly database: DatabaseSync;

  constructor(readonly databasePath: string) {
    mkdirSync(dirname(databasePath), { recursive: true, mode: 0o700 });
    this.database = new DatabaseSync(databasePath);
    this.database.exec(
      "PRAGMA journal_mode = WAL; PRAGMA busy_timeout = 5000;",
    );
    this.database.exec(`
      CREATE TABLE IF NOT EXISTS atlas_memory_records (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
      ) STRICT;
    `);
  }

  async register(key: string, value: T): Promise<void> {
    const now = Date.now();
    this.database
      .prepare(
        `
      INSERT INTO atlas_memory_records (key, value_json, created_at, updated_at)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(key) DO UPDATE SET
        value_json = excluded.value_json,
        updated_at = excluded.updated_at
    `,
      )
      .run(key, JSON.stringify(value), now, now);
  }

  async lookup(key: string): Promise<T | undefined> {
    const row = this.database
      .prepare("SELECT value_json FROM atlas_memory_records WHERE key = ?")
      .get(key) as { value_json: string } | undefined;
    return row ? (JSON.parse(row.value_json) as T) : undefined;
  }

  async entries(): Promise<AtlasPluginStateEntry<T>[]> {
    const rows = this.database
      .prepare(
        "SELECT key, value_json, created_at FROM atlas_memory_records ORDER BY created_at",
      )
      .all() as StoredRow[];
    return rows.map((row) => ({
      key: row.key,
      value: JSON.parse(row.value_json) as T,
      createdAt: row.created_at,
    }));
  }

  close(): void {
    this.database.close();
  }
}
