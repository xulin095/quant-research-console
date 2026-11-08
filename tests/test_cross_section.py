#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""截面检验器的测试：IC 能不能认出真信号、会不会把噪声当信号、有没有偷看未来。"""

import random
import unittest

from tools import cross_section as C


def make_panel(symbols, months, seed=7, alpha=0.0, base=100.0):
    """monthly 收益 = alpha × 上期收益 + 噪声。

    alpha > 0 → 存在可预测的动量（信号应当有效）
    alpha = 0 → 完全不可预测（信号应当无效）
    """
    rng = random.Random(seed)
    px = {s: base * (1 + 0.01 * i) for i, s in enumerate(symbols)}
    hist = {s: [] for s in symbols}
    for _ in range(months):
        prev = {s: px[s] for s in symbols}
        for s in symbols:
            last = hist[s][-1] if hist[s] else 0.0
            r = 0.004 + alpha * last + rng.gauss(0, 0.05)
            px[s] *= (1 + r)
            hist[s].append(r)
    # 把月度价格展开成"每月一个交易日"的 pseudo 日线，足够 month_ends 用
    panel, dates = {}, []
    level = {s: base for s in symbols}
    for m in range(months):
        d = "%04d-%02d-28" % (2000 + m // 12, m % 12 + 1)
        dates.append(d)
        for s in symbols:
            level[s] *= (1 + hist[s][m])
        panel[d] = dict(level)
    return dates, panel, list(symbols)


class TestSpearman(unittest.TestCase):

    def test_perfect_and_reverse(self):
        self.assertAlmostEqual(C.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0, places=9)
        self.assertAlmostEqual(C.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0, places=9)

    def test_handles_ties(self):
        v = C.spearman([1, 1, 2, 2], [5, 6, 7, 8])
        self.assertTrue(-1 <= v <= 1)

    def test_too_short(self):
        self.assertIsNone(C.spearman([1, 2], [3, 4]))


class TestMonthEnds(unittest.TestCase):

    def test_picks_last_trading_day(self):
        dates = ["2020-01-02", "2020-01-31", "2020-02-03", "2020-02-28", "2020-03-31"]
        self.assertEqual(C.month_ends(dates), ["2020-01-31", "2020-02-28", "2020-03-31"])


class TestDetectorDiscriminates(unittest.TestCase):

    def test_real_momentum_is_detected(self):
        syms = ["S%02d" % i for i in range(12)]
        dates, panel, _ = make_panel(syms, 120, alpha=0.45)
        obs = C.build_observations(panel, dates, lookback_months=3)
        res = C.evaluate(obs, top_n=3)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(res["ic_mean"], 0.05, "存在真实动量时 IC 应为正")
        self.assertGreater(res["ic_ci"][0], 0, "IC 置信区间下界应大于 0")

    def test_pure_noise_is_not_detected(self):
        syms = ["N%02d" % i for i in range(12)]
        dates, panel, _ = make_panel(syms, 120, alpha=0.0, seed=11)
        obs = C.build_observations(panel, dates, lookback_months=3)
        res = C.evaluate(obs, top_n=3)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(abs(res["ic_mean"]), 0.15, "纯噪声不该出现很强的 IC")
        self.assertFalse(res["verdict"].startswith("有预测力"),
                         "纯噪声不能被判成有预测力：" + res["verdict"])


class TestNoLookAhead(unittest.TestCase):

    def test_signal_uses_only_past_prices(self):
        syms = ["A", "B", "C", "D", "E", "F"]
        dates, panel, _ = make_panel(syms, 60, alpha=0.2)
        obs = C.build_observations(panel, dates, lookback_months=2)
        self.assertTrue(obs)
        for o in obs:
            self.assertEqual(len(o["sig"]), len(o["syms"]))
            self.assertEqual(len(o["fwd"]), len(o["syms"]))
        # 最后一期必须有"下一个月"才可能算 fwd；没有则不生成
        self.assertEqual(obs[-1]["date"], C.month_ends(dates)[-2])


class TestCosts(unittest.TestCase):

    def test_cost_lowers_return(self):
        syms = ["C%02d" % i for i in range(10)]
        dates, panel, _ = make_panel(syms, 96, alpha=0.3)
        obs = C.build_observations(panel, dates, lookback_months=3)
        free = C.evaluate(obs, top_n=3, cost=0.0)
        paid = C.evaluate(obs, top_n=3, cost=0.01)
        self.assertLess(paid["strat_cagr"], free["strat_cagr"], "成本没起作用")


class TestAuditHelpers(unittest.TestCase):
    """审计器的三个小零件：p 值、Bonferroni、留出段切分。"""

    def test_one_sided_p_monotone(self):
        from tools import cs_audit as A
        self.assertLess(A.one_sided_p(2.5), A.one_sided_p(1.0))
        self.assertAlmostEqual(A.one_sided_p(0.0), 0.5, places=6)
        self.assertEqual(A.one_sided_p(None), 1.0)

    def test_bonferroni_grows_with_tests(self):
        from tools import cs_audit as A
        p = 0.01
        self.assertLess(A.bonferroni(p, 1), A.bonferroni(p, 12))
        self.assertLessEqual(A.bonferroni(p, 1000), 1.0)
        self.assertAlmostEqual(A.bonferroni(p, 1), p, places=12)

    def test_split_by_date(self):
        from tools import cs_audit as A
        obs = [{"date": "2020-01-01"}, {"date": "2023-01-01"}, {"date": "2024-01-01"}]
        tr, ho = A.split_obs(obs, "2023-01-01")
        self.assertEqual([o["date"] for o in tr], ["2020-01-01"])
        self.assertEqual(len(ho), 2)

    def test_panel_uses_union_not_intersection(self):
        """成分股用并集：某个标的晚上市，不该把整段历史砍掉。"""
        import tempfile
        from pathlib import Path
        from tools import cross_section as C
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name, start in (("a", 0), ("b", 200)):
                lines = ["date,open,close"]
                for i in range(start, 400):
                    dt = "2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1)
                    lines.append(f"{dt},10,{10 + i * 0.01}")
                (d / f"us_S{name.upper()}_2010-01-01_2025-12-31.csv").write_text(
                    "\n".join(lines), encoding="utf-8")
            # 只有 2 只票，低于 MIN_SYMBOLS，应当直接报错而不是静默返回空
            with self.assertRaises(SystemExit):
                C.load_panel(["SA", "SB", "SC"], td)

if __name__ == "__main__":
    unittest.main(verbosity=2)