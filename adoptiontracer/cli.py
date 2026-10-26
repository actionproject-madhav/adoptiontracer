"""Command-line interface.

    adoptiontracer scan   --config artifacts.yaml --output results/
    adoptiontracer lookup --config artifacts.yaml --arxiv 1312.6199
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


def _stage(title: str):
    print(f"\n== {title}")


def cmd_scan(args):
    """Full pipeline: clone, extract, resolve, trace, analyze, write."""
    config = load_config(args.config)
    output_dir = Path(args.output)

    print(f"adoptiontracer: {len(config.artifacts)} artifacts")
    print(f"  repos dir: {config.repos_dir}")
    print(f"  output:    {output_dir}")

    # Stage 0: clone or update artifact repos
    has_urls = any(a.github_url for a in config.artifacts)
    if has_urls:
        _stage("Cloning or updating artifact repositories")
        def _on_clone_progress(name, status):
            print(f"  {name}: {status}", flush=True)
        clone_or_update(config, progress_callback=_on_clone_progress)
        print()

    # Stage 1: extract paper references
    _stage("Extracting paper references")
    extraction = extract(config)
    print(f"  {len(extraction.unique_ids)} unique papers from "
          f"{len(extraction.references)} references")

    # Stage 2: resolve paper metadata
    _stage("Resolving paper metadata from the arXiv API")
    cache_path = output_dir / ".cache" / "arxiv_metadata.json"
    metadata = resolve(extraction.unique_ids, cache_path=cache_path)
    valid = sum(1 for m in metadata.values() if m.valid)
    print(f"  {valid} papers resolved")

    # Stage 3: date first integration
    _stage("Dating first integration from Git history")
    traces = trace(config, extraction)
    papers_with_events = len({e.arxiv_id for e in traces.events})
    print(f"  {len(traces.events)} integration events for "
          f"{papers_with_events} papers")

    # Stage 4: compute lags and write results
    _stage("Computing integration lags")
    result = analyze(config, extraction, metadata, traces)
    stats = write_results(result, output_dir)

    _stage("Summary")
    if stats:
        print(f"  Total papers extracted:  {stats['n_papers_total']}")
        print(f"  Papers in study sample:  {stats['n_papers_selected']}")
        scope = stats.get("lag_stats_scope", "")
        if scope == "all_extracted" and stats.get("n_with_lag_selected", 0) == 0:
            print(f"  Papers with a lag (all extracted; study sample empty): {stats.get('n_with_lag_extracted', stats.get('n_with_lag', 0))}")
            print("  (lag summary uses all extracted papers)")
        else:
            print(f"  Papers with a lag:       {stats.get('n_with_lag_selected', stats.get('n_with_lag', 0))}")
        if stats.get("lag_stats_scope") not in ("none", ""):
            print()
            print(f"  Integration lag (months), scope={stats['lag_stats_scope']}:")
            print(f"    Median:  {stats['median_months']:.1f}")
            print(f"    Mean:    {stats['mean_months']:.1f}")
            print(f"    IQR:     {stats['q1_months']:.1f}-{stats['q3_months']:.1f}")
            print(f"    Range:   {stats['min_months']:.1f}-{stats['max_months']:.1f}")
    else:
        print("  No lags computed.")

    print(f"\n  Output in {output_dir}/: papers_all.csv, papers_selected.csv, summary.json")


def cmd_lookup(args):
    """Report where and when one paper was integrated."""
    config = load_config(args.config)
    arxiv_id = args.arxiv.strip()

    print(f"arXiv:{arxiv_id}")
    print()

    # Extract all references (we need full context to check)
    extraction = extract(config)

    if arxiv_id not in extraction.arxiv_to_artifacts:
        print("  not found in any configured artifact")
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

    # Date the requested paper only
    from .trace import _trace_artifact, _trace_history, AdoptionEvent
    from .extract import _compile_patterns
    artifact_map = {a.name: a for a in config.artifacts}
    patterns = _compile_patterns(config)
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
        if artifact.git_search_mode == "history":
            events.extend(_trace_history(artifact, repo_path, {arxiv_id}, patterns))
        else:
            event = _trace_artifact(arxiv_id, artifact, repo_path, refs)
            if event:
                events.append(event)

    events.sort(key=lambda e: e.date)

    if events:
        print("  Integration timeline:")
        for event in events:
            lag = ""
            if meta and meta.valid and meta.pub_date:
                from .analyze import _compute_lag
                months = _compute_lag(meta.pub_date, event.date)
                if months is not None:
                    lag = f" (lag: {months:.1f} months)"
            print(f"    {event.date}  {event.artifact_name} [{event.artifact_type}]{lag}")
    else:
        print("  no introduction found in Git history")


def _default_config() -> str:
    """Path to the built-in artifacts.yaml shipped with the package."""
    return str(Path(__file__).parent / "artifacts.yaml")


def main():
    default_cfg = _default_config()

    parser = argparse.ArgumentParser(
        prog="adoptiontracer",
        description="Measure research-to-practice integration lag from the Git "
                    "history of practitioner artifacts.",
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
        help="Clone repos, extract papers, date first integration, compute lags",
    )
    scan_parser.add_argument(
        "--config", "-c", default=default_cfg,
        help="Path to artifacts.yaml (default: the nine AML artifacts)",
    )
    scan_parser.add_argument(
        "--output", "-o", default="results",
        help="Output directory for results (default: results/)",
    )

    # lookup command
    lookup_parser = subparsers.add_parser(
        "lookup",
        help="Report where and when one arXiv paper was integrated",
    )
    lookup_parser.add_argument(
        "--config", "-c", default=default_cfg,
        help="Path to artifacts.yaml (default: the nine AML artifacts)",
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
