import pandas as pd
import yfinance as yf
import io
import sys
from contextlib import redirect_stderr

from data.base import DataError, DataFetcher


class USFetcher(DataFetcher):
    market = "us"

    def get_history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            # 第三方库可能直接向 stderr 打英文限流信息；入口统一输出一行中文。
            with redirect_stderr(io.StringIO()):
                raw = yf.download(symbol.upper(), start=start, end=end,
                                  auto_adjust=True, progress=False, threads=False)
            if raw.empty:
                raise DataError("美股数据源没有返回数据，可能遇到 Yahoo 限流")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.reset_index().rename(columns=str.lower)
            return self.standardize(raw, symbol)
        except DataError:
            raise
        except Exception as error:
            raise DataError("美股数据拉取失败：" + str(error)) from error


if __name__ == "__main__":
    try:
        print(USFetcher().get_history("AAPL", "2024-01-01", "2025-12-31").head())
    except DataError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
