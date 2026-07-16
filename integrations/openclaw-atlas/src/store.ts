import { createHash, randomUUID } from "node:crypto";
import { normalizeText } from "./safety.js";
import type {
  AtlasMemoryRecord,
  AtlasMemorySource,
  AtlasPluginStateStore,
  AtlasScope,
  AtlasSearchHit,
} from "./types.js";

const TOKEN_PATTERN = /[\p{L}\p{N}]+/gu;

function textHash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function scopeMatches(record: AtlasMemoryRecord, scope: AtlasScope): boolean {
  return (
    record.scope.agentId === scope.agentId &&
    record.scope.sessionKey === scope.sessionKey
  );
}

function tokens(value: string): Set<string> {
  return new Set(
    (value.toLocaleLowerCase().match(TOKEN_PATTERN) ?? []).filter(
      (token) => token.length > 1,
    ),
  );
}

function lexicalScore(query: string, text: string, tags: string[]): number {
  const queryTokens = tokens(query);
  if (queryTokens.size === 0) {
    return 0;
  }
  const searchable = `${text} ${tags.join(" ")}`.toLocaleLowerCase();
  const textTokens = tokens(searchable);
  let matches = 0;
  for (const token of queryTokens) {
    if (textTokens.has(token)) {
      matches += 1;
    }
  }
  const coverage = matches / queryTokens.size;
  const phraseBonus = searchable.includes(query.toLocaleLowerCase()) ? 0.2 : 0;
  return Math.min(1, coverage * 0.8 + phraseBonus);
}

export class AtlasMemoryStore {
  constructor(
    private readonly state: AtlasPluginStateStore<AtlasMemoryRecord>,
  ) {}

  async put(params: {
    text: string;
    tags?: string[];
    scope: AtlasScope;
    source: AtlasMemorySource;
  }): Promise<{ action: "created" | "duplicate"; record: AtlasMemoryRecord }> {
    const normalizedText = normalizeText(params.text);
    const activeRecords = await this.activeRecords(params.scope);
    const duplicate = activeRecords.find(
      (record) => record.normalizedText === normalizedText,
    );
    if (duplicate) {
      return { action: "duplicate", record: duplicate };
    }
    if ((await this.state.entries()).length >= 10_000) {
      throw new Error(
        "Atlas memory limit reached (10,000 records); forget or export records before storing more.",
      );
    }

    const now = new Date().toISOString();
    const record: AtlasMemoryRecord = {
      id: `mem_${Date.now()}_${randomUUID().slice(0, 12)}`,
      text: normalizedText,
      normalizedText,
      textSha256: textHash(normalizedText),
      tags: [
        ...new Set((params.tags ?? []).map(normalizeText).filter(Boolean)),
      ].slice(0, 12),
      scope: params.scope,
      source: params.source,
      status: "active",
      createdAt: now,
      updatedAt: now,
      accessCount: 0,
    };
    await this.state.register(record.id, record);
    return { action: "created", record };
  }

  async search(params: {
    query: string;
    scope: AtlasScope;
    limit: number;
  }): Promise<AtlasSearchHit[]> {
    const normalizedQuery = normalizeText(params.query);
    const hits = (await this.activeRecords(params.scope))
      .map((record) => {
        const text = record.text ?? "";
        return {
          id: record.id,
          text,
          tags: record.tags,
          score: lexicalScore(normalizedQuery, text, record.tags),
          source: record.source,
          createdAt: record.createdAt,
        } satisfies AtlasSearchHit;
      })
      .filter((hit) => hit.score > 0)
      .sort(
        (left, right) =>
          right.score - left.score ||
          right.createdAt.localeCompare(left.createdAt),
      )
      .slice(0, params.limit);

    const accessedAt = new Date().toISOString();
    for (const hit of hits) {
      const record = await this.state.lookup(hit.id);
      if (!record || record.status !== "active") {
        continue;
      }
      await this.state.register(hit.id, {
        ...record,
        accessCount: record.accessCount + 1,
        lastAccessedAt: accessedAt,
        updatedAt: accessedAt,
      });
    }
    return hits;
  }

  async get(id: string, scope: AtlasScope): Promise<AtlasMemoryRecord | null> {
    const record = await this.state.lookup(id);
    if (!record || !scopeMatches(record, scope) || record.status !== "active") {
      return null;
    }
    const now = new Date().toISOString();
    const updated = {
      ...record,
      accessCount: record.accessCount + 1,
      lastAccessedAt: now,
      updatedAt: now,
    } satisfies AtlasMemoryRecord;
    await this.state.register(id, updated);
    return updated;
  }

  async forget(params: {
    id: string;
    scope: AtlasScope;
    reason?: string;
  }): Promise<"forgotten" | "not_found"> {
    const record = await this.state.lookup(params.id);
    if (
      !record ||
      !scopeMatches(record, params.scope) ||
      record.status !== "active"
    ) {
      return "not_found";
    }
    const now = new Date().toISOString();
    await this.state.register(record.id, {
      ...record,
      text: null,
      normalizedText: null,
      tags: [],
      status: "forgotten",
      forgottenAt: now,
      forgetReason: normalizeText(params.reason ?? "user_request").slice(
        0,
        200,
      ),
      updatedAt: now,
    });
    return "forgotten";
  }

  private async activeRecords(scope: AtlasScope): Promise<AtlasMemoryRecord[]> {
    return (await this.state.entries())
      .map((entry) => entry.value)
      .filter(
        (record) => record.status === "active" && scopeMatches(record, scope),
      );
  }
}
