"""Offline regressions for package ownership, compatible updates and release contracts."""
from pathlib import Path
import os
import shutil
import stat
from unittest import mock

from test_packages import Temporary, make_package, ROOT
from harness.packages import manifest, state
from harness.packages.manager import PackageBusy, Packages
from harness.packages.registry import Registry, RegistryError, publish
from harness.packages.resolve import ResolveError


class PackageRecoveryTests(Temporary):
    def fresh(self, cwd=None):
        return Packages(self.data, cwd=cwd or self.work, registry=Registry(str(self.registry_dir)))

    def test_cache_cleanup_refuses_working_directory_ancestors_home_and_root(self):
        for folder in (Path(""), Path.cwd().parent, Path.home(), Path(Path.cwd().anchor)):
            with self.subTest(folder=str(folder)), mock.patch("harness.packages.state.shutil.rmtree") as remove:
                with self.assertRaisesRegex(ValueError, "refusing"):
                    state.delete(folder)
                remove.assert_not_called()

    def test_cache_cleanup_can_remove_an_owned_read_only_version(self):
        folder = self.root / "owned-cache-version"
        folder.mkdir()
        payload = folder / "package.toml"
        payload.write_text("owned test data")
        payload.chmod(stat.S_IREAD)
        state.delete(folder)
        self.assertFalse(folder.exists())

    def test_cache_cleanup_without_a_home_keeps_working_directory_protection(self):
        folder = self.root / "cache-without-home"
        folder.mkdir()
        self.assertTrue(folder.resolve().is_relative_to(self.root.resolve()))
        with mock.patch("harness.packages.state.Path.home", side_effect=RuntimeError("no passwd entry")):
            with self.subTest(target="working-directory"), mock.patch("harness.packages.state.shutil.rmtree") as remove:
                with self.assertRaisesRegex(ValueError, "refusing"):
                    state.delete(Path(""))
                remove.assert_not_called()
            with self.subTest(target="owned-cache"):
                state.delete(folder)
                self.assertFalse(folder.exists())

    def test_unrelated_remove_preserves_other_project_and_unknown_cache(self):
        self.publish("project-only")
        self.publish("user-only")
        project = self.root / "project-a"
        project.mkdir()
        manager = self.fresh(project)
        manager.install(["project-only"], project=True, log=self.quiet)
        project_path = Path(manager.installed()[0]["path"])
        unknown = state.store_root() / "unknown" / "0.1.0-untracked"
        unknown.mkdir(parents=True)
        (unknown / "user-data").write_text("keep")
        other = self.fresh()
        other.install(["user-only"], log=self.quiet)
        removed = Path(other.installed()[0]["path"])
        other.remove(["user-only"], log=self.quiet)
        self.assertTrue((project_path / "package.toml").is_file())
        self.assertNotIn("problem", manager.installed()[0])
        self.assertEqual((unknown / "user-data").read_text(), "keep")
        self.assertTrue(removed.exists())

    def test_shared_home_across_data_directories_retains_other_users_package(self):
        self.publish("shared")
        other = Packages(self.root / "other-data", cwd=self.work,
                         registry=Registry(str(self.registry_dir)))
        for project in (False, True):
            with self.subTest(other_owner_project=project):
                project_root = self.root / f"owner-{project}"
                project_root.mkdir()
                owner = self.fresh(project_root)
                owner.install(["shared"], project=project, log=self.quiet)
                path = Path(owner.installed()[0]["path"])
                other.install(["shared"], log=self.quiet)
                self.assertEqual(Path(other.installed()[0]["path"]), path)
                other.remove(["shared"], log=self.quiet)
                self.assertTrue((path / "package.toml").is_file())
                self.assertNotIn("problem", owner.installed()[0])
                owner.remove(["shared"], project=project, log=self.quiet)

    def test_removed_project_package_shared_by_another_project_is_kept(self):
        self.publish("shared")
        managers = []
        for name in ("one", "two"):
            project = self.root / name
            project.mkdir()
            manager = self.fresh(project)
            manager.install(["shared"], project=True, log=self.quiet)
            managers.append(manager)
        managers[0].remove(["shared"], project=True, log=self.quiet)
        self.assertNotIn("problem", managers[1].installed()[0])
        path = Path(managers[1].installed()[0]["path"])
        managers[1].remove(["shared"], project=True, log=self.quiet)
        self.assertTrue(path.exists())

    def test_removal_keeps_cache_with_unreadable_lock_and_link_sources_survive(self):
        self.publish("kit")
        project = self.root / "project"
        project.mkdir()
        manager = self.fresh(project)
        manager.install(["kit"], project=True, log=self.quiet)
        (project / "harness.lock").write_text("broken [")
        other = self.fresh()
        other.install(["kit"], log=self.quiet)
        cached = Path(other.installed()[0]["path"])
        logs = []
        other.remove(["kit"], log=logs.append)
        self.assertTrue(cached.exists())
        self.assertEqual(logs, [])
        folder = make_package(self.root / "linked", "local")
        other.install([str(folder)], link=True, consent=lambda _: True, log=self.quiet)
        other.remove(["local"], log=self.quiet)
        self.assertTrue((folder / "package.toml").exists())

    def test_update_selects_highest_compatible_and_preserves_user_range(self):
        self.publish("kit", "0.1.0")
        self.fresh().install(["kit@>=0.1,<1"], log=self.quiet)
        self.publish("kit", "0.2.0")
        self.publish("kit", "0.3.0", harness=">=99")
        manager = self.fresh()
        manager.update(log=self.quiet)
        self.assertEqual(manager.user().packages["kit"].version, "0.2.0")
        self.assertEqual(manager.user().packages["kit"].range, ">=0.1,<1")
        self.assertEqual(manager.update(log=self.quiet)["installed"], [])

    def test_persistent_manager_update_refreshes_versions_and_selects_compatible_release(self):
        self.publish("kit", "0.1.0")
        manager = self.fresh()
        manager.install(["kit@>=0.1,<1"], log=self.quiet)
        self.publish("kit", "0.2.0")
        self.publish("kit", "0.3.0", harness=">=99")
        manager.update(log=self.quiet)
        self.assertEqual(manager.user().packages["kit"].version, "0.2.0")
        self.assertEqual(manager.user().packages["kit"].range, ">=0.1,<1")
        self.publish("kit", "0.2.1")
        manager.update(log=self.quiet)
        self.assertEqual(manager.user().packages["kit"].version, "0.2.1")

    def test_implicit_project_install_refuses_changed_declarations_after_consent_wait(self):
        import concurrent.futures
        import threading

        self.publish("kit", "0.1.0")
        self.publish("kit", "0.2.0")
        self.publish("editor-extra")
        folder = make_package(self.root / "source", "local")
        project_dir = self.root / "project"
        project_dir.mkdir()
        project = state.Project(project_dir)
        project.set_wanted({"kit": {"range": "^0.1", "source": ""},
                            "local": {"range": "", "source": str(folder)}})
        entered, release = threading.Event(), threading.Event()
        def consent(found):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test did not release package consent")
            return True
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            install = pool.submit(self.fresh(project_dir).install, project=True,
                                  consent=consent, log=self.quiet)
            try:
                self.assertTrue(entered.wait(5))
                # An editor changes a range, then another real package operation
                # adds a declaration and lock while the first consent is paused.
                wanted = project.wanted()
                wanted["kit"]["range"] = "^0.2"
                project.set_wanted(wanted)
                self.fresh(project_dir).install(["editor-extra"], project=True, log=self.quiet)
                manifest_before, lock_before = project.file.read_bytes(), project.lock_file.read_bytes()
                installed_before = sorted(path for path in state.store_root().glob("*/*"))
            finally:
                release.set()
            with self.assertRaisesRegex(ResolveError, "changed.*harness install --project"):
                install.result(timeout=5)
        self.assertEqual(project.file.read_bytes(), manifest_before)
        self.assertEqual(project.lock_file.read_bytes(), lock_before)
        self.assertEqual(project.wanted()["kit"]["range"], "^0.2")
        self.assertEqual(sorted(path for path in state.store_root().glob("*/*")), installed_before)
        self.assertEqual(set(project.locked()), {"editor-extra"})

    def test_project_update_keeps_range_source_and_allows_next_update(self):
        self.publish("kit")
        project = self.root / "project"
        project.mkdir()
        source = make_package(self.root / "source", "local")
        manager = self.fresh(project)
        manager.install(["kit@^0.1", str(source)], project=True, consent=lambda _: True, log=self.quiet)
        wanted = state.Project(project).wanted()
        self.publish("kit", "0.1.1")
        self.fresh(project).update(project=True, log=self.quiet)
        self.assertEqual(state.Project(project).wanted(), wanted)
        self.publish("kit", "0.1.2")
        self.fresh(project).update(project=True, log=self.quiet)
        self.assertEqual(state.Project(project).locked()["kit"].version, "0.1.2")
        self.assertEqual(state.Project(project).wanted(), wanted)

    def test_project_update_outside_project_never_updates_user_packages(self):
        self.publish("kit", "0.2.0")
        manager = self.fresh()
        manager.install(["kit@>=0.1,<1"], log=self.quiet)
        self.publish("kit", "1.0.0")
        before = manager.user().packages["kit"]
        with self.assertRaisesRegex(ValueError, "no harness.toml"):
            manager.update(project=True, log=self.quiet)
        after = manager.user().packages["kit"]
        self.assertEqual((after.version, after.range, after.path), (before.version, before.range, before.path))
        self.assertFalse((self.work / "harness.toml").exists())

    def test_install_from_project_manifest_preserves_authored_sources_and_ranges(self):
        folder = make_package(self.root / "source", "local")
        for index, source in enumerate((f"path:{folder}", "git:https://example.invalid/local@v0.1",
                                        "url:https://example.invalid/local.tar.gz")):
            with self.subTest(source=source):
                project = self.root / f"source-project-{index}"
                project.mkdir()
                target = state.Project(project)
                target.set_wanted({"local": {"source": source, "range": "^0.1"}})
                before = target.file.read_bytes()
                origin = f"path:{folder}" if source.startswith("path:") else (
                    "git:https://example.invalid/local@abc123" if source.startswith("git:") else source + "#sha256=abc123")
                with mock.patch("harness.packages.manager.sources.fetch", return_value=(folder, origin)):
                    self.fresh(project).install(project=True, consent=lambda _: True, log=self.quiet)
                self.assertEqual(target.locked()["local"].version, "0.1.0")
                self.assertEqual(target.locked()["local"].source, origin)
                self.assertEqual(target.file.read_bytes(), before)

    def test_project_local_source_stays_local_and_uses_project_root_from_subdirectory(self):
        self.publish("vendored", "9.0.0")
        source = make_package(self.root / "source", "vendored", "0.1.0")
        for index, declaration in enumerate(("path:vendored", "./vendored", "vendored/")):
            with self.subTest(declaration=declaration):
                project = self.root / f"local-project-{index}"
                (project / "sub").mkdir(parents=True)
                shutil.copytree(source, project / "vendored")
                target = state.Project(project)
                target.set_wanted({"vendored": {"source": declaration, "range": "^0.1"}})
                before = target.file.read_bytes()
                consent = mock.Mock(return_value=True)
                self.fresh(project / "sub").install(project=True, consent=consent, log=self.quiet)
                consent.assert_called_once()
                self.assertEqual(target.locked()["vendored"].version, "0.1.0")
                self.assertEqual(target.locked()["vendored"].source, f"path:{(project / 'vendored').resolve()}")
                self.assertEqual(target.file.read_bytes(), before)

    def test_install_from_manifest_checks_the_authored_local_version_range(self):
        folder = make_package(self.root / "source", "local", "0.2.0")
        project = self.root / "source-range-project"
        project.mkdir()
        target = state.Project(project)
        target.set_wanted({"local": {"source": str(folder), "range": "^0.1"}})
        before = target.file.read_bytes()
        with self.assertRaisesRegex(ResolveError, "recorded range"):
            self.fresh(project).install(project=True, consent=lambda _: True, log=self.quiet)
        self.assertEqual(target.file.read_bytes(), before)
        self.assertFalse(target.lock_file.exists())

    def test_resolved_dependencies_cannot_cross_a_retained_recorded_range(self):
        self.publish("dep", "0.1.0")
        self.publish("dep", "0.2.0")
        self.publish("parent", depends={"dep": "^0.1"})
        self.publish("new-top", depends={"dep": ">=0.1"})
        legacy = Packages(self.root / "legacy-data", cwd=self.work, registry=Registry(str(self.registry_dir)))
        legacy.install(["parent"], log=self.quiet)
        parent_record = legacy.user().packages["parent"]
        for project in (False, True):
            with self.subTest(project=project):
                cwd = self.root / f"retained-range-{project}"
                cwd.mkdir()
                manager = Packages(self.root / f"range-data-{project}", cwd=cwd,
                                   registry=Registry(str(self.registry_dir)))
                manager.install(["dep@^0.2"], project=project, log=self.quiet)
                # Restore an inconsistent record set that an older resolver allowed.
                if project:
                    target = state.Project(cwd)
                    locked = target.locked()
                    locked["parent"] = parent_record
                    target.write_lock(locked.values())
                    before = target.lock_file.read_bytes()
                else:
                    user = manager.user()
                    user.packages["parent"] = parent_record
                    user.write()
                    before = user.path.read_bytes()
                with self.assertRaisesRegex(ResolveError, "recorded range"):
                    manager.install(["new-top"], project=project, log=self.quiet)
                records = target.locked() if project else manager.user().packages
                recorded_range = target.wanted()["dep"]["range"] if project else records["dep"].range
                self.assertEqual((records["dep"].version, recorded_range), ("0.2.0", "^0.2"))
                self.assertNotIn("new-top", records)
                self.assertEqual((target.lock_file if project else manager.user().path).read_bytes(), before)

    def test_explicit_unranged_or_local_replacement_does_not_keep_an_obsolete_range(self):
        self.publish("dep", "0.1.0")
        self.publish("dep", "0.2.0")
        replacement = make_package(self.root / "replacement", "dep", "0.2.0")
        for local in (False, True):
            with self.subTest(local=local):
                manager = Packages(self.root / f"explicit-data-{local}", cwd=self.work,
                                   registry=Registry(str(self.registry_dir)))
                manager.install(["dep@^0.1"], log=self.quiet)
                manager.install([str(replacement) if local else "dep"], consent=lambda _: True, log=self.quiet)
                self.assertEqual((manager.user().packages["dep"].version, manager.user().packages["dep"].range),
                                 ("0.2.0", ""))

    def test_obsolete_project_lock_conflict_names_explicit_removal_recovery(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        project = self.root / "obsolete-project"
        project.mkdir()
        manager = self.fresh(project)
        manager.install(["parent"], project=True, log=self.quiet)
        target = state.Project(project)
        target.set_wanted({"dep": {"range": "^0.2", "source": ""}})
        before = target.lock_file.read_bytes()
        self.publish("dep", "0.2.0")
        manager.registry.index(refresh=True)
        with self.assertRaisesRegex(ResolveError, "harness remove --project"):
            manager.install(project=True, log=self.quiet)
        self.assertEqual(target.lock_file.read_bytes(), before)
        manager.remove(["parent"], project=True, log=self.quiet)
        manager.install(project=True, log=self.quiet)
        self.assertEqual(target.locked()["dep"].version, "0.2.0")

    def test_manifest_install_keeps_compatible_registry_lock_until_explicit_update(self):
        self.publish("kit", "0.1.0")
        project = self.root / "locked-project"
        project.mkdir()
        manager = self.fresh(project)
        manager.install(["kit@^0.1"], project=True, log=self.quiet)
        self.publish("kit", "0.1.1")
        manager.registry.index(refresh=True)
        with mock.patch.object(manager.registry, "versions", wraps=manager.registry.versions) as versions:
            manager.install(project=True, log=self.quiet)
        self.assertEqual(state.Project(project).locked()["kit"].version, "0.1.0")
        versions.assert_not_called()
        manager.update(project=True, log=self.quiet)
        self.assertEqual(state.Project(project).locked()["kit"].version, "0.1.1")

    def test_old_browser_and_computer_recover_with_the_suggested_joint_upgrade(self):
        self.publish("computer", "0.7.3")
        self.publish("browser", "0.5.1", depends={"computer": "^0.7"})
        manager = self.fresh()
        with mock.patch("harness.packages.manager.harness_version", return_value="0.81.1"):
            manager.install(["browser"], log=self.quiet)
        manager.enabled()
        self.assertIn("harness install computer@^0.8 browser", manager.problems["computer"])
        self.publish("computer", "0.8.0")
        self.publish("browser", "0.5.2", depends={"computer": "^0.8"})
        manager = self.fresh()
        manager.install(["computer@^0.8", "browser"], log=self.quiet)
        self.assertEqual(manager.user().packages["computer"].version, "0.8.0")
        self.assertEqual(manager.user().packages["browser"].version, "0.5.2")

    def test_project_update_changes_lock_without_declaring_indirect_dependencies(self):
        self.publish("dependency", "0.1.0")
        self.publish("entry", "0.1.0", depends={"dependency": "^0.1"})
        project = self.root / "project"
        project.mkdir()
        manager = self.fresh(project)
        manager.install(["entry@^0.1"], project=True, log=self.quiet)
        manifest_before = (project / "harness.toml").read_bytes()
        self.publish("dependency", "0.1.1")
        manager.update(project=True, log=self.quiet)
        self.assertEqual(state.Project(project).locked()["dependency"].version, "0.1.1")
        self.assertEqual((project / "harness.toml").read_bytes(), manifest_before)
        self.publish("dependency", "0.1.2")
        manager.update(["dependency"], project=True, log=self.quiet)
        self.assertEqual(state.Project(project).locked()["dependency"].version, "0.1.2")
        self.assertEqual((project / "harness.toml").read_bytes(), manifest_before)
        manager.remove(["entry"], project=True, log=self.quiet)
        self.assertEqual(state.Project(project).wanted(), {})

    def test_incompatible_update_has_no_partial_changes(self):
        self.publish("kit")
        manager = self.fresh()
        manager.install(["kit"], log=self.quiet)
        self.publish("kit", "0.2.0", harness=">=99")
        self.assertEqual(self.fresh().update(log=self.quiet)["installed"], [])
        self.assertEqual(manager.user().packages["kit"].version, "0.1.0")

    def test_browser_dependency_keeps_current_computer_and_refuses_old_archive(self):
        browser = manifest.load(ROOT / "packages/browser")
        self.publish("computer", "0.7.3")
        self.publish("computer", "0.8.0")
        manager = self.fresh()
        manager.install(["computer@^0.8"], log=self.quiet)
        manager.install([str(browser.path)], consent=lambda _: True, log=self.quiet)
        self.assertEqual(manager.user().packages["computer"].version, "0.8.0")
        old = make_package(self.root / "old", "browser", "0.5.0", depends={"computer": "^0.7"})
        with self.assertRaisesRegex(ResolveError, "incompatible.*harness install computer"):
            manager.install([str(old)], consent=lambda _: True, log=self.quiet)
        self.assertEqual(manager.user().packages["computer"].version, "0.8.0")

    def test_legacy_computer_is_refused_when_core_is_upgraded(self):
        self.publish("computer", "0.7.3")
        manager = self.fresh()
        with mock.patch("harness.packages.manager.harness_version", return_value="0.81.1"):
            manager.install(["computer"], log=self.quiet)
            self.assertEqual(len(manager.enabled()), 1)
        self.assertEqual(manager.enabled(), [])
        self.assertIn("harness install computer@^0.8", manager.problems["computer"])
        with self.assertRaisesRegex(ResolveError, "incompatible"):
            self.fresh().install(["computer"], log=self.quiet)

    def test_current_package_manifests_refuse_cores_without_required_apis(self):
        for name in ("computer", "external-agents", "browser"):
            package = manifest.load(ROOT / "packages" / name)
            with self.subTest(package=name), mock.patch("harness.packages.manager.harness_version", return_value="0.81.1"):
                with self.assertRaisesRegex(ResolveError, "works with harness"):
                    self.fresh().install([str(package.path)], consent=lambda _: True, log=self.quiet)

    def test_published_versions_are_immutable_and_store_files_stay_read_only(self):
        folder = self.publish("kit")
        manager = self.fresh()
        manager.install(["kit"], log=self.quiet)
        installed = Path(manager.installed()[0]["path"]) / "package.toml"
        self.assertFalse(installed.stat().st_mode & stat.S_IWUSR)
        (folder / "README.md").write_text("changed")
        with self.assertRaises(RegistryError):
            publish(self.registry_dir, folder, log=self.quiet)
        self.assertEqual(installed.read_text(), (folder / "package.toml").read_text())


class ConcurrentPackageRecoveryTests(Temporary):
    def test_nonlegacy_activation_and_reads_do_not_wait_for_unrelated_install(self):
        import concurrent.futures
        import threading
        from harness.packages.manager import activate

        for migrated in (False, True):
            with self.subTest(existing_migrated_addons=migrated):
                if migrated:
                    (self.data / "addons").mkdir(parents=True)
                    user = self.packages().user()
                    user.migrated = True
                    user.write()
                folder = make_package(self.root / "source", f"slow-{str(migrated).lower()}")
                installer, reader = self.packages(), self.packages()
                entered, release, read_done = threading.Event(), threading.Event(), threading.Event()
                def requirements(path, python, log):
                    entered.set()
                    if not release.wait(10):
                        raise RuntimeError("test did not release slow package preparation")
                def read():
                    activate(reader)
                    installed = reader.installed()
                    read_done.set()
                    return installed
                with mock.patch.object(Packages, "_requirements", side_effect=requirements), \
                        concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    install = pool.submit(installer.install, [str(folder)], consent=lambda _: True, log=self.quiet)
                    try:
                        self.assertTrue(entered.wait(5))
                        result = pool.submit(read)
                        # Completion must happen while the installer is explicitly
                        # held, not after a short polling/timing assumption.
                        self.assertTrue(read_done.wait(5), "ordinary activation waited on unrelated install")
                        self.assertFalse(release.is_set())
                        self.assertNotIn(f"slow-{str(migrated).lower()}", {row["name"] for row in result.result(timeout=5)})
                    finally:
                        release.set()
                    install.result(timeout=5)

    def test_busy_install_is_not_queued_and_explicit_retry_reuses_complete_dependencies(self):
        import concurrent.futures
        import threading

        folder = make_package(self.root / "source", "shared", skills=["tool"])
        extra = make_package(self.root / "source", "extra")
        entered, release = threading.Event(), threading.Event()
        calls = []
        first, second = self.packages(), self.packages()
        def requirements(path, python, log):
            if not (path / "skills/tool").is_dir():
                return
            calls.append(path)
            deps = path / "skills/tool/.deps"
            deps.mkdir()
            (deps / "partial").write_text("not ready")
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test did not release dependency preparation")
            (deps / "ready").write_text("complete")
            (deps / "partial").unlink()
        with mock.patch.object(Packages, "_requirements", side_effect=requirements), \
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first.install, [str(folder)], consent=lambda _: True, log=self.quiet)
            try:
                self.assertTrue(entered.wait(5))
                two = pool.submit(second.install, [str(folder), str(extra)], consent=lambda _: True, log=self.quiet)
                with self.assertRaisesRegex(PackageBusy, "not queued.*retry"):
                    two.result(timeout=5)
                self.assertFalse(release.is_set())
                self.assertEqual(first.user().packages, {})
            finally:
                release.set()
            one.result(timeout=5)
            self.assertEqual(set(first.user().packages), {"shared"})
            second.install([str(folder), str(extra)], consent=lambda _: True, log=self.quiet)
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(second.user().packages), {"shared", "extra"})
        path = Path(first.user().packages["shared"].path)
        self.assertEqual((path / "skills/tool/.deps/ready").read_text(), "complete")
        self.assertFalse((path / "skills/tool/.deps/partial").exists())
        self.assertEqual(list(path.parent.glob("*.partial")), [])
        self.assertNotIn("problem", second.installed()[0])

    def test_stalled_fetch_or_consent_does_not_hold_store_lock(self):
        import concurrent.futures
        import threading
        from harness.packages import sources

        for stage in ("fetch", "consent"):
            with self.subTest(stage=stage):
                folder = make_package(self.root / "source", f"outer-{stage}")
                self.publish(f"extra-{stage}")
                waiting, release = threading.Event(), threading.Event()
                fetch = sources.fetch
                def pause():
                    waiting.set()
                    if not release.wait(10):
                        raise RuntimeError("test did not release source preparation")
                def slow_fetch(*args, **kwargs):
                    if stage == "fetch":
                        pause()
                    return fetch(*args, **kwargs)
                def consent(found):
                    if stage == "consent":
                        pause()
                    return True
                with mock.patch.object(sources, "fetch", side_effect=slow_fetch), \
                        concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    one = pool.submit(self.packages().install, [str(folder)], consent=consent, log=self.quiet)
                    try:
                        self.assertTrue(waiting.wait(5))
                        two = pool.submit(self.packages().install, [f"extra-{stage}"], log=self.quiet)
                        two.result(timeout=5)
                        self.assertFalse(release.is_set())
                        self.assertIn(f"extra-{stage}", self.packages().user().packages)
                    finally:
                        release.set()
                    one.result(timeout=5)
                user = self.packages().user()
                self.assertIn(f"extra-{stage}", user.packages)
                self.assertIn(f"outer-{stage}", user.packages)

    def test_busy_enable_does_not_run_later_and_retry_preserves_removal(self):
        import concurrent.futures
        import threading

        self.publish("remove-me")
        self.publish("keep-me")
        self.packages().install(["remove-me", "keep-me"], log=self.quiet)
        first, second = self.packages(), self.packages()
        entered, release, second_called = threading.Event(), threading.Event(), threading.Event()
        read = first.user
        captured = False
        def slow_read():
            nonlocal captured
            user = read()
            if not captured:
                captured = True
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test did not release user-record mutation")
            return user
        def disable():
            second_called.set()
            second.enable("keep-me", False)
        with mock.patch.object(first, "user", side_effect=slow_read), \
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first.remove, ["remove-me"], log=self.quiet)
            try:
                self.assertTrue(entered.wait(5))
                two = pool.submit(disable)
                self.assertTrue(second_called.wait(5))
                with self.assertRaisesRegex(PackageBusy, "not queued"):
                    two.result(timeout=5)
            finally:
                release.set()
            one.result(timeout=5)
        self.assertTrue(self.packages().user().packages["keep-me"].enabled)
        second.enable("keep-me", False)
        user = self.packages().user()
        self.assertEqual(set(user.packages), {"keep-me"})
        self.assertFalse(user.packages["keep-me"].enabled)

    def test_change_callback_can_install_and_update_does_not_reacquire_its_lock(self):
        import concurrent.futures

        self.publish("kit")
        self.publish("extra")
        manager = self.packages()
        manager.install(["kit@^0.1"], log=self.quiet)
        self.publish("kit", "0.1.1")
        manager = self.packages()
        callbacks = []
        def changed():
            manager.on_change = None
            callbacks.append("updated")
            self.packages().install(["extra"], log=self.quiet)
        manager.on_change = changed
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(manager.update, log=self.quiet).result(timeout=5)
        self.assertEqual(callbacks, ["updated"])
        user = self.packages().user()
        self.assertEqual(user.packages["kit"].version, "0.1.1")
        self.assertIn("extra", user.packages)

    def test_consent_and_interpreter_callbacks_can_install_other_packages(self):
        import concurrent.futures
        import sys

        folder = make_package(self.root / "source", "outer", skills=["tool"])
        self.publish("consent-extra")
        self.publish("interpreter-extra")
        callbacks = []
        def consent(found):
            callbacks.append("consent")
            self.packages().install(["consent-extra"], log=self.quiet)
            return True
        def python():
            callbacks.append("python")
            self.packages().install(["interpreter-extra"], log=self.quiet)
            return sys.executable
        def requirements(path, interpreter, log):
            if (path / "skills/tool").is_dir():
                self.assertEqual(interpreter(), sys.executable)
                (path / "skills/tool/.deps").mkdir()
        with mock.patch.object(Packages, "_requirements", side_effect=requirements), \
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(self.packages().install, [str(folder)], consent=consent, python=python,
                        log=self.quiet).result(timeout=5)
        self.assertEqual(callbacks, ["consent", "python"])
        self.assertEqual(set(self.packages().user().packages), {"outer", "consent-extra", "interpreter-extra"})

    def test_busy_process_refuses_then_explicit_retry_reuses_cache_and_merges_records(self):
        import subprocess
        import sys
        import time

        folder = make_package(self.root / "source", "shared", skills=["tool"])
        extra = make_package(self.root / "source", "extra")
        control = self.root / "control"
        control.mkdir()
        script = self.root / "installer.py"
        script.write_text('''
import os
from pathlib import Path
import sys
import time
from harness.packages.manager import PackageBusy, Packages
from harness.packages.manifest import load
role, control, folder, extra = sys.argv[1:]
control = Path(control)
def wait(name):
    deadline = time.monotonic() + 10
    while not (control / name).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"timed out waiting for {name}")
        time.sleep(0.01)
class Manager(Packages):
    def _requirements(self, path, python, log):
        if load(path).name != "shared":
            return
        with (control / "calls").open("a") as out:
            out.write(role + "\\n")
        deps = path / "skills/tool/.deps"
        deps.mkdir()
        (deps / "partial").write_text("incomplete")
        if role == "first":
            (control / "entered").touch()
            wait("release")
        (deps / "ready").write_text("complete")
        (deps / "partial").unlink()
(control / f"{role}-called").touch()
try:
    Manager(cwd=control).install([folder] + ([extra] if role == "second" else []),
                                consent=lambda _: True, log=lambda _: None)
except PackageBusy as error:
    print(error)
    sys.exit(23)
''')
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        processes = []
        def start(role):
            process = subprocess.Popen([sys.executable, str(script), role, str(control), str(folder), str(extra)],
                                       env=env, cwd=self.work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(process)
            return process
        def wait_for(name):
            deadline = time.monotonic() + 5
            while not (control / name).exists():
                if time.monotonic() >= deadline:
                    self.fail(f"child did not write {name}")
                time.sleep(0.01)
        try:
            first = start("first")
            wait_for("entered")
            second = start("second")
            wait_for("second-called")
            # The second process refuses while the holder is still explicitly
            # paused. It cannot launch a queued install after a client timeout.
            stdout, stderr = second.communicate(timeout=5)
            self.assertEqual(second.returncode, 23, stdout + stderr)
            self.assertIn("not queued", stdout)
            self.assertFalse((control / "release").exists())
            (control / "release").touch()
            stdout, stderr = first.communicate(timeout=10)
            self.assertEqual(first.returncode, 0, stdout + stderr)
            self.assertEqual(set(self.packages().user().packages), {"shared"})
            retry = start("second")
            stdout, stderr = retry.communicate(timeout=10)
            self.assertEqual(retry.returncode, 0, stdout + stderr)
        finally:
            (control / "release").touch()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
        self.assertEqual((control / "calls").read_text().splitlines(), ["first"])
        user = self.packages().user()
        self.assertEqual(set(user.packages), {"shared", "extra"})
        cache = Path(user.packages["shared"].path)
        self.assertEqual((cache / "skills/tool/.deps/ready").read_text(), "complete")
        self.assertFalse((cache / "skills/tool/.deps/partial").exists())
        self.assertEqual(list(cache.parent.glob("*.partial")), [])
