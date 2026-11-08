#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台后端测试：卡片校验、冻结护栏、账本统计。不起服务器、不跑回测。"""

import json
import tempfile
import unittest
from pathlib import Path

from app import server as S


class TestCardValidation(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        S.CARDS = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def good(self, **kw):
        c = {"id": "HK-900", "kind": "cross_section", "direction": "reversal",
             "lookback": 5, "top_n": 3, "mechanism": "测试机制", "claims": "测试"}
        c.update(kw)
        return c

    def test_save_ok(self):
        S.save_card(self.good())
        self.assertTrue((S.CARDS / "HK-900.json").exists())

    def test_missing_field_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            S.save_card(self.good(mechanism=""))
        self.assertIn("缺少字段", str(ctx.exception))

    def test_bad_lookback_rejected(self):
        for lb in (0, 13, -1):
            with self.assertRaises(ValueError):
                S.save_card(self.good(lookback=lb))

    def test_bad_direction_rejected(self):
        with self.assertRaises(ValueError):
            S.save_card(self.good(direction="both"))

    def test_frozen_params_cannot_change(self):
        """跑过的卡改参数必须被拒绝 —— 这是防 p-hacking 的机械护栏。"""
        S.save_card(self.good())
        with self.assertRaises(ValueError) as ctx:
            S.save_card(self.good(lookback=6))
        self.assertIn("冻结", str(ctx.exception))

    def test_new_id_allows_new_params(self):
        S.save_card(self.good())
        S.save_card(self.good(id="HK-901", lookback=6))
        self.assertTrue((S.CARDS / "HK-901.json").exists())


class TestRegistryRead(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        S.REGISTRY = Path(self.td.name) / "registry.jsonl"

    def tearDown(self):
        self.td.cleanup()

    def test_empty(self):
        r = S.read_registry()
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["pass_rate"], 0.0)

    def test_counts_and_pass_rate(self):
        rows = [{"id": "A", "verdict": "FAIL"}, {"id": "B", "verdict": "PASS"},
                {"id": "C", "verdict": "FAIL"}]
        S.REGISTRY.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        r = S.read_registry()
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["passed"], 1)
        self.assertAlmostEqual(r["pass_rate"], 1 / 3, places=3)
        self.assertEqual(r["entries"][0]["id"], "C")   # 最新的在最前

    def test_bad_line_skipped(self):
        S.REGISTRY.write_text('{"id":"A","verdict":"FAIL"}\n不是json\n', encoding="utf-8")
        self.assertEqual(S.read_registry()["total"], 1)


class TestStatus(unittest.TestCase):

    def test_shape(self):
        d = S.data_status()
        for k in ("cache_files", "universe_size", "held_out_from"):
            self.assertIn(k, d)
        self.assertIsInstance(d["cache_files"], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)