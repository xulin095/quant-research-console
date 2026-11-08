from abc import ABC, abstractmethod

import pandas as pd

from config import MIN_ROWS


class DataError(Exception):
    pass


class DataFetcher(ABC):
    market = ""

    @abstractmethod
    def get_history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """返回标准 OHLCV 表。"""

    def standardize(self, frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
        columns = ["date", "open", "high", "low", "close", "volume"]
        if not set(columns).issubset(frame.columns):
            raise DataError("数据缺少必要的价格或成交量列")
        result = frame[columns].copy()
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        for column in columns[1:]:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result.dropna(subset=columns)
        result = result.drop_duplicates("date", keep="last").sort_values("date")
        result["symbol"] = symbol.upper()
        result["market"] = self.market
        result = result.reset_index(drop=True)
        if len(result) < MIN_ROWS:
            raise DataError("数据不足 60 个交易日")
        if (result[["open", "high", "low", "close"]] <= 0).any().any():
            raise DataError("价格数据包含非正数")
        if (result["volume"] < 0).any():
            raise DataError("成交量数据包含负数")
        return result


if __name__ == "__main__":
    print("标准数据列：date, open, high, low, close, volume, symbol, market")
