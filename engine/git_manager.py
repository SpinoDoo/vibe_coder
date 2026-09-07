"""
Every change happens on a disposable branch and is only ever merged to the
base branch (default 'main') after it passes the eval hard-gates. Anything
that fails is reverted, never left half-applied.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class GitManager:
    def __init__(self, repo_dir: Path, base_branch: str = "main"):
        self.repo_dir = Path(repo_dir)
        self.base_branch = base_branch
        self._ensure_repo()

    def _run(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.repo_dir, capture_output=True, text=True
        )
        if check and result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _ensure_repo(self):
        is_new_repo = not (self.repo_dir / ".git").exists()
        if is_new_repo:
            self._run("init")

        # Ensure a local git identity exists so commits never fail silently.
        # Only sets it locally (this repo only) and only if unset -- never
        # overrides a real identity the user already configured.
        has_email = subprocess.run(
            ["git", "config", "--get", "user.email"], cwd=self.repo_dir, capture_output=True, text=True
        ).returncode == 0
        if not has_email:
            self._run("config", "user.email", "engine@local")
            self._run("config", "user.name", "Autonomous Improvement Engine")

        if is_new_repo:
            self._run("checkout", "-b", self.base_branch, check=False)
            (self.repo_dir / ".gitkeep").touch(exist_ok=True)
            self._run("add", "-A")
            sha = self.commit_all("Initial commit (auto-created by engine)")
            if sha is None:
                raise GitError(
                    "failed to create initial commit in target repo -- check git is installed "
                    "and the target_dir is writable"
                )
        else:
            branches = self._run("branch", "--list", self.base_branch)
            if not branches:
                self._run("checkout", "-b", self.base_branch, check=False)

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD")

    def create_cycle_branch(self, cycle_id: str) -> str:
        branch = f"engine-cycle/{cycle_id}"
        self._run("checkout", self.base_branch)
        self._run("checkout", "-b", branch)
        return branch

    def diff_stat(self) -> str:
        return self._run("diff", "--stat", check=False)

    def commit_all(self, message: str) -> str | None:
        self._run("add", "-A")
        status = self._run("status", "--porcelain")
        if not status:
            return None  # nothing changed
        self._run("commit", "-m", message)
        return self._run("rev-parse", "HEAD")

    def merge_to_base(self, branch: str, message: str):
        self._run("checkout", self.base_branch)
        self._run("merge", "--no-ff", branch, "-m", message)

    def abandon_branch(self, branch: str):
        self._run("checkout", self.base_branch)
        self._run("branch", "-D", branch, check=False)

    def revert_working_tree(self):
        """Hard reset any uncommitted changes on the current branch."""
        self._run("reset", "--hard", "HEAD")
        self._run("clean", "-fd")

    def log_recent(self, n: int = 10) -> list[str]:
        out = self._run("log", f"-{n}", "--oneline", "--no-decorate", check=False)
        return out.splitlines() if out else []
