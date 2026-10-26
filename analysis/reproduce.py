#!/usr/bin/env python3
"""Recompute every statistic reported in the paper from the frozen files in data/.

Run:  python analysis/reproduce.py > results.txt

Inputs are read-only; see data/README.md for the schema of each file.
"""
import glob
import os
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from lifelines import CoxPHFitter, KaplanMeierFitter
import statsmodels.api as sm
import statsmodels.formula.api as smf

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
E = DATA_DIR
L = DATA_DIR
D = DATA_DIR
CUT = pd.Timestamp("2025-01-31")
TOOLS = {"CleverHans", "Foolbox", "IBM ART", "TextAttack", "PyRIT"}
BENCH = {"RobustBench", "AutoAttack", "HarmBench"}


def typ(a):
    return "Tool" if a in TOOLS else "Benchmark" if a in BENCH else "Regulatory"


def q(s):
    return f"median {s.median():.1f} IQR [{s.quantile(.25):.1f}, {s.quantile(.75):.1f}] mean {s.mean():.1f} sd {s.std():.1f} range [{s.min():.1f}, {s.max():.1f}] n={len(s)}"


def section(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ---------------------------------------------------------------- RQ1
section("RQ1  uniform candidate pool (primary)")
pool = pd.read_csv(f"{L}/pool_261_first_events.csv", dtype={"arxiv_id": str})
pool["ad"] = pd.to_datetime(pool.ad)
pool["pub"] = pd.to_datetime(pool.pub)
print("pool:", q(pool.lag))
print(f"  within 6 mo {100*(pool.lag<=6).mean():.0f}%  within 12 mo {100*(pool.lag<=12).mean():.0f}%  within 24 mo {100*(pool.lag<=24).mean():.0f}%  negative lags {(pool.lag<0).sum()}")

part = pd.read_csv(f"{L}/partition_69_192.csv", dtype={"arxiv_id": str})
cv = part[part.cross_validated].lag
rest = part[~part.cross_validated].lag
print("cross-validated 69 (uniform dates):", q(cv))
print("other 192:", q(rest))
u, p = stats.mannwhitneyu(cv, rest, alternative="two-sided")
print(f"  MW two-sided U={u:.1f} p={p:.3f}")

# year-stratified: van Elteren (stratified Wilcoxon) + stratified permutation of the median difference
part = part.merge(pool[["arxiv_id", "pub"]], on="arxiv_id")
part["year"] = part.pub.dt.year
num = den = 0.0
for _, g in part.groupby("year"):
    if g.cross_validated.nunique() < 2:
        continue
    r = stats.rankdata(g.lag)
    n1, n = g.cross_validated.sum(), len(g)
    w = r[g.cross_validated.values].sum()
    ew = n1 * (n + 1) / 2
    vw = n1 * (n - n1) * (n + 1) / 12
    num += (w - ew) / (n + 1)
    den += vw / (n + 1) ** 2
z = num / np.sqrt(den)
print(f"  van Elteren year-stratified z={z:.2f} p={2*stats.norm.sf(abs(z)):.3f}")

frozen = pd.read_csv(f"{D}/papers_71_coded.csv", dtype=str)
frozen["arxiv_id"] = frozen.arxiv_id.str.strip()
frozen["lag"] = frozen.adoption_lag_months.astype(float)
print("submitted 71 (frozen dates):", q(frozen.lag))
f69 = frozen[frozen.arxiv_id.str.strip().isin(set(part[part.cross_validated].arxiv_id))]
print("submitted 69 in-window (frozen dates):", q(f69.lag))
missing2 = sorted(set(frozen.arxiv_id.str.strip()) - set(part[part.cross_validated].arxiv_id))
print("  the two post-cutoff ATLAS-only papers:", missing2,
      frozen[frozen.arxiv_id.str.strip().isin(missing2)][["first_adoption_artifact", "first_adoption_date"]].values.tolist())
red = pd.read_csv(f"{L}/redated_27.csv", dtype={"arxiv_id": str})
print(f"  re-dated >1 mo between passes: {len(red)}/69; agree within 1 mo: {69-len(red)}")

# ---------------------------------------------------------------- per-artifact-type
section("RQ1  per-event lag by artifact type (uniform pass)")
ev = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(f"{E}/events/*.csv")], ignore_index=True)
ev["ad"] = pd.to_datetime(ev.author_date, utc=True, format="ISO8601", errors="coerce").dt.tz_localize(None)
ev = ev.dropna(subset=["ad"])
ev = ev[ev.ad <= CUT]
ev["typ"] = ev.artifact.map(typ)
pubmap = dict(zip(pool.arxiv_id, pool.pub))
pa = ev[ev.arxiv_id.isin(pubmap)].sort_values("ad").groupby(["arxiv_id", "artifact"]).first().reset_index()
pa["pub"] = pa.arxiv_id.map(pubmap)
pa["lag"] = (pa.ad - pa.pub).dt.days / 30.44
pa["typ"] = pa.artifact.map(typ)
ids69 = set(part[part.cross_validated].arxiv_id)


def type_table(d, label):
    print(f"[{label}] paper-artifact first events n={len(d)}")
    for t in ["Tool", "Benchmark", "Regulatory"]:
        g = d[d.typ == t].lag
        print(f"  {t:11s} n={len(g):3d} median {g.median():5.1f} IQR [{g.quantile(.25):.1f}, {g.quantile(.75):.1f}]")
    groups = [d[d.typ == t].lag.values for t in ["Tool", "Benchmark", "Regulatory"]]
    H, pk = stats.kruskal(*groups)
    print(f"  Kruskal-Wallis H={H:.2f} p={pk:.4f}")
    names = ["Tool", "Benchmark", "Regulatory"]
    for i in range(3):
        for j in range(i + 1, 3):
            _, pm = stats.mannwhitneyu(groups[i], groups[j], alternative="two-sided")
            print(f"    {names[i]} vs {names[j]}: MW p={pm:.4f} Bonferroni(3) p={min(1, 3*pm):.4f}")
    for a in sorted(d.artifact.unique()):
        g = d[d.artifact == a].lag
        print(f"    {a:12s} n={len(g):3d} median {g.median():5.1f}")


type_table(pa, "pool 261")
type_table(pa[pa.arxiv_id.isin(ids69)], "cross-validated 69")

# ---------------------------------------------------------------- pathways
section("Integration pathways (uniform pass)")
for label, d in [("pool 261", pa), ("cross-validated 69", pa[pa.arxiv_id.isin(ids69)])]:
    multi = d.groupby("arxiv_id").filter(lambda g: len(g) >= 2).sort_values("ad")
    n_multi = multi.arxiv_id.nunique()
    firsts = multi.groupby("arxiv_id").first()
    fc = firsts.typ.value_counts()
    print(f"[{label}] multi-artifact papers {n_multi}/{d.arxiv_id.nunique()}; first integrator: " +
          ", ".join(f"{k} {v} ({100*v/n_multi:.0f}%)" for k, v in fc.items()))
    seqs = []
    for pid, g in multi.groupby("arxiv_id"):
        g = g.sort_values("ad")
        seqs.append((g.typ.iloc[0], g.typ.iloc[1], (g.ad.iloc[1] - g.ad.iloc[0]).days / 30.44))
    sq = pd.DataFrame(seqs, columns=["a", "b", "gap"])
    tr = sq.groupby(["a", "b"]).gap.agg(["count", "median"]).reset_index()
    tr["pct"] = 100 * tr["count"] / len(sq)
    print(tr.sort_values("count", ascending=False).to_string(index=False))

# ---------------------------------------------------------------- code-level tier
section("Code-level tier")
code = pd.read_csv(f"{L}/code_events_159.csv", dtype={"arxiv_id": str})
print(f"pool papers with a code-file event by cutoff: {len(code)}/261 = {100*len(code)/261:.0f}%")
print(f"  code commit is the first event (gap=0): {(code.gap_months==0).sum()} ({100*(code.gap_months==0).mean():.0f}%);"
      f" gap<=1 mo: {(code.gap_months<=1).sum()} ({100*(code.gap_months<=1).mean():.0f}%); gap 75th pct {code.gap_months.quantile(.75):.1f}; median {code.gap_months.median():.1f}")
code["first_code"] = pd.to_datetime(code.first_code)
pool_c = pool.merge(code[["arxiv_id", "first_code"]], on="arxiv_id", how="left")
pool_c["event"] = pool_c.first_code.notna().astype(int)
pool_c["dur"] = np.where(pool_c.event == 1, (pool_c.first_code - pool_c.pub).dt.days / 30.44, (CUT - pool_c.pub).dt.days / 30.44)
pool_c["dur"] = pool_c.dur.clip(lower=0.01)
km = KaplanMeierFitter().fit(pool_c.dur, pool_c.event)
print(f"  KM median code-level lag, pool: {km.median_survival_time_:.1f} mo; 24-mo cumulative incidence {100*(1-km.survival_function_at_times(24).values[0]):.0f}%")
sub = pool_c[pool_c.arxiv_id.isin(ids69)]
km69 = KaplanMeierFitter().fit(sub.dur, sub.event)
print(f"  cross-validated 69: code events {int(sub.event.sum())}/69 = {100*sub.event.mean():.0f}%; KM median {km69.median_survival_time_}; 24-mo cumulative incidence {100*(1-km69.survival_function_at_times(24).values[0]):.0f}%")
print(f"  among papers with code events: median lag to first code, pool {sub.dur[sub.event==1].median():.1f} (69) / {pool_c.dur[pool_c.event==1].median():.1f} (pool)")

# ---------------------------------------------------------------- first-event file class (precision audit) on 69
section("Precision audit (file class of first event), cross-validated 69")
f69u = pd.read_csv(f"{E}/first_events_69.csv", dtype={"arxiv_id": str})
print(f69u.fclass.value_counts().to_dict(), f"n={len(f69u)}")
d69 = ev[ev.arxiv_id.isin(ids69)]
CODE_EXT = {'py', 'ipynb', 'js', 'ts', 'cc', 'cpp', 'c', 'h', 'hpp', 'java', 'sh', 'r', 'jl', 'cs', 'go', 'rs', 'm'}
d69 = d69.assign(ext=d69.file.str.lower().str.rsplit(".", n=1).str[-1])
print(f"  any code-file event: {d69[d69.ext.isin(CODE_EXT)].arxiv_id.nunique()}/69")

# ---------------------------------------------------------------- leakage
section("Temporal-leakage audit of the metadata-URL rule")
led = pd.read_csv(f"{L}/exposure_ledger_23.csv", dtype={"arxiv_id": str})
print(led.category.value_counts().to_dict(), "(zero_lag_excluded papers all had the URL at v1)")
leaked = set(led[led.category == "leaked_post_integration"].arxiv_id.astype(str))
am = pd.read_csv(f"{E}/arxiv_meta.csv", dtype=str)
url71 = am[am.arxiv_id.isin(set(frozen.arxiv_id.str.strip()))]
print(f"  URL rule matches among the 71 at re-fetch: {url71.code_latest.astype(int).sum()}/71")

# ---------------------------------------------------------------- extra artifacts
section("Extra artifacts (torchattacks, advertorch, DeepRobust)")
ex = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(f"{E}/events_extra/*.csv")], ignore_index=True)
ex["ad"] = pd.to_datetime(ex.author_date, utc=True, format="ISO8601", errors="coerce").dt.tz_localize(None)
ex = ex[ex.ad <= CUT]
exf = ex.sort_values("ad").groupby("arxiv_id").ad.min()
u69 = f69u.copy()
u69["ad"] = pd.to_datetime(u69.ad)
u69["ad_extra"] = u69.arxiv_id.astype(str).map(exf)
moves = u69.ad_extra.notna() & (u69.ad_extra < u69.ad)
earlier = u69[moves]
u69["lag12"] = np.where(moves, (u69.ad_extra - pd.to_datetime(u69.pub)).dt.days / 30.44, u69.lag)
print(f"  papers whose first date moves earlier: {len(earlier)}/69; median lag 9 artifacts {u69.lag.median():.1f} -> 12 artifacts {u69.lag12.median():.1f}")
print(f"  pool papers appearing in extra artifacts: {len(set(exf.index) & set(pool.arxiv_id))}/261 ({100*len(set(exf.index) & set(pool.arxiv_id))/261:.0f}%)")

# ---------------------------------------------------------------- RQ2 domains on 69 (uniform)
section("RQ2 domain medians, cross-validated 69, uniform dates")
cod = frozen.copy()
cod["arxiv_id"] = cod.arxiv_id.str.strip()
u69m = u69.merge(cod[["arxiv_id", "G1", "G3", "G4", "G5", "G6", "Q1"]], on="arxiv_id")
dom_map = {"Cross": "Cross-domain"}
u69m["Domain"] = u69m.G3.replace(dom_map)
for dmn, g in u69m.groupby("Domain"):
    print(f"  {dmn:13s} n={len(g):2d} median {g.lag.median():5.1f} IQR [{g.lag.quantile(.25):.1f}, {g.lag.quantile(.75):.1f}]")
v = u69m[u69m.Domain == "Vision"].lag
l = u69m[u69m.Domain == "LLM"].lag
u1, p1 = stats.mannwhitneyu(l, v, alternative="less")
print(f"  LLM < Vision one-tailed MW U={u1:.1f} p={p1:.3f}")
doms = [g.lag.values for _, g in u69m.groupby("Domain")]
H, pk = stats.kruskal(*doms)
print(f"  Kruskal-Wallis across domains H={H:.2f} p={pk:.3f}")
names = sorted(u69m.Domain.unique())
pmin = 1
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        a, b = u69m[u69m.Domain == names[i]].lag, u69m[u69m.Domain == names[j]].lag
        if len(a) and len(b):
            _, pm = stats.mannwhitneyu(a, b)
            pmin = min(pmin, pm)
print(f"  smallest pairwise MW p={pmin:.4f} vs Bonferroni alpha 0.05/{len(names)*(len(names)-1)//2}={0.05/(len(names)*(len(names)-1)//2):.4f}")
print("  frozen 71 domain medians:", {d: round(g.lag.median(), 1) for d, g in frozen.groupby("G3")})

# ---------------------------------------------------------------- temporal trend on 69 uniform
section("Temporal trend, cross-validated 69, uniform dates")
u69m["pub"] = pd.to_datetime(u69m.pub)
u69m["t"] = u69m.pub.dt.year + (u69m.pub.dt.dayofyear - 1) / 365.25
sl = stats.linregress(u69m.t, u69m.lag)
print(f"  OLS slope {sl.slope:.2f} mo/yr t={sl.slope/sl.stderr:.2f} p={sl.pvalue:.3f} R2={sl.rvalue**2:.3f}")
rho, prho = stats.spearmanr(u69m.t, u69m.lag)
print(f"  Spearman rho={rho:.2f} p={prho:.3f}")
sl71 = stats.linregress(pd.to_datetime(frozen.paper_pub_date).dt.year + (pd.to_datetime(frozen.paper_pub_date).dt.dayofyear - 1) / 365.25, frozen.lag)
print(f"  (frozen 71: slope {sl71.slope:.2f} p={sl71.pvalue:.3f})")
pool["t"] = pool.pub.dt.year + (pool.pub.dt.dayofyear - 1) / 365.25
slp = stats.linregress(pool.t, pool.lag)
print(f"  pool 261: OLS slope {slp.slope:.2f} mo/yr p={slp.pvalue:.3g} R2={slp.rvalue**2:.3f}; Spearman {stats.spearmanr(pool.t, pool.lag)[0]:.2f}")
for cut in ["2020-10-22"]:
    c = pd.Timestamp(cut)
    pre, post = u69m[u69m.pub < c].lag, u69m[u69m.pub >= c].lag
    u2, p2 = stats.mannwhitneyu(pre, post)
    print(f"  ATLAS launch {cut}: pre n={len(pre)} median {pre.median():.1f} | post n={len(post)} median {post.median():.1f} MW p={p2:.3f}")
    t0 = c.year + (c.dayofyear - 1) / 365.25
    its = u69m.assign(post=(u69m.t >= t0).astype(int), tc=u69m.t - t0)
    its["post_t"] = its.post * its.tc
    m = smf.ols("lag ~ tc + post + post_t", its).fit()
    print("  ITS segmented: " + ", ".join(f"{k} {m.params[k]:.2f} (p={m.pvalues[k]:.3f})" for k in ["tc", "post", "post_t"]))

# ---------------------------------------------------------------- cohort (frame)
section("AML frame cohort (primary RQ3)")
co = pd.read_csv(f"{E}/frame_cohort_9297.csv.gz", dtype={"arxiv_id": str})
co = co[co.dur > 0]
co["pub"] = pd.to_datetime(co.pub)
print(f"  N={len(co)}, events {int(co.event.sum())} ({100*co.event.mean():.1f}%), median lag among integrated {co[co.event==1].dur.median():.1f} mo IQR [{co[co.event==1].dur.quantile(.25):.1f}, {co[co.event==1].dur.quantile(.75):.1f}]")
print(f"  frame members among the 71: {len(set(co.arxiv_id.astype(str)) & set(frozen.arxiv_id.str.strip()))}/71")
print(f"  official code prevalence {100*co.official.mean():.0f}%; integration rate with code {100*co[co.official==1].event.mean():.1f}% vs without {100*co[co.official==0].event.mean():.1f}%")
print("  year distribution:", co.pub.dt.year.value_counts().sort_index().to_dict())
SEC = r"\bCCS\b|Computer and Communications Security|S&P|Security and Privacy|USENIX Security|NDSS|EuroS|AsiaCCS|ACSAC|RAID|SaTML|TIFS|Security"
ML = r"NeurIPS|Neural Information|ICML|International Conference on Machine Learning|ICLR|Learning Representations|CVPR|Computer Vision and Pattern|ICCV|ECCV|AAAI|IJCAI|EMNLP|\bACL\b|NAACL|AISTATS|KDD|COLT|\bUAI\b|JMLR|TMLR|Machine Learning"
vn = co.venue.fillna("")
co["v_sec"] = vn.str.contains(SEC, case=False, regex=True).astype(int)
co["v_ml"] = (vn.str.contains(ML, case=False, regex=True) & ~co.v_sec.astype(bool)).astype(int)
co["v_none"] = (vn.str.strip() == "").astype(int)
kw = pd.get_dummies(co.matched_keyword, prefix="kw", drop_first=True).astype(int)
co2 = pd.concat([co, kw], axis=1)


def cox(df, cols, label, strata=None):
    c = CoxPHFitter(penalizer=0.0)
    c.fit(df[["dur", "event"] + cols + ([strata] if strata else [])], duration_col="dur", event_col="event", strata=strata)
    hr = np.exp(c.params_["official"])
    lo, hi = np.exp(c.confidence_intervals_.loc["official"])
    print(f"  Cox {label}: HR_code {hr:.2f} [{lo:.2f}, {hi:.2f}] p={c.summary.loc['official','p']:.1e}" +
          (f"; HR_year {np.exp(c.params_['year_c']):.2f}" if "year_c" in cols else ""))
    return c


cox(co2, ["official", "year_c"], "official + year")
cox(co2, ["official", "year_c", "v_sec", "v_ml"], "official + year + venue class")
cox(co2, ["official", "year_c", "v_sec", "v_ml"] + list(kw.columns), "official + year + venue class + topic keyword")
print("  has_abstract==0:", int((co2.has_abstract==0).sum()), "; venue empty:", int(co2.v_none.sum()), "; types Review:", int(co2.types.fillna('').str.contains('Review').sum()))
co2["yr"] = co2.pub.dt.year
cox(co2, ["official", "v_sec", "v_ml"], "official + venue, stratified by year", strata="yr")
X = sm.add_constant(co2[["official", "year_c"]].astype(float))
lg = sm.Logit(co2.event, X).fit(disp=0)
print(f"  Logistic official + year: OR {np.exp(lg.params['official']):.2f} [{np.exp(lg.conf_int().loc['official',0]):.2f}, {np.exp(lg.conf_int().loc['official',1]):.2f}] p={lg.pvalues['official']:.1e}")
X = sm.add_constant(co2[["anyrepo", "year_c"]].astype(float))
lg2 = sm.Logit(co2.event, X).fit(disp=0)
print(f"  Logistic any-repo + year: OR {np.exp(lg2.params['anyrepo']):.2f}")
c3 = CoxPHFitter().fit(co2[["dur", "event", "anyrepo", "year_c"]], "dur", "event")
print(f"  Cox any-repo + year: HR {np.exp(c3.params_['anyrepo']):.2f} [{np.exp(c3.confidence_intervals_.loc['anyrepo'].iloc[0]):.2f}, {np.exp(c3.confidence_intervals_.loc['anyrepo'].iloc[1]):.2f}]")
# proportional hazards check
from lifelines.statistics import proportional_hazard_test
c1 = CoxPHFitter().fit(co2[["dur", "event", "official", "year_c"]], "dur", "event")
ph = proportional_hazard_test(c1, co2[["dur", "event", "official", "year_c"]], time_transform="rank")
print("  PH test (rank):", {k: round(v, 3) for k, v in ph.summary["p"].items()})
# year-stratified KM
kmc = KaplanMeierFitter().fit(co2.dur, co2.event)
print(f"  KM cumulative incidence at 12/24/36 mo: {[round(100*(1-kmc.survival_function_at_times(t).values[0]),1) for t in (12,24,36)]}")
for v_, g in co2.groupby("official"):
    k = KaplanMeierFitter().fit(g.dur, g.event)
    print(f"    official={v_}: n={len(g)} CI@24 {100*(1-k.survival_function_at_times(24).values[0]):.1f}%  CI@48 {100*(1-k.survival_function_at_times(48).values[0]):.1f}%")

# ---------------------------------------------------------------- matched sample (regenerated controls)
section("Matched case-control sample, regenerated controls (sensitivity)")
cc = pd.read_csv(f"{E}/case_control_138.csv", dtype={"arxiv_id": str})
cc = cc[cc.time > 0].copy()
cc["pub_year_centered"] = cc.pub_year - cc.pub_year.mean()
print(f"  n={len(cc)} events={int(cc.event.sum())}; code_url adopted {100*cc[cc.event==1].code_url.mean():.0f}% controls {100*cc[cc.event==0].code_url.mean():.0f}%")
cols = ["code_url", "pub_year_centered", "is_vision", "is_cross_domain", "is_defense", "is_security_venue"]
for lab, d in [("as regenerated", cc), ("leakage-corrected (6 leaked exposures set to 0)", cc.assign(code_url=np.where(cc.arxiv_id.isin(leaked), 0, cc.code_url)))]:
    print(f"  [{lab}] exposed cases {int(d[d.event==1].code_url.sum())}")
    for pen, pl in [(0.0, "unpenalized"), (0.1, "ridge")]:
        c = CoxPHFitter(penalizer=pen, l1_ratio=0.0).fit(d[["time", "event"] + cols], "time", "event")
        hr = np.exp(c.params_["code_url"]); lo, hi = np.exp(c.confidence_intervals_.loc["code_url"])
        print(f"    Cox {pl}: HR {hr:.2f} [{lo:.2f}, {hi:.2f}] p={c.summary.loc['code_url','p']:.3f}")

# ---------------------------------------------------------------- Table 1 check
section("Table 1 (coding) on the 71")
for col in ["G1", "G3", "G4", "G5", "G6", "Q1"]:
    print(f"  {col}: {frozen[col].value_counts(dropna=False).to_dict()}")
print("done")
