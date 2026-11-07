"""Where the services an agent names run: what the package that places services gives
(the local-models package's deploy: a deploy file, or the harness's own placement on this
machine's GPUs). Without one, no service is placed here: an agent's roles use hosted
models, and a role or service that needs a placed service is left out (or, strict, an
error). config/agent.py resolves agents against it. Standard library only."""

from dataclasses import dataclass


@dataclass
class Unplaced:
    """How a service runs where nothing places it: off."""

    name: str
    mode: str = "off"
    gpu: int | None = None
    python: str | None = None


@dataclass
class NoDeploy:
    """No package places services here: every service is off."""

    name: str = "none"
    path: object = None
    environments: str = "own"
    gpus: object = None

    @property
    def automatic(self) -> bool:
        return True

    @property
    def services(self) -> dict:
        from .registry import load_services

        return load_services()

    @property
    def placements(self) -> dict:
        return {}

    def placement(self, name: str) -> Unplaced:
        if name not in self.services:
            raise ValueError(f"Unknown service {name!r}; known: {sorted(self.services)}")
        return Unplaced(name)

    def variables(self) -> dict:
        return {}


def _deploys():
    from ..extensions import first

    return first("deploys")


def load_deploy(name=None, **options):
    """The deploy `name` (a name of configs/deploy/, a path, None for $HARNESS_DEPLOY) as
    the package that places services loads it; NoDeploy without one."""
    deploys = _deploys()
    if deploys is None:
        if name:
            raise ValueError(f"deploy {name}: placing services needs the local-models package "
                             "(harness install local-models)")
        return NoDeploy()
    return deploys.load_deploy(name, **options)


def automatic(names, **options):
    """The harness's own placement of `names` on this machine (NoDeploy without a package
    that places services)."""
    deploys = _deploys()
    return NoDeploy() if deploys is None else deploys.automatic(names, **options)


def client_config(deploy, name: str) -> dict | None:
    """What a client of service `name` gets on `deploy` (its url and what the model is told),
    None when it does not run there."""
    if isinstance(deploy, NoDeploy):
        return None
    return _deploys().client_config(deploy, name)
