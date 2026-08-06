//! System tray presence.
//!
//! This application spends nearly all its time invisible, waiting on a hotkey. Without a tray
//! icon there is no way back to the window once it is closed, and no way to tell the
//! application is running at all -- which makes a working hotkey look broken.
//!
//! Closing the window therefore hides it rather than quitting. Quitting is deliberate, from
//! this menu, because an accidental close would silently take the hotkey away with it.

use tauri::menu::{Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Runtime};

const SHOW_ITEM: &str = "show";
const QUIT_ITEM: &str = "quit";

/// Build the tray icon and its menu.
pub fn install<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let show = MenuItem::with_id(
        app,
        SHOW_ITEM,
        "Open Local Voice",
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, QUIT_ITEM, "Quit", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&show, &separator, &quit])?;

    let mut builder = TrayIconBuilder::with_id("main-tray")
        .menu(&menu)
        .tooltip("Local Voice")
        // The menu is the right-click action; a left click should just open the window.
        .show_menu_on_left_click(false)
        .on_menu_event(handle_menu_event)
        .on_tray_icon_event(handle_icon_event);

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }

    builder.build(app)?;
    tracing::info!("tray icon installed");
    Ok(())
}

fn handle_menu_event<R: Runtime>(app: &AppHandle<R>, event: MenuEvent) {
    match event.id().as_ref() {
        SHOW_ITEM => present_main_window(app),
        QUIT_ITEM => {
            tracing::info!("quit requested from the tray");
            app.exit(0);
        }
        other => tracing::debug!(item = other, "unhandled tray menu item"),
    }
}

fn handle_icon_event<R: Runtime>(tray: &tauri::tray::TrayIcon<R>, event: TrayIconEvent) {
    if let TrayIconEvent::Click {
        button: MouseButton::Left,
        button_state: MouseButtonState::Up,
        ..
    } = event
    {
        present_main_window(tray.app_handle());
    }
}

/// Bring the main window back into view, whether hidden or merely behind something.
pub fn present_main_window<R: Runtime>(app: &AppHandle<R>) {
    let Some(window) = app.get_webview_window("main") else {
        tracing::warn!("main window is missing; cannot present it");
        return;
    };

    for error in [
        window.show().err(),
        window.unminimize().err(),
        window.set_focus().err(),
    ]
    .into_iter()
    .flatten()
    {
        tracing::warn!(%error, "could not present the main window");
    }
}
