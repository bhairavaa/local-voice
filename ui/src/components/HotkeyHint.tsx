import type { ShortcutBindings } from "../services/shell";

/** Render a binding the way a user reads it, not the way the shell stores it. */
function humanise(binding: string): string[] {
  return binding
    .split("+")
    .map((part) => (part === "CommandOrControl" ? "Ctrl" : part))
    .map((part) => (part === "Escape" ? "Esc" : part));
}

interface Props {
  readonly bindings: ShortcutBindings | null;
  readonly recording: boolean;
}

/**
 * Shows which keys do what.
 *
 * Absent in a browser, where there is no shell to register hotkeys — so nothing is claimed
 * that would not actually work.
 */
export function HotkeyHint({ bindings, recording }: Props) {
  if (!bindings) return null;

  const binding = recording ? bindings.cancel : bindings.toggle;
  const label = recording ? "to discard" : "to dictate from anywhere";

  return (
    <p className="flex items-center justify-center gap-1.5 text-xs text-ink-muted">
      {humanise(binding).map((key) => (
        <kbd
          key={key}
          className="rounded border border-edge bg-surface-raised px-1.5 py-0.5 font-sans text-[11px] text-ink"
        >
          {key}
        </kbd>
      ))}
      <span className="ml-1">{label}</span>
    </p>
  );
}
