import { useEffect, useRef, useState } from "react";

import {
  CANCEL_EVENT,
  TOGGLE_EVENT,
  onShellEvent,
  shortcutBindings,
  type ShortcutBindings,
} from "../services/shell";

interface Handlers {
  readonly onToggle: () => void;
  readonly onCancel: () => void;
}

/**
 * Routes global hotkey presses to the dictation controls.
 *
 * Handlers are held in a ref so the subscription is established once. Re-subscribing whenever a
 * callback identity changed would drop presses during the gap, and the hotkey is the one
 * interaction that must never be missed.
 */
export function useShellShortcuts({ onToggle, onCancel }: Handlers): ShortcutBindings | null {
  const [bindings, setBindings] = useState<ShortcutBindings | null>(null);
  const handlers = useRef<Handlers>({ onToggle, onCancel });

  handlers.current = { onToggle, onCancel };

  useEffect(() => {
    let cancelled = false;
    const teardown: Array<() => void> = [];

    void (async () => {
      const [stopToggle, stopCancel, resolved] = await Promise.all([
        onShellEvent(TOGGLE_EVENT, () => {
          handlers.current.onToggle();
        }),
        onShellEvent(CANCEL_EVENT, () => {
          handlers.current.onCancel();
        }),
        shortcutBindings(),
      ]);

      if (cancelled) {
        stopToggle();
        stopCancel();
        return;
      }

      teardown.push(stopToggle, stopCancel);
      setBindings(resolved);
    })().catch((caught: unknown) => {
      // Without this the hotkey silently does nothing and nothing anywhere explains why.
      console.error("Could not set up global shortcuts:", caught);
    });

    return () => {
      cancelled = true;
      for (const stop of teardown) stop();
    };
  }, []);

  return bindings;
}
