#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""报告复核器 —— 完全不 import 项目代码，自己重算一遍，再和报告对账。

为什么必须「独立」
    如果复核脚本调用 tools/profile.py，那只是「用同一份可能会错的计算再算一遍」，
    错了也会一起错。这个文件从 CSV 读起，自己实现自相关、方差比、置换检验，
    用自己的随机种子（和主程序不同），最后和报告里的数字逐项对比。

它能验什么
    · 交易日数、区间、价格范围  → 和数据文件对账
    · lag1 自相关、VR20        → 独立重算，误差要求 < 0.01
    · 结构判定                  → 用独立置换检验判断，必须与报告一致
    （置换 z 值本身依赖随机种子，所以只比「判定」，不比小数点）

它不能验什么
    · 「这个方向将来能不能赚钱」—— 那是审计（HK 卡）的活，报告不下这个结论

用法
    python referee/profile_check.py --csv data_cache/cn_603345_2010-01-01_2025-12-31.csv
    python referee/profile_check.py --csv ... --report reports/603345_分析报告_2026-11-08.md
"""

import argparse
import csv
import math
import random
import re
import sys
from pathlib import Path

VERDICT_CODE = {
    "趋势型": "trend", "Trending": "trend",
    "均值回归型": "revert", "Mean-reverting": "revert",
    "无明显结构": "none", "No clear structure": "none",
}


def canon_verdict(text):
    """把中英文的判定说法归一到 trend / revert / none / None。"""
    if not text:
        return None
    t = text.strip()
    for k, v in VERDICT_CODE.items():
        if t.startswith(k):
            return v
    return t

SEED = 20261108       # 刻意与主程序不同，避免「同一个种子同一个错」
BOOT = 200


def load(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for r in rd:
            rows.append((r["date"][:10], float(r["open"]), float(r["close"])))
    return rows


def mean(x):
    return sum(x) / len(x)


def var(x, ddof=1):
    m = mean(x)
    return sum((v - m) ** 2 for v in x) / max(1, len(x) - ddof)


def corr(a, b):
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return None if da < 1e-12 or db < 1e-12 else num / (da * db)


def vr(rets, q):
    v1 = var(rets)
    if v1 <= 1e-18:
        return None
    agg = [sum(rets[i:i + q]) for i in range(len(rets) - q + 1)]
    return var(agg) / (q * v1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="报告独立复核（不调用项目代码）")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    rows = load(args.csv)
    closes = [r[2] for r in rows]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))
            if closes[i - 1] > 0 and closes[i] > 0]
    ac1 = corr(rets[1:], rets[:-1])
    v20 = vr(rets, 20)

    # 独立置换检验（自己的种子）
    rng = random.Random(SEED)
    null = []
    buf = list(rets)
    for _ in range(BOOT):
        rng.shuffle(buf)
        v = vr(buf, 20)
        if v is not None:
            null.append(v)
    z = None
    if null and v20 is not None:
        sd = math.sqrt(var(null))
        if sd > 1e-12:
            z = (v20 - mean(null)) / sd

    ac_thr = 2 / math.sqrt(len(rets))
    if z is not None and z > 2 and ac1 > ac_thr:
        verdict = "趋势型"
    elif z is not None and z < -2 and ac1 < -ac_thr:
        verdict = "均值回归型"
    else:
        verdict = "无明显结构"

    print(f"\n独立复核：{Path(args.csv).name}")
    print(f"  交易日 {len(rows)}   区间 {rows[0][0]} → {rows[-1][0]}")
    print(f"  价格范围 {min(closes):.2f} – {max(closes):.2f}")
    print(f"  lag1 自相关 {ac1:+.4f}（阈值 ±{ac_thr:.3f}）")
    print(f"  VR20 {v20:.3f}")
    print(f"  置换 z {z:+.2f}（自算，种子 {SEED}，{BOOT} 次）")
    print(f"  ▶ 独立判定：{verdict}")

    if not args.report:
        print("\n（没给 --report，只做独立计算）")
        return 0

    rp = Path(args.report)
    if not rp.is_file():
        print(f"\n找不到报告：{rp}")
        return 1
    text = rp.read_text(encoding="utf-8", errors="replace")

    def grab(label):
        m = re.search(r"\|\s*" + label + r"\s*\|\s*([-\d.]+)", text)
        return float(m.group(1)) if m else None

    rep_ac = grab("lag1 自相关") or grab("lag1 autocorrelation")
    rep_vr = grab("VR20")
    m = (re.search(r"\*\*判定：([^*]+)\*\*", text)
         or re.search(r"\*\*Verdict: ([^*]+)\*\*", text))
    rep_verdict = m.group(1).strip() if m else None

    print("\n与报告对账：")
    ok = True
    for name, mine, theirs, tol in (("lag1 自相关", ac1, rep_ac, 0.01),
                                    ("VR20", v20, rep_vr, 0.01)):
        if theirs is None:
            print(f"  {name}: 报告里没找到（跳过）")
            continue
        diff = abs(mine - theirs)
        good = diff <= tol
        ok &= good
        print(f"  {name}: 报告 {theirs:+.4f} / 复算 {mine:+.4f}  差 {diff:.4f}  "
              f"{'✓' if good else '✗ 超出容差'}")
    if rep_verdict:
        good = canon_verdict(rep_verdict) == canon_verdict(verdict)
        ok &= good
        print(f"  结构判定: 报告「{rep_verdict}」/ 复算「{verdict}」  {'✓' if good else '✗ 不一致'}")
    else:
        print("  结构判定: 报告里没找到")

    print("\n" + ("结论：报告与独立复算一致，可信" if ok else "结论：有对不上的地方，报告不可信"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())