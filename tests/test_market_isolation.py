#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场隔离测试：同一个代码在不同市场下不能串数据。

这是真实踩到的坑：输入 A 股代码 600519、市场选 us，
拉取明明失败了，画像却照样出图 —— 因为缓存查找只按代码，没看市场。
"""

import tempfile
import unittest
from pathlib import Path

from tools.validate import find_cached


def touch(path, rows=100):
    path.write_text("date,open,high,low,close,volume\n" +
                    "\n".join("2020-01-01,1,1,1,1,1" for _ in range(rows)), encoding="utf-8")


class TestMarketIsolation(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        touch(self.d / "cn_600519_2010-01-01_2025-12-31.csv")
        touch(self.d / "us_AAPL_2010-01-01_2025-12-31.csv")

    def tearDown(self):
        self.td.cleanup()

    def test_market_filter(self):
        self.assertEqual(find_cached(self.d, "600519", "cn").name,
                         "cn_600519_2010-01-01_2025-12-31.csv")
        self.assertIsNone(find_cached(self.d, "600519", "us"),
                          "A股代码在 us 市场下不该找到任何缓存")
        self.assertIsNone(find_cached(self.d, "AAPL", "cn"))

    def test_no_market_falls_back_to_any(self):
        self.assertIsNotNone(find_cached(self.d, "600519"),
                             "不指定市场时允许返回任意市场的缓存（向后兼容）")

    def test_unknown_symbol(self):
        self.assertIsNone(find_cached(self.d, "NOTEXIST", "us"))

    def test_picks_longest_when_multiple(self):
        touch(self.d / "cn_600519_2020-01-01_2021-01-01.csv", rows=50)
        p = find_cached(self.d, "600519", "cn")
        self.assertIn("2010-01-01", p.name, "同一市场多份缓存应取行数最多的")


if __name__ == "__main__":
    unittest.main(verbosity=2)