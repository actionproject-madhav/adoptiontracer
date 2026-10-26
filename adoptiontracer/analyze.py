"""
Compute adoption lags and produce structured output.

Takes extraction results (which papers were found where),
resolved metadata (publication dates, titles, authors),
and trace results (adoption timestamps), then combines
them into a unified dataset with computed adoption lags.
"""

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import TracerConfig
from .extract import ExtractionResult
from .resolve import PaperMetadata
from .trace import TraceResult

logger = logging.getLogger(__name__)

MONTHS_PER_DAY = 1 / 30.44


@dataclass
class PaperRecord:
    """Complete record for one paper: metadata + adoption data."""
    arxiv_id: str
    title: str
    authors: str
    pub_date: str
    found_in_artifacts: str
    num_artifacts: int
    first_adoption_date: str
    first_adoption_artifact: str
    all_adoptions: str
    adoption_lag_months: float | None
    selection_reason: str


@dataclass
class AnalysisResult:
    """Full analysis output: all papers with computed lags."""
    all_papers: list[PaperRecord] = field(default_factory=list)
    selected_papers: list[PaperRecord] = field(default_factory=list)

    @property
    def lags(self) -> list[float]:
        return [p.adoption_lag_months for p in self.selected_papers
                if p.adoption_lag_months is not None]

    def summary_stats(self) -> dict:
        selected_lags = sorted(
            p.adoption_lag_months for p in self.selected_papers
            if p.adoption_lag_months is not None
        )
        all_lags = sorted(
            p.adoption_lag_months for p in self.all_papers
            if p.adoption_lag_months is not None
        )
        # Study sample stats when non-empty; else distributional stats over all extracted
        # papers that have an adoption date (e.g. single-artifact or custom min_artifacts).
        lags = selected_lags if selected_lags else all_lags
        out: dict = {
            "n_papers_total": len(self.all_papers),
            "n_papers_selected": len(self.selected_papers),
            "n_with_lag_selected": len(selected_lags),
            "n_with_lag_extracted": len(all_lags),
        }
        if not lags:
            out["n_with_lag"] = 0
            out["lag_stats_scope"] = "none"
            return out
        n = len(lags)
        out.update({
            "n_with_lag": n,
            "lag_stats_scope": "selected" if selected_lags else "all_extracted",
            "median_months": lags[n // 2],
            "mean_months": round(sum(lags) / n, 1),
            "min_months": lags[0],
            "max_months": lags[-1],
            "q1_months": lags[n // 4],
            "q3_months": lags[3 * n // 4],
            "iqr_months": round(lags[3 * n // 4] - lags[n // 4], 1),
        })
        return out


def _compute_lag(pub_date: str, adopt_date: str) -> float | None:
    """Compute adoption lag in months between two YYYY-MM-DD dates."""
    try:
        pub = datetime.strptime(pub_date, "%Y-%m-%d")
        adopt = datetime.strptime(adopt_date, "%Y-%m-%d")
        return round((adopt - pub).days * MONTHS_PER_DAY, 1)
    except (ValueError, TypeError):
        return None


def analyze(
    config: TracerConfig,
    extraction: ExtractionResult,
    metadata: dict[str, PaperMetadata],
    traces: TraceResult,
) -> AnalysisResult:
    """
    Combine extraction, metadata, and trace data into a unified dataset.

    Applies selection criteria from config to determine which papers
    are included in the analysis sample.
    """
    result = AnalysisResult()

    for arxiv_id in extraction.unique_ids:
        meta = metadata.get(arxiv_id)
        if not meta or not meta.valid:
            continue

        artifacts = sorted(extraction.arxiv_to_artifacts[arxiv_id])
        num_artifacts = len(artifacts)

        events = traces.get_all_events_sorted(arxiv_id)
        first = traces.get_first_event(arxiv_id)

        first_date = first.date if first else ""
        first_artifact = first.artifact_name if first else ""
        all_adoptions = "; ".join(f"{e.artifact_name}:{e.date}" for e in events)
        lag = _compute_lag(meta.pub_date, first_date) if first_date else None

        # Determine selection reason
        is_always_include = any(
            a in config.always_include_from for a in artifacts
        )
        if num_artifacts >= config.min_artifacts:
            selection = f"{config.min_artifacts}+ artifacts"
        elif is_always_include:
            single_from = [a for a in artifacts if a in config.always_include_from]
            selection = f"{single_from[0]} (regulatory)"
        else:
            selection = ""

        record = PaperRecord(
            arxiv_id=arxiv_id,
            title=meta.title,
            authors=meta.authors,
            pub_date=meta.pub_date,
            found_in_artifacts=", ".join(artifacts),
            num_artifacts=num_artifacts,
            first_adoption_date=first_date,
            first_adoption_artifact=first_artifact,
            all_adoptions=all_adoptions,
            adoption_lag_months=lag,
            selection_reason=selection,
        )

        result.all_papers.append(record)
        if selection:
            result.selected_papers.append(record)

    logger.info("Analysis complete: %d total papers, %d selected for study",
                len(result.all_papers), len(result.selected_papers))
    return result


def write_results(result: AnalysisResult, output_dir: Path):
    """Write analysis results to CSV and JSON summary files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "selection_reason", "arxiv_id", "found_in_artifacts", "num_artifacts",
        "title", "authors", "pub_date",
        "first_adoption_date", "first_adoption_artifact",
        "all_adoptions", "adoption_lag_months",
    ]

    # All papers
    all_csv = output_dir / "papers_all.csv"
    _write_csv(all_csv, result.all_papers, fieldnames)
    logger.info("Wrote %d papers to %s", len(result.all_papers), all_csv)

    # Selected papers only
    selected_csv = output_dir / "papers_selected.csv"
    _write_csv(selected_csv, result.selected_papers, fieldnames)
    logger.info("Wrote %d selected papers to %s", len(result.selected_papers), selected_csv)

    # Summary statistics
    stats = result.summary_stats()
    stats_file = output_dir / "summary.json"
    stats_file.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    logger.info("Wrote summary stats to %s", stats_file)

    return stats


def _write_csv(path: Path, papers: list[PaperRecord], fieldnames: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for paper in papers:
            row = {
                "selection_reason": paper.selection_reason,
                "arxiv_id": paper.arxiv_id,
                "found_in_artifacts": paper.found_in_artifacts,
                "num_artifacts": paper.num_artifacts,
                "title": paper.title,
                "authors": paper.authors,
                "pub_date": paper.pub_date,
                "first_adoption_date": paper.first_adoption_date,
                "first_adoption_artifact": paper.first_adoption_artifact,
                "all_adoptions": paper.all_adoptions,
                "adoption_lag_months": paper.adoption_lag_months if paper.adoption_lag_months is not None else "",
            }
            writer.writerow(row)
