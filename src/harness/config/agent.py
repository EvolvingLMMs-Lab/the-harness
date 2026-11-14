"""The agent configuration: what is evaluated, resolved for one machine.

There is one agent, configs/default.toml. It names the prompt pack, the skills (by
interface layers or by name), the services skills use (segmenter, policies, world
models), runtime settings, the budget, and its default model roles. Another agent
file may include it and change some keys; an experiment may override any key.

Model roles come from a model file, configs/models/<name>.toml (the agent's `model`,
an experiment's `model`, or `--model NAME`):

    [main]                          the model that writes programs
    backend = "openrouter"
    model = "x-ai/grok-4.7"
    [vlm]                           questions about images (and pointing without a pointer)
    service = "qwen3-vl-8b"         a role may be a service of the deploy ...
    timeout_seconds = 300           ... with its own settings on top
    [pointer]
    service = "molmo2"
    [verifier]                      overrides on top of main (the success verifier)
    [runtime]                       settings the model needs (context window, ...)

Resolving the agent against a deploy gives the conversation's main model, runtime and
prompt, and a lock: everything that decides what a run computes and nothing about
where it runs (URLs, GPUs, ports). The lock records the agent's VERSION, and its hash
is the configuration's identity; a result and an exported XPolicyLab policy each
name one.
"""

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import tomllib

from . import deep_merge, load_layered, read_toml, route_openrouter
from .. import __version__
from ..core import sha256
from ..embodiments import KINDS
from harness.runtime.decision.prompts import assemble_prompt, features_for, select
from harness.runtime.execution.skills import KNOWLEDGE, LAYER_DEFAULTS, Resolution, available_services, handwritten, resolve, skills_for_layers
from ..paths import ROOT
from ..services.placement import automatic, client_config, load_deploy


REPO = ROOT
# The agent `harness` runs unless told otherwise, and where model files live.
DEFAULT_AGENT = REPO / "configs" / "default.toml"
MODELS_ROOT = REPO / "configs" / "models"
ROLES = ("main", "vlm", "pointer", "verifier")
SERVICE_KEYS = ("segmenter", "vision", "policies", "world_models", "mcp")
# What one entry of each list of services is, in messages.
SERVICE_ENTRY = {"policies": "policy", "world_models": "world model", "mcp": "MCP server"}
# What [game] knowledge says (runtime/execution/skills.py KNOWLEDGE).
KNOWLEDGE_DOC = ("what the agent knows of the game: \"learned\" (the default: no skill written for it by hand loads, "
                 "nor is imported; what it knows is its library's, which learns with runtime.library learn = \"on\", "
                 "runtime/learning/learner.py) or \"handwritten\" (a reference baseline's skills written for the game by hand "
                 "may load)")
# The keys of configs/default.toml (and of an agent file that includes it).
AGENT_KEYS = {
    "description": "one line, shown by harness config and the run viewer",
    "prompt": "the prompt: a pack directory (assembled for the enabled skills) or files, in order; or a table "
              "of them by embodiment kind (robot = ..., desktop = ...)",
    "mode": "program (default: the model writes programs) or direct (one action per call)",
    "actions": "direct mode: the action vocabulary, \"module:function\" (text, allow_policy, allow_skills) -> the "
               "program of one <action>; a ValueError names what is wrong with it",
    "roles": "the model roles the agent uses, among main, vlm, pointer, verifier (default all)",
    "skills": "layers = { learned, reactive, handlers }, or names = [...]; enable = [...] adds optional skills, "
              "disable = [...] removes skills",
    "services": "segmenter, vision (the vision skill's generic perception), policies = [...], world_models = [...], "
                "mcp = [...] (MCP tool servers for the mcp skill): services the skills use",
    "model": "the default model roles: a model file's name (configs/models/<name>.toml), or the roles inline",
    "runtime": "runtime settings: the [runtime] keys",
    "budget": "max_model_calls per episode (default 30)",
    # A table for each embodiment kind but the robot's ([desktop]).
    **{name: f"the agent on {kind.what} (benches of embodiment kind {name}): roles, skills, services, runtime and "
             "budget keys merged over the ones above (runtime also over the model file's)"
             + (f"; knowledge: {KNOWLEDGE_DOC}" if name == "game" else "")
       for name, kind in KINDS.items() if name != "robot"},
}
# The keys of a kind's table ([desktop]): the robot is the agent's top level; `knowledge`
# only a game's.
KIND_KEYS = ("roles", "skills", "services", "runtime", "budget", "knowledge")
# The model roles of a model file (configs/models/<name>.toml), besides `runtime`
# (settings the model needs) and `description`.
ROLE_DOCS = {
    "main": "writes the programs (or, in direct mode, the actions)",
    "vlm": "answers questions about images inside programs (query_vlm), and points without a pointer",
    "pointer": "open-vocabulary pointing (point_to, localize)",
    "verifier": "overrides on top of main for the success verifier (verify, <verify>)",
}
# Settings of the agent's [runtime] (also of a model file's [runtime], and of an
# experiment's overrides). Documentation only: the resolution writes some of them
# itself (skills, skills_dropped, layers, the service configs).
RUNTIME_KEYS = {
    "bootstrap": "the kernel's session factory, \"module:function\" (default the program runtime's)",
    "cameras": "a standing watch declared by the configuration: these cameras' images reach the model with the "
               "opening message and after every program, as an evaluation's observation contract hands them to a "
               "policy. Without it the model gets text every turn and looks on its own demand (look, watch)",
    "cell_timeout_seconds": "optional deadline for a program, bounded by the episode deadline",
    "contract": "the observation contract (embodiments.contract_filter): native (default), xpolicylab (a robot's) or "
                "screenshot (a desktop's)",
    "default_max_seconds": "max_seconds of a bounded execution that names none",
    "fixed_skills": "direct mode: locate, pick and place in the action vocabulary",
    "isolation": "evaluation: run programs isolated, reaching only the installation, the source and the "
                 "environment's services (true; \"auto\": with namespaces where the machine allows them). false: "
                 "programs run on the machine as the user, under runtime.approvals. Experiments default to "
                 "\"auto\"; a conversation a user starts is not isolated",
    "keep_images": "with runtime.cameras: images of the most recent turns kept in the history (default 2). "
                   "Without it the model says how long a view stays (look(keep=), pin=)",
    "search": "the web search of search() (skills/web): {model, engine} on OpenRouter: a model id whose web plugin "
              "searches, and optionally the plugin's engine (exa, native, ...). None: search() says there is none",
    "viewer": "written by the session host: the model role that describes a view for a main model that reads no "
              "images (the setting model.vision); none: such a model is told the view was not sent",
    "knowledge": "a game's knowledge: \"learned\" (default: use the agent's own library) or \"handwritten\" "
                 "(allow reference knowledge). A worker that declares this setting must report the same mode.",
    "label": "a name the run viewer shows for the configuration",
    "layers": "written by the resolution from [skills] layers",
    "library": "what the agent learned: [runtime.library] path = ... (relative, or under $HARNESS_HOME/; layers = "
               "[...]). uses = \"learn\" (default: a run that learns counts its closed loops' results as uses of the library's "
               "entries, runtime/task/context.py), \"on\" (also with a frozen library: practice) or \"off\". Learning "
               "(runtime/learning/learner.py): learn = "
               "\"off\" (read a frozen snapshot, the experiment default) or \"on\" (keep proposals and enable verified "
               "entries at a safe boundary); trigger = \"passive\" or \"active\"; evidence = \"test\" (trusted verification) "
               "or \"validated\" (paired development scores); load = the minimum evidence to load (proposed, provisional, "
               "replayed, validated). Generated code always needs exact trusted proof. replay = true (recheck provisional "
               "entries at startup); reflect = true (propose from observed results at useful decision points). "
               "The active trigger's schedule (runtime/learning/active.py): active_before = true (before "
               "a task's runs, one run that learns its environment) and active_minutes = 1 to 240 (that run's live "
               "time, default 30)",
    "clear_results_after_minutes": "after this long without a reply of the model (the provider's cache of the "
                                   "conversation is cold), the results of all programs but the last 5 are cleared "
                                   "from the conversation (default 60; 0: never)",
    "compact_at_tokens": "compaction: when the context a call of the model read reaches this many tokens, the model "
                         "writes a summary that replaces the conversation before its last messages (default 150000; "
                         "0: never)",
    "mode": "written by the resolution from the agent's mode",
    "actions": "written by the resolution: direct mode's action vocabulary (the agent's actions)",
    "physical": "the physical-input policy of this run over the user's settings (the computer package's "
                "harness_computer/physical.py): {level, rules}; harness run EXPERIMENT sets it from --physical, "
                "--allow-app, --deny-app, --ask-app",
    "privacy": "what the model learns of the user's windows in this run, over the user's settings (the computer "
               "package's harness_computer/privacy.py): {level, rules}; harness run EXPERIMENT sets the level "
               "from --window-details",
    "pointer": "written by the resolution: the pointer role's client config",
    "policies": "written by the resolution: the learned policies' client configs",
    "python": "the kernel's interpreter (default the conversation's)",
    "reactive_budget_ms": "total time for reactive callbacks on a control period (default 5 ms)",
    "sandbox": "written by `harness run` for an active run only: the bench's [sandbox] (runtime/learning/active.py), the "
               "practice sandbox its kernel gets; a task run never has one",
    "reaction_delay_ms": "time between an observation and the action decided on it, rounded up to whole control "
                         "periods (runtime/tick.py): 0 (the default) for development and practice; 150-200 for a "
                         "person's reaction time, as in a full game run or a recorded demo",
    "observer": "explicit world observation: max_side (default 768), reasoning_effort (none), "
                "max_output_tokens (1200). Legacy timer settings are accepted for old profiles.",
    "segmenter": "written by the resolution: the segmenter's client config",
    "vision": "written by the resolution: the vision service's client config",
    "skills": "written by the resolution: the enabled skills",
    "skills_dropped": "written by the resolution: skills left out, and why",
    "post_policy_calls": "with learned policies: model calls after the first run of a handed-over task, then the policy runs on to the end of the episode (0: it runs on at once; default none: no bound)",
    "policy_progress_seconds": "a run of a learned policy also ends when no object the last locate tracks has moved 3 cm for this many seconds, measured every half of it (default none: only when it stops)",
    "strategy_first": "with learned policies: nothing moves before start(strategy, kind) (default false; the agent sets it)",
    "think_while_acting": "accepted for older profiles; it has no effect. Every program runs as a unit and the "
                          "model's turn is its own while one runs",
    "think_interval": "accepted for older profiles. Decision scheduling is event-driven",
    "turn_grace_seconds": "how long a program may hold the model's turn (default 2): one that is over by then "
                          "gives the turn back with its result, a longer one goes on as a unit and the turn comes "
                          "back with its handle",
    "longest_wait_seconds": "what a <wait> of the model without a time lasts; a wait with a time lasts that long "
                            "(default 60)",
    "reflex_trials": "whether a node of the tree of reflexes is set with its trial, after the page on how a "
                     "tree is designed and tried was read: required (the default) or optional",
    "purpose": "whether a program has to say what it is for: required (the default: a program that calls "
               "neither until(condition) nor until(None) is not started, and the model is told) or optional",
    "tell_budget": "whether the model is told with every call what the run has left (its model calls, its "
                   "environment steps, its live time): never (default: the host keeps the limits and ends the "
                   "turn at them) or always (a benchmark with short episodes, where the model plans its end)",
    "thinking": "how long a call of the main model may think (runtime/conversation.py THINKING): model (the "
                "code's default: the model's own settings), none (reasoning off, replies of at most 2000 tokens, "
                "and the model is told to think briefly), low (reasoning effort at most low, 2000 tokens, told "
                "likewise), medium (at most medium, 8000 tokens) or high; a model set lower keeps its own. The "
                "agent thinks low on games",
    "max_wait_seconds": "accepted for older profiles. Use an explicit timeout to bound a program wait",
    "strict_skills": "a configuration built in code, without skills: fail instead of dropping a skill (resolve_for)",
    "task_descriptions": "a directory of task descriptions (<task>.md) added to the first message, or false",
    "verifier": "check success with the verifier before finishing (default true)",
    "vlm": "written by the resolution: the vlm role's client config",
    "world_models": "written by the resolution: the world models' client configs",
    "mcp": "written by the resolution: the MCP servers' client configs",
    "approvals": "{ask, programs, rules} (runtime/safety/approval.py, permissions.py): ask = sensitive or programs "
                 "(whether every program waits for the user); programs = the level of what a program does on the "
                 "machine beyond its own folder (a command, the network, a file written elsewhere): never, "
                 "ask_each, ask_once_session (default), allow; rules = [{level, action, match}] that win over it. "
                 "Where nobody can be asked a level that asks refuses.",
    "agent_skills": "the app: Agent Skills the user installed, {name: {description, path}} (skills/agent_skills)",
    "installed_skills": "the app: the Harness skills the user installed, by name (the prompt's installed section, "
                        "runtime/decision/prompts.py)",
    "instructions": "{load, files, root_markers, max_bytes, exclude}: the user's and the project's instruction "
                    "files (AGENTS.md) the opening message carries (instructions.py); the settings' [instructions] "
                    "in a conversation a user starts, absent elsewhere (none are read)",
}
def _relative(value):
    """Paths of the core's content written relative to it, a package's as packages/<name>/...
    (locks are machine independent)."""
    if isinstance(value, str) and value.startswith(str(REPO)):
        return Path(value).relative_to(REPO).as_posix()
    if isinstance(value, str):
        from ..paths import packages

        for package in packages():
            # By whole path parts: packages/robotwin is not in packages/robot.
            if Path(value).is_relative_to(package.path):
                return f"packages/{package.name}/{Path(value).relative_to(package.path).as_posix()}"
    if isinstance(value, list):
        return [_relative(item) for item in value]
    if isinstance(value, dict):
        return {key: _relative(item) for key, item in value.items()}
    return value


@dataclass
class ResolvedAgent:
    """The agent resolved against one deploy: the conversation's main model, verifier, runtime
    and prompt, the episode's model-call budget, and the lock with its identity (the
    first 16 hex digits of the lock's sha256). `base_prompt` is the prompt without the
    self-improvement library's additions."""

    name: str
    path: Path | None
    main: dict
    verifier: dict
    runtime: dict
    system_prompt: str
    base_prompt: str
    max_model_calls: int
    lock: dict
    identity: str
    # Where each service the agent uses runs on this deploy (not part of the lock).
    placement: dict = field(default_factory=dict)
    # What it was resolved from (resolve_agent's arguments, trees): an exported
    # policy resolves these again on the machine it lands on.
    sources: dict = field(default_factory=dict)
    # The deploy it was resolved against (without a deploy file, the harness's own
    # placement of the services it uses: services/placement.py automatic()).
    deploy: object = None
    # The embodiment kind its skills and prompt were chosen for (embodiments.KINDS).
    embodiment: str = "robot"


@dataclass
class TaskConfig:
    """The configuration of one task: the worker endpoint, the main model and the
    verifier, runtime settings, the prompt, the seeds and the per-episode budgets.
    task_config builds one from a resolved agent; a conversation runs it."""

    path: Path
    environment: dict
    main: dict
    runtime: dict
    system_prompt: str
    task: str
    seeds: list[int]
    max_model_calls: int
    max_wall_seconds: float
    verifier: dict = field(default_factory=dict)
    # The harness prompt without library text; attach_library builds on it.
    base_prompt: str = ""
    # Task description appended to the first message ("with task description").
    task_description: str = ""
    # Stop the episode once model and verifier calls have cost this much (USD).
    max_cost_usd: float | None = None
    # The resolved agent's lock and identity (config/agent.py), and where its services
    # ran; None for configurations built in code.
    lock: dict | None = None
    agent_id: str | None = None
    placement: dict | None = None
    # The embodiment kind the worker drives (embodiments.KINDS).
    embodiment: str = "robot"

    def __post_init__(self):
        if not self.base_prompt:
            self.base_prompt = self.system_prompt

    def snapshot(self) -> dict:
        """The configuration as episode manifests and experiment.json record it (all but
        `path` and `base_prompt`; the lock as `agent_lock`; the embodiment kind when it is
        not the default robot). The frozen evaluator keeps its schema-2 agent lock."""
        runtime = self.runtime
        if runtime.get("mcp"):
            runtime = {**runtime, "mcp": {name: {key: value for key, value in server.items()
                                                if key in ("description", "read_only_tools", "allowed_tools", "tools_off", "resource", "host_write_tool")}
                                           for name, server in runtime["mcp"].items()}}
        return {"environment": self.environment, "version": __version__, "agent_version": __version__, "main": self.main,
                "runtime": runtime,
                "verifier": self.verifier, "system_prompt": self.system_prompt, "task": self.task,
                "seeds": self.seeds, "max_model_calls": self.max_model_calls,
                "max_wall_seconds": self.max_wall_seconds, "task_description": self.task_description,
                "max_cost_usd": self.max_cost_usd, "agent_id": self.agent_id, "agent_lock": self.lock,
                "placement": self.placement,
                **({"embodiment": self.embodiment} if self.embodiment != "robot" else {})}


def _role(spec, deploy, role: str, strict: bool):
    """A role's model config: its own keys, on top of its service's client config."""
    if not spec:
        return None, None
    spec = dict(spec)
    service = spec.pop("service", None)
    if service is None:
        # The URL is where this machine calls the model, resolved here only: a named
        # variable wins over a URL in the file. The lock keeps base_url_env, not the
        # value, so another machine's endpoint is the same agent.
        named = spec.get("base_url_env")
        from_env = os.environ.get(named, "").strip() if named else ""
        if from_env:
            spec["base_url"] = from_env
        return route_openrouter(spec), None
    base = client_config(deploy, service)
    if base is None:
        message = f"role {role} uses service {service}, which deploy {deploy.name} does not run"
        if strict or role == "main":
            raise ValueError(message)
        return None, {"role": role, "service": service, "dropped": message}
    return {**base, **spec}, {"role": role, "service": service}


def _service(entry, deploy, strict: bool, kind: str):
    """(name, client config or None) of one service entry: a name or {service = ...}."""
    spec = {"service": entry} if isinstance(entry, str) else dict(entry)
    name = spec.pop("service")
    base = client_config(deploy, name)
    if base is None:
        if strict:
            raise ValueError(f"The agent's {kind} {name} is not run by deploy {deploy.name}")
        return name, None
    return name, {**base, **spec}


def model_services(runtime: dict, roles: dict) -> dict:
    """The models and servers the kernel's skills call: VLM, pointer, segmenter, vision,
    policies, world models, and the success verifier ({**main, **verifier} of the model
    `roles`; direct control has none)."""
    return {
        "vlm": runtime.get("vlm"),
        "segmenter": runtime.get("segmenter"),
        "vision": runtime.get("vision"),
        "pointer": runtime.get("pointer"),
        "policies": runtime.get("policies", {}),
        "world_models": runtime.get("world_models", {}),
        "mcp": runtime.get("mcp", {}),
        "verifier": ({**roles.get("main", {}), **roles.get("verifier", {})}
                     if runtime.get("verifier", True) and not runtime.get("mode") == "direct" else None),
    }


def image_roles(services: dict) -> dict:
    """The model roles of `services` (model_services) that answer about images (vlm,
    pointer, verifier), each with the class that asks them (a package's host module names
    it: perception's vision_model), which the episode builds in the kernel; without such a
    package they are None."""
    from ..extensions import first

    client = first("vision_model")
    return {role: ({**services[role], "class": client} if client else None)
            for role in ("vlm", "pointer", "verifier") if services.get(role)}


def resolve_for(runtime: dict, roles: dict, embodiment: str = "robot") -> Resolution:
    """The skills a run of this runtime configuration enables (a conversation's, the
    eval package's): `runtime.skills` as resolve_agent resolved them; a configuration
    built in code without them gets those of its interface layers (runtime.layers over
    LAYER_DEFAULTS) that run on the embodiment kind with its services and model `roles`
    ({"main", "verifier"}), and runtime.strict_skills makes a dropped one an error."""
    if runtime.get("skills"):
        return Resolution(list(runtime["skills"]), dict(runtime.get("skills_dropped") or {}))
    return resolve(skills_for_layers(runtime.get("layers"), embodiment=embodiment),
                   available_services(model_services(runtime, roles)),
                   strict=bool(runtime.get("strict_skills", False)), embodiment=embodiment)


def model_names() -> list[str]:
    """The model files of configs/models/, by name."""
    return sorted(path.stem for path in MODELS_ROOT.glob("*.toml"))


def config_keys() -> dict:
    """The agent's [runtime] keys and what each does: RUNTIME_KEYS, and those packages
    document in their config_keys.toml ("runtime.<key>" = "what it does")."""
    from ..paths import find

    keys = dict(RUNTIME_KEYS)
    for path in find("config_keys.toml"):
        with path.open("rb") as handle:
            for key, about in tomllib.load(handle).items():
                name = key.removeprefix("runtime.")
                keys.setdefault(name, str(about))
    return dict(sorted(keys.items()))

def agent_file(value) -> Path:
    """An agent file: a path, or the name of a profile (configs/profiles/<name>.toml of the
    core or a package, e.g. robodojo)."""
    from ..paths import find, locate

    path = locate(Path(value))
    if path.is_file():
        return path.resolve()
    found = find(f"configs/profiles/{Path(str(value)).stem}.toml")
    if not found:
        raise ValueError(f"No agent file or profile {value!r}")
    return found[0].resolve()


def model_path(name) -> Path:
    """The file of a model: a name of configs/models/, or a path to a .toml file."""
    text = str(name)
    if text.endswith(".toml") or "/" in text or "\\" in text:
        path = Path(text).resolve()
    else:
        from ..paths import find

        path = (find(f"configs/models/{text}.toml") or [MODELS_ROOT / f"{text}.toml"])[0]
    if not path.is_file():
        raise ValueError(f"No model file {path}; models: {', '.join(model_names())}")
    return path


def load_model(source) -> dict:
    """Model roles: a model file's name or path (with its includes), a tree as it is,
    or {} for None."""
    if source is None:
        return {}
    if isinstance(source, dict):
        return source
    return load_layered(model_path(source))


def resolve_agent(agent=None, *, model=None, deploy=None, strict: bool = False, name: str | None = None,
                  runtime_overrides: dict | None = None, embodiment: str = "robot",
                  channels: bool = False, package_paths=(), frozen_identity: bool = False) -> ResolvedAgent:
    """Resolve the agent (a path or a merged tree; default configs/default.toml) with
    model roles from `model` (a model name, path or tree; default the agent's own
    `model`) against `deploy` (a Deploy, a name, or None for $HARNESS_DEPLOY), for an
    embodiment kind (the bench's: its skills and prompt). strict: a service or skill the
    agent names that cannot run here is an error instead of being left out.
    runtime_overrides (an experiment's changes to the agent) apply after the model file's
    runtime settings. channels: the bench's embodiment declares channels (the prompt's
    `channels` feature). frozen_identity retains the evaluator's schema-2 hash."""
    if embodiment not in KINDS:
        raise ValueError(f"Unknown embodiment kind {embodiment!r}; kinds are {sorted(KINDS)}")
    path = None
    if agent is None:
        agent = DEFAULT_AGENT
    if not isinstance(agent, dict):
        path = agent_file(agent)
        agent = load_layered(path)
    deploy = deploy if deploy is not None and not isinstance(deploy, (str, Path)) else load_deploy(deploy)
    tree = dict(agent)
    label = name or (path.stem if path else None)
    # A kind's table changes the agent on that kind's benches; the top level is the robot's.
    # Its runtime keys win over the model file's too (what a desktop sees does not
    # depend on the model).
    kinds = {kind: tree.pop(kind) for kind in KINDS if kind != "robot" and kind in tree}
    # The table of a kind no package here registers (the core's default names a game's
    # without the game package) is left out: no bench of that kind runs here.
    for key in [key for key, value in tree.items() if key not in AGENT_KEYS and isinstance(value, dict) and value
                and set(value) <= set(KIND_KEYS)]:
        tree.pop(key)
    unknown = set(tree) - set(AGENT_KEYS)
    if unknown:
        raise ValueError(f"Agent {path or label}: unknown keys {sorted(unknown)}")
    for kind, section in kinds.items():
        unknown = set(section) - set(KIND_KEYS)
        if unknown:
            raise ValueError(f"Agent {path or label}: [{kind}] takes {KIND_KEYS}, not {sorted(unknown)}")
        if "knowledge" in section and (KINDS[kind].knowledge is None or section["knowledge"] not in KNOWLEDGE):
            raise ValueError(f"Agent {path or label}: knowledge is declared by its kind, one of {list(KNOWLEDGE)}")
    kind_section = dict(kinds.get(embodiment, {}))
    kind_runtime = kind_section.pop("runtime", {})
    default_knowledge = KINDS[embodiment].knowledge
    knowledge = kind_section.pop("knowledge", default_knowledge)
    tree = deep_merge(tree, kind_section)
    roles_tree = load_model(model if model is not None else tree.get("model"))
    unknown = set(roles_tree) - {*ROLES, "runtime", "description"}
    if unknown:
        raise ValueError(f"Model: unknown roles {sorted(unknown)}; roles are {ROLES} (and runtime)")
    # The roles this agent uses (direct control without perception: main only).
    used = tree.get("roles", list(ROLES))
    if "main" not in used or set(used) - set(ROLES):
        raise ValueError(f"Agent {path or label}: roles must include main and be among {ROLES}")
    roles_tree = {key: value for key, value in roles_tree.items() if key not in ROLES or key in used}
    if deploy.automatic:
        # No deploy file: the harness places the services this agent names itself.
        deploy = automatic(_service_names(roles_tree, tree.get("services", {})))
    runtime = deep_merge(deep_merge(deep_merge(tree.get("runtime", {}), roles_tree.get("runtime", {})), kind_runtime),
                         runtime_overrides or {})
    if "approvals" in runtime:
        from harness.runtime.safety import approval

        from harness.runtime.safety import permissions

        policy = runtime["approvals"]
        if (not isinstance(policy, dict) or set(policy) - {"ask", "programs", "rules"}
                or policy.get("ask", "sensitive") not in approval.ASK
                or policy.get("programs", permissions.DEFAULT_LEVEL) not in approval.LEVELS):
            raise ValueError("runtime.approvals takes ask = sensitive or programs, programs = one of "
                             f"{', '.join(approval.LEVELS)}, and rules")
        if "rules" in policy:
            policy["rules"] = permissions.rules(policy["rules"])
    if runtime.get("task_descriptions") is False:
        runtime.pop("task_descriptions")
    if tree.get("mode", "program") == "direct":
        if not tree.get("actions"):
            raise ValueError(f"Agent {path or label}: direct mode needs actions = \"module:function\", its action "
                             "vocabulary")
        runtime["mode"] = "direct"
        runtime["actions"] = tree["actions"]
    if runtime.get("contract", "native") not in KINDS[embodiment].contracts:
        raise ValueError(f"runtime.contract on a {embodiment} must be one of {KINDS[embodiment].contracts}")
    placement = {}
    main, record = _role(roles_tree.get("main"), deploy, "main", strict)
    if main is None:
        raise ValueError(f"Agent {path or label}: no main model role")
    if record:
        placement["main"] = record
    for role in ("vlm", "pointer"):
        config, record = _role(roles_tree.get(role), deploy, role, strict)
        if config is not None:
            runtime[role] = config
        if record:
            placement[role] = record
    # The verifier's keys sit on top of main's; a URL it names is resolved as main's is.
    verifier, record = _role(roles_tree.get("verifier"), deploy, "verifier", strict)
    verifier = verifier or {}
    if record:
        placement["verifier"] = record
    services = tree.get("services", {})
    unknown = set(services) - set(SERVICE_KEYS)
    if unknown:
        raise ValueError(f"Agent {path or label}: services are {SERVICE_KEYS}, not {sorted(unknown)}")
    for key in ("segmenter", "vision"):
        if services.get(key):
            service, config = _service(services[key], deploy, strict, key)
            placement[key] = {"service": service, **({} if config else {"dropped": "not run here"})}
            if config is not None:
                runtime[key] = config
    for key in ("policies", "world_models", "mcp"):
        entries = services.get(key, [])
        chosen = {}
        for entry in entries:
            service, config = _service(entry, deploy, strict, SERVICE_ENTRY[key])
            placement.setdefault(key, {})[service] = {} if config else {"dropped": "not run here"}
            if config is not None:
                chosen[service] = config
        if entries:
            runtime[key] = chosen
    # Skills: the interface layers' (R0-R4) or a list, without the disabled ones.
    skills = tree.get("skills", {})
    unknown = set(skills) - {"layers", "names", "enable", "disable"}
    if unknown:
        raise ValueError(f"Agent {path or label}: skills takes layers, names, enable, disable; not {sorted(unknown)}")
    runtime["layers"] = {**LAYER_DEFAULTS, **skills.get("layers", {})}
    requested = (list(skills.get("names") or skills_for_layers(runtime["layers"], embodiment=embodiment))
                 + list(skills.get("enable", [])))
    requested = [skill for skill in dict.fromkeys(requested) if skill not in set(skills.get("disable", []))]
    if knowledge == "learned":
        # The agent learns the game itself: none of the skills written for it by hand, and
        # its own skill library instead.
        named = sorted(set(handwritten()) & (set(skills.get("names") or ()) | set(skills.get("enable", ()))))
        if named:
            raise ValueError(f"Agent {path or label}: knowledge = \"learned\" gives the agent no handwritten skills, "
                             f"but it names {named} (knowledge = \"handwritten\" is the baseline with them)")
        requested = [skill for skill in requested if skill not in set(handwritten())]
    if knowledge is not None:
        runtime["knowledge"] = knowledge
    if (runtime.get("library") or {}).get("learn") == "on":
        # A run whose library learns: programs propose entries (in-context learning), and the
        # body can be probed (its package's probe, runtime/learning/active.py; the others are dropped
        # as skills of another embodiment).
        from harness.runtime.learning.active import schedule
        from harness.runtime.execution.skills import probes

        schedule(runtime["library"])
        requested = [*requested, "learning", *probes()]
    # A skill the agent leaves out by design (R0 has no vision roles) is dropped here on
    # every machine. Strictness is about the machine: the services the agent names were
    # checked above; a skill named in skills.names that cannot run is the one more error.
    resolution = resolve(requested, available_services(model_services(runtime, {"main": main, "verifier": verifier})),
                         embodiment=embodiment)
    named = {skill: why for skill, why in resolution.dropped.items()
             if skill in set(skills.get("names") or ()) | set(skills.get("enable", ()))}
    if strict and named:
        raise ValueError(f"Agent {path or label}: skills it names cannot run: {named}")
    runtime["skills"] = resolution.enabled
    if resolution.dropped:
        runtime["skills_dropped"] = resolution.dropped
    # The prompt: a pack directory assembled for the skills, or files as they are; a
    # table of them gives the embodiment's.
    sources = tree.get("prompt", [])
    if isinstance(sources, dict):
        # Keyed by kind; a kind no package here registers names a prompt that is not used here.
        if embodiment not in sources:
            raise ValueError(f"Agent {path or label}: a prompt table is keyed by embodiment kinds "
                             f"({', '.join(sorted(KINDS))} here) and needs one for {embodiment}")
        sources = sources[embodiment]
    sources = [sources] if isinstance(sources, str) else list(sources)
    texts = []
    for source in sources:
        source = Path(source)
        features = features_for(runtime, channels, embodiment=embodiment)
        texts.append(assemble_prompt(source, runtime["skills"], features=features,
                                     installed=runtime.get("installed_skills", ()),
                                     agent_skills=runtime.get("agent_skills"), embodiment=embodiment) if source.is_dir()
                     else select(source.read_text(encoding="utf-8"), set(runtime["skills"]) | features))
    system_prompt = "".join(text if text.endswith("\n") else text + "\n" for text in texts)
    base_prompt = system_prompt
    if runtime.get("library"):
        from harness.runtime.learning.library import library_for

        library = library_for(runtime, Path("/"))
        if "experience" in runtime["library"]:
            table = runtime["library"]
            modes = {"learn": "on", "read": "off", "off": "off"}
            experience = table["experience"]
            if experience not in modes:
                raise ValueError("runtime.library.experience was one of read, learn, off; use runtime.library.uses")
            if embodiment != "robot":
                table.pop("experience")
                table.setdefault("uses", modes[experience])
        from harness.runtime.learning.usage import USES

        if runtime["library"].get("uses", "learn") not in USES:
            raise ValueError(f"runtime.library.uses is one of {list(USES)}, not {runtime['library']['uses']!r}")
        from harness.runtime.learning.learner import settings as learning

        captured = library.capture()
        if learning(runtime["library"])["learn"] == "on":
            # A library that learns grows from run to run: the configuration names it and
            # its settings, and each run records the version it started with.
            runtime["library"] = {**runtime["library"], "manifest": {
                "directory": str(library.directory), "layers": list(library.layers), "learns": True}}
        else:
            runtime["library"] = {**runtime["library"], "path": str(library.directory),
                                  "manifest": captured.manifest()}
        reactive = "reactive" in runtime["skills"]
        selected = {item.key for item in captured.entries if item.key.startswith("skills/")
                    or reactive and item.key.startswith("reactive/")}
        system_prompt += captured.api_summary(selected) + captured.notes()
    budget = tree.get("budget", {})
    calls = int(budget.get("max_model_calls", 30))
    if calls < 1:
        raise ValueError("budget.max_model_calls must be a positive integer")
    lock = {
        "schema": 2,
        "agent": label,
        "mode": runtime.get("mode", "program"),
        # A library that learns: the prompt without what it holds (each run records its version).
        "prompt_sha256": hashlib.sha256((base_prompt if (runtime.get("library") or {}).get("manifest", {}).get("learns")
                                         else system_prompt).encode()).hexdigest(),
        "prompt_sources": _relative([str(s) for s in sources]),
        "skills": runtime["skills"],
        "skills_dropped": runtime.get("skills_dropped", {}),
        # Roles by what they are, not where they run: a service-backed role is its service.
        "roles": {role: _lock_role(roles_tree.get(role)) for role in ROLES if roles_tree.get(role)},
        "services": {key: services.get(key) for key in SERVICE_KEYS if services.get(key)},
        # Without [environment]: how a service is installed does not change what it computes.
        "service_manifests": {service: sha256({key: value for key, value in read_toml(deploy.services[service].path)
                                               .items() if key != "environment"})
                              for service in _service_names(roles_tree, services) if service in deploy.services},
        "runtime": _relative({key: value for key, value in runtime.items()
                              if key not in ("vlm", "pointer", "segmenter", "vision", "policies", "world_models", "mcp")}),
        "budget": {"max_model_calls": calls},
    }
    if frozen_identity:
        # Keep the original hash input for an unchanged score configuration and
        # let the evaluator continue to reject genuinely different settings.
        lock["agent_version"] = __version__
    else:
        lock.update(schema=3, version=__version__,
                    packages=package_lock([path, *package_paths, *sources, *(deploy.services[name].path for name in
                        _service_names(roles_tree, services) if name in deploy.services), *(
                        skill.path for name, skill in _skills().items() if name in runtime["skills"])]))
    if embodiment != "robot":
        lock["embodiment"] = embodiment
    return ResolvedAgent(name=label, path=path, main=main, verifier=verifier, runtime=runtime,
                         system_prompt=system_prompt, base_prompt=base_prompt, max_model_calls=calls, lock=lock,
                         identity=sha256(lock)[:16], placement=placement,
                         sources={"agent": {key: value for key, value in tree.items() if key != "model"},
                                  "model": roles_tree, "runtime_overrides": runtime_overrides or {}},
                         embodiment=embodiment, deploy=deploy)


def _skills() -> dict:
    from harness.runtime.execution.skills import load_skills

    return load_skills()


def package_lock(used=()) -> dict:
    """Lock the packages containing `used` paths and their installed dependencies.
    Registry store entries use the archive digest. Checkouts and local or linked
    packages use a content hash."""
    from ..packages import Packages
    from ..packages.state import store_path
    from ..paths import packages

    used = [Path(item).resolve() for item in used if item]
    available = {package.name: package for package in packages()}
    roots = {name: package.path.resolve() for name, package in available.items()}
    selected = {name for name, root in roots.items() if any(path.is_relative_to(root) for path in used)}
    pending = list(selected)
    while pending:
        dependencies = (available[pending.pop()].depends.keys() & available.keys()) - selected
        selected.update(dependencies)
        pending.extend(dependencies)
    if not selected:
        return {}

    installed = Packages().records()
    lock = {}
    for name in sorted(selected):
        package, root = available[name], roots[name]
        record, _ = installed.get(name, (None, None))
        released = (record is not None and record.source == "registry" and record.sha256 and not record.link
                    and record.version == package.version
                    and root == store_path(name, record.version, record.sha256).resolve())
        lock[name] = {"version": package.version,
                      **({"sha256": record.sha256} if released else {"content": package_content(root)})}
    return lock


def package_content(root: Path) -> str:
    """Hash a local package's file paths and content, excluding installed dependencies and caches."""
    digest = hashlib.sha256()
    excluded = {"__pycache__", ".deps", ".git", "node_modules", ".pytest_cache"}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in excluded or part.startswith(".venv") for part in relative.parts):
            continue
        name = relative.as_posix().encode()
        with path.open("rb") as file:
            content = hashlib.file_digest(file, "sha256").digest()
        digest.update(name + b"\0" + content)
    return digest.hexdigest()


def overridden_agent(overrides: dict | None = None, *, agent=None, model=None, deploy=None, strict: bool = False,
                     embodiment: str = "robot", channels: bool = False, package_paths=(), frozen_identity: bool = False) -> ResolvedAgent:
    """The agent file (default configs/default.toml) with `overrides` ({"agent": ...,
    "model": ...}, an experiment's or a conversation's changes) applied and its model roles
    from `model` (default the agent's), resolved against `deploy` (resolve_agent)."""
    overrides = overrides or {}
    unknown = set(overrides) - {"agent", "model"}
    if unknown:
        raise ValueError(f"overrides are [overrides.agent] and [overrides.model], not {sorted(unknown)}")
    path = agent_file(agent or DEFAULT_AGENT)
    tree = deep_merge(load_layered(path), overrides.get("agent", {}))
    roles = deep_merge(load_model(model or tree.get("model")), overrides.get("model", {}))
    return resolve_agent(tree, model=roles, deploy=deploy, strict=strict, name=path.stem,
                         runtime_overrides=overrides.get("agent", {}).get("runtime"), embodiment=embodiment,
                         channels=channels, package_paths=[path, *package_paths], frozen_identity=frozen_identity)


def task_description(runtime: dict, task: str) -> str:
    """The task's description (RoboDojo wiki recipe) when the agent uses them."""
    directory = runtime.get("task_descriptions")
    if not directory:
        return ""
    source = Path(directory) / f"{task.removesuffix('_random')}.md"
    if not source.is_file():
        raise ValueError(f"No task description for {task} in {directory}")
    return source.read_text(encoding="utf-8").strip()


def task_config(agent: ResolvedAgent, task: str, seeds, *, budget: dict | None = None, endpoint: str | None = None,
                timeout_seconds: float = 600.0, path: Path | None = None):
    """The configuration (TaskConfig) of `task` with `seeds` for a
    resolved agent, under a per-episode `budget` (max_model_calls, max_wall_seconds,
    max_cost_usd) and against the worker at `endpoint`."""

    seeds = list(seeds)
    if not seeds or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be a nonempty list of distinct integers")
    budget = budget or {}
    cost = budget.get("max_cost_usd")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost <= 0):
        raise ValueError("budget.max_cost_usd must be a positive number")
    return TaskConfig(
        path=path or Path("."), environment={"endpoint": endpoint, "timeout_seconds": timeout_seconds},
        main=dict(agent.main), runtime=dict(agent.runtime), system_prompt=agent.system_prompt, task=task,
        seeds=seeds, max_model_calls=int(budget.get("max_model_calls", agent.max_model_calls)),
        max_wall_seconds=float(budget.get("max_wall_seconds", 3600)), verifier=dict(agent.verifier),
        base_prompt=agent.base_prompt, task_description=task_description(agent.runtime, task),
        max_cost_usd=None if cost is None else float(cost), lock=agent.lock, agent_id=agent.identity,
        placement={"deploy": getattr(agent.deploy, "name", None), **agent.placement},
        embodiment=agent.embodiment)


def _lock_role(spec):
    spec = dict(spec)
    return {key: value for key, value in spec.items() if key not in ("api_key", "base_url")} \
        if "service" in spec else {key: value for key, value in spec.items() if key != "api_key"}


def _service_names(roles_tree, services):
    names = [spec["service"] for spec in roles_tree.values() if isinstance(spec, dict) and "service" in spec]
    for key in ("segmenter", "vision"):
        if services.get(key):
            entry = services[key]
            names.append(entry if isinstance(entry, str) else entry["service"])
    for key in ("policies", "world_models", "mcp"):
        names += [entry if isinstance(entry, str) else entry["service"] for entry in services.get(key, [])]
    return sorted(set(names))
