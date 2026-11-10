"""Change notes and versions (tools/changes.py): a pull request changes no version, a code
change comes with a note, and a release gathers the notes into versions and changelogs."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import changes  # noqa: E402

FILES = {
    "src/harness/__init__.py": '__version__ = "0.81.2"\n',
    "src/harness/cost.py": "SHOWN = True\n",
    "docs/src/content/docs/changelog.md": "---\ntitle: Changelog\n---\n\nIntro.\n\n## 0.81.2\n\n- Old.\n",
    "docs/src/content/docs/zh-cn/changelog.md": "---\ntitle: 变更记录\n---\n\n简介。\n\n## 0.81.2\n\n- 旧。\n",
    "docs/src/content/docs/guide.md": "A guide.\n",
    "packages/computer/package.toml": '[package]\nname = "computer"\nversion = "0.7.3"\nharness = ">=0.81.1,<2"\n',
    "packages/computer/CHANGELOG.md": "# Changelog\n\n## 0.7.3\n\n- Old.\n",
    "packages/computer/harness_computer/host.py": "X = 1\n",
    "packages/computer/tests/test_host.py": "X = 1\n",
    "private/packages/app/package.toml": '[package]\nname = "app"\nversion = "0.9.2"\nharness = ">=0.81,<2"\n',
    "private/packages/app/CHANGELOG.md": "# Changelog\n\n## 0.9.2\n\n- Old.\n",
    "changes/README.md": "How to write a change note.\n",
}


def note(levels: str, text: str = "Something changed.", zh: str = "") -> str:
    return f"---\n{levels}\n---\n{text}\n" + (f"<!-- zh -->\n{zh}\n" if zh else "")


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="harness-notes-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for path, text in FILES.items():
            self.write(path, text)
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        self.commit("base")
        self.git("checkout", "-q", "-b", "change")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def write(self, path, text):
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text, encoding="utf-8", newline="\n")

    def read(self, path):
        return (self.root / path).read_text(encoding="utf-8")

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", message)

    def check(self, title=""):
        self.commit()
        return changes.check_pr("main", title, self.root)

    # A pull request

    def test_a_version_raised_in_a_pull_request_is_refused(self):
        # As PR #253 first was: the version raised, a changelog section, a fix, no note.
        self.write("src/harness/__init__.py", '__version__ = "0.81.3"\n')
        self.write("docs/src/content/docs/changelog.md", self.read("docs/src/content/docs/changelog.md")
                   .replace("## 0.81.2", "## 0.81.3\n\n- New.\n\n## 0.81.2"))
        self.write("src/harness/cost.py", "SHOWN = False\n")
        problems = "\n".join(self.check("the-harness: no cost shown"))
        self.assertIn("src/harness/__init__.py: versions change only in a release", problems)
        self.assertIn("changelog.md: changelogs change only in a release", problems)
        self.assertIn("src/harness/cost.py: a code change comes with a change note", problems)

    def test_the_same_change_with_a_note_passes(self):
        self.write("src/harness/cost.py", "SHOWN = False\n")
        self.write("changes/no-cost.md", note("core: patch", "Costs are no longer shown."))
        self.assertEqual(self.check("the-harness: no cost shown"), [])

    def test_a_package_version_or_range_raised_is_refused(self):
        self.write("packages/computer/package.toml",
                   FILES["packages/computer/package.toml"].replace(">=0.81.1", ">=0.81.2"))
        self.write("changes/range.md", note("computer: patch"))
        self.assertIn("its version and harness range change only in a release", "\n".join(self.check()))

    def test_internal_changes_pass_with_an_empty_note_and_docs_or_tests_need_none(self):
        self.write("docs/src/content/docs/guide.md", "A better guide.\n")
        self.write("packages/computer/tests/test_host.py", "X = 2\n")
        self.assertEqual(self.check(), [])
        self.write("packages/computer/harness_computer/host.py", "X = 2\n")
        self.assertTrue(self.check())
        self.write("changes/refactor.md", "---\n---\n")
        self.assertEqual(self.check(), [])

    def test_a_note_names_a_known_component_with_a_known_level(self):
        self.write("src/harness/cost.py", "SHOWN = False\n")
        self.write("changes/a.md", note("nothing: patch"))
        self.write("changes/b.md", note("core: huge"))
        self.write("changes/c.md", note("core: major"))
        self.write("changes/d.md", "core: patch\nNo header.\n")
        problems = "\n".join(self.check())
        self.assertIn("no component 'nothing'", problems)
        self.assertIn("not 'huge'", problems)
        self.assertIn("before 1.0 a breaking change of core is `minor`", problems)
        self.assertIn("changes/d.md: starts with a header", problems)

    def test_private_packages_keep_their_notes_private(self):
        self.write("changes/app.md", note("app: patch"))
        self.write("private/changes/core.md", note("core: patch"))
        problems = "\n".join(self.check())
        self.assertIn("changes/app.md: app is private; its note goes in private/changes/", problems)
        self.assertIn("private/changes/core.md: a note in private/changes/ names a private package", problems)

    def test_a_release_may_change_versions_once_translated(self):
        self.write("changes/no-cost.md", note("core: patch", "Costs are no longer shown."))
        self.commit()
        self.git("checkout", "-q", "-B", "main")
        self.git("checkout", "-q", "-b", "release")
        changes.prepare(self.root, log=lambda message: None)
        self.assertIn("translate the notes marked", "\n".join(self.check("Release 0.81.3")))
        self.write("docs/src/content/docs/zh-cn/changelog.md", self.read("docs/src/content/docs/zh-cn/changelog.md")
                   .replace(f"Costs are no longer shown. {changes.UNTRANSLATED}", "不再显示花费。"))
        self.assertEqual(self.check("the-harness: Release 0.81.3"), [])
        self.assertTrue(self.check("the-harness: release notes"))

    # A release

    def test_prepare_raises_each_component_by_its_largest_level(self):
        self.write("changes/fix.md", note("core: patch", "A fix.", "一个修复。"))
        self.write("changes/feature.md", note("core: minor\ncomputer: patch", "A feature."))
        self.write("changes/internal.md", "---\n---\n")
        self.write("private/changes/app.md", note("app: minor", "An app change."))
        versions = changes.prepare(self.root, log=lambda message: None)
        self.assertEqual(versions, {"core": ("0.81.2", "0.82.0"), "app": ("0.9.2", "0.10.0"),
                                    "computer": ("0.7.3", "0.7.4")})
        self.assertEqual(self.read("src/harness/__init__.py"), '__version__ = "0.82.0"\n')
        self.assertIn('version = "0.7.4"', self.read("packages/computer/package.toml"))
        self.assertIn('version = "0.10.0"', self.read("private/packages/app/package.toml"))
        log = self.read("docs/src/content/docs/changelog.md")
        self.assertIn("Intro.\n\n## 0.82.0\n\n- A feature.\n- A fix.\n\n## 0.81.2", log)
        self.assertNotIn("An app change", log)
        zh = self.read("docs/src/content/docs/zh-cn/changelog.md")
        self.assertIn(f"## 0.82.0\n\n- A feature. {changes.UNTRANSLATED}\n- 一个修复。\n\n## 0.81.2", zh)
        self.assertIn("## 0.7.4\n\n- A feature.\n\n## 0.7.3", self.read("packages/computer/CHANGELOG.md"))
        self.assertIn("## 0.10.0\n\n- An app change.\n\n## 0.9.2", self.read("private/packages/app/CHANGELOG.md"))
        left = sorted(path.name for path in (self.root / "changes").iterdir())
        self.assertEqual(left, ["README.md"])
        self.assertEqual(list((self.root / "private/changes").iterdir()), [])

    def test_prepare_refuses_a_bad_note_and_changes_nothing(self):
        self.write("changes/bad.md", note("nothing: patch"))
        with self.assertRaises(ValueError):
            changes.prepare(self.root, log=lambda message: None)
        self.assertEqual(self.read("src/harness/__init__.py"), FILES["src/harness/__init__.py"])
        self.assertTrue((self.root / "changes/bad.md").is_file())

    def test_prepare_keeps_crlf_files_crlf(self):
        path = self.root / "packages/computer/CHANGELOG.md"
        path.write_bytes(FILES["packages/computer/CHANGELOG.md"].replace("\n", "\r\n").encode())
        self.write("changes/fix.md", note("computer: patch", "A fix."))
        changes.prepare(self.root, log=lambda message: None)
        self.assertEqual(path.read_bytes(), b"# Changelog\r\n\r\n## 0.7.4\r\n\r\n- A fix.\r\n\r\n## 0.7.3\r\n\r\n- Old.\r\n")


if __name__ == "__main__":
    unittest.main()
