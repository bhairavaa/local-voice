/**
 * Discovery of the engine's address and session token.
 *
 * Inside the desktop shell these come from Rust, which read them from the engine's startup
 * handshake. When the interface is opened directly in a browser during development there is
 * no shell to ask, so they are taken from Vite environment variables instead.
 */

export interface EngineConnection {
  readonly port: number;
  readonly token: string;
}

/** Raised when the engine's location cannot be determined. */
export class EngineUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineUnavailableError";
  }
}

const TAURI_INTERNALS = "__TAURI_INTERNALS__";

/** Whether the interface is running inside the desktop shell rather than a plain browser. */
export function isRunningInDesktopShell(): boolean {
  return typeof window !== "undefined" && TAURI_INTERNALS in window;
}

async function connectionFromShell(): Promise<EngineConnection> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<EngineConnection>("engine_connection");
}

function connectionFromEnvironment(): EngineConnection {
  const port = import.meta.env.VITE_ENGINE_PORT;
  const token = import.meta.env.VITE_ENGINE_TOKEN;

  if (port === undefined || token === undefined) {
    throw new EngineUnavailableError(
      "Not running in the desktop shell. Start the engine, then set VITE_ENGINE_PORT and " +
        "VITE_ENGINE_TOKEN from its handshake line before running the dev server.",
    );
  }

  const parsedPort = Number.parseInt(port, 10);
  if (!Number.isInteger(parsedPort) || parsedPort <= 0 || parsedPort > 65535) {
    throw new EngineUnavailableError(`VITE_ENGINE_PORT is not a valid port: ${port}`);
  }

  return { port: parsedPort, token };
}

/** Resolve how to reach the engine, whichever context the interface is running in. */
export async function resolveConnection(): Promise<EngineConnection> {
  return isRunningInDesktopShell() ? connectionFromShell() : connectionFromEnvironment();
}
