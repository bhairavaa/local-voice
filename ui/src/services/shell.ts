/**
 * The desktop shell's side of the boundary.
 *
 * Everything touching the operating system — hotkeys, clipboard, window focus — lives in Rust
 * and is reached through here. In a plain browser none of it exists, so each function degrades
 * to something sensible rather than throwing: the interface stays usable for development.
 */

import { isRunningInDesktopShell } from "./connection";

export interface ShortcutBindings {
  readonly toggle: string;
  readonly cancel: string;
}

/** Emitted by the shell when the dictation hotkey is pressed. */
export const TOGGLE_EVENT = "dictation://toggle";

/** Emitted by the shell when the cancel hotkey is pressed. */
export const CANCEL_EVENT = "dictation://cancel";

/**
 * Subscribe to a shell event. Returns a function that unsubscribes.
 *
 * Failures are logged rather than swallowed. A listener that never attaches makes the hotkey
 * appear simply not to work, with nothing anywhere to say why.
 */
export async function onShellEvent(
  event: string,
  handler: () => void,
): Promise<() => void> {
  if (!isRunningInDesktopShell()) {
    console.warn(`Not in the desktop shell; "${event}" will never fire.`);
    return () => undefined;
  }

  try {
    const { listen } = await import("@tauri-apps/api/event");
    const unlisten = await listen(event, () => {
      console.debug(`shell event received: ${event}`);
      handler();
    });
    console.info(`listening for shell event: ${event}`);
    return unlisten;
  } catch (caught) {
    console.error(`Could not listen for "${event}":`, caught);
    return () => undefined;
  }
}

/** The hotkeys currently registered, for display in the interface. */
export async function shortcutBindings(): Promise<ShortcutBindings | null> {
  if (!isRunningInDesktopShell()) return null;

  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ShortcutBindings>("shortcut_bindings");
}

/**
 * Copy text to the clipboard.
 *
 * Inside the shell this goes through Rust, which reaches the real system clipboard. The
 * browser's own API is used otherwise, and it requires the document to be focused — which is
 * why the shell path is not merely a convenience.
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (isRunningInDesktopShell()) {
    const { writeText } = await import("@tauri-apps/plugin-clipboard-manager");
    await writeText(text);
    return;
  }

  await navigator.clipboard.writeText(text);
}

/** Bring the window forward, once there is something worth showing. */
export async function presentWindow(): Promise<void> {
  if (!isRunningInDesktopShell()) return;

  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("present_window");
}

/**
 * Show or hide the "listening" indicator.
 *
 * Without it, dictating from another application gives no sign that anything is happening,
 * which makes a working hotkey indistinguishable from a broken one.
 */
export async function setRecordingIndicator(visible: boolean): Promise<void> {
  if (!isRunningInDesktopShell()) return;

  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("set_recording_indicator", { visible });
}
