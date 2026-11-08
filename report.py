from pathlib import Path


def percent(value):
    return "样本不足" if value is None else f"{value:.2%}"


def ratio(value):
    return "样本不足" if value is None else f"{value:.2f}"


def adjustment(market):
    return {"us": "yfinance 自动调整后的价格", "cn": "akshare 前复权价格；前复权历史价会随除权变化",
            "crypto": "Binance 原始价格；UTC 00:00 日线，无复权"}[market]


def trade_lines(trades, last_date):
    lines = []
    for number, trade in enumerate(trades.to_dict("records"), 1):
        closed = trade["status"] == "已平仓"
        end = trade["sell_date"] if closed else last_date
        days = (date_from(end) - date_from(trade["buy_date"])).days
        cells = [str(number), trade["buy_date"], f'{trade["buy_price"]:.2f}',
                 end if closed else "—", f'{trade["sell_price"]:.2f}' if closed else "—",
                 f'{trade["shares"]:.6f}', f'{trade["pnl"]:.2f}' if closed else "—",
                 percent(trade["ret"]) if closed else "—", str(days), trade["status"]]
        lines.append("| " + " | ".join(cells) + " |")
    return lines or ["| — | — | — | — | — | — | — | — | — | 无交易 |"]


def date_from(value):
    from datetime import date
    return date.fromisoformat(value)


def make_report(data, trades, metrics, state, symbol, market, start, end):
    last = data.iloc[-1]
    lines = ["## 1. 基本信息", "", f"代码：{symbol}；市场：{market}；区间：{start} 至 {end}。",
             f"价格口径：{adjustment(market)}。成交量单位：{'基础币数量' if market == 'crypto' else '股'}。",
             "策略：MA5/MA20 严格穿越，信号次日开盘成交；全仓，只做多。",
             "每侧手续费 0.03%，滑点 0.05%；不计印花税。", "",
             "## 2. 近期价格", "", "| 日期 | 开盘价 | 最高价 | 最低价 | 收盘价 | 成交量 |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in data.tail(5).to_dict("records"):
        lines.append(f"| {row['date']} | {row['open']:.2f} | {row['high']:.2f} | {row['low']:.2f} | {row['close']:.2f} | {row['volume']:.2f} |")
    lines += ["", "## 3. 回测结果", "", "| 指标 | 结果 |", "| --- | ---: |"]
    items = [("总收益率", percent(metrics["total"])), ("年化收益率", percent(metrics["annual"])),
             ("最大回撤", percent(metrics["mdd"])), ("夏普比率", ratio(metrics["sharpe"])),
             ("胜率", percent(metrics["winrate"])), ("交易次数", str(metrics["trades"])),
             ("买入持有同期收益率", percent(metrics["benchmark"])),
             ("回测样本交易日数", str(metrics["sample_days"])),
             ("买入成交笔数", str(metrics["buy_count"])), ("卖出成交笔数", str(metrics["sell_count"]))]
    lines += [f"| {name} | {value} |" for name, value in items]
    lines += ["", "## 4. 交易记录", "", "| 序号 | 买入日 | 买入价 | 卖出日 | 卖出价 | 股数 | 收益额 | 收益率 | 持有天数 | 状态 |",
              "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    lines += trade_lines(trades, last["date"])
    if state["shares"] > 0:
        lines += ["", "期末仍持仓，按最后一个交易日收盘价结算权益。"]
    lines += ["", "## 5. 风险提示", "", "只代表过去，不代表未来。不要用实盘资金直接照抄。",
              f"本次样本共 {metrics['sample_days']} 个交易日；换一个时间段结果可能完全不同；震荡市里双均线会频繁假信号。",
              "本版本只跑单一时间区间，未做样本内外切分。", ""]
    return "\n".join(lines)


def write_report(text, symbol, market, start, end):
    path = Path("reports") / f"{symbol}_{market}_{start}_{end}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
