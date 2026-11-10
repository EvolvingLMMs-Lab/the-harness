"""Embodiments: what a robot or a computer is, independent of how a run reaches it.

embodiments/<name>/embodiment.toml holds the facts a policy may know about the
embodiment without asking a simulator. Its `kind` (KINDS, default robot) decides the
session that drives it (runtime/execution/session.py), the skills that run on it (a skill's
`embodiments`) and the keys it must have.

A robot's file holds joint groups and limits, arm mounts, the fingertip offset, gripper
widths and readings, control rate, planner limits, camera calibration (head camera fixed
in the world, wrist cameras fixed on link6), the action keys of XPolicyLab's protocol,
and the shield's defaults. A simulator worker reports the same facts live in its
profile; the XPolicyLab connector and contract-restricted workers take them from here.
A computer's (desktop) file holds its screen and the rate of its input steps; a game's
the screen of its window, the keys its inputs can press and the rate of a still step.

KINDS is everything the core knows that differs between kinds; a new kind is one entry
here, its session class, its skills (a skill's `embodiments`), a prompt and a bench
(benches/<name>/bench.toml `kind`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import tomllib

from .paths import ROOT


EMBODIMENTS_ROOT = ROOT / "embodiments"


@dataclass(frozen=True)
class Kind:
    """An embodiment kind. A worker reports its kind in its profile (`kind`, default robot)."""

    name: str
    # What it is, in the documentation ("a robot").
    what: str
    # The keys an embodiment file of the kind must have.
    file_keys: tuple[str, ...]
    # The kernel session that drives it, "module:Class" (runtime/execution/session.py).
    session: str
    # The observation contracts its workers can be served with: native, those it declares and those
    # packages register for it (contracts.toml, contract_filter).
    contracts: tuple[str, ...]
    # The success verifier's instructions (runtime/decision/messages.py).
    verifier: str
    # The label and keys of the state in every message to the model, and the image
    # streams it sees unless runtime.cameras names others.
    state_label: str
    state_keys: tuple[str, ...]
    cameras: tuple[str, ...]
    # Where its agents' sub-agents run when the session has no place of its own to give
    # ("module:Class", a runtime/task/delegation.py Place: a game's view of the agent's episode).
    place: str = ""
    knowledge: str | None = None
    native_features: tuple[str, ...] = ()
    prompt_features: tuple[str, ...] = ()


# The core's own kind: a conversation without an environment (runtime/execution/noenv.py).
_CORE_KINDS = {kind.name: kind for kind in (
    Kind(name="none", what="no environment", file_keys=("name",),
         session="harness.runtime.execution.noenv:NoSession", contracts=("native",),
         verifier="Check the claim against what the conversation itself established: the user's messages, the "
                  "files they attached and the results the connected tools returned. Answer on the first line "
                  "with exactly YES or NO, then one sentence of evidence.",
         state_label="State", state_keys=("step",), cameras=()),
)}


class _Kinds(Mapping):
    """The core's kinds (robot, desktop, game) and those packages register in their
    kinds.toml, one table per kind with the fields of Kind:

        [drone]
        what = "a drone"
        file_keys = ["name", "control_hz", "camera"]
        session = "skills.drone.session:DroneSession"
        contracts = ["native"]
        verifier = "You check a claim about a drone from its camera images. ..."
        state_label = "Drone state"
        state_keys = ["step", "altitude"]
        cameras = ["front"]

    A package's kind of a name the core has is left out."""

    def __init__(self, core):
        self._core = core
        self._cache = (None, core)

    def _kinds(self) -> dict:
        from .paths import find

        files = tuple(path for path in find("kinds.toml"))
        if files != self._cache[0]:
            kinds = dict(self._core)
            for path in files:
                with path.open("rb") as handle:
                    for name, row in tomllib.load(handle).items():
                        if name in kinds:
                            continue
                        kinds[name] = Kind(name=name, what=row["what"], file_keys=tuple(row["file_keys"]),
                                           session=row["session"], contracts=tuple(row.get("contracts", ("native",))),
                                           verifier=row["verifier"], state_label=row["state_label"],
                                           state_keys=tuple(row.get("state_keys", ())),
                                           cameras=tuple(row.get("cameras", ())), place=str(row.get("place", "")),
                                           knowledge=row.get("knowledge"),
                                           native_features=tuple(row.get("native_features", ())),
                                           prompt_features=tuple(row.get("prompt_features", ())))
            registered = contracts()
            for name, kind in list(kinds.items()):
                extra = tuple(contract for contract, row in registered.items()
                              if row["kind"] == name and contract not in kind.contracts)
                if extra:
                    kinds[name] = replace(kind, contracts=kind.contracts + extra)
            self._cache = (files, kinds)
        return self._cache[1]

    def __getitem__(self, name):
        return self._kinds()[name]

    def __iter__(self):
        return iter(self._kinds())

    def __len__(self):
        return len(self._kinds())


KINDS = _Kinds(_CORE_KINDS)


def contracts() -> dict:
    """{name: {"kind", "filter", "summary"}}: the observation contracts the packages register in
    their contracts.toml, one table per contract:

        [xpolicylab]
        kind = "robot"
        filter = "harness_robodojo.contract:XPolicyLabContract"
        summary = "what RoboDojo's official client hands a policy"

    A filter is a class taking the embodiment, whose apply(method, arguments, result) gives
    what a worker method returned as the contract shows it (core/worker.py)."""
    from .paths import find

    found = {}
    for path in find("contracts.toml"):
        with path.open("rb") as handle:
            for name, row in tomllib.load(handle).items():
                found.setdefault(name, {"kind": row["kind"], "filter": row["filter"], "summary": row.get("summary", "")})
    return found


def contract_filter(name: str, embodiment: dict):
    """The filter a worker of `embodiment` is served with under the contract `name`: None for
    native (everything is reported); a registered contract's filter otherwise."""
    import importlib

    kind = embodiment_kind(embodiment)
    allowed = KINDS[kind].contracts
    if name not in allowed:
        raise ValueError(f"A {kind} is served with the contracts {allowed}, not {name!r}")
    if name == "native":
        return None
    module, _, attribute = contracts()[name]["filter"].partition(":")
    return getattr(importlib.import_module(module), attribute)(embodiment)


def embodiment_path(name) -> Path:
    """The embodiment file of a name (`embodiments/<name>/embodiment.toml`) or a path; an
    unknown name is an error."""
    path = Path(name)
    # A file only: a directory named like an embodiment (a checkout called "gamescientist")
    # is not one.
    if path.suffix == ".toml" or path.is_file():
        return path.resolve()
    from .paths import find

    found = find(f"embodiments/{name}/embodiment.toml")
    if not found:
        known = sorted({p.parent.name for folder in find("embodiments") for p in folder.glob("*/embodiment.toml")})
        raise ValueError(f"Unknown embodiment {name!r}; known: {known}")
    return found[0]


def embodiment_kind(data: dict) -> str:
    """The kind of an embodiment tree or a worker profile (default robot); an unknown kind
    is an error."""
    kind = data.get("kind", "robot")
    if kind not in KINDS:
        raise ValueError(f"Unknown embodiment kind {kind!r}; kinds are {sorted(KINDS)}")
    return kind


def load_embodiment(name) -> dict:
    """An embodiment's tree (a name or a path, see embodiment_path); it must have the keys
    of its kind (KINDS): a robot's name, control_hz, groups, arm_bases and cameras."""
    with embodiment_path(name).open("rb") as handle:
        data = tomllib.load(handle)
    for key in KINDS[embodiment_kind(data)].file_keys:
        if key not in data:
            raise ValueError(f"Embodiment {name}: missing {key}")
    return data


def profile(embodiment: dict) -> dict:
    """The worker profile a robot embodiment implies (what a simulator worker reports
    live), for connections without a simulator."""
    if embodiment_kind(embodiment) != "robot":
        raise ValueError(f"Embodiment {embodiment['name']}: a worker profile is built here for robots only")
    groups = [{"name": name, "joints": list(group["joints"]), "gripper": group["gripper"]}
              for name, group in embodiment["groups"].items()]
    keys = ("control_hz", "physics_steps_per_tick", "action_low", "action_high", "cameras", "planner_limits",
            "tip_offset_m", "gripper_empty_opening", "gripper_open_width_m", "table_z", "return_to_start",
            "shield", "planner_world")
    return {"groups": groups, "arm_bases": {k: list(v) for k, v in embodiment["arm_bases"].items()},
            "embodiment": embodiment["name"], **{key: embodiment[key] for key in keys if key in embodiment}}
