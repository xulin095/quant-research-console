#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策层测试：规则表的单调性、无前视、成本真实扣除。"""

import unittest
from unittest import mock

from tools import decide as D


def rows_from(prices):
    return [{"date": "D%04d" % i, "open": p, "close": p} for i, p in enumerate(prices)]


def wave(n=700, regime=55, drift=0.005, noise=0.002, base=100.0, seed=5):
    """交替趋势段序列：会让均线真正穿越（有换手），策略也确实能赚一点。

    第一版用的是纯周期波动，结果均线从不穿越 —— 既没有交易成本可扣，
    也测不出"策略成本"这条。造测试数据时必须保证**真的有换手**。
    """
    import random
    rng = random.Random(seed)
    out, p = [], base
    for i in range(n):
        sign = 1 if (i // regime) % 2 == 0 else -1
        p *= (1 + sign * drift + rng.gauss(0, noise))
        out.append(p)
    return out

class TestRuleTable(unittest.TestCase):

    def test_no_history_no_position(self):
        self.assertEqual(D.target_weight(None, None), 0.0)

    def test_monotone_in_evidence(self):
        """证据越强，仓位只能不变或变大 —— 规则表不许出现反直觉的跳变。"""
        self.assertEqual(D.target_weight(0.50, -1.0), 0.0)
        self.assertEqual(D.target_weight(0.56, 0.10), 0.02)
        self.assertEqual(D.target_weight(0.62, 1.50), 0.05)

    def test_never_exceeds_cap(self):
        for hit in (0.9, 0.99, 1.0):
            self.assertLessEqual(D.target_weight(hit, 99.0), D.MAX_WEIGHT)


class TestNoLookAhead(unittest.TestCase):

    def test_weights_ignore_future(self):
        """把后半段改成暴涨，前半段的仓位序列必须一模一样。"""
        base = wave(700)
        altered = base[:500] + [base[499] * (1.03 ** (i + 1)) for i in range(200)]
        a = D.run(rows_from(base))
        b = D.run(rows_from(altered))
        self.assertEqual(a["weights"][:500], b["weights"][:500],
                         "前半段仓位变了 → 说明用了未来数据")


class TestCosts(unittest.TestCase):

    def test_higher_rebalance_cost_lowers_equity(self):
        rows = rows_from(wave(700))
        r0 = D.run(rows)
        self.assertGreater(r0["invested_ratio"], 0.5, "测试前提：必须先真的下注")
        base = r0["dec"]["final"]
        with mock.patch.object(D, "REBAL_FEE", 0.01):
            costly = D.run(rows)["dec"]["final"]
        self.assertLess(costly, base, "调仓成本没起作用")

    def test_higher_strategy_cost_lowers_equity(self):
        rows = rows_from(wave(700))
        base = D.run(rows)["dec"]["final"]
        with mock.patch.object(D, "STRAT_FEE", 0.02):
            costly = D.run(rows)["dec"]["final"]
        self.assertLess(costly, base)


class TestOutputs(unittest.TestCase):

    def test_three_curves_and_stats(self):
        res = D.run(rows_from(wave(700)))
        for key in ("dec", "strat", "bh"):
            self.assertIn(key, res)
            self.assertGreater(res[key]["final"], 0)
            self.assertGreaterEqual(res[key]["mdd"], 0)
            self.assertLessEqual(res[key]["mdd"], 1)
        self.assertTrue(0.0 <= res["invested_ratio"] <= 1.0)

    def test_short_data_never_invests(self):
        res = D.run(rows_from(wave(120)))
        self.assertEqual(res["avg_weight"], 0.0, "不足一年历史时必须不表态")


if __name__ == "__main__":
    unittest.main(verbosity=2)