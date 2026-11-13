# Changelog

## 0.5.2

- Package removal retains shared immutable cache files for other projects and independently configured data directories, and updates choose compatible versions while keeping your declared ranges. Explicit updates refresh published versions, including in a running app. A project install paused for trust refuses changed declarations instead of overwriting them. Preparing path, Git or URL sources and waiting for trust leave other package commands available. If another package change is already publishing files or records, a new request stops promptly and asks you to retry after it finishes. Broken environment caches rebuild on first use; installation errors show their cause and retry only transient network failures, and the terminal uses its declared dependency pins. Browser depends on computer 0.8, and current browser, computer and external-agents packages require Harness 0.82 or newer. The core refuses older computer packages with an upgrade command instead of running an incompatible managed-workspace protocol. Project updates change the lock without turning indirect dependencies into declarations; outside a project, `--update --project` refuses to touch user packages. Installing from a project's declarations preserves its source references and ranges, including legacy local-path records. Named dependency updates respect retained parent packages' constraints; jointly updated or replaced parents use their new dependencies. Local sources stay local and resolve relative to the project root; older URL records remain usable. Manifest installs retain compatible registry locks. Dependency changes, including local replacements, respect retained parents and recorded ranges; incompatible existing records are refused before writes. The old computer/browser pair has one joint-upgrade command, and obsolete project lock conflicts explain explicit removal. Cache reuse checks source identity and compatibility, including identical-version switches from development copies or another registry. Cleanup refuses the working directory, its ancestors, the home directory and filesystem roots. Registry mirrors are recognized by identical archive checksums; implicit lock restore refuses different or missing content until you explicitly update or select a source. Source selection updates project declarations and dependencies together. Automatic installation respects development/disabled choices and pinned ranges; updates preserve enabled state and select versions compatible with the current platform. Capability recovery refreshes an already installed provider and restores missing selected cache files without dropping owner settings. Recovery commands retain saved ranges; unnamed development dependencies and unavailable project locks refuse before writes, and missing-cache lock restoration checks its archive checksum. Automatic recovery validates existing registry content in every scope, while explicit updates keep their selection authority. Dependency recovery names compatible joint commands, registry read failures preserve their real cause, and ready installed capabilities remain available before installation-policy gates without repeated change notifications. Recovery commands stay limited to the related installed packages, including with obsolete lock entries or a stray lock. First-use installation of a new provider applies the same protection to already selected shared dependencies.

## 0.5.1

- Depend on computer 0.7: with the range left at 0.5 the package could not be installed beside the current computer package.

## 0.5.0

- The page is no longer sent with every turn: `read_page()` and `elements()` give it as text, and `look()` shows it when a program needs the picture. The background browser can be taken into another conversation with `use_environment("browser", why)`. Requires Harness 0.80.0.

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
