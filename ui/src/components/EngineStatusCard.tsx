import type { EngineHealth } from "../hooks/useEngineHealth";

const INDICATOR_CLASSES: Record<EngineHealth["status"], string> = {
  connecting: "bg-ink-muted animate-pulse",
  ready: "bg-accent",
  unavailable: "bg-danger",
};

const LABELS: Record<EngineHealth["status"], string> = {
  connecting: "Connecting to engine",
  ready: "Engine ready",
  unavailable: "Engine unavailable",
};

/** Reports whether the local engine process is reachable, and why it is not when it fails. */
export function EngineStatusCard({ status, health, error, refresh }: EngineHealth) {
  return (
    <section className="w-full max-w-lg rounded-xl border border-edge bg-surface-raised p-6 shadow-lg">
      <header className="flex items-center gap-3">
        <span
          className={`size-2.5 rounded-full ${INDICATOR_CLASSES[status]}`}
          aria-hidden="true"
        />
        <h2 className="text-base font-medium text-ink">{LABELS[status]}</h2>
      </header>

      {health && (
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-ink-muted">Version</dt>
          <dd className="text-ink tabular-nums">{health.version}</dd>
          <dt className="text-ink-muted">Process</dt>
          <dd className="text-ink tabular-nums">{health.process_id}</dd>
          <dt className="text-ink-muted">Uptime</dt>
          <dd className="text-ink tabular-nums">{health.uptime_seconds.toFixed(1)}s</dd>
        </dl>
      )}

      {error && (
        <p className="mt-4 text-sm leading-relaxed text-ink-muted" role="alert">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={refresh}
        className="mt-5 rounded-md border border-edge px-3 py-1.5 text-sm text-ink transition hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Check again
      </button>
    </section>
  );
}
