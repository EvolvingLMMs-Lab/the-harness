"""The first start since packages: the skills installed in the app become packages.

Before packages, the app kept the skills a user installed under <data>/addons/
(skills/ for Harness skills, agent-skills/ for Agent Skills). On the first start with
packages, each of them becomes a local package of its own name (source
"migrated:addons"), trusted, as the user installed it (a skill the user turned off in
Settings stays off). The folder stays where it was; nothing reads it any more. The
user's config.toml records that this was done (packages.addons_migrated).
"""

from pathlib import Path
import shutil
import tempfile

from ..core import tree_hash
from . import archive, state
from .addons import find_skills
from .manifest import load, write


ADDONS = "addons"


def migrate(packages, *, log=lambda message: None) -> list[str]:
    """Turn the app's installed skills into packages, once; returns their names."""
    addons = Path(packages.data) / ADDONS
    if not addons.is_dir():
        return []
    user = packages.user()
    if user.migrated:
        return []
    names = []
    for kind in ("skills", "agent-skills"):
        folder = addons / kind
        if not folder.is_dir():
            continue
        found, problems = find_skills(folder)
        for problem in problems:
            log(f"not migrated: {problem}")
        for skill in found:
            if skill["name"] in user.packages:
                continue
            with tempfile.TemporaryDirectory(prefix="harness-migrate-") as temporary:
                root = Path(temporary) / skill["name"]
                shutil.copytree(skill["folder"], root / kind / skill["name"],
                                ignore=shutil.ignore_patterns(".git", "__pycache__"))
                write(root, name=skill["name"], summary=skill["summary"])
                try:
                    package = load(root)
                except ValueError as error:
                    log(f"not migrated: {error}")
                    continue
                digest = tree_hash(root, archive.files(root))
                target = state.store_path(package.name, package.version, digest)
                if not (target / "package.toml").is_file():
                    # Its .deps (requirements installed for the kernel) come along.
                    shutil.copytree(root, target)
                    deps = skill["folder"] / ".deps"
                    if deps.is_dir():
                        shutil.copytree(deps, target / kind / skill["name"] / ".deps")
                    state.freeze(target)
            user.packages[package.name] = state.Record(package.name, package.version, digest,
                                                       "migrated:addons", path=str(target))
            names.append(package.name)
            log(f"{package.name}: the skill installed in the app is now a package")
    user.migrated = True
    user.write()
    return names
