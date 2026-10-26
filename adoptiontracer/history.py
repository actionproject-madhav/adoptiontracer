"""Stream a repository's full history once and record every first introduction
of an arXiv identifier.

This is the dating method used in the paper: the event for a (paper, file)
pair is the earliest commit on any branch whose added lines contain the
paper's identifier, timestamped by author date so that rebases and
force-pushes that rewrite committer metadata do not move it.
"""

import csv
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_ARGS = [
    "log", "--all", "--reverse", "--no-renames", "--unified=0",
    "--date=iso-strict", "--format=COMMIT%x09%H%x09%ad%x09%cd", "-p",
]


@dataclass
class IntroductionEvent:
    arxiv_id: str
    file: str
    author_date: str   # ISO 8601
    commit_date: str   # ISO 8601
    commit: str


def _ids_in(text: str, patterns: list[re.Pattern]) -> set[str]:
    found = set()
    for p in patterns:
        for m in p.finditer(text):
            found.add(m.group(1))
    return found


def scan_history(repo_path: Path, patterns: list[re.Pattern],
                 timeout: int = 3600) -> list[IntroductionEvent]:
    """Return the first introduction of every (arxiv_id, file) pair in the repo.

    The patch stream is read line by line; only added lines are inspected.
    """
    proc = subprocess.Popen(
        ["git", "-C", str(repo_path)] + LOG_ARGS,
        stdout=subprocess.PIPE, text=True, errors="ignore", bufsize=1 << 20,
    )
    seen: set[tuple[str, str]] = set()
    events: list[IntroductionEvent] = []
    cur_hash = cur_ad = cur_cd = ""
    cur_file: str | None = None
    try:
        for line in proc.stdout:
            if line.startswith("COMMIT\t"):
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 4:
                    cur_hash, cur_ad, cur_cd = parts[1], parts[2], parts[3]
                cur_file = None
            elif line.startswith("+++ "):
                p = line[4:].strip()
                cur_file = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            elif line.startswith("+") and not line.startswith("+++"):
                if "rxiv" not in line and "eprint" not in line.lower():
                    continue
                for aid in _ids_in(line, patterns):
                    key = (aid, cur_file or "")
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append(IntroductionEvent(aid, cur_file or "", cur_ad, cur_cd, cur_hash))
    finally:
        proc.stdout.close()
        proc.wait(timeout=timeout)
    if proc.returncode != 0:
        logger.warning("git log exited with %d for %s", proc.returncode, repo_path.name)
    return events


def write_events(events: list[IntroductionEvent], artifact: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arxiv_id", "artifact", "file", "author_date", "commit_date", "commit"])
        for e in events:
            w.writerow([e.arxiv_id, artifact, e.file, e.author_date, e.commit_date, e.commit])
