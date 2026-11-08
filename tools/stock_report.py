#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""单只股票的分析报告 —— 给「要不要继续研究这只票」用，不是给买卖决策用。

五个部分
    一、数据体检   这份数据可不可信（行数、区间、脏数据、密度）
    二、结构判断   这只票历史上是趋势型还是均值回归型（带证据强度）
    三、能做什么   按结构给出「可以试哪个方向」的假设参数（只是方向，不是建议）
    四、已知风险   样本、幸存者偏差、成本、复权
    五、免责

设计原则
    · 每个数字都能复现（同一份缓存算两遍必须一样）
    · 判不出结构时说「判不出」，不硬凑方向
    · 不出现「建议买入/卖出/目标价」这类表述

用法
    python -m tools.stock_report --symbol AAPL
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.profile import profile  # noqa: E402
from tools.validate import find_cached, read_csv  # noqa: E402


def data_health(rows):
    """数据体检：只做能由数据本身判断的事。"""
    prices = [r["close"] for r in rows]
    # read_csv 只保证 date/open/close 这几列，high/low 可能没有，不能硬取
    def _min_price(r):
        vals = [r[k] for k in ("open", "high", "low", "close") if r.get(k) is not None]
        return min(vals) if vals else None

    bad_price = 0
    for r in rows:
        m = _min_price(r)
        if m is not None and m <= 0:
            bad_price += 1
    dates = [r["date"] for r in rows]
    dup = len(dates) - len(set(dates))
    ordered = all(dates[i] <= dates[i + 1] for i in range(len(dates) - 1))
    days = len(rows)
    years = days / 252
    density = days / (252 * years) if years else None     # 与「每年 252 天」的接近程度
    return {
        "days": days, "years": round(years, 2),
        "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
        "bad_price": bad_price, "duplicates": dup, "sorted": ordered,
        "density": round(density, 3) if density else None,
        "min_close": min(prices) if prices else None,
        "max_close": max(prices) if prices else None,
    }


def suggest_cards(prof, symbol, market):
    """按结构给出可以试的检验参数（方向 + 参数），不是买卖建议。"""
    struct = prof.get("structure")
    if struct == "趋势型":
        return [m for m in [dict(
            kind="cross_section", direction="momentum", lookback=6, top_n=3,
            market=market, symbol=symbol,
            why="结构像趋势延续：过去涨得好的，倾向继续涨。用「买过去涨得多的」去检验。")]]
    if struct == "均值回归型":
        return [m for m in [dict(
            kind="cross_section", direction="reversal", lookback=5, top_n=3,
            market=market, symbol=symbol,
            why="结构像涨跌回吐：过去跌得多的，倾向反弹。用「买过去跌得多的」去检验。")]]
    return []


def build_report(rows, symbol, market, cache_name=""):
    prof = profile(rows)
    health = data_health(rows)
    today = date.today().isoformat()

    L = []
    L.append(f"# {symbol} 分析报告")
    L.append("")
    L.append(f"> 生成时间 {today} ｜ 数据文件 `{cache_name or '—'}` ｜ 市场 {market}")
    L.append("")

    # ---------- 一句话 ----------
    L.append("## 0. 一句话结论")
    L.append("")
    if not prof.get("ok"):
        L.append(f"**这份数据目前不足以分析**：{prof.get('reason', '未知原因')}。")
    elif prof["structure"] == "趋势型":
        L.append(f"**这只票历史上是「顺着走」型**：涨跌有明显惯性（结构强度 z = {prof['vr20_z']}）。"
                 f"顺着这个结构，值得去检验「买过去涨得多的」这个方向。")
    elif prof["structure"] == "均值回归型":
        L.append(f"**这只票历史上是「来回摆」型**：涨了容易跌回、跌了容易反弹（结构强度 z = {prof['vr20_z']}）。"
                 f"顺着这个结构，值得去检验「买过去跌得多的」这个方向。")
    else:
        L.append("**这只票历史上看不出稳定结构**：趋势和回归都不占优。"
                 "这种情况下硬套方向是最容易亏钱的做法 —— 建议换一只票，或换一类信号。")
    L.append("")

    # ---------- 一、数据体检 ----------
    L.append("## 1. 数据体检")
    L.append("")
    L.append("| 项目 | 数值 | 怎么看 |")
    L.append("| --- | --- | --- |")
    L.append(f"| 交易日数 | {health['days']} 天（约 {health['years']} 年） | 少于 60 天无法分析 |")
    L.append(f"| 区间 | {health['first']} → {health['last']} | 越长越能覆盖不同行情 |")
    L.append(f"| 价格范围 | {health['min_close']:.2f} – {health['max_close']:.2f} | 含 0 或负数说明复权口径有问题 |")
    L.append(f"| 非正价格 | {health['bad_price']} 行 | 必须为 0 |")
    L.append(f"| 重复日期 | {health['duplicates']} 行 | 必须为 0 |")
    L.append(f"| 日期有序 | {'是' if health['sorted'] else '否'} | 乱序会让指标算错 |")
    L.append(f"| 数据密度 | {health['density']} | 接近 1.00 表示没有大段缺失 |")
    L.append("")
    if health["bad_price"] or health["duplicates"] or not health["sorted"]:
        L.append("> ⚠ 这份数据存在质量问题，上面的结构判断会被影响，建议先清洗再去检验。")
        L.append("")

    # ---------- 二、结构判断 ----------
    L.append("## 2. 结构判断")
    L.append("")
    if prof.get("ok"):
        L.append(f"**判定：{prof['structure']}**（不是拍脑袋，是两条独立证据都通过才下的）")
        L.append("")
        L.append("| 指标 | 数值 | 含义 |")
        L.append("| --- | --- | --- |")
        L.append(f"| lag1 自相关 | {prof['autocorr1']} | 今天的涨跌跟昨天还有没有关系（正＝有惯性，负＝会回吐） |")
        L.append(f"| VR20 | {prof['vr20']} | 20 天波动 / 1 天波动；>1 波动被放大，<1 被吃掉 |")
        L.append(f"| 置换 z 值 | {prof['vr20_z']} | 把日期打乱重来 120 次后，这个 VR 有多罕见（\\|z\\|>2 才算有结构） |")
        L.append(f"| 年化波动 | {prof['annual_vol']*100:.2f}% | 价格晃得有多厉害 |")
        L.append(f"| 最大回撤 | {prof['max_drawdown']*100:.2f}%（{prof['max_dd_days']} 天） | 历史上最难受的时候亏多少 |")
        L.append("")
        L.append("证据：")
        for w in prof["evidence"]:
            L.append(f"- {w}")
    else:
        L.append(prof.get("reason", "数据不足"))
    L.append("")

    # ---------- 三、能做什么 ----------
    L.append("## 3. 能做什么（方向，不是建议）")
    L.append("")
    cards = suggest_cards(prof, symbol, market)
    if cards:
        for c in cards:
            L.append(f"- **{c['why']}**")
            L.append("")
            L.append("  可以新建一条这样的检验：")
            L.append("")
            L.append("  ```json")
            L.append(f'  {{"kind": "{c["kind"]}", "market": "{c["market"]}", '
                     f'"direction": "{c["direction"]}", '
                     f'"lookback": {c["lookback"]}, "top_n": {c["top_n"]}}}')
            L.append("  ```")
            L.append("")
        L.append("> 注意：这只是「顺着结构该往哪想」，不是说这个方向一定有效。"
                 "必须跑一次检验，看它能不能过 95% 那道坎。")
    else:
        L.append("没有可以试的方向。结构不明确时，最诚实的答案是「先别做」。")
    L.append("")

    # ---------- 四、已知风险 ----------
    L.append("## 4. 已知风险")
    L.append("")
    L.append(f"- **样本窗口**：只有 {health['years']} 年。换一个时间段，结构可能完全不同。")
    L.append("- **幸存者偏差**：这份数据来自「今天还存在的标的」。用它回测等于提前知道谁赢了。")
    L.append("- **成本假设**：检验时按单边 0.08%（手续费 0.03% + 滑点 0.05%）计算，未含税费与冲击成本。")
    L.append("- **复权口径**：A 股长历史必须用后复权；前复权在高分红股上会算出负价格。")
    L.append("- **结构会变**：历史偏趋势不代表未来偏趋势，只代表「过去是这样」。")
    L.append("")

    # ---------- 五、免责 ----------
    L.append("## 5. 免责声明")
    L.append("")
    L.append("本报告是**研究工具**的输出，用于判断「这只票值不值得继续研究」，"
             "不构成投资建议、不预测价格、不承诺收益。")
    L.append("")
    L.append("本报告只代表过去，不代表未来。不要用实盘资金直接照抄。")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成单只股票的分析报告")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--csv-dir", default="data_cache")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    sym = args.symbol.upper()
    path = args.csv or find_cached(args.csv_dir, sym)
    if not path:
        print(f"缓存里找不到 {sym}")
        return 1
    path = Path(path)
    market = path.name.split("_")[0]
    rows = read_csv(path)
    md = build_report(rows, sym, market, path.name)
    out = Path(args.out) if args.out else Path("reports") / f"{sym}_分析报告_{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"已生成：{out}（{len(md)} 字符）")
    return 0


if __name__ == "__main__":
    sys.exit(main())