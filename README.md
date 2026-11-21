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
| Fund | Institutional class | Minimum initial investment |
|---|---|---|
| JPMorgan Equity Income | HLIEX | $1,000,000 |
| BlackRock Equity Dividend | MADVX | $2,000,000 |
| Lord Abbett Affiliated | LAFYX | $1,000,000 |
| American Century Value | AVLIX | $5,000,000 |
| Goldman Sachs Equity Income | GSIIX | $1,000,000 |
| Vanguard Institutional Index (benchmark) | VINIX | $5,000,000 |
| Vanguard Small-Cap Index (benchmark) | VSCIX | $5,000,000 |
| Vanguard Value Index (benchmark) | VIVIX | $5,000,000 |

Minimums aren't on Yahoo; they are entered in `get_data.py` (`MIN_INVEST`), with the source page for each class in `SOURCES`. All 8 classes have 4,018 trading days (Dec 1, 2010 to Nov 20, 2026), giving 189 months (Jan 2011 to Sep 2026).

## Data
| File | Source |
|---|---|
| `data_raw/daily_<TICKER>.csv` | Yahoo Finance: Date, Close (NAV, split-adjusted only), Adj Close, Dividends (capital gains included), Capital Gains, Stock Splits |
| `data_raw/fund_info.csv` | Yahoo Finance snapshot: expense ratio, turnover, total assets, inception date, category average expense ratio |
| `data_raw/F-F_Research_Data_Factors.csv`, `F-F_Momentum_Factor.csv` | Ken French Data Library: Mkt-RF, SMB, HML, RF, Mom (% per month) |
| `data_raw/expense_ratio_history.csv` | Annual reports (Form N-CSR, Financial Highlights) on SEC EDGAR: net expense ratio (after waivers) and turnover for every fiscal year 2011–2026, with the report in `source` and the filing link in `source_url`. Fiscal years whose report isn't filed yet are blank and carried forward. |

## Construction (in `get_data.py`)
- **Net total return**: r_d = (NAV_d + Div_d + CapGain_d) / NAV_{d−1} − 1, compounded within each month. The NAV is already net of the fund's fees. It is checked against Yahoo Adj Close.
- **Fees**: the monthly fee is each fiscal year's net expense ratio ÷ 12, applied to the months of that fiscal year; months after the last reported year keep the last ratio. Gross return = net return + monthly fee. Classes with no history yet fall back to Yahoo's current snapshot, labelled `yahoo_snapshot (history TBD)` in `er_source`. `python get_data.py --fee-template` writes a blank fee file.
- **Cleaning**: removes duplicate dates, missing NAVs and double-reported distributions, and trims to the sample window. Outliers (|z| > 4) are flagged and kept. Winsorized copies (1/99 and 5/95) are for the sensitivity analysis only. Every step's count is in `cleaning_log.csv`.
- **Output for analysis**: `fund_monthly.csv`, one row per fund, investor group (`inst` or `index`) and month, with the factors merged in.
