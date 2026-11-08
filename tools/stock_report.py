#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Per-ticker analysis report -- answers "should I keep researching this?"

Two languages
    lang="zh" (default) or "en". Same numbers, same verdicts; only the prose differs.

Five sections
    1. Data health   is this data trustworthy (rows, range, dirty rows, density)
    2. Structure     trending or mean-reverting, with the evidence strength
    3. What to test  the hypothesis parameters worth trying (a direction, not advice)
    4. Known risks   sample window, survivorship, costs, price adjustment
    5. Disclaimer

Rules
    * every number is reproducible from the same cache
    * when structure is unclear it says so instead of inventing a direction
    * never says buy / sell / target price / guaranteed

Usage
    python -m tools.stock_report --symbol AAPL [--lang en]
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.profile import profile  # noqa: E402
from tools.validate import find_cached, read_csv  # noqa: E402

STRUCT_EN = {"趋势型": "Trending",
             "均值回归型": "Mean-reverting",
             "无明显结构": "No clear structure"}

S = {
    "zh": {
        "title": "# {symbol} 分析报告",
        "meta": "> 生成时间 {today} ｜ 数据文件 `{cache}` ｜ 市场 {market}",
        "s0": "## 0. 一句话结论",
        "s1": "## 1. 数据体检",
        "s2": "## 2. 结构判断",
        "s3": "## 3. 能做什么（方向，不是建议）",
        "s4": "## 4. 已知风险",
        "s5": "## 5. 免责声明",
        "insufficient": "**这份数据目前不足以分析**：{reason}。",
        "trend_head": "**这只票历史上是「顺着走」型**：涨跌有明显惯性（结构强度 z = {z}）。",
        "trend_next": "顺着这个结构，值得去检验「买过去涨得多的」这个方向。",
        "revert_head": "**这只票历史上是「来回摆」型**：涨了容易跌回、跌了容易反弹（结构强度 z = {z}）。",
        "revert_next": "顺着这个结构，值得去检验「买过去跌得多的」这个方向。",
        "none_head": "**这只票历史上看不出稳定结构**：趋势和回归都不占优。",
        "none_next": "这种情况下硬套方向是最容易亏钱的做法 —— 建议换一只票，或换一类信号。",
        "th_item": "| 项目 | 数值 | 怎么看 |", "th_metric": "| 指标 | 数值 | 含义 |",
        "row_days": "| 交易日数 | {n} 天（约 {y} 年） | 少于 60 天无法分析 |",
        "row_range": "| 区间 | {first} → {last} | 越长越能覆盖不同行情 |",
        "row_price": "| 价格范围 | {lo:.2f} – {hi:.2f} | 含 0 或负数说明复权口径有问题 |",
        "row_bad": "| 非正价格 | {n} 行 | 必须为 0 |",
        "row_dup": "| 重复日期 | {n} 行 | 必须为 0 |",
        "row_sorted": "| 日期有序 | {yes} | 乱序会让指标算错 |",
        "row_density": "| 数据密度 | {d} | 接近 1.00 表示没有大段缺失 |",
        "dirty": "> ⚠ 这份数据存在质量问题，上面的结构判断会被影响，建议先清洗再去检验。",
        "verdict": "**判定：{structure}**（不是拍脑袋，是两条独立证据都通过才下的）",
        "row_ac": "| lag1 自相关 | {v} | 今天的涨跌跟昨天还有没有关系（正＝有惯性，负＝会回吐） |",
        "row_vr": "| VR20 | {v} | 20 天波动 / 1 天波动；>1 波动被放大，<1 被吃掉 |",
        "row_z": "| 置换 z 值 | {v} | 把日期打乱重来 120 次后，这个 VR 有多罕见（\\|z\\|>2 才算有结构） |",
        "row_vol": "| 年化波动 | {v}% | 价格晃得有多厉害 |",
        "row_dd": "| 最大回撤 | {v}%（{days} 天） | 历史上最难受的时候亏多少 |",
        "evidence": "证据：",
        "card_intro": "  可以新建一条这样的检验：",
        "card_warn": "> 注意：这只是「顺着结构该往哪想」，不是说这个方向一定有效。必须跑一次检验，看它能不能过 95% 那道坎。",
        "no_direction": "没有可以试的方向。结构不明确时，最诚实的答案是「先别做」。",
        "risk_window": "- **样本窗口**：只有 {y} 年。换一个时间段，结构可能完全不同。",
        "risk_surv": "- **幸存者偏差**：这份数据来自「今天还存在的标的」。用它回测等于提前知道谁赢了。",
        "risk_cost": "- **成本假设**：检验时按单边 0.08%（手续费 0.03% + 滑点 0.05%）计算，未含税费与冲击成本。",
        "risk_cn_adj": "- **复权口径**：A 股长历史必须用后复权；前复权在高分红股上会算出负价格。",
        "risk_cn_rule": "- **交易制度**：涨跌停时买不进/卖不出，停牌日无数据；本报告未模拟这些限制。",
        "risk_us_adj": "- **复权口径**：用的是 yfinance 的调整后价格（拆股、分红已调整）。",
        "risk_us_rule": "- **交易制度**：未模拟盘前盘后、借券成本与流动性冲击。",
        "risk_cr_rule": "- **交易制度**：加密 7×24 无收盘，波动远高于股票。",
        "risk_drift": "- **结构会变**：历史偏趋势不代表未来偏趋势，只代表「过去是这样」。",
        "disclaimer_1": "本报告是**研究工具**的输出，用于判断「这只票值不值得继续研究」，不构成投资建议、不预测价格、不承诺收益。",
        "disclaimer_2": "本报告只代表过去，不代表未来。不要用实盘资金直接照抄。",
        "why_trend": "结构像趋势延续：过去涨得好的，倾向继续涨。用「买过去涨得多的」去检验。",
        "why_revert": "结构像涨跌回吐：过去跌得多的，倾向反弹。用「买过去跌得多的」去检验。",
        "msg_done": "已生成：{out}（{n} 字符）",
        "msg_missing": "缓存里找不到 {sym}",
        "filename": "{sym}_分析报告_{today}.md",
    },
    "en": {
        "title": "# {symbol} analysis report",
        "meta": "> Generated {today} | data file `{cache}` | market {market}",
        "s0": "## 0. Bottom line",
        "s1": "## 1. Data health",
        "s2": "## 2. Structural verdict",
        "s3": "## 3. What is worth testing (a direction, not advice)",
        "s4": "## 4. Known risks",
        "s5": "## 5. Disclaimer",
        "insufficient": "**This data is not enough to analyse**: {reason}.",
        "trend_head": "**This ticker has trended historically**: moves show clear persistence (structure strength z = {z}).",
        "trend_next": "Following that structure, the direction worth testing is 'buy past winners'.",
        "revert_head": "**This ticker has mean-reverted historically**: rallies faded and sell-offs bounced (structure strength z = {z}).",
        "revert_next": "Following that structure, the direction worth testing is 'buy past losers'.",
        "none_head": "**No stable structure is visible in this ticker**: neither trend nor reversion dominates.",
        "none_next": "Forcing a direction here is the easiest way to lose money -- consider another ticker or another class of signal.",
        "th_item": "| Item | Value | How to read it |", "th_metric": "| Metric | Value | Meaning |",
        "row_days": "| Trading days | {n} (~{y} years) | fewer than 60 cannot be analysed |",
        "row_range": "| Range | {first} -> {last} | longer covers more regimes |",
        "row_price": "| Price range | {lo:.2f} - {hi:.2f} | zero or negative means the adjustment is broken |",
        "row_bad": "| Non-positive prices | {n} rows | must be 0 |",
        "row_dup": "| Duplicate dates | {n} rows | must be 0 |",
        "row_sorted": "| Dates sorted | {yes} | out-of-order dates corrupt every indicator |",
        "row_density": "| Density | {d} | close to 1.00 means no large gaps |",
        "dirty": "> ⚠ This data has quality problems; the structural verdict above is affected. Clean it before testing.",
        "verdict": "**Verdict: {structure}** (two independent pieces of evidence agree; this is not a guess)",
        "row_ac": "| lag1 autocorrelation | {v} | does today remember yesterday (positive = persistence, negative = give-back) |",
        "row_vr": "| VR20 | {v} | 20-day variance / 1-day variance; above 1 compounds, below 1 gets eaten |",
        "row_z": "| Permutation z | {v} | how rare this VR is when the date order is shuffled 120 times (\\|z\\| > 2 counts as structure) |",
        "row_vol": "| Annualised volatility | {v}% | how violently the price moves |",
        "row_dd": "| Maximum drawdown | {v}% ({days} days) | the worst peak-to-trough loss on record |",
        "evidence": "Evidence:",
        "card_intro": "  You could write a test like this:",
        "card_warn": "> Note: this is only 'which way to think given the structure', not a claim that the direction works. Run a test and see whether it clears the 95% bar.",
        "no_direction": "Nothing worth testing. When structure is unclear, the honest answer is 'do not trade it'.",
        "risk_window": "- **Sample window**: {y} years only. A different period could show a completely different structure.",
        "risk_surv": "- **Survivorship bias**: this data comes from names that still exist today, so a backtest already knows who won.",
        "risk_cost": "- **Cost assumption**: 0.08% per side (0.03% commission + 0.05% slippage); taxes and market impact excluded.",
        "risk_cn_adj": "- **Price adjustment**: long A-share history must be back-adjusted; forward adjustment goes negative on high-dividend names.",
        "risk_cn_rule": "- **Trading rules**: no limit-up/limit-down or halt modelling, and halted days have no bar.",
        "risk_us_adj": "- **Price adjustment**: yfinance adjusted prices (splits and dividends already handled).",
        "risk_us_rule": "- **Trading rules**: pre/post-market, borrow cost and market impact are not modelled.",
        "risk_cr_rule": "- **Trading rules**: crypto trades 24/7 with no close and far higher volatility.",
        "risk_drift": "- **Structure drifts**: historically trending does not mean it will trend next, only that it did.",
        "disclaimer_1": "This report is the output of a **research instrument**, meant to judge whether a ticker is worth more research. It is not investment advice, does not predict prices and promises no returns.",
        "disclaimer_2": "It describes the past, not the future. Do not trade real money off it.",
        "why_trend": "The structure looks like trend continuation: past winners tend to keep winning. Test 'buy past winners'.",
        "why_revert": "The structure looks like give-back: past losers tend to bounce. Test 'buy past losers'.",
        "msg_done": "written: {out} ({n} chars)",
        "msg_missing": "no cached data for {sym}",
        "filename": "{sym}_report_{today}.md",
    },
}


def data_health(rows):
    """Only judge what the data itself can tell us."""
    prices = [r["close"] for r in rows]

    def _min_price(r):
        vals = [r[k] for k in ("open", "high", "low", "close") if r.get(k) is not None]
        return min(vals) if vals else None

    bad_price = sum(1 for r in rows
                    if (m := _min_price(r)) is not None and m <= 0)
    dates = [r["date"] for r in rows]
    dup = len(dates) - len(set(dates))
    ordered = all(dates[i] <= dates[i + 1] for i in range(len(dates) - 1))
    days = len(rows)
    years = days / 252
    density = days / (252 * years) if years else None
    return {
        "days": days, "years": round(years, 2),
        "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
        "bad_price": bad_price, "duplicates": dup, "sorted": ordered,
        "density": round(density, 3) if density else None,
        "min_close": min(prices) if prices else None,
        "max_close": max(prices) if prices else None,
    }


def suggest_cards(prof, symbol, market, lang="zh"):
    """Turn the structure into testable parameters (a direction, not advice)."""
    T = S.get(lang, S["zh"])
    struct = prof.get("structure")
    if struct == "趋势型":
        return [dict(kind="cross_section", direction="momentum", lookback=6, top_n=3,
                     market=market, symbol=symbol, why=T["why_trend"])]
    if struct == "均值回归型":
        return [dict(kind="cross_section", direction="reversal", lookback=5, top_n=3,
                     market=market, symbol=symbol, why=T["why_revert"])]
    return []


def build_report(rows, symbol, market, cache_name="", lang="zh"):
    T = S.get(lang, S["zh"])
    prof = profile(rows)
    health = data_health(rows)
    today = date.today().isoformat()
    yes = "是" if lang != "en" else "yes"
    no = "否" if lang != "en" else "no"

    L = []
    L.append(T["title"].format(symbol=symbol))
    L.append("")
    L.append(T["meta"].format(today=today, cache=cache_name or "-", market=market))
    L.append("")

    # ---------- 0 ----------
    L.append(T["s0"])
    L.append("")
    if not prof.get("ok"):
        L.append(T["insufficient"].format(reason=prof.get("reason", "unknown")))
    elif prof["structure"] == "趋势型":
        L.append(T["trend_head"].format(z=prof["vr20_z"]))
        L.append(T["trend_next"])
    elif prof["structure"] == "均值回归型":
        L.append(T["revert_head"].format(z=prof["vr20_z"]))
        L.append(T["revert_next"])
    else:
        L.append(T["none_head"])
        L.append(T["none_next"])
    L.append("")

    # ---------- 1 ----------
    L.append(T["s1"])
    L.append("")
    L.append(T["th_item"])
    L.append("| --- | --- | --- |")
    L.append(T["row_days"].format(n=health["days"], y=health["years"]))
    L.append(T["row_range"].format(first=health["first"], last=health["last"]))
    L.append(T["row_price"].format(lo=health["min_close"], hi=health["max_close"]))
    L.append(T["row_bad"].format(n=health["bad_price"]))
    L.append(T["row_dup"].format(n=health["duplicates"]))
    L.append(T["row_sorted"].format(yes=yes if health["sorted"] else no))
    L.append(T["row_density"].format(d=health["density"]))
    L.append("")
    if health["bad_price"] or health["duplicates"] or not health["sorted"]:
        L.append(T["dirty"])
        L.append("")

    # ---------- 2 ----------
    L.append(T["s2"])
    L.append("")
    if prof.get("ok"):
        label = STRUCT_EN.get(prof["structure"], prof["structure"]) if lang == "en" else prof["structure"]
        L.append(T["verdict"].format(structure=label))
        L.append("")
        L.append(T["th_metric"])
        L.append("| --- | --- | --- |")
        L.append(T["row_ac"].format(v=prof["autocorr1"]))
        L.append(T["row_vr"].format(v=prof["vr20"]))
        L.append(T["row_z"].format(v=prof["vr20_z"]))
        L.append(T["row_vol"].format(v=f"{prof['annual_vol']*100:.2f}"))
        L.append(T["row_dd"].format(v=f"{prof['max_drawdown']*100:.2f}",
                                     days=prof["max_dd_days"]))
        L.append("")
        L.append(T["evidence"])
        bullets = prof["evidence"]
        if lang == "en" and prof.get("evidence_en"):
            bullets = prof["evidence_en"]
        for w in bullets:
            L.append(f"- {w}")
    else:
        L.append(prof.get("reason", ""))
    L.append("")

    # ---------- 3 ----------
    L.append(T["s3"])
    L.append("")
    cards = suggest_cards(prof, symbol, market, lang)
    if cards:
        for c in cards:
            L.append(f"- **{c['why']}**")
            L.append("")
            L.append(T["card_intro"])
            L.append("")
            L.append("  ```json")
            L.append(f'  {{"kind": "{c["kind"]}", "market": "{c["market"]}", '
                     f'"direction": "{c["direction"]}", '
                     f'"lookback": {c["lookback"]}, "top_n": {c["top_n"]}}}')
            L.append("  ```")
            L.append("")
        L.append(T["card_warn"])
    else:
        L.append(T["no_direction"])
    L.append("")

    # ---------- 4 ----------
    L.append(T["s4"])
    L.append("")
    L.append(T["risk_window"].format(y=health["years"]))
    L.append(T["risk_surv"])
    L.append(T["risk_cost"])
    if market == "cn":
        L.append(T["risk_cn_adj"])
        L.append(T["risk_cn_rule"])
    elif market == "us":
        L.append(T["risk_us_adj"])
        L.append(T["risk_us_rule"])
    else:
        L.append(T["risk_cr_rule"])
    L.append(T["risk_drift"])
    L.append("")

    # ---------- 5 ----------
    L.append(T["s5"])
    L.append("")
    L.append(T["disclaimer_1"])
    L.append("")
    L.append(T["disclaimer_2"])
    return "\n".join(L)


def report_filename(symbol, lang="zh"):
    T = S.get(lang, S["zh"])
    return T["filename"].format(sym=symbol, today=date.today().isoformat())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a per-ticker analysis report")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--csv-dir", default="data_cache")
    ap.add_argument("--out", default=None)
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    args = ap.parse_args(argv)

    T = S[args.lang]
    sym = args.symbol.upper()
    path = args.csv or find_cached(args.csv_dir, sym)
    if not path:
        print(T["msg_missing"].format(sym=sym))
        return 1
    path = Path(path)
    market = path.name.split("_")[0]
    rows = read_csv(path)
    md = build_report(rows, sym, market, path.name, lang=args.lang)
    out = Path(args.out) if args.out else Path("reports") / report_filename(sym, args.lang)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(T["msg_done"].format(out=out, n=len(md)))
    return 0


if __name__ == "__main__":
    sys.exit(main())