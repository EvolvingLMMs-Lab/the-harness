"""Embodiments: what an agent acts through, independent of how a run reaches it.

embodiments/<name>/embodiment.toml holds the facts a policy may know about the
embodiment without asking its worker. Its `kind` (KINDS) decides the session that drives
it (runtime/execution/session.py), the skills that run on it (a skill's `embodiments`)
and the keys it must have. An embodiment file and a worker's profile name their kind.

KINDS is everything the core knows that differs between kinds. The core has one kind of
its own, a conversation with no environment ("none"). Every other kind is a package's:
one table in its kinds.toml, with its session class, its skills (a skill's
`embodiments`), its prompt, the agent's settings on it and a bench
(benches/<name>/bench.toml `kind`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
import tomllib

from .paths import ROOT


EMBODIMENTS_ROOT = ROOT / "embodiments"


@dataclass(frozen=True)
class Kind:
    """An embodiment kind. A worker reports its kind in its profile (`kind`)."""

    name: str
    # What it is, in the documentation ("a computer").
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
    # Its prompt pack (a directory; in kinds.toml a path from the package's folder), used
    # where the agent's configuration names none for the kind.
    prompt: str = ""
    # The agent's settings on this kind (config/agent.py KIND_KEYS: roles, skills, services,
    # runtime, budget, knowledge), under what the agent's own table for the kind says.
    agent: Mapping = field(default_factory=dict)
    # Locks and snapshots of an agent on this kind do not name the kind: for a kind whose
    # locks were made before kinds were recorded, so that they keep their hash.
    unnamed_in_lock: bool = False
    # Its library keeps the setting `experience` as it is (config/agent.py); for every other
    # kind that setting is read as `uses`.
    library_experience: bool = False
    # Recording a use of a library entry waits for the host's answer (builtin/skills/learning).
    record_waits: bool = True
    # After each program the model is given recent notes and the nearest places (builtin/skills/memory).
    memory_report: bool = True
    # Its own variant of a skill: {skill: {"summary", "mixin", "exports"}} in place of the
    # skill's (runtime/execution/skills.py Skill.for_embodiment).
    interfaces: Mapping = field(default_factory=dict)


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
    """The core's kind (none) and those packages register in their kinds.toml, one table
    per kind with the fields of Kind:

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
                                           prompt_features=tuple(row.get("prompt_features", ())),
                                           prompt=str((path.parent / row["prompt"]).resolve()) if row.get("prompt") else "",
                                           agent=dict(row.get("agent", {})),
                                           unnamed_in_lock=bool(row.get("unnamed_in_lock", False)),
                                           library_experience=bool(row.get("library_experience", False)),
                                           record_waits=bool(row.get("record_waits", True)),
                                           memory_report=bool(row.get("memory_report", True)),
                                           interfaces={skill: dict(variant)
                                                       for skill, variant in row.get("interfaces", {}).items()})
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

        [name]
        kind = "the kind it is for"
        filter = "package.module:Class"
        summary = "one line: what a policy is handed under it"

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
    """The kind of an embodiment tree or a worker profile, which names it; a missing or
    unknown kind is an error."""
    kind = data.get("kind")
    if kind is None:
        raise ValueError(f"No embodiment kind is named (`kind`); kinds are {sorted(KINDS)}")
    if kind not in KINDS:
        raise ValueError(f"Unknown embodiment kind {kind!r}; kinds are {sorted(KINDS)}")
    return kind


def load_embodiment(name) -> dict:
    """An embodiment's tree (a name or a path, see embodiment_path); it must have the keys
    of its kind (KINDS)."""
    with embodiment_path(name).open("rb") as handle:
        data = tomllib.load(handle)
    for key in KINDS[embodiment_kind(data)].file_keys:
        if key not in data:
            raise ValueError(f"Embodiment {name}: missing {key}")
    return data
