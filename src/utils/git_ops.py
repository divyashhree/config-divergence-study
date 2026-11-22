"""
Git operations utility: safe clone, checkout, log extraction.

Uses the Git CLI for reliability and transparency.
"""
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone

from src.utils.logging_config import get_logger

logger = get_logger("git_ops")


class GitError(Exception):
    """Raised when a git operation fails."""
    pass


def clone_repo(
    url: str,
    dest: Path,
    shallow: bool = False,
    depth: int = 1,
) -> Path:
    """
    Clone a git repository.

    Args:
        url: Repository URL (HTTPS).
        dest: Destination directory.
        shallow: If True, perform a shallow clone.
        depth: Clone depth if shallow.

    Returns:
        Path to cloned repository.

    Raises:
        GitError: If clone fails.
    """
    if dest.exists():
        logger.info(f"Repository already exists at {dest}, skipping clone")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--no-checkout"]
    if shallow:
        cmd.extend(["--depth", str(depth)])
    cmd.extend([url, str(dest)])

    logger.info(f"Cloning {url} -> {dest}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise GitError(f"git clone failed: {result.stderr.strip()}")
        logger.info(f"Clone successful: {dest}")
        return dest
    except subprocess.TimeoutExpired:
        # Clean up partial clone
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise GitError(f"git clone timed out for {url}")


def checkout(repo_path: Path, ref: str = "HEAD") -> str:
    """
    Checkout a specific ref (branch, tag, or SHA).

    Returns:
        The resolved commit SHA.
    """
    _run_git(repo_path, ["checkout", ref, "--force"])
    sha = _run_git(repo_path, ["rev-parse", "HEAD"]).strip()
    logger.debug(f"Checked out {ref} -> {sha}")
    return sha


def get_head_sha(repo_path: Path) -> str:
    """Get the current HEAD SHA."""
    return _run_git(repo_path, ["rev-parse", "HEAD"]).strip()


def get_file_at_commit(repo_path: Path, commit_sha: str, file_path: str) -> str | None:
    """
    Retrieve file contents at a specific commit without checkout.

    Returns:
        File contents as string, or None if file doesn't exist at that commit.
    """
    try:
        return _run_git(repo_path, ["show", f"{commit_sha}:{file_path}"])
    except GitError:
        return None


def get_commit_log(
    repo_path: Path,
    max_count: int = 500,
    since: str | None = None,
    until: str | None = None,
    paths: list[str] | None = None,
) -> list[dict]:
    """
    Extract commit log entries.

    Returns:
        List of dicts with sha, date, author, message.
    """
    # Use a delimiter unlikely to appear in messages
    sep = "|||FIELD_SEP|||"
    fmt = f"%H{sep}%aI{sep}%an{sep}%s"
    cmd = ["log", f"--format={fmt}", f"--max-count={max_count}"]
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")
    if paths:
        cmd.append("--")
        cmd.extend(paths)

    output = _run_git(repo_path, cmd)
    commits = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(sep)
        if len(parts) >= 4:
            commits.append({
                "sha": parts[0],
                "date": parts[1],
                "author": parts[2],
                "message": parts[3],
            })
    return commits


def get_changed_files(repo_path: Path, commit_sha: str) -> list[str]:
    """Get list of files changed in a commit."""
    try:
        output = _run_git(repo_path, ["diff-tree", "--no-commit-id", "-r", "--name-only", commit_sha])
        return [f for f in output.strip().split("\n") if f.strip()]
    except GitError:
        return []


def list_files_at_commit(repo_path: Path, commit_sha: str, pattern: str = "") -> list[str]:
    """
    List files in the repository tree at a specific commit.

    Args:
        repo_path: Path to the repo.
        commit_sha: Commit to inspect.
        pattern: Optional glob pattern to filter (applied client-side).

    Returns:
        List of file paths relative to repo root.
    """
    output = _run_git(repo_path, ["ls-tree", "-r", "--name-only", commit_sha])
    files = [f for f in output.strip().split("\n") if f.strip()]
    if pattern:
        import fnmatch
        files = [f for f in files if fnmatch.fnmatch(f, pattern)]
    return files


def _run_git(repo_path: Path, args: list[str]) -> str:
    """
    Run a git command in the specified repository.

    Raises:
        GitError: If the command fails.
    """
    cmd = ["git", "-C", str(repo_path)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
        return result.stdout
    except subprocess.TimeoutExpired:
        raise GitError(f"git command timed out: {' '.join(args[:2])}")
