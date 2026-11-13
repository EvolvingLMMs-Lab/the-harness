"""Source-aware registry replacement and incompatible-lock recovery, entirely offline."""
import os
import shlex
import shutil
import subprocess
import sys
from unittest import mock

from test_packages import ROOT, Temporary, make_package
from harness.packages import manifest, sources, state
from harness.packages.manager import MissingPackage, Packages
from harness.packages.registry import Registry, RegistryError, publish
from harness.packages.resolve import ResolveError


class PackageSourceRecoveryTests(Temporary):
    def test_ready_provider_lookup_does_not_publish_another_package_change(self):
        case = self.root / "ready-lookup"
        registry = case / "registry"
        registry.mkdir(parents=True)
        folder = make_package(case / "sources", "widget", skills=["probe"])
        publish(registry, folder, log=self.quiet)
        manager = self.manager(case, registry)
        manager.install(["widget"], log=self.quiet)
        manager.on_change = mock.Mock()
        self.assertEqual(manager.ensure("skills", "probe", log=self.quiet).name, "widget")
        manager.on_change.assert_not_called()

    def manager(self, case, registry):
        work = case / "project"
        work.mkdir(parents=True, exist_ok=True)
        return Packages(case / "data", cwd=work, registry=Registry(str(registry)))

    def published(self, case, registry, name, version="0.1.0", *, depends=None, harness="", payload=""):
        registry.mkdir(parents=True, exist_ok=True)
        folder = make_package(case, name, version, depends=depends, harness=harness)
        (folder / "payload.txt").write_text(payload)
        publish(registry, folder, log=self.quiet)
        return folder

    def records(self, manager, project):
        return manager.project().locked() if project else manager.user().packages

    def cache(self, name, record):
        # Project.locked records intentionally have no path. Never use that field
        # for filesystem mutations; canonical cache paths must be inside this test.
        folder = state.store_path(name, record.version, record.sha256).resolve()
        expected = (self.root / "home" / "packages").resolve()
        self.assertTrue(folder.is_relative_to(expected), str(folder))
        return folder

    def locked_fixture(self, manager, registry, source, *, project, version="0.1.0"):
        """Serialize an old install without pretending the current core/platform supports it."""
        entry = manager.registry.entry("widget", version)
        record = state.Record("widget", version, entry["sha256"], f"registry:{registry}")
        folder = self.cache("widget", record)
        if not folder.is_dir():
            shutil.copytree(source, folder)
            state.freeze(folder)
        record.path = str(folder)
        if project:
            target = state.Project(manager.cwd)
            target.set_wanted({"widget": {"range": "", "source": ""}})
            target.write_lock([record])
            manager.trust_project(target)
        else:
            user = manager.user()
            user.packages["widget"] = record
            user.write()
        return record

    def recover(self, command, manager, registry):
        """Run the shown recovery command at the actual CLI with isolated data/cache."""
        argv = shlex.split(command)
        self.assertEqual(argv.pop(0), "harness")
        env = {**os.environ, "HARNESS_DATA": str(manager.data), "HARNESS_REGISTRY": str(registry),
               "PYTHONPATH": str(ROOT / "src")}
        result = subprocess.run([sys.executable, "-m", "harness", *argv], cwd=manager.cwd, env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def switch_fixture(self, kind, project, label):
        case = self.root / label
        registry_a, registry_b = case / "registry-a", case / "registry-b"
        self.published(case / "source-a", registry_a, "old-dep")
        old = make_package(case / "source-old", "widget", depends={"old-dep": "^0.1"})
        (old / "payload.txt").write_text(f"old-{kind}")
        if kind == "registry":
            publish(registry_a, old, log=self.quiet)
            spec = "widget"
        elif kind == "path":
            spec = str(old)
        elif kind == "git":
            spec = "git:https://example.invalid/widget.git@0123456789abcdef"
        else:
            spec = "https://example.invalid/widget.tar.gz"
        self.published(case / "source-b", registry_b, "new-dep", "0.2.0")
        self.published(case / "source-b", registry_b, "widget", depends={"new-dep": "^0.2"}, payload="registry-b")
        manager_a = self.manager(case, registry_a)
        if kind in ("git", "url"):
            origin = ("git:https://example.invalid/widget.git@0123456789abcdef" if kind == "git"
                      else "url:https://example.invalid/widget.tar.gz#sha256=synthetic")
            with mock.patch.object(sources, "fetch", return_value=(old, origin)):
                manager_a.install([spec], project=project, consent=lambda _: True, log=self.quiet)
        else:
            manager_a.install([spec], project=project, consent=lambda _: True, log=self.quiet)
        return case, registry_b, self.manager(case, registry_b)

    def assert_switched(self, manager, project, registry, version="0.1.0", payload="registry-b"):
        records = self.records(manager, project)
        widget = records["widget"]
        self.assertEqual(widget.version, version)
        self.assertEqual(widget.source, f"registry:{registry}")
        self.assertIn("new-dep", records)
        folder = self.cache("widget", widget)
        self.assertEqual((folder / "payload.txt").read_text(), payload)
        self.assertEqual(manifest.load(folder).depends, {"new-dep": "^0.2"})

    def test_same_version_source_switch_reloads_registry_content_and_dependencies(self):
        for kind in ("path", "git", "url", "registry"):
            for project in (False, True):
                with self.subTest(old_source=kind, project=project):
                    case, registry, manager = self.switch_fixture(kind, project, f"switch-{kind}-{project}")
                    if project:
                        manager.project().set_wanted({"widget": {"range": "^0.1", "source": ""}})
                    if project and kind == "registry":
                        with self.assertRaisesRegex(ResolveError, "harness install --update --project widget"):
                            manager.install(project=True, log=self.quiet)
                        manager.install(["widget"], project=True, log=self.quiet)
                    else:
                        manager.install([] if project else ["widget"], project=project, log=self.quiet)
                    self.assert_switched(manager, project, registry)

    def test_same_version_registry_identity_change_counts_as_an_update(self):
        for project in (False, True):
            with self.subTest(project=project):
                case, registry, manager = self.switch_fixture("registry", project, f"update-{project}")
                result = manager.update(["widget"], project=project, log=self.quiet)
                self.assertIn("widget", {row["name"] for row in result["installed"]})
                self.assert_switched(manager, project, registry)

    def test_implicit_registry_switch_refuses_different_content_until_explicit_selection(self):
        case, registry, manager = self.switch_fixture("registry", True, "implicit-new-version")
        self.published(case / "source-b", registry, "widget", "0.1.1",
                       depends={"new-dep": "^0.2"}, payload="registry-b-new")
        manager.project().set_wanted({"widget": {"range": "^0.1", "source": ""}})
        before = manager.project().lock_file.read_bytes()
        with self.assertRaisesRegex(ResolveError, "harness install --update --project widget"):
            manager.install(project=True, log=self.quiet)
        self.assertEqual(manager.project().lock_file.read_bytes(), before)
        manager.install(["widget"], project=True, log=self.quiet)
        self.assert_switched(manager, True, registry, "0.1.1", "registry-b-new")

    def test_incompatible_core_lock_with_or_without_cache_refuses_then_update_recovers(self):
        for project in (False, True):
            for cached in (False, True):
                with self.subTest(project=project, cached=cached):
                    case = self.root / f"core-{project}-{cached}"
                    registry = case / "registry"
                    old = self.published(case / "sources", registry, "widget", harness="<0.83")
                    self.published(case / "sources", registry, "widget", "0.2.0", harness=">=0.83")
                    manager = self.manager(case, registry)
                    record = self.locked_fixture(manager, registry, old, project=project)
                    folder = self.cache("widget", record)
                    if not cached:
                        # Keep absent-cache fixtures recoverable and contained in
                        # the owned temporary root; no deletion of record.path.
                        folder.rename(case / "detached-widget-cache")
                    side = make_package(case / "side-source", "side", depends={"widget": ">=0.1,<1"})
                    if project:
                        wanted = manager.project().wanted()
                        wanted["side"] = {"range": "", "source": str(side)}
                        manager.project().set_wanted(wanted)
                    files = ([manager.project().file, manager.project().lock_file]
                             if project else [manager.user().path])
                    before = {path: path.read_bytes() for path in files}
                    stored = sorted(state.store_root().glob("*/*"))
                    command = "harness install --update" + (" --project" if project else "")
                    with self.assertRaisesRegex(ResolveError, command):
                        manager.install([] if project else [str(side)], project=project,
                                        consent=lambda _: True, log=self.quiet)
                    self.assertEqual({path: path.read_bytes() for path in files}, before)
                    self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                    manager.update(["widget"], project=project, log=self.quiet)
                    self.assertEqual(self.records(manager, project)["widget"].version, "0.2.0")
                    manager.install([] if project else [str(side)], project=project,
                                    consent=lambda _: True, log=self.quiet)
                    self.assertIn("side", self.records(manager, project))

    def test_platform_lock_is_checked_before_unrelated_local_package_is_stored(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                case = self.root / f"platform-{cached}"
                registry = case / "registry"
                other = "linux" if manifest.platform() != "linux" else "windows"
                registry.mkdir(parents=True)
                old = make_package(case / "sources", "widget")
                package_file = old / "package.toml"
                package_file.write_text(package_file.read_text() + f'platforms = ["{other}"]\n')
                publish(registry, old, log=self.quiet)
                self.published(case / "sources", registry, "widget", "0.2.0")
                manager = self.manager(case, registry)
                self.locked_fixture(manager, registry, old, project=True)
                if not cached:
                    folder = self.cache("widget", manager.project().locked()["widget"])
                    folder.rename(case / "detached-platform-cache")
                wanted = manager.project().wanted()
                wanted["widget"]["range"] = ""
                side = make_package(case / "side-source", "side", depends={"widget": ">=0.1,<1"})
                wanted["side"] = {"range": "", "source": str(side)}
                manager.project().set_wanted(wanted)
                lock = manager.project().lock_file.read_bytes()
                stored = sorted(state.store_root().glob("*/*"))
                with self.assertRaisesRegex(ResolveError, "harness install --update --project"):
                    manager.install(project=True, consent=lambda _: True, log=self.quiet)
                self.assertEqual(manager.project().lock_file.read_bytes(), lock)
                self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                manager.update(["widget"], project=True, log=self.quiet)
                manager.install(project=True, consent=lambda _: True, log=self.quiet)
                self.assertEqual(manager.project().locked()["widget"].version, "0.2.0")

    def test_implicit_conflict_hint_distinguishes_changed_ranges_and_obsolete_lock_entries(self):
        case = self.root / "hint"
        registry = case / "registry"
        self.published(case / "sources", registry, "widget")
        self.published(case / "sources", registry, "parent", depends={"widget": "^0.1"})
        manager = self.manager(case, registry)
        manager.install(["parent"], project=True, log=self.quiet)
        self.published(case / "sources", registry, "widget", "0.2.0")
        manager = self.manager(case, registry)
        manager.project().set_wanted({"widget": {"range": "^0.2", "source": ""}})
        with self.assertRaises(ResolveError) as failure:
            manager.install(project=True, log=self.quiet)
        self.assertIn("harness install --update --project", str(failure.exception))
        self.assertIn("harness remove --project NAME", str(failure.exception))

    def test_explicit_project_registry_switch_clears_dev_source_and_survives_implicit_install(self):
        case, registry, manager = self.switch_fixture("path", True, "explicit-project")
        manager.install(["widget"], project=True, log=self.quiet)
        self.assertEqual(manager.project().wanted()["widget"]["source"], "")
        manager.install(project=True, log=self.quiet)
        self.assert_switched(manager, True, registry)

    def test_active_same_named_registry_dependencies_switch_content_and_metadata_together(self):
        case = self.root / "same-dependency"
        registry_a, registry_b = case / "a", case / "b"
        self.published(case / "source-a", registry_a, "old-leaf")
        self.published(case / "source-a", registry_a, "dep", depends={"old-leaf": "^0.1"}, payload="dep-a")
        self.published(case / "source-a", registry_a, "widget", depends={"dep": "^0.1"}, payload="widget-a")
        self.published(case / "source-b", registry_b, "new-leaf", "0.2.0")
        self.published(case / "source-b", registry_b, "dep", depends={"new-leaf": "^0.2"}, payload="dep-b")
        self.published(case / "source-b", registry_b, "widget", depends={"dep": "^0.1"}, payload="widget-b")
        self.manager(case, registry_a).install(["widget"], log=self.quiet)
        manager = self.manager(case, registry_b)
        manager.install(["widget"], log=self.quiet)
        records = manager.user().packages
        self.assertIn("new-leaf", records)
        self.assertEqual(records["dep"].source, f"registry:{registry_b}")
        self.assertEqual((self.cache("dep", records["dep"]) / "payload.txt").read_text(), "dep-b")
        self.assertEqual(manifest.load(self.cache("dep", records["dep"])).depends, {"new-leaf": "^0.2"})

    def test_official_alias_mirror_restores_same_archive_without_version_or_source_churn(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                case = self.root / f"mirror-{cached}"
                registry, mirror = case / "registry", case / "mirror"
                self.published(case / "sources", registry, "widget", payload="locked")
                manager = self.manager(case, registry)
                manager.install(["widget@^0.1"], project=True, log=self.quiet)
                records = manager.project().locked()
                records["widget"].source = "registry"
                manager.project().write_lock(records.values())
                self.published(case / "sources", registry, "widget", "0.1.1", payload="newer")
                shutil.copytree(registry, mirror)
                if not cached:
                    self.cache("widget", records["widget"]).rename(case / "detached-cache")
                before = manager.project().lock_file.read_bytes()
                offline = self.manager(case, mirror)
                offline.install(project=True, log=self.quiet)
                restored = offline.project().locked()["widget"]
                self.assertEqual(restored.version, "0.1.0")
                self.assertEqual(restored.source, "registry")
                self.assertEqual(restored.sha256, records["widget"].sha256)
                self.assertEqual(offline.project().lock_file.read_bytes(), before)
                self.assertEqual((self.cache("widget", restored) / "payload.txt").read_text(), "locked")

    def test_older_official_alias_mirror_refuses_missing_locked_archive_without_downgrade(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                case = self.root / f"old-mirror-{cached}"
                registry, mirror = case / "registry", case / "mirror"
                self.published(case / "sources", registry, "widget", payload="old")
                shutil.copytree(registry, mirror)
                self.published(case / "sources", registry, "widget", "0.1.1", payload="locked-newer")
                manager = self.manager(case, registry)
                manager.install(["widget@^0.1"], project=True, log=self.quiet)
                records = manager.project().locked()
                records["widget"].source = "registry"
                manager.project().write_lock(records.values())
                if not cached:
                    self.cache("widget", records["widget"]).rename(case / "detached-cache")
                before = manager.project().lock_file.read_bytes()
                offline = self.manager(case, mirror)
                with self.assertRaisesRegex(ResolveError, "harness install --update --project"):
                    offline.install(project=True, log=self.quiet)
                self.assertEqual(offline.project().lock_file.read_bytes(), before)
                self.assertEqual(offline.project().locked()["widget"].version, "0.1.1")

    def test_ensure_refuses_broken_dev_source_and_disabled_registry_choice(self):
        for dev in (False, True):
            with self.subTest(dev=dev):
                case = self.root / f"ensure-{dev}"
                registry_a, registry_b = case / "a", case / "b"
                registry_a.mkdir(parents=True)
                registry_b.mkdir(parents=True)
                for label, registry in (("a", registry_a), ("b", registry_b)):
                    folder = make_package(case / label / "source", "widget", skills=["r7grab"])
                    (folder / "payload.txt").write_text(label)
                    publish(registry, folder, log=self.quiet)
                manager = self.manager(case, registry_a)
                if dev:
                    local = make_package(case / "dev", "widget")
                    manager.install([str(local)], link=True, consent=lambda _: True, log=self.quiet)
                    (local / "package.toml").write_text("broken [")
                else:
                    manager.install(["widget"], log=self.quiet)
                    manager.enable("widget", False)
                before = manager.user().path.read_bytes()
                selected = self.manager(case, registry_b)
                with self.assertRaisesRegex(MissingPackage, "repair|disabled"):
                    selected.ensure("skills", "r7grab", log=self.quiet)
                self.assertEqual(selected.user().path.read_bytes(), before)
                record = selected.user().packages["widget"]
                self.assertEqual(record.link, dev)
                self.assertEqual(record.enabled, dev)

    def test_replacements_keep_disabled_state_and_owner_selected_dev_dependency(self):
        case, registry, manager = self.switch_fixture("registry", False, "disabled-update")
        manager.enable("widget", False)
        manager.update(["widget"], log=self.quiet)
        self.assertFalse(manager.user().packages["widget"].enabled)
        local = make_package(case / "dev", "widget")
        manager.install([str(local)], consent=lambda _: True, link=True, log=self.quiet)
        self.assertFalse(manager.user().packages["widget"].enabled)
        # A registry parent may use an owner-selected development dependency.
        dep = make_package(case / "dev", "dep")
        (dep / "payload.txt").write_text("dev")
        manager.install([str(dep)], consent=lambda _: True, link=True, log=self.quiet)
        self.published(case / "source-b", registry, "dep", payload="registry")
        self.published(case / "source-b", registry, "parent", depends={"dep": "^0.1"})
        manager.registry.index(refresh=True)
        manager.install(["parent"], log=self.quiet)
        record = manager.user().packages["dep"]
        self.assertTrue(record.link)
        self.assertEqual((dep / "payload.txt").read_text(), "dev")

    def test_platform_selection_can_install_and_update_to_an_older_compatible_version(self):
        case = self.root / "platform-selection"
        registry = case / "registry"
        self.published(case / "sources", registry, "widget", payload="compatible")
        incompatible = make_package(case / "sources", "widget", "0.2.0")
        other = "linux" if manifest.platform() != "linux" else "windows"
        file = incompatible / "package.toml"
        file.write_text(file.read_text() + f'platforms = ["{other}"]\n')
        publish(registry, incompatible, log=self.quiet)
        manager = self.manager(case, registry)
        manager.install(["widget"], log=self.quiet)
        self.assertEqual(manager.user().packages["widget"].version, "0.1.0")
        self.locked_fixture(manager, registry, incompatible, project=True, version="0.2.0")
        with self.assertRaisesRegex(ResolveError, "harness install --update --project"):
            manager.install(project=True, log=self.quiet)
        manager.update(["widget"], project=True, log=self.quiet)
        self.assertEqual(manager.project().locked()["widget"].version, "0.1.0")

    def test_ensure_honors_user_and_project_pins_without_publishing_a_useless_update(self):
        for project in (False, True):
            for in_range_patch in (False, True):
                with self.subTest(project=project, in_range_patch=in_range_patch):
                    case = self.root / f"ensure-pin-{project}-{in_range_patch}"
                    registry = case / "registry"
                    self.published(case / "sources", registry, "pin-demo")
                    manager = self.manager(case, registry)
                    manager.install(["pin-demo@^0.1"], project=project, log=self.quiet)
                    if in_range_patch:
                        self.published(case / "sources", registry, "pin-demo", "0.1.1")
                    providing = make_package(case / "sources", "pin-demo", "0.2.0", skills=["probe"])
                    publish(registry, providing, log=self.quiet)
                    manager = self.manager(case, registry)
                    if project:
                        # This user version must not be changed while recovering
                        # the trusted project's different pinned version.
                        manager.install(["pin-demo@^0.2"], log=self.quiet)
                    files = [manager.user().path]
                    if project:
                        files += [manager.project().file, manager.project().lock_file]
                    before = {path: path.read_bytes() for path in files}
                    stored = sorted(state.store_root().glob("*/*"))
                    with self.assertRaisesRegex(MissingPackage, r"recorded range \^0.1"):
                        manager.ensure("skills", "probe", log=self.quiet)
                    self.assertEqual({path: path.read_bytes() for path in files}, before)
                    self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                    self.assertEqual(self.records(manager, project)["pin-demo"].version, "0.1.0")

    def test_ensure_can_update_within_existing_range_and_scope(self):
        for project in (False, True):
            with self.subTest(project=project):
                case = self.root / f"ensure-compatible-{project}"
                registry = case / "registry"
                self.published(case / "sources", registry, "pin-demo")
                manager = self.manager(case, registry)
                manager.install(["pin-demo@^0.1"], project=project, log=self.quiet)
                for version in ("0.1.1", "0.2.0"):
                    providing = make_package(case / "sources", "pin-demo", version, skills=["probe"])
                    publish(registry, providing, log=self.quiet)
                manager = self.manager(case, registry)
                if project:
                    manager.install(["pin-demo@^0.2"], log=self.quiet)
                    user_before = manager.user().path.read_bytes()
                    manifest_before = manager.project().file.read_bytes()
                found = manager.ensure("skills", "probe", log=self.quiet)
                self.assertEqual(found.version, "0.1.1")
                self.assertEqual(self.records(manager, project)["pin-demo"].version, "0.1.1")
                if project:
                    self.assertEqual(manager.user().path.read_bytes(), user_before)
                    self.assertEqual(manager.project().file.read_bytes(), manifest_before)
                else:
                    self.assertEqual(manager.user().packages["pin-demo"].range, "^0.1")

    def test_ensure_registry_mismatch_requires_explicit_selection_in_existing_scope(self):
        for project in (False, True):
            with self.subTest(project=project):
                case = self.root / f"ensure-selection-{project}"
                registry_a, registry_b = case / "a", case / "b"
                self.published(case / "source-a", registry_a, "widget", payload="source-a")
                registry_b.mkdir(parents=True)
                providing = make_package(case / "source-b", "widget", skills=["probe"])
                publish(registry_b, providing, log=self.quiet)
                manager = self.manager(case, registry_a)
                manager.install(["widget@^0.1"], project=project, log=self.quiet)
                selected = self.manager(case, registry_b)
                files = [selected.user().path]
                if project:
                    files += [selected.project().file, selected.project().lock_file]
                before = {path: path.read_bytes() for path in files}
                command = "harness install --update" + (" --project" if project else "") + " widget"
                with self.assertRaisesRegex(MissingPackage, command):
                    selected.ensure("skills", "probe", log=self.quiet)
                self.assertEqual({path: path.read_bytes() for path in files}, before)
                self.assertEqual(self.records(selected, project)["widget"].source, f"registry:{registry_a}")

    def test_ensure_reactivates_installed_provider_after_stale_process_roots(self):
        from harness import paths
        for project in (False, True):
            with self.subTest(project=project):
                case = self.root / f"stale-roots-{project}"
                registry = case / "registry"
                registry.mkdir(parents=True)
                folder = make_package(case / "sources", "widget", skills=["probe"])
                publish(registry, folder, log=self.quiet)
                manager = self.manager(case, registry)
                manager.install(["widget@^0.1"], project=project, log=self.quiet)
                record = self.records(manager, project)["widget"]
                before = (record.version, record.source, record.sha256, record.enabled)
                os.environ["HARNESS_PACKAGE_ROOTS"] = ""
                paths.packages_changed()
                self.assertIsNone(manager.provider("skills", "probe"))
                self.assertEqual(manager.ensure("skills", "probe", log=self.quiet).version, "0.1.0")
                restored = self.records(manager, project)["widget"]
                self.assertEqual((restored.version, restored.source, restored.sha256, restored.enabled), before)

    def test_selected_plan_repairs_missing_root_or_dependency_cache_without_changing_pins(self):
        for project in (False, True):
            for missing_root in (False, True):
                with self.subTest(project=project, missing_root=missing_root):
                    case = self.root / f"repair-cache-{project}-{missing_root}"
                    registry = case / "registry"
                    self.published(case / "sources", registry, "lib")
                    widget = make_package(case / "sources", "widget", depends={"lib": "^0.1"}, skills=["probe"])
                    publish(registry, widget, log=self.quiet)
                    manager = self.manager(case, registry)
                    manager.install(["widget@^0.1"], project=project, log=self.quiet)
                    records = self.records(manager, project)
                    before = {name: (row.version, row.sha256, row.source, row.enabled) for name, row in records.items()}
                    self.cache("lib", records["lib"]).rename(case / "detached-lib")
                    if missing_root:
                        self.cache("widget", records["widget"]).rename(case / "detached-widget")
                        manager.ensure("skills", "probe", log=self.quiet)
                    else:
                        manager.update(["widget"], project=project, log=self.quiet)
                    restored = self.records(manager, project)
                    self.assertEqual({name: (row.version, row.sha256, row.source, row.enabled)
                                      for name, row in restored.items()}, before)
                    for name, row in restored.items():
                        self.assertTrue((self.cache(name, row) / "package.toml").is_file())
                    if project:
                        self.assertEqual(manager.project().wanted()["widget"]["range"], "^0.1")
                        self.assertNotIn("widget", manager.user().packages)
                    else:
                        self.assertEqual(manager.user().packages["widget"].range, "^0.1")

    def test_registry_recovery_hints_execute_without_dropping_user_or_project_ranges(self):
        for project in (False, True):
            with self.subTest(project=project):
                case = self.root / f"registry-hint-{project}"
                a, b = case / "a", case / "b"
                self.published(case / "a-source", a, "widget", payload="a")
                b.mkdir(parents=True)
                for version in ("0.1.0", "0.2.0"):
                    folder = make_package(case / "b-source", "widget", version, skills=["probe"])
                    publish(b, folder, log=self.quiet)
                manager = self.manager(case, a)
                manager.install(["widget@^0.1"], project=project, log=self.quiet)
                selected = self.manager(case, b)
                command = "harness install --update" + (" --project" if project else "") + " widget"
                with self.assertRaises(MissingPackage) as failure:
                    selected.ensure("skills", "probe", log=self.quiet)
                self.assertIn(command, str(failure.exception))
                self.recover(command, selected, b)
                record = self.records(selected, project)["widget"]
                self.assertEqual(record.version, "0.1.0")
                self.assertEqual(record.source, f"registry:{b}")
                self.assertEqual(selected.project().wanted()["widget"]["range"] if project else record.range, "^0.1")

    def test_dev_selection_hint_includes_and_preserves_the_owner_range(self):
        for project in (False, True):
            with self.subTest(project=project):
                case = self.root / f"dev-hint-{project}"
                registry = case / "registry"
                registry.mkdir(parents=True)
                for version in ("0.1.0", "0.2.0"):
                    folder = make_package(case / "sources", "widget", version, skills=["probe"])
                    publish(registry, folder, log=self.quiet)
                dev = make_package(case / "dev", "widget")
                manager = self.manager(case, registry)
                manager.install([str(dev)], project=project, link=not project, consent=lambda _: True, log=self.quiet)
                if project:
                    wanted = manager.project().wanted()
                    wanted["widget"]["range"] = "^0.1"
                    manager.project().set_wanted(wanted)
                else:
                    user = manager.user()
                    user.packages["widget"].range = "^0.1"
                    user.write()
                command = "harness install" + (" --project" if project else "") + " " + shlex.quote("widget@^0.1")
                with self.assertRaises(MissingPackage) as failure:
                    manager.ensure("skills", "probe", log=self.quiet)
                self.assertIn(command, str(failure.exception))
                self.recover(command, manager, registry)
                record = self.records(manager, project)["widget"]
                self.assertEqual(record.version, "0.1.0")
                self.assertEqual(manager.project().wanted()["widget"]["range"] if project else record.range, "^0.1")
                self.assertEqual(record.source, f"registry:{registry}")

    def test_explicit_project_install_cannot_downgrade_an_unnamed_locked_mirror_dependency(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                case = self.root / f"project-dep-{cached}"
                a, b = case / "a", case / "b"
                self.published(case / "a-source", a, "lib", "0.1.1", payload="locked")
                self.published(case / "b-source", b, "lib", payload="older")
                self.published(case / "b-source", b, "newpkg", depends={"lib": "^0.1"})
                manager = self.manager(case, a)
                manager.install(["lib@^0.1"], project=True, log=self.quiet)
                if not cached:
                    self.cache("lib", manager.project().locked()["lib"]).rename(case / "detached-lib")
                selected = self.manager(case, b)
                before = selected.project().lock_file.read_bytes(), selected.project().file.read_bytes()
                stored = sorted(state.store_root().glob("*/*"))
                command = "harness install --update --project lib"
                with self.assertRaisesRegex(ResolveError, "then retry the original") as failure:
                    selected.install(["newpkg"], project=True, log=self.quiet)
                self.assertIn(command, str(failure.exception))
                self.assertEqual((selected.project().lock_file.read_bytes(), selected.project().file.read_bytes()), before)
                self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                self.recover(command, selected, b)
                self.assertEqual(selected.project().wanted()["lib"]["range"], "^0.1")
                selected.install(["newpkg"], project=True, log=self.quiet)
                self.assertEqual(selected.project().locked()["lib"].version, "0.1.0")

    def test_unrequested_dev_dependency_cannot_be_replaced_when_version_or_files_do_not_fit(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                case = self.root / f"dev-dep-{missing}"
                registry = case / "registry"
                self.published(case / "sources", registry, "dep", "0.8.0", payload="registry")
                parent = make_package(case / "sources", "parent", depends={"dep": "^0.8"}, skills=["probe"])
                publish(registry, parent, log=self.quiet)
                dev = make_package(case / "dev", "dep", "0.8.0" if missing else "0.9.0")
                manager = self.manager(case, registry)
                manager.install([str(dev)], link=True, consent=lambda _: True, log=self.quiet)
                if missing:
                    self.assertTrue(dev.resolve().is_relative_to(self.root.resolve()))
                    dev.rename(case / "detached-dev")
                before = manager.user().path.read_bytes()
                stored = sorted(state.store_root().glob("*/*"))
                with self.assertRaisesRegex(ResolveError, "repair.*harness install dep"):
                    manager.ensure("skills", "probe", log=self.quiet)
                self.assertEqual(manager.user().path.read_bytes(), before)
                self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                self.assertTrue(manager.user().packages["dep"].link)

    def test_uncached_same_address_changed_archive_refuses_until_range_preserving_update(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                case = self.root / f"same-address-{cached}"
                registry, rebuilt = case / "registry", case / "rebuilt"
                self.published(case / "old-source", registry, "widget", payload="original")
                manager = self.manager(case, registry)
                manager.install(["widget@^0.1"], project=True, log=self.quiet)
                old = manager.project().locked()["widget"]
                self.published(case / "new-source", rebuilt, "widget", payload="changed")
                fresh_entry = Registry(str(rebuilt)).entry("widget", "0.1.0")
                shutil.copyfile(rebuilt / fresh_entry["file"], registry / fresh_entry["file"])
                shutil.copyfile(rebuilt / "index.json", registry / "index.json")
                selected = self.manager(case, registry)
                before = selected.project().lock_file.read_bytes()
                if cached:
                    # A cached original is usable even when its same-address
                    # index is unavailable; no forced index lookup is allowed.
                    (registry / "index.json").rename(case / "detached-index.json")
                    selected.install(project=True, log=self.quiet)
                    self.assertEqual(selected.project().lock_file.read_bytes(), before)
                    self.assertEqual((self.cache("widget", old) / "payload.txt").read_text(), "original")
                else:
                    self.cache("widget", old).rename(case / "detached-widget")
                    command = "harness install --update --project widget"
                    with self.assertRaisesRegex(ResolveError, command):
                        selected.install(project=True, log=self.quiet)
                    self.assertEqual(selected.project().lock_file.read_bytes(), before)
                    self.recover(command, selected, registry)
                    updated = selected.project().locked()["widget"]
                    self.assertEqual(updated.sha256, fresh_entry["sha256"])
                    self.assertEqual(selected.project().wanted()["widget"]["range"], "^0.1")
                    self.assertEqual((self.cache("widget", updated) / "payload.txt").read_text(), "changed")

    def test_automatic_missing_root_recovery_verifies_original_archive_in_both_scopes(self):
        for project in (False, True):
            with self.subTest(project=project):
                case = self.root / f"auto-original-{project}"
                a, rebuilt = case / "registry", case / "rebuilt"
                a.mkdir(parents=True)
                rebuilt.mkdir(parents=True)
                for label, registry in (("old", a), ("new", rebuilt)):
                    widget = make_package(case / label, "widget", skills=["probe"])
                    (widget / "payload.txt").write_text(label)
                    publish(registry, widget, log=self.quiet)
                manager = self.manager(case, a)
                manager.install(["widget@^0.1"], project=project, log=self.quiet)
                old = self.records(manager, project)["widget"]
                self.cache("widget", old).rename(case / "detached-widget")
                new = Registry(str(rebuilt)).entry("widget", "0.1.0")
                shutil.copyfile(rebuilt / new["file"], a / new["file"])
                shutil.copyfile(rebuilt / "index.json", a / "index.json")
                selected = self.manager(case, a)
                files = [selected.user().path] + ([selected.project().file, selected.project().lock_file] if project else [])
                before = {path: path.read_bytes() for path in files}
                command = "harness install --update" + (" --project" if project else "") + " widget"
                with self.assertRaisesRegex(ResolveError, command):
                    selected.ensure("skills", "probe", log=self.quiet)
                self.assertEqual({path: path.read_bytes() for path in files}, before)
                self.recover(command, selected, a)
                restored = self.records(selected, project)["widget"]
                self.assertEqual(restored.sha256, new["sha256"])
                self.assertEqual(selected.project().wanted()["widget"]["range"] if project else restored.range, "^0.1")

    def test_automatic_active_dependencies_do_not_re_source_through_an_older_mirror(self):
        for project in (False, True):
            for cached in (False, True):
                with self.subTest(project=project, cached=cached):
                    case = self.root / f"auto-dependency-{project}-{cached}"
                    a, mirror = case / "a", case / "mirror"
                    self.published(case / "a-source", a, "lib", "0.1.1", payload="original")
                    self.published(case / "a-source", a, "widget", depends={"lib": "^0.1"})
                    manager = self.manager(case, a)
                    manager.install(["widget@^0.1"], project=project, log=self.quiet)
                    if not cached:
                        self.cache("lib", self.records(manager, project)["lib"]).rename(case / "detached-lib")
                    shutil.copytree(a, mirror)
                    index = Registry(str(mirror)).index()
                    index["packages"].pop("lib")
                    import json
                    (mirror / "index.json").write_text(json.dumps(index))
                    self.published(case / "mirror-source", mirror, "lib", payload="older")
                    new = make_package(case / "mirror-source", "widget", "0.1.1", depends={"lib": "^0.1"}, skills=["probe"])
                    publish(mirror, new, log=self.quiet)
                    selected = self.manager(case, mirror)
                    files = [selected.user().path] + ([selected.project().file, selected.project().lock_file] if project else [])
                    before = {path: path.read_bytes() for path in files}
                    stored = sorted(state.store_root().glob("*/*"))
                    with self.assertRaisesRegex(ResolveError, "harness install --update"):
                        selected.ensure("skills", "probe", log=self.quiet)
                    self.assertEqual({path: path.read_bytes() for path in files}, before)
                    self.assertEqual(sorted(state.store_root().glob("*/*")), stored)

    def test_project_dependency_refusal_shows_a_joint_executable_range_preserving_recovery(self):
        case = self.root / "joint-recovery"
        a, b = case / "a", case / "b"
        self.published(case / "a-source", a, "lib")
        self.published(case / "a-source", a, "widget", depends={"lib": "^0.1"})
        self.published(case / "b-source", b, "lib", "0.2.0")
        self.published(case / "b-source", b, "widget", depends={"lib": "^0.2"}, payload="selected")
        manager = self.manager(case, a)
        manager.install(["widget@^0.1"], project=True, log=self.quiet)
        selected = self.manager(case, b)
        before = selected.project().file.read_bytes()
        command = "harness install --update --project widget lib"
        with self.assertRaises(ResolveError) as failure:
            selected.update(["widget"], project=True, log=self.quiet)
        self.assertIn(command, str(failure.exception))
        self.recover(command, selected, b)
        self.assertEqual(selected.project().file.read_bytes(), before)
        self.assertEqual(selected.project().locked()["lib"].version, "0.2.0")
        self.assertEqual(selected.project().locked()["widget"].source, f"registry:{b}")

    def test_registry_read_failure_is_not_relabelled_as_content_mismatch(self):
        for alias in (False, True):
            with self.subTest(alias=alias):
                case = self.root / f"unreadable-{alias}"
                registry = case / "registry"
                self.published(case / "sources", registry, "widget")
                manager = self.manager(case, registry)
                manager.install(["widget"], project=True, log=self.quiet)
                records = manager.project().locked()
                if alias:
                    records["widget"].source = "registry"
                    manager.project().write_lock(records.values())
                else:
                    self.cache("widget", records["widget"]).rename(case / "detached-widget")
                (registry / "index.json").rename(case / "detached-index.json")
                before = manager.project().lock_file.read_bytes()
                with self.assertRaises(RegistryError) as failure:
                    self.manager(case, registry).install(project=True, log=self.quiet)
                self.assertIn("cannot be read", str(failure.exception))
                self.assertNotIn("explicitly select", str(failure.exception))
                self.assertEqual(manager.project().lock_file.read_bytes(), before)

    def test_ready_installed_provider_refreshes_before_auto_policy_and_stale_registry_gates(self):
        from harness import paths
        from harness.settings import Settings
        for mode in ("off", "ask"):
            for dev in (False, True):
                with self.subTest(mode=mode, dev=dev):
                    case = self.root / f"ready-{mode}-{dev}"
                    registry = case / "registry"
                    self.published(case / "sources", registry, "unrelated")
                    host = self.manager(case, registry)
                    host.registry.index()  # This host's index predates the owner installation.
                    folder = make_package(case / "new-source", "widget", skills=["probe"])
                    publish(registry, folder, log=self.quiet)
                    installer = self.manager(case, registry)
                    installer.install([str(folder)] if dev else ["widget@^0.1"], link=dev,
                                      consent=lambda _: True, log=self.quiet)
                    Settings(host.data).update({"packages": {"auto_install": mode}})
                    os.environ["HARNESS_PACKAGE_ROOTS"] = ""
                    paths.packages_changed()
                    self.assertEqual(host.registry.providers("skills", "probe"), [])
                    before = host.user().path.read_bytes()
                    def no_prompt(found):
                        raise AssertionError("already installed capability must not ask to install")
                    self.assertEqual(host.ensure("skills", "probe", ask=no_prompt, log=self.quiet).name, "widget")
                    self.assertEqual(host.user().path.read_bytes(), before)
                    self.assertEqual(host.user().packages["widget"].link, dev)

    def test_stray_project_lock_refuses_dev_replacement_without_project_attribute_error(self):
        case = self.root / "stray-lock"
        registry = case / "registry"
        self.published(case / "sources", registry, "dep", "0.8.0")
        self.published(case / "sources", registry, "parent", depends={"dep": "^0.8"})
        dev = make_package(case / "dev", "dep", "0.9.0")
        manager = self.manager(case, registry)
        manager.install([str(dev)], consent=lambda _: True, log=self.quiet)
        target = state.Project(manager.cwd)
        target.write_lock([manager.user().packages["dep"]])
        self.assertIsNone(manager.project())
        before = target.lock_file.read_bytes()
        with self.assertRaisesRegex(ResolveError, "repair.*harness install --project dep"):
            manager.install(["parent"], project=True, log=self.quiet)
        self.assertFalse(target.file.exists())
        self.assertEqual(target.lock_file.read_bytes(), before)

    def test_windows_repair_specs_use_double_quotes_without_changing_os_state(self):
        for spec in ("widget@^0.1", "widget@>=0.1,<1"):
            with self.subTest(spec=spec):
                self.assertEqual(Packages._quote_spec(spec, windows=True), '"' + spec + '"')
                self.assertEqual(Packages._quote_spec(spec, windows=False), shlex.quote(spec))

    def test_narrow_recovery_ignores_unrequested_orphan_lock_entries_absent_from_registry(self):
        case = self.root / "orphan-hint"
        a, b = case / "a", case / "b"
        self.published(case / "a-source", a, "helper")
        self.published(case / "a-source", a, "lib", depends={"helper": "^0.1"})
        manager = self.manager(case, a)
        manager.install(["lib@^0.1"], project=True, log=self.quiet)
        self.published(case / "a-source", a, "lib", "0.1.1")
        manager.update(["lib"], project=True, log=self.quiet)
        orphan = manager.project().locked()["helper"].row()
        self.published(case / "b-source", b, "lib", payload="selected")
        self.published(case / "b-source", b, "newpkg", depends={"lib": "^0.1"})
        selected = self.manager(case, b)
        command = "harness install --update --project lib"
        with self.assertRaises(ResolveError) as failure:
            selected.install(["newpkg"], project=True, log=self.quiet)
        self.assertIn(command, str(failure.exception))
        self.assertIn("then retry the original", str(failure.exception))
        self.assertNotIn("newpkg lib", str(failure.exception))
        self.assertNotIn("helper", str(failure.exception))
        self.recover(command, selected, b)
        self.assertEqual(selected.project().locked()["helper"].row(), orphan)
        self.assertEqual(selected.project().wanted()["lib"]["range"], "^0.1")
        selected.install(["newpkg"], project=True, log=self.quiet)
        self.assertIn("newpkg", selected.project().locked())

    def test_implicit_restore_hint_names_only_the_failing_declared_package(self):
        case = self.root / "declared-hint"
        a, b = case / "a", case / "b"
        self.published(case / "a-source", a, "lib", payload="old")
        other = self.published(case / "a-source", a, "other", payload="same")
        manager = self.manager(case, a)
        manager.install(["lib@^0.1", "other@^0.1"], project=True, log=self.quiet)
        self.published(case / "b-source", b, "lib", payload="changed")
        publish(b, other, log=self.quiet)
        self.published(case / "b-source", b, "other", "0.1.1", payload="unrequested newer")
        selected = self.manager(case, b)
        command = "harness install --update --project lib"
        with self.assertRaises(ResolveError) as failure:
            selected.install(project=True, log=self.quiet)
        self.assertIn(command + " to explicitly", str(failure.exception))
        self.assertNotIn("lib other", str(failure.exception))
        self.recover(command, selected, b)
        selected.install(project=True, log=self.quiet)
        self.assertEqual(selected.project().locked()["other"].version, "0.1.0")
        self.assertEqual(selected.project().wanted()["other"]["range"], "^0.1")

    def test_stray_registry_lock_hint_uses_named_install_that_creates_a_valid_project(self):
        case = self.root / "stray-registry"
        a, b = case / "a", case / "b"
        self.published(case / "a-source", a, "lib", payload="old")
        self.published(case / "b-source", b, "lib", payload="changed")
        self.published(case / "b-source", b, "newpkg", depends={"lib": "^0.1"})
        manager = self.manager(case, a)
        manager.install(["lib@^0.1"], log=self.quiet)
        target = state.Project(manager.cwd)
        target.write_lock([manager.user().packages["lib"]])
        selected = self.manager(case, b)
        self.assertIsNone(selected.project())
        command = "harness install --project lib"
        with self.assertRaises(ResolveError) as failure:
            selected.install(["newpkg"], project=True, log=self.quiet)
        self.assertIn(command, str(failure.exception))
        self.assertNotIn("--update", str(failure.exception))
        self.recover(command, selected, b)
        selected.install(["newpkg"], project=True, log=self.quiet)
        self.assertEqual(selected.project().locked()["lib"].source, f"registry:{b}")
        self.assertEqual(selected.user().packages["lib"].range, "^0.1")

    def test_new_provider_automatic_install_protects_existing_shared_registry_dependencies(self):
        for cached in (False, True):
            with self.subTest(cached=cached):
                case = self.root / f"new-provider-{cached}"
                a, mirror = case / "a", case / "mirror"
                self.published(case / "a-source", a, "lib", "0.1.1", payload="original")
                self.published(case / "a-source", a, "other", depends={"lib": "^0.1"})
                manager = self.manager(case, a)
                manager.install(["other@^0.1"], log=self.quiet)
                user = manager.user()
                user.packages["lib"].range = "^0.1"
                user.write()
                if not cached:
                    self.cache("lib", user.packages["lib"]).rename(case / "detached-lib")
                self.published(case / "mirror-source", mirror, "lib", payload="older")
                widget = make_package(case / "mirror-source", "widget", depends={"lib": "^0.1"}, skills=["probe"])
                publish(mirror, widget, log=self.quiet)
                selected = self.manager(case, mirror)
                before = selected.user().path.read_bytes()
                stored = sorted(state.store_root().glob("*/*"))
                command = "harness install --update lib"
                with self.assertRaises(ResolveError) as failure:
                    selected.ensure("skills", "probe", log=self.quiet)
                self.assertIn(command, str(failure.exception))
                self.assertIn("then retry the original", str(failure.exception))
                self.assertNotIn("widget lib", str(failure.exception))
                self.assertEqual(selected.user().path.read_bytes(), before)
                self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                self.recover(command, selected, mirror)
                self.assertEqual(selected.user().packages["lib"].range, "^0.1")
                self.assertEqual(selected.ensure("skills", "probe", log=self.quiet).name, "widget")
                self.assertEqual(selected.user().packages["other"].source, f"registry:{a}")
