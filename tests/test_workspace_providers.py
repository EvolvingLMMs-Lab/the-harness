"""New package kinds route through the host without a built-in backend branch."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import harness
from harness.host.workspaces import Workspaces, WorkspaceProvider
from harness.runtime.execution import skills
from harness.runtime.execution.skills import SKILLS_ROOT
from harness.settings import Settings
from harness.host.tasks import TaskHost
from harness_workspace.host import Workspaces as Projects


class Lab(WorkspaceProvider):
    def __init__(self, directory, settings):
        self.leases = {}; self.closed = False
    def kinds(self): return ("lab",)
    def kind(self, requested=None, text=None): return "lab"
    def accepts(self, binding): return "instrument" in binding
    def bench(self, kind): return "lab-bench"
    def bind(self, kind, directory, request, parent=None):
        return {"instrument": request["instrument"]}, {"instrument": request["instrument"]}
    def tree(self, tree, kind): return {**tree, "bench": self.bench(kind)}
    def acquire(self, run, kind, **waiting):
        worker = SimpleNamespace(run=run, options=waiting["options"])
        self.leases[run] = worker
        return worker
    def of(self, run): return self.leases.get(run)
    def release(self, run): del self.leases[run]
    def close(self): self.closed = True


class ProviderTests(unittest.TestCase):
    def test_third_package_selects_binds_and_releases_without_builtin_backend(self):
        module = SimpleNamespace(Workspaces=Lab)
        with tempfile.TemporaryDirectory() as directory, patch("harness.extensions.hosts", return_value=[
                (SimpleNamespace(name="laboratory"), module)]):
            host = Workspaces(directory, None)
            kind = host.kind(binding={"instrument": "spectrometer"})
            options, metadata = host.bind(kind, directory, {"instrument": "spectrometer"})
            self.assertEqual(host.tree({}, kind), {"bench": "lab-bench"})
            worker = host.acquire("task", kind, options=options)
            self.assertIs(host.of("task"), worker)
            self.assertEqual(metadata, {"instrument": "spectrometer"})
            host.release("task")
            self.assertIsNone(host.of("task"))
            provider = host.provider(kind)
            host.close()
            self.assertTrue(provider.closed)

    def test_duplicate_kind_is_rejected_before_allocating_any_worker(self):
        providers = [(SimpleNamespace(name=name), SimpleNamespace(Workspaces=Lab)) for name in ("a", "b")]
        with patch("harness.extensions.hosts", return_value=providers):
            with self.assertRaisesRegex(ValueError, "multiple packages"):
                Workspaces(".", None).kind("lab")

    def test_common_skills_support_a_new_kind_without_core_manifest_edits(self):
        kinds = {**dict(skills.KINDS), "lab": None}
        with patch.object(skills, "KINDS", kinds):
            for name in ("entries", "checklist", "memory", "instructions", "agents", "mcp"):
                self.assertIn("lab", skills._skill(SKILLS_ROOT / name / "skill.toml").embodiments)
            selected = skills.resolve(["entries", "checklist"], set(), embodiment="lab", strict=True)
            self.assertIn("entries", selected.enabled)
            self.assertIn("checklist", selected.enabled)

    def test_universal_skill_keeps_optional_interfaces_for_absent_packages(self):
        with patch.object(skills, "KINDS", {"lab": None}):
            memory = skills._skill(SKILLS_ROOT / "memory/skill.toml")
            self.assertEqual(memory.embodiments, ("lab",))
            self.assertEqual(memory.for_embodiment("lab").mixin, memory.mixin)

    def test_project_provider_owns_root_validation_and_child_inheritance(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(Path(directory) / "data")
            provider = Projects(directory, settings)
            options, metadata = provider.bind("project", Path(directory) / "first", {"folder": directory})
            parent = SimpleNamespace(workspace_kind="project", workspace_options=options, parent=None)
            child, info = provider.bind("project", Path(directory) / "child", {}, parent)
            self.assertEqual(child["folder"], options["folder"])
            self.assertNotEqual(child["artifacts"], options["artifacts"])
            self.assertEqual(info, metadata)
            with self.assertRaisesRegex(ValueError, "explicitly bound"):
                provider.bind("project", directory, {})
            provider.close()

    def test_two_packages_build_only_their_own_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            app = TaskHost(directory)
            try:
                values = app.settings.get()
                project = app.conversation_tree(values, "project")
                computer = app.conversation_tree(values, "desktop")
                self.assertEqual(project["bench"], "workspace")
                self.assertEqual(set(project["overrides"]["agent"]["prompt"]), {"workspace"})
                self.assertNotIn("desktop", project["overrides"]["agent"])
                self.assertEqual(computer["bench"], "computer")
                self.assertEqual(set(computer["overrides"]["agent"]["prompt"]), {"desktop"})
                self.assertEqual(app.workspaces.kind(binding={"folder": directory}), "project")
                self.assertIn("computer", app.status())
            finally:
                app.close()
