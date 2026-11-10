---
title: Changelog
---

The first public snapshot is being prepared. Changes to public releases will be recorded here.

## 0.81.2

Costs are no longer shown or limited. Only OpenRouter reports what a call cost, so every other provider showed $0 and a dollar limit applied on OpenRouter alone. The terminal chat's status line, `/sessions` and `harness sessions` (the spent column now counts model calls), the timeline's usage lines and sub-agent reports show no dollars. Settings has no `limits.max_cost_usd` (a saved value is ignored, an update naming it is refused), and conversations the session host starts get no cost budget: the assistant's $5 default is gone, model calls and minutes still bound them. Traces and summaries still record `cost_usd`; an experiment's `[budget] max_cost_usd`, the host API's `budget.max_cost_usd` and the evaluation reports are unchanged. The app drops its cost display, the cost fields of Settings and of calendar tasks, and TapTab's daily and per-run cost caps (app 0.9.2). Checked: the new `tests/test_cost_hidden.py` (timeline lines, the sessions cell, the status line, the setting) and the app's `tests/test_no_cost_limit.py` (background work starts past the old daily budget, with a budget of calls and seconds only) fail on 0.81.1 and pass; on 0.81.1 the status line read `$0.2842` after one reply and one sub-agent report. Scoped reply-display, terminal-details, CLI, packages, model-attribution, environment-choice and first-use tests pass; the app's settings test passes. The app and the terminal chat were not driven live. No full suite.

## 0.81.1

A new installation installs the package of the environment a task needs. With no environment package installed, `harness run "..." --folder .` and `--workspace project` ended with "no installed package provides workspace", and a new conversation offered only "no environment": packages were installed on first use for benches, skills and services, but an environment was looked for among installed packages only. A package now declares the environments its host gives (`workspaces` under `[provides]`; workspace 0.2.1: project; computer 0.7.3: desktop, browser, apps, display), the registry's index carries them, and the session host installs the package of a named or chosen environment as `packages.auto_install` says; a folder alone names a project. The choice of a new conversation lists the registry's environments until one is installed. Checked: the regression tests fail on 0.81.0 and pass on this change; from a wheel in a new environment with an empty home, a task given only a folder installed `workspace` and finished. No full suite.

## 0.81.0

The desktop environment works through screenshots and the real mouse and keyboard only. Choosing the desktop used to give the agent the background-window prompt and the `windows`, `use_window`, `launch`, `elements` and `act` tools as well; in a real Windows session with physical input allowed it then used accessibility actions on a covered Chrome window. Those tools and their prompt section are now a separate skill of the background applications, separate display and background browser environments, and the desktop worker refuses window-targeted and element operations before dispatch (computer 0.7.1). Screen recording is off by default and is no longer a first-use question; it is turned on explicitly to record a demo. Checked: an installed-package task on real Windows clicked a text field, typed into it and confirmed with three physical, delivered input receipts and no recording; the desktop regression fails against computer 0.6.0 and passes on this change, together with the scoped first-use, environment-choice and environment-attach tests. No full suite.

## 0.80.2 (unreleased)

The terminal chat asks where a conversation works when the conversation opens, before the first message is typed (at start and after `/new`); the last choice is highlighted and Enter takes it. In 0.80.0 the question opened only after the first message was sent, and the Enter that sent the message answered it at once with the highlighted choice, so no choice was seen. A choice that still opens after a message (the opening one was dismissed) ignores Enter for its first 0.6 s. The status line names the chosen environment before the first message. A conversation without an environment no longer prints an evaluator line, and the browser package installs beside computer 0.7 (browser 0.5.1). Checked: 15 scoped tests of the environment choice pass, one of which sends the stale Enter through a pipe; the terminal chat itself was not driven live.

## 0.80.1 (unreleased)

Plain conversational replies display once. Their `agent_message` notification now identifies the existing model reply, so shared transcript consumers render only the original answer while raw trace and inbox consumers retain the notification. Independent messages, repeated answers on different turns, and model/program finish output remain visible. Scoped runtime-to-terminal and trace-replay regressions reproduce the duplicate before the fix and cover these boundaries; no full suite or live model evaluation was run.

## 0.80.0 (unreleased)

A conversation's environment is no longer fixed by one saved setting, and its observation is no longer a fixed bundle per environment.

- **Each conversation chooses where it works.** The choice lists what the installed packages provide: no environment (conversation only: no worker, no view), a project folder, a background browser, background applications, your desktop, a separate display. `session.environment` is `ask` (the default: every new conversation asks, the last choice highlighted), `last`, or one kind. `computer.mode` is now the computer kind highlighted first; saved values keep working. The terminal has an opening choice and `/environment`, the app's composer has the two new choices, the command line takes `--workspace none|project|...`, and Python takes `workspace="none"`. Where nobody can be asked and the setting is `ask`, the task does not start and the error names the option.
- **One agent takes another environment when a step needs it.** `use_environment(kind, why)` attaches it to the same conversation and `release_environment(kind)` gives it back; its calls are under its name (`desktop.click(...)`, `project.run_command(...)`, `browser.read_page()`). `environments.attach` grades the permission (`never`, `ask_each`, `ask_once_session`, `allow`; default `ask_once_session`), with rules per kind. The question shows the model's reason. With `physical.level = "allow"` it does not ask; `never` still refuses; where nobody can be asked and the level asks, it is refused with the reason. Every attachment and its reason is in the conversation, the timeline and the trace. Real mouse and keyboard stay under the physical-input policy.
- **Sub-agents are off by default.** `session.agents`, `--agents`, `/agents`, the app's switch or `runtime={"agents": True}` turn them on, or the agent asks with `request_agents(why)` and you agree.
- **The model looks when it needs to.** Every turn is text. `look()` puts a view in the next turn with that program's result, `watch()` brings the views with every program (or every few seconds) until `unwatch()`, and a view stays for one reply unless the model keeps or pins it. A configuration that declares `runtime.cameras` keeps its standing watch unchanged: the resolved evaluation agent is byte-identical to 0.79.2 for its robot, desktop and game tables, and the robot packages are untouched.
- **Models that read no images.** Model entries record it (from the provider's catalog where it says; editable). Such a model is sent no image; `model.vision` names a model that describes a view for it; the environment choice says so beside environments with a screen.
- **The verifier** gets the state, the elements or page text the environment reports, and the views.

Checked on Windows with Python 3.14: 75 scoped tests over the changed contracts pass (environment choice 13, attaching and sub-agents 22, views and the model flag 17, first-use choices 14, workspace providers 7, model attribution 2); the docs type check, build (121 pages) and bundle budget pass. Real tasks with DeepSeek V4.1 Flash through the Python API and the command line: no environment answered with 0 workers and 0 images in 1 model call; a project task changed a stylesheet, asked once for the background browser with its reason, and after approval finished in the same conversation (26 model calls, 3 images, all from its own looks); after a refusal it went on without the browser (12 calls, 0 images); a desktop task read a table cell (1745) from the window's elements in 3 calls with 1 image, from its own look; with the model marked as reading no images, a project task finished with 0 images and a desktop look sent 0 images, with the note shown in the environment choice. In the app, the no-environment case was run once; the attach question in the app and the terminal chat's views were not exercised live. No paired before/after comparison was run: the default follows the design decision that the model decides when to look. The full suite was not run.
## 0.79.2 (unreleased)

Windows terminal chat accounts for console line reflow before erasing or refreshing the input region after a width change. Repeated shrinking and widening no longer strands separator lines above the input. The repair keeps the inline layout and transcript instead of clearing the viewport. Regression coverage uses the actual Chat layout in Windows ConPTY, including draft input, transcript preservation, height changes and rapid resize sequences; no model calls are needed.

## 0.79.1 (unreleased)

New clients no longer silently submit work to a busy host running different code. Existing sessions remain accessible for inspection and shutdown; an idle old host is replaced, including when discovered inside the startup lock. This prevents an old host from bypassing first-use choices after an upgrade. Ctrl+O now opens a temporary program-details view; Ctrl+O or Esc restores compact chat without leaving expanded output in scrollback. Live program details refresh, and chat output received while viewing them is preserved for return.

## 0.79.0 (unreleased)

Computer 0.6.0 requires explicit first-use choices for workspace mode, real input, other-window information and screen recording. The TUI and interactive run command ask before starting a task and save only an explicit answer. Cancel starts nothing; existing settings and per-task flags remain authoritative. Headless clients receive a structured `choice_required` response. Child workspace allocation checks the same decisions. Project-folder tasks and automatic package-installation policy are unchanged. Scoped checks cover unset/invalid values, cancellation, persistence, runtime overrides, HTTP transport and child allocation.

## 0.78.3 (unreleased)

Running `harness` or `harness chat` now opens a new terminal UI conversation instead of the optional agent package's plain-text prompt. The first message starts a task through the existing host, preserving task options and attachments; opening and closing an empty chat starts no task. Scoped regression checks reproduce the old routing failure and cover both commands, first-message options, model selection, normal exit and redirected streams.

## 0.78.2 (unreleased)

Installing another package now activates existing package modules before looking up their host extensions. Task hosts resolve their data directory before creating run paths, including macOS temporary paths and symbolic links. Computer 0.5.25 stops requesting the removed optional `chat` skill, so browser and desktop task configuration works without an app frontend. Regression checks reproduced the installation, path and skill failures before the fixes; all 45 scoped checks pass on macOS. Installed-wheel acceptance from outside the checkout verified package installation, a real browser task, and an interactive project repair with DeepSeek V4.1 Flash. The local acceptance used a local package registry; the public registry has not been updated. No full suite was run.

The terminal restoration check ignores Darwin's kernel-managed `PENDIN` marker; a plain standard-library raw-mode round trip produces the same marker. All configurable terminal attributes are still compared.

## 0.78.1 (unreleased)


OpenRouter model requests now identify the app as `the-harness` with `HTTP-Referer: https://harness.lmms-lab.com/` and `X-OpenRouter-Title: the-harness`. Both streaming and non-streaming requests carry attribution, including explicit OpenRouter relays and compatible clients targeting the official hostname. Other providers retain their existing headers. Receiver-side HTTP checks cover cancellation and provider boundaries; two real DeepSeek V4.1 Flash calls from an installed wheel verified the outgoing headers and successful responses. The full test suite was not run.

On POSIX, attaching to a hosted terminal session now forwards its native terminal output and keyboard input through the existing session API. Interactive clients retain their own interface instead of displaying cursor-control sequences as chat text. Ctrl-] detaches without stopping the hosted process. This was reproduced while hosting Hermes on the Linux demo server; raw PTY records remain unchanged.


## 0.78.0 (unreleased)

Installing core does not preselect external products; automatic installation of packages required by a task remains enabled by default. Explicit MCP connections work without the app or persistent agent, over stdio or HTTP. Custom-connector revocation is rechecked before dispatch, including calls queued on shared resources. Task calls retain complete MCP results, serialize shared resources, reject stale dispatch and record late receipts. MCP task submission accepts installed workspace kinds, explicit folders and task budgets. Scoped transport, package and task-entry checks cover these contracts; real-task acceptance is recorded separately before PR delivery.

`harness --version` prints the installed core version and exits.

## 0.77.0 (unreleased)

Separate optional frontend commands from the core CLI. Publishable packages use the SDK; source and package archives have explicit boundaries. Scoped package, workspace and agent checks pass; public release remains pending.

On macOS, `pid_alive` no longer counts an exited process its parent has not reaped yet (a zombie) as running: macOS has no `/proc`, so it reads the process's state with `sysctl`. Run liveness, the computer's coordination and virtual machines, and the launch locks rely on it.
