"""Load and validate artifact configuration from YAML."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml


@dataclass
class ArtifactConfig:
    name: str
    type: str  # Tool, Benchmark, Regulatory
    github_url: str = ""
    repo_dir: str = ""  # auto-derived from github_url if not set
    selection_criteria: str = ""
    description: str = ""
    github_stars: Optional[int] = None
    git_search_mode: str = "file"  # "file" or "string"


@dataclass
class TracerConfig:
    repos_dir: Path
    artifacts: list[ArtifactConfig]
    paper_patterns: dict[str, list[str]]
    scan_extensions: list[str]
    exclude_ids: set[str]
    min_artifacts: int = 2
    always_include_from: list[str] = field(default_factory=list)

    def get_repo_path(self, artifact: ArtifactConfig) -> Path:
        return self.repos_dir / artifact.repo_dir


def _repo_dir_from_url(url: str) -> str:
    """Derive a local directory name from a GitHub URL."""
    path = urlparse(url).path.strip("/")
    # "org/repo-name" or "org/repo-name.git" → "repo-name"
    repo_name = path.split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    return repo_name


def load_config(config_path: str | Path, repos_relative_to_cwd: bool = False) -> TracerConfig:
    """Load configuration from a YAML file.

    If repos_relative_to_cwd is True (or the config lives inside a Python
    package in site-packages), relative repos_dir is resolved against CWD
    instead of the config file's directory.
    """
    config_path = Path(config_path).resolve()
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    repos_dir = Path(raw.get("repos_dir", "./repos"))
    if not repos_dir.is_absolute():
        is_installed = "site-packages" in str(config_path)
        if repos_relative_to_cwd:
            repos_dir = (Path.cwd() / repos_dir).resolve()
        elif is_installed:
            # Bundled config from pip: ignore YAML repos_dir (often ../artifact_repos
            # meant for in-repo layouts) and clone under ./artifact_repos in CWD.
            repos_dir = (Path.cwd() / "artifact_repos").resolve()
        else:
            repos_dir = (config_path.parent / repos_dir).resolve()

    artifacts = []
    for entry in raw.get("artifacts", []):
        github_url = entry.get("github_url", "")
        repo_dir = entry.get("repo_dir", "")

        # Auto-derive repo_dir from github_url if not explicitly set
        if not repo_dir and github_url:
            repo_dir = _repo_dir_from_url(github_url)
        elif not repo_dir:
            raise ValueError(f"Artifact '{entry.get('name')}' needs either "
                             f"'github_url' or 'repo_dir'")

        artifacts.append(ArtifactConfig(
            name=entry["name"],
            type=entry["type"],
            github_url=github_url,
            repo_dir=repo_dir,
            selection_criteria=entry.get("selection_criteria", ""),
            description=entry.get("description", ""),
            github_stars=entry.get("github_stars"),
            git_search_mode=entry.get("git_search_mode", "file"),
        ))

    selection = raw.get("selection", {})

    return TracerConfig(
        repos_dir=repos_dir,
        artifacts=artifacts,
        paper_patterns=raw.get("paper_patterns", {}),
        scan_extensions=raw.get("scan_extensions", [".py", ".md", ".txt"]),
        exclude_ids=set(raw.get("exclude_ids", [])),
        min_artifacts=selection.get("min_artifacts", 2),
        always_include_from=selection.get("always_include_from", []),
    )
