#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究仪器的测试：卡指纹稳定性、记账不丢、判据只看数字。"""

import unittest

from tools import audit as A


class TestCardHash(unittest.TestCase):

    def test_hash_ignores_description(self):
        a = {"id": "X", "kind": "cross_section", "lookback": 5, "mechanism": "说法一"}
        b = {"id": "X", "kind": "cross_section", "lookback": 5, "mechanism": "完全不同的说法"}
        self.assertEqual(A.card_hash(a), A.card_hash(b), "描述文字不该影响指纹")

    def test_hash_changes_with_params(self):
        a = {"id": "X", "kind": "cross_section", "lookback": 5}
        b = {"id": "X", "kind": "cross_section", "lookback": 6}
        self.assertNotEqual(A.card_hash(a), A.card_hash(b), "改了参数必须换指纹")


class TestVerdict(unittest.TestCase):

    def test_cross_section_rules(self):
        ok, _ = A.verdict_cross_section({"ic_ci_low": 0.01, "excess_t": 2.5})
        self.assertTrue(ok)
        ok, _ = A.verdict_cross_section({"ic_ci_low": -0.01, "excess_t": 2.5})
        self.assertFalse(ok, "IC 区间跨 0 必须不通过")
        ok, _ = A.verdict_cross_section({"ic_ci_low": 0.01, "excess_t": 1.9})
        self.assertFalse(ok, "超额 t 不够必须不通过")

    def test_time_series_rules(self):
        self.assertTrue(A.verdict_time_series({"excess_ci_low": 0.001})[0])
        self.assertFalse(A.verdict_time_series({"excess_ci_low": -0.001})[0])
        self.assertFalse(A.verdict_time_series({})[0])


class TestRegistry(unittest.TestCase):

    def test_count_zero_when_missing(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            A.REGISTRY = Path(td) / "registry.jsonl"
            self.assertEqual(A.count_registry(), 0)
            A.append_registry({"id": "T1", "verdict": "FAIL"})
            self.assertEqual(A.count_registry(), 1)
            A.append_registry({"id": "T2", "verdict": "PASS"})
            self.assertEqual(A.count_registry(), 2, "记账必须追加而不是覆盖")


if __name__ == "__main__":
    unittest.main(verbosity=2)