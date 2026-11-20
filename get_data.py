"""
CFM301 Project 5 - Are the fees justified?  Institutional share classes of active funds.
DATA STAGE: pull + construct + clean.

Question: Do the institutional share classes of active large-cap value funds earn enough before
fees to justify what they charge, and should institutions pay for active management through a
flat fee, a fulcrum fee, or simply index?

Design: five active large-cap value funds, each through its INSTITUTIONAL class ($1M-$5M minimum,
the cheapest way to hire the manager through a mutual fund). Benchmark: three Vanguard
INSTITUTIONAL index funds ($5M minimum). Each fund's RETAIL class (same portfolio, higher fee) is
kept for the sensitivity analysis only. Every class has full daily history 2010-12-01 .. 2026
(4,017 trading days), so all series cover the same 189 months.

  python get_data.py --download   # ONLINE, run once: writes data_raw/ (Yahoo + Ken French)
  python get_data.py              # OFFLINE (default): builds data_clean/ from data_raw/ only

Sources
  Yahoo Finance (yfinance) : daily NAV + distributions per share class, fee/turnover snapshot
  Ken French data library  : MKT-RF, SMB, HML, RF and MOM (UMD), monthly
  Fund documents (labelled): minimum initial investment and maximum sales charge (MIN_INVEST,
                             MAX_LOAD below, each with its source URL in SOURCES)

data_raw/   (submit these - the build step reads nothing else)
  daily_<TICKER>.csv             raw daily NAV (Close, not dividend-adjusted), Adj Close, distributions
  fund_info.csv                  Yahoo snapshot: expense ratio, turnover, total assets, inception
  F-F_Research_Data_Factors.csv  Ken French 3 factors + RF (raw, % per month)
  F-F_Momentum_Factor.csv        Ken French momentum (raw, % per month)
  expense_ratio_history.csv      optional, historical fees: ticker,date,exp_ratio,source_url

data_clean/
  monthly_returns.csv   share-class level: net TR, expense ratio, gross TR, RF, excess returns
  fund_monthly.csv      one row per (fund, investor, month): investor = inst | retail | index;
                        net/gross excess returns (raw, winsorized 1/99 and 5/95), load-adjusted
                        retail returns (load spread over 3/5/10 years) + factors
  pairs_monthly.csv     institutional vs retail class of each fund, month by month (sensitivity)
  factors_monthly.csv   mktrf, smb, hml, umd, rf (decimals)
  index_returns.csv     wide: monthly net returns of the index funds (constrained benchmark, Req 7)
  fees.csv              one row per class: group, minimum, load, ER, turnover, sources
  distributions.csv     every dividend / capital-gain distribution
  return_check.csv      months where our TR differs from Yahoo Adj Close by > 0.5%
  cleaning_log.csv      every cleaning step and how many observations it affected (Req 4)
"""

import argparse
import datetime as dt
import io
import os
import re
import urllib.request
import zipfile

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR, CLEAN_DIR = os.path.join(BASE, "data_raw"), os.path.join(BASE, "data_clean")

START = "2010-12-01"            # one month early: Jan 2011 return needs the Dec 2010 NAV
FIRST_MONTH = "2011-01"         # sample start; sample end = last month in the factor file

# Active large-cap value funds: institutional class (main analysis) + retail class (sensitivity only).
ACTIVE_FUNDS = {
    "JPMorgan Equity Income":     {"inst": "HLIEX", "retail": "OIEIX"},
    "BlackRock Equity Dividend":  {"inst": "MADVX", "retail": "MDDVX"},
    "Lord Abbett Affiliated":     {"inst": "LAFYX", "retail": "LAFFX"},
    "American Century Value":     {"inst": "AVLIX", "retail": "TWVLX"},
    "Goldman Sachs Equity Income": {"inst": "GSIIX", "retail": "GSGRX"},
}
# Institutional index funds = implementable benchmark (Req 7, Ch 10 slides 31-34).
INDEX_FUNDS = {
    "Vanguard Institutional Index":     {"index": "VINIX"},
    "Vanguard Small-Cap Index":         {"index": "VSCIX"},
    "Vanguard Value Index":             {"index": "VIVIX"},
}
# Minimum initial investment (USD) and maximum front-end sales charge. Yahoo does not report
# either, so each value is entered by hand with the page it came from (SOURCES). Confirm against
# the current prospectus before submitting.
MIN_INVEST = {
    "HLIEX": 1_000_000, "MADVX": 2_000_000, "LAFYX": 1_000_000, "AVLIX": 5_000_000, "GSIIX": 1_000_000,
    "VINIX": 5_000_000, "VSCIX": 5_000_000, "VIVIX": 5_000_000,
    "OIEIX": 1_000, "MDDVX": 1_000, "LAFFX": 1_000, "TWVLX": 2_500, "GSGRX": 1_000,
}
# Paid once at purchase by retail A-share buyers; NOT in the expense ratio. All other classes: none.
MAX_LOAD = {"OIEIX": 0.0525, "MDDVX": 0.0525, "LAFFX": 0.0575, "GSGRX": 0.0550}
SOURCES = {
    "HLIEX": "https://www.morningstar.com/funds/xnas/hliex/quote",
    "MADVX": "https://www.morningstar.com/funds/xnas/madvx/strategy",
    "LAFYX": "https://zacks.com/funds/mutual-fund/quote/LAFYX/class-info",
    "AVLIX": "https://www.americancentury.com/advisors/sales-information/minimums-pricing/share-classes/i",
    "GSIIX": "https://www.zacks.com/funds/mutual-fund/quote/GSIIX/class-info",
    "VINIX": "https://www.morningstar.com/funds/xnas/vinix/quote",
    "VSCIX": "https://zacks.com/funds/mutual-fund/quote/VSCIX/class-info",
    "VIVIX": "https://www.zacks.com/funds/mutual-fund/quote/VIVIX/class-info",
    "OIEIX": "https://am.jpmorgan.com/us/en/asset-management/adv/products/jpmorgan-equity-income-fund-a-4812c0464.md",
    "MDDVX": "https://www.aaii.com/fund/ticker/MDDVX",
    "LAFFX": "https://sec.gov/Archives/edgar/data/2691/000093041324000734/0000930413-24-000734.txt",
    "TWVLX": "https://www.americancentury.com/invest/funds/value/avlix/",
    "GSGRX": "https://www.sec.gov/Archives/edgar/data/822977/000119312519056769/d636625d485bpos.htm",
}
LOAD_HORIZONS = (3, 5, 10)      # years over which the retail load is spread (sensitivity, Req 10)

WINSOR_MAIN = (0.01, 0.99)      # winsorized versions kept for the sensitivity analysis (Req 10)
WINSOR_ALT = (0.05, 0.95)
CHECK_TOL = 0.005               # flag |our TR - Adj Close TR| > 0.5% in a month
OUTLIER_Z = 4.0                 # flag months more than 4 sd from the class's own mean

KF_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
KF_FILES = {"F-F_Research_Data_Factors": "F-F_Research_Data_Factors.csv",
            "F-F_Momentum_Factor": "F-F_Momentum_Factor.csv"}


def universe():
    """(group, fund, ticker, investor) for every share class."""
    rows = []
    for group, funds in (("active", ACTIVE_FUNDS), ("index", INDEX_FUNDS)):
        for fund, classes in funds.items():
            rows += [(group, fund, tk, inv) for inv, tk in classes.items()]
    return rows


def raw(name):
    return os.path.join(RAW_DIR, name)


def clean(name):
    return os.path.join(CLEAN_DIR, name)


# ---------------------------------------------------------------------------
# 2. DOWNLOAD (online, run once)
# ---------------------------------------------------------------------------
def download_yahoo():
    import yfinance as yf
    end = dt.date.today().isoformat()
    infos, missing = [], []
    for group, fund, tk, inv in universe():
        print(f"Yahoo: {tk} ({fund}, {inv})")
        t = yf.Ticker(tk)
        df = t.history(start=START, end=end, interval="1d", auto_adjust=False, actions=True)
        if df.empty:
            missing.append(tk)
            print(f"  !! no price data for {tk} - check the ticker")
            continue
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        for col in ["Dividends", "Capital Gains", "Stock Splits"]:
            if col not in df.columns:
                df[col] = 0.0
        df = df[["Close", "Adj Close", "Dividends", "Capital Gains", "Stock Splits"]]
        df.to_csv(raw(f"daily_{tk}.csv"), index_label="Date")   # raw: no cleaning here
        infos.append({"group": group, "fund": fund, "investor": inv, **get_info(t, tk)})
    pd.DataFrame(infos).to_csv(raw("fund_info.csv"), index=False)
    if missing:
        print(f"  tickers with NO data: {missing}")


def get_info(t, ticker):
    """Current snapshot only - Yahoo keeps no fee history."""
    row = {"ticker": ticker, "retrieved": dt.date.today().isoformat()}
    try:
        info = t.info or {}
    except Exception as e:  # noqa: BLE001
        info, row["info_error"] = {}, str(e)
    # annualReportExpenseRatio and annualHoldingsTurnover are DECIMALS (0.0051 = 0.51%);
    # netExpenseRatio is in PERCENT (0.51). totalAssets is fund-wide (all share classes), $.
    for k in ["longName", "fundFamily", "legalType", "annualReportExpenseRatio",
              "netExpenseRatio", "annualHoldingsTurnover", "totalAssets", "fundInceptionDate"]:
        row[k] = info.get(k)
    if row.get("fundInceptionDate") is not None:
        row["fundInceptionDate"] = (dt.date(1970, 1, 1) +
                                    dt.timedelta(seconds=int(row["fundInceptionDate"]))).isoformat()
    try:  # fund vs Morningstar-category average expense ratio
        ops = t.funds_data.fund_operations
        if ops is not None and "Annual Report Expense Ratio" in ops.index:
            v = ops.loc["Annual Report Expense Ratio"]
            row["category_avg_expense_ratio"] = v.iloc[1] if len(v) > 1 else None
    except Exception as e:  # noqa: BLE001
        row["funds_data_error"] = str(e)
    return row


def download_french():
    for zname, csvname in KF_FILES.items():
        print(f"Ken French: {zname}")
        with urllib.request.urlopen(f"{KF_URL}{zname}_CSV.zip", timeout=60) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        member = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with open(raw(csvname), "wb") as f:
            f.write(z.read(member))


# ---------------------------------------------------------------------------
# 3. BUILD (offline)
# ---------------------------------------------------------------------------
LOG = []


def log(step, ticker, n, detail=""):
    LOG.append({"step": step, "ticker": ticker, "n_affected": int(n), "detail": detail})


def load_factors():
    """Parse the monthly block of the Ken French CSVs; convert % to decimals."""
    def parse(path):
        rows = []
        with open(path, encoding="latin-1") as f:
            header = None
            for line in f:
                if "annual" in line.lower() and header is not None:
                    break                                   # monthly block ends here
                parts = [p.strip() for p in line.split(",")]
                if header is None and len(parts) > 1 and parts[0] == "" and parts[1]:
                    header = [p.lower().replace("-", "") for p in parts[1:]]
                elif header is not None and re.fullmatch(r"\d{6}", parts[0]):
                    rows.append([parts[0]] + [float(x) for x in parts[1:len(header) + 1]])
        df = pd.DataFrame(rows, columns=["yyyymm"] + header)
        df["month"] = pd.PeriodIndex(df.pop("yyyymm"), freq="M")
        return df.set_index("month") / 100.0

    ff = parse(raw(KF_FILES["F-F_Research_Data_Factors"]))
    mom = parse(raw(KF_FILES["F-F_Momentum_Factor"])).rename(columns={"mom": "umd"})
    fac = ff.join(mom, how="inner")[["mktrf", "smb", "hml", "umd", "rf"]]
    fac = fac[fac.index >= pd.Period(FIRST_MONTH, "M")]
    bad = fac.isna().any(axis=1) | (fac <= -0.99).any(axis=1)
    log("factors: rows with missing/-99.99 values dropped", "FF", bad.sum())
    return fac[~bad]


def load_daily(tk):
    df = pd.read_csv(raw(f"daily_{tk}.csv"), parse_dates=["Date"], index_col="Date").sort_index()
    log("daily: raw trading days", tk, len(df))
    n0 = len(df)
    df = df[~df.index.duplicated(keep="last")]
    log("daily: duplicate dates removed", tk, n0 - len(df))
    bad = df["Close"].isna() | (df["Close"] <= 0)
    log("daily: missing / non-positive NAV removed", tk, bad.sum())
    df = df[~bad].copy()
    for c in ["Dividends", "Capital Gains"]:
        df[c] = df[c].fillna(0.0)
    # Yahoo usually folds capital gains into 'Dividends'; if a day shows the SAME amount in both
    # columns it is one distribution reported twice -> count it once.
    dup = (df["Capital Gains"] > 0) & np.isclose(df["Dividends"], df["Capital Gains"])
    df.loc[dup, "Capital Gains"] = 0.0
    log("daily: distribution double-reported in Dividends and Capital Gains", tk, dup.sum())
    return df


def monthly_total_return(df):
    """
    Total return, ALL distributions reinvested on the ex-date (Req 3, Ch 16):
        r_d = (NAV_d + Div_d + CapGain_d) / NAV_{d-1} - 1,  compounded within each calendar month.
    'Close' with auto_adjust=False is the NAV adjusted for splits only, not for distributions.
    """
    nav = df["Close"]
    dist = df["Dividends"] + df["Capital Gains"]
    r = ((nav + dist) / nav.shift(1) - 1).iloc[1:]
    by = r.index.to_period("M")
    out = pd.DataFrame({"ret_net": (1 + r).groupby(by).prod() - 1,
                        "n_days": r.groupby(by).count()})
    adj = df["Adj Close"].groupby(df.index.to_period("M")).last()
    out["ret_adjclose"] = adj.pct_change()
    out["nav_end"] = nav.groupby(nav.index.to_period("M")).last()
    out["dist_month"] = dist.groupby(dist.index.to_period("M")).sum()
    out.index.name = "month"
    return out


def winsorize(s, lo, hi):
    a, b = s.quantile(lo), s.quantile(hi)
    return s.clip(a, b), int(((s < a) | (s > b)).sum())


def expense_ratio_history():
    """Optional hand-collected fee history (annual reports): ticker, date, exp_ratio (decimal)."""
    p = raw("expense_ratio_history.csv")
    if os.path.exists(p):
        return pd.read_csv(p, parse_dates=["date"])
    return None


def attach_expense_ratio(m, tk, hist, snap):
    """
    Annual expense ratio for every month, converted to monthly as ER/12 (Req 3).
    History: a fiscal-year ER applies to the months up to its report date -> merge_asof 'forward';
    months after the last report keep the last known ER. Otherwise: Yahoo snapshot (constant).
    """
    m = m.copy()
    h = None if hist is None else hist[hist["ticker"] == tk].sort_values("date")
    if h is not None and len(h):
        key = pd.DataFrame({"date": m.index.to_timestamp(how="end").normalize()})
        fw = pd.merge_asof(key, h[["date", "exp_ratio"]], on="date", direction="forward")
        bw = pd.merge_asof(key, h[["date", "exp_ratio"]], on="date", direction="backward")
        m["er_annual"] = fw["exp_ratio"].fillna(bw["exp_ratio"]).to_numpy()
        m["er_source"] = "annual_report"
    else:
        m["er_annual"] = snap
        m["er_source"] = "yahoo_snapshot" if pd.notna(snap) else "missing"
    log("fees: months with no expense ratio (gross return set to missing)", tk,
        m["er_annual"].isna().sum())
    m["er_monthly"] = m["er_annual"] / 12.0
    m["ret_gross"] = m["ret_net"] + m["er_monthly"]                  # Wermers (2000) gross-of-fee
    return m


def build():
    for f in [KF_FILES["F-F_Research_Data_Factors"], KF_FILES["F-F_Momentum_Factor"], "fund_info.csv"]:
        if not os.path.exists(raw(f)):
            raise SystemExit(f"Missing data_raw/{f}. Run once with:  python get_data.py --download")
    fac = load_factors()
    last = fac.index.max()
    info = pd.read_csv(raw("fund_info.csv")).set_index("ticker")
    hist = expense_ratio_history()

    rets, dists, checks = [], [], []
    for group, fund, tk, inv in universe():
        if not os.path.exists(raw(f"daily_{tk}.csv")):
            log("missing: share class with no raw data file (excluded)", tk, 0)
            continue
        d = load_daily(tk)
        m = monthly_total_return(d)

        # sample window: drop inception month (no prior NAV -> incomplete month), keep FIRST_MONTH..last
        first = d.index.min().to_period("M")
        keep = (m.index > first) & (m.index >= pd.Period(FIRST_MONTH, "M")) & (m.index <= last)
        log("sample: months outside Jan-2011..factor end, or inception month", tk, (~keep).sum())
        m = m[keep]
        full = pd.period_range(m.index.min(), m.index.max(), freq="M")
        log("missing: months with no return inside the class's history (left missing)", tk,
            len(full) - len(m))
        m = m.reindex(full)
        m.index.name = "month"

        m = attach_expense_ratio(m, tk, hist, info["annualReportExpenseRatio"].get(tk, np.nan))
        m = m.join(fac[["rf"]])
        m["ex_net"] = m["ret_net"] - m["rf"]
        m["ex_gross"] = m["ret_gross"] - m["rf"]

        # outliers: flag, do not drop (fund NAVs are struck by the fund; big months are real)
        z = (m["ret_net"] - m["ret_net"].mean()) / m["ret_net"].std()
        m["outlier_flag"] = z.abs() > OUTLIER_Z
        log(f"outliers: |z| > {OUTLIER_Z} flagged (kept)", tk, m["outlier_flag"].sum())

        # return-construction check vs Yahoo Adj Close
        diff = m["ret_net"] - m["ret_adjclose"]
        bad = diff.abs() > CHECK_TOL
        log(f"check: |TR - Adj Close TR| > {CHECK_TOL:.1%}", tk, bad.sum())
        if bad.any():
            checks.append(m.loc[bad, ["ret_net", "ret_adjclose", "dist_month"]]
                          .assign(diff=diff[bad]).reset_index().assign(ticker=tk))

        m = m.reset_index()
        for col, val in (("max_load", MAX_LOAD.get(tk, 0.0)),
                         ("min_investment", MIN_INVEST.get(tk, np.nan)), ("investor", inv),
                         ("ticker", tk), ("fund", fund), ("group", group)):
            m.insert(0, col, val)
        rets.append(m)
        log("monthly: observations kept", tk, m["ret_net"].notna().sum())

        dd = d.loc[(d["Dividends"] > 0) | (d["Capital Gains"] > 0), ["Close", "Dividends", "Capital Gains"]]
        dists.append(dd.reset_index().rename(columns={"Date": "ex_date"}).assign(ticker=tk))

    cls = pd.concat(rets, ignore_index=True)
    os.makedirs(CLEAN_DIR, exist_ok=True)
    cls.assign(month=cls["month"].astype(str)).to_csv(clean("monthly_returns.csv"), index=False)
    pd.concat(dists, ignore_index=True).to_csv(clean("distributions.csv"), index=False)
    (pd.concat(checks, ignore_index=True) if checks else
     pd.DataFrame(columns=["ticker", "month", "ret_net", "ret_adjclose", "dist_month", "diff"])) \
        .to_csv(clean("return_check.csv"), index=False)
    fac.reset_index().assign(month=lambda x: x["month"].astype(str)) \
        .to_csv(clean("factors_monthly.csv"), index=False)

    fund_level(cls, fac)
    pairs(cls)
    index_returns(cls)
    fee_table(cls, info)
    pd.DataFrame(LOG).to_csv(clean("cleaning_log.csv"), index=False)
    summary(cls)


def fund_level(cls, fac):
    """One series per (fund, investor class) + factors; winsorized copies for sensitivity (Req 10)."""
    keep = ["group", "fund", "investor", "ticker", "month", "ret_net", "ret_gross", "er_monthly", "max_load"]
    f = cls[keep].merge(fac.reset_index(), on="month", how="left").reset_index(drop=True)
    f["ex_net"] = f["ret_net"] - f["rf"]
    f["ex_gross"] = f["ret_gross"] - f["rf"]
    # front-end load spread evenly (geometrically) over an H-year holding period:
    # (1 - load) ** (1 / 12H) per month, so the H-year wealth loss equals the load exactly
    for h in LOAD_HORIZONS:
        drag = (1 - f["max_load"]) ** (1 / (12 * h))
        f[f"ex_net_load{h}y"] = (1 + f["ret_net"]) * drag - 1 - f["rf"]
    for tag, (lo, hi) in {"w1": WINSOR_MAIN, "w5": WINSOR_ALT}.items():
        parts = []
        for tk, grp in f.groupby("ticker"):
            w, n = winsorize(grp["ret_net"], lo, hi)
            log(f"winsorize {lo:.0%}/{hi:.0%}: months clipped ({tag}, sensitivity only)", tk, n)
            parts.append(w)
        f[f"ret_net_{tag}"] = pd.concat(parts)
        f[f"ex_net_{tag}"] = f[f"ret_net_{tag}"] - f["rf"]
        f[f"ex_gross_{tag}"] = f[f"ex_net_{tag}"] + f["er_monthly"]
    f.assign(month=f["month"].astype(str)).sort_values(["group", "fund", "investor", "month"]) \
        .to_csv(clean("fund_monthly.csv"), index=False)


def pairs(cls):
    """
    Institutional vs retail class of each fund, month by month. Same portfolio, so the gross gap
    should be ~0 and the net gap should equal the fee gap (a check on the data and the fee table).
    """
    a = cls[cls["group"] == "active"]
    w = a.pivot_table(index=["fund", "month"], columns="investor",
                      values=["ret_net", "ret_gross", "er_monthly"])
    w.columns = [f"{v}_{inv}" for v, inv in w.columns]
    w = w.reset_index()
    w["net_gap"] = w["ret_net_inst"] - w["ret_net_retail"]
    w["gross_gap"] = w["ret_gross_inst"] - w["ret_gross_retail"]
    w["fee_gap"] = w["er_monthly_retail"] - w["er_monthly_inst"]
    for fund, g in w.groupby("fund"):
        log("check: |annual gross gap inst vs retail| > 0.05% (same portfolio)", fund,
            abs(g["gross_gap"].mean() * 12) > 0.0005,
            f"gross gap {g['gross_gap'].mean() * 12:+.3%}/yr, net gap {g['net_gap'].mean() * 12:+.3%}/yr, "
            f"fee gap {g['fee_gap'].mean() * 12:.3%}/yr")
    w.assign(month=w["month"].astype(str)).to_csv(clean("pairs_monthly.csv"), index=False)


def index_returns(cls):
    idx = cls[cls["group"] == "index"].pivot(index="month", columns="ticker", values="ret_net").dropna()
    idx.index = idx.index.astype(str)
    idx.to_csv(clean("index_returns.csv"))


def fee_table(cls, info):
    ok = cls.dropna(subset=["ret_net"])
    last = ok.sort_values("month").groupby("ticker").tail(1)
    span = ok.groupby("ticker")["month"].agg(["min", "max", "count"])
    t = last[["group", "fund", "investor", "ticker", "min_investment", "max_load", "er_annual",
              "er_source"]].set_index("ticker")
    t = t.join(span.rename(columns={"min": "first_month", "max": "last_month", "count": "n_months"}))
    for k, new in [("longName", "share_class_name"), ("annualHoldingsTurnover", "turnover"),
                   ("totalAssets", "fund_total_assets_usd"),
                   ("category_avg_expense_ratio", "category_avg_er"), ("retrieved", "snapshot_date")]:
        if k in info:
            t[new] = info[k]
    # fee gap retail - institutional within each fund (same portfolio = whole net-return gap)
    gap = t[t["group"] == "active"].pivot_table(index="fund", columns="investor", values="er_annual")
    t["fee_gap_vs_inst"] = t.apply(lambda r: r["er_annual"] - gap.loc[r["fund"], "inst"]
                                   if r["fund"] in gap.index else np.nan, axis=1)
    t["min_load_source_url"] = [SOURCES.get(tk, "") for tk in t.index]
    order = {"inst": 0, "index": 1, "retail": 2}
    t = t.reset_index().assign(o=lambda x: x["investor"].map(order)) \
        .sort_values(["o", "fund"]).drop(columns="o")
    t.assign(first_month=t["first_month"].astype(str), last_month=t["last_month"].astype(str)) \
        .to_csv(clean("fees.csv"), index=False)


def summary(cls):
    lg = pd.DataFrame(LOG)
    print("\nCleaning steps (observations affected, all share classes):")
    print(lg.groupby("step")["n_affected"].sum().to_string())
    ok = cls.dropna(subset=["ret_net"])
    print(f"\nShare classes: {ok['ticker'].nunique()}   sample: {ok['month'].min()} .. {ok['month'].max()}")
    print(ok.groupby(["fund", "investor", "ticker"])["month"].agg(["min", "max", "count"]).to_string())


# ---------------------------------------------------------------------------
# 4. RUN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CFM301 Project 5 data stage")
    ap.add_argument("--download", action="store_true", help="pull raw data (internet needed)")
    a = ap.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    if a.download:
        download_yahoo()
        download_french()
    build()
