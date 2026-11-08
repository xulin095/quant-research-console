#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量画像测试：文件名解析、去重保留最长、结构分组。"""

import random
import tempfile
import unittest
from pathlib import Path

from tools import profile_all as PA


def write_csv(path, prices, market="us", sym="X"):
    lines = ["date,open,high,low,close,volume"]
    for i, p in enumerate(prices):
        d = "2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1)
        lines.append("%s,%.4f,%.4f,%.4f,%.4f,1000" % (d, p, p, p, p))
    path.write_text("\n".join(lines), encoding="utf-8")


def trend(n=700, seed=3, regime=60):
    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        s = 1 if (i // regime) % 2 == 0 else -1
        p *= (1 + s * 0.005 + rng.gauss(0, 0.004))
        out.append(p)
    return out


def revert(n=700, seed=5):
    rng = random.Random(seed)
    p, out, last = 100.0, [], 0.0
    for _ in range(n):
        r = -0.35 * last + rng.gauss(0, 0.01)
        last = r
        p *= (1 + r)
        out.append(p)
    return out


class TestSymbolOf(unittest.TestCase):

    def test_parses_market_and_symbol(self):
        sym, mk = PA.symbol_of("us_AAPL_2010-01-01_2025-12-31.csv")
        self.assertEqual((sym, mk), ("AAPL", "us"))
        sym2, mk2 = PA.symbol_of("cn_600519_2015-01-01_2025-12-31.csv")
        self.assertEqual((sym2, mk2), ("600519", "cn"))

    def test_rejects_odd_names(self):
        self.assertEqual(PA.symbol_of("random.csv"), (None, None))


class TestScan(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_groups_by_structure(self):
        write_csv(self.d / "us_TRENDX_2020-01-01_2025-12-31.csv", trend())
        write_csv(self.d / "us_REVERTX_2020-01-01_2025-12-31.csv", revert())
        rows, summary = PA.scan(self.d)
        self.assertEqual(len(rows), 2)
        by = {r["symbol"]: r["structure"] for r in rows}
        self.assertEqual(by["TRENDX"], "趋势型")
        self.assertEqual(by["REVERTX"], "均值回归型")
        self.assertEqual(summary["趋势型"], 1)
        self.assertEqual(summary["均值回归型"], 1)

    def test_keeps_longest_duplicate(self):
        write_csv(self.d / "us_DUP_2020-01-01_2021-01-01.csv", trend(300))
        write_csv(self.d / "us_DUP_2020-01-01_2025-12-31.csv", trend(700))
        rows, _ = PA.scan(self.d)
        self.assertEqual(len(rows), 1, "同一标的只应保留一条")
        self.assertEqual(rows[0]["rows"], 700)

    def test_short_files_skipped(self):
        write_csv(self.d / "us_SHORT_2020-01-01_2020-06-01.csv", trend(50))
        rows, _ = PA.scan(self.d, min_rows=120)
        self.assertEqual(rows, [])

    def test_min_years_filter(self):
        write_csv(self.d / "us_TRENDX_2020-01-01_2025-12-31.csv", trend(700))
        rows, _ = PA.scan(self.d, min_years=99)
        self.assertEqual(rows, [])


class TestJsonSafe(unittest.TestCase):
    """批量画像的结果必须能序列化成 JSON —— 真实数据里出现过负数取分数次幂返回 complex 的事故。"""

    def test_complex_and_dirty_prices_do_not_crash(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            prices, p = [], 100.0
            for i in range(600):
                p *= (1 + ((-1) ** i) * 0.05)     # 剧烈震荡，可能把价格推到 0 以下
                prices.append(p)
            write_csv(d / "us_WEIRD_2020-01-01_2025-12-31.csv", prices)
            rows, summary = PA.scan(d, min_years=0)
            json.dumps({"summary": summary, "rows": rows})   # 不能抛异常
            for r in rows:
                self.assertNotIsInstance(r["annual_return"], complex)

    def test_negative_start_price_safe(self):
        from tools.profile import profile as prof
        prices = [-10.0 + i for i in range(300)]              # 首价为负
        rows = [{"date": "D%04d" % i, "open": p, "close": p} for i, p in enumerate(prices)]
        r = prof(rows)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["annual_return"], "负首价下年化收益必须为 None，不能是复数")

if __name__ == "__main__":
    unittest.main(verbosity=2)