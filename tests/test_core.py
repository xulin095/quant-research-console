import math
import unittest
from datetime import date, timedelta

import pandas as pd

from backtest import run_backtest
from config import CAPITAL
from data.base import DataFetcher
from data.registry import FETCHERS, get_fetcher
from indicators import add_indicators
from report import make_report
from risk import calculate_risk


class SyntheticFetcher(DataFetcher):
    market = "synthetic"

    def get_history(self, symbol, start, end):
        # 20 天平盘、10 天上涨、10 天下跌，产生严格金叉和死叉。
        closes = [100.0] * 20 + [110.0] * 10 + [80.0] * 10
        dates = [(date(2025, 1, 1) + timedelta(days=i)).isoformat()
                 for i in range(len(closes))]
        raw = pd.DataFrame({"date": dates, "open": closes,
                            "high": [x + 1 for x in closes],
                            "low": [x - 1 for x in closes],
                            "close": closes, "volume": [1000.0] * len(closes)})
        # 核心模块支持 40 日教学样本；正式入口的数据层仍强制 60 日。
        raw["symbol"] = symbol
        raw["market"] = self.market
        return raw


class CoreTests(unittest.TestCase):
    def test_injected_source_full_pipeline(self):
        FETCHERS["synthetic"] = SyntheticFetcher
        try:
            data = get_fetcher("synthetic").get_history("DEMO", "2025-01-01", "2025-02-10")
            enriched = add_indicators(data)
            trades, equity, state = run_backtest(enriched)
            metrics = calculate_risk(enriched, trades, equity, state)
            # 报告排版不依赖市场路由；合成市场只在测试中指定口径。
            from unittest.mock import patch
            with patch("report.adjustment", return_value="合成历史价格"):
                report = make_report(enriched, trades, metrics, state,
                                     "DEMO", "synthetic", "2025-01-01", "2025-02-10")
            self.assertIn("## 5. 风险提示", report)
            self.assertEqual(len(equity), 40)
            self.assertGreaterEqual(state["buy_count"], 1)
            self.assertGreaterEqual(state["sell_count"], 1)
        finally:
            del FETCHERS["synthetic"]

    def test_buy_shares_and_cash_by_hand(self):
        data = add_indicators(SyntheticFetcher().get_history("DEMO", "", ""))
        trades, equity, state = run_backtest(data)
        buy = trades.iloc[0]
        day = data[data["date"] == buy["buy_date"]].iloc[0]
        open_price = float(day["open"])
        expected_shares = math.floor(100000 / (open_price * 1.0008) * 1e6) / 1e6
        expected_cash = 100000 - expected_shares * open_price * 1.0008
        self.assertAlmostEqual(buy["shares"], expected_shares, delta=1e-6)
        self.assertAlmostEqual(buy["buy_price"] / open_price, 1.0008, delta=1e-6)
        buy_index = data.index[data["date"] == buy["buy_date"]][0]
        actual_cash = equity.iloc[buy_index]["equity"] - expected_shares * day["close"]
        self.assertAlmostEqual(actual_cash, expected_cash, delta=1e-6)

    def test_drawdown_and_sharpe_by_hand(self):
        data = pd.DataFrame({"close": [100, 110, 99, 120]})
        equity = pd.DataFrame({"equity": [100000, 110000, 99000, 120000]})
        empty = pd.DataFrame(columns=["status", "pnl"])
        state = {"buy_count": 0, "sell_count": 0}
        result = calculate_risk(data, empty, equity, state)
        self.assertAlmostEqual(result["mdd"], 0.1, delta=1e-6)
        daily = [0.1, -0.1, 120000 / 99000 - 1]
        excess = [r - 0.02 / 252 for r in daily]
        mean = sum(excess) / 3
        std = math.sqrt(sum((r - mean) ** 2 for r in excess) / 2)
        expected_sharpe = mean / std * math.sqrt(252)
        self.assertAlmostEqual(result["sharpe"], expected_sharpe, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
