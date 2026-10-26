"""Date the first integration of each paper in each artifact.

Three modes are available per artifact (``git_search_mode``):

- ``history`` (default): stream the full history once and take the earliest
  commit on any branch whose added lines introduce the identifier, by author
  date. This is the method used in the paper.
- ``file``: ``git log -S <id> -- <file>`` for each file that references the
  paper at HEAD, with a repo-wide ``-S`` fallback.
- ``string``: repo-wide ``git log -S <id>`` only, for repositories that keep
  all references in a few aggregated files.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import ArtifactConfig, TracerConfig
from .extract import ExtractionResult, PaperReference, _compile_patterns
from .history import scan_history

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


def _trace_history(
    artifact: ArtifactConfig,
    repo_path: Path,
    wanted: set[str],
    patterns: list,
) -> list[AdoptionEvent]:
    """One pass over the full history; earliest author-dated introduction per paper."""
    first: dict[str, tuple[str, str]] = {}
    for ev in scan_history(repo_path, patterns):
        if ev.arxiv_id not in wanted:
            continue
        date = ev.author_date[:10]
        if ev.arxiv_id not in first or date < first[ev.arxiv_id][0]:
            first[ev.arxiv_id] = (date, ev.file)
    return [
        AdoptionEvent(aid, artifact.name, artifact.type, date, file)
        for aid, (date, file) in first.items()
    ]


def trace(
    config: TracerConfig,
    extraction: ExtractionResult,
) -> TraceResult:
    """Date every (paper, artifact) pair found by extraction."""
    result = TraceResult()
    patterns = _compile_patterns(config)
    logger.info("Tracing first-integration dates for %d papers across %d artifacts",
                len(extraction.unique_ids), len(config.artifacts))

    for artifact in config.artifacts:
        repo_path = config.get_repo_path(artifact)
        if not repo_path.exists():
            continue
        wanted = {aid for aid, names in extraction.arxiv_to_artifacts.items()
                  if artifact.name in names}
        if not wanted:
            continue
        if artifact.git_search_mode == "history":
            logger.info("  %s: streaming history for %d papers", artifact.name, len(wanted))
            result.events.extend(_trace_history(artifact, repo_path, wanted, patterns))
            continue
        for arxiv_id in sorted(wanted):
            refs = [r for r in extraction.arxiv_to_refs[arxiv_id] if r.artifact_name == artifact.name]
            event = _trace_artifact(arxiv_id, artifact, repo_path, refs)
            if event:
                result.events.append(event)

    logger.info("Tracing complete: %d integration events for %d papers",
                len(result.events),
                len({e.arxiv_id for e in result.events}))
    return result
