# Evaluation: how accurate is this thing, really?

Run on 2026-11-09 against live data. Everything below is reproducible with
`python -m tools.eval_accuracy` and `python -m tools.eval_live`.

## What "accuracy" can and cannot mean here

This project does **not** predict prices. It reports (a) whether the data is trustworthy and
(b) whether a past structure or a tested rule is distinguishable from luck. So there are only
two honest kinds of accuracy:

| Kind | Question | Result |
| --- | --- | --- |
| **System accuracy** | Does the pipeline compute correctly, reproducibly, and can an independent checker confirm it? | **100%** |
| **Verdict stability** | If we classify on the first 70% of history, does the verdict hold on the last 30%? | **72.5% overall, 8.0% for "structure detected"** |

Anything claiming "95% prediction accuracy" would be describing a different product.

## 1. Live end-to-end run (six real tickers)

Fetched from the internet on the day of the run, then profiled, reported and referee-checked:

| Ticker | Market | Bars (2015-2025) | Structure | Permutation z | Report | Independent referee |
| --- | --- | --- | --- | --- | --- | --- |
| 600519 | cn | 2673 | no clear structure | -1.18 | 2731 chars | PASS |
| 000001 | cn | 2673 | no clear structure | -0.74 | 2729 chars | PASS |
| 601318 | cn | 2673 | no clear structure | -1.24 | 2729 chars | PASS |
| AAPL | us | 2765 | no clear structure | -1.31 | 2677 chars | PASS |
| MSFT | us | 2765 | mean-reverting | -4.45 | 2966 chars | PASS |
| NVDA | us | 2765 | no clear structure | -1.24 | 2678 chars | PASS |

Every report was reconciled against an independent recomputation that does not import project
code (`referee/profile_check.py`): **6 of 6 agreed**, exit code 0.

Note the substantive result: five of six real large caps show **no stable structure**. That is
the expected outcome, not a bug. Markets are close to random most of the time.

## 2. System accuracy (this part really is ~100%)

| Check | Result |
| --- | --- |
| Cached files inspected | 118 |
| Files containing non-positive prices | 0 |
| Files with unsorted or duplicate dates | 0 |
| Same data profiled twice gives identical numbers | yes |
| Reports verified against an independent recomputation | 6 / 6 |

Two stale caches (`cn_000693`, `cn_000760`) did contain negative prices from the earlier
forward-adjusted era. They were deleted, and `tools/profile.py` now **refuses** to profile data
with non-positive prices instead of silently dropping those rows. The data source refuses them too.

## 3. Verdict stability (the honest, much lower number)

Method: for each ticker with at least 750 bars, profile the first 70% of history, then profile
the last 30% independently, and compare the verdicts.

| | Value |
| --- | --- |
| Tickers tested | 109 |
| Same verdict in both halves | 79 (72.5%) |
| **Tickers where the first half said "structure", and the second half agreed** | **2 of 25 (8.0%)** |
| Correlation of the permutation z-score between halves | +0.138 |

Confusion matrix (first half -> second half):

| first half | second half | count |
| --- | --- | --- |
| no clear structure | no clear structure | 77 |
| mean-reverting | no clear structure | 18 |
| trending | no clear structure | 5 |
| no clear structure | trending | 4 |
| no clear structure | mean-reverting | 3 |
| mean-reverting | mean-reverting | 2 |

### What this means

The 72.5% headline is almost entirely the "no structure" class agreeing with itself. Once the
tool claims a *structure*, that claim survives into the next period only **8% of the time**, and
the z-scores of the two halves are nearly uncorrelated (+0.14).

In plain terms: **a single-ticker structural verdict describes that period, not the next one.**
It is a hint about which direction to write a hypothesis card for, not a tradeable signal.

This is exactly why the project's rule is that a direction must pass a card audit on out-of-sample
data before it counts as anything, and why the reports say "no direction" so often.

## 4. What would actually raise the number

Not more indicators. In order of expected value:

1. **Require persistence**: only call structure when z stays beyond the threshold across
   consecutive sub-periods. This will cut the "structure" count hard, and make the survivors
   more meaningful.
2. **Cross-sectional instead of single-name**: rank many tickers at once — far more observations
   per decision, which is what `tools/cross_section.py` does.
3. **Point-in-time universes**: without delisted names, every stability estimate above is
   optimistic by an unknown amount.

## 5. Reproducing this

```bash
python -m tools.eval_live        # fetch six real tickers, profile, report
python -m tools.eval_accuracy    # stability + system checks over the whole cache
```