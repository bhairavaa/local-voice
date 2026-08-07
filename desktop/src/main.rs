// Suppress the console window in release builds; the shell is a background tray application.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    local_voice_lib::run()
}
