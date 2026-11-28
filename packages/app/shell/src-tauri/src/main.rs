//! The Harness desktop shell: a window over the app page the session host serves, a tray
//! icon that keeps it running with the window closed, and system notifications for the four
//! kinds of thing the owner must decide or know (approvals, the spending limit, failed or
//! unknown actions, an expired channel login).
//!
//! The shell holds no state of the agent. Everything goes through the bundled Python and the
//! host: `python -m harness.host.login page` starts or finds the host, `install` and
//! `uninstall` switch the login item, and the host's HTTP API pauses, resumes and stops.
//!
//! A start that fails is said in the window: the start page (frontend/index.html) shows the
//! reason, the fix and the log the harness gave, with Try again and Open the log. The login
//! item's host has no window, so a failure of it is a system notification, and the window
//! starts it again when it next opens. The shell's own words (the tray, its notifications)
//! are Chinese or English by the page's language (general.language, else the system's).
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
//!   the-harness --path on|off|status [--report FILE]
//!                                   the `harness` command for terminals: on the PATH, off
//!                                   it, or which one a new terminal runs (installers), and exit
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
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::Value;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::webview::NewWindowResponse;
use tauri::{
    AppHandle, LogicalPosition, LogicalSize, Manager, PhysicalPosition, PhysicalSize, Position,
    Rect, RunEvent, Size, Url, WebviewBuilder, WebviewUrl, WebviewWindowBuilder, Window,
    WindowEvent, Wry,
};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_updater::UpdaterExt;

const POLL: Duration = Duration::from_secs(5);
const LOGIN_CHECK: Duration = Duration::from_secs(60);
// The update's report to the host (and the owner's requests back), and how often it checks.
const UPDATE_TICK: Duration = Duration::from_secs(1);
const UPDATE_EVERY: Duration = Duration::from_secs(60 * 60);
const UPDATE_EVERY_DEV: Duration = Duration::from_secs(10 * 60);
const PRE_INSTALL_CHECK_TIMEOUT: Duration = Duration::from_secs(6);
// DATA/host/<REOPEN>: what to reopen after the restart of an update.
const REOPEN: &str = "shell-reopen.json";
const BROWSER_WEBVIEW: &str = "browser";
const KINDS: [&str; 4] = ["approval", "limit", "failed", "login"];

/// What the shell shares between the tray, the poller and the window.
#[derive(Default)]
struct Shared {
    paused: bool,
    autostart: bool,
    /// macOS: the `harness` command is linked on the PATH (the tray's item says which way it goes).
    command: bool,
    last_notification: Option<Value>,
    started_host: bool,
    host_child: Option<Child>,
    update: Upd,
    /// The chat and view to reopen, read once at start after an update's restart.
    reopen: Option<Value>,
    /// A start is under way (the bundled packages, then the host): a second one only waits.
    starting: bool,
    /// Why the last start failed, for the start page; None while it starts and once it did.
    failure: Option<Failure>,
    /// The first start's own work, for the start page: which of how many bundled packages is
    /// being installed.
    progress: Option<(usize, usize)>,
    /// The session key of the host whose page the window loaded. A host that started again
    /// has another one, which the page in the window cannot use.
    page_key: Option<String>,
}

/// Why the app could not start, as the start page shows it: the kind (the code of the
/// harness's Problem, or the shell's own `packages` and `runtime`), the reason and the fix in
/// the harness's words, the rest of what was said, and the log's path.
#[derive(Clone, Debug, Default, PartialEq, serde::Serialize)]
struct Failure {
    code: String,
    reason: String,
    fix: String,
    detail: String,
    log: String,
}

// -- the language of the shell's own words -------------------------------------------------

/// The page's language as the host last told it (general.language): 0 the system's, 1
/// Chinese, 2 English.
static LANGUAGE: AtomicU8 = AtomicU8::new(0);

fn set_language(choice: &str) {
    LANGUAGE.store(match choice { "zh" => 1, "en" => 2, _ => 0 }, Ordering::Relaxed);
}

/// Whether the shell speaks Chinese: the page's language when it is set, else the system's
/// (asked once), as the page does with the browser's.
fn chinese() -> bool {
    static SYSTEM: OnceLock<bool> = OnceLock::new();
    match LANGUAGE.load(Ordering::Relaxed) {
        1 => true,
        2 => false,
        _ => *SYSTEM.get_or_init(|| sys_locale::get_locale().map(|tag| tag.to_lowercase().starts_with("zh")).unwrap_or(false)),
    }
}

/// One of the shell's own texts, in Chinese or English.
fn tt<'a>(zh: &'a str, en: &'a str) -> &'a str {
    if chinese() { zh } else { en }
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

// -- this build's name and channel ---------------------------------------------------------

/// The app's name as this build's Tauri configuration has it (The Harness; a dev build: The
/// Harness Dev). main() sets it before anything else; the window, the tray and the
/// notifications say it, and a .deb's runtime is in the folder of that name.
static PRODUCT: OnceLock<String> = OnceLock::new();

fn product() -> &'static str {
    PRODUCT.get().map(String::as_str).unwrap_or("The Harness")
}

/// The channel this build belongs to (stable, dev): the first word of runtime/channel, which
/// the installer's build writes and the harness reads too (harness/channel.py); stable
/// without it.
fn channel() -> &'static str {
    static FOUND: OnceLock<String> = OnceLock::new();
    FOUND.get_or_init(|| {
        runtime_dir()
            .and_then(|runtime| std::fs::read_to_string(runtime.join("channel")).ok())
            .and_then(|text| channel_of(&text))
            .unwrap_or_else(|| "stable".into())
    })
}

fn channel_of(text: &str) -> Option<String> {
    let name = text.split_whitespace().next()?;
    let fits = name.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit());
    (fits && name.len() <= 16).then(|| name.to_string())
}

/// `base` as a channel has it: itself on the stable one, else with the channel's name after
/// it (.harness is .harness-dev), as harness/channel.py's tag().
fn tagged(base: &str, channel: &str) -> String {
    if channel == "stable" {
        base.to_string()
    } else {
        format!("{base}-{channel}")
    }
}

/// The build number of a channel's build (412 of 0.87.0-dev.412, given its pre-release part
/// "dev.412"): none for a release.
fn build_number(pre: &str) -> Option<u64> {
    pre.rsplit_once('.')?.1.parse().ok()
}

/// Whether a build replaces the one running, by their build numbers alone: a channel's builds
/// follow each other by number whatever version of the core each was built from (a branch's
/// 0.87.0-dev.413 comes after main's 0.88.0-dev.412). None when either has no build number:
/// the versions themselves decide then.
fn newer_build(current_pre: &str, remote_pre: &str) -> Option<bool> {
    Some(build_number(remote_pre)? > build_number(current_pre)?)
}

/// How often automatic update checks run for `ch`: hourly on stable, every 10 min on dev/other channels.
fn update_interval(ch: &str) -> Duration {
    if ch == "stable" { UPDATE_EVERY } else { UPDATE_EVERY_DEV }
}

/// Whether `candidate` is strictly newer than `current` (e.g. "0.87.0-dev.27" > "0.87.0-dev.26",
/// "0.87.0" > "0.87.0-dev.27", "0.88.0" > "0.87.0"). Prevents re-downloading the same version or
/// downgrading an already-cached `ready` update from a stale CDN mirror.
fn version_newer(current: &str, candidate: &str) -> bool {
    if current == candidate {
        return false;
    }
    let (c_base, c_pre) = current.split_once('-').unwrap_or((current, ""));
    let (n_base, n_pre) = candidate.split_once('-').unwrap_or((candidate, ""));
    if let Some(newer) = newer_build(c_pre, n_pre) {
        return newer;
    }
    let parse = |s: &str| -> Vec<u64> {
        s.split('.').map(|p| p.parse::<u64>().unwrap_or(0)).collect()
    };
    let (cb, nb) = (parse(c_base), parse(n_base));
    if nb != cb {
        return nb > cb;
    }
    match (c_pre.is_empty(), n_pre.is_empty()) {
        (false, true) => true,
        (true, false) => false,
        _ => n_pre > c_pre,
    }
}

// -- the bundled Python and the harness ----------------------------------------------------

/// The folder installers put next to the shell: runtime/python (python-build-standalone with
/// the Harness wheel) and runtime/packages (package folders installed on first start).
fn runtime_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let candidates = [
        dir.join("runtime"),                                  // Windows, an AppImage's usr/bin
        dir.join("../Resources/runtime"),                     // macOS .app
        dir.join("../lib").join(product()).join("runtime"),   // .deb (/usr/bin -> /usr/lib/<product>)
        dir.join("../lib").join(exe.file_stem().unwrap_or_default()).join("runtime"),
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

/// The user's data folder ($HARNESS_DATA, default ~/.harness; the dev channel's is
/// ~/.harness-dev), as the harness has it.
fn data_dir() -> PathBuf {
    if let Ok(given) = std::env::var("HARNESS_DATA") {
        if !given.is_empty() {
            return PathBuf::from(given);
        }
    }
    let home = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE")).unwrap_or_else(|_| ".".into());
    PathBuf::from(home).join(tagged(".harness", channel()))
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

/// Install the package folders the installer brought (agent, app and the ones for first use),
/// each time a folder's content is new; the harness copies each into the user's packages and
/// replaces an older or stale one. `progress` hears which of how many it is at (the start page
/// shows it). What failed: (name, the harness's own words), also logged to DATA/logs/shell.log.
fn install_bundled_packages(progress: &dyn Fn(usize, usize)) -> Vec<(String, String)> {
    let mut failed = Vec::new();
    let Some(runtime) = runtime_dir() else { return failed };
    let Ok(entries) = std::fs::read_dir(runtime.join("packages")) else { return failed };
    let done = data_dir().join("host").join("shell-packages");
    let _ = std::fs::create_dir_all(&done);
    let mut folders: Vec<_> = entries.flatten().map(|entry| entry.path()).filter(|p| p.join("package.toml").is_file()).collect();
    // The agent and the app first: the window needs them; the others when they are used.
    folders.sort_by_key(|p| match p.file_name().and_then(|n| n.to_str()) { Some("agent") => 0, Some("app") => 1, _ => 2 });
    let new: Vec<_> = folders
        .into_iter()
        .map(|folder| {
            let name = folder.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            let marker = done.join(format!("{name}-{}", folder_digest(&folder)));
            (folder, name, marker)
        })
        .filter(|(_, _, marker)| !marker.exists())
        .collect();
    for (index, (folder, name, marker)) in new.iter().enumerate() {
        let (name, marker) = (name.clone(), marker.clone());
        progress(index + 1, new.len());
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

fn shell_log() -> String {
    data_dir().join("logs").join("shell.log").to_string_lossy().to_string()
}

/// The packages the window needs did not install: there is no app to open yet.
fn packages_failure(failed: &[(String, String)]) -> Failure {
    let names: Vec<&str> = failed.iter().map(|(name, _)| name.as_str()).collect();
    let said: Vec<String> = failed.iter().map(|(name, said)| format!("{name}\n{said}")).collect();
    Failure { code: "packages".into(), reason: names.join(", "), fix: String::new(), detail: said.join("\n\n"), log: shell_log() }
}

/// The bundled Python did not get as far as the harness (it is missing, or ended without the
/// harness's answer): `said` is what there is of it.
fn runtime_failure(said: &str) -> Failure {
    log(&format!("the Python runtime: {said}"));
    let reason = said.lines().rev().find(|line| !line.trim().is_empty()).unwrap_or("").trim().to_string();
    Failure { code: "runtime".into(), reason, fix: String::new(), detail: said.trim().to_string(), log: shell_log() }
}

/// The failure `harness.host.login` printed ({error, fix, code, log}, the last line of its
/// standard output); None when it printed none.
fn told(output: &str) -> Option<Failure> {
    let line = output.lines().rev().find(|line| !line.trim().is_empty())?;
    let found: Value = serde_json::from_str(line.trim()).ok()?;
    let text = |key: &str| found[key].as_str().unwrap_or("").to_string();
    let reason = found["error"].as_str()?.to_string();
    Some(Failure { code: found["code"].as_str().unwrap_or("error").into(), reason, fix: text("fix"), detail: String::new(), log: text("log") })
}

/// The start page's own address (WebviewUrl::App): the window comes back to it to show a
/// failure when it was on the host's page.
fn start_page() -> Url {
    Url::parse(if cfg!(windows) { "http://tauri.localhost/index.html" } else { "tauri://localhost/index.html" }).unwrap()
}

/// The start failed: the start page shows why (it asks start_state), instead of a window that
/// goes on saying it is starting.
fn fail(app: &AppHandle, failure: Failure) {
    log(&format!("the start failed ({}): {}", failure.code, failure.reason));
    if let Some(state) = app.try_state::<State>() {
        state.lock().unwrap().failure = Some(failure);
    }
    show_start(app);
}

/// The start page with what the shell has to say now: redrawn when the window is on it, loaded
/// when the window is on the host's page.
fn show_start(app: &AppHandle) {
    let Some(webview) = app.get_webview("main") else { return };
    let start = start_page();
    if webview.url().map(|now| now.origin() == start.origin()).unwrap_or(true) {
        let _ = webview.eval("window.sync && window.sync()");
    } else {
        let _ = webview.navigate(start);
    }
}

/// What the start page shows: {"failure": null, "progress": null | [n, of]} while the app
/// starts (progress: the first start installing what the app brought), else why it did not.
#[tauri::command]
fn start_state(state: tauri::State<'_, State>) -> Value {
    let shared = state.lock().unwrap();
    serde_json::json!({
        "product": product(),
        "failure": shared.failure,
        "progress": shared.progress.map(|(at, of)| [at, of]),
    })
}

/// The failure card's Try again.
#[tauri::command]
fn retry(app: AppHandle) {
    open(&app, None);
}

/// The failure card's Open the log: the failure's log file in the system's own viewer.
#[tauri::command]
fn open_log(state: tauri::State<'_, State>) {
    let path = state.lock().unwrap().failure.as_ref().map(|failure| failure.log.clone()).unwrap_or_default();
    if path.is_empty() {
        return;
    }
    let program = if cfg!(windows) { "explorer" } else if cfg!(target_os = "macos") { "open" } else { "xdg-open" };
    let _ = Command::new(program).arg(path).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
}

// -- native embedded browser (child WebView in the right workbench pane) -------------------

/// Validate and normalize a URL for the embedded browser: only http:// and https:// are allowed.
fn parse_browser_url(raw: &str) -> Result<Url, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("URL is empty".into());
    }
    let normalized = if trimmed.contains("://") {
        trimmed.to_string()
    } else if trimmed.starts_with("localhost")
        || trimmed.starts_with("127.0.0.1")
        || trimmed.starts_with("[::1]")
    {
        format!("http://{trimmed}")
    } else {
        format!("https://{trimmed}")
    };
    let parsed = Url::parse(&normalized).map_err(|e| format!("invalid URL: {e}"))?;
    match parsed.scheme() {
        "http" | "https" => Ok(parsed),
        scheme => Err(format!("unsupported URL scheme: {scheme}")),
    }
}

/// Sanitize logical bounds for the child WebView; returns None when collapsed or non-finite.
fn clamp_browser_bounds(x: f64, y: f64, width: f64, height: f64) -> Option<(f64, f64, f64, f64)> {
    if ![x, y, width, height].iter().all(|v| v.is_finite()) {
        return None;
    }
    if width < 20.0 || height < 20.0 {
        return None;
    }
    Some((x.max(0.0), y.max(0.0), width, height))
}

/// Convert CSS viewport bounds from the main webview into an exact host-window `Rect`.
/// When `viewport_width`/`viewport_height` and `inner_size` are available, mapping through
/// the dimensionless viewport fraction produces exact `PhysicalPosition`/`PhysicalSize`
/// regardless of Windows DPI scaling, cross-monitor DPI changes, or WebView2 zoom level.
fn resolve_browser_rect(
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    viewport_width: Option<f64>,
    viewport_height: Option<f64>,
    inner_size: Option<PhysicalSize<u32>>,
) -> Option<Rect> {
    let (cx, cy, cw, ch) = clamp_browser_bounds(x, y, width, height)?;
    if let (Some(vw), Some(vh), Some(inner)) = (viewport_width, viewport_height, inner_size) {
        if vw.is_finite()
            && vh.is_finite()
            && vw >= 1.0
            && vh >= 1.0
            && inner.width > 0
            && inner.height > 0
        {
            let sx = inner.width as f64 / vw;
            let sy = inner.height as f64 / vh;
            let px = (cx * sx).round().clamp(0.0, inner.width as f64) as i32;
            let py = (cy * sy).round().clamp(0.0, inner.height as f64) as i32;
            let max_w = (inner.width as i32 - px).max(0) as u32;
            let max_h = (inner.height as i32 - py).max(0) as u32;
            let pw = ((cw * sx).round().max(0.0) as u32).min(max_w);
            let ph = ((ch * sy).round().max(0.0) as u32).min(max_h);
            if pw < 20 || ph < 20 {
                return None;
            }
            return Some(Rect {
                position: Position::Physical(PhysicalPosition::new(px, py)),
                size: Size::Physical(PhysicalSize::new(pw, ph)),
            });
        }
    }
    Some(Rect {
        position: Position::Logical(LogicalPosition::new(cx, cy)),
        size: Size::Logical(LogicalSize::new(cw, ch)),
    })
}

/// Serializes child-webview creation and mutations off the Win32 UI thread so concurrent
/// `browser_open` / `browser_bounds` / `browser_close` calls never race or duplicate labels.
fn browser_op_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

#[tauri::command]
async fn browser_open(
    app: AppHandle,
    caller: tauri::Webview,
    url: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    viewport_width: Option<f64>,
    viewport_height: Option<f64>,
) -> Result<String, String> {
    if caller.label() != "main" {
        return Err("forbidden".into());
    }
    let target = parse_browser_url(&url)?;
    // On Windows, `Window::add_child` deadlocks if called synchronously from a command handler
    // (WebView2 IPC runs on the Win32 main thread; see wry#583). Always execute on a blocking
    // worker thread from an `async` command.
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = browser_op_lock().lock().unwrap_or_else(|e| e.into_inner());
        let window = app.get_window("main").ok_or("main window not found")?;
        let rect = resolve_browser_rect(
            x,
            y,
            width,
            height,
            viewport_width,
            viewport_height,
            window.inner_size().ok(),
        );
        if let Some(existing) = app.get_webview(BROWSER_WEBVIEW) {
            if let Some(bounds) = rect {
                let _ = existing.set_bounds(bounds);
                let _ = existing.show();
            } else {
                let _ = existing.hide();
            }
            existing.navigate(target.clone()).map_err(|e| e.to_string())?;
            return Ok(target.to_string());
        }
        let app_nav = app.clone();
        let app_new = app.clone();
        let builder = WebviewBuilder::new(BROWSER_WEBVIEW, WebviewUrl::External(target.clone()))
            .focused(false)
            .on_navigation(move |next_url| {
                let allowed = matches!(next_url.scheme(), "http" | "https" | "about");
                if allowed && matches!(next_url.scheme(), "http" | "https") {
                    if let Some(main) = app_nav.get_webview("main") {
                        if let Ok(encoded) = serde_json::to_string(next_url.as_str()) {
                            let _ = main.eval(&format!(
                                "window.__harnessBrowserNav && window.__harnessBrowserNav({encoded})"
                            ));
                        }
                    }
                }
                allowed
            })
            .on_new_window(move |next_url, _features| {
                if matches!(next_url.scheme(), "http" | "https") {
                    if let Some(child) = app_new.get_webview(BROWSER_WEBVIEW) {
                        let _ = child.navigate(next_url);
                    }
                }
                NewWindowResponse::Deny
            });
        let (pos, size) = rect
            .map(|r| (r.position, r.size))
            .unwrap_or((
                Position::Logical(LogicalPosition::new(0.0, 0.0)),
                Size::Logical(LogicalSize::new(1.0, 1.0)),
            ));
        let child = window.add_child(builder, pos, size).map_err(|e| e.to_string())?;
        if rect.is_none() {
            let _ = child.hide();
        }
        Ok(target.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn browser_bounds(
    app: AppHandle,
    caller: tauri::Webview,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    visible: bool,
    viewport_width: Option<f64>,
    viewport_height: Option<f64>,
) -> Result<(), String> {
    if caller.label() != "main" {
        return Err("forbidden".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = browser_op_lock().lock().unwrap_or_else(|e| e.into_inner());
        let Some(child) = app.get_webview(BROWSER_WEBVIEW) else {
            return Ok(());
        };
        if !visible {
            let _ = child.hide();
            return Ok(());
        }
        let inner = app.get_window("main").and_then(|w| w.inner_size().ok());
        if let Some(bounds) = resolve_browser_rect(
            x,
            y,
            width,
            height,
            viewport_width,
            viewport_height,
            inner,
        ) {
            let _ = child.set_bounds(bounds);
            let _ = child.show();
        } else {
            let _ = child.hide();
        }
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn browser_nav(app: AppHandle, caller: tauri::Webview, action: String) -> Result<(), String> {
    if caller.label() != "main" {
        return Err("forbidden".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = browser_op_lock().lock().unwrap_or_else(|e| e.into_inner());
        let Some(child) = app.get_webview(BROWSER_WEBVIEW) else {
            return Ok(());
        };
        let script = match action.as_str() {
            "back" => "window.history.back()",
            "forward" => "window.history.forward()",
            "reload" => "window.location.reload()",
            _ => return Err(format!("unknown browser action: {action}")),
        };
        child.eval(script).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn browser_close(app: AppHandle, caller: tauri::Webview) -> Result<(), String> {
    if caller.label() != "main" {
        return Err("forbidden".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = browser_op_lock().lock().unwrap_or_else(|e| e.into_inner());
        if let Some(child) = app.get_webview(BROWSER_WEBVIEW) {
            let _ = child.close();
        }
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
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

/// --autostart on | off | default: only explicit `on` or `off` changes the login item.
/// `default` is a no-op so installing or opening the app never registers a login item
/// behind the user's back.
fn autostart(choice: &str) -> i32 {
    let words: &[&str] = match choice {
        "on" => &["install"],
        "off" => &["uninstall"],
        "default" => return 0,
        _ => {
            eprintln!("--autostart on, off or default");
            return 2;
        }
    };
    match login(words) {
        Ok(text) => {
            print!("{text}");
            0
        }
        Err(error) => {
            eprintln!("{error}");
            1
        }
    }
}

/// Whether `args` is a CLI invocation (e.g. `the-harness --version`, `the-harness status`,
/// `the-harness -p "hi"`) rather than a desktop shell launch (no args, an http(s) URL, or
/// one of the shell's own internal flags). Used on Linux where `/usr/bin/the-harness` serves
/// as both the desktop app launcher and the primary CLI command.
fn is_cli_invocation(args: &[String]) -> bool {
    let Some(first) = args.get(1) else {
        return false;
    };
    if matches!(first.as_str(), "--focus" | "--host" | "--autostart" | "--stop-host" | "--path") {
        return false;
    }
    if first.starts_with("http://") || first.starts_with("https://") {
        return false;
    }
    true
}

/// `harness_app/shell.py command ARGS` with the bundled Python: the `harness` command for
/// terminals (on the PATH, off it, which one a terminal runs). The file is run from the app
/// package the installer brought: nothing is installed for the user yet when an installer asks.
fn path_command(args: &[&str]) -> Result<String, String> {
    let script = runtime_dir()
        .map(|runtime| runtime.join("packages").join("app").join("harness_app").join("shell.py"))
        .filter(|file| file.is_file())
        .ok_or("this build brings no app package")?;
    let script = script.to_string_lossy().to_string();
    let mut words = vec![script.as_str(), "command"];
    words.extend_from_slice(args);
    let output = harness(&words).output().map_err(|error| format!("{}: {error}", python().display()))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
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

/// The app page (starting the host when none runs, as harness does), or why there is none:
/// `harness.host.login page` prints the page, or the failure with its reason, fix and log.
fn page() -> Result<Url, Failure> {
    let output = match harness(&["-m", "harness.host.login", "page"]).output() {
        Ok(output) => output,
        Err(error) => return Err(runtime_failure(&format!("{}: {error}", python().display()))),
    };
    let printed = String::from_utf8_lossy(&output.stdout);
    if output.status.success() {
        let found: Value = serde_json::from_str(printed.trim()).unwrap_or(Value::Null);
        if let Some(page) = found["page"].as_str().and_then(|page| Url::parse(page).ok()) {
            return Ok(page);
        }
    }
    match told(&printed) {
        Some(failure) => Err(failure),
        None => Err(runtime_failure(&format!("{}{}", String::from_utf8_lossy(&output.stderr), printed))),
    }
}

// -- windows -------------------------------------------------------------------------------

fn main_window(app: &AppHandle) -> Window {
    if let Some(window) = app.get_window("main") {
        return window;
    }
    let builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title(product())
        .inner_size(1200.0, 800.0)
        .min_inner_size(380.0, 480.0);
    let _ = title_bar(builder).build().expect("the main window");
    app.get_window("main").expect("the main window")
}

/// The page draws the title bar in its own top row (capabilities/window.json lets it drag,
/// minimize, maximize and close): no native strip; Windows and Linux keep the system's
/// resize edges, snapping and shadow, macOS keeps its traffic lights over the page.
fn title_bar<'a>(builder: WebviewWindowBuilder<'a, Wry, AppHandle>) -> WebviewWindowBuilder<'a, Wry, AppHandle> {
    #[cfg(target_os = "macos")]
    return builder.title_bar_style(tauri::TitleBarStyle::Overlay).hidden_title(true);
    #[cfg(not(target_os = "macos"))]
    return builder.decorations(false).shadow(true);
}

/// Show the window on `url`, or on the host's page (found or started off the UI thread). One
/// start at a time: while one is under way (the first installs the bundled packages) another
/// click only raises the window. What fails is shown by the start page (fail).
fn open(app: &AppHandle, url: Option<Url>) {
    let window = main_window(app);
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
    let Some(state) = app.try_state::<State>().map(|state| state.inner().clone()) else { return };
    // After an update's restart: the chat or view that was open.
    let reopen = {
        let mut shared = state.lock().unwrap();
        if shared.starting {
            return;
        }
        shared.starting = true;
        shared.reopen.take()
    };
    // Try again: the start page says it is starting again.
    if state.lock().unwrap().failure.take().is_some() {
        show_start(app);
    }
    let app = app.clone();
    thread::spawn(move || {
        let found = start(&app, &state, url, reopen.is_some());
        state.lock().unwrap().starting = false;
        match found {
            Ok(mut url) => {
                if let Some(reopen) = &reopen {
                    for key in ["chat", "view"] {
                        if let Some(value) = reopen[key].as_str().filter(|value| !value.is_empty()) {
                            url.query_pairs_mut().append_pair(key, value);
                        }
                    }
                }
                if let Some(webview) = app.get_webview("main") {
                    // The page the window has is this host's when the address and the session
                    // key are the same; a host that started again gets its page loaded anew.
                    let key = url.query_pairs().find(|(name, _)| name == "token").map(|(_, value)| value.to_string());
                    let showing = webview.url().map(|now| now.origin() == url.origin()).unwrap_or(false)
                        && state.lock().unwrap().page_key == key;
                    if !showing || reopen.is_some() {
                        state.lock().unwrap().page_key = key;
                        let _ = webview.navigate(url);
                    }
                }
            }
            Err(failure) => fail(&app, failure),
        }
    });
}

/// What the window needs before it has a page: after an update the installed packages brought
/// up to it, the bundled packages installed, and the host answering.
fn start(app: &AppHandle, state: &State, url: Option<Url>, updated: bool) -> Result<Url, Failure> {
    if updated {
        upgrade_installed();
    }
    let said = |progress: Option<(usize, usize)>| {
        state.lock().unwrap().progress = progress;
        show_start(app);
    };
    let installed = install_bundled_packages(&|at, of| said(Some((at, of))));
    if state.lock().unwrap().progress.is_some() {
        said(None);
    }
    let failed: Vec<_> = installed.into_iter().filter(|(name, _)| name == "agent" || name == "app").collect();
    if !failed.is_empty() {
        return Err(packages_failure(&failed));
    }
    match url {
        Some(url) => Ok(url),
        None => page(),
    }
}

/// A second start of the shell (harness app, a click on its icon): its arguments, here.
fn handle(app: &AppHandle, args: &[String]) {
    let url = args.iter().skip(1).find_map(|word| Url::parse(word).ok().filter(|u| u.scheme().starts_with("http")));
    if args.iter().any(|word| word == "--host" || word == "--autostart" || word == "--stop-host" || word == "--path") {
        return;
    }
    open(app, url);
}

// -- the tray ------------------------------------------------------------------------------

/// The tray's items, kept to say them again: the pause item by the agent's state, the update
/// item by its version, all of them when the page's language changes.
#[derive(Clone)]
struct Items {
    menu: Menu<Wry>,
    open: MenuItem<Wry>,
    update: MenuItem<Wry>,
    pause: MenuItem<Wry>,
    login: CheckMenuItem<Wry>,
    command: MenuItem<Wry>,
    quit: MenuItem<Wry>,
}

fn pause_label(paused: bool, zh: bool) -> &'static str {
    match (paused, zh) {
        (false, false) => "Pause",
        (true, false) => "Resume",
        (false, true) => "暂停",
        (true, true) => "继续",
    }
}

/// The tray's item while an update is ready. Windows: the installer closes the app for a
/// moment, so the item says so before the click.
fn restart_label(version: &str, zh: bool) -> String {
    match (zh, cfg!(windows)) {
        (false, true) => format!("Restart to update to {version} (it closes briefly to install)"),
        (false, false) => format!("Restart to update to {version}"),
        (true, true) => format!("重启以更新到 {version}（安装时窗口会关一下）"),
        (true, false) => format!("重启以更新到 {version}"),
    }
}

/// macOS: the item that links the terminal command (`harness`; a dev build's `harness-dev`)
/// into the PATH or takes it out, in the words of VS Code's two shell commands.
fn command_label(linked: bool, zh: bool, command: &str) -> String {
    match (linked, zh) {
        (false, false) => format!("Install '{command}' command in PATH"),
        (true, false) => format!("Uninstall '{command}' command from PATH"),
        (false, true) => format!("在 PATH 中安装“{command}”命令"),
        (true, true) => format!("从 PATH 中卸载“{command}”命令"),
    }
}

/// Every item's text in the shell's language as it is now.
fn label(items: &Items, state: &State) {
    let zh = chinese();
    let (paused, command, ready) = {
        let shared = state.lock().unwrap();
        (shared.paused, shared.command, (shared.update.phase == "ready").then(|| shared.update.version.clone().unwrap_or_default()))
    };
    let _ = items.open.set_text(if zh { format!("打开 {}", product()) } else { format!("Open {}", product()) });
    let _ = items.pause.set_text(pause_label(paused, zh));
    let _ = items.login.set_text(if zh { "开机时启动" } else { "Start at login" });
    let _ = items.command.set_text(command_label(command, zh, &tagged("the-harness", channel())));
    let _ = items.quit.set_text(if zh { "退出" } else { "Quit" });
    if let Some(version) = ready {
        let _ = items.update.set_text(restart_label(&version, zh));
    }
}

fn tray(app: &AppHandle, state: State) -> tauri::Result<()> {
    let item = |id: &str| MenuItem::with_id(app, id, "", true, None::<&str>);
    let (open_item, pause_item, quit_item, update_item, command_item) = (item("open")?, item("pause")?, item("quit")?, item("update")?, item("command")?);
    let login_item = CheckMenuItem::with_id(app, "login", "", true, false, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open_item, &pause_item, &login_item, &separator, &quit_item])?;
    if cfg!(target_os = "macos") {
        // No installer runs on macOS: the app offers the command itself, as VS Code does.
        menu.insert(&command_item, 3)?;
    }
    let items = Items { menu, open: open_item, update: update_item, pause: pause_item, login: login_item, command: command_item, quit: quit_item };
    label(&items, &state);
    let menu_state = state.clone();
    let menu_items = items.clone();
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("an icon"))
        .tooltip(product())
        .menu(&items.menu)
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
                    let _ = menu_items.pause.set_text(pause_label(!paused, chinese()));
                }
            }
            "login" => {
                let wanted = !menu_state.lock().unwrap().autostart;
                let state = menu_state.clone();
                let item = menu_items.login.clone();
                thread::spawn(move || {
                    let _ = login(&[if wanted { "install" } else { "uninstall" }]);
                    refresh_login(&state, &item);
                });
            }
            "command" => {
                let wanted = !menu_state.lock().unwrap().command;
                let (state, item, app) = (menu_state.clone(), menu_items.command.clone(), app.clone());
                thread::spawn(move || {
                    if let Err(error) = path_command(&[if wanted { "on" } else { "off" }]) {
                        let _ = app.notification().builder().title(product()).body(error).show();
                    }
                    refresh_command(&state, &item);
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
    let (update_app, update_state, update_items) = (app.clone(), state.clone(), items.clone());
    thread::spawn(move || updates(update_app, update_state, update_items));
    let app = app.clone();
    thread::spawn(move || poll(app, state, items));
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

/// macOS: whether this app's `harness` is on a terminal's PATH (the link is there), into its item.
fn refresh_command(state: &State, item: &MenuItem<Wry>) {
    if let Ok(text) = path_command(&["status", "--json"]) {
        if let Ok(found) = serde_json::from_str::<Value>(text.trim()) {
            let linked = found["on_path"].as_bool().unwrap_or(false);
            state.lock().unwrap().command = linked;
            let _ = item.set_text(command_label(linked, chinese(), &tagged("harness", channel())));
        }
    }
}

fn poll(app: AppHandle, state: State, items: Items) {
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
                let _ = items.pause.set_text(pause_label(paused, chinese()));
            }
        }
        notify(&app, &state, first);
        first = false;
        if last_login.elapsed() >= LOGIN_CHECK {
            refresh_login(&state, &items.login);
            if cfg!(target_os = "macos") {
                refresh_command(&state, &items.command);
            }
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
        .get_window("main")
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
        let title = row["title"].as_str().unwrap_or(product());
        let body = row["body"].as_str().unwrap_or("");
        let _ = app.notification().builder().title(title).body(body).show();
        if let Some(window) = app.get_window("main") {
            let _ = window.request_user_attention(Some(tauri::UserAttentionType::Informational));
        }
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

/// Whether to check now, by app.update: default at start and every `interval`, start at start
/// only, manual when asked (Check for updates), none never (not even when asked).
fn due_with_interval(mode: &str, since_last: Option<Duration>, asked: bool, interval: Duration) -> bool {
    match mode {
        "none" => false,
        _ if asked => true,
        "default" => since_last.map(|time| time >= interval).unwrap_or(true),
        "start" => since_last.is_none(),
        _ => false,
    }
}

fn due(mode: &str, since_last: Option<Duration>, asked: bool) -> bool {
    due_with_interval(mode, since_last, asked, UPDATE_EVERY)
}

/// The update's loop: report to the host each second and take the owner's requests; check by
/// app.update (the host's answer: default at start and periodically, start at start only, manual
/// when asked, none never); keep the tray's item updated while an update is ready. The answer also
/// carries the page's language, which the tray's words follow.
fn updates(app: AppHandle, state: State, items: Items) {
    let mut shown_version: Option<String> = None;
    let mut last_check: Option<Instant> = None;
    let interval = update_interval(channel());
    loop {
        let state_now = report(&app, &state.lock().unwrap().update);
        if let Ok(answer) = post("/api/app/update", serde_json::json!({"action": "shell", "state": state_now})) {
            let spoke = chinese();
            set_language(answer["language"].as_str().unwrap_or("system"));
            if chinese() != spoke {
                label(&items, &state);
            }
            let mode = answer["mode"].as_str().unwrap_or("default").to_string();
            let asked = answer["requests"].as_array().map(|rows| rows.iter().any(|row| row == "check")).unwrap_or(false);
            if due_with_interval(&mode, last_check.map(|time| time.elapsed()), asked, interval) {
                last_check = Some(Instant::now());
                check(&app, &state);
            }
            if answer["restart"].is_object() {
                let app_c = app.clone();
                let state_c = state.clone();
                let req = answer["restart"].clone();
                thread::spawn(move || restart(&app_c, &state_c, &req));
            }
        }
        let ready = {
            let shared = state.lock().unwrap();
            (shared.update.phase == "ready").then(|| shared.update.version.clone().unwrap_or_default())
        };
        match (ready, shown_version.as_deref()) {
            (Some(version), prev) if prev != Some(version.as_str()) => {
                let _ = items.update.set_text(restart_label(&version, chinese()));
                if prev.is_none() {
                    if items.menu.insert(&items.update, 1).is_ok() {
                        shown_version = Some(version);
                    }
                } else {
                    shown_version = Some(version);
                }
            }
            (None, Some(_)) => {
                let _ = items.menu.remove(&items.update);
                shown_version = None;
            }
            _ => {}
        }
        thread::sleep(UPDATE_TICK);
    }
}

/// Check, and when there is a newer update download it and verify its signature (Update::download
/// checks it against the updater key): it is then ready, and nothing more happens until the
/// owner clicks Restart to update. When an update is already `ready`, checking again still polls
/// for an even newer release and seamlessly upgrades the cached bundle if one exists (keeping the
/// previously verified bundle intact on network errors or if no newer release exists).
fn check(app: &AppHandle, state: &State) {
    let prev_ready: Option<(String, Option<String>)> = {
        let mut shared = state.lock().unwrap();
        let update = &mut shared.update;
        if matches!(update.phase.as_str(), "checking" | "downloading" | "installing") {
            return;
        }
        if !configured(app) {
            update.phase = "off".into();
            update.error = Some("this build has no updater key".into());
            return;
        }
        let prev = if update.phase == "ready" && update.found.is_some() && update.bytes.is_some() {
            update.version.clone().map(|v| (v, update.notes.clone()))
        } else {
            None
        };
        update.phase = "checking".into();
        update.error = None;
        prev
    };
    let app = app.clone();
    let state = state.clone();
    tauri::async_runtime::spawn(async move {
        let result: Result<bool, String> = async {
            // A channel's numbered builds follow each other by build number; releases by version.
            let updater = app
                .updater_builder()
                .version_comparator(|current, release| {
                    newer_build(current.pre.as_str(), release.version.pre.as_str()).unwrap_or(release.version > current)
                })
                .build()
                .map_err(|error| error.to_string())?;
            let Some(found) = updater.check().await.map_err(|error| error.to_string())? else { return Ok(false) };
            // Already have this exact version (or a newer one) verified in memory: reuse without re-downloading.
            if let Some((ref cached_ver, _)) = prev_ready {
                if !version_newer(cached_ver, &found.version) {
                    return Ok(true);
                }
            }
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
            shared.update.version = Some(found.version.clone());
            shared.update.notes = found.body.clone();
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
            Ok(false) => {
                if let Some((ver, notes)) = prev_ready {
                    update.phase = "ready".into();
                    update.version = Some(ver);
                    update.notes = notes;
                } else {
                    update.phase = "latest".into();
                }
            }
            Err(error) => {
                eprintln!("update: {error}");
                if let Some((ver, notes)) = prev_ready {
                    // Preserve the already-verified ready bundle if checking/downloading a newer one failed.
                    update.phase = "ready".into();
                    update.version = Some(ver);
                    update.notes = notes;
                    update.error = Some(error);
                } else {
                    update.phase = "error".into();
                    update.error = Some(error);
                    update.found = None;
                    update.bytes = None;
                }
            }
        }
    });
}

/// The owner's Restart to update, handed over by the host once nothing is at work (or the
/// owner chose to interrupt): do a quick pre-install check so back-to-back releases jump
/// straight to the newest version in one restart, then stop the host, install, and restart.
fn restart(app: &AppHandle, state: &State, request: &Value) {
    let (mut found, mut bytes, host_mode) = {
        let mut shared = state.lock().unwrap();
        if shared.update.phase != "ready" {
            return;
        }
        shared.update.phase = "installing".into();
        (shared.update.found.clone(), shared.update.bytes.take(), shared.started_host)
    };
    let (Some(cached_found), Some(cached_bytes)) = (found.take(), bytes.take()) else { return };
    let mut active_found = cached_found;
    let mut active_bytes = cached_bytes;

    // Fast pre-install check: if a strictly newer release was published after the cached bundle
    // was downloaded (e.g. dev.27 arrived while dev.26 was waiting in memory), download and install
    // the latest release directly in one single restart. Any timeout/network error falls back cleanly
    // to the already-verified cached bundle.
    if configured(app) {
        let app_for_check = app.clone();
        let state_for_dl = state.clone();
        let cached_ver = active_found.version.clone();
        let upgraded: Option<(tauri_plugin_updater::Update, Vec<u8>)> = tauri::async_runtime::block_on(async move {
            let updater = app_for_check
                .updater_builder()
                .timeout(PRE_INSTALL_CHECK_TIMEOUT)
                .version_comparator(|current, release| {
                    newer_build(current.pre.as_str(), release.version.pre.as_str()).unwrap_or(release.version > current)
                })
                .build()
                .ok()?;
            let latest = updater.check().await.ok()??;
            if !version_newer(&cached_ver, &latest.version) {
                return None;
            }
            {
                let mut shared = state_for_dl.lock().unwrap();
                shared.update.phase = "downloading".into();
                shared.update.version = Some(latest.version.clone());
                shared.update.notes = latest.body.clone();
                shared.update.got = 0;
                shared.update.total = None;
            }
            let progress = state_for_dl.clone();
            let dl = latest
                .download(
                    move |chunk, total| {
                        let mut shared = progress.lock().unwrap();
                        shared.update.got += chunk as u64;
                        shared.update.total = total;
                    },
                    || {},
                )
                .await
                .ok()?;
            Some((latest, dl))
        });
        if let Some((latest_found, latest_bytes)) = upgraded {
            let mut shared = state.lock().unwrap();
            shared.update.version = Some(latest_found.version.clone());
            shared.update.notes = latest_found.body.clone();
            shared.update.found = Some(latest_found.clone());
            shared.update.phase = "installing".into();
            active_found = latest_found;
            active_bytes = latest_bytes;
        } else {
            let mut shared = state.lock().unwrap();
            shared.update.version = Some(active_found.version.clone());
            shared.update.notes = active_found.body.clone();
            shared.update.phase = "installing".into();
        }
    }

    let window = app.get_window("main").map(|w| w.is_visible().unwrap_or(false)).unwrap_or(false);
    let reopen = data_dir().join("host").join(REOPEN);
    let record = serde_json::json!({
        "chat": request["chat"], "view": request["view"], "window": window,
        "from": app.package_info().version.to_string(), "to": active_found.version,
    });
    let _ = std::fs::create_dir_all(data_dir().join("host"));
    let _ = std::fs::write(&reopen, record.to_string());
    if address().is_some() {
        let interrupt = request["interrupt"].as_bool().unwrap_or(false);
        if let Err(error) = post("/api/host/stop", serde_json::json!({"force": interrupt})) {
            // Work started in between: it stays ready, and the click can come again.
            let mut shared = state.lock().unwrap();
            shared.update.phase = "ready".into();
            shared.update.found = Some(active_found);
            shared.update.bytes = Some(active_bytes);
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
    match active_found.install(&active_bytes) {
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
                start_host(app, state);
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

/// `python -m harness.host.login run`: the session host, waited for. When the host ends on
/// its own with a failure, it prints why on its standard output (told).
fn host_child() -> std::io::Result<Child> {
    let mut words = vec!["-m".to_string(), "harness.host.login".to_string(), "run".to_string()];
    words.extend(std::env::args().skip_while(|word| word != "--host").skip(1));
    let words: Vec<&str> = words.iter().map(String::as_str).collect();
    harness(&words).stdout(Stdio::piped()).stderr(Stdio::null()).spawn()
}

/// The login item's host, started and kept. It has no window to say a failure in: when it
/// ends on its own with one, the owner gets a system notification with the reason (as Hermes
/// Desktop's "stopped working in the background" notice), and the window, when it next opens,
/// starts the host again and shows what fails then.
fn start_host(app: &AppHandle, state: &State) {
    let mut child = match host_child() {
        Ok(child) => child,
        Err(error) => {
            log(&format!("the session host: {}: {error}", python().display()));
            return;
        }
    };
    if let Some(mut printed) = child.stdout.take() {
        let app = app.clone();
        thread::spawn(move || {
            let mut said = String::new();
            let _ = std::io::Read::read_to_string(&mut printed, &mut said);
            if let Some(failure) = told(&said) {
                log(&format!("the login item's host ended ({}): {}", failure.code, failure.reason));
                let name = product();
                let title = if chinese() { format!("{name} 在后台停了") } else { format!("{name} stopped in the background") };
                let hint = if chinese() { format!("打开 {name} 看怎么办。") } else { format!("Open {name} to see what to do.") };
                let _ = app.notification().builder().title(title).body(format!("{}\n{hint}", failure.reason)).show();
            }
        });
    }
    let mut shared = state.lock().unwrap();
    shared.host_child = Some(child);
    shared.started_host = true;
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
    // This build's configuration first: its product name is where a .deb's runtime is found.
    let context = tauri::generate_context!();
    let _ = PRODUCT.set(context.config().product_name.clone().unwrap_or_else(|| "The Harness".into()));
    let args: Vec<String> = std::env::args().collect();
    let flag = |name: &str| args.iter().position(|word| word == name);
    if let Some(at) = flag("--autostart") {
        std::process::exit(autostart(args.get(at + 1).map(String::as_str).unwrap_or("default")));
    }
    if flag("--stop-host").is_some() {
        let _ = post("/api/host/stop", serde_json::json!({"force": true}));
        std::process::exit(0);
    }
    if let Some(at) = flag("--path") {
        let words: Vec<&str> = args[at + 1..].iter().map(String::as_str).collect();
        std::process::exit(match path_command(&words) {
            Ok(text) => {
                print!("{text}");
                0
            }
            Err(error) => {
                eprintln!("{error}");
                1
            }
        });
    }
    #[cfg(target_os = "linux")]
    if is_cli_invocation(&args) {
        let mut cmd = Command::new(python());
        cmd.arg("-m").arg("harness").args(args.iter().skip(1));
        if std::env::var_os("HARNESS_HOST_COMMAND").is_none() {
            cmd.env("HARNESS_HOST_COMMAND", launcher());
        }
        cmd.env("PYTHONUTF8", "1");
        if std::env::var_os("APPIMAGE").is_some() {
            cmd.env_remove("PYTHONHOME").env_remove("PYTHONPATH");
        }
        let code = cmd.status().map(|s| s.code().unwrap_or(1)).unwrap_or(1);
        std::process::exit(code);
    }
    let host_mode = flag("--host").is_some();
    if host_mode && !has_display() {
        // A server without a display: the host alone, as the login item's process.
        if take_reopen().is_some() {
            upgrade_installed();
        }
        install_bundled_packages(&|_, _| {});
        let code = host_child().and_then(|child| child.wait_with_output()).map(|output| {
            if let Some(failure) = told(&String::from_utf8_lossy(&output.stdout)) {
                log(&format!("the login item's host ended ({}): {}", failure.code, failure.reason));
            }
            output.status.code().unwrap_or(1)
        });
        std::process::exit(code.unwrap_or(1));
    }

    let state: State = Arc::new(Mutex::new(Shared::default()));
    let setup_state = state.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if argv.iter().any(|word| word == "--focus") {
                if let Some(window) = app.get_window("main") {
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
        // App commands: start_state/retry/open_log are granted only to the local start page
        // (capabilities/default.json); browser_* are granted only to the main webview on
        // http://127.0.0.1:*/* (capabilities/window.json). The "browser" child webview gets none.
        .invoke_handler(tauri::generate_handler![
            start_state,
            retry,
            open_log,
            browser_open,
            browser_bounds,
            browser_nav,
            browser_close
        ])
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
                install_bundled_packages(&|_, _| {});
                start_host(&handle_, &setup_state);
                if window {
                    // An update's restart from an open window: open it again, on its chat.
                    open(&handle_, None);
                }
            } else {
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
        .build(context)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_update_mode_checks_when_it_says() {
        let hour = Some(UPDATE_EVERY);
        let minute = Some(Duration::from_secs(60));
        // default: at start, again after an hour, and when asked
        assert!(due("default", None, false) && due("default", hour, false) && !due("default", minute, false));
        assert!(due("default", minute, true));
        // start: at start only, or when asked
        assert!(due("start", None, false) && !due("start", hour, false) && due("start", hour, true));
        // manual: only when asked
        assert!(!due("manual", None, false) && !due("manual", hour, false) && due("manual", None, true));
        // none: never, not even when asked
        assert!(!due("none", None, false) && !due("none", None, true));
        // an unknown value checks as manual does
        assert!(!due("sometimes", None, false));
    }

    #[test]
    fn a_channel_has_its_own_names() {
        assert_eq!(channel_of("dev\n0.87.0-dev.412\n").as_deref(), Some("dev"));
        assert_eq!(channel_of("stable").as_deref(), Some("stable"));
        // not a channel's name: the build is taken as stable
        assert_eq!((channel_of(""), channel_of("../x"), channel_of("Dev")), (None, None, None));
        assert_eq!((tagged(".harness", "stable"), tagged(".harness", "dev")), (".harness".to_string(), ".harness-dev".to_string()));
    }

    #[test]
    fn a_channels_builds_follow_each_other_by_build_number() {
        assert_eq!((build_number("dev.412"), build_number(""), build_number("rc1")), (Some(412), None, None));
        assert_eq!(newer_build("dev.412", "dev.413"), Some(true));
        assert_eq!(newer_build("dev.413", "dev.413"), Some(false));
        assert_eq!(newer_build("dev.413", "dev.412"), Some(false));
        // a release, on either side: the versions themselves decide
        assert_eq!((newer_build("", "dev.5"), newer_build("dev.5", ""), newer_build("", "")), (None, None, None));
    }

    #[test]
    fn version_newer_supersedes_cached_ready_builds_safely() {
        assert!(version_newer("0.87.0-dev.26", "0.87.0-dev.27"));
        assert!(version_newer("0.87.0-dev.9", "0.87.0-dev.10"));
        assert!(!version_newer("0.87.0-dev.27", "0.87.0-dev.27"));
        assert!(!version_newer("0.87.0-dev.27", "0.87.0-dev.26"));
        assert!(version_newer("0.87.0-dev.27", "0.87.0"));
        assert!(!version_newer("0.87.0", "0.87.0-dev.27"));
        assert!(version_newer("0.87.0", "0.88.0"));
        assert_eq!(update_interval("stable"), UPDATE_EVERY);
        assert_eq!(update_interval("dev"), UPDATE_EVERY_DEV);
    }

    #[test]
    fn the_tray_says_before_the_click_that_windows_closes_the_app() {
        assert_eq!(restart_label("1.2.3", false).contains("closes briefly"), cfg!(windows));
        assert!(restart_label("1.2.3", false).starts_with("Restart to update to 1.2.3"));
        assert_eq!(restart_label("1.2.3", true).contains("会关一下"), cfg!(windows));
        assert!(restart_label("1.2.3", true).starts_with("重启以更新到 1.2.3"));
    }

    #[test]
    fn the_tray_speaks_the_pages_language_else_the_systems() {
        set_language("zh");
        assert!(chinese());
        assert_eq!(tt("退出", "Quit"), "退出");
        set_language("en");
        assert!(!chinese());
        assert_eq!(tt("退出", "Quit"), "Quit");
        // "system" (and anything unknown) falls back to the system's language, whichever it is
        set_language("system");
        let system = chinese();
        set_language("xx");
        assert_eq!(chinese(), system);
        assert_eq!((pause_label(false, true), pause_label(true, true)), ("暂停", "继续"));
        assert_eq!((pause_label(false, false), pause_label(true, false)), ("Pause", "Resume"));
        assert!(command_label(false, false, "the-harness").starts_with("Install 'the-harness'") && command_label(true, false, "the-harness-dev").starts_with("Uninstall 'the-harness-dev'"));
    }

    #[test]
    fn cli_invocation_detection_distinguishes_gui_and_cli_args() {
        let s = |xs: &[&str]| xs.iter().map(|x| x.to_string()).collect::<Vec<_>>();
        assert!(!is_cli_invocation(&s(&["the-harness"])));
        assert!(!is_cli_invocation(&s(&["the-harness", "http://127.0.0.1:8780/?token=abc"])));
        assert!(!is_cli_invocation(&s(&["the-harness", "--focus"])));
        assert!(!is_cli_invocation(&s(&["the-harness", "--host"])));
        assert!(!is_cli_invocation(&s(&["the-harness", "--autostart", "on"])));
        assert!(!is_cli_invocation(&s(&["the-harness", "--stop-host"])));
        assert!(!is_cli_invocation(&s(&["the-harness", "--path", "status"])));
        assert!(is_cli_invocation(&s(&["the-harness", "--version"])));
        assert!(is_cli_invocation(&s(&["the-harness", "--help"])));
        assert!(is_cli_invocation(&s(&["the-harness", "status"])));
        assert!(is_cli_invocation(&s(&["the-harness", "-p", "hi"])));
        assert!(is_cli_invocation(&s(&["the-harness", "hello"])));
    }

    #[test]
    fn browser_url_normalization_allows_only_http_and_https() {
        assert_eq!(parse_browser_url("google.com").unwrap().as_str(), "https://google.com/");
        assert_eq!(parse_browser_url("localhost:3000/app").unwrap().as_str(), "http://localhost:3000/app");
        assert_eq!(parse_browser_url("127.0.0.1:8080").unwrap().as_str(), "http://127.0.0.1:8080/");
        assert_eq!(parse_browser_url("https://github.com/EvolvingLMMs-Lab/the-harness").unwrap().scheme(), "https");
        assert!(parse_browser_url("").is_err());
        assert!(parse_browser_url("file:///etc/passwd").is_err());
        assert!(parse_browser_url("javascript:alert(1)").is_err());
        assert!(parse_browser_url("tauri://localhost/index.html").is_err());
    }

    #[test]
    fn browser_bounds_clamps_and_rejects_collapsed_or_nan_rects() {
        assert_eq!(clamp_browser_bounds(100.0, 40.0, 500.0, 700.0), Some((100.0, 40.0, 500.0, 700.0)));
        assert_eq!(clamp_browser_bounds(-5.0, -2.0, 300.0, 400.0), Some((0.0, 0.0, 300.0, 400.0)));
        assert_eq!(clamp_browser_bounds(10.0, 10.0, 0.0, 400.0), None);
        assert_eq!(clamp_browser_bounds(10.0, 10.0, 15.0, 15.0), None);
        assert_eq!(clamp_browser_bounds(f64::NAN, 10.0, 300.0, 400.0), None);
    }

    #[test]
    fn browser_rect_maps_viewport_fraction_to_exact_physical_pixels() {
        // 1920x1080 physical window at 125% Windows DPI -> 1536x864 CSS viewport
        let rect = resolve_browser_rect(
            1024.0,
            108.0,
            504.0,
            748.0,
            Some(1536.0),
            Some(864.0),
            Some(PhysicalSize::new(1920, 1080)),
        )
        .expect("physical rect");
        assert_eq!(rect.position, Position::Physical(PhysicalPosition::new(1280, 135)));
        assert_eq!(rect.size, Size::Physical(PhysicalSize::new(630, 935)));

        // Overflowing right/bottom edge is clamped strictly inside the host window
        let clamped = resolve_browser_rect(
            1200.0,
            100.0,
            600.0,
            900.0,
            Some(1536.0),
            Some(864.0),
            Some(PhysicalSize::new(1920, 1080)),
        )
        .expect("clamped rect");
        assert_eq!(clamped.position, Position::Physical(PhysicalPosition::new(1500, 125)));
        assert_eq!(clamped.size, Size::Physical(PhysicalSize::new(420, 955)));

        // Without viewport dimensions, falls back cleanly to logical units
        let fallback = resolve_browser_rect(100.0, 50.0, 400.0, 600.0, None, None, None)
            .expect("logical fallback");
        assert_eq!(fallback.position, Position::Logical(LogicalPosition::new(100.0, 50.0)));
        assert_eq!(fallback.size, Size::Logical(LogicalSize::new(400.0, 600.0)));
    }

    #[test]
    fn a_failed_start_is_read_from_what_the_harness_printed() {
        // the host's own log lines may come first; the failure is the last line
        let printed = "harness: starting the session host\n{\"error\": \"the session host exited (1) while starting, in the package agent: ImportError: cannot import name 'X'\", \"code\": \"host_exited\", \"fix\": \"update the package (harness install --update agent) or remove it (harness remove agent), then try again\", \"log\": \"C:\\\\data\\\\logs\\\\host.log\"}\n";
        let failure = told(printed).expect("a failure");
        assert_eq!(failure.code, "host_exited");
        assert!(failure.reason.contains("ImportError") && failure.fix.contains("harness remove agent"));
        assert_eq!(failure.log, "C:\\data\\logs\\host.log");
        // a failure without a fix or a log (a data folder of a newer version) keeps them empty
        let newer = told("{\"error\": \"the data folder was last used by a newer The Harness\", \"code\": \"data_newer\"}").unwrap();
        assert_eq!((newer.code.as_str(), newer.fix.as_str(), newer.log.as_str()), ("data_newer", "", ""));
        // the page's answer, a traceback or nothing is not a failure the harness told
        assert_eq!(told("{\"url\": \"http://127.0.0.1:1\", \"token\": \"t\", \"page\": \"http://127.0.0.1:1/?token=t\"}"), None);
        assert_eq!(told("Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named 'harness'"), None);
        assert_eq!(told(""), None);
    }

    #[test]
    fn what_did_not_install_or_run_is_a_failure_with_the_shells_log() {
        let failed = vec![("agent".to_string(), "ValueError: bad".to_string()), ("app".to_string(), "no space".to_string())];
        let failure = packages_failure(&failed);
        assert_eq!((failure.code.as_str(), failure.reason.as_str()), ("packages", "agent, app"));
        assert!(failure.detail.contains("agent\nValueError: bad") && failure.detail.contains("app\nno space"));
        assert!(failure.log.ends_with("shell.log"));
    }
}
