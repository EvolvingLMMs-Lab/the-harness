"""Resolution: one version of each package for a run, or an error that says why not.

The requests (`harness install a b@^0.2`, a project's [packages]) and every chosen
version's `depends` are ranges a package must satisfy. A package keeps the version it
has when that satisfies them all; otherwise the registry's highest version that does
and works with this harness is taken. With a dozen packages a simple fixed point does;
a conflict names who needs what.
"""

from .manifest import platform
from .registry import RegistryError, harness_fits
from .versions import best, satisfies


class ResolveError(ValueError):
    pass


def resolve(requests: dict, registry, *, harness: str, have: dict | None = None, fixed: dict | None = None,
            depends_of=None, use_installed=None) -> dict:
    """{name: version} for `requests` ({name: range}) and their dependencies.

    `have`: {name: version} already installed (kept when they fit); `fixed`: {name:
    (version, depends)} of packages from other sources, which cannot change;
    `depends_of(name, version)`: the depends of an installed version (default: the
    registry's). Retained installed packages constrain active dependencies without
    adding unrelated dependency requests; a parent selected for replacement uses
    its selected manifest instead. `use_installed(name, version)` can decline an
    installed preference/active manifest without discarding retained parent metadata."""
    have, fixed = dict(have or {}), dict(fixed or {})
    needs: dict[str, dict[str, str]] = {}

    def need(name, wanted, by):
        needs.setdefault(name, {})[by] = wanted

    def depends(name, version, *, retained=False):
        if name in fixed:
            return fixed[name][1]
        if depends_of is not None and (retained or use_installed is None or use_installed(name, version)):
            found = depends_of(name, version)
            if found is not None or retained:
                return found
        return registry.entry(name, version).get("depends", {})

    retained = {}
    for name, version in have.items():
        if name in requests or name in fixed:
            continue
        try:
            wants = depends(name, version, retained=True)
            if wants is not None:
                retained[name] = (version, wants)
        except (RegistryError, ValueError):
            # An unavailable retained manifest is not an explicit install request.
            continue

    for name, wanted in requests.items():
        need(name, wanted, "you")
    chosen = {}
    for name, (version, wants) in fixed.items():
        chosen[name] = version
        for other, wanted in wants.items():
            need(other, wanted, f"{name} {version}")
    for _ in range(200):
        changed = False
        problems = []
        for name in sorted(needs.keys() | fixed.keys()):
            if not needs.get(name) and name not in fixed:
                continue
            constraints = dict(needs.get(name, {}))
            for parent, (version, wants) in retained.items():
                # An active parent contributes the selected version's edges below.
                # An inactive retained parent constrains only already active names.
                if not needs.get(parent) and name in wants:
                    constraints[f"{parent} {version}"] = wants[name]
            ranges = list(constraints.values())
            current = chosen.get(name)
            if current and all(satisfies(current, wanted) for wanted in ranges):
                continue
            if name in fixed:
                problems.append(ResolveError(_conflict(name, constraints,
                                                      f"{name} {current} (from its source) is not in range")))
                continue
            pick = (have.get(name) if have.get(name) and all(satisfies(have[name], r) for r in ranges)
                    and (use_installed is None or use_installed(name, have[name])) else None)
            if pick is None:
                try:
                    published = [version for version in registry.versions(name)
                                 if harness_fits(registry.entry(name, version), harness)
                                 and (not registry.entry(name, version).get("platforms")
                                      or platform() in registry.entry(name, version)["platforms"])]
                except RegistryError as error:
                    problems.append(ResolveError(f"{name}: {error}"))
                    continue
                if not published and name not in registry.packages():
                    problems.append(ResolveError(f"no package {name} in {registry.base}" + _who(constraints)))
                    continue
                pick = best(published, *ranges)
            if pick is None:
                problems.append(ResolveError(_conflict(name, constraints, f"published for harness {harness}: "
                                                      f"{', '.join(published) or 'none'}")))
                continue
            if current:
                for other in needs.values():
                    other.pop(f"{name} {current}", None)
            chosen[name] = pick
            for other, wanted in depends(name, pick).items():
                need(other, wanted, f"{name} {pick}")
            changed = True
        if not changed:
            # A later selection can activate/replace a retained parent, removing an
            # apparent conflict. Report it only after no selection can make progress.
            if problems:
                raise problems[0]
            return {name: chosen[name] for name in sorted(chosen) if needs.get(name) or name in fixed}
    raise ResolveError("the versions did not settle: " + ", ".join(f"{n} {v}" for n, v in sorted(chosen.items())))


def _who(needs: dict) -> str:
    asked = [by for by in needs if by != "you"]
    return f" (needed by {', '.join(asked)})" if asked else ""


def _conflict(name: str, needs: dict, detail: str) -> str:
    wants = "; ".join(f"{by} needs {name} {wanted or 'any'}" for by, wanted in sorted(needs.items()))
    return f"no version of {name} fits: {wants} ({detail})"
