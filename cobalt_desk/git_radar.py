"""Read-only Git multi-worktree radar using `git --no-optional-locks`."""

from __future__ import annotations

import concurrent.futures
import os
import pathlib
import subprocess
import threading
import time
from typing import Any

from cobalt_desk.redaction import redact_sensitive_text

GIT_NO_LOCK_ARGS: tuple[str, ...] = ("--no-optional-locks",)


def run_git_readonly(repo_dir: pathlib.Path, args: list[str], timeout: float = 2.5) -> str | None:
    """Execute a read-only git command with `--no-optional-locks` so `index.lock` is NEVER created."""
    cmd = ["git", *GIT_NO_LOCK_ARGS, "-C", str(repo_dir), *args]
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.run(cmd, check=False, **kwargs)
        if proc.returncode != 0:
            return None
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def detect_default_branch(repo_dir: pathlib.Path) -> str:
    """Auto-detect repository default branch (`origin/HEAD` -> `main` -> `master` -> `develop`)."""
    sym = run_git_readonly(repo_dir, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if sym:
        cleaned = sym.strip().removeprefix("origin/")
        if cleaned:
            return cleaned
    for candidate in ("main", "master", "develop", "trunk"):
        chk = run_git_readonly(repo_dir, ["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"])
        if chk is not None:
            return candidate
    return "main"


class GitWorktreeRadar:
    """Thread-safe read-only inspector for parallel Git worktrees."""

    def __init__(
        self,
        repo_dir: pathlib.Path | None = None,
        cache_ttl: float = 5.0,
        static_demo_worktrees: list[dict[str, Any]] | None = None,
    ) -> None:
        self.repo_dir = repo_dir.resolve() if repo_dir and repo_dir.exists() else None
        self.cache_ttl = cache_ttl
        self.static_demo_worktrees = static_demo_worktrees
        self._lock = threading.Lock()
        self._cache_ts = 0.0
        self._cache_data: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return self.static_demo_worktrees is not None or self.repo_dir is not None

    def get_worktrees(self, force: bool = False) -> list[dict[str, Any]]:
        if self.static_demo_worktrees is not None:
            return list(self.static_demo_worktrees)
        if self.repo_dir is None:
            return []

        now = time.time()
        with self._lock:
            if not force and (now - self._cache_ts) < self.cache_ttl and self._cache_data:
                return self._cache_data

            raw = run_git_readonly(self.repo_dir, ["worktree", "list", "--porcelain"])
            if not raw:
                return self._cache_data

            default_branch = detect_default_branch(self.repo_dir)
            entries: list[dict[str, str]] = []
            cur: dict[str, str] = {}
            for line in raw.splitlines():
                if not line.strip():
                    if cur.get("worktree"):
                        entries.append(cur)
                    cur = {}
                    continue
                if line.startswith("worktree "):
                    cur["worktree"] = line[len("worktree ") :].strip()
                elif line.startswith("HEAD "):
                    cur["head"] = line[len("HEAD ") :].strip()
                elif line.startswith("branch "):
                    ref = line[len("branch ") :].strip()
                    cur["branch"] = ref.removeprefix("refs/heads/")
                elif line == "detached":
                    cur["branch"] = "(detached)"
            if cur.get("worktree"):
                entries.append(cur)

            def _inspect_one(ent: dict[str, str]) -> dict[str, Any] | None:
                wt_path = pathlib.Path(ent["worktree"])
                if not wt_path.exists():
                    return None
                raw_branch = ent.get("branch", "?")
                branch = redact_sensitive_text(raw_branch)
                log_out = run_git_readonly(wt_path, ["log", "-1", "--format=%h%x09%ci%x09%cr%x09%s"])
                short_sha = ent.get("head", "")[:7]
                commit_iso = ""
                commit_rel = ""
                subject = ""
                if log_out:
                    parts = log_out.strip().split("\t", 3)
                    if len(parts) >= 1:
                        short_sha = parts[0]
                    if len(parts) >= 2:
                        commit_iso = parts[1]
                    if len(parts) >= 3:
                        commit_rel = parts[2]
                    if len(parts) >= 4:
                        subject = redact_sensitive_text(parts[3])[:140]

                st_out = run_git_readonly(wt_path, ["status", "--porcelain"])
                dirty_count = len([ln for ln in (st_out or "").splitlines() if ln.strip()])

                behind = 0
                ahead = 0
                is_default = raw_branch == default_branch
                if raw_branch and not is_default and raw_branch != "(detached)":
                    ab_out = run_git_readonly(
                        wt_path, ["rev-list", "--left-right", "--count", f"{default_branch}...HEAD"]
                    )
                    if ab_out:
                        ab_parts = ab_out.strip().split()
                        if len(ab_parts) == 2 and ab_parts[0].isdigit() and ab_parts[1].isdigit():
                            behind = int(ab_parts[0])
                            ahead = int(ab_parts[1])

                if dirty_count > 0:
                    state = "CODING"
                elif is_default:
                    state = "MAIN"
                elif ahead > 0:
                    state = "UNMERGED"
                else:
                    state = "MERGED"

                return {
                    "name": wt_path.name,
                    "branch": branch,
                    "default_branch": default_branch,
                    "sha": short_sha,
                    "commit_iso": commit_iso,
                    "commit_rel": commit_rel,
                    "subject": subject,
                    "dirty_count": dirty_count,
                    "ahead": ahead,
                    "behind": behind,
                    "state": state,
                }

            results: list[dict[str, Any]] = []
            if entries:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(entries))) as pool:
                    for item in pool.map(_inspect_one, entries):
                        if item is not None:
                            results.append(item)

            self._cache_data = results
            self._cache_ts = time.time()
            return results
