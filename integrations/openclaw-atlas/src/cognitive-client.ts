import { spawn, type ChildProcess } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { createHash, randomBytes } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SERVICE_VERSION = "0.1.0";

type ManagedState = {
  port: number;
  scopeId: string;
  serviceVersion: string;
  token: string;
};

type ServiceEnvelope = {
  api_version?: unknown;
  data?: unknown;
  error?: { code?: unknown; message?: unknown };
  ok?: unknown;
};

export class CognitiveServiceError extends Error {
  constructor(
    message: string,
    readonly code = "service_error",
    readonly status = 0,
  ) {
    super(message);
  }
}

export class CognitiveServiceUnavailable extends CognitiveServiceError {}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function serviceRoot(explicitRoot?: string): string {
  if (explicitRoot) {
    if (!existsSync(join(explicitRoot, "server.py"))) {
      throw new CognitiveServiceUnavailable(
        `Atlas cognitive-service assets are missing from ${explicitRoot}`,
      );
    }
    return explicitRoot;
  }
  const here = dirname(fileURLToPath(import.meta.url));
  const candidates = [
    join(here, "..", "..", "service"),
    join(here, "..", "..", "..", "cognitive-service"),
  ];
  const root = candidates.find((candidate) => existsSync(join(candidate, "server.py")));
  if (!root) {
    throw new CognitiveServiceUnavailable(
      "Atlas cognitive-service assets are missing; reinstall the OpenClaw package",
    );
  }
  return root;
}

function parseState(path: string, expectedScope: string): ManagedState {
  let value: unknown;
  try {
    value = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    throw new CognitiveServiceError(`Invalid managed cognitive state file: ${path}`);
  }
  if (!value || typeof value !== "object") {
    throw new CognitiveServiceError(`Invalid managed cognitive state file: ${path}`);
  }
  const state = value as Partial<ManagedState>;
  if (
    state.scopeId !== expectedScope ||
    !Number.isInteger(state.port) ||
    typeof state.token !== "string" ||
    state.token.length < 32
  ) {
    throw new CognitiveServiceError(`Managed cognitive state does not match scope: ${path}`);
  }
  return state as ManagedState;
}

export class ManagedCognitiveClient {
  readonly baseUrl: string;
  readonly token: string;
  readonly scopeId: string;
  private child: ChildProcess | null = null;
  private launchError: Error | null = null;
  private ownsRunningInstance = false;
  private readonly ownerInstance = randomBytes(16).toString("hex");
  private readonly databasePath: string;
  private readonly logPath: string;

  constructor(
    private readonly dataDir: string,
    scopeKey: string,
    private readonly pythonCommand = process.env.ATLAS_PYTHON ||
      (process.platform === "win32" ? "python" : "python3"),
    private readonly serviceAssetRoot?: string,
    serviceNamespace = "openclaw",
  ) {
    if (!/^[a-z][a-z0-9-]{0,31}$/.test(serviceNamespace)) {
      throw new CognitiveServiceError("Invalid Atlas service namespace");
    }
    const identity = `${dataDir}\0${scopeKey}`;
    this.scopeId = `${serviceNamespace}-${sha256(identity).slice(0, 32)}`;
    const port = 20_000 + (Number.parseInt(sha256(identity).slice(0, 8), 16) % 30_000);
    const serviceDir = join(dataDir, "cognitive", this.scopeId);
    mkdirSync(serviceDir, { recursive: true, mode: 0o700 });
    const statePath = join(serviceDir, "state.json");
    if (!existsSync(statePath)) {
      const state: ManagedState = {
        port,
        scopeId: this.scopeId,
        serviceVersion: SERVICE_VERSION,
        token: randomBytes(32).toString("base64url"),
      };
      try {
        writeFileSync(statePath, `${JSON.stringify(state)}\n`, {
          encoding: "utf8",
          flag: "wx",
          mode: 0o600,
        });
      } catch (error) {
        if (!existsSync(statePath)) throw error;
      }
    }
    const state = parseState(statePath, this.scopeId);
    if (state.port !== port || state.serviceVersion !== SERVICE_VERSION) {
      throw new CognitiveServiceError(
        "Managed cognitive state uses an incompatible port or service version",
      );
    }
    this.baseUrl = `http://127.0.0.1:${state.port}`;
    this.token = state.token;
    this.databasePath = join(serviceDir, "cognitive.sqlite3");
    this.logPath = join(serviceDir, "service.log");
  }

  static operationKey(prefix: string, context: string, payload: unknown): string {
    return `openclaw-${prefix}-${sha256(canonical({ context, payload }))}`;
  }

  static memoryId(idempotencyKey: string): string {
    return `openclaw-${sha256(idempotencyKey).slice(0, 32)}`;
  }

  private async raw(method: string, path: string, body?: unknown): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout(5_000),
      });
    } catch {
      throw new CognitiveServiceUnavailable(
        `Atlas cognitive service is unavailable at ${this.baseUrl}`,
        "unavailable",
        0,
      );
    }
    let envelope: ServiceEnvelope;
    try {
      envelope = (await response.json()) as ServiceEnvelope;
    } catch {
      throw new CognitiveServiceError("Cognitive service returned invalid JSON", "invalid_response", response.status);
    }
    if (envelope.api_version !== "v1") {
      throw new CognitiveServiceError("Cognitive service returned an invalid v1 envelope");
    }
    if (!response.ok || envelope.ok !== true) {
      throw new CognitiveServiceError(
        typeof envelope.error?.message === "string"
          ? envelope.error.message
          : `Cognitive service HTTP ${response.status}`,
        typeof envelope.error?.code === "string" ? envelope.error.code : "http_error",
        response.status,
      );
    }
    return envelope.data;
  }

  private async health(): Promise<Record<string, unknown>> {
    const health = (await this.raw("GET", "/v1/health")) as Record<string, unknown>;
    if (health.scope_id !== this.scopeId) {
      throw new CognitiveServiceError("Cognitive service scope mismatch; refusing cross-scope access");
    }
    if (health.service_version !== SERVICE_VERSION) {
      throw new CognitiveServiceError(
        `Cognitive service version mismatch: expected ${SERVICE_VERSION}`,
      );
    }
    return health;
  }

  private launch(): void {
    const root = serviceRoot(this.serviceAssetRoot);
    const logFd = openSync(this.logPath, "a", 0o600);
    this.launchError = null;
    try {
      this.child = spawn(
        this.pythonCommand,
        [
          join(root, "server.py"),
          "--db",
          this.databasePath,
          "--scope",
          this.scopeId,
          "--port",
          new URL(this.baseUrl).port,
          "--owner-instance",
          this.ownerInstance,
          "--parent-pid",
          String(process.pid),
        ],
        {
          cwd: root,
          detached: process.platform !== "win32",
          env: { ...process.env, ATLAS_COGNITIVE_TOKEN: this.token },
          stdio: ["ignore", logFd, logFd],
          windowsHide: true,
        },
      );
      // Spawn reports an absent executable asynchronously; retain it so the
      // readiness loop returns the real cause instead of only a timeout.
      this.child.once("error", (error) => {
        this.launchError = error;
      });
    } finally {
      closeSync(logFd);
    }
    this.ownsRunningInstance = true;
  }

  async ensureAvailable(): Promise<Record<string, unknown>> {
    try {
      const health = await this.health();
      const owner = (health.managed_owner ?? {}) as Record<string, unknown>;
      this.ownsRunningInstance = owner.instance_id === this.ownerInstance;
      if (!owner.instance_id) {
        throw new CognitiveServiceError(
          "Managed endpoint has no owner metadata; refusing unsafe attachment",
        );
      }
      return health;
    } catch (error) {
      if (!(error instanceof CognitiveServiceUnavailable)) throw error;
    }
    this.launch();
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline) {
      if (this.launchError) {
        throw new CognitiveServiceUnavailable(
          `Could not launch Atlas with ${this.pythonCommand}: ${this.launchError.message}`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
      try {
        const health = await this.health();
        const owner = (health.managed_owner ?? {}) as Record<string, unknown>;
        this.ownsRunningInstance = owner.instance_id === this.ownerInstance;
        return health;
      } catch (error) {
        if (!(error instanceof CognitiveServiceUnavailable)) throw error;
      }
    }
    throw new CognitiveServiceUnavailable(
      `Managed cognitive service did not become ready; inspect ${this.logPath}`,
    );
  }

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    await this.ensureAvailable();
    try {
      return await this.raw(method, path, body);
    } catch (error) {
      if (!(error instanceof CognitiveServiceUnavailable)) throw error;
      this.ownsRunningInstance = false;
      await this.ensureAvailable();
      return await this.raw(method, path, body);
    }
  }

  async shutdown(): Promise<void> {
    if (this.ownsRunningInstance) {
      try {
        await this.raw("POST", "/v1/control/shutdown", {
          owner_instance: this.ownerInstance,
        });
      } catch (error) {
        if (!(error instanceof CognitiveServiceUnavailable)) throw error;
      }
    }
    if (this.child && this.child.exitCode === null) {
      await Promise.race([
        new Promise<void>((resolve) => this.child?.once("exit", () => resolve())),
        new Promise<void>((resolve) => setTimeout(resolve, 3_000)),
      ]);
      if (this.child.exitCode === null) this.child.kill("SIGTERM");
    }
    this.child = null;
    this.ownsRunningInstance = false;
  }
}

export class CognitiveClientPool {
  private readonly clients = new Map<string, ManagedCognitiveClient>();

  constructor(
    private readonly dataDir: string,
    private readonly pythonCommand?: string,
    private readonly serviceAssetRoot?: string,
  ) {}

  forScope(scopeKey: string): ManagedCognitiveClient {
    let client = this.clients.get(scopeKey);
    if (!client) {
      client = new ManagedCognitiveClient(
        this.dataDir,
        scopeKey,
        this.pythonCommand,
        this.serviceAssetRoot,
      );
      this.clients.set(scopeKey, client);
    }
    return client;
  }

  async shutdown(): Promise<void> {
    const results = await Promise.allSettled(
      [...this.clients.values()].map((client) => client.shutdown()),
    );
    this.clients.clear();
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") throw failure.reason;
  }
}
