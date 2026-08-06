/**
 * Typed client for the engine's HTTP API.
 *
 * Request and response shapes come from `generated/engine.ts`, which is produced from the
 * engine's own OpenAPI document. Changing a Pydantic model and forgetting to regenerate
 * therefore breaks the build rather than producing a silent mismatch at runtime.
 */

import type { components } from "./generated/engine";
import type { EngineConnection } from "./connection";

export type HealthResponse = components["schemas"]["HealthResponse"];
export type CapabilitiesResponse = components["schemas"]["CapabilitiesResponse"];
export type DictationResultResponse = components["schemas"]["DictationResultResponse"];
export type DictationStateResponse = components["schemas"]["DictationStateResponse"];
export type EnhancementProfile = components["schemas"]["EnhancementProfile"];

/** Raised when the engine is reachable but rejects or fails a request. */
export class EngineRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "EngineRequestError";
    this.status = status;
  }
}

export interface EngineClient {
  getHealth(signal?: AbortSignal): Promise<HealthResponse>;
  getCapabilities(signal?: AbortSignal): Promise<CapabilitiesResponse>;
  getDictationState(signal?: AbortSignal): Promise<DictationStateResponse>;
  startDictation(): Promise<DictationStateResponse>;
  /** Resolves once transcription finishes, so it takes as long as the model needs. */
  stopDictation(profile?: EnhancementProfile): Promise<DictationResultResponse>;
  cancelDictation(): Promise<void>;
}

export function createEngineClient(connection: EngineConnection): EngineClient {
  const baseUrl = `http://127.0.0.1:${String(connection.port)}`;
  const authorization = { Authorization: `Bearer ${connection.token}` };

  async function send<T>(
    path: string,
    {
      method = "GET",
      body,
      signal,
    }: { method?: string; body?: unknown; signal?: AbortSignal | undefined } = {},
  ): Promise<T> {
    const response = await fetch(`${baseUrl}${path}`, {
      method,
      headers:
        body === undefined
          ? authorization
          : { ...authorization, "Content-Type": "application/json" },
      body: body === undefined ? null : JSON.stringify(body),
      signal: signal ?? null,
    });

    if (!response.ok) {
      throw new EngineRequestError(
        response.status,
        await describeFailure(response, path),
      );
    }

    return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  }

  return {
    getHealth: (signal) => send<HealthResponse>("/health", { signal }),
    getCapabilities: (signal) => send<CapabilitiesResponse>("/capabilities", { signal }),
    getDictationState: (signal) => send<DictationStateResponse>("/dictation/state", { signal }),
    startDictation: () => send<DictationStateResponse>("/dictation/start", { method: "POST" }),
    stopDictation: (profile) =>
      send<DictationResultResponse>("/dictation/stop", {
        method: "POST",
        body: { profile: profile ?? null },
      }),
    cancelDictation: async () => {
      await send<undefined>("/dictation/cancel", { method: "POST" });
    },
  };
}

/** Prefer the engine's own explanation over a bare status code. */
async function describeFailure(response: Response, path: string): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload) {
      return String((payload as { detail: unknown }).detail);
    }
  } catch {
    // Fall through to the generic message below.
  }
  return `Engine returned ${String(response.status)} for ${path}`;
}
