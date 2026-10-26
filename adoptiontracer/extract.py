"""
Extract paper references from artifact Git repositories.

Scans configured file types for arXiv ID patterns and records
which artifact referenced which paper and in which file.
"""

import re
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import ArtifactConfig, TracerConfig

logger = logging.getLogger(__name__)


@dataclass
class PaperReference:
    """A single reference to a paper found in an artifact repo."""
    arxiv_id: str
    artifact_name: str
    artifact_type: str
    source_file: str  # relative path within the repo


@dataclass
class ExtractionResult:
    """Aggregated extraction results across all artifacts."""
    references: list[PaperReference] = field(default_factory=list)

    # Derived lookups (populated by finalize())
    arxiv_to_artifacts: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    arxiv_to_refs: dict[str, list[PaperReference]] = field(default_factory=lambda: defaultdict(list))
    unique_ids: list[str] = field(default_factory=list)

    def finalize(self):
        """Build lookup indices from raw references."""
        self.arxiv_to_artifacts = defaultdict(set)
        self.arxiv_to_refs = defaultdict(list)
        for ref in self.references:
            self.arxiv_to_artifacts[ref.arxiv_id].add(ref.artifact_name)
            self.arxiv_to_refs[ref.arxiv_id].append(ref)
        self.unique_ids = sorted(self.arxiv_to_artifacts.keys())


def _compile_patterns(config: TracerConfig) -> list[re.Pattern]:
    """Compile arXiv regex patterns from config."""
    patterns = []
    for pattern_list in config.paper_patterns.values():
        for p in pattern_list:
            patterns.append(re.compile(p, re.IGNORECASE))

    if not patterns:
        patterns = [
            re.compile(r'arxiv\.org/abs/(\d{4}\.\d{4,5})', re.IGNORECASE),
            re.compile(r'arxiv\.org/pdf/(\d{4}\.\d{4,5})', re.IGNORECASE),
            re.compile(r'arXiv[:\s]+(\d{4}\.\d{4,5})', re.IGNORECASE),
            re.compile(r'eprint\s*=\s*[{"](\d{4}\.\d{4,5})[}"]', re.IGNORECASE),
        ]
    return patterns


def _extract_ids_from_file(filepath: Path, patterns: list[re.Pattern]) -> set[str]:
    """Extract all arXiv IDs from a single file."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()

    found = set()
    for pattern in patterns:
        for match in pattern.finditer(content):
            found.add(match.group(1))
    return found


def _scan_artifact(
    artifact: ArtifactConfig,
    repo_path: Path,
    extensions: list[str],
    patterns: list[re.Pattern],
    exclude_ids: set[str],
) -> list[PaperReference]:
    """Scan a single artifact repo for paper references."""
    if not repo_path.exists():
        logger.debug("Repo not found: %s (expected at %s)", artifact.name, repo_path)
        return []

    refs = []
    for ext in extensions:
        for filepath in repo_path.rglob(f"*{ext}"):
            rel_path = str(filepath.relative_to(repo_path))

            arxiv_ids = _extract_ids_from_file(filepath, patterns)
            for aid in arxiv_ids:
                if aid in exclude_ids:
                    continue
                refs.append(PaperReference(
                    arxiv_id=aid,
                    artifact_name=artifact.name,
                    artifact_type=artifact.type,
                    source_file=rel_path,
                ))

    logger.info("  %s: %d references (%d unique papers)",
                artifact.name, len(refs), len({r.arxiv_id for r in refs}))
    return refs


def extract(config: TracerConfig) -> ExtractionResult:
    """
    Scan all configured artifact repos for paper references.

    Returns an ExtractionResult with all references found,
    deduplicated lookups, and the list of unique arXiv IDs.
    """
    logger.info("Scanning %d artifact repositories...", len(config.artifacts))

    patterns = _compile_patterns(config)
    result = ExtractionResult()

    missing_names: list[str] = []
    for artifact in config.artifacts:
        repo_path = config.get_repo_path(artifact)
        if not repo_path.exists():
            missing_names.append(artifact.name)
        refs = _scan_artifact(
            artifact, repo_path,
            config.scan_extensions, patterns, config.exclude_ids,
        )
        result.references.extend(refs)

    result.finalize()

    if missing_names:
        logger.warning(
            "%d of %d artifact repos missing under %s (%s). "
            "Run `adoptiontracer scan` to clone, or pass `-c` to a config next to your repos.",
            len(missing_names),
            len(config.artifacts),
            config.repos_dir,
            ", ".join(missing_names[:6]) + ("…" if len(missing_names) > 6 else ""),
        )

    logger.info("Extraction complete: %d unique papers from %d total references",
                len(result.unique_ids), len(result.references))
    return result
