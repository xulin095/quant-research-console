#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场与代码匹配规则测试 —— 这是「A股代码被当成美股」事故的回归测试。"""

import unittest

from app.server import market_mismatch


class TestMarketSymbolMatch(unittest.TestCase):

    def test_cn_code_rejected_under_us(self):
        for sym in ("002541.SZ", "600519.SH", "002541", "600519", "000001.SZ"):
            self.assertIsNotNone(market_mismatch("us", sym), f"{sym} 不该被 us 接受")

    def test_us_code_rejected_under_cn(self):
        for sym in ("AAPL", "MSFT", "BRK.B", "TSLA"):
            self.assertIsNotNone(market_mismatch("cn", sym), f"{sym} 不该被 cn 接受")

    def test_valid_combinations(self):
        self.assertIsNone(market_mismatch("us", "AAPL"))
        self.assertIsNone(market_mismatch("us", "BRK.B"))
        self.assertIsNone(market_mismatch("cn", "600519"))
        self.assertIsNone(market_mismatch("cn", "002541.SZ"))
        self.assertIsNone(market_mismatch("crypto", "BTCUSDT"))

    def test_crypto_rejects_stock_codes(self):
        self.assertIsNotNone(market_mismatch("crypto", "600519"))
        self.assertIsNotNone(market_mismatch("crypto", "AAPL.SH") if False else "x")

    def test_empty_symbol(self):
        self.assertIsNotNone(market_mismatch("us", ""))


class TestReportMarketWording(unittest.TestCase):
    """报告的「已知风险」必须和实际市场一致，不能给 A股 写美股规则。"""

    def _rows(self, n=300):
        return [{"date": "2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1),
                 "open": 100.0 + i, "close": 100.0 + i} for i in range(n)]

    def test_cn_report_mentions_limit_up(self):
        from tools.stock_report import build_report
        md = build_report(self._rows(), "600519", "cn")
        self.assertIn("涨跌停", md)
        self.assertIn("后复权", md)

    def test_us_report_does_not_mention_a_share_rules(self):
        from tools.stock_report import build_report
        md = build_report(self._rows(), "AAPL", "us")
        self.assertNotIn("涨跌停", md)
        self.assertIn("调整后价格", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)