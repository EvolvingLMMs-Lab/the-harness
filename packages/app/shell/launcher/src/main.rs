//! The `harness` command of the desktop app on Windows: runtime\bin\harness.exe, whose folder
//! the installer puts on the user's PATH. It runs the harness with the app's bundled Python
//! (runtime\python\python.exe -m harness ARGS), so a terminal uses the version the app has.
//!
//! A program and not a .cmd file, as Ollama's installer brings `ollama.exe`: any program can
//! start it without a shell, its exit status is the harness's, and Ctrl+C in it goes to the
//! harness without cmd's "Terminate batch job (Y/N)?".
//!
//! A login item the harness registers from a terminal (harness host install, the first run's
//! question) starts the app's shell in host mode, as the one the app registers does:
//! HARNESS_HOST_COMMAND names it (harness/host/login.py), unless the caller set its own.

use std::path::{Path, PathBuf};
use std::process::Command;

const HOST_COMMAND: &str = "HARNESS_HOST_COMMAND";

/// The JSON list ["SHELL", "--host"]: what the login item runs.
fn host_command(shell: &Path) -> String {
    let mut text = String::from("[\"");
    for c in shell.to_string_lossy().chars() {
        match c {
            '"' => text.push_str("\\\""),
            '\\' => text.push_str("\\\\"),
            c if (c as u32) < 0x20 => text.push_str(&format!("\\u{:04x}", c as u32)),
            c => text.push(c),
        }
    }
    text.push_str("\", \"--host\"]");
    text
}

/// The shell's file name beside `runtime`: the-harness, or the channel's own (the-harness-dev)
/// when runtime\channel names one, as the installers' build writes it.
fn shell_name(runtime: &Path) -> String {
    let channel = std::fs::read_to_string(runtime.join("channel")).unwrap_or_default();
    let channel = channel.split_whitespace().next().unwrap_or("stable");
    let name = if channel == "stable" { "the-harness".to_string() } else { format!("the-harness-{channel}") };
    if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name
    }
}

/// The folder `runtime` this program is in the `bin` of: runtime\bin\harness.exe.
fn runtime() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    Some(exe.parent()?.parent()?.to_path_buf())
}

#[cfg(windows)]
mod console {
    #[link(name = "kernel32")]
    extern "system" {
        fn SetConsoleCtrlHandler(handler: Option<unsafe extern "system" fn(u32) -> i32>, add: i32) -> i32;
    }

    /// Ctrl+C (0) and Ctrl+Break (1) are handled here by doing nothing; closing the console,
    /// logging off and shutting down end this process as usual.
    unsafe extern "system" fn handler(event: u32) -> i32 {
        (event <= 1) as i32
    }

    /// Ctrl+C belongs to the harness, which gets it from the same console: this process only
    /// waits for it and hands its exit status on.
    pub fn leave_interrupts_to_the_child() {
        unsafe {
            SetConsoleCtrlHandler(Some(handler), 1);
        }
    }
}

fn main() {
    let Some(runtime) = runtime() else {
        eprintln!("harness: cannot tell where this program is");
        std::process::exit(1);
    };
    let python = runtime.join("python").join(if cfg!(windows) { "python.exe" } else { "bin/python3" });
    let mut command = Command::new(&python);
    command.arg("-m").arg("harness").args(std::env::args_os().skip(1));
    if std::env::var_os(HOST_COMMAND).is_none() {
        let shell = runtime.parent().unwrap_or(&runtime).join(shell_name(&runtime));
        command.env(HOST_COMMAND, host_command(&shell));
    }
    #[cfg(windows)]
    console::leave_interrupts_to_the_child();
    match command.status() {
        Ok(status) => std::process::exit(status.code().unwrap_or(1)),
        Err(error) => {
            eprintln!("harness: the Python runtime of The Harness did not run ({}: {error})", python.display());
            eprintln!("  install The Harness again; your settings, chats and data stay");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_login_item_command_is_a_json_list_with_the_path_escaped() {
        assert_eq!(host_command(Path::new(r"C:\Users\a b\The Harness\the-harness.exe")), r#"["C:\\Users\\a b\\The Harness\\the-harness.exe", "--host"]"#);
        assert_eq!(host_command(Path::new("/opt/say \"hi\"/the-harness")), r#"["/opt/say \"hi\"/the-harness", "--host"]"#);
        assert_eq!(host_command(Path::new("C:\\用户\\应用\\the-harness.exe")), "[\"C:\\\\用户\\\\应用\\\\the-harness.exe\", \"--host\"]");
    }
}
