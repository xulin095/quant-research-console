#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
第 0 棒交付：独立复算裁判（audit_recalc.py）

作用
    不信任被测项目给出的任何数字。只从 data_cache 里的标准表 CSV 重新算一遍
    双均线回测与 6 个风控数字，再和报告 .md 里写的数字逐项对比。

铁律
    本文件 **禁止 import 被测项目里的任何模块**。它是一条独立的计算路径，
    否则就变成"用被测代码验证被测代码"，这个裁判就废了。

用法
    python audit_recalc.py --root ..\quant-agent                  # 自动找最新报告
    python audit_recalc.py --root ..\quant-agent --report reports\xxx.md
    python audit_recalc.py --csv ..\quant-agent\data_cache\us_AAPL_2024-01-01_2025-12-31.csv
    python audit_recalc.py --csv xxx.csv --market us --symbol AAPL --start 2024-01-01 --end 2025-12-31

退出码
    0  报告数字与独立复算一致（或只复算、没给报告）
    1  有不一致 / 数据缺失

口径来源：prompts-v2.md 附录 A。改口径必须同时改这里和 design.md，否则对不上就是 bug。
"""

import argparse
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 口径常量
CAPITAL = 100000.0      # 初始资金
FAST, SLOW = 5, 20      # 快线 / 慢线
FEE, SLIP = 0.0003, 0.0005
RF_ANNUAL = 0.02        # 无风险利率（年化）
TRADING_DAYS = 252
MIN_ROWS = 60           # 少于这个行数视为数据不足

REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume"]

# 报告里的中文标签 -> 内部字段名
LABELS = {
    "总收益率": "total",
    "年化收益率": "annual",
    "最大回撤": "mdd",
    "夏普比率": "sharpe",
    "胜率": "winrate",
    "交易次数": "trades",
}

# 百分比型指标：容差按"百分点"算（报告保留 2 位小数）
PCT_FIELDS = {"total", "annual", "mdd", "winrate"}
TOL_PCT = 0.011     # 2 位小数的舍入误差留一点余量
TOL_RATIO = 0.011   # 夏普
TOL_TRADES = 0      # 交易次数必须完全相等


# ---------------------------------------------------------------- 读数据
def read_standard_csv(path):
    """读标准 OHLCV 表。只用标准库，不依赖 pandas，避免"顺手"复用被测代码。"""
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        header = [h.strip() for h in f.readline().strip().split(",")]
        missing = [c for c in REQUIRED_COLS if c not in header]
        if missing:
            raise ValueError(f"标准表缺列：{missing}（实际表头：{header}）")
        idx = {c: header.index(c) for c in REQUIRED_COLS}
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                rows.append({
                    "date": parts[idx["date"]][:10],
                    "open": float(parts[idx["open"]]),
                    "close": float(parts[idx["close"]]),
                })
            except (ValueError, IndexError) as e:
                raise ValueError(f"这一行解析失败：{line!r}（{e}）")
    if len(rows) < MIN_ROWS:
        raise ValueError(f"数据只有 {len(rows)} 行，少于最少 {MIN_ROWS} 行，无法复算")
    return rows


def find_cache(project_root, market=None, symbol=None):
    """在 data_cache 里找缓存 CSV。按 prompts-v2 的命名规约匹配，不信 glob 顺序。"""
    cache_dir = Path(project_root) / "data_cache"
    if not cache_dir.is_dir():
        raise FileNotFoundError(f"没有缓存目录：{cache_dir}")
    pattern = re.compile(r"^(?P<market>[a-z]+)_(?P<symbol>[A-Za-z0-9._-]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$")
    hits = []
    for p in sorted(cache_dir.glob("*.csv")):
        m = pattern.match(p.name)
        if not m:
            continue
        if market and m.group("market") != market:
            continue
        if symbol and m.group("symbol").upper() != symbol.upper():
            continue
        hits.append(p)
    if not hits:
        raise FileNotFoundError(
            f"{cache_dir} 里没有符合 data_cache/{{market}}_{{symbol}}_{{start}}_{{end}}.csv 命名的文件"
        )
    if len(hits) > 1 and not market and not symbol:
        print(f"[提醒] 找到 {len(hits)} 个缓存且没指定 --market/--symbol，取最后一个：{hits[-1].name}")
    return hits[-1]


# ---------------------------------------------------------------- 复算
def add_signals(rows):
    """MA5/MA20 + 严格穿越信号。用朴素滑动平均，不引入 pandas。"""
    closes = [r["close"] for r in rows]
    n = len(closes)

    def sma(i, w):
        if i + 1 < w:
            return None
        return sum(closes[i + 1 - w:i + 1]) / w

    ma_f = [sma(i, FAST) for i in range(n)]
    ma_s = [sma(i, SLOW) for i in range(n)]

    for i, r in enumerate(rows):
        r["ma_fast"], r["ma_slow"] = ma_f[i], ma_s[i]
        r["golden"] = r["death"] = False
        if i == 0 or ma_f[i] is None or ma_s[i] is None or ma_f[i - 1] is None or ma_s[i - 1] is None:
            continue
        cur, prev = ma_f[i] > ma_s[i], ma_f[i - 1] > ma_s[i - 1]
        r["golden"] = cur and not prev          # 严格上穿
        r["death"] = (not cur) and prev         # 严格下穿
    return rows


def run_backtest(rows):
    """信号次日开盘成交、全仓、双边扣费。返回 (trades, equity)。

    股数向下取整到 1e-6，现金不得为负 —— 和附录 A 一致。
    """
    cash = CAPITAL
    shares = 0.0
    entry = None
    pending = None          # "buy" / "sell" / None，在下一根开盘执行
    trades, equity = [], []

    for r in rows:
        if pending == "buy":
            px = r["open"]
            shares = math.floor(cash / (px * (1 + FEE + SLIP)) * 1e6) / 1e6
            cost = shares * px * (1 + FEE + SLIP)
            cash -= cost
            entry = {"buy_date": r["date"], "buy_price": px, "shares": shares, "cost": cost}
            pending = None
        elif pending == "sell":
            px = r["open"]
            proceeds = shares * px * (1 - FEE - SLIP)
            cash += proceeds
            t = dict(entry)
            t.update({
                "sell_date": r["date"], "sell_price": px, "proceeds": proceeds,
                "pnl": proceeds - entry["cost"],
                "ret": proceeds / entry["cost"] - 1,
            })
            trades.append(t)
            shares, entry, pending = 0.0, None, None

        equity.append(cash + shares * r["close"])

        if r["golden"] and shares == 0.0 and pending is None:
            pending = "buy"
        elif r["death"] and shares > 0.0 and pending is None:
            pending = "sell"

    return trades, equity, {"shares": shares, "cash": cash}


def metrics(trades, equity):
    """6 个风控数字。样本不足一律返回 None（报告应写"样本不足"）。"""
    e = [float(x) for x in equity]
    out = {}
    out["final_equity"] = e[-1]
    out["total"] = e[-1] / CAPITAL - 1

    n = len(e) - 1
    out["annual"] = (e[-1] / CAPITAL) ** (TRADING_DAYS / n) - 1 if n > 0 and e[-1] > 0 else None

    peak, mdd = e[0], 0.0
    for x in e:
        peak = max(peak, x)
        mdd = max(mdd, 1 - x / peak)
    out["mdd"] = mdd

    rets = [e[i] / e[i - 1] - 1 for i in range(1, len(e)) if e[i - 1] > 0]
    excess = [r - RF_ANNUAL / TRADING_DAYS for r in rets]
    sharpe = None
    if len(excess) >= 2:
        mean = sum(excess) / len(excess)
        var = sum((x - mean) ** 2 for x in excess) / (len(excess) - 1)
        sd = math.sqrt(var)
        # 浮点残差保护：权益全程不变时 var 理论上为 0，但求和顺序会留下 1e-19 级噪声，
        # 不设阈值就会算出 -1.5e16 这种荒谬的夏普。所以用 1e-12 当"实际为零"。
        if sd > 1e-12:
            sharpe = mean / sd * math.sqrt(TRADING_DAYS)
    out["sharpe"] = sharpe

    closed = len(trades)
    out["trades"] = closed
    out["winrate"] = (sum(1 for t in trades if t["pnl"] > 0) / closed) if closed else None
    out["sample_days"] = len(e)
    return out


# ---------------------------------------------------------------- 读报告
def parse_report_numbers(text):
    """从报告 Markdown 表格里抠出 6 个数字。返回 {字段: 原始字符串}。"""
    found = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip().strip("*` ") for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        for label, field in LABELS.items():
            if field in found:
                continue
            if cells[0] == label or cells[0].startswith(label):
                found[field] = cells[1]
    return found


def to_number(cell):
    """把 '12.34%' / '1.05' / '样本不足' 转成 float 或 None。百分比转成小数。"""
    if cell is None:
        return None
    s = cell.replace(",", "").replace("−", "-").strip()
    if not s or "样本不足" in s or s.lower() in ("none", "nan", "-", "—", "n/a"):
        return None
    is_pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100.0 if is_pct else v


# ---------------------------------------------------------------- 主流程
def fmt_pct(x):
    return "—" if x is None else f"{x * 100:.2f}%"


def main(argv=None):
    ap = argparse.ArgumentParser(description="独立复算裁判：从 CSV 重算，和报告数字对比")
    ap.add_argument("--root", default=".", help="项目根目录（含 data_cache/ 与 reports/）")
    ap.add_argument("--csv", default=None, help="直接指定标准表 CSV")
    ap.add_argument("--report", default=None, help="报告 .md 路径；不给就自动找最新")
    ap.add_argument("--market", default=None)
    ap.add_argument("--symbol", default=None)
    args = ap.parse_args(argv)

    try:
        csv_path = Path(args.csv) if args.csv else find_cache(args.root, args.market, args.symbol)
        rows = add_signals(read_standard_csv(csv_path))
    except (OSError, ValueError) as e:
        print(f"[复算失败] {e}")
        return 1

    trades, equity, state = run_backtest(rows)
    m = metrics(trades, equity)

    # 期末是否仍持仓：以最终持仓股数为准，而不是"最后信号是谁"。
    # 最后一根 K 线上的金叉不会成交（没有次日开盘），这种情况不算持仓。
    holding = state["shares"] > 0
    m["holding_at_end"] = holding

    sharpe_s = "样本不足" if m["sharpe"] is None else "%.2f" % m["sharpe"]
    print(f"数据文件   {csv_path}")
    print(f"样本行数   {m['sample_days']} 行")
    print(f"交易回合   {m['trades']} 次" + ("（期末仍持仓）" if holding else ""))
    print(f"期末权益   {m['final_equity']:.2f}")
    print(f"总收益率   {fmt_pct(m['total'])}")
    print(f"年化收益率 {fmt_pct(m['annual'])}")
    print(f"最大回撤   {fmt_pct(m['mdd'])}")
    print(f"夏普比率   {sharpe_s}")
    print(f"胜率       {'样本不足' if m['winrate'] is None else fmt_pct(m['winrate'])}")

    if not args.report:
        print("\n（没给 --report，只做复算，不对比）")
        return 0

    rp = Path(args.report)
    if not rp.is_absolute():
        rp = Path(args.root) / args.report
    if not rp.is_file():
        print(f"\n[对比失败] 报告不存在：{rp}")
        return 1

    got = parse_report_numbers(rp.read_text(encoding="utf-8-sig"))
    print(f"\n对比报告   {rp}\n")
    print(f"{'指标':<10}{'报告值':>12}{'复算值':>12}{'差值':>12}   判定")
    print("-" * 58)

    bad = 0
    for label, field in LABELS.items():
        reported = to_number(got.get(field))
        mine = m.get(field)
        if reported is None and mine is None:
            print(f"{label:<10}{'样本不足':>12}{'样本不足':>12}{'—':>12}   PASS")
            continue
        if reported is None or mine is None:
            print(f"{label:<10}{'-' if reported is None else reported:>12}{'-' if mine is None else round(mine, 6):>12}{'——':>12}   FAIL（一边有值一边没有）")
            bad += 1
            continue
        diff = reported - mine
        if field == "trades":
            ok = int(round(reported)) == int(mine)
            shown_reported, shown_mine, shown_diff = f"{int(round(reported))}", f"{int(mine)}", f"{diff:+.0f}"
        elif field in PCT_FIELDS:
            ok = abs(diff) * 100 <= TOL_PCT
            shown_reported, shown_mine, shown_diff = fmt_pct(reported), fmt_pct(mine), f"{diff * 100:+.3f}pp"
        else:
            ok = abs(diff) <= TOL_RATIO
            shown_reported, shown_mine, shown_diff = f"{reported:.2f}", f"{mine:.2f}", f"{diff:+.4f}"
        print(f"{label:<10}{shown_reported:>12}{shown_mine:>12}{shown_diff:>12}   {'PASS' if ok else 'FAIL'}")
        if not ok:
            bad += 1

    print("-" * 58)
    if bad:
        print(f"结论：{bad} 项不一致 —— 报告数字与独立复算对不上，判 FAIL")
        return 1
    print("结论：6 项全部一致 —— 报告数字可信")
    return 0


if __name__ == "__main__":
    sys.exit(main())
