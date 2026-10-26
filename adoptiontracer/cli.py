"""
AdoptionTracer command-line interface.

Usage:
    python -m adoptiontracer scan   --config artifacts.yaml --output results/
    python -m adoptiontracer index  --config artifacts.yaml --output results/
    python -m adoptiontracer lookup --config artifacts.yaml --arxiv 1312.6199
"""

import argparse
import logging
import sys
from pathlib import Path

from .clone import clone_or_update
from .config import load_config
from .extract import extract
from .resolve import resolve
from .trace import trace
from .analyze import analyze, write_results


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def cmd_scan(args):
    """Full pipeline: clone → extract → resolve → trace → analyze → write."""
    config = load_config(args.config)
    output_dir = Path(args.output)

    print(f"AdoptionTracer v0.1.0 — Scanning {len(config.artifacts)} artifacts")
    print(f"  Repos dir: {config.repos_dir}")
    print(f"  Output:    {output_dir}")
    print()

    # Stage 0: Auto-clone / update artifact repos
    has_urls = any(a.github_url for a in config.artifacts)
    if has_urls:
        print("=" * 60)
        print("STAGE 0: Cloning / updating artifact repositories")
        print("=" * 60)
        def _on_clone_progress(name, status):
            print(f"  {name}: {status}", flush=True)
        clone_or_update(config, progress_callback=_on_clone_progress)
        print()

    # Stage 1: Extract paper references from repos
    print("=" * 60)
    print("STAGE 1: Extracting paper references from repositories")
    print("=" * 60)
    extraction = extract(config)
    print(f"  → {len(extraction.unique_ids)} unique papers from "
          f"{len(extraction.references)} total references\n")

    # Stage 2: Resolve paper metadata from arXiv
    print("=" * 60)
    print("STAGE 2: Resolving paper metadata from arXiv API")
    print("=" * 60)
    cache_path = output_dir / ".cache" / "arxiv_metadata.json"
    metadata = resolve(extraction.unique_ids, cache_path=cache_path)
    valid = sum(1 for m in metadata.values() if m.valid)
    print(f"  → {valid} papers resolved successfully\n")

    # Stage 3: Trace adoption timestamps via Git archaeology
    print("=" * 60)
    print("STAGE 3: Tracing adoption timestamps via Git history")
    print("=" * 60)
    traces = trace(config, extraction)
    papers_with_events = len({e.arxiv_id for e in traces.events})
    print(f"  → {len(traces.events)} adoption events for "
          f"{papers_with_events} papers\n")

    # Stage 4: Analyze and write results
    print("=" * 60)
    print("STAGE 4: Computing adoption lags and writing results")
    print("=" * 60)
    result = analyze(config, extraction, metadata, traces)
    stats = write_results(result, output_dir)

    # Summary
    print()
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    if stats:
        print(f"  Total papers extracted:  {stats['n_papers_total']}")
        print(f"  Papers in study sample:  {stats['n_papers_selected']}")
        scope = stats.get("lag_stats_scope", "")
        if scope == "all_extracted" and stats.get("n_with_lag_selected", 0) == 0:
            print(f"  Papers with adoption lag (extracted, study sample empty): {stats.get('n_with_lag_extracted', stats.get('n_with_lag', 0))}")
            print(f"  (Lag summary uses all extracted papers; tighten selection or add artifacts for study-sample stats.)")
        else:
            print(f"  Papers with adoption data: {stats.get('n_with_lag_selected', stats.get('n_with_lag', 0))}")
        if stats.get("lag_stats_scope") not in ("none", ""):
            print()
            print(f"  Adoption lag (months), scope={stats['lag_stats_scope']}:")
            print(f"    Median:  {stats['median_months']:.1f}")
            print(f"    Mean:    {stats['mean_months']:.1f}")
            print(f"    IQR:     {stats['q1_months']:.1f} – {stats['q3_months']:.1f}")
            print(f"    Range:   {stats['min_months']:.1f} – {stats['max_months']:.1f}")
    else:
        print("  No adoption lag data computed.")

    print(f"\n  Output files in: {output_dir}/")
    print(f"    papers_all.csv       — all {stats.get('n_papers_total', 0)} extracted papers")
    print(f"    papers_selected.csv  — {stats.get('n_papers_selected', 0)} study sample papers")
    print(f"    summary.json         — summary statistics")


def cmd_lookup(args):
    """Look up adoption status for a specific paper."""
    config = load_config(args.config)
    arxiv_id = args.arxiv.strip()

    print(f"AdoptionTracer — Looking up adoption for arXiv:{arxiv_id}")
    print()

    # Extract all references (we need full context to check)
    extraction = extract(config)

    if arxiv_id not in extraction.arxiv_to_artifacts:
        print(f"  Paper arXiv:{arxiv_id} was NOT found in any artifact.")
        print(f"  This paper has no detected adoption in the configured artifacts.")
        return

    artifacts = sorted(extraction.arxiv_to_artifacts[arxiv_id])
    print(f"  Found in {len(artifacts)} artifact(s): {', '.join(artifacts)}")
    print()

    # Resolve metadata
    metadata = resolve([arxiv_id])
    meta = metadata.get(arxiv_id)
    if meta and meta.valid:
        print(f"  Title:     {meta.title}")
        print(f"  Authors:   {meta.authors}")
        print(f"  Published: {meta.pub_date}")
        print()

    # Trace adoption dates — only for the requested paper
    from .trace import _trace_artifact, TraceResult, AdoptionEvent
    artifact_map = {a.name: a for a in config.artifacts}
    events: list[AdoptionEvent] = []

    refs_by_artifact: dict[str, list] = {}
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
            events.append(event)

    events.sort(key=lambda e: e.date)

    if events:
        print("  Adoption timeline:")
        for event in events:
            lag = ""
            if meta and meta.valid and meta.pub_date:
                from .analyze import _compute_lag
                months = _compute_lag(meta.pub_date, event.date)
                if months is not None:
                    lag = f" (lag: {months:.1f} months)"
            print(f"    {event.date}  {event.artifact_name} [{event.artifact_type}]{lag}")
    else:
        print("  No adoption timestamps found in Git history.")


def _default_config() -> str:
    """Path to the built-in artifacts.yaml shipped with the package."""
    return str(Path(__file__).parent / "artifacts.yaml")


def main():
    default_cfg = _default_config()

    parser = argparse.ArgumentParser(
        prog="adoptiontracer",
        description="AdoptionTracer: Measure research-to-practice adoption lag "
                    "through artifact-anchored backward traceability.",
        epilog="Examples:\n"
               "  adoptiontracer scan                         # scan default 9 AML artifacts\n"
               "  adoptiontracer scan -c my_artifacts.yaml    # scan custom artifacts\n"
               "  adoptiontracer lookup --arxiv 1312.6199     # check one paper\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan command
    scan_parser = subparsers.add_parser(
        "scan",
        help="Full pipeline: clone repos, extract papers, trace adoption, compute lags",
    )
    scan_parser.add_argument(
        "--config", "-c", default=default_cfg,
        help=f"Path to artifacts.yaml (default: built-in 9 AML artifacts)",
    )
    scan_parser.add_argument(
        "--output", "-o", default="results",
        help="Output directory for results (default: results/)",
    )

    # lookup command
    lookup_parser = subparsers.add_parser(
        "lookup",
        help="Look up adoption status for a specific arXiv paper",
    )
    lookup_parser.add_argument(
        "--config", "-c", default=default_cfg,
        help=f"Path to artifacts.yaml (default: built-in 9 AML artifacts)",
    )
    lookup_parser.add_argument(
        "--arxiv", "-a", required=True,
        help="arXiv ID to look up (e.g., 1312.6199)",
    )

    args = parser.parse_args()
    if args.command == "lookup" and not args.verbose:
        setup_logging(verbose=False)
        logging.getLogger("adoptiontracer").setLevel(logging.WARNING)
    else:
        setup_logging(args.verbose)

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "lookup":
        cmd_lookup(args)
