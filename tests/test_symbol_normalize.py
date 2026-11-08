#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代码写法归一化测试。

事故背景：用户输入 603345.SH 并选「市场=自动」，
后端没归一化，去找 `*_603345.SH_*.csv`，而实际文件叫 cn_603345_*.csv，
于是报「数据里没有 603345.SH」—— 数据明明在。
"""

import unittest

from app.server import normalize_symbol


class TestNormalize(unittest.TestCase):

    def test_cn_with_suffix(self):
        for raw in ("603345.SH", "603345.sh", "sh603345", "SH603345", "603345"):
            self.assertEqual(normalize_symbol(raw, "cn"), "603345", raw)

    def test_cn_without_market_hint(self):
        """不指定市场时也必须归一化 —— 这就是那次报告的 bug。"""
        for raw in ("603345.SH", "002541.SZ", "sh600519"):
            self.assertTrue(normalize_symbol(raw, None).isdigit(), raw)
            self.assertTrue(normalize_symbol(raw, "").isdigit(), raw)

    def test_us_symbols_untouched(self):
        for raw in ("AAPL", "brk.b", "MSFT"):
            self.assertEqual(normalize_symbol(raw, "us"), raw.upper())

    def test_crypto_untouched(self):
        self.assertEqual(normalize_symbol("btcusdt", "crypto"), "BTCUSDT")

    def test_index_not_mistaken(self):
        """000001 是上证指数/平安银行的前缀，必须保留 6 位（不能变成 1）。"""
        self.assertEqual(normalize_symbol("000001", "cn"), "000001")
        self.assertEqual(normalize_symbol("000001.SZ", "cn"), "000001")


if __name__ == "__main__":
    unittest.main(verbosity=2)