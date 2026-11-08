import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from config import MIN_ROWS
from data.base import DataError
from data.registry import FETCHERS, get_fetcher
from indicators import add_indicators
from backtest import run_backtest
from risk import calculate_risk
from report import make_report, write_report


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("参数错误：" + message)


def parse_args(argv=None):
    parser = ChineseParser(description="历史行情分析与回测")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)
    if args.market not in FETCHERS:
        raise ValueError("市场无效；可用市场：" + ", ".join(FETCHERS))
    if not args.symbol.isalnum():
        raise ValueError("代码只能包含字母和数字")
    try:
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    except ValueError as error:
        raise ValueError("日期须为 YYYY-MM-DD") from error
    if start >= end:
        raise ValueError("开始日期必须早于结束日期")
    args.symbol = args.symbol.upper()
    return args


def get_data(args):
    # 自然日都不足 60 天时，交易日必然更少，无需发网络请求。
    if (date.fromisoformat(args.end) - date.fromisoformat(args.start)).days < MIN_ROWS:
        raise DataError("数据不足 60 个交易日")
    path = Path("data_cache") / f"{args.market}_{args.symbol}_{args.start}_{args.end}.csv"
    fetcher = get_fetcher(args.market)
    if path.exists() and not args.no_cache:
        try:
            cached = pd.read_csv(path)
            if len(cached) >= MIN_ROWS:
                return fetcher.standardize(cached, args.symbol)
        except (OSError, ValueError, DataError):
            pass
    data = fetcher.get_history(args.symbol, args.start, args.end)
    data = fetcher.standardize(data, args.symbol)
    path.parent.mkdir(exist_ok=True)
    data.to_csv(path, index=False, encoding="utf-8")
    return data


def run(argv=None):
    try:
        args = parse_args(argv)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        data = get_data(args)
        with_indicators = add_indicators(data)
        trades, equity, state = run_backtest(with_indicators)
        metrics = calculate_risk(with_indicators, trades, equity, state)
        text = make_report(with_indicators, trades, metrics, state,
                           args.symbol, args.market, args.start, args.end)
        path = write_report(text, args.symbol, args.market, args.start, args.end)
        print(path)
        return 0
    except Exception as error:
        print("数据或计算失败：" + str(error).replace("\n", " "), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
