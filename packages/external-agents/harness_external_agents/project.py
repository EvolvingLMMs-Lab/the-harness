"""Git working directories and Harness-owned worktrees for external sessions."""

import os
from pathlib import Path
import subprocess

from harness.sdk import home


def git(directory, *arguments, codes=(0,)):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(directory), *arguments],
                            capture_output=True, encoding="utf-8", errors="replace", env=environment, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode not in codes:
        raise ValueError(result.stderr.strip() or f"git {arguments[0]} failed")
    return result.stdout


class Project:
    def __init__(self, folder, isolation, run_name):
        self.cwd = folder
        self.worktree = self.branch = self.base = self.ref = None
        self.directory = None
        try:
            self.directory = Path(git(folder, "rev-parse", "--show-toplevel").strip()).resolve(strict=True)
        except (ValueError, FileNotFoundError):
            if isolation == "worktree":
                raise ValueError("a worktree requires an existing Git repository")
        if isolation not in (None, "folder", "worktree"):
            raise ValueError("isolation is folder or worktree")
        if self.directory is not None:
            self.base = git(folder, "rev-parse", "--verify", "HEAD", codes=(0, 128)).strip() or None
            self.ref = git(folder, "symbolic-ref", "-q", "HEAD", codes=(0, 1)).strip() or None
        if isolation == "worktree":
            if self.base is None:
                raise ValueError("a managed worktree needs a starting commit")
            container = home() / "session-worktrees"
            container.mkdir(parents=True, exist_ok=True)
            self.branch = f"harness/session-{run_name}"
            self.worktree = container / run_name
            git(self.directory, "worktree", "add", "-b", self.branch, str(self.worktree), self.base)
            # Git only checks out committed files, so a directory of untracked files may be absent.
            relative = folder.relative_to(self.directory)
            self.cwd = self.worktree / relative
            if not self.cwd.is_dir():
                self.cwd = self.worktree

    def metadata(self):
        return {"project": str(self.directory or self.cwd), "cwd": str(self.cwd), "ref": self.ref,
                "base": self.base, "worktree": str(self.worktree) if self.worktree else None,
                "worktree_branch": self.branch}

    def diff(self):
        directory = self.worktree or self.directory
        if directory is None:
            raise ValueError("this project has no Git diff")
        arguments = (self.base,) if self.base else ()
        patch = git(directory, "diff", "--no-ext-diff", "--no-textconv", *arguments, "--")
        untracked = git(directory, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        paths = [path for path in untracked if path]
        return {"base": self.base, "patch": patch[:1024 * 1024], "untracked": paths[:1000],
                "truncated": len(patch) > 1024 * 1024 or len(paths) > 1000}

    def merge(self):
        if not self.worktree or not self.ref:
            raise ValueError("merge requires a managed worktree with an original branch")
        if git(self.directory, "symbolic-ref", "-q", "HEAD", codes=(0, 1)).strip() != self.ref:
            raise ValueError("check out the worktree's original branch before merging")
        if git(self.directory, "status", "--porcelain"):
            raise ValueError("the original working tree must be clean before merging")
        if git(self.worktree, "status", "--porcelain"):
            raise ValueError("commit the worktree changes before merging")
        target = git(self.worktree, "rev-parse", "HEAD").strip()
        git(self.directory, "merge", "--ff-only", target)
        return {"commit": target}

    def discard(self):
        if not self.worktree:
            raise ValueError("this session has no managed worktree")
        git(self.directory, "worktree", "remove", "--force", str(self.worktree))
        self.worktree = self.branch = None
        return {"removed": True}
