//! Desktop shell for Local AI Assistant.
//!
//! This layer owns everything that touches the operating system. The Python engine owns the
//! speech and text pipeline and nothing else, so it never needs elevated permissions or a
//! keyboard hook.

pub mod engine;
pub mod overlay;
pub mod shortcuts;
pub mod tray;

use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{Manager, RunEvent, State, WindowEvent};

use crate::engine::{EngineConnection, EngineError, EngineProcess};
use crate::shortcuts::ShortcutSettings;

/// Holds the running engine so it can be stopped when the application exits.
struct EngineState(Mutex<Option<EngineProcess>>);

/// The hotkeys in force, so the interface can show the user what to press.
struct ShortcutState(ShortcutSettings);

/// Report the active hotkey bindings.
#[tauri::command]
fn shortcut_bindings(state: State<'_, ShortcutState>) -> ShortcutSettings {
    state.0.clone()
}

/// Bring the window forward. Called once the interface has text worth showing.
#[tauri::command]
fn present_window(app: tauri::AppHandle) {
    tray::present_main_window(&app);
}

/// Show or hide the recording indicator, so dictation is visible from another application.
#[tauri::command]
fn set_recording_indicator(app: tauri::AppHandle, visible: bool) {
    overlay::set_visible(&app, visible);
}

/// Report where the interface should connect, without exposing process details to the webview.
#[tauri::command]
fn engine_connection(state: State<'_, EngineState>) -> Result<EngineConnection, String> {
    let guard = state
        .0
        .lock()
        .map_err(|_| "engine state is poisoned".to_owned())?;

    guard
        .as_ref()
        .map(|process| EngineConnection::from(process.handshake()))
        .ok_or_else(|| "the engine is not running".to_owned())
}

/// Locate the engine source tree when running from a development checkout.
fn development_engine_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|root| root.join("engine"))
        .unwrap_or_else(|| PathBuf::from("engine"))
}

fn start_engine(app: &tauri::AppHandle) -> Result<EngineProcess, EngineError> {
    let resource_dir = app
        .path()
        .resource_dir()
        .unwrap_or_else(|_| PathBuf::from("."));

    EngineProcess::start(&resource_dir, &development_engine_dir())
}

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_env("LAA_LOG")
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_writer(std::io::stderr)
        .init();

    let shortcuts = ShortcutSettings::from_environment();

    tauri::Builder::default()
        // Must be registered first. A second instance would otherwise start, fail to claim the
        // hotkeys the first one already holds, and sit there looking broken — so launching
        // again just brings the running application forward.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            tracing::info!("second instance requested; presenting the running one");
            tray::present_main_window(app);
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(EngineState(Mutex::new(None)))
        .manage(ShortcutState(shortcuts.clone()))
        .invoke_handler(tauri::generate_handler![
            engine_connection,
            shortcut_bindings,
            present_window,
            set_recording_indicator
        ])
        .on_window_event(|window, event| {
            // Closing hides rather than quits: this is a background utility, and losing the
            // hotkey because a window was dismissed would be a surprise. Quit lives in the tray.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                    tracing::info!("main window hidden; the application is still listening");
                }
            }
        })
        .setup(move |app| {
            let process = start_engine(app.handle())?;
            let state: State<'_, EngineState> = app.state();
            *state
                .0
                .lock()
                .map_err(|_| "engine state is poisoned".to_owned())? = Some(process);

            // Unavailable hotkeys are reported, not fatal: the application is still usable
            // through its window, and the user needs to know which binding to change.
            for failure in shortcuts::register(app.handle(), &shortcuts) {
                tracing::warn!(%failure, "continuing without this hotkey");
            }

            tray::install(app.handle())?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the application")
        .run(|app, event| {
            // Stop the engine deliberately on exit. The engine also watches this process, so an
            // abrupt kill still leaves no orphan behind.
            if let RunEvent::Exit = event {
                let state: State<'_, EngineState> = app.state();

                // Take ownership within this statement rather than holding the guard across
                // the block: an `if let` keeps its temporary alive to the end of the block,
                // which would outlive `state` itself.
                let running = state.0.lock().ok().and_then(|mut guard| guard.take());

                if let Some(process) = running {
                    process.shutdown();
                }
            }
        });
}
