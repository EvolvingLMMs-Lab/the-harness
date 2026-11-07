# computer

The `computer` package lets the agent use the computer it runs on (Windows, macOS or Linux): it sees the screen or one window and acts with the pointer, the keyboard and the apps' accessibility trees, on a task you give it in a conversation.

What the agent does happens in your accounts and with your files. Alongside the input bounds and physical-input policy, the worker asks before sensitive actions it can identify from the accessibility tree or app shortcuts. Detection depends on what the app exposes.

## Install

```bash
harness install computer
```

The app installs it the first time a conversation needs it. It installs the worker's environment: screen capture, pointer and keys, clipboard pasting, and on each system its window and accessibility backend.

Outside Python:

- **macOS**: allow **Screen Recording** (Screen & System Audio Recording on macOS 15 and later) and **Accessibility** for the app that runs `harness` (the terminal, or the app that started it), in System Settings > Privacy & Security. Screen Recording takes effect when that app starts again.
- **A display of its own on Linux**: Xvfb (`sudo apt install xvfb`; Fedora: `sudo dnf install xorg-x11-server-Xvfb`), or weston with Xwayland (`HARNESS_DISPLAY_SERVER=weston` picks it). With at-spi2-core, which most desktops install, the agent reads the apps' accessibility trees there.
- **A display of its own on Windows**: QEMU (`winget install SoftwareFreedomConservancy.QEMU`) and the Windows Hypervisor Platform (Windows features, then restart), plus a disk image.
- **A display of its own on macOS**: Virtualization.framework for a Tart VM folder or a raw EFI disk; the harness builds its helper with the Xcode command line tools (`xcode-select --install`) the first time. QEMU (`brew install qemu`) works too.

## Use

The simplest way is the app ([The app](https://harness.lmms-lab.com/docs/use/app/)):

```bash
harness
```

Type what you want done. From the terminal:

```bash
harness run "Find flights from Beijing to New York on 2 November and show me the options" --workspace apps
```

`configs/experiments/computer.toml` is the desktop agent with this computer's prompt; its budget is 60 model calls, an hour and $2 an episode. The app's conversations use the core's `configs/assistant.toml`, the same agent with the plan skill.

### Workspaces

A conversation works in a workspace of one of four kinds:

| Workspace | `computer.mode` | Systems | Your mouse and keyboard |
|---|---|---|---|
| This desktop | `desktop` | Windows, macOS, Linux | used as your physical-input policy allows, in turn with other agents |
| Background browser | `browser` | any, with Google Chrome installed | never (see the `browser` package) |
| Apps in the background | `apps` | Windows, macOS, Linux on X11 | only where nothing else reaches the window, and as your policy allows |
| A display of its own | `display` | Linux (a display server), Windows and macOS (a virtual machine) | never |

Choose it in the app beside the model before a conversation's first message. In the terminal chat, use `/settings` to change `computer.mode`. For a suite, pass the workspace explicitly:

```bash
harness run configs/experiments/computer.toml --workspace display --workspaces 4
```

From Python, pass `workspace="display"` to `host.start(...)`. Where a kind cannot run (no Chrome, a Wayland session, no image for a virtual machine), the app hides it and **Settings → Computer** says what is missing.

**Apps in the background** works one window at a time without your focus. The agent reads a window's accessibility tree and acts on its elements (press a button, set a field, check a box), sends clicks and keys to the window itself, and drives a Chrome or Electron app it launched over DevTools. Apps it starts open off your screens until it or you bring them on (`use_window(..., visible=True)`). Your own windows stay out of its sight unless a rule under "your windows" lets it see one ([Permissions](https://harness.lmms-lab.com/docs/configure/permissions/)); it then chooses one with `use_window`. On Linux this needs an X11 session: Tk, Qt and Motif apps take sent clicks and keys, GTK apps give their trees but not sent events.

**A display of its own** on Linux is an X display you never see: the apps the agent launches run there, and its clicks and keys use that display's own pointer and keyboard. On Windows and macOS it is a virtual machine started from an image you choose, with no window on your screen. Each machine runs over a copy-on-write layer of the image, deleted when the workspace ends, so the image never changes. Set `computer.vm_image` in Settings, or pass it to a run:

```bash
harness run configs/experiments/computer.toml --workspace display --vm-image PATH --workspaces 2
```

The image is an x86-64 desktop as qcow2, vmdk, vhdx, vdi, raw or a live ISO, a VMware folder, or on macOS a Tart VM folder. On a macOS guest, the machine's screen is the guest's screen sharing, so turn that on in the guest; the user is the `vm_user` setting and the password `$HARNESS_VM_PASSWORD` (both `admin` by default, as in Tart's images).

### While it works

- **Hands off.** While you move the pointer (on Windows also any key or click), its steps wait until you leave the computer alone for 2 s, and it looks at the screen again.
- **Your windows stay yours.** If you bring another window to the front, it stops as after **Take over**; **Hand back** lets it go on.
- **Stop at once** by pushing the pointer into a corner of the screen. **Stop**, **Esc**, `/pause` and `/end` stop it more gently ([Interrupt and take over](https://harness.lmms-lab.com/docs/use/interrupt/)).
- **It asks you** before a step that is yours, such as logging in or paying.
- **Any text types as it is**: text is pasted through the clipboard, which is put back afterwards.
- **Several monitors**: it sees the one with the active window and follows it; `use_screen(2)` holds one monitor, `use_screen()` follows again.

## What it provides

- **Embodiment `computer`**: this computer's screen, pointer, keyboard and windows, with the desktop shield.
- **Bench `computer`**: one task, `free`; the instruction is yours.
- **Skill `desktop`**: `click`, `drag`, `scroll`, `type_text`, `press`, `wait`, screenshots, `show`, `finish`; `windows`, `use_window`, `launch`, and element actions (`elements`, `act`).
- **Skill `screens`**: `screens()` lists the monitors, `use_screen()` picks or follows one.
- **Skill `plan`**: a plan you see while it works, its steps checked off.
- **Skill `chat`**: the chat comes to the front when the agent's turn ends, unless the result is on the screen (`stay_on_screen`).
- **Experiments**: `configs/experiments/computer.toml` (the app's conversations: the core's `configs/assistant.toml`).

## Settings

Set in the app under **Settings → Computer** or in the terminal chat under `/settings`.

| Key | Default | |
|---|---|---|
| `mode` | `browser` | the workspace new conversations start in: `desktop`, `browser`, `apps`, `display` |
| `monitor` | 1 | the monitor it starts on (1 is the primary) |
| `max_side` | 1920 | screenshots are scaled to at most this many pixels on the long side |
| `step_limit` | 300 | input steps a conversation may take |
| `workspaces` | 4 | workspaces of any kind that work at once |
| `displays` | 2 | displays of their own that run at once |
| `display_backend` | `auto` | `auto` (Linux: a display server; elsewhere a virtual machine), `local`, `vm` (a virtual machine on Linux too, with KVM) |
| `vm_image` | empty | the disk image a display workspace's virtual machine starts from |
| `vm_hypervisor` | `auto` | `auto`, `qemu`, `vz` (macOS Virtualization.framework) |
| `vm_memory`, `vm_cpus` | 2048, 2 | each virtual machine's memory (MiB) and processors |
| `vm_accel` | `hardware` | `hardware` only, or `any`: software emulation where the hypervisor is missing (much slower) |

When the agent may use your real mouse and keyboard, and what its model learns of your other windows, are the `physical` and `privacy` settings ([Permissions](https://harness.lmms-lab.com/docs/configure/permissions/)). For one session: `--physical LEVEL`, `--allow-app`, `--deny-app`, `--window-details LEVEL`.

## Limits and known issues

- Every screenshot goes to the model provider. Close what the task does not need, and use a browser profile of its own. Screenshots are also kept in the conversation's trace on this computer.
- A Wayland session gives other programs neither window pictures nor input, so there only **This desktop** and **A display of its own** work.
- A virtual machine boots cold every time (QEMU cannot save its state under the Windows Hypervisor Platform). `windows()`, `launch()` and element ids do not reach inside it: the agent opens apps from the machine's own desktop. Under QEMU its keyboard types US ASCII.
- On macOS, without the two permissions the apps and desktop workspaces do not start, and say which is missing.
