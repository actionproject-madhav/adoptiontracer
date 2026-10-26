"""
Git archaeology for adoption timestamps.

For each paper referenced by an artifact, find the earliest Git commit
that introduced the reference. Supports two modes:

- file mode: uses `git log -S <id> -- <file>` scoped to specific files
  (fast, works for repos where each paper has a distinct file/entry)
- string mode: uses `git log -S` across the whole repo
  (slower but accurate for repos with aggregated files like MITRE ATLAS)
"""

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import ArtifactConfig, TracerConfig
from .extract import ExtractionResult, PaperReference

logger = logging.getLogger(__name__)


@dataclass
class AdoptionEvent:
    """A single adoption event: one artifact adopting one paper."""
    arxiv_id: str
    artifact_name: str
    artifact_type: str
    date: str          # YYYY-MM-DD
    source_file: str   # file where reference was found


@dataclass
class TraceResult:
    """All adoption events discovered across all artifacts."""
    events: list[AdoptionEvent] = field(default_factory=list)

    def get_events_for_paper(self, arxiv_id: str) -> list[AdoptionEvent]:
        return [e for e in self.events if e.arxiv_id == arxiv_id]

    def get_first_event(self, arxiv_id: str) -> AdoptionEvent | None:
        paper_events = self.get_events_for_paper(arxiv_id)
        if not paper_events:
            return None
        return min(paper_events, key=lambda e: e.date)

    def get_all_events_sorted(self, arxiv_id: str) -> list[AdoptionEvent]:
        return sorted(self.get_events_for_paper(arxiv_id), key=lambda e: e.date)


def _git_first_commit_string_search(repo_path: Path, search_string: str) -> str | None:
    """
    Find the earliest commit where search_string was introduced, using `git log -S`.
    Returns YYYY-MM-DD or None.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--all", "-S", search_string,
             "--reverse", "--format=%ad", "--date=short"],
            cwd=repo_path,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            date = result.stdout.strip().split("\n")[0]
            if date <= datetime.now().strftime("%Y-%m-%d"):
                return date
    except subprocess.TimeoutExpired:
        logger.warning("git log -S timed out for '%s' in %s", search_string, repo_path.name)
    except Exception as e:
        logger.warning("git error for '%s' in %s: %s", search_string, repo_path.name, e)
    return None


def _git_first_commit_file(repo_path: Path, arxiv_id: str, filepath: str) -> str | None:
    """
    Find the earliest commit that introduced arxiv_id in a specific file,
    using `git log -S <arxiv_id> -- <filepath>`.
    Returns YYYY-MM-DD or None.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--all", "-S", arxiv_id, "--reverse",
             "--format=%ad", "--date=short", "--", filepath],
            cwd=repo_path,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            date = result.stdout.strip().split("\n")[0]
            if date <= datetime.now().strftime("%Y-%m-%d"):
                return date
    except subprocess.TimeoutExpired:
        logger.warning("git log -S timed out for %s in %s", filepath, repo_path.name)
    except Exception as e:
        logger.warning("git error for %s in %s: %s", filepath, repo_path.name, e)
    return None


def _trace_artifact(
    arxiv_id: str,
    artifact: ArtifactConfig,
    repo_path: Path,
    refs: list[PaperReference],
) -> AdoptionEvent | None:
    """
    Find the earliest adoption date for one paper in one artifact.
    Tries string-search mode for artifacts that aggregate references
    in single files, falls back to file-based tracing otherwise.
    """
    if artifact.git_search_mode == "string":
        date = _git_first_commit_string_search(repo_path, arxiv_id)
        if date:
            source = refs[0].source_file if refs else ""
            return AdoptionEvent(
                arxiv_id=arxiv_id,
                artifact_name=artifact.name,
                artifact_type=artifact.type,
                date=date,
                source_file=source,
            )
        return None

    # File mode: check each source file for when the arxiv_id was introduced
    best_date = None
    best_file = ""
    for ref in refs:
        date = _git_first_commit_file(repo_path, arxiv_id, ref.source_file)
        if date and (best_date is None or date < best_date):
            best_date = date
            best_file = ref.source_file

    # String search fallback only when file tracing found nothing
    # (catches renamed/moved files without doubling runtime)
    if best_date is None:
        date_s = _git_first_commit_string_search(repo_path, arxiv_id)
        if date_s:
            best_date = date_s
            best_file = refs[0].source_file if refs else ""

    if best_date:
        return AdoptionEvent(
            arxiv_id=arxiv_id,
            artifact_name=artifact.name,
            artifact_type=artifact.type,
            date=best_date,
            source_file=best_file,
        )
    return None


def trace(
    config: TracerConfig,
    extraction: ExtractionResult,
) -> TraceResult:
    """
    Trace adoption timestamps for all extracted paper references.

    For each (paper, artifact) pair, runs Git archaeology to find
    the earliest commit date when the reference was introduced.
    """
    artifact_map = {a.name: a for a in config.artifacts}
    result = TraceResult()
    total = len(extraction.unique_ids)

    logger.info("Tracing adoption dates for %d papers across %d artifacts...",
                total, len(config.artifacts))

    for i, arxiv_id in enumerate(extraction.unique_ids):
        if (i + 1) % 25 == 0 or i == 0:
            logger.info("  Progress: %d/%d papers", i + 1, total)

        refs_by_artifact: dict[str, list[PaperReference]] = {}
        for ref in extraction.arxiv_to_refs[arxiv_id]:
            refs_by_artifact.setdefault(ref.artifact_name, []).append(ref)

        for artifact_name, refs in refs_by_artifact.items():
            artifact = artifact_map.get(artifact_name)
            if not artifact:
                continue
            repo_path = config.get_repo_path(artifact)
            if not repo_path.exists():
                continue

            event = _trace_artifact(arxiv_id, artifact, repo_path, refs)
            if event:
                result.events.append(event)

    logger.info("Tracing complete: %d adoption events for %d papers",
                len(result.events),
                len({e.arxiv_id for e in result.events}))
    return result
