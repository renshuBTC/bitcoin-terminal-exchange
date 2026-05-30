// Prevents the second console window from appearing on Windows release builds.
// In debug we keep the console so cargo run / cargo tauri dev still shows logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    btx_app_lib::run()
}
