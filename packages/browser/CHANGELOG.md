# Changelog

## 0.5.3

- The core prompt is less than half as long. It keeps what every reply needs: how to reply, how to work, and one line for each call. The details of the tree of reflexes (every setting of a node) and of units (waits, what the model is told and in what order, units of its own, who has the environment) are in two pages that a program reads on demand, `guide("tree")` and `guide("units")`. A page that was read is given again after a summary of the conversation. `reflex_method()` still works and returns `guide("tree")`. The other sections are brought to the same standard. The request for a reflection after an episode, the same whatever the agent acts in, asks for a note, a memory entry or a skill and no longer for a reactive helper: the nodes of a tree are kept from the tree the agent set. The library section gives `setup` in the signature of `library.propose` and no longer names a `tree` call. The checklist section has no example task. The section on world memory, which no setting could switch on and whose calls do not exist, is removed. The core names no kind of environment any more. Its default configuration has no table for a computer or a game and no table of prompts: a kind's package says its prompt and the agent's settings on it in its `kinds.toml` (`prompt`, `agent`), and may declare what is particular to the kind (`unnamed_in_lock`, `library_experience`, `record_waits`, `memory_report`, `interfaces`). Where nothing names a kind, it is `none`, a conversation with no environment, not a robot. What breaks: a `skill.toml` must say `embodiments` (the kinds it runs on, or `["*"]`); an embodiment file and a worker's profile must name their `kind`; `harness.embodiments.profile()` is gone (it built one kind's worker profile and is that kind's package's). `verify(claim)` is a call of every kind. The rest of what the core held of one package is that package's now. The session host and the command line name no workspace kind: a provider says where its kinds stand among those offered (`order` in `describe`), what it preselects (`preselected`), and a package adds its own flags to `harness run` (its host module's `run_arguments` and `run_sets`; `--vm-image` is the computer package's). `environment_kinds()` lists what a conversation can take, so no prompt lists kinds. A package brings the third-party sources it uses (`third_party/sources.toml` in the package); the core's list is empty. A service of a protocol that is not the core's (`http`, `openai_chat`, `mcp`) names it and gives that protocol's own table, read as `ServiceSpec.options` (it was `ServiceSpec.xpolicylab`). The guard actions `OPEN_GRIPPER` and `BACK_OFF` and the prompt feature `measured_gripper` are no longer the core's: the package of the kind that has them names them. The pins `environment/constraints.txt` of the core, which were one benchmark's, are gone: the browser benchmark's environment no longer names them (it is built anew on its next use). A prompt pack needs `pack.toml`: the section list for packs without one, which named skills of packages, is removed. Direct mode's action vocabulary (`runtime.actions`) is called with `skills`, the enabled skills, in place of `allow_policy`.

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
