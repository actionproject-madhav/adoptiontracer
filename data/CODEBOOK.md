# Codebook

Variables coded by hand for the 71 cross-validated papers in
`papers_71_coded.csv`. Each paper was read in full (arXiv version current in
January 2025) together with its linked repository, if any. Three coders labeled
every paper independently; two primary coders reconciled disagreements by
consensus against these definitions, and the third coder's labels were used
only to measure reliability. Multi-label fields use `/` as separator and list
components in order of emphasis; the first component is the primary label used
in tables and tests. Blank means not applicable.

## Research characteristics

**G1 Contribution type.** What the paper contributes.
`Attack` proposes or improves an attack; `Defense` proposes or improves a
defense or robust training method; `Evaluation` contributes a benchmark,
evaluation protocol, or empirical study without a new attack or defense.
Papers with several contributions list all, primary first
(for example `Attack/Evaluation`).

**G2 Threat category.** NIST AI 100-2 category of the threat the paper addresses.
`Evasion` test-time input perturbation; `Poisoning` training-time corruption,
including backdoors; `Privacy` extraction of training data or model
information. Blank for papers whose contribution does not target a single
category (most defense and evaluation papers).

**G3 Domain.** Data modality the method is developed and evaluated on.
`Vision`, `NLP` (text models other than LLMs), `LLM`, `Audio`, `Malware`,
or `Cross-domain` when the paper evaluates on two or more modalities with
no primary one.

**G4 Venue type.** Where the paper was published.
`ML` machine learning or vision conference or journal (NeurIPS, ICML, ICLR,
CVPR, ICCV, ECCV, AAAI, IJCAI, ACL, EMNLP, JMLR, TMLR and similar);
`Security` security venue (IEEE S&P, CCS, USENIX Security, NDSS, SaTML,
AISec and similar); `arXiv-only` no peer-reviewed venue found.

**G5 Author-released code.** `Yes` if the authors released runnable
implementation code at a URL reachable in January 2025 (the paper, its arXiv
page, or an author's public repository points to it); `No` otherwise.
Third-party implementations do not count here; they are counted in the
"any public implementation" measure, which is taken from the Papers with Code
index and reported separately in the paper.

**G6 Code timing.** For `G5 = Yes`, `At-pub` if the repository's first public
commit or release is within 30 days of the paper's first public availability,
`Post-pub` if later. `Never` when `G5 = No`.

## Threat model (attack papers only)

**T1 Access level.** Attacker's access to the target model.
`White` full access to parameters and gradients; `Black` query access only;
`Gray` partial knowledge (for example architecture or training data).
Papers evaluating several settings list all, primary first.

**T2 Gradient use.** `Yes` if the attack uses gradients of the target or a
surrogate model; `No` otherwise.

## Practical evaluation

**Q1 Real-world testing.** `Yes` if the paper evaluates against a deployed
production system or commercial API (for example a cloud vision API or a
released chat assistant); `No` if evaluation is confined to research models
and standard datasets. Blank where the coders could not determine this.

## Identifiers and dates

`arxiv_id` arXiv identifier. `paper_pub_date` first arXiv submission date.
`found_in_artifacts`, `num_artifacts`, `first_adoption_date`,
`first_adoption_artifact`, `all_adoptions`, `adoption_lag_months` are the
integration events as extracted at the time of the submission; the uniform
re-extraction used for the paper's lag statistics is in `first_events_69.csv`.
`selection_reason` records why the paper entered the cross-validated subset
(`2+ artifacts` or `MITRE ATLAS (regulatory)`).
