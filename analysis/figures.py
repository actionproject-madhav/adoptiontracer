#!/usr/bin/env python3
"""Figures 1-3 of the paper, drawn from the frozen files in data/.

Run:  python analysis/figures.py
Output: figures/{rq1_adoption_lag_distribution,rq2_domain_comparison,rq3_forest_plot}.pdf

Text is rendered with LaTeX (Computer Modern) to match the paper body; a TeX
installation is required. Set MPLBACKEND or edit rcParams below to use plain
matplotlib fonts instead.
"""
import glob
import os
import warnings

import matplotlib
matplotlib.use("pdf")
import matplotlib.ticker
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")
E = DATA_DIR
L = DATA_DIR
D = DATA_DIR
OUT = os.path.join(HERE, "..", "figures")
CUT = pd.Timestamp("2025-01-31")
TOOLS = {"CleverHans", "Foolbox", "IBM ART", "TextAttack", "PyRIT"}
BENCH = {"RobustBench", "AutoAttack", "HarmBench"}

INK, FOREST, VERMILLION, MUTED, SOFT, HAIR = "#1a1a1a", "#034f46", "#d64e2e", "#736f6c", "#b8b5b1", "#e6e3df"
TEXTWIDTH_IN = 6.0

plt.rcParams.update({
    "text.usetex": True,
    "font.family": "serif",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "text.color": INK,
    "legend.frameon": False,
    "pdf.fonttype": 42,
    "savefig.dpi": 300,
})


def clean(ax, left=True):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if not left:
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)


def panel_labels(fig, panels):
    """Place bold (a), (b), ... flush with the left edge of each panel's outermost text."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    renderer = FigureCanvasAgg(fig).get_renderer()
    boxes = [ax.get_tightbbox(renderer) for ax, _ in panels]
    inv = fig.transFigure.inverted()
    top = max(inv.transform((0, b.y1))[1] for b in boxes) + 3 / 72 / fig.get_figheight()
    for (ax, s), b in zip(panels, boxes):
        xf = inv.transform((b.x0, 0))[0]
        fig.text(xf, top, rf"\textbf{{({s})}}", ha="left", va="bottom", fontsize=8)


def km_curve(ax, dur, event, color, label, scale=1.0):
    km = KaplanMeierFitter().fit(dur, event)
    t = km.survival_function_.index.values
    s = scale * (1 - km.survival_function_.iloc[:, 0].values)
    ci = km.confidence_interval_
    lo, hi = scale * (1 - ci.iloc[:, 1].values), scale * (1 - ci.iloc[:, 0].values)
    ax.step(t, s, where="post", color=color, linewidth=1.0, label=label)
    ax.fill_between(t, lo, hi, step="post", color=color, alpha=0.12, linewidth=0)


def load():
    pool = pd.read_csv(f"{L}/pool_261_first_events.csv", dtype={"arxiv_id": str})
    pool["pub"] = pd.to_datetime(pool.pub)
    ev = pd.concat([pd.read_csv(f, dtype=str) for f in glob.glob(f"{E}/events/*.csv")], ignore_index=True)
    ev["ad"] = pd.to_datetime(ev.author_date, utc=True, format="ISO8601", errors="coerce").dt.tz_localize(None)
    ev = ev.dropna(subset=["ad"])
    ev = ev[ev.ad <= CUT]
    pubmap = dict(zip(pool.arxiv_id, pool.pub))
    pa = ev[ev.arxiv_id.isin(pubmap)].sort_values("ad").groupby(["arxiv_id", "artifact"]).first().reset_index()
    pa["lag"] = (pa.ad - pa.arxiv_id.map(pubmap)).dt.days / 30.44
    pa["typ"] = pa.artifact.map(lambda a: "Tool" if a in TOOLS else "Benchmark" if a in BENCH else "Regulatory")
    code = pd.read_csv(f"{L}/code_events_159.csv", dtype={"arxiv_id": str})
    code["first_code"] = pd.to_datetime(code.first_code)
    pc = pool.merge(code[["arxiv_id", "first_code"]], on="arxiv_id", how="left")
    pc["event"] = pc.first_code.notna().astype(int)
    pc["dur"] = np.where(pc.event == 1, (pc.first_code - pc.pub).dt.days / 30.44, (CUT - pc.pub).dt.days / 30.44)
    pc["dur"] = pc.dur.clip(lower=0.01)
    f69 = pd.read_csv(f"{E}/first_events_69.csv", dtype={"arxiv_id": str})
    coded = pd.read_csv(f"{D}/papers_71_coded.csv", dtype=str)
    coded["arxiv_id"] = coded.arxiv_id.str.strip()
    f69 = f69.merge(coded[["arxiv_id", "G3"]], on="arxiv_id")
    f69["Domain"] = f69.G3.replace({"Cross": "Cross-domain"})
    co = pd.read_csv(f"{E}/frame_cohort_9297.csv.gz", dtype={"arxiv_id": str})
    co = co[co.dur > 0]
    return pool, pa, pc, f69, co


DATA = None


def data():
    global DATA
    if DATA is None:
        DATA = load()
    return DATA


# ------------------------------------------------------------------ Figure 1
def make_fig1():
    pool, pa, pc, _, _ = data()
    fig = plt.figure(figsize=(TEXTWIDTH_IN - 0.05, 1.85))
    # explicit axes boxes in figure fractions: [left, bottom, width, height]
    ax_a = fig.add_axes([0.06, 0.24, 0.205, 0.66])
    ax_b = fig.add_axes([0.455, 0.24, 0.2, 0.66])
    ax_c = fig.add_axes([0.765, 0.24, 0.23, 0.66])

    ax = ax_a
    bins = np.arange(0, 103, 3)
    ax.hist(pool.lag, bins=bins, color=FOREST, edgecolor="white", linewidth=0.4)
    ax.axvline(pool.lag.median(), color=INK, linestyle=(0, (4, 2)), linewidth=0.9)
    ax.set_xlabel("Integration lag (months)")
    ax.set_ylabel("Papers")
    ax.set_xlim(0, 102)
    ax.set_xticks([0, 24, 48, 72, 96])
    ax.set_yticks([0, 20, 40, 60, 80])
    clean(ax)

    ax = ax_b
    order = ["Regulatory", "Tool", "Benchmark"]
    vals = [pa[pa.typ == t].lag.values for t in order]
    ax.boxplot(vals, vert=False, widths=0.55, patch_artist=True, whis=(0, 100), showfliers=False,
               boxprops=dict(facecolor=HAIR, edgecolor=INK, linewidth=0.6),
               medianprops=dict(color=INK, linewidth=1.1),
               whiskerprops=dict(color=INK, linewidth=0.6),
               capprops=dict(color=INK, linewidth=0.6))
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels([f"{t} ($n$={len(d)})" for t, d in zip(order, vals)])
    ax.set_xlabel("Integration lag (months)")
    ax.set_xlim(-3, 102)
    ax.set_xticks([0, 24, 48, 72, 96])
    clean(ax, left=False)

    ax = ax_c
    km_curve(ax, pool.lag.clip(lower=0.01), np.ones(len(pool)), FOREST, "Any file", 100)
    km_curve(ax, pc.dur, pc.event, VERMILLION, "Code-level", 100)
    ax.set_xlim(0, 72)
    ax.set_ylim(0, 100)
    ax.set_xticks([0, 12, 24, 36, 48, 60, 72])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Months since arXiv posting")
    ax.set_ylabel(r"Integrated (\%)")
    ax.legend(loc="lower right", handlelength=1.4, borderaxespad=0.3)
    clean(ax)
    panel_labels(fig, [(ax_a, "a"), (ax_b, "b"), (ax_c, "c")])
    return fig


# ------------------------------------------------------------------ Figure 2
def make_fig2():
    _, _, _, f69, _ = data()
    fig = plt.figure(figsize=(TEXTWIDTH_IN + 0.18, 1.75))
    ax = fig.add_axes([0.19, 0.22, 0.79, 0.76])
    dom_order = ["Malware", "Audio", "Cross-domain", "NLP", "LLM", "Vision"]
    vals = [f69[f69.Domain == d].lag.values for d in dom_order]
    ax.boxplot(vals, vert=False, widths=0.55, whis=(0, 100), showfliers=False, patch_artist=True,
               boxprops=dict(facecolor=HAIR, edgecolor=INK, linewidth=0.6),
               medianprops=dict(color=INK, linewidth=1.1),
               whiskerprops=dict(color=INK, linewidth=0.6),
               capprops=dict(color=INK, linewidth=0.6))
    ax.set_yticks(range(1, len(dom_order) + 1))
    ax.set_yticklabels([f"{d} ($n$={len(v)})" for d, v in zip(dom_order, vals)])
    ax.set_xlabel("Integration lag (months)")
    ax.set_xlim(-1.5, 52)
    ax.set_xticks([0, 12, 24, 36, 48])
    clean(ax, left=False)
    return fig


# ------------------------------------------------------------------ Figure 3
ROWS = [
    ("Population frame, $N$=9{,}297", None, None, None, None),
    ("Cox HR, year-adjusted", 4.87, 3.55, 6.69, FOREST),
    ("Cox HR, year-strat.\\ + venue", 3.58, 2.57, 4.99, FOREST),
    ("Logistic OR, year-adjusted", 5.26, 3.78, 7.31, FOREST),
    ("Matched sample", None, None, None, None),
    ("Logistic OR, $n$=139", 2.34, 0.96, 5.68, INK),
    ("Cox HR, original controls, $n$=139", 1.79, 1.03, 3.10, INK),
    ("Cox HR, re-drawn controls, $n$=138", 2.11, 1.17, 3.80, INK),
    ("Cox HR, leakage-corrected, $n$=138", 1.49, 0.79, 2.83, INK),
]


def make_fig3():
    _, _, _, _, co = data()
    fig = plt.figure(figsize=(TEXTWIDTH_IN + 0.07, 1.9))
    ax1 = fig.add_axes([0.055, 0.22, 0.265, 0.70])
    ax2 = fig.add_axes([0.645, 0.22, 0.18, 0.70])

    km_curve(ax1, co[co.official == 1].dur, co[co.official == 1].event, FOREST, "Official repository", 100)
    km_curve(ax1, co[co.official == 0].dur, co[co.official == 0].event, MUTED, "No official repository", 100)
    ax1.set_xlim(0, 72)
    ax1.set_ylim(0, 8)
    ax1.set_yticks([0, 2, 4, 6, 8])
    ax1.set_xticks([0, 12, 24, 36, 48, 60, 72])
    ax1.set_xlabel("Months since arXiv posting")
    ax1.set_ylabel(r"Integrated (\%)")
    ax1.legend(loc="upper left", handlelength=1.4, borderaxespad=0.2)
    clean(ax1)

    n = len(ROWS)
    ys = np.arange(n)[::-1]
    ax2.axvline(1.0, color=SOFT, linewidth=0.7, zorder=1)
    for y, (lab, est, lo, hi, col) in zip(ys, ROWS):
        if est is None:
            ax2.text(-0.07, y, rf"\textit{{{lab}}}", transform=ax2.get_yaxis_transform(), ha="right", va="center", fontsize=7)
            continue
        ax2.text(-0.07, y, lab, transform=ax2.get_yaxis_transform(), ha="right", va="center", fontsize=7)
        ax2.plot([lo, hi], [y, y], color=col, linewidth=0.9, zorder=2, solid_capstyle="butt")
        for xx in (lo, hi):
            ax2.plot([xx, xx], [y - 0.18, y + 0.18], color=col, linewidth=0.7, zorder=2)
        ax2.plot(est, y, marker="o" if "HR" in lab else "s", markersize=4.0, color=col, zorder=3)
        ax2.text(1.06, y, f"{est:.2f} ({lo:.2f}--{hi:.2f})", transform=ax2.get_yaxis_transform(), va="center", ha="left", fontsize=7)
    ax2.set_yticks([])
    ax2.set_xscale("log")
    ax2.set_xlim(0.6, 9)
    ax2.set_xticks([1, 2, 4, 8])
    ax2.set_xticklabels(["1", "2", "4", "8"])
    ax2.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax2.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax2.set_ylim(-0.7, n - 0.3)
    ax2.set_xlabel(r"Estimate (95\% CI)")
    clean(ax2, left=False)
    panel_labels(fig, [(ax1, "a"), (ax2, "b")])
    return fig


FIGS = {
    "rq1_adoption_lag_distribution": make_fig1,
    "rq2_domain_comparison": make_fig2,
    "rq3_forest_plot": make_fig3,
}

if __name__ == "__main__":
    for name, fn in FIGS.items():
        fig = fn()
        fig.savefig(f"{OUT}/{name}.pdf", bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        print("wrote", name)
