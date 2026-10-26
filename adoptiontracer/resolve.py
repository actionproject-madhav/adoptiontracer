"""
Resolve paper metadata from arXiv API.

Takes a list of arXiv IDs and fetches titles, authors, and
publication dates. Results are cached to avoid redundant API calls.
"""

import json
import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
BATCH_SIZE = 20
RATE_LIMIT_SECONDS = 0.4


@dataclass
class PaperMetadata:
    arxiv_id: str
    title: str
    authors: str
    pub_date: str  # YYYY-MM-DD (first arXiv submission)
    valid: bool = True


def _fetch_batch(arxiv_ids: list[str]) -> list[PaperMetadata]:
    """Fetch metadata for a batch of arXiv IDs in one API call."""
    id_list = ",".join(arxiv_ids)
    url = f"{ARXIV_API}?id_list={id_list}&max_results={len(arxiv_ids)}"

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read().decode("utf-8")
    except Exception as e:
        logger.warning("arXiv API error for batch: %s", e)
        return [PaperMetadata(aid, "", "", "", valid=False) for aid in arxiv_ids]

    root = ET.fromstring(data)
    entries = root.findall("atom:entry", ATOM_NS)

    results = []
    for entry in entries:
        id_elem = entry.find("atom:id", ATOM_NS)
        if id_elem is None:
            continue

        raw_id = id_elem.text.strip().split("/abs/")[-1]
        # Strip version suffix (e.g., "2302.10149v2" -> "2302.10149")
        arxiv_id = raw_id.split("v")[0] if "v" in raw_id else raw_id

        title_elem = entry.find("atom:title", ATOM_NS)
        title = title_elem.text.strip().replace("\n", " ") if title_elem is not None else ""

        if not title or "Error" in title:
            results.append(PaperMetadata(arxiv_id, "", "", "", valid=False))
            continue

        authors = []
        for author in entry.findall("atom:author", ATOM_NS):
            name = author.find("atom:name", ATOM_NS)
            if name is not None:
                authors.append(name.text)
        author_str = "; ".join(authors[:5])
        if len(authors) > 5:
            author_str += "..."

        pub_elem = entry.find("atom:published", ATOM_NS)
        pub_date = pub_elem.text[:10] if pub_elem is not None else ""

        results.append(PaperMetadata(
            arxiv_id=arxiv_id,
            title=title,
            authors=author_str,
            pub_date=pub_date,
        ))

    return results


def resolve(
    arxiv_ids: list[str],
    cache_path: Path | None = None,
) -> dict[str, PaperMetadata]:
    """
    Resolve metadata for a list of arXiv IDs.

    Uses the arXiv API with batching and rate-limiting.
    Optionally caches results to a JSON file to avoid re-fetching.

    Returns a dict mapping arxiv_id -> PaperMetadata.
    """
    cache: dict[str, PaperMetadata] = {}
    if cache_path and cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            for aid, entry in raw.items():
                cache[aid] = PaperMetadata(**entry)
            logger.info("Loaded %d cached paper metadata entries", len(cache))
        except Exception:
            logger.warning("Cache file corrupted, starting fresh")

    to_fetch = [aid for aid in arxiv_ids if aid not in cache]
    logger.info("Resolving %d papers (%d cached, %d to fetch)",
                len(arxiv_ids), len(arxiv_ids) - len(to_fetch), len(to_fetch))

    for i in range(0, len(to_fetch), BATCH_SIZE):
        batch = to_fetch[i:i + BATCH_SIZE]
        logger.info("  Fetching batch %d-%d of %d...",
                     i + 1, min(i + BATCH_SIZE, len(to_fetch)), len(to_fetch))

        results = _fetch_batch(batch)
        for meta in results:
            cache[meta.arxiv_id] = meta

        # Retry any failures individually
        for aid in batch:
            if aid not in cache or not cache[aid].valid:
                time.sleep(RATE_LIMIT_SECONDS)
                retry = _fetch_batch([aid])
                if retry and retry[0].valid:
                    cache[retry[0].arxiv_id] = retry[0]

        time.sleep(RATE_LIMIT_SECONDS)

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            aid: {
                "arxiv_id": m.arxiv_id, "title": m.title,
                "authors": m.authors, "pub_date": m.pub_date,
                "valid": m.valid,
            }
            for aid, m in cache.items()
        }
        cache_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        logger.info("Cached %d entries to %s", len(cache), cache_path)

    return {aid: cache.get(aid, PaperMetadata(aid, "", "", "", valid=False))
            for aid in arxiv_ids}
