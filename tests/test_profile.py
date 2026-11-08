#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构画像的测试：趋势序列要判趋势、回归序列要判回归、噪声不硬套。"""

import random
import unittest

from tools import profile as P


def rows_from(prices):
    return [{"date": "D%05d" % i, "open": p, "close": p} for i, p in enumerate(prices)]


def trend_prices(n=800, seed=3, regime=60, drift=0.005, noise=0.004):
    """分段持续的趋势：每 60 天换一次方向。

    注意：恒定漂移 + 独立噪声**不会**产生正自相关（漂移是常数，收益之间没有记忆），
    那样测出来必然是「无明显结构」。真正的趋势结构来自「趋势会持续一段时间」，
    所以要造分段漂移。这个测试第一版就写错了，是它自己发现的。
    """
    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(n):
        sign = 1 if (i // regime) % 2 == 0 else -1
        p *= (1 + sign * drift + rng.gauss(0, noise))
        out.append(p)
    return out


def revert_prices(n=800, seed=5, k=0.35, noise=0.01):
    """AR(1) 负系数：涨了容易跌回来，均值回归结构。"""
    rng = random.Random(seed)
    p, out, last = 100.0, [], 0.0
    for _ in range(n):
        r = -k * last + rng.gauss(0, noise)
        last = r
        p *= (1 + r)
        out.append(p)
    return out


class TestGuards(unittest.TestCase):

    def test_too_short(self):
        r = P.profile(rows_from([100.0] * 50))
        self.assertFalse(r["ok"])
        self.assertIn("至少需要", r["reason"])

    def test_flat_series_no_structure(self):
        r = P.profile(rows_from([100.0] * 300))
        self.assertTrue(r["ok"])
        self.assertEqual(r["structure"], "无明显结构")
        self.assertEqual(r["allowed_directions"], [])


class TestDetectsStructure(unittest.TestCase):

    def test_trend_series_is_called_trend(self):
        r = P.profile(rows_from(trend_prices()))
        self.assertTrue(r["ok"])
        self.assertGreater(r["autocorr1"], 0)
        self.assertEqual(r["structure"], "趋势型", r["evidence"])
        self.assertIn("momentum", r["allowed_directions"])

    def test_reverting_series_is_called_reversal(self):
        r = P.profile(rows_from(revert_prices()))
        self.assertTrue(r["ok"])
        self.assertLess(r["autocorr1"], 0)
        self.assertEqual(r["structure"], "均值回归型", r["evidence"])
        self.assertIn("reversal", r["allowed_directions"])

    def test_structure_has_evidence_lines(self):
        r = P.profile(rows_from(trend_prices()))
        self.assertGreaterEqual(len(r["evidence"]), 2)

    def test_caveat_always_present(self):
        """画像必须始终带「这是历史描述、不是预测」的声明。"""
        for prices in (trend_prices(), revert_prices()):
            r = P.profile(rows_from(prices))
            self.assertIn("不是预测", r["caveat"])
            self.assertIn("审计", r["caveat"])


class TestStatistics(unittest.TestCase):

    def test_variance_ratio_near_one_for_noise(self):
        rng = random.Random(11)
        prices, p = [], 100.0
        for _ in range(2000):
            p *= (1 + rng.gauss(0, 0.01))
            prices.append(p)
        r = P.profile(rows_from(prices))
        self.assertTrue(0.6 < r["vr20"] < 1.5, f"噪声的 VR20 应接近 1，实际 {r['vr20']}")

    def test_max_drawdown_bounds(self):
        r = P.profile(rows_from(trend_prices()))
        self.assertGreaterEqual(r["max_drawdown"], 0)
        self.assertLess(r["max_drawdown"], 1)

    def test_autocorr_range(self):
        r = P.profile(rows_from(revert_prices()))
        self.assertTrue(-1 <= r["autocorr1"] <= 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)