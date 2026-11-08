#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""截面检验器 —— 回答「这一堆票里，哪几只比哪几只强」以及「这个排序有预测力吗」。

为什么换问法
    时序问的是「这只票现在该不该在场」：单标的、样本量少、容易撞天花板。
    截面问的是「同一天里，A 比 B 强吗」：20 只票 × 120 个月 = 2400 个观测，
    样本量天然大一个数量级，而且始终有仓位，不吃「空仓机会成本」的亏。

它算三件事
    1. rank IC：每期把「信号排名」和「下一期收益排名」做相关。
       IC 就是「这个排序对未来收益有没有预测力」的直接度量。
    2. IC 的置信区间：块重采样，下界 > 0 才算有预测力。
    3. 按排序真的去交易：做多前 N 名、每月调仓、扣换手成本，跟等权基准比。

判定口径（写死）
    IC 95% CI 下界 > 0  → 排序有预测力（值得继续投入）
    CI 跨越 0            → 无证据
    CI 上界 < 0          → 反向有效（说明该反向做，或者信噪号定义反了）

用法
    python -m tools.cross_section --symbols AAPL,MSFT,NVDA,... --csv-dir data_cache
    python -m tools.cross_section --symbols ... --lookback 6 --top 3 --cost 0.0008
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.validate import find_cached, read_csv  # noqa: E402

DEFAULT_COST = 0.0008     # 单边成本（手续费 + 滑点）
MIN_SYMBOLS = 5


# ------------------------------------------------------------------ 数据
def load_panel(symbols, csv_dir):
    """读多只票，取日期交集，返回 (dates, panel)。panel[date] = {sym: close}"""
    series = {}
    for sym in symbols:
        p = find_cached(csv_dir, sym)
        if p is None:
            print(f"  [跳过] {sym} 没有缓存")
            continue
        try:
            rows = read_csv(p)
        except (OSError, ValueError) as e:
            print(f"  [跳过] {sym} 读不了：{e}")
            continue
        series[sym] = {r["date"]: r["close"] for r in rows}

    if len(series) < MIN_SYMBOLS:
        raise SystemExit(f"只有 {len(series)} 只票有数据，截面至少需要 {MIN_SYMBOLS} 只")

    # 用「并集」而不是「交集」：交集会因为某个标的晚上市（如 KHC 2015 年分拆）
    # 把整段历史砍掉。并集允许成分股随时间变化，这才是接近 point-in-time 的做法。
    all_dates = set()
    for v in series.values():
        all_dates.update(v)
    dates = sorted(all_dates)
    panel = {d: {s: v[d] for s, v in series.items() if d in v} for d in dates}
    if len(dates) < 300:
        raise SystemExit(f"可用交易日只有 {len(dates)} 天，不足以做截面检验")
    # 至少要有 MIN_SYMBOLS 只票同时有价格的日子才算数
    dates = [d for d in dates if len(panel[d]) >= MIN_SYMBOLS]
    return dates, panel, list(series)


def month_ends(dates):
    """每个自然月的最后一个交易日。"""
    out = []
    for i in range(len(dates) - 1):
        if dates[i][:7] != dates[i + 1][:7]:
            out.append(dates[i])
    if dates:
        out.append(dates[-1])
    return out


# ------------------------------------------------------------------ 统计
def ranks(xs):
    """平均秩（处理并列）。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(a, b):
    if len(a) != len(b) or len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da < 1e-12 or db < 1e-12:
        return None
    return num / (da * db)


def mean_t(xs):
    n = len(xs)
    if n < 2:
        return None, None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    if sd < 1e-12:
        return m, 0.0
    return m, m / sd * math.sqrt(n)


def bootstrap_ci(xs, n_boot=2000, seed=17, alpha=0.05):
    """简单重采样（月频、近似独立），返回均值区间。"""
    if len(xs) < 12:
        return None
    import random
    rng = random.Random(seed)
    out = []
    n = len(xs)
    for _ in range(n_boot):
        s = [xs[rng.randrange(n)] for _ in range(n)]
        out.append(sum(s) / n)
    out.sort()
    return out[int(alpha / 2 * len(out))], out[len(out) // 2], out[int((1 - alpha / 2) * len(out)) - 1]


# ------------------------------------------------------------------ 主流程
def build_observations(panel, dates, lookback_months=6):
    """每期生成：{date: {sym: signal}, date: {sym: forward_return}}，严格不看未来。"""
    me = month_ends(dates)
    pos = {d: i for i, d in enumerate(me)}
    obs = []
    for idx, d in enumerate(me):
        if idx - lookback_months < 0 or idx + 1 >= len(me):
            continue
        past = me[idx - lookback_months]
        fwd = me[idx + 1]
        sig, fwd_r = {}, {}
        for sym in panel[d]:
            p0, p1, p2 = panel[past].get(sym), panel[d].get(sym), panel[fwd].get(sym)
            if not p0 or not p1 or not p2:
                continue
            sig[sym] = p1 / p0 - 1
            fwd_r[sym] = p2 / p1 - 1
        syms = sorted(set(sig) & set(fwd_r))
        if len(syms) >= MIN_SYMBOLS:
            obs.append({"date": d, "syms": syms,
                        "sig": [sig[s] for s in syms],
                        "fwd": [fwd_r[s] for s in syms]})
    return obs


def evaluate(obs, top_n=3, cost=DEFAULT_COST, boot=2000):
    ics, strat, bench, turns = [], [], [], []
    prev_hold = set()
    for o in obs:
        ic = spearman(o["sig"], o["fwd"])
        if ic is not None:
            ics.append(ic)

        order = sorted(range(len(o["syms"])), key=lambda i: -o["sig"][i])
        hold = set(order[:top_n])
        if not hold:
            continue
        r = sum(o["fwd"][i] for i in hold) / len(hold)
        turn = len(hold - prev_hold) / len(hold)          # 换手比例
        turns.append(turn)
        strat.append(r - turn * 2 * cost)                 # 卖出 + 买入各付一次
        bench.append(sum(o["fwd"]) / len(o["fwd"]))
        prev_hold = hold

    if len(strat) < 12:
        return {"ok": False, "reason": f"可用期数只有 {len(strat)}，不足 12 期"}

    ic_m, ic_t = mean_t(ics)
    ic_ci = bootstrap_ci(ics, n_boot=boot)
    ex = [a - b for a, b in zip(strat, bench)]
    ex_m, ex_t = mean_t(ex)
    ex_ci = bootstrap_ci(ex, n_boot=boot)

    def cagr(monthly):
        cum = 1.0
        for r in monthly:
            cum *= (1 + r)
        return cum ** (12 / len(monthly)) - 1

    def mdd(monthly):
        cum, peak, worst = 1.0, 1.0, 0.0
        for r in monthly:
            cum *= (1 + r)
            peak = max(peak, cum)
            worst = max(worst, 1 - cum / peak)
        return worst

    if ic_ci is None:
        verdict = "无法判断（期数不足）"
    elif ic_ci[0] > 0:
        verdict = "有预测力（IC CI 下界 > 0）"
    elif ic_ci[2] < 0:
        verdict = "反向有效（IC CI 上界 < 0）"
    else:
        verdict = "无证据（IC CI 跨越 0）"

    return {
        "ok": True, "periods": len(strat), "ic_mean": ic_m, "ic_t": ic_t, "ic_ci": ic_ci,
        "ic_pos_ratio": sum(1 for x in ics if x > 0) / len(ics),
        "strat_cagr": cagr(strat), "strat_mdd": mdd(strat),
        "bench_cagr": cagr(bench), "bench_mdd": mdd(bench),
        "ex_mean": ex_m, "ex_t": ex_t, "ex_ci": ex_ci,
        "avg_turnover": sum(turns) / len(turns) if turns else 0.0,
        "verdict": verdict,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="截面动量/排序检验")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--csv-dir", default="data_cache")
    ap.add_argument("--lookback", type=int, default=6, help="回看几个月（信号）")
    ap.add_argument("--top", type=int, default=3, help="做多前几名")
    ap.add_argument("--cost", type=float, default=DEFAULT_COST)
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args(argv)

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    dates, panel, used = load_panel(syms, args.csv_dir)
    print(f"参与标的 {len(used)} 只：{', '.join(used)}")
    print(f"共同交易日 {len(dates)} 天（{dates[0]} → {dates[-1]}）")

    obs = build_observations(panel, dates, lookback_months=args.lookback)
    res = evaluate(obs, top_n=args.top, cost=args.cost)
    print(f"可用期数 {len(obs)} 期（回看 {args.lookback} 个月，做多前 {args.top} 名）\n")

    if not res.get("ok"):
        print(res["reason"])
        return 1

    lo, mid, hi = res["ic_ci"]
    print(f"  rank IC 均值 {res['ic_mean']:+.4f}   t = {res['ic_t']:+.2f}   "
          f"正 IC 占比 {res['ic_pos_ratio']*100:.1f}%")
    print(f"  IC 95% CI    [{lo:+.4f}, {hi:+.4f}]（中位 {mid:+.4f}）")
    print(f"\n  策略年化 {res['strat_cagr']*100:+.2f}%（回撤 {res['strat_mdd']*100:.2f}%）"
          f"   等权基准 {res['bench_cagr']*100:+.2f}%（回撤 {res['bench_mdd']*100:.2f}%）")
    print(f"  月度超额 {res['ex_mean']*100:+.3f}%/月   t = {res['ex_t']:+.2f}   "
          f"平均换手 {res['avg_turnover']*100:.0f}%")
    if res["ex_ci"]:
        a, b, c = res["ex_ci"]
        print(f"  超额 95% CI  [{a*100:+.3f}%, {c*100:+.3f}%]/月")
    print(f"\n  ▶ 判定：{res['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
