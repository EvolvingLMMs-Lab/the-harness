---
title: "Desktop app"
description: "Install The Harness desktop app on Windows, macOS or Linux, get past the unsigned-app warning on first open, keep it running at login, and remove it."
---

The desktop app is The Harness with everything it needs in one installer: its own Python
runtime, the Harness itself and a window with a tray icon. You do not need Python. Developers
can keep using `pip install the-harness` ([Install](/docs/getting-started/install/)).

Download the installer for your system from the
[latest release](https://github.com/EvolvingLMMs-Lab/the-harness/releases/latest):

| System | File |
|---|---|
| Windows | `The.Harness_X.Y.Z_x64-setup.exe` (or the `.msi`) |
| macOS (Apple silicon) | `The.Harness_X.Y.Z_aarch64.dmg` |
| Linux | `The.Harness_X.Y.Z_amd64.AppImage` or `The.Harness_X.Y.Z_amd64.deb` |

## First open: the unsigned-app warning

The installers are not code-signed yet, so the system warns the first time you open one.
This happens once.

**Windows.** Microsoft Defender SmartScreen shows "Windows protected your PC" and names an
unknown publisher. Click **More info**, check that the app is `The.Harness_…_x64-setup.exe`,
then click **Run anyway**.

**macOS.** Open the `.dmg` and drag **The Harness** into **Applications**. The first time you
open it, macOS says it cannot verify the developer. Click **Done**, open **System Settings ›
Privacy & Security**, scroll to the message about The Harness and click **Open Anyway**, then
confirm with your password. The first time it starts at login, macOS also shows a "Background
item added" notice; that is the login item below.

**Linux.** An AppImage needs to be made executable (`chmod +x The.Harness_*.AppImage`) and
needs FUSE 2 (`libfuse2` on Ubuntu). A `.deb` installs with
`sudo apt install ./The.Harness_X.Y.Z_amd64.deb` and adds the `harness` command.

## Running at login

The installer turns on starting at login, as Ollama does, so after a restart your agent
carries on by itself. The login item is the system's own:

| System | Login item |
|---|---|
| Windows | a scheduled task "The Harness host", or a launcher in your Startup folder where tasks are not allowed |
| macOS | a LaunchAgent, `~/Library/LaunchAgents/com.lmms-lab.harness.host.plist` |
| Linux | a systemd user service, `harness-host.service` |

The tray menu's **Start at login** and the setting `agent.autostart` show whether that item
exists and switch it. In a terminal:

```bash
harness host install     # start at login
harness host status      # whether it does, as the system has it
harness host uninstall   # no longer start at login
```

If you remove the item in the system's own settings, The Harness shows it as off too.

On a Linux server, a user service runs without anyone logged in only with lingering on;
`harness host install` says so when it is off:

```bash
sudo loginctl enable-linger "$USER"
```

## The tray

Closing the window keeps The Harness running in the tray (the menu bar on macOS). The tray
menu has **Open The Harness**, **Pause** (the agent stops waking and acting; its channels
stay connected and what happens meanwhile is handled after you resume), **Start at login**
and **Quit** (work in progress ends as cancelled, then the agent stops until you open the app
or log in again). System notifications come only for what you must decide or know: an
approval request, the spending limit reached, an action that failed or ended unknown, and an
expired channel login.

## Updates

The app updates itself from GitHub Releases. Each update is checked against The Harness's
update key before it installs, separately from code signing.

## Install without a window

For a computer you reach only over SSH:

```bash
# Linux (.deb), then as the user who owns the agent
sudo apt install ./The.Harness_X.Y.Z_amd64.deb
harness host install
sudo loginctl enable-linger "$USER"
```

```powershell
# Windows: installs for the current user and turns on starting at login
.\The.Harness_X.Y.Z_x64-setup.exe /S
```

## Remove it

Uninstall it the way your system removes apps (Windows: **Settings › Apps**; macOS: move it
from **Applications** to the Bin; Linux: `sudo apt remove the-harness` or delete the
AppImage). Run `harness host uninstall` first on macOS and Linux to remove the login item.
Your data stays in `~/.harness/`, as with `pip uninstall`.
