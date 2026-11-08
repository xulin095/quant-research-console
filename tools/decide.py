#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""决策层验证器 —— 「按这套 10 行规则下注，十年下来会发生什么」。

定位
    它不是一个会出建议的 agent。它是**一张写死的规则表 + 一次历史回放**。
    A 端（估计器）给出「边际优势的估计」，B 端（本文件）只做一件事：
    按预先写死的阈值决定仓位 —— 0% / 2% / 5%，别的什么都不做。

    之所以把 B 写成代码而不是写成 agent：任何语言模型都能把「概率 55%」
    解释成「建议关注」，而规则表不能。B 的价值在于**它没有发挥空间**。

关键防骗设计
    1. 所有估计只用 t 日之前的信息（weight[t] 由 t-1 及更早的收益算出），绝不看未来
    2. 交易成本真实扣除：策略自身的买卖成本 + 决策层调仓成本
    3. 输出里必须同时给出「100% 买入持有」和「100% 一直做策略」两条基准线
       —— 决策层如果不能同时打赢这两条，它就没有存在价值
    4. 失效事件单独统计：单日亏损超过 5% 的次数、最惨单日、最大回撤

用法
    python -m tools.decide --symbols AAPL,MSFT,NVDA --csv-dir data_cache
    python -m tools.decide --csv data_cache/us_AAPL_2010-01-01_2025-12-31.csv
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate import bh_returns, find_cached, read_csv, sharpe, _sma  # noqa: E402

CAPITAL = 100000.0
STRAT_FEE, STRAT_SLIP = 0.0003, 0.0005   # 策略自身每笔成本
REBAL_FEE = 0.0002                       # 决策层调仓成本（按变动仓位计）

WINDOW = 252          # 用过去一年估计边际优势
MIN_HISTORY = 252     # 不足一年 → 不表态（仓位 0）
ANN = 252

# ---------------------------------------------------------------- 规则表
# 这是整个「B 端」的全部智慧。想改？可以，但必须 git commit 之后再跑。
RULES = [
    # (最少胜率, 最少 t 值, 目标仓位)
    (0.60, 1.00, 0.05),
    (0.55, 0.00, 0.02),
]
DEFAULT_WEIGHT = 0.0
MAX_WEIGHT = 0.05


def target_weight(hit_rate, t_stat):
    """规则表本体：输入过去一年的两个统计量，输出目标仓位。无状态、无随机、无模型。"""
    if hit_rate is None or t_stat is None:
        return 0.0                      # 数据不足 → 不表态
    weight = DEFAULT_WEIGHT
    for min_hit, min_t, w in RULES:
        if hit_rate >= min_hit and t_stat >= min_t:
            weight = max(weight, w)
    return min(weight, MAX_WEIGHT)


# ---------------------------------------------------------------- 策略层
def strategy_returns(rows, fast=5, slow=20):
    """策略自身：均线之上持仓、之下空仓。返回 (收益序列, 换手标记序列)。

    用收盘价做撮合（比"次日开盘"略乐观，但两边成本都扣了）。
    """
    closes = [r["close"] for r in rows]
    ma_f, ma_s = _sma(closes, fast), _sma(closes, slow)
    rets, flips = [], []
    pos = 0
    for i in range(1, len(closes)):
        held = pos
        r = closes[i] / closes[i - 1] - 1
        rets.append(held * r)
        ready = ma_f[i] is not None and ma_s[i] is not None
        new_pos = 1 if (ready and ma_f[i] > ma_s[i]) else 0
        flips.append(new_pos != pos)
        if new_pos != pos:
            rets[-1] -= (STRAT_FEE + STRAT_SLIP)   # 换手成本
        pos = new_pos
    return rets, flips


def rolling_edge(rets, window=WINDOW, min_history=MIN_HISTORY):
    """滚动估计「胜率」与「t 值」，只用 t 之前的样本，返回与 rets 对齐的列表。"""
    out = []
    for t in range(len(rets)):
        hist = rets[max(0, t - window):t]        # 严格不含 t
        if len(hist) < min_history:
            out.append((None, None))
            continue
        # 胜率只在「真的有仓位」的交易日上算。
        # 空仓日收益恒为 0，如果算进分母，胜率会被系统性地压到 0.5 以下，
        # 于是规则表永远不建仓 —— 这个坑是写测试时发现的。
        nz = [x for x in hist if abs(x) > 1e-12]
        if len(nz) < 60:
            out.append((None, None))
            continue
        wins = sum(1 for x in nz if x > 0)
        hit = (wins + 1) / (len(nz) + 2)      # Laplace 平滑，避免 0%/100%
        m = sum(hist) / len(hist)
        sd = math.sqrt(sum((x - m) ** 2 for x in hist) / (len(hist) - 1)) if len(hist) > 1 else 0.0
        t_stat = m / sd * math.sqrt(len(hist)) if sd > 1e-12 else 0.0
        out.append((hit, t_stat))
    return out


# ---------------------------------------------------------------- 回放
def run(rows, fast=5, slow=20, window=WINDOW):
    """决策层回放。返回三条曲线（决策层 / 100%策略 / 100%买入持有）。"""
    closes = [r["close"] for r in rows]
    srets, _ = strategy_returns(rows, fast, slow)
    brets = bh_returns(rows)

    n = min(len(srets), len(brets))
    srets, brets = srets[-n:], brets[-n:]

    edge = rolling_edge(srets, window=window)
    weights = [target_weight(edge[t][0], edge[t][1]) for t in range(n)]

    eq_dec, eq_str, eq_bh = CAPITAL, CAPITAL, CAPITAL
    curves = {"dec": [], "strat": [], "bh": []}
    daily_dec = []
    prev_w = 0.0
    for t in range(n):
        rebal = abs(weights[t] - prev_w) * REBAL_FEE
        r_dec = weights[t] * srets[t] - rebal
        daily_dec.append(r_dec)
        eq_dec *= (1 + r_dec)
        eq_str *= (1 + srets[t])
        eq_bh *= (1 + brets[t])
        curves["dec"].append(eq_dec)
        curves["strat"].append(eq_str)
        curves["bh"].append(eq_bh)
        prev_w = weights[t]

    def stats(curve, daily):
        final = curve[-1]
        years = len(curve) / ANN
        cagr = (final / CAPITAL) ** (1 / years) - 1 if years > 0 and final > 0 else None
        peak, mdd = curve[0], 0.0
        for x in curve:
            peak = max(peak, x)
            mdd = max(mdd, 1 - x / peak)
        return {"final": final, "cagr": cagr, "mdd": mdd,
                "sharpe": sharpe(daily), "worst_day": min(daily) if daily else 0.0,
                "blowups": sum(1 for x in daily if x < -0.05)}

    invested = sum(1 for w in weights if w > 0) / n if n else 0.0
    return {
        "days": n, "invested_ratio": invested,
        "avg_weight": sum(weights) / n if n else 0.0,
        "weights": weights,
        "dec": stats(curves["dec"], daily_dec),
        "strat": stats(curves["strat"], srets),
        "bh": stats(curves["bh"], brets),
    }


# ---------------------------------------------------------------- 输出
def pct(x):
    return "—" if x is None else f"{x * 100:+.2f}%"


def report_one(name, res):
    print(f"\n=== {name}（{res['days']} 天，平均仓位 {res['avg_weight']*100:.1f}%，"
          f"有仓天数占比 {res['invested_ratio']*100:.0f}%）===")
    print(f"  {'':<14}{'最终权益':>12}{'年化':>10}{'最大回撤':>10}{'夏普':>8}{'最惨单日':>10}{'爆仓日':>7}")
    for label, key in (("决策层", "dec"), ("100%策略", "strat"), ("100%持有", "bh")):
        s = res[key]
        print(f"  {label:<12}{s['final']:>13,.0f}{pct(s['cagr']):>10}"
              f"{pct(-s['mdd']):>10}{s['sharpe']:>8.2f}{pct(s['worst_day']):>10}{s['blowups']:>7}")
    # 判定要公平：决策层只用了很小的仓位，拿它的绝对权益去跟满仓基准比是耍流氓。
    # 所以先看「它到底愿不愿意下注」，再看风险调整后的效率（年化 / 最大回撤）。
    d = res["dec"]
    if res["invested_ratio"] < 0.05:
        print("  ▶ 判定：几乎不下注（估计器常年看不出一致优势）—— "
              "这是规则表的正确行为，但也说明本标的没有可下注的东西")
        return

    def eff(s):
        return (s["cagr"] / s["mdd"]) if s["mdd"] > 1e-9 and s["cagr"] is not None else 0.0

    beats = []
    if eff(d) > eff(res["bh"]):
        beats.append("买入持有")
    if eff(d) > eff(res["strat"]):
        beats.append("100% 执行策略")
    if len(beats) == 2:
        print("  ▶ 判定：风险调整后优于两条基准（唯一值得继续看的情形）")
    else:
        lose = [x for x in ("买入持有", "100% 执行策略") if x not in beats]
        print("  ▶ 判定：风险调整后仍跑输 " + "、".join(lose) +
              "（效率 决策层 %.2f vs 持有 %.2f）" % (eff(d), eff(res["bh"])))


def main(argv=None):
    ap = argparse.ArgumentParser(description="决策规则表的历史回放")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--csv-dir", default="data_cache")
    args = ap.parse_args(argv)

    targets = []
    if args.csv:
        targets.append(("CSV", Path(args.csv)))
    for sym in (args.symbols or "").split(","):
        sym = sym.strip().upper()
        if sym:
            p = find_cached(args.csv_dir, sym)
            targets.append((sym, p))
    if not targets:
        ap.error("给 --symbols 或 --csv")

    better_than_both = 0
    total = 0
    for name, path in targets:
        if path is None:
            print(f"\n=== {name} ===\n  没有缓存，跳过")
            continue
        try:
            rows = read_csv(path)
        except (OSError, ValueError) as e:
            print(f"\n=== {name} ===\n  读不了：{e}")
            continue
        res = run(rows)
        total += 1
        if res["dec"]["final"] >= max(res["bh"]["final"], res["strat"]["final"]):
            better_than_both += 1
        report_one(name, res)

    print("\n" + "=" * 62)
    print(f"共回放 {total} 个标的；决策层同时打赢「买入持有」和「100%策略」的有 {better_than_both} 个")
    print("判据：如果接近 0，问题不在『缺一个出建议的 agent』，而在『没有可下注的优势』。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
