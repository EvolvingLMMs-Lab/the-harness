fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                "start_state",
                "retry",
                "open_log",
                "browser_open",
                "browser_bounds",
                "browser_nav",
                "browser_close",
            ]),
        ),
    )
    .expect("failed to run tauri-build");
}
