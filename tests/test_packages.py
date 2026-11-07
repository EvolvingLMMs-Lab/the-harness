"""Packages (harness.packages): package.toml and what a package provides, versions and
ranges, deterministic package files, sources, a registry directory, resolution, the
store, the user's list, a project's harness.toml and harness.lock, trust, install on
first use, and the commands. Everything runs offline against registry directories."""

import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from harness import __version__  # noqa: E402
from harness.packages import archive, manifest, sources, versions  # noqa: E402
from harness.packages.manager import MissingPackage, Packages, activate  # noqa: E402
from harness.packages.registry import Registry, RegistryError, check_index, publish  # noqa: E402
from harness.packages.resolve import ResolveError, resolve  # noqa: E402
from harness.core import tree_hash  # noqa: E402
from harness.packages.state import Project, set_table  # noqa: E402


def make_package(root, name, version="0.1.0", *, depends=None, harness="", skills=(), embodiments=(),
                 benches=(), services=(), agent_skills=(), extra="", summary=None) -> Path:
    """A package folder under root/name-version with the resources named."""
    folder = Path(root) / f"{name}-{version}" / name
    folder.mkdir(parents=True)
    lines = ["[package]", f'name = "{name}"', f'version = "{version}"', f'summary = "{summary or name + " things"}"']
    if harness:
        lines.append(f'harness = "{harness}"')
    if depends:
        lines.append("depends = { " + ", ".join(f'{k} = "{v}"' for k, v in depends.items()) + " }")
    (folder / "package.toml").write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
    for skill in skills:
        (folder / "skills" / skill).mkdir(parents=True)
        (folder / "skills" / skill / "skill.toml").write_text(
            f'name = "{skill}"\nsummary = "{skill} calls"\nmixin = "skills.{skill}:Mixin"\nexports = ["{skill}_call"]\n'
            'optional = true\nembodiments = ["desktop"]\n', encoding="utf-8")
        (folder / "skills" / skill / "__init__.py").write_text(
            f"class Mixin:\n    def {skill}_call(self):\n        return '{skill}'\n", encoding="utf-8")
    for embodiment in embodiments:
        (folder / "embodiments" / embodiment).mkdir(parents=True)
        (folder / "embodiments" / embodiment / "embodiment.toml").write_text(
            f'name = "{embodiment}"\nkind = "desktop"\ncontrol_hz = 2\nscreen = [800, 600]\n', encoding="utf-8")
    for bench in benches:
        (folder / "benches" / bench).mkdir(parents=True)
        (folder / "benches" / bench / "bench.toml").write_text(f'name = "{bench}"\n', encoding="utf-8")
    for service in services:
        (folder / "services").mkdir(exist_ok=True)
        (folder / "services" / f"{service}.toml").write_text(
            f'kind = "mcp"\nsummary = "{service} tools"\nprotocol = "mcp"\n'
            f'command = ["{{python}}", "-u", "services/servers/serve_{service}.py", "--port", "{{port}}"]\n'
            f'port = 8861\nvram_gb = 0.0\nload_seconds = 5\n'
            f'client = {{ url = "{{url}}/mcp", description = "{service} tools" }}\n'
            f'[environment]\npython = "3.11"\nrequirements = ["torch==2.7.0"]\n', encoding="utf-8")
    for skill in agent_skills:
        (folder / "agent-skills" / skill).mkdir(parents=True)
        (folder / "agent-skills" / skill / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: How to {skill}.\n---\nSteps.\n", encoding="utf-8")
    (folder / "README.md").write_text(f"# {name}\n\nIt does {name} things.\n", encoding="utf-8")
    (folder / "CHANGELOG.md").write_text(f"## {version}\n\n- First.\n", encoding="utf-8")
    return folder


class Temporary(unittest.TestCase):
    """A HARNESS_HOME, a data directory, a working directory and a registry of their own."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.registry_dir = self.root / "registry"
        self.registry_dir.mkdir()
        self.data = self.root / "data"
        self.work = self.root / "work"
        self.work.mkdir()
        patcher = mock.patch.dict(os.environ, {"HARNESS_HOME": str(self.root / "home"),
                                               "HARNESS_DATA": str(self.data),
                                               "HARNESS_REGISTRY": str(self.registry_dir)})
        patcher.start()
        os.environ.pop("HARNESS_AUTO_INSTALL", None)
        self.roots = os.environ.get("HARNESS_PACKAGE_ROOTS")
        self.addCleanup(patcher.stop)
        self.addCleanup(self._restore)
        self.addCleanup(_rmtree, self.root)
        self.quiet = lambda message: None

    def _restore(self):
        if self.roots is None:
            os.environ.pop("HARNESS_PACKAGE_ROOTS", None)
        else:
            os.environ["HARNESS_PACKAGE_ROOTS"] = self.roots
        from harness.runtime.execution import skills

        skills._CACHE.clear()

    def publish(self, *args, **options) -> Path:
        folder = make_package(self.root / "sources", *args, **options)
        publish(self.registry_dir, folder, log=self.quiet)
        return folder

    def packages(self, **options) -> Packages:
        return Packages(self.data, cwd=options.pop("cwd", self.work), **options)


def _rmtree(path):
    def writable(function, target, _):
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        function(target)

    shutil.rmtree(path, **({"onexc": writable} if sys.version_info >= (3, 12) else {"onerror": writable}))


class VersionTests(unittest.TestCase):
    def test_versions_order_and_ranges(self):
        parse = versions.Version.parse
        self.assertLess(parse("0.9.9"), parse("0.10.0"))
        self.assertLess(parse("1.0.0-rc.2"), parse("1.0.0-rc.10"))
        self.assertLess(parse("1.0.0-rc.10"), parse("1.0.0"))
        self.assertEqual(str(parse("0.57")), "0.57.0")
        self.assertTrue(versions.satisfies("1.4.2", "^1.2"))
        self.assertFalse(versions.satisfies("2.0.0", "^1.2"))
        self.assertTrue(versions.satisfies("0.3.9", "^0.3"))
        self.assertFalse(versions.satisfies("0.4.0", "^0.3"))
        self.assertTrue(versions.satisfies("1.2.9", "~1.2"))
        self.assertFalse(versions.satisfies("1.3.0", "~1.2"))
        self.assertTrue(versions.satisfies("0.57.0", ">=0.57,<2"))
        self.assertFalse(versions.satisfies("2.0.0", ">=0.57,<2"))
        self.assertTrue(versions.satisfies("1.2.3", "1.2.3"))
        self.assertFalse(versions.satisfies("1.2.3", "!=1.2.3"))
        self.assertTrue(versions.satisfies("9.9.9", "*"))
        # A pre-release only when the range names one.
        self.assertFalse(versions.satisfies("1.0.0-rc.1", ">=0.9"))
        self.assertTrue(versions.satisfies("1.0.0-rc.1", ">=1.0.0-rc.0"))
        self.assertEqual(versions.best(["0.1.0", "0.2.0", "0.3.0-rc.1", "1.0.0"], "^0.1", "<0.3"), "0.1.0")
        self.assertEqual(versions.best(["0.2.0", "1.0.0"], "^0.1"), None)
        self.assertEqual(versions.best(["0.1.0", "0.1.5", "0.2.0", "0.3.0-rc.1"]), "0.2.0")
        self.assertEqual(versions.best(["0.1.0", "0.1.5", "0.2.0"], "~0.1"), "0.1.5")
        self.assertEqual(versions.latest(["0.1.0", "1.0.0-rc.1"]), "0.1.0")
        for bad in ("one", ">=x", "1..2"):
            with self.assertRaises(ValueError):
                versions.check_range(bad)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_what_a_package_provides_is_found_by_convention(self):
        folder = make_package(self.root, "kit", skills=["grab"], embodiments=["arm"], benches=["stack"],
                              services=["seg"], agent_skills=["plan-trip"],
                              extra='[provides]\nskills = ["grab"]\ncommands = { kit-check = "skills.grab:check" }\n')
        (folder / "configs" / "profiles").mkdir(parents=True)
        (folder / "configs" / "profiles" / "kit-default.toml").write_text("[agent]\n")
        (folder / "configs" / "experiments").mkdir()
        (folder / "configs" / "experiments" / "kit-dev.toml").write_text("bench = \"stack\"\n")
        (folder / "prompts").mkdir()
        (folder / "prompts" / "kit.md").write_text("Use the kit.\n")
        (folder / "kinds.toml").write_text('[arm]\nwhat = "an arm"\n')
        (folder / "settings.toml").write_text('[kit]\nspeed = 1\n')
        (folder / "config_keys.toml").write_text('"runtime.kit" = "what the kit does"\n')
        package = manifest.load(folder)
        self.assertEqual((package.name, package.version, package.summary), ("kit", "0.1.0", "kit things"))
        self.assertEqual(package.provides, {
            "kinds": ("arm",), "embodiments": ("arm",), "skills": ("grab",), "benches": ("stack",),
            "services": ("seg",), "prompts": ("kit",), "profiles": ("kit-default",), "experiments": ("kit-dev",),
            "agent_skills": ("plan-trip",), "settings": ("kit",), "config_keys": ("runtime.kit",),
            "commands": ("kit-check",)})
        self.assertEqual(package.commands, {"kit-check": "skills.grab:check"})
        self.assertEqual(package.folder("agent_skills"), folder.resolve() / "agent-skills")
        self.assertEqual(package.index_entry()["provides"]["skills"], ["grab"])

    def test_what_is_refused(self):
        def broken(text, name="bad"):
            folder = self.root / f"{name}-{len(list(self.root.iterdir()))}"
            folder.mkdir()
            (folder / "package.toml").write_text(text)
            with self.assertRaises(ValueError) as raised:
                manifest.load(folder)
            return str(raised.exception)

        self.assertIn("no package.toml", self._missing())
        self.assertIn("unknown [package] keys", broken('[package]\nname = "a"\nversion = "1.0.0"\nauthor = "x"\n'))
        self.assertIn("not lowercase", broken('[package]\nname = "Big"\nversion = "1.0.0"\n'))
        self.assertIn("no version", broken('[package]\nname = "a"\n'))
        self.assertIn("is not a version", broken('[package]\nname = "a"\nversion = "1.0.0"\nharness = "soon"\n'))
        self.assertIn("platforms", broken('[package]\nname = "a"\nversion = "1.0.0"\nplatforms = ["amiga"]\n'))
        self.assertIn("depends names", broken('[package]\nname = "a"\nversion = "1.0.0"\ndepends = { a = "*" }\n'))
        self.assertIn("does not have", broken('[package]\nname = "a"\nversion = "1.0.0"\n[provides]\nskills = ["x"]\n'))
        self.assertIn("module:function", broken('[package]\nname = "a"\nversion = "1.0.0"\n'
                                                '[provides]\ncommands = { go = "nowhere" }\n'))

    def _missing(self):
        with self.assertRaises(ValueError) as raised:
            manifest.load(self.root)
        return str(raised.exception)

    def test_a_written_package_toml_loads(self):
        folder = self.root / "w"
        folder.mkdir()
        manifest.write(folder, name="w", summary='Says "hi" — and more')
        self.assertEqual(manifest.load(folder).summary, 'Says "hi" — and more')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_the_same_folder_gives_the_same_bytes(self):
        folder = make_package(self.root, "same", skills=["a"])
        (folder / "skills" / "a" / "__pycache__").mkdir()
        (folder / "skills" / "a" / "__pycache__" / "x.pyc").write_bytes(b"cache")
        first = archive.build(folder, self.root / "one.tar.gz")
        os.utime(folder / "README.md", (1, 1))
        second = archive.build(folder, self.root / "two.tar.gz")
        self.assertEqual(first, second)
        self.assertEqual((self.root / "one.tar.gz").read_bytes(), (self.root / "two.tar.gz").read_bytes())
        with tarfile.open(self.root / "one.tar.gz") as tar:
            names = tar.getnames()
            self.assertTrue(all(member.mtime == 0 and member.uid == 0 for member in tar.getmembers()))
        self.assertIn("same/package.toml", names)
        self.assertFalse(any("__pycache__" in name for name in names))
        unpacked = archive.unpack(self.root / "one.tar.gz", self.root / "out")
        self.assertEqual(unpacked.name, "same")
        self.assertEqual(manifest.load(unpacked).name, "same")
        self.assertEqual(tree_hash(unpacked, archive.files(unpacked)), tree_hash(folder, archive.files(folder)))

    def test_paths_outside_and_links_are_refused(self):
        for name, kind in (("../escape.txt", tarfile.REGTYPE), ("/abs.txt", tarfile.REGTYPE),
                           ("link", tarfile.SYMTYPE)):
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind == tarfile.SYMTYPE:
                    info.linkname = "/etc/passwd"
                    tar.addfile(info)
                else:
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                archive.unpack(buffer.getvalue(), self.root / f"x{len(list(self.root.iterdir()))}")


class SourceTests(unittest.TestCase):
    def test_the_texts_a_source_can_be(self):
        self.assertEqual(sources.parse("minecraft"), sources.Source("registry", "minecraft", name="minecraft"))
        self.assertEqual(sources.parse("local-models@^0.2").range, "^0.2")
        git = sources.parse("git:github.com/x/y@v1#packages/z")
        self.assertEqual((git.kind, git.url, git.ref, git.subdir), ("git", "https://github.com/x/y", "v1", "packages/z"))
        plain = sources.parse("git+https://example.org/x/y.git")
        self.assertEqual((plain.url, plain.ref), ("https://example.org/x/y.git", ""))
        tree = sources.parse("https://github.com/anthropics/skills/tree/main/skills/pdf")
        self.assertEqual((tree.kind, tree.ref, tree.subdir), ("git", "main", "skills/pdf"))
        self.assertEqual(sources.parse("https://example.org/p-1.0.0.tar.gz").kind, "url")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(sources.parse(folder).kind, "path")
            # A bare name is the registry's even with a folder of that name here.
            cwd = os.getcwd()
            try:
                os.chdir(folder)
                Path("computer").mkdir()
                self.assertEqual(sources.parse("computer").kind, "registry")
                self.assertEqual(sources.parse("./computer").kind, "path")
            finally:
                os.chdir(cwd)
        for bad in ("", "https://example.org/page", "Not A Name", "./nowhere-at-all"):
            with self.assertRaises(ValueError):
                sources.parse(bad)


class RegistryTests(Temporary):
    def test_publish_index_and_download(self):
        self.publish("kit", skills=["grab"])
        self.publish("kit", "0.2.0", skills=["grab"], harness=">=99")
        index = json.loads((self.registry_dir / "index.json").read_text())
        check_index(index)
        entry = index["packages"]["kit"]
        self.assertEqual((entry["latest"], sorted(entry["versions"])), ("0.2.0", ["0.1.0", "0.2.0"]))
        row = entry["versions"]["0.1.0"]
        self.assertEqual(row["file"], "kit/0.1.0/kit-0.1.0.tar.gz")
        self.assertEqual(row["provides"], {"skills": ["grab"]})
        self.assertEqual(row["readme"], "kit/0.1.0/README.md")
        self.assertTrue((self.registry_dir / "kit" / "0.1.0" / "CHANGELOG.md").is_file())
        # A published version never changes.
        with self.assertRaisesRegex(RegistryError, "published already"):
            publish(self.registry_dir, make_package(self.root / "again", "kit", skills=["grab"]), log=self.quiet)
        registry = Registry(str(self.registry_dir))
        self.assertEqual(registry.versions("kit"), ["0.1.0", "0.2.0"])
        self.assertEqual(registry.providers("skills", "grab"), ["kit"])
        self.assertEqual([row["name"] for row in registry.search("grab")], ["kit"])
        self.assertEqual(registry.search("nothing-like-it"), [])
        folder, digest = registry.download("kit", "0.1.0", self.root / "dl", log=self.quiet)
        self.assertEqual((manifest.load(folder).version, digest), ("0.1.0", row["sha256"]))
        # A file that is not the index's is not unpacked.
        file = self.registry_dir / "kit" / "0.2.0" / "kit-0.2.0.tar.gz"
        file.write_bytes(file.read_bytes() + b"tampered")
        with self.assertRaisesRegex(RegistryError, "sha256"):
            registry.download("kit", "0.2.0", self.root / "dl2", log=self.quiet)

    def test_resolution_picks_one_version_each_or_says_why_not(self):
        self.publish("base", "0.1.0")
        self.publish("base", "0.2.0")
        self.publish("base", "0.3.0", harness=">=99")
        self.publish("game", "0.1.0", depends={"base": "^0.1"})
        self.publish("mc", "0.1.0", depends={"game": ">=0.1", "base": ">=0.1"})
        self.publish("new", "0.1.0", depends={"base": ">=0.2"})
        registry = Registry(str(self.registry_dir))
        self.assertEqual(resolve({"mc": ""}, registry, harness=__version__),
                         {"base": "0.1.0", "game": "0.1.0", "mc": "0.1.0"})
        # 0.3.0 does not work with this harness; ^0.1 rules out 0.2.0 for game's sake.
        self.assertEqual(resolve({"new": ""}, registry, harness=__version__), {"base": "0.2.0", "new": "0.1.0"})
        self.assertEqual(resolve({"mc": ""}, registry, harness=__version__, have={"base": "0.1.0"})["base"], "0.1.0")
        with self.assertRaises(ResolveError) as raised:
            resolve({"mc": "", "new": ""}, registry, harness=__version__)
        self.assertIn("game 0.1.0 needs base ^0.1", str(raised.exception))
        self.assertIn("new 0.1.0 needs base >=0.2", str(raised.exception))
        with self.assertRaisesRegex(ResolveError, "no package nope"):
            resolve({"nope": ""}, registry, harness=__version__)


class InstallTests(Temporary):
    def test_from_the_registry_with_what_it_depends_on(self):
        self.publish("kit", skills=["keys"])
        self.publish("mc", depends={"kit": "^0.1"}, skills=["mine"], embodiments=["mc"])
        packages = self.packages()
        result = packages.install(["mc"], log=self.quiet)
        self.assertEqual(sorted(row["name"] for row in result["installed"]), ["kit", "mc"])
        rows = {row["name"]: row for row in packages.installed()}
        self.assertEqual({name: (row["version"], row["scope"]) for name, row in rows.items()},
                         {"kit": ("0.1.0", "user"), "mc": ("0.1.0", "user")})
        store = Path(rows["mc"]["path"])
        self.assertEqual(store.parent, Path(os.environ["HARNESS_HOME"]) / "packages" / "mc")
        self.assertTrue(store.name.startswith("0.1.0-"))
        # Installed versions never change.
        self.assertFalse(os.access(store / "package.toml", os.W_OK))
        self.assertEqual(packages.provider("embodiments", "mc").name, "mc")
        self.assertEqual([package.name for package in packages.enabled() if "skills" in package.provides],
                         ["kit", "mc"])
        # The skills load in this process once the packages are active (a name a checkout's
        # package has, such as game, would be the checkout's: paths.package_roots).
        activate(packages)
        from harness.runtime.execution.skills import load_skills

        self.assertTrue({"keys", "mine"} <= set(load_skills()))
        with self.assertRaisesRegex(ValueError, "still needed: mc depends on kit"):
            packages.remove(["kit"], log=self.quiet)
        packages.remove(["mc", "kit"], log=self.quiet)
        self.assertEqual(packages.installed(), [])
        self.assertFalse(store.exists())
        activate(packages)
        self.assertNotIn("mine", load_skills())

    def test_a_package_from_elsewhere_needs_consent(self):
        folder = make_package(self.root / "mine", "tool", skills=["hammer"], services=["seg"])
        packages = self.packages()
        asked = packages.install([str(folder)], log=self.quiet)
        self.assertTrue(asked["needs_trust"])
        self.assertEqual(asked["found"][0]["services"], ["seg"])
        self.assertEqual(asked["found"][0]["environments"], [{"for": "service seg", "requirements": ["torch==2.7.0"]}])
        self.assertEqual(packages.installed(), [])
        seen = []
        result = packages.install([str(folder)], consent=lambda found: seen.append(found) or True, log=self.quiet)
        self.assertEqual(result["installed"][0]["source"], f"path:{folder.resolve()}")
        self.assertEqual(len(seen), 1)
        # Linked: used where it is, for a package being written.
        packages.remove(["tool"], log=self.quiet)
        packages.install([str(folder)], consent=lambda found: True, link=True, log=self.quiet)
        row = packages.installed()[0]
        self.assertEqual((row["link"], Path(row["path"])), (True, folder.resolve()))
        packages.remove(["tool"], log=self.quiet)
        self.assertTrue(folder.is_dir())

    def test_a_package_for_another_harness_or_platform_is_refused(self):
        newer = make_package(self.root / "n", "newer", harness=">=99")
        with self.assertRaisesRegex(ResolveError, "works with harness >=99"):
            self.packages().install([str(newer)], consent=lambda found: True, log=self.quiet)
        other = "linux" if manifest.platform() != "linux" else "windows"
        elsewhere = make_package(self.root / "e", "elsewhere", extra="")
        text = (elsewhere / "package.toml").read_text().replace("[package]", f'[package]\nplatforms = ["{other}"]')
        (elsewhere / "package.toml").write_text(text)
        with self.assertRaisesRegex(ResolveError, "runs on"):
            self.packages().install([str(elsewhere)], consent=lambda found: True, log=self.quiet)

    def test_update_takes_the_newest_in_range(self):
        self.publish("kit", "0.1.0")
        packages = self.packages()
        packages.install(["kit@^0.1"], log=self.quiet)
        self.publish("kit", "0.1.4")
        self.publish("kit", "0.2.0")
        packages = self.packages()
        result = packages.update(log=self.quiet)
        self.assertEqual([(row["name"], row["version"]) for row in result["installed"]], [("kit", "0.1.4")])
        self.assertEqual(packages.user().packages["kit"].range, "^0.1")
        self.assertEqual(self.packages().update(log=self.quiet)["installed"], [])

    def test_a_project_pins_its_packages_and_needs_trust(self):
        self.publish("kit", "0.1.0", skills=["grab"])
        self.publish("kit", "0.2.0", skills=["grab"])
        project = self.work / "proj"
        (project / "sub").mkdir(parents=True)
        (project / "harness.toml").write_text('# my project\n[agent]\nmodel = "x"\n\n[packages]\n')
        packages = self.packages(cwd=project / "sub")
        packages.install(["kit@~0.1"], project=True, log=self.quiet)
        text = (project / "harness.toml").read_text()
        self.assertIn('[agent]\nmodel = "x"', text)
        self.assertIn('[packages]\nkit = "~0.1"', text)
        locked = Project(project).locked()
        self.assertEqual((locked["kit"].version, locked["kit"].source), ("0.1.0", "registry:" + str(self.registry_dir)))
        self.assertEqual(packages.installed()[0]["scope"], "project")
        self.assertEqual(packages.user().packages, {})
        # Another user (or a fresh data directory) has not trusted the project.
        stranger = Packages(self.root / "other-data", cwd=project)
        self.assertEqual(stranger.installed(), [])
        # Installing the project's packages trusts it, and installs what the lock says.
        _rmtree(Path(os.environ["HARNESS_HOME"]) / "packages")
        result = stranger.install(project=True, log=self.quiet)
        self.assertEqual([(row["name"], row["version"]) for row in result["installed"]], [("kit", "0.1.0")])
        self.assertEqual(stranger.installed()[0]["scope"], "project")
        stranger.remove(["kit"], project=True, log=self.quiet)
        self.assertEqual(Project(project).locked(), {})

    def test_set_table_keeps_the_rest_of_a_file(self):
        text = '[agent]\nmodel = "x"\n\n[packages]\nold = "1"\n\n[packages.extra]\nx = 1\n\n[[runs]]\nn = 1\n'
        self.assertEqual(set_table(text, "packages", ["[packages]", 'kit = "^1"']),
                         '[agent]\nmodel = "x"\n\n[packages]\nkit = "^1"\n[[runs]]\nn = 1\n')
        self.assertEqual(set_table("", "packages", ["[packages]"]), "[packages]\n")


class FirstUseTests(Temporary):
    def test_auto_install_official_ask_off(self):
        self.publish("rover", embodiments=["rover"], skills=["roverx"])
        packages = self.packages()
        from harness.settings import Settings

        Settings(self.data).update({"packages": {"auto_install": "off"}})
        with self.assertRaisesRegex(MissingPackage, "harness install rover .packages.auto_install is off"):
            packages.ensure("embodiments", "rover", log=self.quiet)
        Settings(self.data).update({"packages": {"auto_install": "ask"}})
        questions = []
        with self.assertRaisesRegex(MissingPackage, "was not installed"):
            packages.ensure("embodiments", "rover", ask=lambda q: questions.append(q) or False, log=self.quiet)
        self.assertEqual(questions[0]["package"], "rover")
        self.assertEqual(packages.installed(), [])
        Settings(self.data).update({"packages": {"auto_install": "official"}})
        self.assertEqual(packages.ensure("embodiments", "rover", log=self.quiet).name, "rover")
        self.assertEqual([row["name"] for row in packages.installed()], ["rover"])
        # Already there: nothing is asked or installed.
        self.assertEqual(packages.ensure("skills", "roverx", ask=None).name, "rover")
        with self.assertRaisesRegex(MissingPackage, "no package provides the bench nowhere"):
            packages.ensure("benches", "nowhere", log=self.quiet)

    def test_offline_the_registry_cache_answers(self):
        self.publish("kit")
        cached = Registry("https://registry.invalid/x")
        cached.cache.mkdir(parents=True)
        (cached.cache / "index.json").write_text((self.registry_dir / "index.json").read_text())
        os.utime(cached.cache / "index.json", (0, 0))
        self.assertEqual(cached.versions("kit"), ["0.1.0"])
        with self.assertRaisesRegex(RegistryError, "cannot be read"):
            Registry("https://registry.invalid/never-cached").index()


class CommandTests(Temporary):
    def run_cli(self, *argv):
        from harness.cli import main

        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        try:
            os.chdir(self.work)
            with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO("")):
                code = main(list(argv))
        finally:
            os.chdir(cwd)
        return code, out.getvalue(), err.getvalue()

    def test_install_list_info_search_update_remove(self):
        self.publish("kit", skills=["grab"], services=["seg"])
        code, out, err = self.run_cli("install", "kit")
        self.assertEqual(code, 0, err)
        self.assertIn("kit 0.1.0", out)
        code, out, _ = self.run_cli("list", "--json")
        self.assertEqual([(row["name"], row["provides"]["skills"]) for row in json.loads(out)], [("kit", ["grab"])])
        code, out, _ = self.run_cli("list")
        self.assertIn("skills: grab", out)
        code, out, _ = self.run_cli("list", "kit")
        self.assertIn("provides: skills: grab; services: seg", out)
        self.assertIn("installs an environment for: service seg: torch==2.7.0", out)
        code, out, _ = self.run_cli("list", "--available", "seg", "--json")
        self.assertEqual([(row["name"], row["installed"]) for row in json.loads(out)], [("kit", "0.1.0")])
        code, out, _ = self.run_cli("list", "--available")
        self.assertIn("kit", out)
        code, out, _ = self.run_cli("install", "--update")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("remove", "kit")
        self.assertEqual((code, out.strip()), (0, "removed kit"))

    def test_a_folder_needs_yes_without_a_terminal(self):
        folder = make_package(self.root / "f", "tool")
        code, _, err = self.run_cli("install", str(folder))
        self.assertEqual(code, 1)
        self.assertIn("harness install --yes", err)
        code, out, err = self.run_cli("install", str(folder), "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("tool 0.1.0 (path:", out)

    def test_unknown_names_say_so(self):
        self.publish("kit")
        code, _, err = self.run_cli("install", "no-such-package")
        self.assertEqual(code, 1)
        self.assertIn("no package no-such-package", err)
        code, out, err = self.run_cli("list", "--available", "no-such-package", "--json")
        self.assertEqual((code, json.loads(out), err), (0, [], ""))


class RegistrationTests(Temporary):
    """What a package registers beside the core's: an embodiment kind, a settings section,
    configuration keys, a command."""

    def test_a_package_brings_a_kind_settings_keys_and_a_command(self):
        folder = make_package(self.root / "src", "drone", extra='[provides]\ncommands = { fly = "dronecli.main:fly" }\n')
        (folder / "kinds.toml").write_text(
            '[drone]\nwhat = "a drone"\nfile_keys = ["name", "control_hz"]\nsession = "dronecli.main:Session"\n'
            'verifier = "You check a claim about a drone."\nstate_label = "Drone state"\nstate_keys = ["step"]\n'
            'cameras = ["front"]\n'
            '[desktop]\nwhat = "not the registered desktop"\nfile_keys = []\nsession = "x:y"\nverifier = ""\n'
            'state_label = ""\n', encoding="utf-8")
        (folder / "settings.toml").write_text(
            '[drone.altitude]\ndefault = 10.0\nkind = "float"\nbounds = [1.0, 100.0]\nabout = "how high it flies"\n'
            '[drone.mode]\ndefault = "calm"\nkind = "choice"\nchoices = ["calm", "fast"]\nabout = "how it flies"\n'
            '[limits.max_steps]\ndefault = 1\nkind = "int"\nbounds = [1, 2]\nabout = "not the core\'s"\n',
            encoding="utf-8")
        (folder / "config_keys.toml").write_text('"runtime.drone_ceiling" = "the highest it may fly"\n',
                                                 encoding="utf-8")
        (folder / "dronecli").mkdir()
        (folder / "dronecli" / "__init__.py").write_text("")
        (folder / "dronecli" / "main.py").write_text(
            "def fly(argv):\n    print('flying', *argv)\n    return 3\n\nclass Session:\n    pass\n")
        packages = self.packages()
        packages.install([str(folder)], consent=lambda found: True, link=True, log=self.quiet)
        activate(packages)
        from harness.config.agent import config_keys
        from harness.embodiments import KINDS
        from harness.settings import SCHEMA, Settings, check

        self.assertEqual((KINDS["drone"].cameras, KINDS["desktop"].what), (("front",), "a computer"))
        self.assertEqual(SCHEMA["drone"]["altitude"][:4], (10.0, "float", (1.0, 100.0), "how high it flies"))
        # A package's section is in every frontend, after the core's.
        from harness.settings import described, rows

        self.assertEqual(SCHEMA["drone"]["altitude"].applies, "next_conversation")
        self.assertEqual(list(described()["drone"]), ["altitude", "mode"])
        self.assertIn("drone.altitude", [row["setting"] for row in rows(Settings(self.data).get())])
        self.assertEqual(check("drone", "mode", "fast"), "fast")
        with self.assertRaises(ValueError):
            check("drone", "mode", "wild")
        self.assertEqual(SCHEMA["limits"]["max_steps"][2], (1, 1000))
        self.assertEqual(Settings(self.data).update({"drone": {"altitude": 20}})["drone"]["altitude"], 20.0)
        self.assertEqual(config_keys()["drone_ceiling"], "the highest it may fly")
        code, out, _ = CommandTests.run_cli(self, "fly", "north", "--fast")
        self.assertEqual((code, out.strip()), (3, "flying north --fast"))
        # Off, it brings nothing.
        packages.enable("drone", False)
        self.assertNotIn("drone", KINDS)
        self.assertNotIn("drone", SCHEMA)


class SettingTests(unittest.TestCase):
    def test_the_packages_settings(self):
        from harness.settings import SCHEMA, check

        self.assertEqual(SCHEMA["packages"]["auto_install"][0], "official")
        self.assertEqual(check("packages", "auto_install", "ask"), "ask")
        with self.assertRaises(ValueError):
            check("packages", "auto_install", "sometimes")


if __name__ == "__main__":
    unittest.main()
