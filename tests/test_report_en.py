#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""English report tests: same numbers, English prose, no advice language."""

import re
import unittest

from tools import stock_report as R


def rows(n=300):
    return [{"date": "2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1),
             "open": 100.0 + i * 0.5, "close": 100.0 + i * 0.5} for i in range(n)]


class TestEnglishReport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.en = R.build_report(rows(), "TEST", "us", "us_TEST.csv", lang="en")
        cls.zh = R.build_report(rows(), "TEST", "us", "us_TEST.csv", lang="zh")

    def test_five_sections(self):
        for h in ("## 0. Bottom line", "## 1. Data health",
                  "## 2. Structural verdict", "## 3. What is worth testing",
                  "## 4. Known risks", "## 5. Disclaimer"):
            self.assertIn(h, self.en, f"missing section {h}")

    def test_no_chinese_in_english_report(self):
        """英文本不该夹中文（结构名、单位、风险段都算）。"""
        body = "\n".join(l for l in self.en.splitlines() if not l.startswith("#"))
        cn = re.findall(r"[\u4e00-\u9fff]+", body)
        self.assertEqual(cn, [], f"英文报告里出现中文：{cn[:8]}")

    def test_no_advice_language(self):
        lowered = self.en.lower()
        for bad in ("buy recommendation", "sell recommendation", "target price",
                    "guaranteed", "will rise", "will fall", "you should buy"):
            self.assertNotIn(bad, lowered, f"report contains advice language: {bad}")

    def test_uses_english_structure_label(self):
        self.assertIn("Verdict:", self.en)
        self.assertNotIn("判定：", self.en)

    def test_same_numbers_in_both_languages(self):
        """同一份数据，两种语言的数字必须一致。"""
        num = r"[-+]?\d+\.\d+"
        a = re.findall(num, self.en)
        b = re.findall(num, self.zh)
        self.assertEqual(sorted(a), sorted(b), "中英文报告的数字不一致")

    def test_filename_per_language(self):
        self.assertTrue(R.report_filename("600519", "zh").endswith(".md"))
        self.assertIn("_分析报告_", R.report_filename("600519", "zh"))
        self.assertIn("_report_", R.report_filename("600519", "en"))

    def test_short_data_english(self):
        md = R.build_report(rows(50), "SHORT", "us", lang="en")
        self.assertIn("not enough to analyse", md)
        self.assertIn("do not trade it", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)