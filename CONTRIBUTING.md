# Contributing

Thanks for trying this out. This project has more rules than most, and they are written down
here so you don't waste effort on a change I will not merge.

## 1. Get it running

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

python -m unittest discover -s tests -v     # expect 132 passing
python -m app.server --open                 # opens http://127.0.0.1:8765
```

**The test suite does not need yfinance, akshare or requests** — they are imported lazily, only
when you actually fetch data. If `pip install akshare` fails on your machine, skip it; the tests
still run.

## 2. What to include in a bug report

Without these I can only guess:

1. **What you ran** (full command, or which buttons you clicked and what you entered)
2. **Expected vs actual**
3. **The raw error** (terminal output, or F12 → Console in the browser)
4. If it is data-related: **the first 3 lines of the CSV**, plus market and ticker
5. Python version and OS

## 3. Rules for changes

### 3.1 No investment-advice phrasing

Code, comments, reports and UI copy must not contain phrases equivalent to
"buy recommendation", "sell recommendation", "target price", "guaranteed to rise/fall".
`tests/test_stock_report.py` enforces this on generated reports. It is a hard rule, not a style preference.

### 3.2 Market and ticker must match

`002541.SZ` is an A-share ticker. Hand it to the "US" fetcher and Yahoo will happily return it
(Shenzhen tickers use exactly that suffix), so you end up with A-share data labelled `us` —
the data is real, the label is fake, and the report lies.

Locked down by `app/server.py::market_mismatch` and `tests/test_market_match.py`.

### 3.3 Do not relax the verdict

The bar is: **the 95% confidence interval of excess return over buy-and-hold has a lower bound > 0,
on out-of-sample data.**

If you want to test a new idea, write a new card (`cards/*.json`) with its mechanism and parameters,
run it once, and report the result. **Do not change parameters and re-run until it passes** —
that is re-rolling the exam and it corrupts every downstream significance claim.

### 3.4 Data sources must stay pluggable

To add a market (Hong Kong, futures, ...), implement `DataFetcher` from `data/base.py` and register
it in `data/registry.py`. Import third-party libraries **inside functions**, never at module level
(`tests/test_import_hygiene.py` will catch it).

## 4. Verifying your own change

```bash
# Independent referee: re-derives the numbers without importing project code
python referee/profile_check.py --csv data_cache/cn_600519_2020-01-01_2025-12-31.csv
```

## 5. Changes I will not merge

- More technical indicators (MACD / KDJ / Bollinger) without explaining why the existing evidence
  is insufficient
- Lowering the pass threshold from 95%, or replacing "excess over buy-and-hold" with "absolute return > 0"
- Any look-ahead bias in the backtest (e.g. using today's close to decide a fill at today's open)
- Declaring a strategy valid on a sample of fewer than 10 tickers