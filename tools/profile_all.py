#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""批量结构画像 —— 一次看清「这批票里哪些偏趋势、哪些偏回归」。

用途
    上传一批票之后，先别急着写卡：先看它们的结构分布。
    如果全市场都偏回归，那你的假设方向就该是反转；如果混杂，就挑同质的子集来做。

注意
    这是**描述统计的分组**，不是筛选"能赚钱的票"。
    一只票历史上偏趋势，不代表它接下来会趋势 —— 它只告诉你"该往哪个方向提假设"。

用法
    python -m tools.profile_all
    python -m tools.profile_all --min-years 3 --json profiles.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.profile import profile  # noqa: E402
from tools.validate import read_csv  # noqa: E402

NAME_RE = re.compile(r"^(us|cn|crypto)_(?P<sym>.+)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")
ORDER = {"趋势型": 0, "均值回归型": 1, "无明显结构": 2}


def _num(x):
    """只允许有限实数进入结果，其余（nan/inf/complex）记 None。"""
    if isinstance(x, complex) or x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f or abs(f) == float("inf") else round(f, 4)


def symbol_of(path):
    m = NAME_RE.match(Path(path).name)
    return (m.group("sym").upper(), m.group(1)) if m else (None, None)


def scan(csv_dir="data_cache", min_rows=120, min_years=2.0):
    """遍历缓存目录，逐个画像。同一标的有多份时保留最长的那份。"""
    best = {}
    for p in sorted(Path(csv_dir).glob("*.csv")):
        sym, market = symbol_of(p)
        if not sym:
            continue
        try:
            data = read_csv(p)
        except (OSError, ValueError):
            continue
        if len(data) < min_rows:
            continue
        r = profile(data)
        if not r.get("ok"):
            continue
        if r["years"] < min_years:
            continue
        if sym in best and best[sym]["rows"] >= r["rows"]:
            continue
        best[sym] = {
            "symbol": sym, "market": market, "file": p.name,
            "rows": r["rows"], "years": r["years"],
            "annual_return": r["annual_return"], "annual_vol": r["annual_vol"],
            "max_drawdown": r["max_drawdown"],
            "autocorr1": _num(r["autocorr1"]), "vr5": _num(r["vr5"]),
            "vr20": _num(r["vr20"]),
            "structure": r["structure"], "allowed_directions": r["allowed_directions"],
        }
    rows = list(best.values())
    rows.sort(key=lambda x: (ORDER.get(x["structure"], 9), -(x["vr20"] or 0)))
    summary = {k: sum(1 for r in rows if r["structure"] == k) for k in ORDER}
    return rows, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="批量结构画像")
    ap.add_argument("--csv-dir", default="data_cache")
    ap.add_argument("--min-rows", type=int, default=120)
    ap.add_argument("--min-years", type=float, default=2.0,
                    help="最短年数。低于 2 年时方差比极不稳定，默认剔除")
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args(argv)

    rows, summary = scan(args.csv_dir, args.min_rows, args.min_years)
    if not rows:
        print("没有可画像的标的（检查 data_cache 是否有 ≥120 行的 CSV）")
        return 1

    print(f"\n{'标的':<10}{'市场':<7}{'年数':>6}{'年化':>9}{'波动':>8}"
          f"{'回撤':>8}{'lag1':>8}{'VR20':>7}   结构")
    print("-" * 82)
    def col(x, width=8, nd=1, as_pct=False):
        """None 必须能安全打印：脏数据标的的年化收益/回撤可能是 None。"""
        if x is None:
            body = "—"
        elif as_pct:
            body = f"{x * 100:.{nd}f}%"
        else:
            body = f"{x:.{nd}f}"
        return f"{body:>{width}}"

    for r in rows[:args.top]:
        print(f"{r['symbol']:<10}{r['market']:<7}{r['years']:>6.1f}"
              f"{col(r['annual_return'], 9, 1, True)}{col(r['annual_vol'], 8, 1, True)}"
              f"{col(r['max_drawdown'], 8, 1, True)}{col(r['autocorr1'], 8, 3)}"
              f"{col(r['vr20'], 7, 2)}   {r['structure']}")
    if len(rows) > args.top:
        print(f"... 另有 {len(rows)-args.top} 只未显示")

    print("\n分布：" + "；".join(f"{k} {v}" for k, v in summary.items()))
    if summary.get("趋势型", 0) and summary.get("均值回归型", 0):
        print("→ 结构混杂：建议**分开做子集**，别把两种结构混在一个截面里")
    elif summary.get("均值回归型", 0) > summary.get("趋势型", 0):
        print("→ 这批票整体偏均值回归：假设方向优先考虑反转")
    elif summary.get("趋势型", 0) > summary.get("均值回归型", 0):
        print("→ 这批票整体偏趋势：假设方向优先考虑动量")
    else:
        print("→ 大多数无明显结构：这批票可能不适合做方向性假设")

    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "rows": rows},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())