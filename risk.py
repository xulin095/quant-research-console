import math

from config import CAPITAL, RF, TRADING_DAYS


def calculate_risk(data, trades, equity, state):
    values = equity["equity"]
    closed = trades[trades["status"] == "已平仓"] if len(trades) else trades
    daily = values.pct_change().dropna()
    excess = daily - RF / TRADING_DAYS
    deviation = excess.std(ddof=1)
    sharpe = None
    if len(excess) >= 2 and math.isfinite(deviation) and deviation > 1e-12:
        sharpe = excess.mean() / deviation * math.sqrt(TRADING_DAYS)
    return {
        "total": values.iloc[-1] / CAPITAL - 1,
        "annual": (values.iloc[-1] / CAPITAL) ** (TRADING_DAYS / (len(values) - 1)) - 1,
        "mdd": abs((values / values.cummax() - 1).min()),
        "sharpe": sharpe,
        "winrate": (closed["pnl"].gt(0).sum() / len(closed)) if len(closed) else None,
        "trades": len(closed),
        "benchmark": data["close"].iloc[-1] / data["close"].iloc[0] - 1,
        "sample_days": len(values),
        "buy_count": state["buy_count"],
        "sell_count": state["sell_count"],
    }
