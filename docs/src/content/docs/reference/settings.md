---
title: "Settings"
description: "The keys of ~/.harness/config.toml: every section and key, its values and default, and what it does."
---

Your settings are kept in one file, `~/.harness/config.toml` (or `config.toml` in
`$HARNESS_DATA` when it is set), with your model and keys. `harness` writes it on its
first run; the app's **Settings** page and the terminal interface change it, and you can
edit it by hand. A file holds only the values that were changed; every other key has its
default. A value that no longer passes its check falls back to the default.

```toml
[model]
provider = "openrouter"
model = "deepseek/deepseek-v4.1-flash"
reasoning_effort = "low"

[keys]
OPENROUTER_API_KEY = "sk-or-..."

[limits]
max_steps = 30

[[physical.rules]]
level = "allow"
app = "code"
```

Each key below is written `section.key`: `limits.max_steps` is `max_steps` under
`[limits]`. The rules of the two graded policies are lists of tables
(`[[physical.rules]]`, `[[privacy.rules]]`).

`/settings` in `harness` lists every key, those packages add too, and changes one;
it refuses a value outside its bounds with the reason.

## model and keys

| Key | Values (default) | What it does |
|---|---|---|
| `model.provider` | a provider of [Models and providers](/docs/configure/models/) (default `openrouter`) | who serves the model |
| `model.model` | the provider's model id (default `deepseek/deepseek-v4.1-flash`) | the model the agent uses |
| `model.base_url` | an address (default none) | another endpoint for the provider, such as a proxy; required for `custom` |
| `keys.<VARIABLE>` | the key | a provider's or a connector's key, by the name of its variable (`OPENROUTER_API_KEY`); a key in the environment wins |

The other `model` keys, its advanced settings, are listed under [model](#model) below.

## packages

| Key | Values (default) | What it does |
|---|---|---|
| `packages.auto_install` | `official`, `ask`, `off` (default `official`) | what happens when a task needs something no installed package provides: install it from the official registry, ask first, or stop and say which package to install |
| `packages.registry` | an https address or a folder (default empty: the official registry) | where packages come from; `HARNESS_REGISTRY` wins |

The packages you installed and the projects you trusted are kept under `[packages]` too;
`harness install` and `harness remove` change them ([Packages](/docs/configure/packages/)).

### When a change takes effect

| Settings | Take effect |
|---|---|
| `model`, `approvals`, `limits`, `personal`, and `computer` keys that shape a conversation (`mode`, `monitor`, `max_side`, `step_limit`, the browser and virtual machine keys) | when the next conversation starts; a conversation that runs keeps the values it started with |
| `computer.workspaces`, `computer.chromes`, `computer.displays` | at once: the pool of workspaces follows them |
| `physical`, `privacy` | at once: the workers read them each time they change |
| `general` | on the app's page at once; `open_browser` the next time the app starts |
| `data.keep_days` | the next time the app starts |

See [Permissions](/docs/configure/permissions/) for how the physical-input and window-details
levels and their rules work, and [CLI workspaces](/docs/use/cli/) for the Settings page.

## general

| Key | Values (default) | What it does |
|---|---|---|
| `general.language` | `system`, `zh`, `en` (default `system`) | the language of the app's page; `system` follows the browser |
| `general.theme` | `system`, `light`, `dark` (default `system`) | light or dark page; `system` follows the computer |
| `general.open_browser` | `true`, `false` (default `true`) | open the app's page in the browser when the app starts |
| `general.notifications` | `true`, `false` (default `true`) | a notification when the agent asks something or finishes, while the page is in the background |

## model

| Key | Values (default) | What it does |
|---|---|---|
| `model.reasoning_effort` | `default`, `low`, `medium`, `high` (default `default`) | how much the model reasons before it answers; `default` keeps the provider's. More is slower and costs more |
| `model.max_output_tokens` | 0 to 200000 (default 0) | the longest reply, in tokens; 0 keeps the harness's default |
| `model.checker` | text, at most 200 characters (default empty) | a model of the same provider that checks the result; empty uses the model itself |
| `model.vision` | text, at most 200 characters (default empty) | a model of the same provider that reads images, asked to describe a view when the main model reads none; empty: such a model is told the view was not sent and works from text |
| `model.think_while_acting` | `default`, `on`, or `off` | Accepted for older configurations; it has no effect. Every program runs as a unit and the model's turn is its own while one runs. |
| `model.think_interval` | 0 to 600 seconds | Retained for older configurations. |

## session

| Key | Values (default) | What it does |
|---|---|---|
| `session.environment` | `ask`, `last` or a workspace kind (default `ask`) | where a new conversation works when none is named: `ask` asks at the start of every conversation, with the last choice highlighted; `last` takes the last choice without asking; a kind (`none`, `project`, `browser`, `apps`, `desktop`, `display`) always takes that one. Where nobody can be asked, `ask` is an error that names the option |
| `session.agents` | `off`, `on` (default `off`) | sub-agents in new conversations: `off` does not load their calls and prompt (you can switch them on in a conversation, and the agent may ask you to); `on` loads them from the start, as deep as `limits.agent_depth` allows |

## environments

| Key | Values (default) | What it does |
|---|---|---|
| `environments.attach` | `never`, `ask_each`, `ask_once_session`, `allow` (default `ask_once_session`) | when an agent may take another environment into its conversation, where no rule says otherwise. Each attachment and its reason is shown and recorded whether or not it asked. With `physical.level = "allow"` it does not ask; `never` still refuses. Applies at once |
| `environments.rules` | a list of `{level, kind}` (default empty) | a level for one environment kind (`desktop`, `apps`, `display`, `browser`, `project`); it wins over `environments.attach`. Applies at once |

## approvals

| Key | Values (default) | What it does |
|---|---|---|
| `approvals.ask` | `sensitive`, `programs` (default `sensitive`) | Sensitive operations require one approval per request. `programs` also requires approval before each program. **Ask before acting** overrides the setting for one conversation. A saved `limits.ask_before_acting = true` is read as `programs` |

## limits

| Key | Values (default) | What it does |
|---|---|---|
| `limits.max_steps` | 1 to 1000 (default 60) | model calls one task may take |
| `limits.max_minutes` | 1 to 1440 (default 360) | minutes a conversation may run |
| `limits.agent_depth` | 0 to 4 (default 1) | once sub-agents are on (`session.agents`), how deep agents may start them; their steps and minutes come out of the conversation's: 0 none; 1 the conversation's agent may and its sub-agents may not; 2 theirs may too; and so on |

## learning

| Key | Values (default) | What it does |
|---|---|---|
| `learning.mode` | `on`, `replay_always`, `frozen` (default `on`) | the default mode of a learning library you select |
| `learning.active_minutes` | 1 to 240 (default 30) | minutes of live time a "learn this environment" conversation takes |
| `learning.admission` | `off`, `fixture`, `own_test` (default `fixture`) | how a skill or reactive rule the agent wrote itself is admitted: only by a fixture this computer provides (`fixture`), also by the entry's own test run by the host where the environment is not physical (`own_test`), or never (`off`). `HARNESS_LEARNING_ADMISSION` wins over it. See [How code is admitted](/docs/learn/while-working/#how-code-is-admitted) |

## computer

| Key | Values (default) | What it does |
|---|---|---|
| `computer.mode` | `desktop`, `browser`, `apps`, `display` (default `browser`) | the computer kind a new conversation's environment choice highlights before you have made one (`session.environment` asks for each conversation): `desktop` controls this computer's screen, mouse and keyboard; `browser` searches and browses in an isolated headless Chrome without your logins; `apps` works in this computer's applications in the background, off your screen and without your mouse and keyboard (Windows, macOS, Linux on X11); `display` runs applications on a display of the conversation's own that you never see (Linux: a display server; Windows and macOS: a virtual machine) |
| `computer.monitor` | 1 to 16 (default 1) | desktop mode: the monitor the agent starts on, 1 being the primary; it follows the active window to the others |
| `computer.max_side` | 640 to 3840 (default 1920) | screenshots are scaled to at most this many pixels on the long side; smaller is cheaper and faster, larger shows small text better |
| `computer.step_limit` | 10 to 5000 (default 300) | mouse and keyboard steps a conversation may take |
| `computer.workspaces` | 1 to 16 (default 4) | conversations that may work at once, each in a workspace of its own (a background browser, the desktop); a conversation beyond it waits for one to end |
| `computer.chromes` | 1 to 16 (default 1) | headless Chromes the background browsers share, each conversation in a context of its own (no shared logins or cookies) |
| `computer.browser_windows` | `off`, `tiled` (default `off`) | `off`: background browsers are headless; `tiled`: each conversation's or agent's browser is a window, tiled on a screen, to watch or record them |
| `computer.browser_display` | text, at most 40 characters (default empty) | `tiled`: the X display the windows open on, such as `:99`; empty is this computer's own screen |
| `computer.browser_area` | `x,y,width,height` (default `0,0,1920,1080`) | `tiled`: the part of the screen the windows are tiled in; width and height above 0 |
| `computer.record_screen` | `off`, `on` (default `off`) | `tiled`: record the screen the windows are on for each conversation (`screen.mkv` beside its trace, each frame with its time), for [`harness replay`](/docs/use/replay/) |
| `computer.browser_locale` | a language tag such as `en-US`, or `system` (default `system`) | the language a background browser asks websites for (its pages' `navigator.language`, `Accept-Language`, dates and numbers); `system` uses this computer's |
| `computer.displays` | 0 to 16 (default 2) | display workspaces (a display server or a virtual machine each) that may run at once; a new one beyond it waits |
| `computer.display_backend` | `auto`, `local`, `vm` (default `auto`) | what a display workspace runs on: `auto` is a display server on Linux and a virtual machine on Windows and macOS; `local` a display server (Linux); `vm` a virtual machine |
| `computer.vm_image` | text, at most 200 characters (default empty) | the disk image a display workspace's virtual machine starts from: an x86-64 desktop as qcow2, vmdk, vhdx, vdi, raw or a live ISO, a VMware folder, or on macOS a Tart VM folder. Each workspace runs over a layer of its own, deleted when it ends; the image is never changed |
| `computer.vm_hypervisor` | `auto`, `qemu`, `vz` (default `auto`) | `auto`: QEMU, and on macOS Virtualization.framework for a Tart folder or a raw disk; `qemu`; `vz`: macOS's Virtualization.framework |
| `computer.vm_memory` | 512 to 65536 MiB (default 2048) | memory of each display workspace's virtual machine |
| `computer.vm_cpus` | 1 to 64 (default 2) | processors of each display workspace's virtual machine |
| `computer.vm_accel` | `hardware`, `any` (default `hardware`) | `hardware`: only with the system's hypervisor (Windows Hypervisor Platform, macOS, KVM); `any`: software emulation where it is missing, much slower |
| `computer.vm_user` | text, at most 100 characters (default `admin`) | the guest's user for its screen sharing (a Virtualization.framework machine); its password is `$HARNESS_VM_PASSWORD`, default `admin` |

## physical

When an agent may use your real mouse and keyboard. Input sent to a window in the
background never needs it; this policy decides only the steps that would.

| Key | Values (default) | What it does |
|---|---|---|
| `physical.level` | levels, strictest first: `never`, `ask_each`, `ask_once_app`, `ask_once_session`, `when_idle`, `allow` (default `ask_once_app`) | the level where no rule says otherwise: never; ask before every step; ask the first time in each app; ask once per session; only while you leave the computer alone, stopping the moment you touch it; allow (still taking turns for the input and yielding to you) |
| `physical.rules` | a list of at most 200 rules (default none) | each rule `{level, session, agent, app, window, action, idle_seconds}` sets a level where its scopes match: a session, an agent, an app (its process name, or a glob such as `chrome*`), a window (part of its title, or a glob), a kind of action (`pointer`, `drag`, `keyboard`, `clipboard`, `foreground`). The most specific matching rule wins: more scopes first, then the narrower scope (window, app, agent, session, action), then the later rule. A step of several kinds takes the strictest |
| `physical.idle_seconds` | 0.0 to 600.0 (default 2.0) | `when_idle`: seconds you leave the computer alone before an agent may act; a rule may carry its own |
| `physical.max_hold_seconds` | 0.5 to 60.0 (default 3.0) | when agents take turns, each keeps the input at most this long, then hands it to the next one waiting |
| `physical.yield_on_user_input` | `true`, `false` (default `true`) | refuse an agent's step while you use the mouse or keyboard |
| `physical.corner_stop` | `true`, `false` (default `true`) | moving the pointer into a corner of the screen stops the agent |

When a level asks, your answer keeps for this step, this app, the whole session, or
always (a rule added to `physical.rules`).

## privacy

What the model learns of the windows the agent does not own. It owns the windows it
launched or works in, and every window of a display workspace; of those it learns
everything.

| Key | Values (default) | What it does |
|---|---|---|
| `privacy.level` | levels, strictest first: `none`, `presence`, `apps`, `titles` (default `presence`) | the level where no rule says otherwise: `none` nothing, not even that another window is in front; `presence` only that another window is in front; `apps` the app of each other window too; `titles` their titles too. In the desktop workspace its screenshots still show your screen |
| `privacy.rules` | a list of at most 200 rules (default none) | each rule `{level, session, agent, workspace, app, window}` sets a level where its scopes match: a session, an agent, a workspace kind (`desktop`, `apps`, `display`), an app (its process name, or a glob), a window (part of its title, or a glob). The most specific matching rule wins: more scopes first, then the narrower scope (window, app, workspace, agent, session), then the later rule |

## personal

| Key | Values (default) | What it does |
|---|---|---|
| `personal.about` | text, at most 4000 characters (default empty) | what the agent should know about you; added to every new conversation |
| `personal.instructions` | text, at most 4000 characters (default empty) | how you want the agent to work; added to every new conversation, in your words |

## data

| Key | Values (default) | What it does |
|---|---|---|
| `data.keep_days` | 0 to 3650 (default 0) | conversations older than this many days are deleted when the app starts; 0 keeps them all |
