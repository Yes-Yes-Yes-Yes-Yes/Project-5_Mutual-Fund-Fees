"""
CFM301 Project 5 - Are the fees justified?  Institutional share classes of active funds.
DATA STAGE: download the raw data, build monthly returns, clean them.

Question: do the institutional share classes of active large-cap value funds earn enough before
fees to justify what they charge, and should institutions pay a flat fee, a fulcrum fee, or index?

Funds: five active large-cap value funds through their INSTITUTIONAL class ($1M-$5M minimum),
benchmarked against three Vanguard INSTITUTIONAL index funds ($5M minimum). Every class has full
daily history from 2010-12-01, so all series cover the same months (2011-01 .. last factor month).

HOW TO RUN
  python get_data.py --download   # online, run once: refreshes the downloaded files in data_raw/
  python get_data.py              # offline: builds data_clean/ from data_raw/ only

WHERE EACH INPUT COMES FROM (all files in data_raw/)
  daily_<TICKER>.csv             DOWNLOADED by this script from Yahoo Finance (yfinance package),
                                 https://finance.yahoo.com/quote/<TICKER>/history
                                 columns: Date, Close (NAV, split-adjusted only), Adj Close,
                                 Dividends, Capital Gains, Stock Splits
  F-F_Research_Data_Factors.csv  DOWNLOADED by this script from the Ken French Data Library,
  F-F_Momentum_Factor.csv        https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
                                 Mkt-RF, SMB, HML, RF, Mom in % per month
  expense_ratio_history.csv      TYPED IN BY HAND (not downloaded): one row per fund per fiscal year,
                                 the NET expense ratio (after waivers) and portfolio turnover from the
                                 "Financial Highlights" table of each fund's annual report (Form N-CSR)
                                 on SEC EDGAR, https://www.sec.gov/edgar/search/. Each row names its
                                 report in 'source' and links the filing in 'source_url'. Fiscal years
                                 whose report is not filed yet are left blank and carried forward.
  MIN_INVEST / MIN_INVEST_URL    (below, in this file) minimum initial investment, typed in by hand
                                 from the page in MIN_INVEST_URL.

OUTPUTS (data_clean/)
  monthly_returns.csv   one row per share class and month: net return, expense ratio, gross return,
                        RF, excess returns, outlier flag
  fund_monthly.csv      the analysis file: net/gross excess returns (raw and winsorized 1/99, 5/95)
                        with the factors merged in
  factors_monthly.csv   mktrf, smb, hml, umd, rf (decimals)
  index_returns.csv     monthly net returns of the three index funds, side by side
  fees.csv              one row per class: minimum, latest expense ratio and turnover, their sources
  distributions.csv     every dividend / capital-gain distribution
  return_check.csv      months where our return differs from Yahoo's Adj Close by more than 0.5%
  cleaning_log.csv      every cleaning step and how many observations it affected
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
# 1. SETTINGS
# ---------------------------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR, CLEAN_DIR = os.path.join(BASE, "data_raw"), os.path.join(BASE, "data_clean")

START = "2010-12-01"            # one month early: the Jan 2011 return needs the Dec 2010 NAV
FIRST_MONTH = "2011-01"         # sample start; sample end = last month in the factor file

# fund name -> {investor type: ticker}
ACTIVE_FUNDS = {                # active large-cap value funds, institutional class only
    "JPMorgan Equity Income":      {"inst": "HLIEX"},
    "BlackRock Equity Dividend":   {"inst": "MADVX"},
    "Lord Abbett Affiliated":      {"inst": "LAFYX"},
    "American Century Value":      {"inst": "AVLIX"},
    "Goldman Sachs Equity Income": {"inst": "GSIIX"},
}
INDEX_FUNDS = {                 # institutional index funds = the cheap alternative (benchmark)
    "Vanguard Institutional Index": {"index": "VINIX"},
    "Vanguard Small-Cap Index":     {"index": "VSCIX"},
    "Vanguard Value Index":         {"index": "VIVIX"},
}

# Minimum initial investment (USD), typed in by hand from the page in MIN_INVEST_URL.
MIN_INVEST = {
    "HLIEX": 1_000_000, "MADVX": 2_000_000, "LAFYX": 1_000_000, "AVLIX": 5_000_000, "GSIIX": 1_000_000,
    "VINIX": 5_000_000, "VSCIX": 5_000_000, "VIVIX": 5_000_000,
}
MIN_INVEST_URL = {
    "HLIEX": "https://www.morningstar.com/funds/xnas/hliex/quote",
    "MADVX": "https://www.morningstar.com/funds/xnas/madvx/strategy",
    "LAFYX": "https://zacks.com/funds/mutual-fund/quote/LAFYX/class-info",
    "AVLIX": "https://www.americancentury.com/advisors/sales-information/minimums-pricing/share-classes/i",
    "GSIIX": "https://www.zacks.com/funds/mutual-fund/quote/GSIIX/class-info",
    "VINIX": "https://www.morningstar.com/funds/xnas/vinix/quote",
    "VSCIX": "https://zacks.com/funds/mutual-fund/quote/VSCIX/class-info",
    "VIVIX": "https://www.zacks.com/funds/mutual-fund/quote/VIVIX/class-info",
}

FEE_FILE = "expense_ratio_history.csv"      # hand-collected from annual reports, see top of file

KF_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
KF_FILES = {"F-F_Research_Data_Factors": "F-F_Research_Data_Factors.csv",   # zip name -> saved csv
            "F-F_Momentum_Factor": "F-F_Momentum_Factor.csv"}

CHECK_TOL = 0.005               # flag months where |our return - Adj Close return| > 0.5%
OUTLIER_Z = 4.0                 # flag months more than 4 s.d. from the class's own mean (kept)
WINSOR_MAIN = (0.01, 0.99)      # winsorized copies, for the sensitivity analysis only
WINSOR_ALT = (0.05, 0.95)


def universe():
    """List every share class as (group, fund, ticker, investor)."""
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
# 2. DOWNLOAD (online, run once with --download)
# ---------------------------------------------------------------------------
def download_yahoo():
    """Daily NAV and distributions for every share class -> data_raw/daily_<TICKER>.csv (unchanged)."""
    import yfinance as yf
    end = dt.date.today().isoformat()
    for _, fund, tk, _ in universe():
        print(f"Yahoo: {tk} ({fund})")
        # auto_adjust=False keeps 'Close' as the actual NAV (not reduced for distributions)
        df = yf.Ticker(tk).history(start=START, end=end, interval="1d", auto_adjust=False, actions=True)
        if df.empty:
            print(f"  !! no price data for {tk} - check the ticker")
            continue
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        for col in ["Dividends", "Capital Gains", "Stock Splits"]:
            if col not in df.columns:
                df[col] = 0.0
        df = df[["Close", "Adj Close", "Dividends", "Capital Gains", "Stock Splits"]]
        df.to_csv(raw(f"daily_{tk}.csv"), index_label="Date")


def download_french():
    """Monthly factors from the Ken French Data Library (zipped CSV) -> data_raw/ (unchanged)."""
    for zname, csvname in KF_FILES.items():
        print(f"Ken French: {zname}")
        with urllib.request.urlopen(f"{KF_URL}{zname}_CSV.zip", timeout=60) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        member = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with open(raw(csvname), "wb") as f:
            f.write(z.read(member))


# ---------------------------------------------------------------------------
# 3. READ AND CLEAN THE RAW FILES (offline)
# ---------------------------------------------------------------------------
LOG = []                        # one entry per cleaning step -> data_clean/cleaning_log.csv


def log(step, ticker, n, detail=""):
    LOG.append({"step": step, "ticker": ticker, "n_affected": int(n), "detail": detail})


def load_factors():
    """Monthly block of the two Ken French files, joined and converted from % to decimals."""
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
    bad = fac.isna().any(axis=1) | (fac <= -0.99).any(axis=1)      # French codes missing as -99.99
    log("factors: rows with missing/-99.99 values dropped", "FF", bad.sum())
    return fac[~bad]


def load_daily(tk):
    """One class's daily file, with duplicate dates, bad NAVs and double-counted payouts removed."""
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
    # Yahoo usually folds capital gains into 'Dividends'; the SAME amount in both columns on one
    # day is one distribution reported twice -> count it once.
    dup = (df["Capital Gains"] > 0) & np.isclose(df["Dividends"], df["Capital Gains"])
    df.loc[dup, "Capital Gains"] = 0.0
    log("daily: distribution double-reported in Dividends and Capital Gains", tk, dup.sum())
    return df


def load_fee_history():
    """
    The hand-collected annual-report fees (data_raw/expense_ratio_history.csv).
    Rows still blank (report not filed yet) are dropped; % are converted to decimals.
    """
    p = raw(FEE_FILE)
    if not os.path.exists(p):
        raise SystemExit(f"Missing data_raw/{FEE_FILE} (typed in from the funds' annual reports).")
    h = pd.read_csv(p, parse_dates=["fiscal_year_end"])
    h = h.dropna(subset=["expense_ratio_pct"])
    h["exp_ratio"] = h["expense_ratio_pct"] / 100.0
    h["turnover"] = h["turnover_pct"] / 100.0
    return h.rename(columns={"fiscal_year_end": "date"})


# ---------------------------------------------------------------------------
# 4. CONSTRUCT RETURNS
# ---------------------------------------------------------------------------
def monthly_total_return(df):
    """
    Net total return with every distribution reinvested on its ex-date:
        r_d = (NAV_d + Div_d + CapGain_d) / NAV_{d-1} - 1,  compounded within each calendar month.
    The NAV is struck after the fund deducts its fees, so this return is already NET of fees.
    Yahoo's Adj Close return is kept only as a cross-check.
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


def add_fees(m, tk, fees):
    """
    Give every month its fund's expense ratio and turnover, then the gross-of-fee return.
    A month gets the ratio of the fiscal year it falls in (the first fiscal year-end on or after
    it). Months after the latest annual report keep the last ratio, labelled '(carried forward)'.
    Monthly fee = annual ratio / 12;  gross return = net return + monthly fee (Wermers, 2000).
    """
    m = m.copy()
    h = fees[fees["ticker"] == tk].sort_values("date")
    if h.empty:
        raise SystemExit(f"No fee rows for {tk} in data_raw/{FEE_FILE}.")
    month_end = pd.DataFrame({"date": m.index.to_timestamp(how="end").normalize()})
    cols = ["date", "exp_ratio", "turnover", "source"]
    this_fy = pd.merge_asof(month_end, h[cols], on="date", direction="forward")   # fiscal year it falls in
    last_fy = pd.merge_asof(month_end, h[cols], on="date", direction="backward")  # latest year reported
    carried = this_fy["exp_ratio"].isna() & last_fy["exp_ratio"].notna()
    for c in ("exp_ratio", "turnover", "source"):
        this_fy[c] = this_fy[c].where(~carried, last_fy[c])
    m["er_annual"] = this_fy["exp_ratio"].to_numpy()
    m["turnover_annual"] = this_fy["turnover"].to_numpy()
    m["er_source"] = this_fy["source"].where(~carried, this_fy["source"] + " (carried forward)").to_numpy()
    log("fees: months using the last reported fiscal year (carried forward)", tk, carried.sum())
    log("fees: months with expense ratio from annual reports", tk, m["er_annual"].notna().sum())
    log("fees: months with no expense ratio (gross return set to missing)", tk,
        m["er_annual"].isna().sum())
    m["er_monthly"] = m["er_annual"] / 12.0
    m["ret_gross"] = m["ret_net"] + m["er_monthly"]
    return m


def winsorize(s, lo, hi):
    """Clip a series at its lo/hi quantiles; also return how many values were clipped."""
    a, b = s.quantile(lo), s.quantile(hi)
    return s.clip(a, b), int(((s < a) | (s > b)).sum())


# ---------------------------------------------------------------------------
# 5. BUILD data_clean/
# ---------------------------------------------------------------------------
def build():
    for f in KF_FILES.values():
        if not os.path.exists(raw(f)):
            raise SystemExit(f"Missing data_raw/{f}. Run once with:  python get_data.py --download")
    fac = load_factors()
    last = fac.index.max()
    fees = load_fee_history()

    rets, dists, checks = [], [], []
    for group, fund, tk, inv in universe():
        if not os.path.exists(raw(f"daily_{tk}.csv")):
            log("missing: share class with no raw data file (excluded)", tk, 0)
            continue
        d = load_daily(tk)
        m = monthly_total_return(d)

        # sample window: FIRST_MONTH .. last factor month, minus the (incomplete) inception month
        first = d.index.min().to_period("M")
        keep = (m.index > first) & (m.index >= pd.Period(FIRST_MONTH, "M")) & (m.index <= last)
        log("sample: months outside Jan-2011..factor end, or inception month", tk, (~keep).sum())
        m = m[keep]
        full = pd.period_range(m.index.min(), m.index.max(), freq="M")
        log("missing: months with no return inside the class's history (left missing)", tk,
            len(full) - len(m))
        m = m.reindex(full)
        m.index.name = "month"

        m = add_fees(m, tk, fees)
        m = m.join(fac[["rf"]])
        m["ex_net"] = m["ret_net"] - m["rf"]
        m["ex_gross"] = m["ret_gross"] - m["rf"]

        # outliers: flagged, not dropped (fund NAVs are struck by the fund; big months are real)
        z = (m["ret_net"] - m["ret_net"].mean()) / m["ret_net"].std()
        m["outlier_flag"] = z.abs() > OUTLIER_Z
        log(f"outliers: |z| > {OUTLIER_Z} flagged (kept)", tk, m["outlier_flag"].sum())

        # cross-check our return against Yahoo's Adj Close return
        diff = m["ret_net"] - m["ret_adjclose"]
        bad = diff.abs() > CHECK_TOL
        log(f"check: |TR - Adj Close TR| > {CHECK_TOL:.1%}", tk, bad.sum())
        if bad.any():
            checks.append(m.loc[bad, ["ret_net", "ret_adjclose", "dist_month"]]
                          .assign(diff=diff[bad]).reset_index().assign(ticker=tk))

        m = m.reset_index()
        for col, val in (("min_investment", MIN_INVEST.get(tk, np.nan)), ("investor", inv),
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

    write_fund_monthly(cls, fac)
    write_index_returns(cls)
    write_fee_table(cls)
    pd.DataFrame(LOG).to_csv(clean("cleaning_log.csv"), index=False)
    print_summary(cls)


def write_fund_monthly(cls, fac):
    """fund_monthly.csv: excess returns + factors per class and month, plus winsorized copies."""
    keep = ["group", "fund", "investor", "ticker", "month", "ret_net", "ret_gross", "er_monthly"]
    f = cls[keep].merge(fac.reset_index(), on="month", how="left").reset_index(drop=True)
    f["ex_net"] = f["ret_net"] - f["rf"]
    f["ex_gross"] = f["ret_gross"] - f["rf"]
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


def write_index_returns(cls):
    """index_returns.csv: the index funds' monthly net returns, one column per ticker."""
    idx = cls[cls["group"] == "index"].pivot(index="month", columns="ticker", values="ret_net").dropna()
    idx.index = idx.index.astype(str)
    idx.to_csv(clean("index_returns.csv"))


def write_fee_table(cls):
    """fees.csv: one row per class with its minimum and its latest expense ratio and turnover."""
    ok = cls.dropna(subset=["ret_net"])
    latest = ok.sort_values("month").groupby("ticker").tail(1)
    span = ok.groupby("ticker")["month"].agg(["min", "max", "count"])
    t = latest[["group", "fund", "investor", "ticker", "min_investment", "er_annual",
                "turnover_annual", "er_source"]].set_index("ticker")
    t = t.rename(columns={"turnover_annual": "turnover"})
    t = t.join(span.rename(columns={"min": "first_month", "max": "last_month", "count": "n_months"}))
    t["min_source_url"] = [MIN_INVEST_URL.get(tk, "") for tk in t.index]
    order = {"inst": 0, "index": 1}
    t = t.reset_index().assign(o=lambda x: x["investor"].map(order)) \
        .sort_values(["o", "fund"]).drop(columns="o")
    t.assign(first_month=t["first_month"].astype(str), last_month=t["last_month"].astype(str)) \
        .to_csv(clean("fees.csv"), index=False)


def print_summary(cls):
    lg = pd.DataFrame(LOG)
    print("\nCleaning steps (observations affected, all share classes):")
    print(lg.groupby("step")["n_affected"].sum().to_string())
    ok = cls.dropna(subset=["ret_net"])
    print(f"\nShare classes: {ok['ticker'].nunique()}   sample: {ok['month'].min()} .. {ok['month'].max()}")
    print(ok.groupby(["fund", "investor", "ticker"])["month"].agg(["min", "max", "count"]).to_string())


# ---------------------------------------------------------------------------
# 6. RUN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CFM301 Project 5 data stage")
    ap.add_argument("--download", action="store_true",
                    help="re-download the Yahoo and Ken French files first (internet needed)")
    a = ap.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    if a.download:
        download_yahoo()
        download_french()
    build()
