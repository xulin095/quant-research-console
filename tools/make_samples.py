#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""生成示例数据 —— 用来把这个系统跑一遍，看清它在不同结构下的表现。

三份"干净"样本（结构已知，用来验证画像是否判得准）：
    TRENDFAKE   分段趋势：每 60 天换向，漂移 ±0.5%     → 应当判「趋势型」
    REVERTFAKE  AR(1) 负系数 −0.35                       → 应当判「均值回归型」
    RANDWALK    纯随机游走，零漂移                       → 应当判「无明显结构」

两份"脏"样本（用来验证上传校验是否真的会拦）：
    BROKEN_missing_volume   少了 volume 列               → 应当被拒：缺少列
    BROKEN_negative_price   混入负价格                   → 应当丢弃非正价行

注意：这些是**合成数据**，只用于验证工具链，没有任何市场含义。
用法
    python -m tools.make_samples
    → 生成到 samples/ 目录，然后在研究台「数据」页拖进去上传
"""

import random
import sys
from datetime import date, timedelta
from pathlib import Path

OUT = Path("samples")


def weekdays(n, start=date(2020, 1, 2)):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def ohlc_from_closes(closes, seed=1):
    """由收盘序列造出合理的开高低：开盘跳空、日内振幅。"""
    rng = random.Random(seed)
    rows = []
    prev = closes[0]
    for i, c in enumerate(closes):
        gap = rng.gauss(0, 0.002) if i else 0.0
        o = prev * (1 + gap)
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.004)))
        vol = int(abs(rng.gauss(2_000_000, 600_000))) + 100_000
        rows.append((o, hi, lo, c, vol))
        prev = c
    return rows


def gen_trend(n=1500, seed=21, regime=60, drift=0.005, noise=0.004):
    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        sign = 1 if (i // regime) % 2 == 0 else -1
        p *= (1 + sign * drift + rng.gauss(0, noise))
        out.append(p)
    return out


def gen_revert(n=1500, seed=22, k=0.35, noise=0.010):
    rng = random.Random(seed)
    p, out, last = 100.0, [], 0.0
    for _ in range(n):
        r = -k * last + rng.gauss(0, noise)
        last = r
        p *= (1 + r)
        out.append(p)
    return out


def gen_random(n=1500, seed=23, sd=0.012):
    rng = random.Random(seed)
    p, out = 100.0, []
    for _ in range(n):
        p *= (1 + rng.gauss(0, sd))
        out.append(p)
    return out


def write(path, dates, rows, include_volume=True):
    head = "date,open,high,low,close,volume" if include_volume else "date,open,high,low,close"
    lines = [head]
    for d, (o, h, l, c, v) in zip(dates, rows):
        base = f"{d.isoformat()},{o:.2f},{h:.2f},{l:.2f},{c:.2f}"
        lines.append(base + (f",{v}" if include_volume else ""))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    OUT.mkdir(exist_ok=True)
    n = 1500
    dates = weekdays(n)

    specs = [
        ("TRENDFAKE", gen_trend(n), "分段趋势（每 60 天换向）"),
        ("REVERTFAKE", gen_revert(n), "AR(1) 负系数（涨了容易跌回）"),
        ("RANDWALK", gen_random(n), "纯随机游走（无结构）"),
    ]
    made = []
    for name, closes, desc in specs:
        rows = ohlc_from_closes(closes, seed=hash(name) % 1000)
        p = write(OUT / f"{name}_2020-01-01_2025-12-31.csv", dates, rows)
        made.append((p.name, desc, len(rows)))

    # 脏样本 1：缺 volume 列
    rows = ohlc_from_closes(gen_trend(300), seed=7)
    p1 = write(OUT / "BROKEN_missing_volume.csv", weekdays(300), rows, include_volume=False)
    made.append((p1.name, "缺 volume 列（应被拒）", 300))

    # 脏样本 2：混入负价格
    rows = list(ohlc_from_closes(gen_trend(300), seed=8))
    rows[100] = (-5.0, 1.0, -6.0, -5.0, 100000)     # 一行负价
    p2 = write(OUT / "BROKEN_negative_price.csv", weekdays(300), rows)
    made.append((p2.name, "含 1 行负价（应丢弃该行）", 300))

    print(f"已生成到 {OUT.resolve()}\\")
    for name, desc, cnt in made:
        size = (OUT / name).stat().st_size
        print(f"  {name:<38} {cnt:>5} 行  {size/1024:>6.1f} KB   {desc}")
    print("\n下一步：打开研究台 →「数据」页 → 把文件拖进去 → 市场选 us → 代码填文件名前缀")
    return 0


if __name__ == "__main__":
    sys.exit(main())