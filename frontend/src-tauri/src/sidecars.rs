use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const OLLAMA_URL: &str = "http://127.0.0.1:11434";
const BACKEND_URL: &str = "http://127.0.0.1:8420";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(45);
const POLL_INTERVAL: Duration = Duration::from_millis(400);
/// The bundled local vision model (also what the backend asks Ollama for).
const LOCAL_MODEL: &str = "qwen3-vl:2b";

#[derive(Default)]
pub struct SidecarState {
    pub ollama_child: Mutex<Option<CommandChild>>,
    pub backend_child: Mutex<Option<CommandChild>>,
}

fn url_is_healthy(url: &str) -> bool {
    ureq::get(url).timeout(Duration::from_secs(2)).call().is_ok()
}

fn wait_until_healthy(url: &str, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if url_is_healthy(url) {
            return true;
        }
        std::thread::sleep(POLL_INTERVAL);
    }
    false
}

fn existing_ollama_has_local_model() -> bool {
    let resp = ureq::get(&format!("{OLLAMA_URL}/api/tags"))
        .timeout(Duration::from_secs(3))
        .call();
    match resp {
        Ok(response) => match response.into_json::<serde_json::Value>() {
            Ok(json) => json
                .get("models")
                .and_then(|m| m.as_array())
                .map(|models| {
                    models.iter().any(|m| {
                        m.get("name")
                            .and_then(|n| n.as_str())
                            .map(|n| n == LOCAL_MODEL)
                            .unwrap_or(false)
                    })
                })
                .unwrap_or(false),
            Err(_) => false,
        },
        Err(_) => false,
    }
}

fn try_pull_local_model_on_existing() {
    let _ = ureq::post(&format!("{OLLAMA_URL}/api/pull"))
        .timeout(Duration::from_secs(600))
        .send_json(serde_json::json!({ "name": LOCAL_MODEL, "stream": false }));
}

fn show_error_and_exit(app: &AppHandle, title: &str, message: &str) -> bool {
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Error)
        .buttons(MessageDialogButtons::OkCancelCustom("Retry".into(), "Quit".into()))
        .blocking_show()
}

/// Orchestrates startup of the AI engine (Ollama) and the forensic backend,
/// retrying on failure via a dialog rather than ever silently failing or
/// crashing. Runs on a dedicated background thread so the UI stays responsive.
pub fn start_services(app: AppHandle) {
    loop {
        match ensure_ollama_running(&app) {
            Ok(()) => break,
            Err(_) => {
                let retry = show_error_and_exit(
                    &app,
                    "AI Engine Unavailable",
                    "The Red Thread could not start its local AI vision engine (Ollama).\n\n\
                     If you have Ollama installed separately, make sure it can run on this \
                     machine. Otherwise this usually means antivirus or a security policy is \
                     blocking the bundled engine from starting.\n\n\
                     You can retry, or quit and check the log at:\n\
                     %APPDATA%\\RedThread\\logs\\",
                );
                if !retry {
                    app.exit(1);
                    return;
                }
            }
        }
    }

    loop {
        match ensure_backend_running(&app) {
            Ok(()) => break,
            Err(detail) => {
                let retry = show_error_and_exit(
                    &app,
                    "Forensic Engine Failed to Start",
                    &format!(
                        "The Red Thread's case-processing backend failed to start.\n\n{}\n\n\
                         You can retry, or quit and check the log at:\n%APPDATA%\\RedThread\\logs\\",
                        detail
                    ),
                );
                if !retry {
                    app.exit(1);
                    return;
                }
            }
        }
    }

    if let Some(splash) = app.get_webview_window("splashscreen") {
        let _ = splash.close();
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }
}

fn ensure_ollama_running(app: &AppHandle) -> Result<(), String> {
    if url_is_healthy(&format!("{OLLAMA_URL}/api/version")) {
        // Reuse whatever is already serving on the standard port (e.g. the
        // user's own system-wide Ollama install) rather than fighting it for
        // the port. We never spawn or manage a sidecar in this branch, so we
        // never kill the user's own instance on shutdown either.
        if !existing_ollama_has_local_model() {
            try_pull_local_model_on_existing();
        }
        return Ok(());
    }

    let state = app.state::<SidecarState>();
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Could not resolve resource directory: {e}"))?;
    let models_dir = resource_dir.join("resources").join("ollama_models");

    let (mut rx, child) = app
        .shell()
        .sidecar("ollama")
        .map_err(|e| format!("Bundled AI engine binary missing: {e}"))?
        .env("OLLAMA_MODELS", models_dir.to_string_lossy().to_string())
        .env("OLLAMA_HOST", "127.0.0.1:11434")
        .args(["serve"])
        .spawn()
        .map_err(|e| format!("Failed to launch bundled AI engine: {e}"))?;

    *state.ollama_child.lock().unwrap() = Some(child);

    std::thread::spawn(move || {
        while rx.blocking_recv().is_some() {
            // Drain stdout/stderr so the pipe never backs up; details go to
            // Ollama's own log file inside the bundle if ever needed.
        }
    });

    if wait_until_healthy(&format!("{OLLAMA_URL}/api/version"), STARTUP_TIMEOUT) {
        Ok(())
    } else {
        Err("The bundled AI engine did not respond in time.".to_string())
    }
}

fn ensure_backend_running(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<SidecarState>();

    let (mut rx, child) = app
        .shell()
        .sidecar("redthread-backend")
        .map_err(|e| format!("Backend binary missing: {e}"))?
        .spawn()
        .map_err(|e| format!("Failed to launch backend process: {e}"))?;

    *state.backend_child.lock().unwrap() = Some(child);

    let recent_lines = std::sync::Arc::new(Mutex::new(Vec::<String>::new()));
    let recent_lines_clone = recent_lines.clone();
    std::thread::spawn(move || {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.blocking_recv() {
            let line = match event {
                CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                    Some(String::from_utf8_lossy(&bytes).to_string())
                }
                _ => None,
            };
            if let Some(line) = line {
                let mut lines = recent_lines_clone.lock().unwrap();
                lines.push(line);
                if lines.len() > 40 {
                    lines.remove(0);
                }
            }
        }
    });

    if wait_until_healthy(&format!("{BACKEND_URL}/api/health"), STARTUP_TIMEOUT) {
        Ok(())
    } else {
        let tail = recent_lines.lock().unwrap().join("\n");
        Err(if tail.is_empty() {
            "The backend did not respond in time (no output captured).".to_string()
        } else {
            format!("The backend did not respond in time. Recent output:\n{tail}")
        })
    }
}

/// Kills a process and its full descendant tree. Needed because both
/// sidecars spawn children of their own at runtime: PyInstaller's --onefile
/// bootloader re-execs a child process to actually run the backend, and
/// Ollama spawns a separate llama-server child while a model is loaded.
/// CommandChild::kill() only terminates the direct child we spawned, which
/// would leave those grandchildren running as orphans — this does not.
#[cfg(target_os = "windows")]
fn kill_process_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .output();
}

#[cfg(not(target_os = "windows"))]
fn kill_process_tree(pid: u32) {
    // Best-effort on Unix: negative pid targets the process group, which
    // only works if the child was spawned as its own group leader. Falls
    // back to a direct kill of the known pid either way.
    let _ = std::process::Command::new("kill")
        .args(["-9", &format!("-{pid}")])
        .output();
    let _ = std::process::Command::new("kill")
        .args(["-9", &pid.to_string()])
        .output();
}

/// Kills any sidecar processes we actually spawned (and their full process
/// trees). Never touches a pre-existing system Ollama instance we merely
/// reused.
pub fn shutdown_services(app: &AppHandle) {
    let state = app.state::<SidecarState>();
    if let Some(child) = state.backend_child.lock().unwrap().take() {
        kill_process_tree(child.pid());
    }
    if let Some(child) = state.ollama_child.lock().unwrap().take() {
        kill_process_tree(child.pid());
    }
}
