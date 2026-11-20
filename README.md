# CFM 301 Project 5 — Are the Fees Justified? Institutional Share Classes

## Environment
- Python 3.14.3
- pandas 3.0.6, numpy 2.5.3
- Only for re-downloading: yfinance 1.8.0

```
pip install pandas==3.0.6 numpy==2.5.3     # needed to reproduce the results
pip install yfinance==1.8.0                 # needed only to re-download raw data
```

## How to run (from this folder)
1. `python get_data.py` builds every file in `data_clean/` from the files in `data_raw/`. It needs no internet connection and no login.
2. *(Optional: refreshes the raw data)* `python get_data.py --download` pulls fresh data from Yahoo Finance and Ken French.

## Funds
| Fund | Institutional, main analysis (min.) | Retail, sensitivity only (min., load) |
|---|---|---|
| JPMorgan Equity Income | HLIEX ($1,000,000) | OIEIX ($1,000, 5.25%) |
| BlackRock Equity Dividend | MADVX ($2,000,000) | MDDVX ($1,000, 5.25%) |
| Lord Abbett Affiliated | LAFYX ($1,000,000) | LAFFX ($1,000, 5.75%) |
| American Century Value | AVLIX ($5,000,000) | TWVLX ($2,500, none) |
| Goldman Sachs Equity Income | GSIIX ($1,000,000) | GSGRX ($1,000, 5.50%) |

Benchmark: Vanguard Institutional index funds VINIX, VSCIX and VIVIX, each with a $5,000,000 minimum. Minimums and loads aren't on Yahoo; they are entered in `get_data.py` (`MIN_INVEST`, `MAX_LOAD`), with the source page for each class in `SOURCES`. All 13 classes have 4,017 trading days (Dec 2010 to Nov 2026), giving 189 months (Jan 2011 to Sep 2026).

## Data
| File | Source |
|---|---|
| `data_raw/daily_<TICKER>.csv` | Yahoo Finance: Date, Close (NAV, split-adjusted only), Adj Close, Dividends (capital gains included), Capital Gains, Stock Splits |
| `data_raw/fund_info.csv` | Yahoo Finance snapshot: expense ratio, turnover, total assets, inception date, category average expense ratio |
| `data_raw/F-F_Research_Data_Factors.csv`, `F-F_Momentum_Factor.csv` | Ken French Data Library: Mkt-RF, SMB, HML, RF, Mom (% per month) |

## Construction (in `get_data.py`)
- **Total return**: r_d = (NAV_d + Div_d + CapGain_d) / NAV_{d−1} − 1, compounded within each month. It is checked against Yahoo Adj Close.
- **Fees**: annual expense ratio ÷ 12; gross return = net return + ER/12. The expense ratio is today's snapshot, applied to all 189 months. A `data_raw/expense_ratio_history.csv` (`ticker,date,exp_ratio,source_url`) is used instead if it exists.
- **Cleaning**: removes duplicate dates, missing NAVs and double-reported distributions, and trims to the sample window. Outliers (|z| > 4) are flagged and kept. Winsorized copies (1/99 and 5/95) and load-adjusted retail returns are for the sensitivity analysis only. Every step's count is in `cleaning_log.csv`.
- **Output for analysis**: `fund_monthly.csv`, one row per fund, investor group (`inst`, `index` or `retail`) and month, with the factors merged in.
