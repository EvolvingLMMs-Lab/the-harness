"""Discover package workspace providers and route ownership; no environment implementation."""
from pathlib import Path
import sys
from .workers import Cancelled


class WorkspaceProvider:
    """Package lifecycle contract. Binding data is opaque to the host.

    Implement kinds, kind, bench, tree, bind and acquire. Optional presentation and
    managed execution are capabilities of the provider, not inferred from kind names.
    """
    def accepts(self, binding):
        return not binding

    def bind(self, kind, directory, request, parent=None):
        if request:
            raise ValueError(f"unsupported binding for {kind}: {sorted(request)}")
        return {}, {}

    def options(self, kind=None):
        return {}

    def describe(self, kind):
        """How a kind is offered when a conversation chooses where to work: {"label",
        "about"}, and optionally "folder" (it is bound to a folder the user names),
        "views" (it has pictures the model may look at: a model that reads no images
        works there from text and structure only) and "physical" (it may use the user's
        real mouse and keyboard)."""
        return {"label": kind, "about": ""}

    def environment(self, kind):
        """An environment in this process for a kind that takes no worker, else None."""
        return None

    def require_choices(self, kind, runtime=None):
        """Check user decisions before starting a task; providers own their choices."""

    def builtin_skills(self, kind):
        return ()

    def extra_skills(self, kind):
        return ()

    def validate_managed(self, kind):
        raise ValueError(f"{kind} does not support managed execution")

    def python(self, kind, log=print):
        return self.pool.python(kind, log)

    def of(self, run):
        return self.pool.of(run)

    def release(self, run):
        self.pool.release(run)

    def record(self, directory, kind, trace):
        return None

    def windows(self):
        return None

    def screen(self, run=None):
        return None

    def status(self):
        return {"status": self.pool.status(), "workspaces": self.pool.describe(), "kinds": list(self.kinds())}

    def presentation(self):
        return {}

    def restart(self):
        return self.pool.stop_free()

    def close(self):
        self.pool.close()


# The order environments are offered in (kinds of other packages follow).
ORDER = ("none", "project", "browser", "apps", "desktop", "display")

# What every provider implements itself; WorkspaceProvider gives the rest.
REQUIRED = ("kinds", "kind", "bench", "tree", "acquire")
CONTRACT = REQUIRED + tuple(name for name, value in vars(WorkspaceProvider).items()
                            if callable(value) and not name.startswith("_"))


def incompatible(factory) -> str:
    """Why a package's Workspaces cannot serve this harness, '' when it can: a class that
    subclasses WorkspaceProvider and implements REQUIRED, or has every method of CONTRACT
    (a provider written before WorkspaceProvider lacks describe, accepts, bind...)."""
    if not isinstance(factory, type):
        return "its Workspaces is not a class"
    wanted = REQUIRED if issubclass(factory, WorkspaceProvider) else CONTRACT
    missing = [name for name in dict.fromkeys(wanted) if not callable(getattr(factory, name, None))]
    if not missing:
        return ""
    return (f"its workspace provider lacks {', '.join(missing[:3])}{', …' if len(missing) > 3 else ''} "
            "(made for another harness version)")


def skipped(package, problem: str) -> str:
    """The line that says a package's workspaces were left out, and how to get them."""
    version = getattr(package, "version", "")
    # All of them: a package that depends on it may be as old (browser on computer).
    fix = ": harness install --update" if "harness version" in problem else ""
    return f"{package.name} {version}".strip() + f" was skipped: {problem}{fix}"


def package_problems() -> dict:
    """{package: why its workspaces are left out} for the packages this process uses, without
    starting any provider: a host module that does not import (extensions.host_problems) or
    a Workspaces that does not fit (incompatible). harness doctor reports them."""
    from ..extensions import host_problems, hosts

    loaded = hosts()  # first: it finds the host modules that do not import
    found = dict(host_problems())
    for package, module in loaded:
        factory = getattr(module, "Workspaces", None)
        problem = incompatible(factory) if factory is not None else ""
        if problem:
            found[package.name] = skipped(package, problem)
    return found


class NoWorkspace(WorkspaceProvider):
    """The core's own kind, `none`: a conversation with the model and the connected tools
    only. Nothing is acquired: no worker, no screen, no folder (runtime/execution/noenv.py)."""

    KIND = "none"

    def kinds(self):
        return (self.KIND,)

    def accepts(self, binding):
        return False

    def kind(self, requested=None, text=None):
        return self.KIND

    def bench(self, kind):
        return self.KIND

    def describe(self, kind):
        return {"label": "No environment",
                "about": "conversation, the model and the connected tools only; nothing is started"}

    def tree(self, tree, kind):
        from ..paths import ROOT
        from ..runtime.execution.kernel import DEFAULT_BOOTSTRAP

        tree["bench"] = self.KIND
        agent = tree["overrides"]["agent"]
        agent["prompt"][self.KIND] = str(ROOT / "prompts" / "conversation")
        agent[self.KIND] = {"roles": ["main"], "runtime": {
            "contract": "native", "verifier": False, "max_history_turns": 10,
            "think_while_acting": "off", "bootstrap": DEFAULT_BOOTSTRAP}}
        return tree

    def builtin_skills(self, kind):
        return ("conversation",)

    def python(self, kind, log=print):
        import sys

        return sys.executable

    def environment(self, kind):
        from ..runtime.execution.noenv import NoEnvironment

        return NoEnvironment()

    def acquire(self, run, kind, **waiting):
        raise ValueError("a conversation without an environment takes no workspace")

    def of(self, run):
        return None

    def release(self, run):
        pass

    def status(self):
        return {"status": "ready", "workspaces": [], "kinds": list(self.kinds())}

    def restart(self):
        return 0

    def close(self):
        pass


class Workspaces:
    Cancelled = Cancelled

    def __init__(self, directory, settings):
        self.directory, self.settings = Path(directory), settings
        self._providers = {}
        self._none = NoWorkspace()
        # {package: why its workspaces are left out}: one package that does not fit this
        # harness (or fails to start) costs its own environments, not every conversation.
        self.problems = {}

    def providers(self):
        from ..extensions import host_problems, hosts
        for package, module in hosts():
            factory = getattr(module, "Workspaces", None)
            if factory is None or package.name in self._providers or package.name in self.problems:
                continue
            problem = incompatible(factory)
            if not problem:
                try:
                    self._providers[package.name] = factory(self.directory, self.settings)
                    continue
                except Exception as error:  # the package's own code: its environments only are lost
                    problem = f"its workspace provider did not start ({type(error).__name__}: {error})"
            self.problems[package.name] = skipped(package, problem)
            print(f"harness: {self.problems[package.name]}", file=sys.stderr, flush=True)
        for name, problem in host_problems().items():
            self.problems.setdefault(name, problem)
        return tuple(self._providers.values())

    def missing(self, kind) -> str:
        """The error for a kind no provider gives, with the packages that were left out."""
        text = f"no installed package provides workspace {kind!r}"
        return text + "".join(f"; {problem}" for problem in self.problems.values())

    def catalog(self):
        found = {}
        for provider in (*self.providers(), self._none):
            for kind in provider.kinds():
                if kind in found:
                    raise ValueError(f"multiple packages provide workspace {kind}")
                found[kind] = provider
        return found

    def kinds(self):
        return tuple(self.catalog())

    def kind(self, requested=None, text=None, binding=None):
        catalog = self.catalog()
        if requested not in (None, "auto"):
            if requested not in catalog:
                raise ValueError(self.missing(requested))
            return catalog[requested].kind(requested, text)
        matches = [p for p in self.providers() if p.accepts(binding or {})]
        if not matches and not binding and len(self.providers()) == 1:
            matches = list(self.providers())
        if len(matches) != 1:
            raise ValueError("select --workspace explicitly; install a package providing the requested environment")
        return matches[0].kind(None, text)

    def environments(self) -> list[dict]:
        """What a new conversation may choose to work in, in the order it is offered: no
        environment, then each kind the installed packages give, as its provider describes
        it ({"value", "label", "about"} and its "folder", "views" and "physical" flags)."""
        catalog = self.catalog()
        order = [kind for kind in ORDER if kind in catalog] + [kind for kind in catalog if kind not in ORDER]
        return [{"value": kind, **catalog[kind].describe(kind)} for kind in order]

    def provider(self, kind=None):
        kind = self.kind() if kind is None else kind
        catalog = self.catalog()
        if kind not in catalog:
            raise ValueError(self.missing(kind))
        return catalog[kind]

    def require_choices(self, kind, runtime=None):
        self.provider(kind).require_choices(kind, runtime)

    def bench(self, kind):
        return self.provider(kind).bench(kind)

    def tree(self, tree, kind):
        return self.provider(kind).tree(tree, kind)

    def options(self, kind=None):
        return self.provider(kind).options(kind)

    def bind(self, kind, directory, request, parent=None):
        return self.provider(kind).bind(kind, directory, request, parent)

    def acquire(self, run, kind, **waiting):
        return self.provider(kind).acquire(run, kind, **waiting)

    def environment(self, kind):
        return self.provider(kind).environment(kind)

    def of(self, run):
        return next((worker for p in self.providers() if (worker := p.of(run)) is not None), None)

    def release(self, run):
        for provider in self.providers():
            if provider.of(run) is not None:
                provider.release(run)
                return

    def record(self, directory, kind, trace):
        return self.provider(kind).record(directory, kind, trace)

    def windows(self):
        return next((value for p in self.providers() if (value := p.windows()) is not None), None)

    def screen(self, run=None):
        if run is not None:
            return next((p.screen(run) for p in self.providers() if p.of(run) is not None), None)
        return self.provider().screen(None)

    def status(self):
        return {"providers": [p.status() for p in self.providers()], "kinds": list(self.kinds())}

    def presentation(self):
        return {key: value for p in self.providers() for key, value in p.presentation().items()}

    def restart(self):
        return sum(p.restart() for p in self.providers())

    def close(self):
        for provider in self._providers.values():
            provider.close()
