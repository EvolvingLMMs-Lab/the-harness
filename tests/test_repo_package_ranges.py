"""The repo's own packages install together: every package's `depends` is satisfied by the
version of that package in the repo (installers bundle them side by side)."""
from pathlib import Path
import tomllib
from unittest import TestCase

import helpers  # noqa: F401  (source paths)

from harness.packages.versions import satisfies

PACKAGES = Path(__file__).resolve().parents[1] / "packages"


class RepoRangeTests(TestCase):
    def test_every_depends_is_satisfied_by_the_repos_versions(self):
        manifests = {path.parent.name: tomllib.loads(path.read_text(encoding="utf-8"))
                     for path in PACKAGES.glob("*/package.toml")}
        versions = {(m.get("package") or {}).get("name", name): (m.get("package") or {}).get("version")
                    for name, m in manifests.items()}
        problems = []
        for name, manifest in manifests.items():
            for needed, wanted in ((manifest.get("package") or {}).get("depends") or {}).items():
                if needed not in versions:
                    continue  # a package from the registry, not in this repo
                if not satisfies(versions[needed], wanted):
                    problems.append(f"{name} needs {needed} {wanted}, the repo has {versions[needed]}")
        self.assertEqual(problems, [])
