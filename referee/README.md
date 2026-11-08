# referee — independent referees

These scripts deliberately **do not import the project's own code**. The reason is one sentence:
using the code under test to verify the code under test is like letting the defendant testify.

| File | Purpose |
| --- | --- |
| `profile_check.py` | **Report verifier**: re-derives autocorrelation / variance ratio / permutation test from the raw CSV, then reconciles every number against a report in `reports/`. Exit code 0 = agreement, 1 = mismatch. |
| `verify.py` | The v1 mechanical verification suite (13 checks: file layout, report sections, banned phrases, exit codes, cache naming, ...) |
| `audit_recalc.py` | Independently recomputes the backtest and six risk figures from cached CSVs and compares them to a report |

## Usage

```bash
# Verify a report (most common)
python referee/profile_check.py \
  --csv data_cache/cn_600519_2020-01-01_2025-12-31.csv \
  --report reports/600519_分析报告_2026-11-08.md

# v1 mechanical verification
python referee/verify.py --root .

# Recompute a backtest independently from cache
python referee/audit_recalc.py --root . --report reports/AAPL_us_2024-01-01_2025-12-31.md
```

## What it cannot verify

- It does not judge whether a strategy "will make money" — that is the job of `tools/audit.py` and `cards/`
- The permutation z-score depends on a random seed, so it guarantees **verdict-level** agreement,
  not decimal agreement