/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Engine port, supplied only when running the interface in a plain browser for development. */
  readonly VITE_ENGINE_PORT?: string;
  /** Engine session token, supplied only when running the interface in a plain browser. */
  readonly VITE_ENGINE_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
