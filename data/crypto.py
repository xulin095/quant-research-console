from datetime import datetime, timezone
import sys

import pandas as pd

from config import PROXY
from data.base import DataError, DataFetcher


class CryptoFetcher(DataFetcher):
    market = "crypto"

    def get_history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            cursor = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1000)
            stop = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp() * 1000)
            records = []
            import requests                     # 延迟导入
            session = requests.Session()
            session.trust_env = False
            proxies = {"http": PROXY, "https": PROXY} if PROXY else None
            while cursor < stop:
                response = session.get("https://api.binance.com/api/v3/klines",
                                        params={"symbol": symbol.upper(), "interval": "1d",
                                                "startTime": cursor, "endTime": stop - 1,
                                                "limit": 1000}, timeout=15, proxies=proxies)
                response.raise_for_status()
                batch = response.json()
                if not isinstance(batch, list) or not batch:
                    break
                records.extend(batch)
                next_cursor = int(batch[-1][0]) + 86400000
                if next_cursor <= cursor:
                    raise DataError("加密行情分页没有前进")
                cursor = next_cursor
            session.close()
            frame = pd.DataFrame(records)
            if frame.empty:
                raise DataError("加密数据源没有返回数据")
            frame = frame[[0, 1, 2, 3, 4, 5]].copy()
            frame.columns = ["date", "open", "high", "low", "close", "volume"]
            frame["date"] = pd.to_datetime(frame["date"], unit="ms", utc=True).dt.strftime("%Y-%m-%d")
            return self.standardize(frame, symbol)
        except DataError:
            raise
        except Exception as error:
            raise DataError("加密数据拉取失败：" + str(error)) from error


if __name__ == "__main__":
    try:
        print(CryptoFetcher().get_history("BTCUSDT", "2024-01-01", "2025-12-31").head())
    except DataError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
