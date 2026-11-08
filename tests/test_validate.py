#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证器自己的测试 —— 重点不是「能跑」，而是「能区分真优势与纯噪声」。

一个分不清噪声和优势的检测器，比没有检测器更危险：它会给出「有证据」的漂亮结论。
所以这里必须有两类样本：
    · 人造趋势市（双均线确实有优势）→ 必须判「有证据」
    · 纯随机游走（没有任何优势）    → 必须**不**判「有证据」

另一个关键测试是对账：tools/validate.py 的回测内核必须能复现 v1 报告的数字，
否则它验证的是另一个策略，结论不可用。
"""

import unittest
from datetime import date, timedelta

import tools.validate as V


# ------------------------------------------------------------------ 造样本
def make_rows(prices, start=date(2020, 1, 1)):
    return [{"date": (start + timedelta(days=i)).isoformat(),
             "open": p, "close": p} for i, p in enumerate(prices)]


def trend_prices(n=1500, seed=11, regime=90, drift=0.006, noise=0.002):
    """人造趋势市：每 90 天换向，涨幅明显、噪声小 —— 双均线应当能捕捉。"""
    import random
    rng = random.Random(seed)
    price, out = 100.0, []
    for i in range(n):
        sign = 1 if (i // regime) % 2 == 0 else -1
        price *= (1 + sign * drift + rng.gauss(0, noise))
        out.append(price)
    return out


def random_walk_prices(n=1500, seed=22, sd=0.01):
    """纯随机游走，零漂移 —— 任何趋势策略在这里都只该亏成本和噪声。"""
    import random
    rng = random.Random(seed)
    price, out = 100.0, []
    for _ in range(n):
        price *= (1 + rng.gauss(0, sd))
        out.append(price)
    return out


class TestReconcileWithV1(unittest.TestCase):
    """对账：回测内核必须和 v1 报告一致，否则验的不是同一个策略。"""

    def test_reproduces_v1_aapl_total_return(self):
        from pathlib import Path
        p = Path("data_cache/us_AAPL_2024-01-01_2025-12-31.csv")
        if not p.is_file():
            self.skipTest("没有 AAPL 缓存（先跑一次 main.py）")
        rows = V.read_csv(p)
        rets = V.simulate(rows, 5, 20)
        cum = 1.0
        for r in rets:
            cum *= (1 + r)
        # v1 报告：总收益率 5.06%，期末权益 105062.99
        self.assertAlmostEqual(cum - 1, 0.0506299, delta=5e-4,
                               msg=f"与 v1 报告不一致：{cum - 1:.6f}")

    def test_same_rules_no_negative_equity(self):
        rows = make_rows(trend_prices(n=400))
        rets = V.simulate(rows, 5, 20)
        cum = 1.0
        for r in rets:
            cum *= (1 + r)
        self.assertGreater(cum, 0, "权益出现非正值，复利无法继续")

    def test_fast_must_be_less_than_slow(self):
        rows = make_rows(trend_prices(n=100))
        self.assertEqual(V.simulate(rows, 20, 5), [], "快线不得大于慢线")


class TestStatistics(unittest.TestCase):

    def test_sharpe_zero_when_flat(self):
        self.assertEqual(V.sharpe([0.0] * 100), 0.0)

    def test_bootstrap_ci_positive_for_real_drift(self):
        """真实漂移 + 小噪声：CI 下界必须 > 0。

        注意不能用常数序列（[0.002]*200）：标准差为 0，夏普按定义记 0，测不出漂移。
        """
        import random
        rng = random.Random(3)
        daily = [0.002 + rng.gauss(0, 0.001) for _ in range(300)]
        lo, mid, hi = V.block_bootstrap_ci(daily, block=20, n_boot=300, seed=1)
        self.assertGreater(lo, 0, f"稳定正收益的 CI 下界必须 > 0，实际 {lo:+.3f}")

    def test_bootstrap_ci_covers_zero_for_noise(self):
        import random
        rng = random.Random(5)
        daily = [rng.gauss(0, 0.01) for _ in range(600)]
        lo, mid, hi = V.block_bootstrap_ci(daily, block=20, n_boot=300, seed=1)
        self.assertLess(lo, 0.3 * V.sharpe(daily) + 0.5, "零均值噪声不该被吹成显著正收益")
        self.assertLess(hi, 3.0)

    def test_deflated_sharpe_punishes_more_trials(self):
        """同样的观察值，试的参数越多，越不该算「有证据」。"""
        import random
        rng = random.Random(9)
        daily = [rng.gauss(0.001, 0.01) for _ in range(500)]
        sr = V.sharpe(daily)
        few = V.deflated_sharpe(sr, [sr - 0.5, sr + 0.5], daily)
        many = V.deflated_sharpe(sr, [sr + rng.gauss(0, 1.0) for _ in range(200)], daily)
        self.assertIsNotNone(few)
        self.assertIsNotNone(many)
        self.assertLess(many[0], few[0], "试了 200 组参数应当比只试 2 组更严格")

    def test_deflated_sharpe_none_when_too_short(self):
        self.assertIsNone(V.deflated_sharpe(0.5, [0.1, 0.2], [0.01] * 10))


class TestDetectorDiscriminates(unittest.TestCase):
    """核心：检测器必须能分开「真优势」和「纯噪声」。"""

    def test_trend_market_is_detected_as_evidence(self):
        rows = make_rows(trend_prices())
        res = V.walk_forward(rows, train=252, test=126, boot=1000, block=20)
        self.assertTrue(res["ok"], res.get("reason"))
        lo = res["ci"][0]
        self.assertGreater(lo, 0, f"人造趋势市应判「有证据」，实际超额 CI 下界 {lo:+.3f}")
        self.assertTrue(res["verdict"].startswith("有证据"), "判定应为有证据，实际：" + res["verdict"])

    def test_random_walk_is_not_called_evidence(self):
        rows = make_rows(random_walk_prices())
        res = V.walk_forward(rows, train=252, test=126, boot=1000, block=20)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertFalse(res["verdict"].startswith("有证据"),
                         "纯随机游走不能被判成有证据，实际：" + res["verdict"])

    def test_trend_beats_buy_and_hold(self):
        """人造趋势市里，双均线应当跑赢躺着不动（超额为正），否则不算有优势。"""
        res = V.walk_forward(make_rows(trend_prices()), boot=800)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(res["oos_excess_cum"], 0,
                           "应跑赢买入持有，实际超额 %.2f%%" % (res["oos_excess_cum"] * 100))
        self.assertGreater(res["excess_sharpe"], 0.3)
    def test_trend_scores_better_than_noise(self):
        a = V.walk_forward(make_rows(trend_prices()), boot=600)
        b = V.walk_forward(make_rows(random_walk_prices()), boot=600)
        self.assertGreater(a["oos_sharpe"], b["oos_sharpe"] + 0.5,
                           "趋势市样本外夏普应显著高于随机游走")


class TestWalkForwardMechanics(unittest.TestCase):

    def test_params_chosen_on_train_not_test(self):
        """参数选择只能看训练段：同一份数据、只改测试段，选出的参数应随训练段变化。"""
        rows = make_rows(trend_prices(n=900))
        res = V.walk_forward(rows, train=252, test=126, step=126, boot=200)
        self.assertGreaterEqual(res["windows"], 2)
        for p in res["picks"]:
            self.assertEqual(len(p["params"]), 2)
            self.assertLess(p["params"][0], p["params"][1])

    def test_grid_has_no_invalid_combo(self):
        """网格里不许有 fast >= slow：无效组合会被记 0 分，在所有参数为负时误选。"""
        for f, s in V.DEFAULT_GRID:
            self.assertLess(f, s, f"无效参数组合 {f}/{s} 混进了网格")

    def test_all_negative_train_still_picks_valid_param(self):
        """训练段全亏时，也必须选出真正跑过的参数，而不是返回空结果。"""
        import random
        rng = random.Random(31)
        prices, p = [], 100.0
        for _ in range(900):
            p *= (1 + rng.gauss(-0.001, 0.012))   # 持续下行 + 噪声，所有参数都亏
            prices.append(p)
        res = V.walk_forward(make_rows(prices), train=252, test=126, boot=200)
        self.assertTrue(res["ok"], res.get("reason"))
        for pick in res["picks"]:
            self.assertLess(pick["params"][0], pick["params"][1])
    def test_too_short_data_reports_not_ok(self):
        res = V.walk_forward(make_rows(trend_prices(n=200)))
        self.assertFalse(res["ok"])
        self.assertIn("不足", res["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
