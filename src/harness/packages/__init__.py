"""Packages: everything the harness can do beyond its core comes in a package, installed
from the registry at harness.lmms-lab.com (or another source) ahead of time or the first
time a run needs it.

    from harness import packages

    packages.install(["minecraft"])          # and what it depends on
    packages.installed()                      # [{name, version, source, provides, ...}]
    packages.search("robot"), packages.info("robodojo")
    packages.update(), packages.remove(["minecraft"])
    packages.ensure("embodiments", "minecraft")   # install on first use (packages.auto_install)
    packages.describe(packages.info("robodojo"))  # its fields and lines as every frontend shows them

The same as `harness install / remove / update / list / search / info`, the app's
Packages page. The modules:

    manifest.py     package.toml, and what a package provides by convention
    versions.py     versions and ranges
    sources.py      registry names, git, archive URLs, folders
    registry.py     the registry's index and files; publishing a version
    archive.py      deterministic package files, unpacked safely
    resolve.py      one version of each package, or why not
    state.py        the store, the user's list, a project's harness.toml and harness.lock
    manager.py      install, remove, update, trust, install on first use
    describe.py     a package as the frontends show it: its row of a list, its lines
    addons.py       the skills packages hold (Harness skills and Agent Skills)
    migrate.py      the app's installed skills becoming packages
    environments.py the environments services and benches run in
    provision.py    installing a run's services and benches (environments, weights, assets)
"""

from .describe import COLUMNS, describe, rows
from .manager import AUTO_INSTALL, MissingPackage, Packages, activate
from .manifest import PACKAGE_KEYS, PROVIDES, Package, load
from .registry import OFFICIAL, Registry, RegistryError
from .resolve import ResolveError


def install(specs=(), **options) -> dict:
    return Packages().install(specs, **options)


def remove(names, **options) -> list[str]:
    return Packages().remove(names, **options)


def update(names=(), **options) -> dict:
    return Packages().update(names, **options)


def installed() -> list[dict]:
    return Packages().installed()


def enabled() -> list[Package]:
    return Packages().enabled()


def search(query: str = "") -> list[dict]:
    return Packages().search(query)


def info(name: str) -> dict:
    return Packages().info(name)


def ensure(what: str, name: str, **options) -> Package:
    return Packages().ensure(what, name, **options)


__all__ = ["AUTO_INSTALL", "COLUMNS", "MissingPackage", "OFFICIAL", "PACKAGE_KEYS", "PROVIDES", "Package",
           "Packages", "Registry", "RegistryError", "ResolveError", "activate", "describe", "enabled", "ensure",
           "info", "install", "installed", "load", "remove", "rows", "search", "update"]
