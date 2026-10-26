# Data

Frozen inputs for `analysis/reproduce.py` and `analysis/figures.py`. All dates
are ISO 8601; all lags are months (days / 30.44) from the paper's first arXiv
posting to the integration event. The observation cutoff is 2025-01-31.

Artifacts: CleverHans, IBM ART, TextAttack, PyRIT, Foolbox (tools);
RobustBench, AutoAttack, HarmBench (benchmarks); MITRE ATLAS (regulatory).

## Integration events

| File | Rows | Description |
|---|---|---|
| `events/<artifact>.csv` | 9 files | Every first introduction of an arXiv identifier into a file of the artifact, from a single pass over the full Git history (`adoptiontracer events`). Columns: `arxiv_id, artifact, file, author_date, commit_date, commit`. |
| `events_extra/<artifact>.csv` | 3 files | Same for torchattacks, advertorch, and DeepRobust, used only in the extra-artifact sensitivity check. |
| `pool_261_first_events.csv` | 261 | Candidate pool: one row per paper with its earliest event across the nine artifacts. `ad` event author date, `pub` arXiv v1 date, `lag`. |
| `partition_69_192.csv` | 261 | Pool split into the 69 cross-validated papers (`cross_validated` true: cited by two or more artifacts, or by MITRE ATLAS, with a first event inside the observation window) and the other 192. |
| `first_events_69.csv` | 69 | First event per cross-validated paper with file class `fclass` (code, doc, other) and artifact type `typ`. |
| `paper_artifact_events_69.csv` | 149 | First event per (paper, artifact) pair for the 69, used for pathway sequencing. |
| `code_events_159.csv` | 159 | Pool papers with a commit touching a source-code file by the cutoff. `first_any` first event of any kind, `first_code` first code-file event, `gap_months` between them. |
| `redated_27.csv` | 27 | Cross-validated papers whose lag differs by more than one month between the submission's per-artifact extraction (`lag_frozen`) and the uniform history pass (`lag_uniform`). |

## Coded sample

| File | Rows | Description |
|---|---|---|
| `papers_71_coded.csv` | 71 | The cross-validated sample as submitted, with the final human-coded variables. `G1` contribution type, `G2` threat category (NIST AI 100-2), `G3` domain, `G4` venue type, `G5` code available, `G6` code timing, `T1` access level, `T2` gradient use, `Q1` real-world testing. `first_adoption_*` and `adoption_lag_months` are the submission's dates; the uniform re-extraction is in `first_events_69.csv`. |
| `candidates_286.csv` | 286 | All arXiv identifiers extracted from the artifact snapshots before the adversarial-ML relevance screen (`is_aml_paper`). |
| `coding/coder_A.csv`, `coder_B.csv`, `coder_C.csv` | 71 each | Raw annotation sheets of the three coders as recorded (casing, whitespace, and free-text venue names left untouched). `coder_A` is the reconciled master after consensus between the two primary coders; `coder_C` is the independent reliability rater. |

## Code-availability exposure

| File | Rows | Description |
|---|---|---|
| `arxiv_meta.csv` | 286 | arXiv metadata re-fetched for the candidates: `published`, `updated`, `title`, `code_latest` (1 if the latest-version comment or abstract carries a repository URL), `comment_latest`. |
| `exposure_ledger_23.csv` | 23 | Version-history audit of every metadata-URL match among the 71. `category`: `v1` (URL present in version 1, 8), `zero_lag_excluded` (3), `pre_integration` (URL added before the first event, 6), `leaked_post_integration` (added after it, 6). |
| `case_control_138.csv` | 138 | Matched case-control sample with controls re-drawn by the deterministic procedure in the paper (67 integrated papers, 71 controls). `time` months, `event`, `pub_year`, domain and venue indicators, `code_url` metadata-URL exposure, `code_pwc` Papers with Code official repository. |

## Population frame

| File | Rows | Description |
|---|---|---|
| `frame_cohort_9297.csv.gz` | 9,297 | Every arXiv paper returned by Semantic Scholar for the eleven adversarial-ML phrases (`matched_keyword`), 2013-2024. `pub` arXiv date, `event` 1 if the paper has an event in any of the nine artifacts by the cutoff, `event_date`, `dur` months to event or censoring, `official` Papers with Code official repository, `anyrepo` any linked repository, `venue`, `types`, `year_c` centred year. |

## Reproducibility note

`events/` can be regenerated with `adoptiontracer events -o events/`. Because the
upstream repositories are live, a fresh scan can differ from the frozen files
when their history is rewritten; PyRIT's public history was squashed between the
submission and the uniform re-extraction. The paper reports the frozen files.
