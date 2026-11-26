//! The Harness desktop shell: a window over the app page the session host serves, a tray
//! icon that keeps it running with the window closed, and system notifications for the four
//! kinds of thing the owner must decide or know (approvals, the spending limit, failed or
//! unknown actions, an expired channel login).
//!
//! The shell holds no state of the agent. Everything goes through the bundled Python and the
//! host: `python -m harness.host.login page` starts or finds the host, `install` and
//! `uninstall` switch the login item, and the host's HTTP API pauses, resumes and stops.
//!
//!   the-harness                     open the window (start the host when none runs)
//!   the-harness URL                 open the window on URL (harness app)
//!   the-harness --overlay URL       the timeline overlay window on URL
//!   the-harness --focus             raise the running window; exit 1 when none runs
//!   the-harness --host              the login item: the session host, waited for, plus the
//!                                   tray when there is a display
//!   the-harness --autostart on|off|default
//!                                   switch the login item (default: on unless the
//!                                   installer's default was applied before) and exit
//!   the-harness --stop-host         ask the host to stop (installers, before replacing files)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_notification::NotificationExt;

const POLL: Duration = Duration::from_secs(5);
const LOGIN_CHECK: Duration = Duration::from_secs(60);
const UPDATE_CHECK: Duration = Duration::from_secs(6 * 60 * 60);
const KINDS: [&str; 4] = ["approval", "limit", "failed", "login"];

/// What the shell shares between the tray, the poller and the window.
#[derive(Default)]
struct Shared {
    paused: bool,
    autostart: bool,
    last_notification: Option<Value>,
    started_host: bool,
    host_child: Option<Child>,
}

type State = Arc<Mutex<Shared>>;

// -- the bundled Python and the harness ----------------------------------------------------

/// The folder installers put next to the shell: runtime/python (python-build-standalone with
/// the Harness wheel) and runtime/packages (package folders installed on first start).
fn runtime_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let candidates = [
        dir.join("runtime"),                                  // Windows, an AppImage's usr/bin
        dir.join("../Resources/runtime"),                     // macOS .app
        dir.join("../lib/The Harness/runtime"),               // .deb (/usr/bin -> /usr/lib/<product>)
        dir.join("../lib/the-harness/runtime"),
    ];
    candidates.into_iter().find(|path| path.join("python").is_dir())
}

/// The Python that runs the harness: $HARNESS_PYTHON, else the bundled one, else python3 or
/// python on PATH (a developer's pip install).
fn python() -> PathBuf {
    if let Ok(given) = std::env::var("HARNESS_PYTHON") {
        if !given.is_empty() {
            return PathBuf::from(given);
        }
    }
    if let Some(runtime) = runtime_dir() {
        let python = runtime.join("python");
        let found = if cfg!(windows) { python.join("python.exe") } else { python.join("bin").join("python3") };
        if found.is_file() {
            return found;
        }
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

/// What the login item runs: this shell with --host (an AppImage: the AppImage itself, since
/// its files move each time it mounts).
fn launcher() -> String {
    let exe = std::env::var("APPIMAGE")
        .ok()
        .filter(|path| !path.is_empty())
        .map(PathBuf::from)
        .or_else(|| std::env::current_exe().ok())
        .unwrap_or_else(|| PathBuf::from("the-harness"));
    serde_json::to_string(&[exe.to_string_lossy().to_string(), "--host".to_string()]).unwrap()
}

fn harness(args: &[&str]) -> Command {
    let mut command = Command::new(python());
    command
        .args(args)
        .env("HARNESS_HOST_COMMAND", launcher())
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    command
}

/// `python -m harness.host.login ARGS`: its standard output, or the error it gave.
fn login(args: &[&str]) -> Result<String, String> {
    let mut words = vec!["-m", "harness.host.login"];
    words.extend_from_slice(args);
    let output = harness(&words).output().map_err(|error| format!("{}: {error}", python().display()))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

/// The user's data folder ($HARNESS_DATA, default ~/.harness), as the harness has it.
fn data_dir() -> PathBuf {
    if let Ok(given) = std::env::var("HARNESS_DATA") {
        if !given.is_empty() {
            return PathBuf::from(given);
        }
    }
    let home = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE")).unwrap_or_else(|_| ".".into());
    PathBuf::from(home).join(".harness")
}

/// Install the package folders the installer brought (agent, app) once per version; the
/// harness copies each into the user's packages.
fn install_bundled_packages() {
    let Some(runtime) = runtime_dir() else { return };
    let Ok(entries) = std::fs::read_dir(runtime.join("packages")) else { return };
    let done = data_dir().join("host").join("shell-packages");
    let _ = std::fs::create_dir_all(&done);
    for entry in entries.flatten() {
        let folder = entry.path();
        let Ok(manifest) = std::fs::read_to_string(folder.join("package.toml")) else { continue };
        let version = manifest
            .lines()
            .find_map(|line| line.trim().strip_prefix("version"))
            .and_then(|rest| rest.split('"').nth(1))
            .unwrap_or("0");
        let name = entry.file_name().to_string_lossy().to_string();
        let marker = done.join(format!("{name}-{version}"));
        if marker.exists() {
            continue;
        }
        let path = folder.to_string_lossy().to_string();
        match harness(&["-m", "harness", "install", &path, "--yes"]).output() {
            Ok(output) if output.status.success() => {
                let _ = std::fs::write(&marker, b"");
            }
            Ok(output) => eprintln!("harness install {name}: {}", String::from_utf8_lossy(&output.stderr)),
            Err(error) => eprintln!("harness install {name}: {error}"),
        }
    }
}

/// --autostart default: on, the first time only (as Ollama's installer does); after that the
/// login item stays as the user left it.
fn autostart(choice: &str) -> i32 {
    let marker = data_dir().join("host").join("shell-autostart-default");
    let words: &[&str] = match choice {
        "on" => &["install"],
        "off" => &["uninstall"],
        "default" if marker.exists() => return 0,
        "default" => &["install"],
        _ => {
            eprintln!("--autostart on, off or default");
            return 2;
        }
    };
    match login(words) {
        Ok(text) => {
            print!("{text}");
            if choice == "default" {
                let _ = std::fs::create_dir_all(marker.parent().unwrap());
                let _ = std::fs::write(&marker, b"");
            }
            0
        }
        Err(error) => {
            eprintln!("{error}");
            1
        }
    }
}

// -- the host's HTTP API -------------------------------------------------------------------

/// The running host's address and session key (DATA/host/host.json), never starting one.
fn address() -> Option<(String, String)> {
    let text = std::fs::read_to_string(data_dir().join("host").join("host.json")).ok()?;
    let found: Value = serde_json::from_str(&text).ok()?;
    Some((found["url"].as_str()?.to_string(), found["token"].as_str()?.to_string()))
}

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new().timeout(Duration::from_secs(10)).build()
}

fn get(path: &str) -> Option<Value> {
    let (url, token) = address()?;
    agent().get(&format!("{url}{path}")).set("X-Session-API-Key", &token).call().ok()?.into_json().ok()
}

fn post(path: &str, body: Value) -> Result<Value, String> {
    let (url, token) = address().ok_or("the session host is not running")?;
    agent()
        .post(&format!("{url}{path}"))
        .set("X-Session-API-Key", &token)
        .send_json(body)
        .map_err(|error| error.to_string())?
        .into_json()
        .map_err(|error| error.to_string())
}

/// The app page (starting the host when none runs, as harness does).
fn page() -> Result<Url, String> {
    let text = login(&["page"])?;
    let found: Value = serde_json::from_str(text.trim()).map_err(|error| error.to_string())?;
    let page = found["page"].as_str().ok_or("no page in the host's answer")?;
    Url::parse(page).map_err(|error| error.to_string())
}

// -- windows -------------------------------------------------------------------------------

fn main_window(app: &AppHandle) -> WebviewWindow {
    if let Some(window) = app.get_webview_window("main") {
        return window;
    }
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("The Harness")
        .inner_size(1200.0, 800.0)
        .min_inner_size(380.0, 480.0)
        .build()
        .expect("the main window")
}

/// Show the window on `url`, or on the host's page (found or started off the UI thread).
fn open(app: &AppHandle, url: Option<Url>) {
    let window = main_window(app);
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
    let app = app.clone();
    thread::spawn(move || {
        install_bundled_packages();
        let target = match url {
            Some(url) => Ok(url),
            None => page(),
        };
        match target {
            Ok(url) => {
                if let Some(window) = app.get_webview_window("main") {
                    let showing = window.url().map(|now| now.origin() == url.origin()).unwrap_or(false);
                    if !showing {
                        let _ = window.navigate(url);
                    }
                }
            }
            Err(error) => {
                let _ = app.notification().builder().title("The Harness").body(format!("The session host did not start: {error}")).show();
            }
        }
    });
}

/// The timeline overlay: a small window on top in a corner of the screen, which mouse
/// clicks pass through unless click_through=false (overlay.py's options, in the address).
fn overlay(app: &AppHandle, url: Url) {
    let query: std::collections::HashMap<String, String> = url.query_pairs().into_owned().collect();
    let number = |key: &str, default: f64| query.get(key).and_then(|v| v.parse::<f64>().ok()).unwrap_or(default);
    let (width, height) = (number("width", 560.0), number("height", 210.0));
    let corner = query.get("corner").cloned().unwrap_or_else(|| "bottom-right".into());
    let through = query.get("click_through").map(|v| v != "false").unwrap_or(true);
    if let Some(old) = app.get_webview_window("overlay") {
        let _ = old.close();
    }
    let Ok(window) = WebviewWindowBuilder::new(app, "overlay", WebviewUrl::External(url))
        .title("The Harness timeline")
        .inner_size(width, height)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .focused(false)
        .build()
    else {
        return;
    };
    if let Ok(Some(monitor)) = window.primary_monitor() {
        let scale = monitor.scale_factor();
        let size = monitor.size().to_logical::<f64>(scale);
        let margin = 16.0;
        let x = if corner.ends_with("left") { margin } else { size.width - width - margin };
        let y = if corner.starts_with("top") { margin + 24.0 } else { size.height - height - margin - 48.0 };
        let _ = window.set_position(tauri::LogicalPosition::new(x, y));
    }
    let _ = window.set_ignore_cursor_events(through);
}

/// A second start of the shell (harness app, a click on its icon): its arguments, here.
fn handle(app: &AppHandle, args: &[String]) {
    let url = args.iter().skip(1).find_map(|word| Url::parse(word).ok().filter(|u| u.scheme().starts_with("http")));
    if args.iter().any(|word| word == "--overlay") {
        if let Some(url) = url {
            overlay(app, url);
        }
        return;
    }
    if args.iter().any(|word| word == "--host" || word == "--autostart" || word == "--stop-host") {
        return;
    }
    open(app, url);
}

// -- the tray ------------------------------------------------------------------------------

fn tray(app: &AppHandle, state: State) -> tauri::Result<()> {
    let open_item = MenuItem::with_id(app, "open", "Open The Harness", true, None::<&str>)?;
    let pause_item = MenuItem::with_id(app, "pause", "Pause", true, None::<&str>)?;
    let login_item = CheckMenuItem::with_id(app, "login", "Start at login", true, false, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open_item, &pause_item, &login_item, &separator, &quit_item])?;
    let menu_state = state.clone();
    let (pause_menu, login_menu) = (pause_item.clone(), login_item.clone());
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("an icon"))
        .tooltip("The Harness")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "open" => open(app, None),
            "pause" => {
                let paused = menu_state.lock().unwrap().paused;
                let route = if paused { "/api/agent/resume" } else { "/api/agent/pause" };
                if post(route, serde_json::json!({})).is_ok() {
                    menu_state.lock().unwrap().paused = !paused;
                    let _ = pause_menu.set_text(if paused { "Pause" } else { "Resume" });
                }
            }
            "login" => {
                let wanted = !menu_state.lock().unwrap().autostart;
                let state = menu_state.clone();
                let item = login_menu.clone();
                thread::spawn(move || {
                    let _ = login(&[if wanted { "install" } else { "uninstall" }]);
                    refresh_login(&state, &item);
                });
            }
            "quit" => {
                // Quitting the host: what runs in it ends as cancelled or unknown, then it stops.
                let _ = post("/api/host/stop", serde_json::json!({"force": true}));
                if let Some(mut child) = menu_state.lock().unwrap().host_child.take() {
                    let _ = child.wait_timeout_or_kill(Duration::from_secs(30));
                }
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                open(tray.app_handle(), None);
            }
        })
        .build(app)?;

    // The poller: pause state, notifications, the login item, updates.
    let app = app.clone();
    thread::spawn(move || poll(app, state, pause_item, login_item));
    Ok(())
}

/// The login item as the system has it (`harness host status`), into the tray's check mark.
fn refresh_login(state: &State, item: &CheckMenuItem<tauri::Wry>) {
    if let Ok(text) = login(&["status", "--json"]) {
        if let Ok(found) = serde_json::from_str::<Value>(text.trim()) {
            let on = found["on"].as_bool().unwrap_or(false);
            state.lock().unwrap().autostart = on;
            let _ = item.set_checked(on);
        }
    }
}

fn poll(app: AppHandle, state: State, pause_item: MenuItem<tauri::Wry>, login_item: CheckMenuItem<tauri::Wry>) {
    let mut last_login = Instant::now() - LOGIN_CHECK;
    let mut last_update = Instant::now() - UPDATE_CHECK + Duration::from_secs(60);
    let mut first = true;
    loop {
        if let Some(life) = get("/api/agent/life") {
            let paused = life["paused"].as_bool().unwrap_or(false);
            let changed = {
                let mut shared = state.lock().unwrap();
                let changed = shared.paused != paused;
                shared.paused = paused;
                changed
            };
            if changed {
                let _ = pause_item.set_text(if paused { "Resume" } else { "Pause" });
            }
        }
        notify(&app, &state, first);
        first = false;
        if last_login.elapsed() >= LOGIN_CHECK {
            refresh_login(&state, &login_item);
            last_login = Instant::now();
        }
        if last_update.elapsed() >= UPDATE_CHECK {
            last_update = Instant::now();
            update(&app);
        }
        thread::sleep(POLL);
    }
}

/// New notifications of the four kinds, as system notifications while the window is not in
/// front. The first look only marks where to start, unless this shell started the host.
fn notify(app: &AppHandle, state: &State, first: bool) {
    let after = state.lock().unwrap().last_notification.clone();
    let query = match &after {
        Some(Value::Number(n)) => format!("?after={n}"),
        Some(Value::String(s)) => format!("?after={s}"),
        _ => String::new(),
    };
    let Some(answer) = get(&format!("/api/agent/notifications{query}")) else { return };
    let rows = match &answer {
        Value::Array(rows) => rows.clone(),
        other => other["notifications"].as_array().cloned().unwrap_or_default(),
    };
    let silent = first && !state.lock().unwrap().started_host;
    let in_front = app
        .get_webview_window("main")
        .map(|w| w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false))
        .unwrap_or(false);
    for row in &rows {
        if let Some(id) = row.get("id") {
            state.lock().unwrap().last_notification = Some(id.clone());
        }
        let kind = row["kind"].as_str().unwrap_or("");
        if silent || in_front || !KINDS.contains(&kind) {
            continue;
        }
        let title = row["title"].as_str().unwrap_or("The Harness");
        let body = row["body"].as_str().unwrap_or("");
        let _ = app.notification().builder().title(title).body(body).show();
    }
}

/// The shell's own update, from GitHub Releases, checked against the updater key (not code
/// signing). The host is stopped first so the installer can replace the bundled runtime; while
/// work runs in it (it refuses to stop) the update waits for the next check.
fn update(app: &AppHandle) {
    let configured = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|updater| updater["pubkey"].as_str())
        .map(|key| !key.trim().is_empty())
        .unwrap_or(false);
    if !configured {
        return;
    }
    use tauri_plugin_updater::UpdaterExt;
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let Ok(updater) = app.updater() else { return };
        let Ok(Some(found)) = updater.check().await else { return };
        if address().is_some() && post("/api/host/stop", serde_json::json!({"force": false})).is_err() {
            return;
        }
        if found.download_and_install(|_, _| {}, || {}).await.is_ok() {
            app.restart();
        }
    });
}

// -- the login item's process --------------------------------------------------------------

/// `python -m harness.host.login run`: the session host, waited for.
fn host_child() -> std::io::Result<Child> {
    let mut words = vec!["-m".to_string(), "harness.host.login".to_string(), "run".to_string()];
    words.extend(std::env::args().skip_while(|word| word != "--host").skip(1));
    let words: Vec<&str> = words.iter().map(String::as_str).collect();
    harness(&words).stdout(Stdio::null()).stderr(Stdio::null()).spawn()
}

fn has_display() -> bool {
    if cfg!(target_os = "linux") {
        std::env::var_os("DISPLAY").is_some() || std::env::var_os("WAYLAND_DISPLAY").is_some()
    } else {
        true
    }
}

trait WaitTimeout {
    fn wait_timeout_or_kill(&mut self, limit: Duration) -> std::io::Result<()>;
}

impl WaitTimeout for Child {
    fn wait_timeout_or_kill(&mut self, limit: Duration) -> std::io::Result<()> {
        let began = Instant::now();
        while began.elapsed() < limit {
            if self.try_wait()?.is_some() {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(200));
        }
        self.kill()
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let flag = |name: &str| args.iter().position(|word| word == name);
    if let Some(at) = flag("--autostart") {
        std::process::exit(autostart(args.get(at + 1).map(String::as_str).unwrap_or("default")));
    }
    if flag("--stop-host").is_some() {
        let _ = post("/api/host/stop", serde_json::json!({"force": true}));
        std::process::exit(0);
    }
    let host_mode = flag("--host").is_some();
    if host_mode && !has_display() {
        // A server without a display: the host alone, as the login item's process.
        install_bundled_packages();
        let code = host_child().and_then(|mut child| child.wait()).map(|status| status.code().unwrap_or(1));
        std::process::exit(code.unwrap_or(1));
    }

    let state: State = Arc::new(Mutex::new(Shared::default()));
    let setup_state = state.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if argv.iter().any(|word| word == "--focus") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                return;
            }
            handle(app, &argv);
        }))
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(move |app| {
            let args: Vec<String> = std::env::args().collect();
            if args.iter().any(|word| word == "--focus") {
                // No shell was running: nothing to raise.
                std::process::exit(1);
            }
            let handle_ = app.handle().clone();
            if host_mode {
                install_bundled_packages();
                match host_child() {
                    Ok(child) => {
                        let mut shared = setup_state.lock().unwrap();
                        shared.host_child = Some(child);
                        shared.started_host = true;
                    }
                    Err(error) => eprintln!("the session host: {error}"),
                }
            } else {
                // The installer's default, the first time the shell starts (an .msi has no hook).
                thread::spawn(|| {
                    let _ = autostart("default");
                });
                handle(&handle_, &args);
            }
            tray(&handle_, setup_state.clone())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window keeps the shell, and the agent, running in the tray.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("the desktop shell");

    app.run(move |_app, event| match event {
        // Only Quit (an explicit exit code) ends the shell; no open window is not a reason.
        RunEvent::ExitRequested { api, code: None, .. } => api.prevent_exit(),
        RunEvent::Exit => {
            if let Some(mut child) = state.lock().unwrap().host_child.take() {
                let _ = child.wait_timeout_or_kill(Duration::from_secs(30));
            }
        }
        _ => {}
    });
}

