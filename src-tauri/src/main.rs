// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::SocketAddr;
use std::net::TcpStream;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

fn is_backend_listening() -> bool {
    let addr: SocketAddr = "127.0.0.1:8000".parse().unwrap();
    TcpStream::connect_timeout(&addr, Duration::from_millis(350)).is_ok()
}

fn wait_for_backend(timeout_secs: u64) -> bool {
    let start = std::time::Instant::now();
    let max_duration = Duration::from_secs(timeout_secs);
    while start.elapsed() < max_duration {
        if is_backend_listening() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

fn main() {
    let backend_child: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let child_for_setup = Arc::clone(&backend_child);
    let child_for_exit = Arc::clone(&backend_child);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            // 1. Check if backend is already running
            if !is_backend_listening() {
                // Spawn Python backend sidecar binary
                match app.shell().sidecar("reelfren-backend") {
                    Ok(command) => {
                        match command.spawn() {
                            Ok((_rx, child)) => {
                                println!("[Tauri] Spawned reelfren-backend sidecar.");
                                if let Ok(mut lock) = child_for_setup.lock() {
                                    *lock = Some(child);
                                }
                            }
                            Err(e) => {
                                eprintln!("[Tauri] Failed to spawn sidecar: {}", e);
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("[Tauri] Sidecar command not configured or missing: {}", e);
                    }
                }
            } else {
                println!("[Tauri] Backend server already running on port 8000.");
            }

            // 2. Wait for backend to be ready
            let _ready = wait_for_backend(15);

            // 3. Point the main window to the backend URL
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.navigate("http://127.0.0.1:8000".parse().unwrap());
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(move |_app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                // Ensure backend sidecar is terminated on app exit
                if let Ok(mut lock) = child_for_exit.lock() {
                    if let Some(child) = lock.take() {
                        let _ = child.kill();
                        println!("[Tauri] Cleaned up backend sidecar process.");
                    }
                }
            }
        });
}
