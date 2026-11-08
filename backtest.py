import math

import pandas as pd

from config import CAPITAL, FAST, FEE, SLIP, SLOW


def next_signal(frame, index, shares):
    if index == 0:
        return None
    row = frame.iloc[index]
    prev = frame.iloc[index - 1]
    if pd.isna(row["ma5"]) or pd.isna(prev["ma20"]):
        return None
    if shares == 0 and row["ma5"] > row["ma20"] and prev["ma5"] <= prev["ma20"]:
        return "buy"
    if shares > 0 and row["ma5"] <= row["ma20"] and prev["ma5"] > prev["ma20"]:
        return "sell"
    return None


def run_backtest(frame: pd.DataFrame):
    cash = float(CAPITAL)
    shares = 0.0
    entry = None
    pending = None
    trades = []
    equity = []
    buy_count = 0
    sell_count = 0
    for i, row in frame.reset_index(drop=True).iterrows():
        if pending == "buy":
            price = float(row["open"])
            # 买入总成本含双项费率，股数截断至百万分之一股。
            shares = math.floor(cash / (price * (1 + FEE + SLIP)) * 1e6) / 1e6
            cost = shares * price * (1 + FEE + SLIP)
            cash -= cost
            entry = {"buy_date": row["date"], "buy_price": price * (1 + FEE + SLIP),
                     "shares": shares, "cost": cost}
            buy_count += 1
        elif pending == "sell":
            price = float(row["open"])
            proceeds = shares * price * (1 - FEE - SLIP)
            cash += proceeds
            trade = dict(entry)
            trade.update(sell_date=row["date"], sell_price=price * (1 - FEE - SLIP),
                         proceeds=proceeds, pnl=proceeds - entry["cost"],
                         ret=proceeds / entry["cost"] - 1, status="已平仓")
            trades.append(trade)
            shares, entry = 0.0, None
            sell_count += 1
        pending = None
        equity.append({"date": row["date"], "equity": cash + shares * float(row["close"])})
        pending = next_signal(frame, i, shares)
    if entry is not None:
        trade = dict(entry)
        trade.update(sell_date=None, sell_price=None, proceeds=None,
                     pnl=None, ret=None, status="期末持仓")
        trades.append(trade)
    return pd.DataFrame(trades), pd.DataFrame(equity), {"cash": cash,
            "shares": shares, "buy_count": buy_count, "sell_count": sell_count}


if __name__ == "__main__":
    from data.us import USFetcher
    from indicators import add_indicators
    from risk import calculate_risk
    data = add_indicators(USFetcher().get_history("AAPL", "2024-01-01", "2025-12-31"))
    trades, equity, state = run_backtest(data)
    print(trades.to_string(index=False))
    print(equity.iloc[[0, -1]].to_string(index=False))
    print(calculate_risk(data, trades, equity, state))
