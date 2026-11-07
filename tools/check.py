"""Check packages: each loads (package.toml, what it provides), and its Python imports
only `harness.sdk`, the standard library, its own modules, the packages it depends on,
and third-party modules (which run in the environments of its services and benches).

    python tools/check.py                 every package under packages/
    python tools/check.py workspace       one package (a name, or a folder)

An import of any other part of the harness, or of a module another package provides
without declaring it in `depends`, is an error with its file and line. Exit status 0
when every package checks, 1 otherwise.
"""

import argparse
import ast
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PACKAGES = HERE.parent / "packages"
# The core's own content (its built-in skills).
BUILTIN = HERE.parent / "src" / "harness" / "builtin"
# Folders of a package whose Python is imported under the folder's name (skills.<x>).
NAMESPACES = ("skills", "benches", "embodiments", "services", "prompts", "profiles", "experiments")


def modules_of(folder: Path) -> set[str]:
    """The top-level-qualified modules a package folder provides: skills.grab,
    benches.minecraft, and any top-level Python package of its own."""
    out = set()
    for namespace in NAMESPACES:
        for path in sorted((folder / namespace).glob("*")):
            # A folder of modules is a package with or without __init__.py (a namespace).
            if (path.is_dir() and any(path.glob("*.py"))) or path.suffix == ".py":
                out.add(f"{namespace}.{path.stem}")
    for path in sorted(folder.glob("*")):
        if path.is_dir() and (path / "__init__.py").is_file() and path.name not in NAMESPACES:
            out.add(path.name)
    return out


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module
            # from harness import sdk -> harness.sdk
            if node.module == "harness":
                for alias in node.names:
                    yield node.lineno, f"harness.{alias.name}"


def _owner(module: str, provided: dict[str, set[str]]) -> str | None:
    for package, modules in provided.items():
        if any(module == own or module.startswith(own + ".") for own in modules):
            return package
    return None


def check(folder: Path, everything: dict[str, Path]) -> list[str]:
    """The problems of one package folder ([] when it checks)."""
    from harness.packages.manifest import load

    try:
        package = load(folder)
    except ValueError as error:
        return [str(error)]
    problems = []
    if package.name != folder.name:
        problems.append(f"{folder}: its folder is not named after the package ({package.name})")
    provided = {name: modules_of(path) for name, path in everything.items()}
    own = provided.get(package.name, modules_of(folder))
    # The core's built-in skills are part of the harness every package runs in.
    core = {module for module in modules_of(BUILTIN) if module.startswith("skills.")}
    allowed = {package.name} | set(package.depends)
    stdlib = set(sys.stdlib_module_names)
    for path in sorted(folder.rglob("*.py")):
        if any(part in ("__pycache__", ".deps") for part in path.parts):
            continue
        try:
            imports = list(_imports(path))
        except SyntaxError as error:
            problems.append(f"{path.relative_to(folder.parent)}:{error.lineno}: {error.msg}")
            continue
        for line, module in imports:
            top = module.split(".")[0]
            where = f"{path.relative_to(folder.parent).as_posix()}:{line}"
            if top == "harness":
                if module == "harness" or module == "harness.sdk" or module.startswith("harness.sdk."):
                    continue
                problems.append(f"{where}: imports {module}; a package imports the harness only through harness.sdk")
                continue
            if top in stdlib or any(module == mine or module.startswith(mine + ".") for mine in own | core):
                continue
            owner = _owner(module, provided)
            if owner is not None and owner not in allowed:
                problems.append(f"{where}: imports {module} of the package {owner}, which {package.name} does not "
                                f"depend on (add it to depends)")
            elif owner is None and top in NAMESPACES:
                problems.append(f"{where}: imports {module}, which no package here provides")
    for name in package.depends:
        if everything and name not in everything:
            problems.append(f"{folder.name}: depends on {name}, which is not a package here")
    return problems


def packages_in(root: Path) -> dict[str, Path]:
    return {path.parent.name: path.parent for path in sorted(Path(root).glob("*/package.toml"))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", help="packages (names under packages/, or folders); default all")
    parser.add_argument("--root", type=Path, default=PACKAGES, help="the folder of the packages (default packages/)")
    args = parser.parse_args(argv)
    everything = packages_in(args.root)
    chosen = [Path(name) if Path(name).is_dir() and not (args.root / name).is_dir() else args.root / name
              for name in args.names] or list(everything.values())
    failed = 0
    for folder in chosen:
        problems = check(folder, everything)
        print(f"{folder.name}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        for problem in problems:
            print(f"  {problem}")
        failed += bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
