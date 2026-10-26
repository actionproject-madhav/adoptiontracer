"""Clone and update artifact Git repositories.

All remote branches are fetched so that history tracing can search every
branch, not only the default one.
"""

import logging
import subprocess
from pathlib import Path

from .config import ArtifactConfig, TracerConfig

logger = logging.getLogger(__name__)


def _run_git(args: list[str], cwd: Path | None = None, timeout: int = 300) -> bool:
    """Run a git command, return True on success."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning("git %s failed: %s", " ".join(args), result.stderr.strip())
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out after %ds", " ".join(args), timeout)
        return False
    except Exception as e:
        logger.warning("git %s error: %s", " ".join(args), e)
        return False


def clone_or_update(config: TracerConfig, progress_callback=None) -> dict[str, str]:
    """
    Clone missing repos and update existing ones.

    Args:
        config: Tracer configuration with artifact definitions.
        progress_callback: Optional callable(name, status) for real-time progress.

    Returns a dict mapping artifact name to status:
    "cloned", "updated", "exists", "skipped", or "failed".
    """
    config.repos_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    def _report(name: str, status: str):
        results[name] = status
        if progress_callback:
            progress_callback(name, status)

    for artifact in config.artifacts:
        repo_path = config.get_repo_path(artifact)

        if not artifact.github_url:
            if repo_path.exists():
                _report(artifact.name, "exists (no URL, using local)")
            else:
                _report(artifact.name, "skipped (no URL, no local repo)")
                logger.warning("  %s: no github_url and no local repo at %s",
                               artifact.name, repo_path)
            continue

        if repo_path.exists() and (repo_path / ".git").exists():
            logger.info("  %s: pulling updates...", artifact.name)
            ok = _run_git(["pull", "--ff-only"], cwd=repo_path, timeout=120)
            if not ok:
                logger.info("  %s: fast-forward pull failed, trying pull --rebase...", artifact.name)
                ok = _run_git(["pull", "--rebase"], cwd=repo_path, timeout=180)
            _report(artifact.name, "updated" if ok else "exists (pull failed)")
            continue

        logger.info("  %s: cloning %s ...", artifact.name, artifact.github_url)
        ok = _run_git(
            ["clone", artifact.github_url, str(repo_path)],
            timeout=600,
        )
        _report(artifact.name, "cloned" if ok else "failed")

    return results
