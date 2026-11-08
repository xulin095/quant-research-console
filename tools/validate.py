#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""walk-forward 验证器 —— 回答「这个策略有没有真优势」，而不是「这一次赚了多少」。

为什么需要它
    v1 报的是单区间点估计。AAPL 2 年 14 笔交易，t 值 0.29 —— 与噪声无法区分。
    要判断优势是否存在，必须做三件事，缺一不可：
      1) walk-forward：参数在训练段选，成绩只在测试段算（测试段只跑一次，不许回看）
      2) deflated Sharpe：把「试了多少组参数」这个多重检验惩罚算进去
      3) block bootstrap：给出样本外夏普的置信区间（下界 > 0 才算有证据）

用法
    python -m tools.validate --symbols AAPL,600519 --csv-dir data_cache
    python -m tools.validate --csv data_cache/us_AAPL_2024-01-01_2025-12-31.csv
    python -m tools.validate --symbols AAPL --train 252 --test 126 --boot 4000 --json out.json

判定口径（写死在代码里，不许现场改）
    CI 下界 > 0        → 有证据（可以继续投入）
    CI 跨越 0          → 无证据（大概率是噪声，换研究问题）
    CI 上界 < 0        → 显著为负（这个策略族在本市场是负优势）
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path
from statistics import NormalDist, mean, stdev

CAPITAL = 100000.0
FEE, SLIP = 0.0003, 0.0005
ANN = 252
MIN_ROWS = 60

DEFAULT_GRID = [(f, s) for f in (3, 5, 7, 10) for s in (10, 20, 30, 40, 60) if f < s]
# 注意：必须过滤 f >= s。(10,10) 这类组合回测为空，若被记成"夏普 0"，
# 在所有有效参数都亏钱时它会以 0 分胜出 —— 系统就选了个根本不交易的策略。
# 这个坑是真跑数据时暴露的（2024–2025 的 600519 全部参数为负）。


# ------------------------------------------------------------------ 读数据
def read_csv(path):
    """读标准表，只取 date/open/close。缺列直接报错，不猜。"""
    import csv as _csv
    rows = []
    with open(path, "r", encoding="utf-8-sig") as fh:
        rd = _csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (rd.fieldnames or [])}
        for need in ("date", "open", "close"):
            if need not in cols:
                raise ValueError(f"{path} 缺列 {need}（表头：{list(cols)}）")
        for r in rd:
            rows.append({
                "date": r[cols["date"]][:10],
                "open": float(r[cols["open"]]),
                "close": float(r[cols["close"]]),
            })
    if len(rows) < MIN_ROWS:
        raise ValueError(f"{path} 只有 {len(rows)} 行，少于 {MIN_ROWS}")
    return rows


def find_cached(csv_dir, symbol):
    """按 v1 的命名规约找缓存：data_cache/{market}_{symbol}_{start}_{end}.csv

    同一标的可能有多个区间缓存（短区间 + 长历史）。取**行数最多**的那份：
    原来按字母序取第一个，结果好坏取决于文件名，属于隐性陷阱。
    """
    d = Path(csv_dir)
    hits = sorted(p for p in d.glob(f"*_{symbol}_*.csv"))
    if not hits:
        return None
    best, best_rows = None, -1
    for p in hits:
        try:
            n = sum(1 for _ in p.open(encoding="utf-8-sig", errors="replace"))
        except OSError:
            continue
        if n > best_rows:
            best, best_rows = p, n
    return best


# ------------------------------------------------------------------ 回测内核
def _sma(vals, w):
    out, run = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= w:
            run -= vals[i - w]
        if i >= w - 1:
            out[i] = run / w
    return out


def simulate(rows, fast, slow):
    """按 v1 口径回测：信号次日开盘成交、全仓、双边扣费。返回逐日权益收益率列表。

    与项目 backtest.py 规则一致（tests/test_validate.py 里有对账测试锁住这一点）。
    """
    if fast >= slow:
        return []
    closes = [r["close"] for r in rows]
    ma_f, ma_s = _sma(closes, fast), _sma(closes, slow)

    cash, shares, pending = CAPITAL, 0.0, None
    equity = []
    for i, r in enumerate(rows):
        if pending == "buy":
            px = r["open"]
            shares = math.floor(cash / (px * (1 + FEE + SLIP)) * 1e6) / 1e6
            cash -= shares * px * (1 + FEE + SLIP)
            pending = None
        elif pending == "sell":
            cash += shares * r["open"] * (1 - FEE - SLIP)
            shares, pending = 0.0, None

        equity.append(cash + shares * r["close"])

        if i == 0 or ma_f[i] is None or ma_s[i] is None or ma_f[i - 1] is None or ma_s[i - 1] is None:
            continue
        up_now, up_prev = ma_f[i] > ma_s[i], ma_f[i - 1] > ma_s[i - 1]
        if up_now and not up_prev and shares == 0.0 and pending is None:
            pending = "buy"
        elif (not up_now) and up_prev and shares > 0.0 and pending is None:
            pending = "sell"

    return [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]


# ------------------------------------------------------------------ 统计
def bh_returns(rows):
    """买入持有同期日收益 —— 只做多策略的正确参照物。

    没有它，牛市里任何「始终在场」的策略都会显得有优势；
    真正要问的是「信号比躺着不动多赚了吗」，所以要拿超额序列做检验。
    """
    c = [r["close"] for r in rows]
    return [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] > 0]


def sharpe(daily, rf_annual=0.0):
    if len(daily) < 2:
        return 0.0
    ex = [r - rf_annual / ANN for r in daily]
    m, sd = mean(ex), stdev(ex)
    return 0.0 if sd < 1e-12 else m / sd * math.sqrt(ANN)


def block_bootstrap_ci(daily, block=20, n_boot=2000, seed=7, alpha=0.05):
    """块重采样（保留自相关），返回样本外夏普的 (下界, 中位, 上界)。"""
    n = len(daily)
    if n < block * 2 or n < 30:
        return None
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        sample = []
        while len(sample) < n:
            start = rng.randrange(0, n - block + 1)
            sample.extend(daily[start:start + block])
        boots.append(sharpe(sample[:n]))
    boots.sort()
    lo = boots[int(alpha / 2 * len(boots))]
    hi = boots[int((1 - alpha / 2) * len(boots)) - 1]
    return lo, boots[len(boots) // 2], hi


def _skew_kurt(x):
    n = len(x)
    m = mean(x)
    m2 = sum((v - m) ** 2 for v in x) / n
    if m2 <= 0:
        return 0.0, 3.0
    m3 = sum((v - m) ** 3 for v in x) / n
    m4 = sum((v - m) ** 4 for v in x) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def deflated_sharpe(observed_sr, trial_srs, daily):
    """Bailey & López de Prado 的 Deflated Sharpe Ratio。

    输入 trial_srs = 所有被试参数的夏普（训练段），用来估计「纯靠运气能拿到的最好夏普」。
    返回 0~1 的概率：观察到的夏普在扣掉多重检验与偏度/峰度后仍然优于运气。
    """
    n = len(daily)
    if n < 30 or len(trial_srs) < 2:
        return None
    gamma = 0.5772156649015329
    N = len(trial_srs)
    var_sr = stdev(trial_srs) ** 2
    nd = NormalDist()
    sr0 = math.sqrt(var_sr) * ((1 - gamma) * nd.inv_cdf(1 - 1.0 / N)
                               + gamma * nd.inv_cdf(1 - 1.0 / (N * math.e)))
    sk, ku = _skew_kurt(daily)
    denom = 1 - sk * observed_sr + (ku - 1) / 4 * observed_sr ** 2
    if denom <= 0:
        return None
    z = (observed_sr - sr0) * math.sqrt(n - 1) / math.sqrt(denom)
    return nd.cdf(z), sr0


# ------------------------------------------------------------------ 主流程
def walk_forward(rows, grid=DEFAULT_GRID, train=252, test=126, step=None,
                 boot=2000, block=20, seed=7):
    """滚动切窗：训练段选参数，测试段只算成绩。返回 OOS 汇总。"""
    step = step or test
    oos, oos_bh, picks, trial_srs = [], [], [], []
    n = len(rows)
    start = 0
    while start + train + test <= n:
        tr = rows[start:start + train]
        warm = max(s for _, s in grid) + 5
        te_start = start + train
        te = rows[max(0, te_start - warm):te_start + test]
        drop = len(te) - test

        tr_bh = bh_returns(tr)
        best, best_sr = None, None
        for fast, slow in grid:
            if fast >= slow:                     # 无效组合：不许参与比大小
                continue
            if slow + 5 >= len(tr):
                continue
            rets_train = simulate(tr, fast, slow)
            if len(rets_train) < 30:             # 回测为空/太短：不许记成分数
                continue
            # 关键：按「相对买入持有的超额」选参数，而不是按绝对收益。
            # 否则牛市里选出来的就是「一直满仓」的那组参数。
            n_min = min(len(rets_train), len(tr_bh))
            excess = [a - b for a, b in zip(rets_train[-n_min:], tr_bh[-n_min:])]
            sr = sharpe(excess)
            trial_srs.append(sr)
            if best_sr is None or sr > best_sr:
                best, best_sr = (fast, slow), sr

        if best is None:
            start += step
            continue

        rets = simulate(te, *best)[drop:]
        if len(rets) >= test * 0.8:
            te_bh = bh_returns(te)[drop - 1:] if drop >= 1 else bh_returns(te)
            n_min = min(len(rets), len(te_bh))
            oos.extend(rets[-n_min:])
            oos_bh.extend(te_bh[-n_min:])
            picks.append({"start": rows[te_start]["date"], "params": list(best),
                          "train_excess_sharpe": round(best_sr, 3)})
        start += step

    if len(oos) < 60:
        return {"ok": False, "reason": f"样本外可用收益只有 {len(oos)} 天，不足以判断"}

    n = min(len(oos), len(oos_bh))
    oos, oos_bh = oos[-n:], oos_bh[-n:]
    excess = [a - b for a, b in zip(oos, oos_bh)]

    sr = sharpe(oos)
    sr_bh = sharpe(oos_bh)
    sr_ex = sharpe(excess)
    ci = block_bootstrap_ci(excess, block=block, n_boot=boot, seed=seed)
    dsr = deflated_sharpe(sr_ex, trial_srs, excess)

    cum, cum_bh, cum_ex = 1.0, 1.0, 1.0
    for r in oos:
        cum *= (1 + r)
    for r in oos_bh:
        cum_bh *= (1 + r)
    for r in excess:
        cum_ex *= (1 + r)

    # 判定只看「超额」：策略绝对赚钱不算本事，牛市里躺着不动也赚。
    if ci is None:
        verdict = "无法判断（样本外天数不足）"
    elif ci[0] > 0:
        verdict = "有证据（超额 CI 下界 > 0）"
    elif ci[2] < 0:
        verdict = "显著跑输基准（超额 CI 上界 < 0）"
    else:
        verdict = "无证据（超额 CI 跨越 0，大概率是噪声）"

    return {
        "ok": True, "windows": len(picks), "picks": picks,
        "oos_days": n,
        "oos_total_return": cum - 1, "oos_bh_return": cum_bh - 1,
        "oos_excess_cum": cum_ex - 1, "oos_days_excess_mean": sum(excess) / n,
        "oos_sharpe": sr, "oos_bh_sharpe": sr_bh, "excess_sharpe": sr_ex, "ci": ci,
        "deflated_sharpe": dsr[0] if dsr else None,
        "sr0_expected_max": dsr[1] if dsr else None,
        "trials": len(trial_srs), "verdict": verdict,
    }


def fmt_pct(x):
    return "—" if x is None else f"{x * 100:+.2f}%"


def report_one(name, res):
    print(f"\n=== {name} ===")
    if not res.get("ok"):
        print(f"  {res['reason']}")
        return
    print(f"  滚动窗口 {res['windows']} 个，样本外 {res['oos_days']} 天")
    print(f"  策略 {fmt_pct(res['oos_total_return'])}（夏普 {res['oos_sharpe']:+.3f}）"
          f"   vs 买入持有 {fmt_pct(res['oos_bh_return'])}（夏普 {res['oos_bh_sharpe']:+.3f}）")
    print(f"  超额累计 {fmt_pct(res['oos_excess_cum'])}，超额夏普 {res['excess_sharpe']:+.3f}")
    lo, mid, hi = res["ci"]
    print(f"  超额夏普 95% CI  [{lo:+.3f}, {hi:+.3f}]（中位 {mid:+.3f}）")
    if res["deflated_sharpe"] is not None:
        print(f"  Deflated Sharpe {res['deflated_sharpe']:.3f}  "
              f"（运气门槛 SR0={res['sr0_expected_max']:+.3f}，试了 {res['trials']} 组）")
    print(f"  参数选择：" +
          ", ".join(f"{p['start']}:{p['params'][0]}/{p['params'][1]}" for p in res["picks"][:6]) +
          ("…" if len(res["picks"]) > 6 else ""))
    print(f"  ▶ 判定：{res['verdict']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="walk-forward 策略验证器")
    ap.add_argument("--symbols", default=None, help="逗号分隔，如 AAPL,600519")
    ap.add_argument("--csv", default=None, help="直接指定一个标准表 CSV")
    ap.add_argument("--csv-dir", default="data_cache")
    ap.add_argument("--train", type=int, default=252)
    ap.add_argument("--test", type=int, default=126)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--block", type=int, default=20)
    ap.add_argument("--json", default=None, help="把结果写到 JSON")
    args = ap.parse_args(argv)

    targets = []
    if args.csv:
        targets.append(("CSV", Path(args.csv)))
    if args.symbols:
        for sym in args.symbols.split(","):
            sym = sym.strip().upper()
            if not sym:
                continue
            p = find_cached(args.csv_dir, sym)
            targets.append((sym, p) if p else (sym, None))
    if not targets:
        ap.error("要么给 --symbols，要么给 --csv")

    results, evidence = {}, 0
    for name, path in targets:
        if path is None:
            print(f"\n=== {name} ===\n  缓存里找不到，跳过（先跑 main.py 拉一次数据）")
            continue
        try:
            rows = read_csv(path)
        except (OSError, ValueError) as e:
            print(f"\n=== {name} ===\n  读不了：{e}")
            continue
        res = walk_forward(rows, train=args.train, test=args.test,
                           boot=args.boot, block=args.block)
        res["csv"] = str(path)
        results[name] = res
        report_one(name, res)
        if res.get("ok") and res["ci"] and res["ci"][0] > 0:
            evidence += 1

    ok = [r for r in results.values() if r.get("ok")]
    print("\n" + "=" * 60)
    print(f"共验证 {len(ok)} 个标的，其中「样本外 CI 下界 > 0」的有 {evidence} 个")
    if ok:
        print("判据：0–2 个 → 策略族无效，换研究问题；3–6 → 有苗头；≥7 → 可考虑前端")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
