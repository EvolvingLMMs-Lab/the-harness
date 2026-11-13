"""Keep installed dependents usable when resolving named dependency updates."""
from unittest import mock

from test_packages import Temporary, make_package
from harness import __version__
from harness.packages import state
from harness.packages.registry import Registry
from harness.packages.resolve import ResolveError, resolve


class InstalledDependencyRecoveryTests(Temporary):
    def manager(self, cwd=None):
        return self.packages(cwd=cwd or self.work, registry=Registry(str(self.registry_dir)))

    def test_named_dependency_update_respects_retained_user_and_project_parents(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        managers = []
        for project in (False, True):
            cwd = self.root / ("project" if project else "user")
            cwd.mkdir()
            manager = self.manager(cwd)
            manager.install(["parent"], project=project, log=self.quiet)
            managers.append((project, cwd, manager))
        self.publish("dep", "0.1.1")
        self.publish("dep", "0.2.0")
        for project, cwd, manager in managers:
            with self.subTest(project=project):
                wanted = state.Project(cwd).wanted() if project else None
                manager.update(["dep"], project=project, log=self.quiet)
                records = state.Project(cwd).locked() if project else manager.user().packages
                self.assertEqual(records["dep"].version, "0.1.1")
                self.assertEqual(records["parent"].version, "0.1.0")
                if project:
                    self.assertEqual(state.Project(cwd).wanted(), wanted)

    def test_explicit_incompatible_dependency_install_refuses_without_changing_records(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        manager = self.manager()
        manager.install(["parent"], log=self.quiet)
        self.publish("dep", "0.2.0")
        manager.registry.index(refresh=True)
        before = manager.user().path.read_bytes()
        with self.assertRaisesRegex(ResolveError, r"parent 0.1.0 needs dep \^0.1"):
            manager.install(["dep@^0.2"], log=self.quiet)
        self.assertEqual(manager.user().path.read_bytes(), before)
        self.assertEqual(manager.user().packages["dep"].version, "0.1.0")

    def test_local_dependency_override_refuses_retained_user_and_project_parent_conflicts(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        replacement = make_package(self.root / "replacement", "dep", "0.2.0")
        for project in (False, True):
            with self.subTest(project=project):
                cwd = self.root / ("project" if project else "user")
                cwd.mkdir()
                manager = self.manager(cwd)
                manager.install(["parent"], project=project, log=self.quiet)
                files = [state.Project(cwd).file, state.Project(cwd).lock_file] if project else [manager.user().path]
                before = {path: path.read_bytes() for path in files}
                stored = sorted(state.store_root().glob("*/*"))
                with self.assertRaisesRegex(ResolveError, r"parent 0.1.0 needs dep \^0.1"):
                    manager.install([str(replacement)], project=project, consent=lambda _: True, log=self.quiet)
                self.assertEqual({path: path.read_bytes() for path in files}, before)
                self.assertEqual(sorted(state.store_root().glob("*/*")), stored)
                records = state.Project(cwd).locked() if project else manager.user().packages
                self.assertEqual(records["dep"].version, "0.1.0")

    def test_joint_local_parent_and_dependency_replacement_accepts_compatible_fixed_versions(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        parent = make_package(self.root / "replacement", "parent", "0.2.0", depends={"dep": "^0.2"})
        dep = make_package(self.root / "replacement", "dep", "0.2.0")
        for project in (False, True):
            with self.subTest(project=project):
                cwd = self.root / ("project" if project else "user")
                cwd.mkdir()
                manager = self.manager(cwd)
                manager.install(["parent"], project=project, log=self.quiet)
                manager.install([str(parent), str(dep)], project=project, consent=lambda _: True, log=self.quiet)
                records = state.Project(cwd).locked() if project else manager.user().packages
                self.assertEqual({name: row.version for name, row in records.items()},
                                 {"dep": "0.2.0", "parent": "0.2.0"})
                self.assertTrue(all(row.source.startswith("path:") for row in records.values()))

    def test_joint_parent_and_dependency_update_uses_new_parent_constraints(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        manager = self.manager()
        manager.install(["parent"], log=self.quiet)
        self.publish("dep", "0.2.0")
        self.publish("parent", "0.2.0", depends={"dep": "^0.2"})
        manager.update(["dep", "parent"], log=self.quiet)
        self.assertEqual({name: row.version for name, row in manager.user().packages.items()},
                         {"dep": "0.2.0", "parent": "0.2.0"})

    def test_local_parent_replacement_drops_old_installed_dependency_constraints(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        manager = self.manager()
        manager.install(["parent"], log=self.quiet)
        self.publish("dep", "0.2.0")
        manager.registry.index(refresh=True)
        replacement = make_package(self.root / "replacement", "parent", "0.2.0", depends={"dep": "^0.2"})
        manager.install([str(replacement)], consent=lambda _: True, log=self.quiet)
        self.assertEqual(manager.user().packages["dep"].version, "0.2.0")
        self.assertEqual(manager.user().packages["parent"].version, "0.2.0")
        self.assertTrue(manager.user().packages["parent"].source.startswith("path:"))

    def test_transitively_replaced_parent_does_not_leave_old_constraints(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        manager = self.manager()
        manager.install(["parent"], log=self.quiet)
        self.publish("dep", "0.2.0")
        self.publish("parent", "0.2.0", depends={"dep": "^0.2"})
        self.publish("new-top", depends={"parent": "^0.2"})
        manager.registry.index(refresh=True)
        manager.install(["dep@^0.2", "new-top"], log=self.quiet)
        self.assertEqual(manager.user().packages["dep"].version, "0.2.0")
        self.assertEqual(manager.user().packages["parent"].version, "0.2.0")

    def test_new_transitive_dependency_respects_another_retained_parent(self):
        self.publish("dep", "0.1.0")
        self.publish("parent", depends={"dep": "^0.1"})
        manager = self.manager()
        manager.install(["parent"], log=self.quiet)
        self.publish("dep", "0.2.0")
        self.publish("new-top", depends={"dep": "^0.2"})
        manager.registry.index(refresh=True)
        with self.assertRaisesRegex(ResolveError, "parent 0.1.0 needs dep"):
            manager.install(["new-top"], log=self.quiet)
        self.assertNotIn("new-top", manager.user().packages)
        self.assertEqual(manager.user().packages["dep"].version, "0.1.0")

    def test_unrelated_retained_dependencies_are_not_added_or_fetched(self):
        self.publish("dep", "0.2.0")
        registry = Registry(str(self.registry_dir))
        def installed_depends(name, version):
            return {"missing-unrelated": "^1"} if name == "background" else None
        with mock.patch.object(registry, "versions", wraps=registry.versions) as versions:
            plan = resolve({"dep": ""}, registry, harness=__version__,
                           have={"background": "0.1.0", "unknown-retained": "0.1.0"},
                           depends_of=installed_depends)
        self.assertEqual(plan, {"dep": "0.2.0"})
        self.assertNotIn(mock.call("missing-unrelated"), versions.call_args_list)
        self.assertNotIn(mock.call("unknown-retained"), versions.call_args_list)

    def test_unknown_explicit_or_transitive_dependency_still_errors(self):
        self.publish("new-top", depends={"missing": "^0.1"})
        registry = Registry(str(self.registry_dir))
        for requests in ({"missing": ""}, {"new-top": ""}):
            with self.subTest(requests=requests), self.assertRaisesRegex(ResolveError, "no package missing"):
                resolve(requests, registry, harness=__version__, have={"unknown-retained": "0.1.0"})

    def test_registry_selection_gate_preserves_actual_retained_parent_constraints(self):
        self.publish("dep", "0.2.0")
        self.publish("parent", depends={"dep": "^0.2"})
        registry = Registry(str(self.registry_dir))
        def actual_installed(name, version):
            return {"dep": "^0.1"} if name == "parent" else None
        with self.assertRaisesRegex(ResolveError, r"parent 0.1.0 needs dep \^0.1"):
            resolve({"dep": "^0.2"}, registry, harness=__version__, have={"parent": "0.1.0"},
                    depends_of=actual_installed, use_installed=lambda name, version: False)
