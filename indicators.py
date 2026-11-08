import math

import pandas as pd

from config import FAST, LONG, MACD, RSI_N, SLOW, TRADING_DAYS, VOL_N


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    close = result["close"]
    result["ma5"] = close.rolling(FAST).mean()
    result["ma20"] = close.rolling(SLOW).mean()
    result["ma60"] = close.rolling(LONG).mean()
    fast_ema = close.ewm(span=MACD[0], adjust=False).mean()
    slow_ema = close.ewm(span=MACD[1], adjust=False).mean()
    result["dif"] = fast_ema - slow_ema
    result["dea"] = result["dif"].ewm(span=MACD[2], adjust=False).mean()
    # 设计口径的柱值是差的两倍。
    result["macd_hist"] = 2 * (result["dif"] - result["dea"])
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / RSI_N, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / RSI_N, adjust=False).mean()
    result["rsi14"] = 100 - 100 / (1 + gain / loss)
    result.loc[loss == 0, "rsi14"] = 100
    result.loc[:RSI_N - 1, "rsi14"] = float("nan")
    result["ret"] = close.pct_change()
    result["vol20"] = result["ret"].rolling(VOL_N).std(ddof=1) * math.sqrt(TRADING_DAYS)
    return result


if __name__ == "__main__":
    from data.us import USFetcher
    print(add_indicators(USFetcher().get_history("AAPL", "2024-01-01", "2025-12-31")).tail(3).to_string(index=False))
