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
//!   the-harness --focus             raise the running window; exit 1 when none runs
//!   the-harness --host              the login item: the session host, waited for, plus the
//!                                   tray when there is a display
//!   the-harness --autostart on|off|default
//!                                   switch the login item (default: on unless the
//!                                   installer's default was applied before) and exit
//!   the-harness --stop-host         ask the host to stop (installers, before replacing files)
//!
//! Its own update (the Tauri updater, checked against the updater key): by app.update it checks
//! at start and every hour (default), at start only (start), when asked (manual) or never
//! (none), and downloads and verifies the update in the background. Nothing installs or
//! restarts until the owner clicks Restart to update (the page's button through
//! /api/app/update, or the tray); then it waits while the agent is at work unless the owner
//! chose to interrupt, stops the host, installs, restarts and reopens the chat that was open.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::Value;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent, Wry};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_updater::UpdaterExt;

const POLL: Duration = Duration::from_secs(5);
const LOGIN_CHECK: Duration = Duration::from_secs(60);
// The update's report to the host (and the owner's requests back), and how often it checks.
const UPDATE_TICK: Duration = Duration::from_secs(1);
const UPDATE_EVERY: Duration = Duration::from_secs(60 * 60);
// DATA/host/<REOPEN>: what to reopen after the restart of an update.
const REOPEN: &str = "shell-reopen.json";
const KINDS: [&str; 4] = ["approval", "limit", "failed", "login"];

/// What the shell shares between the tray, the poller and the window.
#[derive(Default)]
struct Shared {
    paused: bool,
    autostart: bool,
    last_notification: Option<Value>,
    started_host: bool,
    host_child: Option<Child>,
    update: Upd,
    /// The chat and view to reopen, read once at start after an update's restart.
    reopen: Option<Value>,
}

/// The shell's own update: where it is, and the verified bundle once downloaded.
#[derive(Default)]
struct Upd {
    phase: String, // "", checking, downloading, ready, latest, installing, error, off
    version: Option<String>,
    notes: Option<String>,
    got: u64,
    total: Option<u64>,
    error: Option<String>,
    checked: Option<u64>,
    found: Option<tauri_plugin_updater::Update>,
    bytes: Option<Vec<u8>>,
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
    if std::env::var_os("APPIMAGE").is_some() {
        // An AppImage's AppRun sets PYTHONHOME and PYTHONPATH to its own usr/, where the bundled
        // Python finds no standard library ("No module named 'encodings'").
        command.env_remove("PYTHONHOME").env_remove("PYTHONPATH");
    }
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

/// A short digest of a bundled package folder's files (names and bytes), so a new build of
/// a package with the same version is installed again.
fn folder_digest(folder: &std::path::Path) -> String {
    use std::hash::{Hash, Hasher};
    let mut files = Vec::new();
    let mut stack = vec![folder.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else { continue };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if path.file_name().map(|n| n != "__pycache__").unwrap_or(true) {
                    stack.push(path);
                }
            } else {
                files.push(path);
            }
        }
    }
    files.sort();
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    for path in files {
        path.strip_prefix(folder).unwrap_or(&path).to_string_lossy().hash(&mut hasher);
        std::fs::read(&path).unwrap_or_default().hash(&mut hasher);
    }
    format!("{:016x}", hasher.finish())
}

/// A line in the shell's log (DATA/logs/shell.log), where a failed first start is told.
fn log(line: &str) {
    use std::io::Write;
    let folder = data_dir().join("logs");
    let _ = std::fs::create_dir_all(&folder);
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(folder.join("shell.log")) {
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let _ = writeln!(file, "{now} {line}");
    }
}

/// Install the package folders the installer brought (agent, app and the first-use ones:
/// workspace, computer, browser, qq), each time a folder's content is new; the harness copies
/// each into the user's packages and replaces an older or stale one. What failed: (name,
/// the harness's own words), also logged to DATA/logs/shell.log.
fn install_bundled_packages() -> Vec<(String, String)> {
    let mut failed = Vec::new();
    let Some(runtime) = runtime_dir() else { return failed };
    let Ok(entries) = std::fs::read_dir(runtime.join("packages")) else { return failed };
    let done = data_dir().join("host").join("shell-packages");
    let _ = std::fs::create_dir_all(&done);
    let mut folders: Vec<_> = entries.flatten().map(|entry| entry.path()).filter(|p| p.join("package.toml").is_file()).collect();
    // The agent and the app first: the window needs them; the others when they are used.
    folders.sort_by_key(|p| match p.file_name().and_then(|n| n.to_str()) { Some("agent") => 0, Some("app") => 1, _ => 2 });
    for folder in folders {
        let name = folder.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
        let marker = done.join(format!("{name}-{}", folder_digest(&folder)));
        if marker.exists() {
            continue;
        }
        let path = folder.to_string_lossy().to_string();
        match harness(&["-m", "harness", "install", &path, "--yes"]).output() {
            Ok(output) if output.status.success() => {
                let _ = std::fs::write(&marker, b"");
                log(&format!("installed {name} from {path}"));
            }
            Ok(output) => {
                let said = format!("{}{}", String::from_utf8_lossy(&output.stderr), String::from_utf8_lossy(&output.stdout));
                log(&format!("harness install {name} failed: {}", said.trim()));
                failed.push((name, said.trim().to_string()));
            }
            Err(error) => {
                log(&format!("harness install {name} failed: {error}"));
                failed.push((name, error.to_string()));
            }
        }
    }
    failed
}

/// Tell the start page what failed (it shows it in the app's own look), instead of opening a
/// host page that has no app to show.
fn show_failure(app: &AppHandle, failed: &[(String, String)]) {
    let rows: Vec<String> = failed
        .iter()
        .map(|(name, said)| format!("{{\"name\":{},\"said\":{}}}", json_string(name), json_string(said)))
        .collect();
    let log_path = data_dir().join("logs").join("shell.log");
    let script = format!(
        "window.__failure = {{\"packages\":[{}],\"log\":{},\"retry\":{}}}; window.showFailure && window.showFailure(window.__failure);",
        rows.join(","),
        json_string(&log_path.to_string_lossy()),
        json_string(&format!("\"{}\" -m harness install <the folder above> --yes", python().display()))
    );
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(&script);
    }
}

fn json_string(text: &str) -> String {
    let mut out = String::from("\"");
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => {}
            c if (c as u32) < 0x20 => out.push(' '),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// After an update: the installed packages to the newest version in their range that works with
/// the new harness (harness install --update; the bundled ones follow their content above).
fn upgrade_installed() {
    match harness(&["-m", "harness", "install", "--update"]).output() {
        Ok(output) if !output.status.success() => {
            eprintln!("harness install --update: {}", String::from_utf8_lossy(&output.stderr))
        }
        Err(error) => eprintln!("harness install --update: {error}"),
        _ => {}
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
    // After an update's restart: the chat or view that was open.
    let reopen = app.try_state::<State>().and_then(|state| state.lock().unwrap().reopen.take());
    let app = app.clone();
    thread::spawn(move || {
        if reopen.is_some() {
            upgrade_installed();
        }
        let failed = install_bundled_packages();
        if failed.iter().any(|(name, _)| name == "agent" || name == "app") {
            show_failure(&app, &failed);
            return;
        }
        let target = match url {
            Some(url) => Ok(url),
            None => page(),
        };
        match target {
            Ok(mut url) => {
                if let Some(reopen) = &reopen {
                    for key in ["chat", "view"] {
                        if let Some(value) = reopen[key].as_str().filter(|value| !value.is_empty()) {
                            url.query_pairs_mut().append_pair(key, value);
                        }
                    }
                }
                if let Some(window) = app.get_webview_window("main") {
                    let showing = window.url().map(|now| now.origin() == url.origin()).unwrap_or(false);
                    if !showing || reopen.is_some() {
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

/// A second start of the shell (harness app, a click on its icon): its arguments, here.
fn handle(app: &AppHandle, args: &[String]) {
    let url = args.iter().skip(1).find_map(|word| Url::parse(word).ok().filter(|u| u.scheme().starts_with("http")));
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
    let update_menu = menu.clone();
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("an icon"))
        .tooltip("The Harness")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "open" => open(app, None),
            "update" => {
                // As the page's button: the host holds the request until nothing is at work, and
                // the window shows what it waits for and offers to interrupt.
                let _ = post("/api/app/update", serde_json::json!({"action": "restart"}));
                open(app, None);
            }
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
    let update_app = app.clone();
    let update_state = state.clone();
    thread::spawn(move || updates(update_app, update_state, update_menu));
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

// -- its own update ------------------------------------------------------------------------

/// Whether this build has the updater's public key (build.py puts it in; without it there are
/// no update bundles to verify, so nothing is checked).
fn configured(app: &AppHandle) -> bool {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|updater| updater["pubkey"].as_str())
        .map(|key| !key.trim().is_empty())
        .unwrap_or(false)
}

fn now_seconds() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|time| time.as_secs()).unwrap_or(0)
}

/// What the shell tells the host (and the page shows) of its update.
fn report(app: &AppHandle, update: &Upd) -> Value {
    serde_json::json!({
        "phase": update.phase, "version": update.version, "notes": update.notes,
        "current": app.package_info().version.to_string(), "got": update.got, "total": update.total,
        "error": update.error, "checked": update.checked, "os": std::env::consts::OS,
        "configured": configured(app),
    })
}

/// The tray's item while an update is ready. Windows: the installer closes the app for a
/// moment, so the item says so before the click.
fn restart_label(version: &str) -> String {
    if cfg!(windows) {
        format!("Restart to update to {version} (it closes briefly to install)")
    } else {
        format!("Restart to update to {version}")
    }
}

/// The update's loop: report to the host each second and take the owner's requests; check by
/// app.update (the host's answer: default at start and every hour, start at start only, manual
/// when asked, none never); keep the tray's item while an update is ready.
fn updates(app: AppHandle, state: State, menu: Menu<Wry>) {
    let item = MenuItem::with_id(&app, "update", "Restart to update", true, None::<&str>).expect("the update item");
    let mut shown = false;
    let mut last_check: Option<Instant> = None;
    loop {
        let state_now = report(&app, &state.lock().unwrap().update);
        if let Ok(answer) = post("/api/app/update", serde_json::json!({"action": "shell", "state": state_now})) {
            let mode = answer["mode"].as_str().unwrap_or("default").to_string();
            let asked = answer["requests"].as_array().map(|rows| rows.iter().any(|row| row == "check")).unwrap_or(false);
            let due = match mode.as_str() {
                "default" => last_check.map(|time| time.elapsed() >= UPDATE_EVERY).unwrap_or(true),
                "start" => last_check.is_none(),
                _ => false,
            };
            if mode != "none" && (asked || due) {
                last_check = Some(Instant::now());
                check(&app, &state);
            }
            if answer["restart"].is_object() {
                restart(&app, &state, &answer["restart"]);
            }
        }
        let ready = {
            let shared = state.lock().unwrap();
            (shared.update.phase == "ready").then(|| shared.update.version.clone().unwrap_or_default())
        };
        match (ready, shown) {
            (Some(version), false) => {
                let _ = item.set_text(restart_label(&version));
                shown = menu.insert(&item, 1).is_ok();
            }
            (None, true) => {
                let _ = menu.remove(&item);
                shown = false;
            }
            _ => {}
        }
        thread::sleep(UPDATE_TICK);
    }
}

/// Check, and when there is an update download it and verify its signature (Update::download
/// checks it against the updater key): it is then ready, and nothing more happens until the
/// owner clicks Restart to update.
fn check(app: &AppHandle, state: &State) {
    {
        let mut shared = state.lock().unwrap();
        let update = &mut shared.update;
        if matches!(update.phase.as_str(), "checking" | "downloading" | "ready" | "installing") {
            return;
        }
        if !configured(app) {
            update.phase = "off".into();
            update.error = Some("this build has no updater key".into());
            return;
        }
        update.phase = "checking".into();
        update.error = None;
    }
    let app = app.clone();
    let state = state.clone();
    tauri::async_runtime::spawn(async move {
        let result: Result<bool, String> = async {
            let updater = app.updater().map_err(|error| error.to_string())?;
            let Some(found) = updater.check().await.map_err(|error| error.to_string())? else { return Ok(false) };
            {
                let mut shared = state.lock().unwrap();
                let update = &mut shared.update;
                update.phase = "downloading".into();
                update.version = Some(found.version.clone());
                update.notes = found.body.clone();
                update.got = 0;
                update.total = None;
            }
            let progress = state.clone();
            let bytes = found
                .download(
                    move |chunk, total| {
                        let mut shared = progress.lock().unwrap();
                        shared.update.got += chunk as u64;
                        shared.update.total = total;
                    },
                    || {},
                )
                .await
                .map_err(|error| error.to_string())?;
            let mut shared = state.lock().unwrap();
            shared.update.found = Some(found);
            shared.update.bytes = Some(bytes);
            Ok(true)
        }
        .await;
        let mut shared = state.lock().unwrap();
        let update = &mut shared.update;
        update.checked = Some(now_seconds());
        match result {
            Ok(true) => update.phase = "ready".into(),
            Ok(false) => update.phase = "latest".into(),
            Err(error) => {
                eprintln!("update: {error}");
                update.phase = "error".into();
                update.error = Some(error);
                update.found = None;
                update.bytes = None;
            }
        }
    });
}

/// The owner's Restart to update, handed over by the host once nothing is at work (or the
/// owner chose to interrupt): keep what to reopen, stop the host, install, restart.
fn restart(app: &AppHandle, state: &State, request: &Value) {
    let (found, bytes, host_mode) = {
        let mut shared = state.lock().unwrap();
        if shared.update.phase != "ready" {
            return;
        }
        shared.update.phase = "installing".into();
        (shared.update.found.clone(), shared.update.bytes.take(), shared.started_host)
    };
    let (Some(found), Some(bytes)) = (found, bytes) else { return };
    let window = app.get_webview_window("main").map(|w| w.is_visible().unwrap_or(false)).unwrap_or(false);
    let reopen = data_dir().join("host").join(REOPEN);
    let record = serde_json::json!({
        "chat": request["chat"], "view": request["view"], "window": window,
        "from": app.package_info().version.to_string(), "to": found.version,
    });
    let _ = std::fs::create_dir_all(data_dir().join("host"));
    let _ = std::fs::write(&reopen, record.to_string());
    if address().is_some() {
        let interrupt = request["interrupt"].as_bool().unwrap_or(false);
        if let Err(error) = post("/api/host/stop", serde_json::json!({"force": interrupt})) {
            // Work started in between: it stays ready, and the click can come again.
            let mut shared = state.lock().unwrap();
            shared.update.phase = "ready".into();
            shared.update.bytes = Some(bytes);
            shared.update.error = Some(format!("the host did not stop: {error}"));
            let _ = std::fs::remove_file(&reopen);
            return;
        }
    }
    // The host runs from the files the update replaces: wait for it to end.
    let child = state.lock().unwrap().host_child.take();
    if let Some(mut child) = child {
        let _ = child.wait_timeout_or_kill(Duration::from_secs(30));
    } else {
        let file = data_dir().join("host").join("host.json");
        let began = Instant::now();
        while file.exists() && began.elapsed() < Duration::from_secs(30) {
            thread::sleep(Duration::from_millis(200));
        }
    }
    // Windows: install() starts the installer, which closes this app and opens the new one.
    match found.install(&bytes) {
        Ok(()) => app.restart(),
        Err(error) => {
            eprintln!("update: {error}");
            let _ = std::fs::remove_file(&reopen);
            {
                let mut shared = state.lock().unwrap();
                shared.update.phase = "error".into();
                shared.update.error = Some(error.to_string());
                shared.update.found = None;
            }
            // The old version goes on, with its host again.
            if host_mode {
                if let Ok(child) = host_child() {
                    state.lock().unwrap().host_child = Some(child);
                }
            } else {
                let _ = login(&["page"]);
            }
        }
    }
}

/// What an update's restart asked to reopen (read once, then removed).
fn take_reopen() -> Option<Value> {
    let path = data_dir().join("host").join(REOPEN);
    let text = std::fs::read_to_string(&path).ok()?;
    let _ = std::fs::remove_file(&path);
    serde_json::from_str(&text).ok()
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
        if take_reopen().is_some() {
            upgrade_installed();
        }
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
            app.manage(setup_state.clone());
            let reopen = take_reopen();
            let window = reopen.as_ref().map(|r| r["window"].as_bool().unwrap_or(false)).unwrap_or(false);
            if reopen.is_some() && host_mode && !window {
                thread::spawn(upgrade_installed);
            }
            setup_state.lock().unwrap().reopen = reopen;
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
                if window {
                    // An update's restart from an open window: open it again, on its chat.
                    open(&handle_, None);
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

