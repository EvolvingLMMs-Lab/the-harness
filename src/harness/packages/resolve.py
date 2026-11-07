"""Resolution: one version of each package for a run, or an error that says why not.

The requests (`harness install a b@^0.2`, a project's [packages]) and every chosen
version's `depends` are ranges a package must satisfy. A package keeps the version it
has when that satisfies them all; otherwise the registry's highest version that does
and works with this harness is taken. With a dozen packages a simple fixed point does;
a conflict names who needs what.
"""

from .registry import RegistryError, harness_fits
from .versions import best, satisfies


class ResolveError(ValueError):
    pass


def resolve(requests: dict, registry, *, harness: str, have: dict | None = None, fixed: dict | None = None,
            depends_of=None) -> dict:
    """{name: version} for `requests` ({name: range}) and their dependencies.

    `have`: {name: version} already installed (kept when they fit); `fixed`: {name:
    (version, depends)} of packages from other sources, which cannot change;
    `depends_of(name, version)`: the depends of an installed version (default: the
    registry's)."""
    have, fixed = dict(have or {}), dict(fixed or {})
    needs: dict[str, dict[str, str]] = {}

    def need(name, wanted, by):
        needs.setdefault(name, {})[by] = wanted

    def depends(name, version):
        if name in fixed:
            return fixed[name][1]
        if depends_of is not None:
            found = depends_of(name, version)
            if found is not None:
                return found
        return registry.entry(name, version).get("depends", {})

    for name, wanted in requests.items():
        need(name, wanted, "you")
    chosen = {}
    for name, (version, wants) in fixed.items():
        chosen[name] = version
        for other, wanted in wants.items():
            need(other, wanted, f"{name} {version}")
    for _ in range(200):
        changed = False
        for name in sorted(needs):
            ranges = list(needs[name].values())
            current = chosen.get(name)
            if current and all(satisfies(current, wanted) for wanted in ranges):
                continue
            if name in fixed:
                raise ResolveError(_conflict(name, needs[name], f"{name} {current} (from its source) is not in range"))
            pick = have.get(name) if have.get(name) and all(satisfies(have[name], r) for r in ranges) else None
            if pick is None:
                try:
                    published = [version for version in registry.versions(name)
                                 if harness_fits(registry.entry(name, version), harness)]
                except RegistryError as error:
                    raise ResolveError(f"{name}: {error}") from None
                if not published and name not in registry.packages():
                    raise ResolveError(f"no package {name} in {registry.base}" + _who(needs[name]))
                pick = best(published, *ranges)
            if pick is None:
                raise ResolveError(_conflict(name, needs[name], f"published for harness {harness}: "
                                             f"{', '.join(published) or 'none'}"))
            if current:
                for other in needs.values():
                    other.pop(f"{name} {current}", None)
            chosen[name] = pick
            for other, wanted in depends(name, pick).items():
                need(other, wanted, f"{name} {pick}")
            changed = True
        if not changed:
            return {name: chosen[name] for name in sorted(chosen) if name in needs or name in fixed}
    raise ResolveError("the versions did not settle: " + ", ".join(f"{n} {v}" for n, v in sorted(chosen.items())))


def _who(needs: dict) -> str:
    asked = [by for by in needs if by != "you"]
    return f" (needed by {', '.join(asked)})" if asked else ""


def _conflict(name: str, needs: dict, detail: str) -> str:
    wants = "; ".join(f"{by} needs {name} {wanted or 'any'}" for by, wanted in sorted(needs.items()))
    return f"no version of {name} fits: {wants} ({detail})"
