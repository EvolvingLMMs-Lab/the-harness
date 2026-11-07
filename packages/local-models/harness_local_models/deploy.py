"""Deploy files: where the services of one machine run.

configs/deploy/<machine>.toml says which GPUs this machine gives the project, where
its weights live, and for each service how it runs (git ignores machine files there;
only the example-*.toml ones are tracked):

    weights = "/data/weights"         root of the services' weight directories
    state = "/data/harness-services"  pid files and logs of started services
    gpus = [2, 3, 4, 5]               GPUs services and simulators may use
    gpu_memory_gb = 24

    [sim]                             simulator workers of `harness run`
    gpus = [5]
    workers_per_gpu = 2

    [benches.osomni]                  a bench's own settings (its bench.toml `deploy` keys):
    checkout = "/data/OS-Omni"        here OS-Omni's checkout, environment and desktop VMs,
    python = "/data/OS-Omni/.venv/bin/python"                         one worker each
    machines = [{ runtime_url = "http://127.0.0.1:15001", qmp_socket = "/vm/qmp-1.sock" }]

    [services.sam3]
    gpu = 3                           a GPU index, or "auto" (fit by vram_gb)
    [services.molmo2]
    mode = "external"                 someone else runs it
    url = "http://10.0.0.7:8830"
    [services.openwam]
    mode = "off"

    [services.g05]
    gpu = 1
    mode = "on_demand"                started when a skill first calls it ...
    swap = "big"                      ... and sharing GPU 1 with the other services of
    [services.openwam]                its swap group, one loaded at a time
    gpu = 1
    mode = "on_demand"
    swap = "big"

A service the deploy file does not list is off. Modes: resident (started by
`harness up`, kept running), on_demand (started by the broker when a skill needs it,
stopped after idle_seconds or when a peer of its swap group is needed; see broker.py),
external (only a URL), off. Placement never changes what a run computes, only where
and when; systems decide which services a run uses.

Without a deploy file the harness writes its own (automatic): the services a run uses,
on the GPUs nvidia-smi lists, by their free memory, after room for one simulator worker;
resident when they fit, else on demand in one swap group (SWAP_LEVELS). It is kept in
~/.cache/harness/deploy/auto.toml and reused while it places every service asked for.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
import tomllib

from harness.sdk import ROOT, SERVICES_ROOT, toml_dumps, ServiceSpec, find, home, load_services, python_path, third_party
from harness.sdk import free_port


REPO = ROOT
DEPLOY_ROOT = ROOT / "configs" / "deploy"  # a name is looked up in every root (find)
MODES = ("resident", "on_demand", "external", "off")
# Modes in which a service runs on this machine.
LOCAL = ("resident", "on_demand")
# The keys of configs/deploy/<machine>.toml.
DEPLOY_KEYS = {
    "weights": "root of the services' weight directories (relative to the file, or absolute; "
               "default ~/.cache/harness/weights)",
    "state": "pid files and logs of the services it starts (default ~/.cache/harness/services)",
    "robodojo": "the RoboDojo checkout (default $HARNESS_ROBODOJO_ROOT, else a checkout's third_party/RoboDojo, "
                "else the one `harness install robodojo` puts under ~/.cache/harness)",
    "xpolicylab": "the XPolicyLab checkout (default <robodojo>/XPolicyLab)",
    "gpus": "the GPUs services and simulators may use",
    "gpu_memory_gb": "memory of each of those GPUs (default 24); gpu = \"auto\" plans with it",
    "sim": "simulator workers of `harness run`: gpus, workers_per_gpu, base_port",
    "benches": "[benches.<name>]: a bench's settings on this machine, the keys of its bench.toml `deploy` "
               "(OS-Omni: checkout, python, base_port, machines)",
    "services": "[services.<name>] for each service that runs here; a service not listed is off",
    "broker_port": "where the broker of on-demand services listens (default 8899)",
    "environments": "own (default: each service and benchmark in an environment of its own, installed on first "
                    "use) or project (all in the harness's own interpreter: a checkout's development environment)",
    "reserved": "GPU memory already taken, in GB by GPU index (\"0\" = 9.0): placement leaves it free (the "
                "harness's own placement writes the simulator's and other processes' memory here)",
}
# The keys of one [services.<name>] table of a deploy.
PLACEMENT_KEYS = {
    "mode": f"one of {', '.join(MODES)} (default resident)",
    "gpu": "a GPU index, or \"auto\": the GPU with the most room for its vram_gb",
    "port": "a port other than the manifest's",
    "url": "for mode external: where it answers",
    "python": "another interpreter for it",
    "env": "extra environment variables",
    "swap": "on_demand: the swap group; services of one group share a GPU, one loaded at a time",
    "idle_seconds": "on_demand: stop it after this long without a request",
}
DEPLOY_ENV = "HARNESS_DEPLOY"


@dataclass
class Placement:
    """How one service runs on a deploy (PLACEMENT_KEYS). A service the deploy file does
    not list has mode off; loading the deploy replaces gpu = "auto" with a GPU index."""

    service: str
    mode: str = "off"
    gpu: int | str | None = None
    port: int | None = None
    url: str | None = None
    python: str | None = None
    env: dict = field(default_factory=dict)
    # on_demand: services of one swap group share a GPU, one loaded at a time.
    swap: str | None = None
    idle_seconds: float | None = None


@dataclass
class Deploy:
    """A loaded deploy file: the machine's weights, state and checkout paths, its GPUs, the
    simulator settings, and the placement of each service it lists. Without a deploy file
    (name "none") every service is off."""

    name: str
    path: Path | None
    weights: Path
    state: Path
    robodojo: Path
    xpolicylab: Path
    gpus: list[int] | None
    gpu_memory_gb: float
    sim: dict
    placements: dict[str, Placement]
    # Each bench's [benches.<name>] table, as the bench validated it (harness.bench).
    benches: dict = field(default_factory=dict)
    services_root: Path = SERVICES_ROOT
    # The broker of on-demand services listens here (services/broker.py).
    broker_port: int = 8899
    # "own": services and benchmarks in environments of their own (environments.py);
    # "project": everything in the harness's own interpreter.
    environments: str = "own"
    # GPU memory (GB) already taken on each GPU, by index: placement starts from it.
    reserved: dict = field(default_factory=dict)

    @property
    def automatic(self) -> bool:
        """Whether there is no deploy file: the harness places what a run uses itself
        (automatic())."""
        return self.path is None

    @property
    def services(self) -> dict[str, ServiceSpec]:
        """Every service manifest (under `services_root`) by name, whether it runs here or not."""
        return load_services(self.services_root)

    def placement(self, name: str) -> Placement:
        """How service `name` runs here (mode off when the file does not list it); an
        unknown service is an error."""
        if name not in self.services:
            raise ValueError(f"Unknown service {name!r}; known: {sorted(self.services)}")
        return self.placements.get(name) or Placement(name)

    def variables(self) -> dict:
        """The placeholders of service commands, settings and needed files: python (this
        process's interpreter; launch() gives each service its environment's), repo,
        weights, robodojo, xpolicylab, xpolicylab_parent, state."""
        return {"python": sys.executable, "repo": str(REPO), "weights": str(self.weights),
                "robodojo": str(self.robodojo), "xpolicylab": str(self.xpolicylab),
                "xpolicylab_parent": str(self.xpolicylab.parent), "state": str(self.state)}


def _benches(data: dict, base: Path, path) -> dict:
    """A deploy's [benches.<name>] tables, as they are: the eval package reads each where its
    bench runs (its check_deploy checks the keys and resolves the paths against the deploy
    file)."""
    tables = {}
    for name, table in data.items():
        if not isinstance(table, dict):
            raise ValueError(f"{path}: [benches.{name}] is a table")
        tables[name] = dict(table)
    return tables


def _resolve(value, base: Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return path if path.is_absolute() else (base / path).resolve()


def deploy_path(name: str | os.PathLike | None) -> Path | None:
    """The deploy file for a name (configs/deploy/<name>.toml) or a path; None names
    $HARNESS_DEPLOY, and without it there is no deploy file."""
    name = name or os.environ.get(DEPLOY_ENV)
    if not name:
        return None
    path = Path(name)
    if path.suffix == ".toml" or path.exists():
        return path.resolve()
    found = find(f"configs/deploy/{name}.toml")
    if not found:
        known = sorted({p.stem for folder in find("configs/deploy") for p in folder.glob("*.toml")})
        raise ValueError(f"No deploy file configs/deploy/{name}.toml; known: {known}")
    return found[0]


def load_deploy(name: str | os.PathLike | None = None, *, services_root: Path = SERVICES_ROOT) -> Deploy:
    """The deploy of `name` (see deploy_path); without one, every service is off and
    only hosted models are available."""
    path = deploy_path(name)
    data = {}
    if path is not None:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    unknown = set(data) - set(DEPLOY_KEYS)
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    base = path.parent if path else Path.cwd()
    robodojo = _resolve(data.get("robodojo") or third_party("RoboDojo"), base)
    deploy = Deploy(
        name=path.stem if path else "none", path=path,
        weights=_resolve(data.get("weights", home() / "weights"), base),
        state=_resolve(data.get("state", home() / "services"), base),
        robodojo=robodojo, xpolicylab=_resolve(data.get("xpolicylab", robodojo / "XPolicyLab"), base),
        gpus=[int(g) for g in data["gpus"]] if "gpus" in data else None,
        gpu_memory_gb=float(data.get("gpu_memory_gb", 24.0)), sim=dict(data.get("sim", {})),
        placements={}, services_root=services_root, broker_port=int(data.get("broker_port", 8899)),
        benches=_benches(data.get("benches") or {}, base, path),
        environments=str(data.get("environments", "own")),
        reserved={int(gpu): float(amount) for gpu, amount in (data.get("reserved") or {}).items()})
    if deploy.environments not in ("own", "project"):
        raise ValueError(f"{path}: environments must be own or project")
    services = deploy.services
    for name, entry in (data.get("services") or {}).items():
        if name not in services:
            raise ValueError(f"{path}: unknown service {name!r}; known: {sorted(services)}")
        if not isinstance(entry, dict):
            entry = {"mode": str(entry)}
        unknown = set(entry) - set(PLACEMENT_KEYS)
        if unknown:
            raise ValueError(f"{path}: services.{name} has unknown keys {sorted(unknown)}")
        mode = entry.get("mode", "resident")
        if mode not in MODES:
            raise ValueError(f"{path}: services.{name}.mode must be one of {MODES}")
        if mode == "external" and not entry.get("url"):
            raise ValueError(f"{path}: services.{name} is external and needs a url")
        if mode in LOCAL and "gpu" not in entry and services[name].vram_gb > 0:
            raise ValueError(f"{path}: services.{name} runs here and needs a gpu (an index or \"auto\")")
        if entry.get("swap") and mode != "on_demand":
            raise ValueError(f"{path}: services.{name}: only on_demand services swap")
        deploy.placements[name] = Placement(name, mode, entry.get("gpu"), entry.get("port"), entry.get("url"),
                                            entry.get("python"), dict(entry.get("env", {})), entry.get("swap"),
                                            entry.get("idle_seconds"))
    _place(deploy)
    return deploy


def _place(deploy: Deploy) -> None:
    """Give services with gpu = "auto" a GPU of the deploy that still has room for
    them (largest first; the members of a swap group share one GPU and need the room of
    the largest), and check that no two services share a port."""
    services = deploy.services
    used = dict(planned_memory(deploy))
    for gpu, amount in deploy.reserved.items():
        used[gpu] = used.get(gpu, 0.0) + amount
    units: dict[tuple, list] = {}
    fixed: dict[str, int] = {}
    for placement in deploy.placements.values():
        swap = placement.swap if placement.mode == "on_demand" else None
        if placement.mode in LOCAL and placement.gpu == "auto":
            units.setdefault(("swap", swap) if swap else ("service", placement.service), []).append(placement)
        elif swap and isinstance(placement.gpu, int):
            fixed[swap] = placement.gpu

    def need(members):
        return max(services[p.service].vram_gb for p in members)

    for key, members in sorted(units.items(), key=lambda item: -need(item[1])):
        amount = need(members)
        names = ", ".join(p.service for p in members)
        if key[0] == "swap" and key[1] in fixed:
            # A member was placed by hand: the group is on its GPU, and grows to the largest.
            gpu = fixed[key[1]]
            placed = max(services[p.service].vram_gb for p in deploy.placements.values()
                         if p.mode == "on_demand" and p.swap == key[1] and isinstance(p.gpu, int))
            extra = max(0.0, amount - placed)
            if used.get(gpu, 0.0) + extra > deploy.gpu_memory_gb:
                raise ValueError(f"GPU {gpu} of swap group {key[1]} has no room for {names} (planned: {used})")
        else:
            extra = amount
            candidates = [g for g in (deploy.gpus or []) if used.get(g, 0.0) + amount <= deploy.gpu_memory_gb]
            if not candidates:
                raise ValueError(f"No GPU of {deploy.gpus} has {amount:g} GB left for {names} (planned: {used})")
            gpu = min(candidates, key=lambda g: used.get(g, 0.0))
        used[gpu] = used.get(gpu, 0.0) + extra
        for placement in members:
            placement.gpu = gpu
    ports = {}
    for placement in deploy.placements.values():
        if placement.mode in LOCAL:
            port = placement.port or services[placement.service].port
            if port in ports:
                raise ValueError(f"Services {ports[port]} and {placement.service} both use port {port}")
            ports[port] = placement.service


def planned_memory(deploy: Deploy) -> dict[int, float]:
    """GPU memory the deploy plans per GPU: resident services add up, a swap group
    counts as its largest member (one is loaded at a time)."""
    services = deploy.services
    used: dict[int, float] = {}
    groups: dict[tuple, float] = {}
    for placement in deploy.placements.values():
        if placement.mode not in LOCAL or not isinstance(placement.gpu, int):
            continue
        need = services[placement.service].vram_gb
        if placement.mode == "on_demand" and placement.swap:
            key = (placement.gpu, placement.swap)
            groups[key] = max(groups.get(key, 0.0), need)
        else:
            used[placement.gpu] = used.get(placement.gpu, 0.0) + need
    for (gpu, _group), need in groups.items():
        used[gpu] = used.get(gpu, 0.0) + need
    return used


def render(value, variables: dict):
    """Fill {name} placeholders in strings (recursively in lists and dicts)."""
    if isinstance(value, str):
        out = value
        for key, item in variables.items():
            out = out.replace("{" + key + "}", str(item))
        return out
    if isinstance(value, (list, tuple)):
        return [render(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render(item, variables) for key, item in value.items()}
    return value


def port(deploy: Deploy, name: str) -> int:
    """The port a service listens on here: its placement's, else its manifest's."""
    placement = deploy.placement(name)
    return int(placement.port or deploy.services[name].port)


def url(deploy: Deploy, name: str) -> str | None:
    """Where clients reach a service, or None when it is off."""
    placement = deploy.placement(name)
    if placement.mode == "off":
        return None
    if placement.mode == "external":
        return placement.url.rstrip("/")
    scheme = "ws" if deploy.services[name].protocol == "xpolicylab" else "http"
    return f"{scheme}://127.0.0.1:{port(deploy, name)}"


def client_config(deploy: Deploy, name: str) -> dict | None:
    """The config a skill or agent uses for this service (its manifest's client table
    with the URL filled in), or None when the deploy does not run it."""
    address = url(deploy, name)
    if address is None:
        return None
    spec = deploy.services[name]
    host_port = address.split("://", 1)[-1]
    variables = {"url": address, "host": host_port.rsplit(":", 1)[0],
                 "port": host_port.rsplit(":", 1)[-1] if ":" in host_port else ""}
    config = render(spec.client or {"url": "{url}"}, variables)
    if deploy.placement(name).mode == "on_demand":
        # Clients ask the broker to start it before each call (services/broker.py).
        config["on_demand"] = {"url": f"http://127.0.0.1:{deploy.broker_port}", "service": name}
    return config


def launch(deploy: Deploy, name: str) -> tuple[list[str], dict, str]:
    """(argv, environment, working directory) that start a service of this deploy."""
    from harness_local_models.provision import python as interpreter

    spec = deploy.services[name]
    placement = deploy.placement(name)
    variables = {**deploy.variables(), "port": port(deploy, name), "python": interpreter(deploy, name),
                 "package": package_folder(spec)}
    python = render(placement.python or spec.python, variables)
    variables["python"] = python
    # An xpolicylab service runs XPolicyLab's own server for its policy folder, unless it
    # brings a command that serves the same protocol (services/openwam-policy.toml).
    if spec.protocol == "xpolicylab" and not spec.command:
        xpl = spec.xpolicylab
        policy = xpl["policy"]
        overrides = {"host": "127.0.0.1", "port": variables["port"], "bench_name": xpl.get("bench_name", "RoboDojo"),
                     "task_name": "any", "ckpt_name": xpl.get("ckpt_name", "default"),
                     "env_cfg_type": xpl.get("env_cfg_type", "arx_x5"), "seed": 0, "policy_name": policy,
                     "action_type": xpl.get("action_type", "joint"), "action_dim": xpl.get("action_dim", 14),
                     **xpl.get("overrides", {})}
        argv = [python, "-u", "{xpolicylab}/setup_policy_server.py", "--config_path",
                f"{{xpolicylab}}/policy/{policy}/deploy.yml", "--overrides",
                *[f"{key}={value}" for key, value in overrides.items()]]
        pythonpath = xpl.get("pythonpath", ["{xpolicylab_parent}", "{xpolicylab}"])
        environment = {"PYTHONPATH": os.pathsep.join(render(pythonpath, variables)),
                       "PYTHONWARNINGS": "ignore::UserWarning"}
        cwd = xpl.get("cwd", "{xpolicylab}")
    else:
        argv = list(spec.command)
        environment = {"PYTHONPATH": python_path()}
        cwd = spec.cwd
    environment.update({"PYTHONUNBUFFERED": "1", **spec.env, **placement.env})
    if isinstance(placement.gpu, int):
        environment["CUDA_VISIBLE_DEVICES"] = str(placement.gpu)
    elif placement.gpu is None:
        environment["CUDA_VISIBLE_DEVICES"] = ""
    return render(argv, variables), render(environment, variables), render(cwd, variables)


def weight_dirs(deploy: Deploy, name: str) -> list[Path]:
    """The service's weight directories under the deploy's weights root, one per
    `[[weights]]` entry."""
    return [deploy.weights / entry["dir"] for entry in deploy.services[name].weights]


def missing_files(deploy: Deploy, name: str) -> list[str]:
    """Files the service needs that are not on this machine."""
    spec = deploy.services[name]
    variables = {**deploy.variables(), "package": package_folder(spec)}
    return [path for path in render(list(spec.needs_files), variables) if not Path(path).exists()]


def package_folder(spec) -> str:
    """{package} of a service: the folder of the package (or the core) whose services/
    holds its manifest."""
    return str(spec.path.parent.parent) if spec.path is not None else str(REPO)


# When the services do not all fit the GPUs at once, the kinds that load on demand (one
# swap group, one model loaded at a time), level by level: first the learned policies
# and world models, then every model but the kinematics, which every tick of a motion
# needs.
SWAP_LEVELS = ((), ("policy", "world_model"), ("policy", "world_model", "pointer", "segmenter", "vision", "vlm", "llm"))
# GPU memory the automatic placement leaves for one simulator worker (6-9 GB measured).
SIM_GPU_GB = 9.0




def fit(path: Path, head: dict, entries: dict, *, keep=(), comment: str = "", log=print) -> Deploy:
    """Write the deploy of `head` (top-level keys) and `entries` (one placement per
    service) to `path` and load it: every service as its entry says when they all fit,
    else the kinds of SWAP_LEVELS on demand in one swap group ("models"), level by level.
    Services in `keep` keep the mode their entry gives."""
    registry = load_services()
    path.parent.mkdir(parents=True, exist_ok=True)

    def write(kinds):
        services = {}
        for name, entry in entries.items():
            entry = services[name] = dict(entry)
            if entry.get("mode") == "resident" and registry[name].kind in kinds and name not in keep:
                entry["mode"], entry["swap"] = "on_demand", "models"
        path.write_text(toml_dumps({**head, "services": services}, comment), encoding="utf-8")
        return load_deploy(path)

    for level, kinds in enumerate(SWAP_LEVELS):
        try:
            deploy = write(kinds)
        except ValueError as error:
            if level + 1 == len(SWAP_LEVELS):
                raise ValueError(f"The services {sorted(entries)} do not fit GPUs {head.get('gpus')} even one "
                                 f"model at a time: {error}") from None
            continue
        if kinds:
            log(f"harness: the services do not all fit GPUs {head.get('gpus')} at once; "
                f"{', '.join(kinds)} services load on demand, one at a time")
        return deploy


def automatic(names, *, gpu_rows=None, log=print) -> Deploy:
    """The harness's own deploy for the services `names` (no deploy file): on the GPUs
    of this machine by their free memory now, after room for one simulator worker on the
    GPU with the most; resident when they fit, else on demand by SWAP_LEVELS, each on its
    manifest's port unless something the harness did not start answers there. A service
    that needs a GPU on a machine without one is off. The deploy is written to
    ~/.cache/harness/deploy/auto.toml and reused while it places every service of `names`."""
    from harness_local_models.tools import gpus

    path = home() / "deploy" / "auto.toml"
    names = sorted(set(names))
    if not names:
        return load_deploy(None)
    try:
        previous = load_deploy(path) if path.is_file() else None
    except ValueError:
        previous = None
    if previous is not None and all(name in previous.placements for name in names):
        # Kept unless something it did not start took one of its ports since.
        taken = [name for name, placement in previous.placements.items() if placement.mode in LOCAL
                 and _answers(port(previous, name)) and not (previous.state / f"{name}.json").is_file()]
        if not taken:
            return previous
    names = sorted(set(names) | set(previous.placements if previous else ()))
    services = load_services()
    rows = gpu_rows if gpu_rows is not None else (gpus() or [])
    devices = [row["index"] for row in rows]
    total = max((row["total_gb"] for row in rows), default=0.0)
    # Memory taken now; a smaller GPU counts its missing memory as taken.
    used = {row["index"]: round(row["used_gb"] + total - row["total_gb"], 1) for row in rows}
    head = {"gpus": devices, "gpu_memory_gb": total or 24.0}
    if devices:
        sim = min(devices, key=lambda gpu: used[gpu])
        used[sim] += SIM_GPU_GB
        head["sim"] = {"gpus": [sim], "workers_per_gpu": 1}
    head["reserved"] = {str(gpu): amount for gpu, amount in used.items() if amount > 0}
    entries = {}
    for name in names:
        if services[name].vram_gb > 0 and not devices:
            entries[name] = {"mode": "off"}
        else:
            entries[name] = {"mode": "resident", **({"gpu": "auto"} if services[name].vram_gb > 0 else {})}
            # Its port answers, but not for a service the harness started here: something
            # else has it (a deploy file says when that is the service to use), so another port.
            if _answers(services[name].port) and not (home() / "services" / f"{name}.json").is_file():
                entries[name]["port"] = free_port()
    while True:
        if all(entry["mode"] == "off" for entry in entries.values()):
            path.unlink(missing_ok=True)
            return load_deploy(None)
        try:
            return fit(path, head, entries, log=log,
                       comment="Written by the harness for this machine (no deploy file); free GPU memory at the time")
        except ValueError:
            # Even one model at a time does not fit: the largest is off here (a run that
            # needs it fails when strict, else drops what uses it).
            largest = max((name for name, entry in entries.items() if entry["mode"] != "off"),
                          key=lambda name: services[name].vram_gb)
            log(f"harness: {largest} ({services[largest].vram_gb:g} GB) does not fit the free memory of GPUs "
                f"{devices}; it is off on this machine")
            entries[largest] = {"mode": "off"}



def _answers(port: int) -> bool:
    """Whether something accepts connections on 127.0.0.1:`port`."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


