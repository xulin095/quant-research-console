#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""单标的结构画像 —— 描述统计，不是预测，也不是建议。

它回答一个问题
    「这只票的历史数据，更像趋势型还是均值回归型？」
    这个答案决定你该往哪个方向**提假设**（不是决定买卖）。

为什么用这几个指标
    自相关（lag1）：昨天的涨跌对今天还有没有影响。正值＝延续，负值＝回吐。
    方差比 VR(q)  ：q 日收益的方差 / (q × 日收益方差)。
                    VR > 1 说明波动随时间放大（趋势），VR < 1 说明波动被吃掉（回归）。
    这两个都很糙，但方向明确、不易误读。相比一上来就跑回测，
    先看结构的好处是：**在看结果之前，你就知道该期待什么**。

它绝不做的事
    · 不预测价格
    · 不给买卖建议
    · 不保证「结构会持续」——样本换一段，结论可能完全不同

用法
    python -m tools.profile --symbol AAPL
    python -m tools.profile --csv data_cache/cn_600519_2010-01-01_2025-12-31.csv
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate import find_cached, read_csv  # noqa: E402

MIN_ROWS = 120


def _mean(x):
    return sum(x) / len(x)


def _var(x, ddof=1):
    m = _mean(x)
    return sum((v - m) ** 2 for v in x) / max(1, len(x) - ddof)


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 10:
        return None
    a, b = a[:n], b[:n]
    ma, mb = _mean(a), _mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da < 1e-12 or db < 1e-12:
        return None
    return num / (da * db)


def autocorr(rets, lag=1):
    """lag 期自相关：昨天对今天还有没有影响。"""
    if len(rets) <= lag + 10:
        return None
    return _pearson(rets[lag:], rets[:-lag])


def variance_ratio(rets, q=5):
    """方差比 VR(q)。>1 趋势型，<1 均值回归型。"""
    if len(rets) < q * 10:
        return None
    var1 = _var(rets)
    if var1 <= 1e-18:
        return None
    agg = [sum(rets[i:i + q]) for i in range(len(rets) - q + 1)]
    varq = _var(agg)
    return varq / (q * var1)


def profile(rows):
    """输入标准表行，返回描述统计 + 一句「往哪个方向提假设」的提示。"""
    if len(rows) < MIN_ROWS:
        return {"ok": False, "reason": f"只有 {len(rows)} 行，至少需要 {MIN_ROWS} 行"}

    closes = [r["close"] for r in rows]
    # 脏数据防护：价格为 0 或负时不能算收益率（会除零），负价还会让年化收益变成复数。
    bad_prices = sum(1 for c in closes if c <= 0)
    rets = [closes[i] / closes[i - 1] - 1
            for i in range(1, len(closes))
            if closes[i - 1] > 0 and closes[i] > 0]
    if len(rets) < MIN_ROWS - 1:
        return {"ok": False,
                "reason": f"可用收益只有 {len(rets)} 个（原始 {len(closes)} 行，"
                          f"其中 {bad_prices} 个价格非正），不足以画像"}
    n = len(rets)
    years = n / 252

    mu = _mean(rets)
    sd = math.sqrt(_var(rets))
    ann_vol = sd * math.sqrt(252)
    # 年化收益必须防两种病：
    #   · 首价为 0 → 除零
    #   · 首末价比值为负（脏数据里出现过负价）→ 负数取分数次幂会返回 complex，
    #     一路传到 JSON 序列化直接崩（这是批量画像时炸出来的）
    if years > 0 and closes[0] > 0 and closes[-1] > 0:
        ann_ret = (closes[-1] / closes[0]) ** (1 / years) - 1
    else:
        ann_ret = None

    # 回撤（买入持有）。只在正价格上取峰值 —— 峰值为 0 时除法会炸。
    peak, mdd, mdd_days, cur = None, 0.0, 0, 0
    for c in closes:
        if c <= 0:
            continue
        if peak is None or c >= peak:
            peak, cur = c, 0
        else:
            cur += 1
            mdd_days = max(mdd_days, cur)
            mdd = max(mdd, 1 - c / peak)
    mdd = mdd if peak is not None else None

    ac1 = autocorr(rets, 1)
    ac1 = ac1 if ac1 is None else round(ac1, 4)
    ac5 = autocorr(rets, 5)
    ac5 = ac5 if ac5 is None else round(ac5, 4)
    vr5 = variance_ratio(rets, 5)
    vr20 = variance_ratio(rets, 20)
    vr5 = vr5 if vr5 is None else round(vr5, 3)
    vr20 = vr20 if vr20 is None else round(vr20, 3)

    big = sum(1 for r in rets if abs(r) > 2 * sd) / n if sd > 0 else 0.0
    worst = min(rets) if rets else 0.0

    # ---- 结构判定：只看方向，不给建议
    trend_score, revert_score, why = 0, 0, []
    if ac1 is not None:
        if ac1 > 0.03:
            trend_score += 1
            why.append(f"lag1 自相关 +{ac1:.3f}（涨跌有延续）")
        elif ac1 < -0.03:
            revert_score += 1
            why.append(f"lag1 自相关 {ac1:.3f}（涨跌有回吐）")
        else:
            why.append(f"lag1 自相关 {ac1:+.3f}（近乎无记忆）")
    for label, vr in (("VR5", vr5), ("VR20", vr20)):
        if vr is None:
            continue
        if vr > 1.10:
            trend_score += 1
            why.append(f"{label} {vr:.2f}（趋势放大）")
        elif vr < 0.90:
            revert_score += 1
            why.append(f"{label} {vr:.2f}（波动被吃掉）")

    if trend_score >= 2 and trend_score > revert_score:
        struct = "趋势型"
        hint = "历史上更像趋势延续。可考虑「时序趋势」或「截面动量」方向的假设。"
        allowed_dirs = ["momentum"]
    elif revert_score >= 2 and revert_score > trend_score:
        struct = "均值回归型"
        hint = "历史上更像涨跌回吐。可考虑「截面反转」或「短期反转」方向的假设。"
        allowed_dirs = ["reversal"]
    else:
        struct = "无明显结构"
        hint = "两种方向都不占优 —— 与其硬套，不如换一只票或换一类信号再想。"
        allowed_dirs = []

    def clean(x, nd=6):
        """把 nan / inf / complex 统统变成 None —— 它们没法进 JSON，也没法解释。"""
        if x is None:
            return None
        if isinstance(x, complex):
            return None
        try:
            f = float(x)
        except (TypeError, ValueError):
            return None
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return round(f, nd)

    ann_ret = clean(ann_ret)
    ann_vol = clean(ann_vol)
    mdd = clean(mdd)
    worst = clean(worst)
    mu = clean(mu, 8)
    sd = clean(sd, 8)
    big = clean(big)
    return {
        "ok": True,
        "rows": len(rows), "ret_days": n, "years": round(years, 2),
        "first": rows[0]["date"], "last": rows[-1]["date"],
        "annual_return": ann_ret, "annual_vol": ann_vol,
        "mean_daily": mu, "sd_daily": sd,
        "max_drawdown": mdd, "max_dd_days": mdd_days,
        "worst_day": worst, "tail_ratio": big,
        "autocorr1": ac1, "autocorr5": ac5, "vr5": vr5, "vr20": vr20,
        "bad_prices": bad_prices,
        "structure": struct, "hint": hint, "allowed_directions": allowed_dirs,
        "evidence": why,
        "caveat": (f"这是 {rows[0]['date']} 至 {rows[-1]['date']} 共 {len(rows)} 个交易日的"
                   f"**历史描述**，不是预测。换一段样本结论可能完全不同；"
                   f"任何方向都必须先过 HK 卡的审计才能当依据。"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="单标的结构画像（描述统计）")
    ap.add_argument("--symbol")
    ap.add_argument("--csv")
    ap.add_argument("--csv-dir", default="data_cache")
    args = ap.parse_args(argv)

    path = args.csv
    if not path:
        if not args.symbol:
            ap.error("给 --symbol 或 --csv")
        p = find_cached(args.csv_dir, args.symbol.upper())
        if p is None:
            print(f"缓存里找不到 {args.symbol}")
            return 1
        path = str(p)
    rows = read_csv(path)
    r = profile(rows)
    if not r["ok"]:
        print(r["reason"])
        return 1

    print(f"\n=== {Path(path).name} ===")
    print(f"  样本 {r['rows']} 行 / {r['years']} 年（{r['first']} → {r['last']}）")
    print(f"  年化收益 {r['annual_return']*100:+.2f}%   年化波动 {r['annual_vol']*100:.2f}%"
          f"   最大回撤 {r['max_drawdown']*100:.2f}%（{r['max_dd_days']} 天）")
    print(f"  最惨单日 {r['worst_day']*100:+.2f}%   极端日占比 {r['tail_ratio']*100:.1f}%")
    print(f"\n  自相关 lag1 {r['autocorr1']}  lag5 {r['autocorr5']}"
          f"   VR5 {r['vr5']}  VR20 {r['vr20']}")
    print(f"\n  ▶ 结构判定：{r['structure']}")
    for w in r["evidence"]:
        print(f"     · {w}")
    print(f"  ▶ 提示：{r['hint']}")
    if r["allowed_directions"]:
        print(f"     可试方向：{'、'.join(r['allowed_directions'])}")
    print(f"\n  ⚠ {r['caveat']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
