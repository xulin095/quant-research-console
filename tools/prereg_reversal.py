#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""预注册检验卡 HK-001 —— A股 中期反转（单次，参数冻结）

卡号        HK-001
提交时间    2026-11-08
假设        A股中，过去 5 个月累计涨幅最高的股票，未来 1 个月跑输市场。
            因此做多「过去 5 个月跌幅最大的 3 只」，等权持有 1 个月。
机制        散户追涨 → 短期定价过度 → 随后回吐。反转而非动量。
规则        月末按过去 5 个月收益**升序**取前 3；下月等权持有；换手单边 0.08%。
创新边界    lookback = 5 在此刻冻结。不通过后不许改成 4/6/3 再试。
样本        2021-01-01 之后（留出段；此前未被用于本假设的任何参数选择）
判据        IC 的 95% CI 下界 > 0 且 月度超额 t > 2 → 通过；否则淘汰。
诚实说明    这个假设是「看了 12 个 lookback × 2 个方向之后」才提出的，
            因此还要报一个「发现后校正」的 p 值（N=24）——那才是真实错误率。

跑法
    python -m tools.prereg_reversal
退出码 0 = 通过，1 = 不通过
"""

import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.cross_section import build_observations, evaluate, load_panel  # noqa: E402

CARD = "HK-001"
LOOKBACK = 5          # 冻结
TOP_N = 3             # 冻结
DIRECTION = "reversal"  # 冻结
HOLDOUT = "2021-01-01"
COST = 0.0008
DISCOVERY_TESTS = 24  # 12 个 lookback × 2 个方向 = 发现该假设时已经看过的检验次数


def one_sided_p(t):
    return 1.0 - NormalDist().cdf(t)


def bonferroni(p, n):
    return min(1.0, 1.0 - (1.0 - p) ** n)


def main():
    print(f"预注册卡 {CARD}：{DIRECTION}，lookback={LOOKBACK}，topN={TOP_N}，成本 {COST*100:.2f}%/边")
    print(f"检验区间：{HOLDOUT} 之后（留出段，单次）\n")

    meta = json.loads(Path("universe.json").read_text(encoding="utf-8"))
    syms = [x["code"] for x in meta["success"]]
    print(f"宇宙：{len(syms)} 只（覆盖率 {meta['coverage']*100:.0f}%，"
          f"退市票 {meta['delisted_ok']}/{meta['failed']+meta['delisted_ok']}）")

    dates, panel, used = load_panel(syms, "data_cache")
    obs_all = build_observations(panel, dates, lookback_months=LOOKBACK)
    obs = [o for o in obs_all if o["date"] >= HOLDOUT]
    print(f"留出段可用期数：{len(obs)}（{obs[0]['date']} → {obs[-1]['date']}）\n" if obs else "留出段没有观测")
    if len(obs) < 24:
        print("留出段期数不足 24，无法检验 —— 判定：无法检验（不是通过）")
        return 1

    # 冻结的信号方向：反转 → 把信号取负，于是「做多 top」= 做多前期跌得最狠的
    for o in obs:
        o["sig"] = [-x for x in o["sig"]]

    res = evaluate(obs, top_n=TOP_N, cost=COST, boot=4000)
    if not res.get("ok"):
        print(res.get("reason"))
        return 1

    lo, mid, hi = res["ic_ci"]
    p = one_sided_p(res["ic_t"])
    p_adj = bonferroni(p, DISCOVERY_TESTS)

    print(f"  IC 均值      {res['ic_mean']*100:+.2f}   t = {res['ic_t']:+.2f}")
    print(f"  IC 95% CI    [{lo*100:+.2f}, {hi*100:+.2f}]")
    print(f"  单次 p       {p:.4f}    → 发现后校正 p（N={DISCOVERY_TESTS}）= {p_adj:.4f}")
    print(f"  策略年化     {res['strat_cagr']*100:+.2f}%"
          f"   等权基准 {res['bench_cagr']*100:+.2f}%")
    print(f"  月度超额     {res['ex_mean']*100:+.3f}%/月   t = {res['ex_t']:+.2f}"
          f"   换手 {res['avg_turnover']*100:.0f}%")
    if res["ex_ci"]:
        a, b, c = res["ex_ci"]
        print(f"  超额 95% CI  [{a*100:+.3f}%, {c*100:+.3f}%]/月")

    passed = (lo > 0) and (res["ex_t"] > 2)
    print("\n" + "=" * 58)
    if passed:
        print("判定：通过（IC CI 下界 > 0 且 超额 t > 2）")
        print("下一步：把这张卡连同结果写进登记处，然后才谈仓位与产品。")
        return 0
    print("判定：不通过 —— 按预注册约定，该假设淘汰，不再调参重试。")
    print("        这是本轮研究第二次被自己的工具否掉，也是它有价值的地方。")
    if p_adj >= 0.05:
        print(f"        注：发现后校正 p={p_adj:.3f} ≥ 0.05，说明这个方向本来就大概率是搜索出来的。")
    return 1


if __name__ == "__main__":
    sys.exit(main())