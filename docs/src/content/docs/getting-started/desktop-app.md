---
title: "Desktop app"
description: "Install The Harness desktop app on Windows, macOS or Linux, get past the unsigned-app warning on first open, keep it running at login, and remove it."
---

The desktop app is The Harness with everything it needs in one installer: its own Python
runtime, the Harness itself and a window with a tray icon. You do not need Python. Developers
can keep using `pip install the-harness` ([Install](/docs/getting-started/install/)).
[The app](/docs/use/app/) describes the window and its keys.

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
`sudo apt install ./The.Harness_X.Y.Z_amd64.deb` and adds the `the-harness` command.

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
the-harness host install     # start at login
the-harness host status      # whether it does, as the system has it
the-harness host uninstall   # no longer start at login
```

If you remove the item in the system's own settings, The Harness shows it as off too.

On a Linux server, a user service runs without anyone logged in only with lingering on;
`the-harness host install` says so when it is off:

```bash
sudo loginctl enable-linger "$USER"
```

## The `the-harness` command

The app brings the `the-harness` command for terminals. It runs with the app's own Python, so a
terminal uses the same version as the app and updates with it.

| System | Where it is |
|---|---|
| Windows | `runtime\bin\harness.exe` in the install folder. The installer adds that folder to your PATH (the `.exe` installer to your user's, the `.msi` to the computer's) and removes it when you uninstall |
| macOS | choose **Install 'harness' command in PATH** in the menu bar menu. It links `/usr/local/bin/harness` to the app; macOS asks for an administrator's password when that folder needs one. **Uninstall 'harness' command from PATH** removes the link |
| Linux | the `.deb` installs `/usr/bin/harness`; an AppImage has no command |

Open a new terminal after installing and check it:

```bash
the-harness --version
```

If another `harness` is already on your PATH (from `pip` or `uv`), terminals keep running that
one. It works on the same data folder as the app but does not update with it, and two
versions on one data folder get in each other's way. The last page of the Windows installer
says so and names the file. Remove the other one, then open a new terminal:

```bash
pip uninstall the-harness        # or: uv tool uninstall the-harness
```

## The tray

Closing the window keeps The Harness running in the tray (the menu bar on macOS). The tray
menu has **Open The Harness**, **Pause** (the agent stops waking and acting; its channels
stay connected and what happens meanwhile is handled after you resume), **Start at login**
and **Quit** (work in progress ends as cancelled, then the agent stops until you open the app
or log in again). System notifications come only for what you must decide or know: an
approval request, the spending limit reached, an action that failed or ended unknown, and an
expired channel login. The tray menu and these notifications are in the app's language
(**Settings › General › Language**), which follows the system's unless you choose one.

## If it does not start

When The Harness cannot start, its window says why instead of waiting: what went wrong, what
to do about it and where the log is, with **Try again** and **Open the log**. That covers the
packages it brings not installing on the first start, its background service stopping while it
starts or not answering, and a data folder last used by a newer version (install the newest
app; your data stays). If it stops in the background while no window is open, a system
notification says so, and opening the window starts it again.

## Updates

The app updates itself from GitHub Releases. Each update is checked against The Harness's
update key before it installs, separately from code signing.

### The dev channel

**The Harness Dev** is the build of the newest code, for trying changes before they are
released. It is an app of its own beside The Harness, as VS Code Insiders is beside VS
Code, so both can be installed and open at the same time:

| | The Harness | The Harness Dev |
|---|---|---|
| Icon | cyan cursor | amber cursor |
| Terminal command | `harness` | `the-harness-dev` |
| Your data | `~/.harness` | `~/.harness-dev` |
| What it installs | `~/.cache/harness` | `~/.cache/harness-dev` |
| Updates from | the latest release | the [`dev` prerelease](https://github.com/EvolvingLMMs-Lab/the-harness/releases/tag/dev) |

It shares nothing with The Harness: the first time it opens it goes through its own first
run, with a model of its own. Install it once from the `dev` prerelease; after that it
offers **Restart to update** whenever a newer build is there. It is unstable by design.

## Install without a window

For a computer you reach only over SSH:

```bash
# Linux (.deb), then as the user who owns the agent
sudo apt install ./The.Harness_X.Y.Z_amd64.deb
the-harness host install
sudo loginctl enable-linger "$USER"
```

```powershell
# Windows: installs for the current user and turns on starting at login
.\The.Harness_X.Y.Z_x64-setup.exe /S
```

## Remove it

Uninstall it the way your system removes apps (Windows: **Settings › Apps**; macOS: move it
from **Applications** to the Bin; Linux: `sudo apt remove the-harness` or delete the
AppImage). On Windows this also removes the login item and the PATH entry. On macOS and Linux
run `the-harness host uninstall` first to remove the login item, and on macOS choose **Uninstall
'harness' command from PATH** first to remove the link. Your data stays in `~/.harness/`, as
with `pip uninstall`.
