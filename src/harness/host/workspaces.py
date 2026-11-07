"""Discover package workspace providers and route ownership; no environment implementation."""
from pathlib import Path
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


class Workspaces:
    Cancelled = Cancelled

    def __init__(self, directory, settings):
        self.directory, self.settings = Path(directory), settings
        self._providers = {}

    def providers(self):
        from ..extensions import hosts
        for package, module in hosts():
            factory = getattr(module, "Workspaces", None)
            if factory is not None and package.name not in self._providers:
                self._providers[package.name] = factory(self.directory, self.settings)
        return tuple(self._providers.values())

    def catalog(self):
        found = {}
        for provider in self.providers():
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
                raise ValueError(f"no installed package provides workspace {requested!r}")
            return catalog[requested].kind(requested, text)
        matches = [p for p in self.providers() if p.accepts(binding or {})]
        if not matches and not binding and len(self.providers()) == 1:
            matches = list(self.providers())
        if len(matches) != 1:
            raise ValueError("select --workspace explicitly; install a package providing the requested environment")
        return matches[0].kind(None, text)

    def provider(self, kind=None):
        kind = self.kind() if kind is None else kind
        catalog = self.catalog()
        if kind not in catalog:
            raise ValueError(f"no installed package provides workspace {kind!r}")
        return catalog[kind]

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
