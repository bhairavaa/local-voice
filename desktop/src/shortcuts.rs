//! Global hotkeys.
//!
//! Registration happens here, in the process that owns the window message loop. Doing this
//! from Python would mean a low-level keyboard hook, which needs elevation on Windows and is
//! routinely flagged as a keylogger by antivirus software.
//!
//! A pressed hotkey only emits an event. The HTTP call that follows belongs to the interface,
//! which already holds a typed client generated from the engine's own schema; a second client
//! here would be a second implementation of the same contract, free to drift.

use std::str::FromStr;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

/// Event emitted to the interface when the dictation hotkey is pressed.
pub const TOGGLE_EVENT: &str = "dictation://toggle";

/// Event emitted when the cancel hotkey is pressed.
pub const CANCEL_EVENT: &str = "dictation://cancel";

const TOGGLE_ENV: &str = "LAA_SHELL__TOGGLE_HOTKEY";
const CANCEL_ENV: &str = "LAA_SHELL__CANCEL_HOTKEY";

/// Chosen to avoid the common Windows bindings: Win+Space switches keyboard layout and
/// Ctrl+Shift+Space is used by several editors for parameter hints, but Ctrl+Alt+Space is
/// largely unclaimed.
const DEFAULT_TOGGLE: &str = "CommandOrControl+Alt+Space";
const DEFAULT_CANCEL: &str = "CommandOrControl+Alt+Escape";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ShortcutSettings {
    pub toggle: String,
    pub cancel: String,
}

impl Default for ShortcutSettings {
    fn default() -> Self {
        Self {
            toggle: DEFAULT_TOGGLE.to_owned(),
            cancel: DEFAULT_CANCEL.to_owned(),
        }
    }
}

impl ShortcutSettings {
    /// Read bindings from the environment, falling back to the defaults.
    ///
    /// The `LAA_` prefix matches the engine's convention so both halves of the application are
    /// configured the same way. A settings screen will supersede this.
    pub fn from_environment() -> Self {
        let defaults = Self::default();
        Self {
            toggle: read_binding(TOGGLE_ENV).unwrap_or(defaults.toggle),
            cancel: read_binding(CANCEL_ENV).unwrap_or(defaults.cancel),
        }
    }
}

fn read_binding(variable: &str) -> Option<String> {
    std::env::var(variable)
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}

#[derive(Debug, thiserror::Error)]
pub enum ShortcutError {
    #[error("'{binding}' is not a valid hotkey: {reason}")]
    Unparsable { binding: String, reason: String },

    #[error("'{binding}' is already claimed by another application")]
    Unavailable { binding: String },
}

/// Parse a binding, reporting the offending text rather than a generic failure.
pub fn parse(binding: &str) -> Result<Shortcut, ShortcutError> {
    Shortcut::from_str(binding).map_err(|error| ShortcutError::Unparsable {
        binding: binding.to_owned(),
        reason: error.to_string(),
    })
}

/// Register the dictation hotkeys and route presses to the interface.
///
/// A binding already held by another application is reported and skipped rather than being
/// fatal: losing one hotkey should not stop the application starting, and the user needs to be
/// told which one so they can rebind it.
pub fn register(app: &AppHandle, settings: &ShortcutSettings) -> Vec<ShortcutError> {
    let mut failures = Vec::new();

    for (binding, event) in [
        (&settings.toggle, TOGGLE_EVENT),
        (&settings.cancel, CANCEL_EVENT),
    ] {
        match register_one(app, binding, event) {
            Ok(()) => tracing::info!(binding = %binding, event, "hotkey registered"),
            Err(error) => {
                tracing::warn!(%error, "hotkey unavailable");
                failures.push(error);
            }
        }
    }

    failures
}

fn register_one(app: &AppHandle, binding: &str, event: &'static str) -> Result<(), ShortcutError> {
    let shortcut = parse(binding)?;
    let handle = app.clone();

    app.global_shortcut()
        .on_shortcut(shortcut, move |_app, _shortcut, pressed| {
            // Both the press and the release arrive; acting on each would toggle twice.
            if pressed.state() != ShortcutState::Pressed {
                return;
            }

            // Logged unconditionally. Without it the log cannot distinguish a hotkey press
            // from a button click in the window, because both end at the same endpoint.
            tracing::info!(event, "hotkey pressed");

            match handle.emit(event, ()) {
                Ok(()) => tracing::debug!(event, "hotkey delivered to the interface"),
                Err(error) => {
                    tracing::error!(%error, event, "could not deliver hotkey to the interface");
                }
            }
        })
        .map_err(|_| ShortcutError::Unavailable {
            binding: binding.to_owned(),
        })
}

/// Bring the main window forward so the user can review what was dictated.
pub fn present_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        tracing::warn!("main window is missing; cannot present it");
        return;
    };

    for outcome in [
        window.show().err(),
        window.unminimize().err(),
        window.set_focus().err(),
    ]
    .into_iter()
    .flatten()
    {
        tracing::warn!(error = %outcome, "could not present the window");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_are_parsable() {
        let settings = ShortcutSettings::default();

        assert!(parse(&settings.toggle).is_ok());
        assert!(parse(&settings.cancel).is_ok());
    }

    #[test]
    fn rejects_nonsense_and_names_it() {
        let error = parse("NotAKey+++").expect_err("should not parse");

        assert!(error.to_string().contains("NotAKey+++"));
    }

    #[test]
    fn blank_environment_values_fall_back_to_defaults() {
        assert_eq!(read_binding("LAA_SHELL__A_VARIABLE_THAT_IS_NOT_SET"), None);
    }

    #[test]
    fn the_two_defaults_differ() {
        let settings = ShortcutSettings::default();

        assert_ne!(settings.toggle, settings.cancel);
    }
}
