/**
 * The "listening" indicator, rendered in its own always-on-top window.
 *
 * Deliberately tiny and non-interactive. It exists to answer one question — is it recording? —
 * for a user whose attention is in another application entirely.
 */
export function RecordingOverlay() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="flex items-center gap-2.5 rounded-full border border-edge bg-surface/95 px-4 py-2 shadow-lg backdrop-blur">
        <span className="relative flex size-2.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-danger opacity-75" />
          <span className="relative inline-flex size-2.5 rounded-full bg-danger" />
        </span>
        <span className="text-sm font-medium text-ink">Listening</span>
      </div>
    </div>
  );
}
