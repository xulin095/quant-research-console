import akshare as ak
import pandas as pd
import sys

from data.base import DataError, DataFetcher


class CNFetcher(DataFetcher):
    market = "cn"

    def get_history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            raw = ak.stock_zh_a_hist(symbol=symbol.upper(), period="daily",
                                     start_date=start.replace("-", ""),
                                     end_date=end.replace("-", ""), adjust="qfq")
            raw = raw.rename(columns={"日期": "date", "开盘": "open", "最高": "high",
                                      "最低": "low", "收盘": "close", "成交量": "volume"})
            raw["date"] = pd.to_datetime(raw["date"]).dt.strftime("%Y-%m-%d")
            # AKShare 的成交量为手；标准表统一记股。
            raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce") * 100
            raw = raw[raw["date"] < end]
            return self.standardize(raw, symbol)
        except DataError:
            raise
        except Exception as error:
            raise DataError("A 股数据拉取失败：" + str(error)) from error


if __name__ == "__main__":
    try:
        print(CNFetcher().get_history("600519", "2024-01-01", "2025-12-31").head())
    except DataError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
