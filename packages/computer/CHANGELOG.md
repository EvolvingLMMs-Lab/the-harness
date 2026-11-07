# Changelog

## 0.5.24

- Own desktop/browser host configuration, skill selection and managed-pipe/window state through the package provider.
- Use the shared host worker lease lifecycle while retaining desktop/browser provisioning. Read desktop operation values separately from execution events. Common agent prompts now live in the core; requires Harness 0.75.0.

## 0.5.23

- The physical-input rule schema declares its per-rule idle timeout for the terminal settings editor.

## 0.5.22

- The README and the docstrings name the terminal chat's `/settings` where they named the TUI's settings page.

## 0.5.21

- A page's file input is matched to its own row only ("<label>: <what it holds>"): a button of the label alone,
  such as a page's visible Attach, got set_value and the file's name before. The prompts have the agent check the
  page for the file's name after set_value: a page may remove the input once it has the file, and programs
  cannot read the user's files.

## 0.5.20

- The pictures the model gets (the screen's, a window's) are JPEG at quality 80, not 90: a 1920 x 1080 screen
  is ~180 KB rather than ~230 KB, and each model call carries a few of them (one place: apps.JPEG_QUALITY).

## 0.5.19

- In a page driven over DevTools (a Chromium launched here), a file input opens no native dialog (the file
  chooser is intercepted): the agent gives the file with set_value(id, path) on the input's row (a button
  "<label>: No file chosen"), DOM.setFileInputFiles with ~ as the browser's home, and the row's value is the
  file's name then. Native dialogs of other apps are unchanged.

## 0.5.18

- The prompts give a file dialog a file in the home folder as ~/...: the agent guessed the home folder's place
  from its name (/home/<name>) and typed a path that does not exist.

## 0.5.17

- A window with no accessible of its own (a Chromium's GTK file chooser) has no elements: before, its app's
  nearest frame (the page) was given as its tree, and the agent read the page's elements as the dialog's.
  A Chromium's own dialogs take GTK's input (events sent to them are dropped), so their steps go as the
  user's settings allow rather than unverified and lost.

## 0.5.16

- The prompts steer forms to element actions: list fields by role (a row says required and its value), fill
  with set_value, choose a dropdown's option by its id and read the value back, give a file dialog the path
  and click its Open button (Enter after a typed path can close a Linux dialog without the file); a point
  read off the screenshot is not a window's point. Before finish(), a form's required fields are checked.

## 0.5.15

- A form's fields say what the form requires: element rows carry `required` (and `invalid`) where the
  accessibility tree has them (AT-SPI on Linux), and a web page's script-built dropdown, whose text box stays
  empty, shows the choice beside it as its value (its placeholder is not a value).
- `finish()` names the fields of the window you work in that the form marks required and that are still
  empty, once: fill them, or call finish() again when the task leaves them empty.

## 0.5.14

- Keys and text go into a window the agent's own action opened, as into one it clicked into: a dialog of an
  app it launched (Chrome's file chooser after its Attach click) and a popup or dialog of a window it works in
  (`window_at` reports the window it is transient for, or its owner on Windows). Before, ctrl+l, a path and
  enter into the file chooser were refused until the agent clicked into it.

## 0.5.13

- On Linux, an app launched for the agent starts in the home folder, as a person's would; its own folder keeps
  only its state (a browser's profile). Before, it started in that folder, and a file dialog showed it.

## 0.5.12

- DevTools reaches a launched browser's pages, never a dialog of its own: its file chooser (Linux: transient
  for its window or a dialog by type; Windows: an owned window) is not `cdp`, and its input goes the window's
  way. Before, a click or a key there went over DevTools to the page: the chooser never got it, and ctrl+l and
  a path typed into it navigated the page away from its form.

## 0.5.11

- In a window driven over DevTools (a Chromium launched here), a click on an element or at a point is the
  mouse's (DevTools input at the element's middle, an element out of sight scrolled into view first), not
  the accessibility action standing for it: a script-built control (a custom dropdown's option) ignored
  that action while it was reported done. An action asked for by name (invoke, select, ...) is unchanged.

## 0.5.10

- `elements()` says when it left elements out: past `limit` (200), it prints how many more matched and how to
  filter (role=, text=) or raise the limit; the worker's `elements` call returns `more`. Before, the list was
  cut silently, and a long page's form fields were missing without a word.

## 0.5.9

- In a Chromium window launched on Linux, `scroll_into_view` and `set_value` go over DevTools: the page's
  element of that accessible name nearest to where the accessibility tree has it is scrolled into view
  (`DOM.scrollIntoViewIfNeeded`), or focused, its text selected and the value inserted as typing does
  (`Input.insertText`). Over AT-SPI, Chromium answers `ScrollTo` for an element out of sight and nothing
  moves, and its fields have no EditableText, so their `set_value` was never offered.

## 0.5.8

- For the harness 0.66.1: the worker RPC calls (the pointer's name, a workspace's preview, the start-up check) use the core's `post_json`.

## 0.5.7

- For the harness 0.66: `show()` is the episode core's; the screen and preview data URLs are the core's `data_url`, the session and the workspaces' preview decode with `decode_data_url`.

## 0.5.6

- For the harness 0.65.2: one physical input layer for every worker that drives the real keyboard and mouse (this one and Minecraft's). `presence.py` tells the user's hand: raw input on Windows (injected input has no device), the idle time on an X display and macOS (the worker's own input and another agent's dispatch left out), the quiet time, took_over and hand_back. `physical.PhysicalStep` turns the verdict into a refusal, takes the input lock (at most 120 s) and checks the window again once it holds it, records the step and its delivery, and serves the `physical` method. `desktop/inject.py` has the SendInput and XTest devices and one key table (rfb.py and linux.py use it). `desktop/windows.py` and `linux.py` have the window helpers (processes, image_path, window_at, foreground, bring_to_front, english_input, keyboard_ready, dpi_aware, WGCSession).
- Keys and text sent with the real keyboard wait for the window's input method as Minecraft's do: put in English mode first, refused (`input_method`) when it stays open.

## 0.5.5

- Cascaded browser windows step less (an eighth of the area across, a tenth down), so the first four
  do not start again from the top left: each one's top left, where its agent's pointer rests, stays
  outside the windows opened after it. Before, the fourth came back over the first three.

## 0.5.4

- For the harness 0.65: the pack's last section lists the installed skills (`{ installed = true }`); coordination and the physical-input grants are written with the core's `atomic_write`, the worker options with `toml_dumps`.

## 0.5.3

- A sub-agent's browser is told its name and colour through the worker's `call` (core/worker.py), as an
  environment's own method goes: the request 0.4.2 sent (`{"method": "pointer"}`) was refused, so no
  pointer was drawn.

## 0.5.2

- A Chromium or Electron app launched here (input over DevTools, which reaches the page, never the browser's
  own bar): ctrl+l, alt+d or f6, then the typed address and enter, navigate the page (`cdp.navigate`,
  Page.navigate on the same session); backspace and ctrl+a edit it, escape or any other input leaves it.
  Before, the keys and the address went to the page and nothing navigated.

## 0.5.1

- For the harness 0.64: The screen recording's first-frame time is the core's `probe()` read from the frames' own times; the copy of ffmpeg's start parsing goes.

## 0.5.0

- For the harness 0.63: the computer's worker shares the core's BenchWorker (call dispatch, state, the screen view's check, the outcome behind a token claimed once); its workspaces' and the macOS desktop's ports come from the core (free_port), and the bench names no port of its own.

## 0.4.4

- For the harness 0.62.2: The outcome token is the core's OutcomeToken; process checks and the VM folders use the core's pid_alive (a process we may not query counts as running, so its folder stays); the shield's checks are the core's (finite, in_screen, bounded, reject).

## 0.4.3

- The screen, the input steps and the way of working are in prompts/desktop/steps.md and
  programs.md, shared by this computer, the desktop benches and the browser; each
  core.md keeps what differs (the system, the screen size, what type_text can type, the
  settle time, the user first). The desktop benches now get the print and show() advice
  and the think-while-acting paragraph this computer had.

## 0.4.2

- `browser_windows = "cascade"`: background browsers' windows open as each agent starts, in a few sizes,
  each a little lower and to the right of the one before, overlapping (`cascade()`); the worker is told
  the layout (`HARNESS_BROWSER_LAYOUT`).
- A sub-agent's browser (windows shown) is told its name and its lane's colour on the timeline
  (`AGENT_COLORS`, the app's) when it takes a worker; another run clears them.
- `record_screen` also records a desktop conversation: the whole screen with its pointer (Windows; Linux
  on the X display it is on), and cascaded browser windows.

## 0.4.1

- For the harness 0.62: declares its practice sandbox: none.

## 0.4.0

- The sub-agents section tells the model that `delegate(task, agent="claude-code")` (or "codex") hands a task to that coding agent (the external-agents package).

## 0.3.0

- For the harness 0.59: Workers start as python -m harness.core.worker; the assistant's configuration is the core's configs/assistant.toml.

## 0.2.2

- Linux: `launch` takes an application by the name its menu shows ("Google Chrome", "Text Editor":
  its .desktop entry), as well as a path or a program on PATH.

## 0.2.1

- Typing a text with the real keyboard stops between two lines when the user takes the mouse or
  keyboard (`yield_on_user_input`): the refusal says how much was typed and carries `wait_seconds`;
  the rest is not typed. Before, the user's input was checked there only when another agent
  waited for the input lock.

## 0.2.0

- For the harness 0.58: This computer's code is the package's library (harness_computer: the desktop backends, the workspace pool, the physical-input policy, window privacy, the input lock and window ownership, screen recordings, the desktop's session and shield), with the desktop kind, the computer, physical and privacy settings and its host module (the session host's workspaces).

## 0.1.0

- First release as a package of its own (moved out of the harness core).
