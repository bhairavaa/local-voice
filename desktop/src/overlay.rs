//! The recording indicator.
//!
//! Pressing the hotkey from another application used to produce no visible sign that anything
//! had happened: the main window stays behind whatever the user is working in, so dictation
//! ran completely blind. This is the small overlay that says "listening".
//!
//! It must never take focus. The entire point of dictating from another application is that
//! the target keeps keyboard focus and stays ready to be pasted into; an indicator that stole
//! focus would break the workflow it exists to support.

use tauri::{AppHandle, Manager, PhysicalPosition, WebviewWindow};

pub const OVERLAY_LABEL: &str = "overlay";

/// Distance from the bottom of the work area, in physical pixels.
const BOTTOM_MARGIN: i32 = 96;

fn overlay(app: &AppHandle) -> Option<WebviewWindow> {
    let window = app.get_webview_window(OVERLAY_LABEL);
    if window.is_none() {
        tracing::warn!("overlay window is missing from the configuration");
    }
    window
}

/// Place the overlay at the bottom centre of the primary monitor.
fn position(window: &WebviewWindow) {
    let Ok(Some(monitor)) = window.primary_monitor() else {
        tracing::debug!("no primary monitor reported; leaving the overlay where it is");
        return;
    };
    let Ok(size) = window.outer_size() else {
        return;
    };

    let screen = monitor.size();
    let x = (screen.width as i32 - size.width as i32) / 2;
    let y = screen.height as i32 - size.height as i32 - BOTTOM_MARGIN;

    if let Err(error) = window.set_position(PhysicalPosition::new(x, y)) {
        tracing::warn!(%error, "could not position the overlay");
    }
}

/// Show or hide the recording indicator.
pub fn set_visible(app: &AppHandle, visible: bool) {
    let Some(window) = overlay(app) else {
        return;
    };

    let outcome = if visible {
        position(&window);
        // show() only. set_focus() here would pull keyboard focus away from whatever the user
        // is dictating into.
        window.show()
    } else {
        window.hide()
    };

    if let Err(error) = outcome {
        tracing::warn!(%error, visible, "could not change overlay visibility");
    }
}
