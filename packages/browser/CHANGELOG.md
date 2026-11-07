# Changelog

## 0.4.3

- Use core shared agent prompts with Harness 0.75.0. Browser provisioning and controls remain in their existing packages.

## 0.4.2

- For the harness 0.65: the pack's last section lists the installed skills (`{ installed = true }`).

## 0.4.1

- An agent's pointer shows from its first page on: until it clicks, it rests near the page's top left
  (`REST`), its name readable, not at 0,0.

## 0.4.0

- For the harness 0.63: Its dependencies' new versions.

## 0.3.4

- For the harness 0.62.2: The browser shield's rejection is the core's `reject`.

## 0.3.3

- The prompt's input steps and way of working come from the computer package's
  prompts/desktop (steps.md, programs.md); core.md keeps the page, reading it, its keys
  and its own calls.
- Depends on computer 0.4.3, which has these sections.

## 0.3.2

- A browser window shown draws its agent's pointer with its name in its colour (the `pointer` method):
  it glides to each click, scroll and drag, stays out of the page's events, text and accessibility,
  and comes back on every page. The state says how windows show (`layout`).
- Needs computer 0.4.2.

## 0.3.1

- For the harness 0.62: declares its practice sandbox: none yet.

## 0.3.0

- For the harness 0.59: it depends on computer 0.3 (workers start as python -m harness.core.worker).

## 0.2.0

- For the harness 0.58: Imports what moved out of harness.sdk from the packages that hold it now.

## 0.1.0

- First release as a package of its own (moved out of the harness core).
