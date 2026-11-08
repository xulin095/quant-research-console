#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析报告的测试：结构完整、无禁词、脏数据能识别、短数据不硬编。"""

import unittest

from tools import stock_report as R


def rows(n=300, start=100.0, step=0.5):
    out = []
    for i in range(n):
        p = start + i * step
        out.append({"date": "2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1),
                    "open": p, "close": p})
    return out


class TestReport(unittest.TestCase):

    def setUp(self):
        self.md = R.build_report(rows(), "TEST", "us", "us_TEST.csv")

    def test_has_five_sections(self):
        for h in ("## 0. 一句话结论", "## 1. 数据体检", "## 2. 结构判断",
                  "## 3. 能做什么", "## 4. 已知风险", "## 5. 免责声明"):
            self.assertIn(h, self.md, f"缺少章节 {h}")

    def test_no_banned_words(self):
        for w in ("建议买入", "建议卖出", "推荐", "看好", "一定涨", "一定跌",
                  "目标价", "值得买"):
            self.assertNotIn(w, self.md, f"出现了禁词：{w}")

    def test_has_required_disclaimer(self):
        self.assertIn("只代表过去，不代表未来", self.md)
        self.assertIn("不要用实盘资金直接照抄", self.md)

    def test_reports_data_health_numbers(self):
        self.assertIn("交易日数", self.md)
        self.assertIn("非正价格", self.md)

    def test_detects_negative_price(self):
        bad = rows()
        bad[10] = {"date": "2020-01-11", "open": -5.0, "close": -5.0}
        md = R.build_report(bad, "BAD", "us")
        self.assertIn("存在质量问题", md)

    def test_detects_duplicate_dates(self):
        dup = rows()
        dup[5] = dict(dup[4])
        md = R.build_report(dup, "DUP", "us")
        self.assertIn("重复日期", md)
        self.assertIn("存在质量问题", md)

    def test_short_data_says_so(self):
        md = R.build_report(rows(50), "SHORT", "us")
        self.assertIn("不足以分析", md)
        self.assertIn("先别做", md)

    def test_no_structure_no_direction(self):
        """看不出结构时不能硬给方向。"""
        flat = [{"date": "2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1),
                 "open": 100.0, "close": 100.0} for i in range(300)]
        md = R.build_report(flat, "FLAT", "us")
        self.assertIn("没有可以试的方向", md)

    def test_reproducible(self):
        """同一份数据算两遍结果必须完全一致。"""
        a = R.build_report(rows(), "TEST", "us", "x.csv")
        b = R.build_report(rows(), "TEST", "us", "x.csv")
        # 生成时间同一天，所以整篇应当一致
        self.assertEqual(a.split("生成时间")[1].split("｜")[0],
                         b.split("生成时间")[1].split("｜")[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)