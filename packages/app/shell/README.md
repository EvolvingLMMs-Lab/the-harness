# The Harness desktop shell

A [Tauri 2](https://v2.tauri.app/) window over the app page the session host serves, a tray
icon that keeps it running with the window closed, and system notifications. It holds no
state of the agent: it starts or finds the host with the bundled Python
(`python -m harness.host.login page`), switches the login item with `harness host
install/uninstall/status`, and pauses, resumes and stops through the host's HTTP API.

| Part | What it does |
|---|---|
| Window | the host's page; closing it hides it into the tray |
| Tray | Open The Harness, Pause/Resume (`/api/agent/pause`, `/api/agent/resume`), Start at login (the login item as the system has it), Quit (`/api/host/stop`, then exit) |
| Notifications | `/api/agent/notifications`, only `approval`, `limit`, `failed`, `login`, while the window is not in front |
| Updater | GitHub Releases `latest.json`, checked by `app.update` (default: at start and every hour; start; manual; none), downloaded and verified with the Tauri updater key (`plugins.updater.pubkey`, filled at build time) in the background; it installs only on Restart to update (the page's button through `/api/app/update`, or the tray), after the agent's work reaches a stopping point or the owner interrupts it; the host is stopped, the update installs, the shell restarts on the chat that was open (`DATA/host/shell-reopen.json`) and runs `harness install --update` |
| `--host` | the login item's process: the session host, waited for, plus the tray when there is a display |
| `--focus`, `URL` | what `harness app` starts it with |

## Layout

- `src-tauri/src/main.rs`: the shell.
- `src-tauri/tauri.conf.json`: bundles, the runtime as a resource, the NSIS hooks, the updater.
- `src-tauri/windows/hooks.nsh`: the NSIS installer turns starting at login on (once) and stops
  the host before replacing files.
- `src-tauri/linux/harness`: the `harness` command of the `.deb`.
- `src-tauri/runtime/`: filled by `tools/installers/build.py` (python-build-standalone with the
  Harness wheel, and the `agent` and `app` package folders the shell installs on first start).
- `frontend/index.html`: shown while the host starts.

## Build

```bash
python tools/installers/build.py                  # this system's installers
python tools/installers/build.py --stage-only     # only the runtime, then: cd packages/app/shell && cargo tauri dev
```

The release workflow `.github/workflows/installers.yml` builds Windows, macOS and Linux on a
tag and adds the installers and `latest.json` to the release.

## Updater keys

The updater's key pair is separate from code signing. Generate it once:

```bash
npx tauri signer generate -w ~/.tauri/the-harness.key
```

Put the public key in the repository variable `TAURI_UPDATER_PUBKEY` (or
`tools/installers/updater.pub`, which wins only when the variable is empty) and the private key and its password in the secrets
`TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`. Never commit the private
key. Without the keys the installers build without update bundles and the shell does not
check for updates.

What users see on first open of the unsigned installers is in the documentation:
`docs/src/content/docs/getting-started/desktop-app.md`.
