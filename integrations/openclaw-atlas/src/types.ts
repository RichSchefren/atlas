export type AtlasScope = {
  agentId: string;
  sessionKey: string | null;
};

export type AtlasMemorySource = "manual" | "auto_capture";

export type AtlasMemoryRecord = {
  id: string;
  text: string | null;
  normalizedText: string | null;
  textSha256: string;
  tags: string[];
  scope: AtlasScope;
  source: AtlasMemorySource;
  status: "active" | "forgotten";
  createdAt: string;
  updatedAt: string;
  forgottenAt?: string;
  forgetReason?: string;
  accessCount: number;
  lastAccessedAt?: string;
};

export type AtlasSearchHit = {
  id: string;
  text: string;
  tags: string[];
  score: number;
  source: AtlasMemorySource;
  createdAt: string;
};

export type AtlasPluginStateEntry<T> = {
  key: string;
  value: T;
  createdAt: number;
  expiresAt?: number;
};

export type AtlasPluginStateStore<T> = {
  register(key: string, value: T): Promise<void>;
  lookup(key: string): Promise<T | undefined>;
  entries(): Promise<AtlasPluginStateEntry<T>[]>;
};
