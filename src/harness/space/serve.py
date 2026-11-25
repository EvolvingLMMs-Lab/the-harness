"""Serve a space a package provides: `python -m harness.space.serve NAME [ARGUMENTS]`.

A package declares a space it serves in `spaces/<NAME>.toml`: `line` (what it is) and `entry`
("module:function", called with the remaining arguments). The function runs the space (on the
Agent Space Protocol SDK's space skeleton) until it closes; the address it prints is where a
conversation enters it (`--workspace space --space ADDRESS`).
"""

import importlib
import sys
import tomllib


def provided() -> dict:
    """{name: (package, declaration)} of the spaces the enabled packages serve."""
    from harness.paths import packages

    found = {}
    for package in packages():   # a checkout's packages and the installed, enabled ones
        for name in package.provides.get("spaces", ()):
            path = package.path / "spaces" / f"{name}.toml"
            with path.open("rb") as handle:
                found[name] = (package, tomllib.load(handle))
    return found


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from harness.packages import activate

    activate()
    spaces = {name: d for name, (_, d) in provided().items() if d.get("entry")}
    if not argv or argv[0] in ("-h", "--help"):
        print("python -m harness.space.serve NAME [ARGUMENTS]: the spaces installed packages serve:")
        for name, declaration in sorted(spaces.items()):
            print(f"  {name:<12} {declaration.get('line', '')}")
        return 0 if argv else 2
    name, rest = argv[0], argv[1:]
    if name not in spaces:
        print(f"no installed package serves a space {name!r}; there are {', '.join(sorted(spaces)) or 'none'}",
              file=sys.stderr)
        return 2
    module, function = spaces[name]["entry"].split(":", 1)
    return int(getattr(importlib.import_module(module), function)(rest) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
