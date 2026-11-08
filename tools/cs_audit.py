#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""截面审计：邻域 / 多重检验 / 留出段。

修正了两处会让结论失真的方法问题：
    1. IC 与 topN 无关（IC 是在整个横截面上算的），所以「检验次数」只能是 lookback 的个数。
       把它按 lookback × topN 算成 60 次，会把惩罚放大 5 倍，冤枉真信号。
    2. 成分股用并集而不是交集。交集会因为某个标的晚上市而砍掉整段历史。

输出
    · lookback 扫描表（每个 lookback 一次检验）→ 邻域是否成片
    · Bonferroni 校正后的 p（N = lookback 个数）
    · 最优 lookback 下的 topN 扫描（信息性，用于看仓位集中度影响）
    · 留出段一次性检验
"""

import argparse
import sys
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.cross_section import build_observations, evaluate, load_panel  # noqa: E402

LOOKBACKS = list(range(1, 13))
TOPS = [2, 3, 5, 8, 10]


def split_obs(obs, split_date):
    return ([o for o in obs if o["date"] < split_date],
            [o for o in obs if o["date"] >= split_date])


def one_sided_p(t):
    return 1.0 if t is None else 1.0 - NormalDist().cdf(t)


def bonferroni(p, n_tests):
    """试了 n 次之后，「至少出现一次误报」的概率。"""
    n = max(1, int(n_tests))
    return min(1.0, 1.0 - (1.0 - p) ** n)


def main(argv=None):
    ap = argparse.ArgumentParser(description="截面审计")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--csv-dir", default="data_cache")
    ap.add_argument("--cost", type=float, default=0.0008)
    ap.add_argument("--holdout", default="2023-01-01")
    args = ap.parse_args(argv)

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    dates, panel, used = load_panel(syms, args.csv_dir)
    print(f"标的 {len(used)} 只；交易日 {len(dates)} 天（{dates[0]} → {dates[-1]}）\n")

    train_by_lb, hold_by_lb = {}, {}
    for lb in LOOKBACKS:
        obs = build_observations(panel, dates, lookback_months=lb)
        tr, ho = split_obs(obs, args.holdout)
        train_by_lb[lb], hold_by_lb[lb] = tr, ho

    # ---- 第一步：lookback 邻域（每个 lookback 只算一次检验）
    print("=== 第一步：lookback 邻域（训练段）===")
    print(f"{'回看月':>6}{'IC均值':>10}{'t 值':>8}{'IC CI 下界':>12}{'显著':>6}{'期数':>7}")
    print("-" * 52)
    rows = {}
    for lb in LOOKBACKS:
        obs = train_by_lb[lb]
        if len(obs) < 24:
            continue
        r = evaluate(obs, top_n=3, cost=args.cost, boot=300)   # IC 与 topN 无关
        if not r.get("ok"):
            continue
        rows[lb] = r
        lo = r["ic_ci"][0] if r["ic_ci"] else float("nan")
        hi = r["ic_ci"][2] if r["ic_ci"] else float("nan")
        # 显著必须双向报：只标"显著为正"会把反向有效（A股 常见的短期反转）藏起来，
        # 那是信息，不是噪声。
        flag = "正*" if lo > 0 else ("负*" if hi < 0 else "-")
        print(f"{lb:>6}{r['ic_mean']*100:>10.2f}{r['ic_t']:>8.2f}{lo*100:>12.2f}"
              f"{flag:>6}{r['periods']:>7}")

    if not rows:
        print("没有可用回看期")
        return 1
    pos = [lb for lb, r in rows.items() if r["ic_ci"] and r["ic_ci"][0] > 0]
    neg = [lb for lb, r in rows.items() if r["ic_ci"] and r["ic_ci"][2] < 0]
    print(f"\n{len(rows)} 个回看期里：显著为正（动量）{len(pos)} 个，"
          f"显著为负（反转）{len(neg)} 个")
    if neg and not pos:
        print("  ⚠ 方向与假设相反：这批数据更像『短期反转』而不是『动量』。")
        print("    反转要作为一个**新假设**重新预注册再验一次，不能拿这次的结果当结论。")
    elif pos and len(pos) >= 4:
        print("  成片为正，像真信号（仍需留出段确认）")
    else:
        print("  正负都不成片，更像噪声")

    # ---- 第二步：多重检验
    print("\n=== 第二步：多重检验（N = 回看期个数）===")
    best_lb = max(rows, key=lambda k: rows[k]["ic_t"])
    br = rows[best_lb]
    p = one_sided_p(br["ic_t"])
    p_adj = bonferroni(p, len(rows))
    print(f"  最亮：回看 {best_lb} 月，IC={br['ic_mean']*100:+.2f}，t={br['ic_t']:+.2f}")
    print(f"  单次 p={p:.4f} → 试 {len(rows)} 次后 p={p_adj:.4f} → "
          f"{'仍显著' if p_adj < 0.05 else '不显著，大概率是搜索出来的'}")

    # ---- topN 扫描（信息性）
    print(f"\n=== 补充：在回看 {best_lb} 月下扫 topN（训练段）===")
    for top in TOPS:
        r = evaluate(train_by_lb[best_lb], top_n=top, cost=args.cost, boot=200)
        if r.get("ok"):
            print(f"  topN={top:<3} 策略年化 {r['strat_cagr']*100:+7.2f}%   "
                  f"超额 t={r['ex_t']:+.2f}   换手 {r['avg_turnover']*100:.0f}%")

    # ---- 第三步：留出段，只看一次
    print(f"\n=== 第三步：留出段（{args.holdout} 之后）===")
    hold = hold_by_lb[best_lb]
    if len(hold) < 12:
        print(f"  留出段只有 {len(hold)} 期，不足")
        return 1
    ho = evaluate(hold, top_n=3, cost=args.cost, boot=2000)
    lo, mid, hi = ho["ic_ci"] if ho.get("ic_ci") else (float("nan"),) * 3
    print(f"  回看 {best_lb} 月在留出段：IC={ho['ic_mean']*100:+.2f} (t={ho['ic_t']:+.2f}) "
          f"CI [{lo*100:+.2f}, {hi*100:+.2f}]，{len(hold)} 期")
    print(f"  策略年化 {ho['strat_cagr']*100:+.2f}% vs 等权 {ho['bench_cagr']*100:+.2f}%")
    print(f"  ▶ 留出段判定：{ho['verdict']}")

    ok = (p_adj < 0.05) and (lo > 0)
    print("\n" + "=" * 60)
    print("总结论：" + ("通过三重审计 —— 值得继续投入"
                     if ok else "未通过三重审计 —— 不能当成有优势的策略"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())