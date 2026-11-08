#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按代码拉取的测试：参数校验与命令拼装（不联网）。"""

import unittest

from app import server as S


class TestFetchArgs(unittest.TestCase):

    def test_accepts_valid(self):
        self.assertIsNone(S.check_fetch_args("us", "AAPL", "2010-01-01", "2025-12-31"))
        self.assertIsNone(S.check_fetch_args("cn", "600519", "2015-01-01", "2025-12-31"))
        self.assertIsNone(S.check_fetch_args("us", "BRK.B", "2010-01-01", "2025-12-31"))

    def test_rejects_bad_market(self):
        self.assertIn("market", S.check_fetch_args("jp", "AAPL", "2010-01-01", "2025-12-31"))

    def test_rejects_bad_symbol(self):
        for sym in ("", "AA PL", "AAPL;rm", "../etc", "x" * 30):
            self.assertIsNotNone(S.check_fetch_args("us", sym, "2010-01-01", "2025-12-31"),
                                 f"{sym!r} 应当被拒绝")

    def test_rejects_bad_dates(self):
        self.assertIn("格式", S.check_fetch_args("us", "AAPL", "2010/01/01", "2025-12-31"))
        self.assertIn("早于", S.check_fetch_args("us", "AAPL", "2025-12-31", "2010-01-01"))

    def test_command_shape(self):
        cmd = S.build_fetch_args("cn", "600519", "2015-01-01", "2025-12-31")
        self.assertIn("tools.fetch_basket", cmd)
        self.assertIn("--market", cmd)
        self.assertIn("cn", cmd)
        self.assertIn("600519", cmd)
        self.assertNotIn("--symbols", " ".join(cmd[:1]))   # 参数在列表里，不是拼成一个字符串

    def test_fetch_symbol_rejects_before_running(self):
        """非法参数必须在校验阶段就返回，不能真的去启动子进程。"""
        r = S.fetch_symbol("AAPL", "jp", "2010-01-01", "2025-12-31")
        self.assertFalse(r["ok"])
        self.assertIn("market", r["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)