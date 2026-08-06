import { useCallback, useEffect, useState } from "react";

import { resolveConnection, type EngineConnection } from "../services/connection";
import { createEngineClient, type HealthResponse } from "../services/engineClient";

export type EngineStatus = "connecting" | "ready" | "unavailable";

export interface EngineHealth {
  readonly status: EngineStatus;
  readonly health: HealthResponse | null;
  readonly connection: EngineConnection | null;
  readonly error: string | null;
  readonly refresh: () => void;
}

/** Resolves the engine connection and reports its health, re-running on demand. */
export function useEngineHealth(): EngineHealth {
  const [status, setStatus] = useState<EngineStatus>("connecting");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [connection, setConnection] = useState<EngineConnection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const refresh = useCallback(() => {
    setAttempt((previous) => previous + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setStatus("connecting");
    setError(null);

    void (async () => {
      try {
        const resolved = await resolveConnection();
        const result = await createEngineClient(resolved).getHealth(controller.signal);
        if (cancelled) return;
        setConnection(resolved);
        setHealth(result);
        setStatus("ready");
      } catch (caught) {
        if (cancelled) return;
        setConnection(null);
        setHealth(null);
        setError(caught instanceof Error ? caught.message : String(caught));
        setStatus("unavailable");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [attempt]);

  return { status, health, connection, error, refresh };
}
