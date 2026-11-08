#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""批量拉数据并落缓存（只拉数据，不生成报告）。

为什么单独写一个
    main.py 一行一个标的、还会顺带生成报告；做验证需要几十个标的 × 十年历史，
    用 main.py 会把 reports/ 塞满几十份无人看的报告，还会拖慢裁判的逐份复算。

口径
    与 main.py 完全一致：调 data.registry 的同一批 fetcher，落同名缓存文件
    data_cache\{market}_{symbol}_{start}_{end}.csv，行数不足 60 视为失败不落盘。

网络（本机实测，别踩坑）
    us / crypto：必须走代理 → 需要环境变量 QUANT_PROXY，例如
                  $env:QUANT_PROXY='http://127.0.0.1:7897'
    cn：必须绕过 Windows 注册表代理（requests 会读注册表）→ 本工具在 cn 模式下自动设 NO_PROXY=*

用法
    python -m tools.fetch_basket --market us --symbols AAPL,MSFT --start 2010-01-01 --end 2025-12-31
    python -m tools.fetch_basket --market cn --symbols 600519,000001 --start 2015-01-01 --end 2025-12-31 --sleep 2
"""

import argparse
import os
import sys
import time
from pathlib import Path

MIN_ROWS = 60


def prepare_network(market):
    """按市场切换代理策略，返回一个恢复函数。"""
    saved = {k: os.environ.get(k) for k in
             ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy", "http_proxy", "https_proxy")}

    def restore():
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)

    if market in ("us", "crypto"):
        proxy = os.environ.get("QUANT_PROXY", "")
        if not proxy:
            print("[提醒] 没设 QUANT_PROXY，美股接口大概率会 429。先设：$env:QUANT_PROXY='http://127.0.0.1:7897'")
        else:
            os.environ["HTTPS_PROXY"] = proxy
            os.environ["HTTP_PROXY"] = proxy
    else:
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
    return restore


def main(argv=None):
    ap = argparse.ArgumentParser(description="批量拉行情并落缓存")
    ap.add_argument("--market", required=True, choices=["us", "cn", "crypto"])
    ap.add_argument("--symbols", required=True, help="逗号分隔")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--sleep", type=float, default=2.0, help="每个标的之间休息秒数")
    ap.add_argument("--force", action="store_true", help="忽略已有缓存重拉")
    args = ap.parse_args(argv)

    from data.base import DataError
    from data.registry import get_fetcher

    fetcher = get_fetcher(args.market)
    cache_dir = Path("data_cache")
    cache_dir.mkdir(exist_ok=True)

    ok, skipped, failed = [], [], []
    for raw in args.symbols.split(","):
        sym = raw.strip().upper()
        if not sym:
            continue
        path = cache_dir / f"{args.market}_{sym}_{args.start}_{args.end}.csv"
        if path.is_file() and not args.force:
            rows = sum(1 for _ in path.open(encoding="utf-8-sig", errors="replace"))
            if rows >= MIN_ROWS:
                print(f"  [跳过] {sym} 已有缓存（{rows - 1} 行）")
                skipped.append(sym)
                continue

        restore = prepare_network(args.market)
        try:
            df = fetcher.get_history(sym, args.start, args.end)
            if df is None or len(df) < MIN_ROWS:
                raise DataError(f"只拿到 {0 if df is None else len(df)} 行")
            df.to_csv(path, index=False, encoding="utf-8")
            print(f"  [成功] {sym}  {len(df)} 行 → {path.name}")
            ok.append(sym)
        except (DataError, OSError, ValueError, KeyError) as e:
            print(f"  [失败] {sym}  {type(e).__name__}: {str(e)[:110]}")
            failed.append(sym)
        finally:
            restore()
        time.sleep(args.sleep)

    print(f"\n成功 {len(ok)} / 跳过 {len(skipped)} / 失败 {len(failed)}")
    if failed:
        print("失败清单：" + ", ".join(failed))
        print("（失败不影响已成功的标的，验证器会自动跳过没有缓存的）")
    return 0 if ok or skipped else 1


if __name__ == "__main__":
    sys.exit(main())
