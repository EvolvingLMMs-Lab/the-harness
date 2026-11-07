"""The code part of an agent's lock (`harness lock`): a fingerprint of every source file
that decides what a run computes, of the core and of the packages it runs with.
"""

import hashlib

from harness.sdk import PACKAGE, ROOT, sha256


# Files whose content decides what a run computes (the code part of the lock).
CODE_ROOTS = ("src/harness", "skills", "benches", "prompts", "services")
# Where each of them is: under ROOT (harness/builtin/), but src/harness is the package
# itself, without its builtin/ (named src/harness/... in a checkout and installed alike).
_CODE_DIRS = {"src/harness": PACKAGE}


def code_fingerprint(roots=CODE_ROOTS) -> dict:
    """sha256 of every source file of the agent (Python, prompts, manifests), of the core
    and of each package it runs with (packages/<name>/...), and of them all."""
    from harness.sdk import packages

    directories = [(root, _CODE_DIRS.get(root, ROOT / root)) for root in roots]
    directories += [(f"packages/{package.name}", package.path) for package in packages()]
    files = {}
    for root, directory in directories:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if path.is_file() and path.suffix in (".py", ".md", ".toml", ".json", ".yml", ".yaml") \
                    and "__pycache__" not in relative.parts \
                    and not (root == "src/harness" and relative.parts[:1] == ("builtin",)) \
                    and relative.parts[:1] != ("tests",):
                files[f"{root}/{relative.as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"sha256": sha256(files), "files": len(files)}
