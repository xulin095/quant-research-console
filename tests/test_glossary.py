#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语库测试：结构完整、不重复、关键术语都在、解释不能太短。"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_TERMS = ["夏普比率", "最大回撤", "基准", "样本外", "过拟合", "p 值",
             "置换检验", "幸存者偏差", "rank IC", "前复权"]


class TestGlossary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "glossary.json").read_text(encoding="utf-8"))
        cls.entries = cls.data["entries"]
        cls.terms = {e["term"] for e in cls.entries}

    def test_has_entries(self):
        self.assertGreaterEqual(len(self.entries), 30)

    def test_no_duplicate_terms(self):
        self.assertEqual(len(self.terms), len(self.entries), "术语重复了")

    def test_required_fields(self):
        for e in self.entries:
            self.assertTrue(e.get("term"), e)
            self.assertTrue(e.get("plain"), f"{e.get('term')} 缺 plain")

    def test_explanation_long_enough(self):
        """白话解释太短就等于没解释。"""
        for e in self.entries:
            self.assertGreaterEqual(len(e["plain"]), 20,
                                    f"{e['term']} 的解释只有 {len(e['plain'])} 字")

    def test_key_terms_present(self):
        missing = [t for t in KEY_TERMS if t not in self.terms]
        self.assertEqual(missing, [], f"缺少关键术语：{missing}")

    def test_no_jargon_only_explanation(self):
        """解释里不能只是把术语重复一遍。"""
        for e in self.entries:
            self.assertNotEqual(e["plain"].strip(), e["term"].strip(),
                                f"{e['term']} 的解释等于术语本身")


if __name__ == "__main__":
    unittest.main(verbosity=2)