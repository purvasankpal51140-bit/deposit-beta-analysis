"""
Deposit beta analysis for 10 US banks, 2021-2025.

Question: when the Fed raised rates from near zero to 5.33% in 2022-23, how much
of that did banks pass on to depositors, how fast, and did regional banks have
to pay more than the largest banks? What happened once the Fed started cutting?

Deposit beta = change in cost of interest-bearing deposits / change in Fed funds.

Data (downloaded automatically, both free and public):
  - FDIC BankFind API: quarterly call report data for each bank
  - FRED (St. Louis Fed): effective Fed funds rate, series FEDFUNDS

Run:   python deposit_beta.py
Output goes to output/ (CSV tables, charts, regression results, summary.md)
"""

from pathlib import Path
import json
import urllib.parse
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.formula.api as smf

DATA = Path("data")
OUT = Path("output")
DATA.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

# FDIC certificate numbers identify each bank's main US banking subsidiary.
BANKS = pd.DataFrame([
    (628,   "JPMorgan Chase",  "Large"),
    (3510,  "Bank of America", "Large"),
    (3511,  "Wells Fargo",     "Large"),
    (7213,  "Citigroup",       "Large"),
    (6548,  "U.S. Bancorp",    "Super-regional"),
    (6384,  "PNC",             "Super-regional"),
    (9846,  "Truist",          "Super-regional"),
    (17534, "KeyCorp",         "Regional"),
    (6672,  "Fifth Third",     "Regional"),
    (6560,  "Huntington",      "Regional"),
], columns=["cert", "bank", "group"])

GROUP_ORDER = ["Large", "Super-regional", "Regional"]
COLORS = {"Large": "#1f4e79", "Super-regional": "#4a90c2", "Regional": "#c0504d"}

# Cycle windows. Start = last quarter before the first hike (March 2022).
# Hiking end = last quarter before the first cut (September 2024), so the
# full-cycle beta captures repricing that kept happening after the last hike.
START, END_2022, HIKE_END, EASE_END = "2021Q4", "2022Q4", "2024Q2", "2025Q4"
N_LAGS = 3


# =============================================================== 1. Download
def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "deposit-beta-project"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch_fdic() -> pd.DataFrame:
    """Quarterly call report fields for all 10 banks, cached to data/fdic_raw.csv."""
    cache = DATA / "fdic_raw.csv"
    if cache.exists():
        return pd.read_csv(cache)
    certs = " OR ".join(str(c) for c in BANKS["cert"])
    params = {
        # 2020Q4 is included so 2021Q1 has a prior quarter for average balances
        "filters": f"CERT:({certs}) AND REPDTE:[20201231 TO 20251231]",
        "fields": "CERT,REPDTE,EDEPDOM,EDEPDOMQ,DEPDOM,DEP,DEPI,DEPNI,DEPIFOR",
        "limit": 10000,
        "format": "json",
    }
    url = "https://api.fdic.gov/banks/financials?" + urllib.parse.urlencode(params)
    rows = [rec["data"] for rec in get_json(url)["data"]]
    raw = pd.DataFrame(rows)
    raw.to_csv(cache, index=False)
    print(f"Downloaded {len(raw)} bank-quarters from the FDIC API")
    return raw


def fetch_fed_funds() -> pd.Series:
    """Quarterly average effective Fed funds rate, in percent.

    Call report interest expense is earned over the whole quarter, so the Fed rate
    is averaged over the same three months to compare like with like.
    """
    cache = DATA / "FEDFUNDS.csv"
    if not cache.exists():
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
        pd.read_csv(url).to_csv(cache, index=False)
    ff = pd.read_csv(cache)
    ff.columns = ["date", "fed_funds"]
    ff["date"] = pd.to_datetime(ff["date"])
    ff["fed_funds"] = pd.to_numeric(ff["fed_funds"], errors="coerce")
    q = ff.set_index("date")["fed_funds"].resample("QE").mean()
    q.index = q.index.to_period("Q")
    return q


# =============================================================== 2. Deposit cost
def build_deposit_costs(raw: pd.DataFrame) -> pd.DataFrame:
    """Annualized cost of interest-bearing domestic deposits, in percent.

    cost = quarterly domestic deposit interest expense x (365 / days in quarter)
           / average interest-bearing domestic deposits (start and end of quarter)

    Domestic only: big banks like Citi hold large foreign deposits priced off
    other central banks' rates, which would muddy a comparison to Fed funds.
    """
    df = raw.copy()
    num = ["EDEPDOM", "EDEPDOMQ", "DEPDOM", "DEP", "DEPI", "DEPNI", "DEPIFOR"]
    for c in num:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df["DEPIFOR"] = df["DEPIFOR"].fillna(0)
    df["date"] = pd.to_datetime(df["REPDTE"].astype(str), format="%Y%m%d")
    df["quarter"] = df["date"].dt.to_period("Q")
    df = df.sort_values(["CERT", "date"])

    # Quarterly interest expense. EDEPDOMQ is already quarterly; if it is
    # missing, take the year-to-date figure EDEPDOM minus the prior quarter's.
    ytd_prev = df.groupby(["CERT", df["date"].dt.year])["EDEPDOM"].shift(1).fillna(0)
    df["int_exp_q"] = df["EDEPDOMQ"].fillna(df["EDEPDOM"] - ytd_prev)

    # Interest-bearing domestic deposits. Check whether DEPI is a domestic or a
    # total figure by seeing which balance it adds up to with DEPNI.
    gap_dom = ((df["DEPI"] + df["DEPNI"]) / df["DEPDOM"] - 1).abs().median()
    gap_tot = ((df["DEPI"] + df["DEPNI"]) / df["DEP"] - 1).abs().median()
    if gap_dom <= gap_tot:
        df["ib_dom"] = df["DEPI"]
        print("Check: DEPI + DEPNI matches domestic deposits, so DEPI is domestic.")
    else:
        df["ib_dom"] = df["DEPI"] - df["DEPIFOR"]
        print("Check: DEPI + DEPNI matches total deposits; foreign part removed.")

    df["ib_avg"] = (df["ib_dom"] + df.groupby("CERT")["ib_dom"].shift(1)) / 2
    days = df["date"].dt.dayofyear - df["date"].dt.to_period("Q").dt.start_time.dt.dayofyear + 1
    df["cost_ib_deposits_pct"] = df["int_exp_q"] * (365 / days) / df["ib_avg"] * 100

    df = df.merge(BANKS, left_on="CERT", right_on="cert")
    df = df[df["quarter"] >= pd.Period("2021Q1", "Q")]
    out = df[["bank", "group", "quarter", "cost_ib_deposits_pct",
              "int_exp_q", "ib_dom"]].reset_index(drop=True)

    bad = out[out["cost_ib_deposits_pct"].isna() | (out["cost_ib_deposits_pct"] < 0)
              | (out["cost_ib_deposits_pct"] > 8)]
    if len(bad):
        print("WARNING: these rows look wrong, check them on FDIC BankFind:\n", bad)
    counts = out.groupby("bank").size()
    if (counts != 20).any():
        print("WARNING: not every bank has 20 quarters:\n", counts[counts != 20])
    return out


# =============================================================== 3. Betas
def cycle_beta(g: pd.DataFrame, start: str, end: str) -> float:
    g = g.set_index("quarter")
    s, e = pd.Period(start, "Q"), pd.Period(end, "Q")
    return ((g.loc[e, "cost_ib_deposits_pct"] - g.loc[s, "cost_ib_deposits_pct"])
            / (g.loc[e, "fed_funds"] - g.loc[s, "fed_funds"]))


def compute_betas(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (bank, group), g in df.groupby(["bank", "group"]):
        rows.append({
            "bank": bank, "group": group,
            "beta_full_hiking": cycle_beta(g, START, HIKE_END),
            "beta_by_end_2022": cycle_beta(g, START, END_2022),
            # Fed funds fell, so a positive easing beta means deposit costs fell too
            "beta_easing": cycle_beta(g, HIKE_END, EASE_END),
        })
    b = pd.DataFrame(rows)
    b["order"] = b["group"].map({g: i for i, g in enumerate(GROUP_ORDER)})
    return b.sort_values(["order", "beta_full_hiking"]).drop(columns="order").round(3)


def cumulative_beta_path(df: pd.DataFrame) -> pd.DataFrame:
    """Beta from START to each later hiking-cycle quarter (skips Fed moves < 50 bps,
    where dividing by a tiny number gives jumpy, meaningless betas)."""
    base = df[df["quarter"] == pd.Period(START, "Q")].set_index("bank")
    h = df[(df["quarter"] > pd.Period(START, "Q")) &
           (df["quarter"] <= pd.Period(HIKE_END, "Q"))].copy()
    h["d_cost"] = h["cost_ib_deposits_pct"] - h["bank"].map(base["cost_ib_deposits_pct"])
    h["d_ff"] = h["fed_funds"] - h["bank"].map(base["fed_funds"])
    h = h[h["d_ff"] >= 0.5]
    h["cum_beta"] = h["d_cost"] / h["d_ff"]
    return h


# =============================================================== 4. Regression
def lag_regression(df: pd.DataFrame):
    """By bank group:
        d_cost(t) = a_bank + b0*d_ff(t) + b1*d_ff(t-1) + b2*d_ff(t-2) + b3*d_ff(t-3) + e

    b0..b3 show the speed of pass-through; their sum is the total after a year.
    Bank fixed effects give each bank its own intercept. Standard errors are
    heteroskedasticity-robust (HC1); with 3-4 banks per group, clustering by
    bank would not be reliable.
    """
    df = df.sort_values(["bank", "quarter"]).copy()
    df["d_cost"] = df.groupby("bank")["cost_ib_deposits_pct"].diff()
    df["d_ff"] = df.groupby("bank")["fed_funds"].diff()
    lags = ["d_ff"] + [f"d_ff_l{k}" for k in range(1, N_LAGS + 1)]
    for k in range(1, N_LAGS + 1):
        df[f"d_ff_l{k}"] = df.groupby("bank")["d_ff"].shift(k)
    df = df.dropna(subset=["d_cost"] + lags)
    formula = "d_cost ~ " + " + ".join(lags) + " + C(bank)"

    text, rows = [], []
    for group in GROUP_ORDER:
        g = df[df["group"] == group]
        m = smf.ols(formula, data=g).fit(cov_type="HC1")
        t = m.t_test(" + ".join(lags) + " = 0")
        total, se = float(t.effect.squeeze()), float(t.sd.squeeze())
        text += [f"\n{'=' * 70}\nGROUP: {group}  (n = {int(m.nobs)}, R2 = {m.rsquared:.2f})\n{'=' * 70}",
                 m.summary().tables[1].as_text(),
                 f"Total one-year pass-through (sum of lags): {total:.3f} "
                 f"(SE {se:.3f}, p = {float(t.pvalue):.4f})"]
        rows.append({"group": group, **{l: m.params[l] for l in lags},
                     "total": total, "total_se": se, "r2": m.rsquared, "n": int(m.nobs)})
    return pd.DataFrame(rows).round(3), "\n".join(text)


# =============================================================== 5. Charts
def style(ax):
    ax.spines[["top", "right"]].set_visible(False)


def legend(ax, kind="bar", loc="lower right"):
    mk = (lambda c: plt.Rectangle((0, 0), 1, 1, color=c)) if kind == "bar" \
        else (lambda c: plt.Line2D([0], [0], color=c, linewidth=2.5))
    ax.legend([mk(COLORS[g]) for g in GROUP_ORDER], GROUP_ORDER, loc=loc, frameon=False)


def chart_betas(b: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(b["bank"], b["beta_full_hiking"], color=b["group"].map(COLORS))
    for y, v in enumerate(b["beta_full_hiking"]):
        ax.text(v + 0.01, y, f"{v:.2f}", va="center", fontsize=9)
    ax.set_xlabel("Deposit beta, 2021Q4 to 2024Q2")
    ax.set_title("Share of Fed hikes passed on to interest-bearing depositors")
    legend(ax); style(ax); fig.tight_layout()
    fig.savefig(OUT / "betas_by_bank.png", dpi=200); plt.close(fig)


def chart_cumulative(path: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))
    for _, g in path.groupby("bank"):
        ax.plot(g["quarter"].astype(str), g["cum_beta"],
                color=COLORS[g["group"].iloc[0]], alpha=0.25, linewidth=1)
    avg = path.groupby(["group", "quarter"])["cum_beta"].mean().reset_index()
    for grp in GROUP_ORDER:
        a = avg[avg["group"] == grp]
        ax.plot(a["quarter"].astype(str), a["cum_beta"], color=COLORS[grp],
                linewidth=2.5, marker="o", markersize=4)
    ax.set_ylabel("Cumulative deposit beta since 2021Q4")
    ax.set_title("How deposit beta built up (bold = group average)")
    legend(ax, "line", "upper left"); style(ax)
    plt.xticks(rotation=45); fig.tight_layout()
    fig.savefig(OUT / "cumulative_beta.png", dpi=200); plt.close(fig)


def chart_rates(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(9, 5))
    ff = df.drop_duplicates("quarter").sort_values("quarter")
    ax.plot(ff["quarter"].astype(str), ff["fed_funds"], color="black",
            linewidth=2, linestyle="--", label="Fed funds")
    avg = df.groupby(["group", "quarter"])["cost_ib_deposits_pct"].mean().reset_index()
    for grp in GROUP_ORDER:
        a = avg[avg["group"] == grp]
        ax.plot(a["quarter"].astype(str), a["cost_ib_deposits_pct"],
                color=COLORS[grp], linewidth=2.5, label=grp)
    ax.set_ylabel("Percent")
    ax.set_title("Fed funds vs. cost of interest-bearing deposits (group averages)")
    ax.legend(frameon=False, loc="upper left"); style(ax)
    ax.set_xticks(range(0, len(ff), 2)); plt.xticks(rotation=45)
    fig.tight_layout(); fig.savefig(OUT / "rates_vs_fed_funds.png", dpi=200); plt.close(fig)


def chart_total_passthrough(reg: pd.DataFrame):
    """Total one-year pass-through by group with 95% confidence intervals.

    Individual lag coefficients are not shown: back-to-back Fed moves make
    neighbouring lags highly correlated, so the regression cannot split the
    effect between them reliably. Their sum is stable and well estimated.
    """
    fig, ax = plt.subplots(figsize=(7, 4.5))
    r = reg.set_index("group").reindex(GROUP_ORDER)
    ax.bar(GROUP_ORDER, r["total"], color=[COLORS[g] for g in GROUP_ORDER],
           yerr=1.96 * r["total_se"], capsize=6, width=0.55)
    for i, v in enumerate(r["total"]):
        ax.text(i, v + 1.96 * r["total_se"].iloc[i] + 0.01, f"{v:.2f}", ha="center", fontsize=10)
    ax.set_ylabel("Pass-through within a year, per 1 pt Fed move")
    ax.set_title("Total one-year pass-through by bank group (95% CI)")
    ax.set_ylim(0, max(r["total"] + 1.96 * r["total_se"]) * 1.2); style(ax)
    fig.tight_layout(); fig.savefig(OUT / "total_pass_through.png", dpi=200); plt.close(fig)


# =============================================================== 6. Summary
OUTLIER = "Citigroup"  # far above every other bank; shown with and without


def write_summary(df, betas, reg):
    cols = ["beta_full_hiking", "beta_by_end_2022", "beta_easing"]
    gm = betas.groupby("group")[cols].mean().reindex(GROUP_ORDER)
    ex = betas[(betas["group"] == "Large") & (betas["bank"] != OUTLIER)][cols].mean()
    gm.loc[f"Large excl. {OUTLIER}"] = ex
    gm = gm.rename(columns={"beta_full_hiking": "Full hiking cycle",
                            "beta_by_end_2022": "By end of 2022", "beta_easing": "Easing"})
    md = ["# Results", "",
          f"Data: FDIC call reports, {df['bank'].nunique()} banks, "
          f"{df['quarter'].min()} to {df['quarter'].max()}; Fed funds from FRED.", "",
          "## Average deposit beta by group", "", gm.round(2).to_markdown(), "",
          "## Beta by bank", "", betas.to_markdown(index=False), "",
          "## Lag regression by group", "",
          "Report the total. Individual lags are highly correlated (back-to-back Fed moves), "
          "so the split between them is not reliable.", "",
          reg.to_markdown(index=False)]
    (OUT / "summary.md").write_text("\n".join(md))


# =============================================================== Main
def main():
    ff = fetch_fed_funds()
    df = build_deposit_costs(fetch_fdic())
    df["fed_funds"] = df["quarter"].map(ff)
    if df["fed_funds"].isna().any():
        raise ValueError("Missing Fed funds data for some quarters. Delete data/FEDFUNDS.csv and rerun.")
    df.to_csv(OUT / "deposit_costs.csv", index=False)

    betas = compute_betas(df)
    betas.to_csv(OUT / "betas.csv", index=False)
    reg, reg_text = lag_regression(df)
    reg.to_csv(OUT / "regression_summary.csv", index=False)
    (OUT / "regression_by_group.txt").write_text(reg_text)

    chart_betas(betas)
    chart_cumulative(cumulative_beta_path(df))
    chart_rates(df)
    chart_total_passthrough(reg)

    print("\nBetas by bank:\n", betas.to_string(index=False))
    print(reg_text)
    write_summary(df, betas, reg)
    print(f"\nDone. Everything is in {OUT.resolve()}")


if __name__ == "__main__":
    main()
