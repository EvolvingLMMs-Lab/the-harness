---
title: "Worker protocol"
description: "The HTTP protocol between the harness and a worker: its methods, the calls each kind of worker answers, and the rules every worker keeps."
---

A worker is the thing the agent acts on — a simulator, a robot, this computer's desktop,
a background browser, a game — served over HTTP in a process of its own. The agent's
programs and the episode driver reach it as a client; the worker checks every step before
it acts and keeps the score to itself.

```bash
harness serve --factory benches.robotwin.runtime:create_environment --port 8765
harness serve --factory benches.computer.runtime:create_environment --options worker.toml
harness serve --factory benches.robodojo.runtime:create_environment --contract xpolicylab --embodiment arx_x5
```

| Option | What it does |
|---|---|
| `--factory module:callable` | the callable that makes the environment; required |
| `--options FILE` | a TOML file whose keys are passed to the factory as keyword arguments |
| `--host`, `--port` | where it listens (default `127.0.0.1`, `8765`) |
| `--contract` | what clients may see: `native` (default, everything), `xpolicylab`, `screenshot` ([Contracts](#contracts)) |
| `--embodiment` | the embodiment a contract reads its calibration from; required with a contract |
| `--exit-with-stdin` | end once standard input closes, so the worker ends with the process that started it |

Once it listens it prints one line, `{"worker": NAME, "address": [HOST, PORT]}`. It
answers one request at a time. It listens on the loopback interface by default; binding
any other interface needs `$HARNESS_WORKER_TOKEN`, which every request must then send as
`Authorization: Bearer TOKEN` (the client sends it when the variable is set).

## Requests

```text
POST /rpc   {"method": "...", "arguments": {...}}   ->   200 {"result": ...}
                                                    ->   400 {"error": "ValueError: ..."}
```

Any other path answers 404, a missing or wrong token 401, and a body over 32 MiB is
refused. The client never retries a request: a step that timed out may have been carried
out.

| Method | Arguments | Result |
|---|---|---|
| `describe` | | `{protocol_version: 1, name, tools, snapshot_restore: false, methods}`: `tools` are the worker's tool schemas, `methods` the names `call` takes. A client refuses another protocol version |
| `reset` | `task`, `seed` | the first observation: `{episode_id, step, instruction, state, images}` (images as data URLs) |
| `execute` | `episode_id`, `step`, `action` (`{name, arguments}`) | one action on the current observation: `{observation, reward, success, terminated, truncated, info, videos}`. Refused before a reset, after the episode ended, and for any `(episode_id, step)` but the current one |
| `call` | `name`, `arguments` | the result of one of the environment's own methods ([below](#calls)); an unknown name is an error |

## Calls

The agent's runtime drives a worker through `call`. Every worker answers the common ones;
each kind adds its own.

### Every worker

| Name | Arguments | Result |
|---|---|---|
| `profile` | | static facts: the embodiment kind and name, the control rate (`control_hz`), the cameras or the screen, the shield's options, the step limit, `clock` ([below](#rules-every-worker-keeps)); a robot's joint groups, action limits, arm bases, gripper constants and planner limits |
| `state` | `episode_id` | the state now: `step`, `ended`, and the embodiment's own (a robot's joint positions and end-effector poses, `[x, y, z, qw, qx, qy, qz]` in the environment's frame; a desktop's screen) |
| `tick` | `episode_id`, `step`, `command`, optional `cameras` | one step: `{executed, shield: {verdict, command, reasons}, state[, observation]}`. With `cameras`, the views after the step come with it |
| `observe` | `episode_id`, `cameras`, optional `image_format`, `quality` | `{state, images}` (data URLs); a robot adds `intrinsics`, `camera_to_world` (OpenCV convention) and `image_size` |
| `claim_outcome` | `episode_id` | a token for the outcome, claimed once per episode by the driver after the reset |
| `outcome` | `token` | `{success, reward, process_score, terminated, truncated, steps, ...}`; only with the token |

### Robots and simulators

| Name | Arguments | Result |
|---|---|---|
| `tick` | `command`: absolute joint targets; optional `source` (`policy` for an action of a learned policy) | as above |
| `fk` | `command` (joints) | `{arm: end-effector pose}` |
| `ik` | `episode_id`, `arm`, `pose` | `{success, joints}`, solved from the current joints |
| `plan` | `episode_id`, `arm`, `pose` or `joints`, `raw` | `{success, waypoints}` at the control rate (`raw`: the planner's own path) |
| `policy_obs` | `episode_id` | the observation an evaluation client hands a learned policy (RoboDojo) |
| `action_spec` | | per arm its mount pose, joint limits and velocity limits; the control rates (RoboDojo) |

### Desktops, apps and displays

| Name | Arguments | Result |
|---|---|---|
| `tick` | `command`: one step, below | as above; a step that reached the computer also says how (`delivery`: `mechanism`, `status`, the app and window) |
| `windows` | `episode_id` | the windows (id, app, title, picture size, minimized, launched by the agent) and the one the agent works in |
| `elements` | `episode_id`, `window`, `role`, `text`, `limit` | a window's accessibility elements: id, role, name, value, rect, actions, states, and the same as outline lines (`outline`) |
| `use_screen` | `episode_id`, `index` | act on monitor `index` from now on, or follow the active window again (`null`) |
| `hand_back` | `episode_id` | you handed the computer back after taking over |
| `physical` | `op`: `identify`, `check`, `answer`, `status` | the physical-input policy of this worker's episode: whose steps these are, what a step would meet, your answer to a request, who holds the input now |
| `preview` | `max_side` | a small picture of the screen for the live view; nothing is done or counted |

A desktop step (`command`) is one of:

| `type` | Fields |
|---|---|
| `click` | `x`, `y`, `button` (`left`, `right`), `count` (1, 2), `window` |
| `drag` | `x`, `y`, `to_x`, `to_y`, `duration_ms`, `window` |
| `scroll` | `x`, `y`, `direction` (`up`, `down`, `left`, `right`), `amount`, `window` |
| `type` | `text`, `window` |
| `key` | `keys` (at most 4 pressed together), `window` |
| `wait` | `ms` |
| `act` | `element`, `action` (`click`, `invoke`, `toggle`, `select`, `expand`, `collapse`, `set_value`, `scroll_into_view`), `value` |
| `use_window` | `window`, optional `visible` |
| `launch` | `app`, `args`, optional `visible` |
| `noop` | |

Points are the screen's; with `window` (an id such as `w2`) they are in that window's
picture.

Workers that advertise `action_ids` echo the supplied action ID in the tick receipt. Window
selection and launch return the selected window in `result.window`. The browser exposes
elements in its current document and reports a `page_ready` identity when that document is ready.

A worker started by a trusted host can advertise `managed_approval`. Its control calls
require host authentication. A sensitive input refusal offers an approval request for one
action. The worker verifies the original execution, action, command, cameras and live
target on retry. A request ID alone carries no authority. Application launch and sensitive
input to an unresolved target are refused in this mode. User-facing approval depends on
the host integration.

A worker can independently advertise `authenticated_controls`: its
`managed_control_calls` require a proof from the trusted host, without implying that
it implements a sensitive-action approval UI. `program_control_calls` is a subset the
worker allows the host to relay from a current program; other controls stay host-only.
Project workers protect tick, cancel and release; release belongs to the host lease.
Existing desktop sensitive-approval checks remain separate and unchanged.

### Others

| Worker | Its own calls |
|---|---|
| background browser | the desktop calls, and `page_text` (`episode_id`, `offset`, `limit`): the page's visible text and links |
| games (Minecraft) | `physical`, `hand_back`, `new_world` (a new world, the player's reset), `show_seed`, `world` (the world map's operations: `things`, `thing`, `forget_thing`, `summary`) |
| OSWorld | `declare_infeasible`: the verdict that the task cannot be done, which its infeasible tasks are scored by |
| a bench with a practice sandbox (its bench.toml [sandbox]: Minecraft's practice, the made-up robot) | `sandbox` (`episode_id`, `op`, its arguments): stages a scene, only in an episode of a task's learning variant (`-learn`, an active run's); refused in any other |

## Rules every worker keeps

- **Episode and step.** `tick` and `execute` name the episode and the step they were
  computed for; a stale one is refused and never carried out. A step that may have been
  carried out is never retried silently.
- **The shield runs in the worker.** Every command is checked before it reaches the
  robot or the computer: a robot's joint limits and motion bounds, a desktop step's
  fields, points, keys and text, a game's inputs. Programs cannot go around it. A refused
  step comes back with `executed: false` and the shield's reasons.
- **The outcome is guarded.** Only the holder of the token (the driver) reads it;
  programs and the model never see it.
- **Whose clock.** A profile may name its `clock`: `steps` (the default) when a `tick`
  is the clock — a simulator advances one control period, a hold is waited out by the
  worker — or `wall` when the world runs on in real time and a `tick` returns at once;
  the agent's runtime then keeps the control rate itself and holds every period while
  nothing runs.

## Contracts

A contract filters every result to what an evaluation hands a policy, so development runs
see what an evaluated agent will. The profile names it (`observation_contract`).

| Contract | What clients see |
|---|---|
| `native` | everything the worker reports |
| `xpolicylab` | what XPolicyLab's official client hands a policy: grippers as their last commanded value (`gripper_feedback: "commanded"`), intrinsics and `camera_to_world` from the embodiment's calibration, no step limit in the profile or the state, no task name |
| `screenshot` | a desktop's instruction and screen only: states keep `step`, `ended` and `screen`; no task, track or step limit |

## Implementations

| Factory | Worker |
|---|---|
| `benches.computer.runtime:create_environment` | this computer: the desktop, its apps in the background, or a display of its own |
| `benches.browser.runtime:create_environment` | a background browser |
| `benches.minecraft.runtime:create_environment` | Minecraft |
| `benches.robodojo.runtime:create_environment` | RoboDojo, one task per process ([Benches](/docs/extend/environments/)) |
| `benches.robotwin.runtime:create_environment` | RoboTwin 2.0, one task per process |
| `benches.osworld.runtime:create_environment` | OSWorld |
| `benches.osomni.runtime:create_environment` | OS-Omni |
| `harness.connectors.xpolicylab.Bridge` | not served by `harness serve`: the XPolicyLab connector, a worker whose robot is XPolicyLab's client |

To write a worker of your own, see [Add an environment](/docs/extend/environments/).
