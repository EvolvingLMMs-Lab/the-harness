"""Installing over a data folder that already holds packages from an older harness: a stale
package whose bench or service manifest no longer checks is left out and listed with its
problem; it never stops installing, updating or using the others, nor the host."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase

import helpers  # noqa: F401  (source paths)

ROOT = Path(__file__).resolve().parents[1]


def stale_package(folder: Path) -> Path:
    """A package an older harness installed: its bench has a kind this one does not know,
    its service manifest a kind it does not know either."""
    package = folder / "oldtools"
    (package / "benches" / "oldbench").mkdir(parents=True)
    (package / "services").mkdir()
    (package / "package.toml").write_text('[package]\nname = "oldtools"\nversion = "0.5.1"\nsummary = "old"\n'
                                          'harness = ">=0.1"\n', encoding="utf-8")
    (package / "benches" / "oldbench" / "bench.toml").write_text(
        'name = "oldbench"\nsummary = "old"\nkind = "kind-of-an-older-harness"\nfactory = "x:y"\n', encoding="utf-8")
    (package / "services" / "oldservice.toml").write_text('name = "oldservice"\nkind = "gone"\n', encoding="utf-8")
    return package


class StalePackageTests(TestCase):
    def run_harness(self, *words, home):
        env = {**os.environ, "HARNESS_HOME": str(home), "HARNESS_DATA": str(home),
               "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), *os.environ.get("PYTHONPATH", "").split(os.pathsep)])}
        env.pop("HARNESS_PACKAGE_ROOTS", None)
        return subprocess.run([sys.executable, "-m", "harness", *words], capture_output=True, text=True, env=env,
                              cwd=str(home), timeout=600, encoding="utf-8", errors="replace")

    def test_a_stale_package_does_not_block_installing_another_or_listing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            root = Path(root)
            home = root / "home"
            home.mkdir()
            old = self.run_harness("install", str(stale_package(root)), "--yes", home=home)
            self.assertEqual(old.returncode, 0, old.stdout + old.stderr)
            fresh = self.run_harness("install", str(ROOT / "packages" / "agent"), "--yes", home=home)
            self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr)
            listed = self.run_harness("list", home=home)  # (exits 1: a package has a problem)
            self.assertIn("oldtools", listed.stdout)
            self.assertIn("kind must be one of", listed.stdout + listed.stderr)

    def test_the_whole_set_loaders_leave_the_stale_part_out(self):
        from harness import bench, paths
        from harness.services import registry

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            package = stale_package(Path(root))
            original = paths.find

            def find(name):
                return [*original(name), *([package / name] if (package / name).is_dir() else [])]

            paths.find = find
            registry._CACHE.clear()
            try:
                self.assertNotIn("oldbench", bench.bench_specs())
                self.assertNotIn("oldservice", registry.load_services())
                problems = paths.content_problems(package)
                self.assertEqual(len(problems), 2)
            finally:
                paths.find = original
                registry._CACHE.clear()
