#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""诚实宇宙加载器 —— 专门用来对付幸存者偏差。

背景（本机实测，2026-11-08）
    美股：yfinance 对已退市票**一只都取不到**（试了 TWTR/SIVB/SBNY/FRC/BBBY 等 14 只，0/14）。
          这意味着用免费数据**做不出**美股的 point-in-time 宇宙。
    A股 ：akshare 对已退市票大多仍可取到完整历史（600087 退市于 2014、600005 于 2017、
          000418 于 2019、002680 于 2019 …），实测 7/10 可用。
          所以诚实宇宙只能在 A股 上做。

复权口径
    长历史一律用**后复权 hfq**。前复权在 10 年期 + 高分红股上会算出负价格
    （600519 2015 年首日收盘 −117.62），这不是小问题。

它做三件事
    1. 组合候选池：当前上市（在线取，失败则用内置清单）+ 内置退市清单
    2. 固定种子随机抽样 —— 按运气抽，不按"事后表现"抽
    3. 逐只拉取并**如实记录覆盖情况**：申请多少、拿到多少、失败多少、失败原因
       覆盖率本身就是残余偏差的量化 —— 拿到 92% 就说明还有 8% 的样本缺失。

用法
    python -m tools.universe --sample 60 --seed 7
    python -m tools.universe --sample 60 --start 2010-01-01 --end 2025-12-31 --sleep 1
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

MIN_ROWS = 60

# 内置退市/被并购样本（实测可取的优先排前面）
BUILTIN_DELISTED = [
    "600087", "600005", "000418", "000562", "601299", "002680", "000693",
    "600631", "000760", "600840", "000003", "600632", "000887", "002450",
]

# 在线清单拿不到时的兜底（跨行业、跨市值，不做表现筛选）
BUILTIN_CURRENT = [
    "600519", "000001", "600036", "601318", "000858", "002415", "600276", "600030",
    "601398", "601288", "600028", "601857", "600019", "600585", "000651", "000333",
    "002594", "601012", "600900", "601088", "600309", "600690", "000725", "601668",
    "601390", "601186", "600048", "000002", "600031", "000157", "600104", "601238",
    "600009", "601111", "600115", "601006", "600018", "601919", "600018", "002024",
    "600827", "601933", "600690", "603288", "600887", "002714", "000876", "600438",
    "600745", "002236", "002241", "300750", "300059", "002475", "600703", "000063",
    "600050", "600941", "601728", "600886", "600011", "600027", "600795", "601985",
]


def prepare_network():
    """A股直连；清掉系统代理（requests 会读 Windows 注册表）。"""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def current_candidates(use_online=True):
    """当前上市清单。返回 (codes, 来源说明)。"""
    if use_online:
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            codes = [str(c) for c in df["代码"].tolist()]
            if len(codes) > 500:
                return codes, f"在线全市场 {len(codes)} 只"
        except Exception as e:
            print(f"  [提醒] 在线清单取不到（{type(e).__name__}），改用内置清单")
    return list(dict.fromkeys(BUILTIN_CURRENT)), f"内置清单 {len(set(BUILTIN_CURRENT))} 只"


def build_pool(use_online=True):
    cur, src = current_candidates(use_online)
    pool = [{"code": c, "tag": "listed"} for c in dict.fromkeys(cur)]
    pool += [{"code": c, "tag": "delisted"} for c in dict.fromkeys(BUILTIN_DELISTED)]
    return pool, src


def sample_pool(pool, n, seed=7):
    """固定种子随机抽样；退市样本强制保留（它们才是抵消偏差的关键）。"""
    rng = random.Random(seed)
    delisted = [p for p in pool if p["tag"] == "delisted"]
    listed = [p for p in pool if p["tag"] == "listed"]
    keep = delisted[:]
    rest = n - len(keep)
    if rest > 0 and listed:
        keep += rng.sample(listed, min(rest, len(listed)))
    rng.shuffle(keep)
    return keep


def fetch_one(code, start, end):
    """取后复权日线，返回标准表 DataFrame 或抛异常。只请求一次。"""
    import akshare as ak
    import pandas as pd
    raw = ak.stock_zh_a_hist(symbol=code, period="daily",
                             start_date=start.replace("-", ""),
                             end_date=end.replace("-", ""), adjust="hfq")
    if raw is None or len(raw) == 0 or "日期" not in raw.columns:
        raise ValueError("接口没有返回有效数据")
    df = raw.rename(columns={"日期": "date", "开盘": "open", "最高": "high",
                             "最低": "low", "收盘": "close", "成交量": "volume"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
    df["symbol"] = code
    df["market"] = "cn"
    return df[["date", "open", "high", "low", "close", "volume", "symbol", "market"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description="按诚实宇宙抽样并落缓存")
    ap.add_argument("--sample", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--offline-pool", action="store_true", help="不用在线全市场清单")
    args = ap.parse_args(argv)

    prepare_network()
    pool, src = build_pool(use_online=not args.offline_pool)
    picked = sample_pool(pool, args.sample, args.seed)
    n_del = sum(1 for p in picked if p["tag"] == "delisted")
    print(f"候选池：{src} + 内置退市 {len(BUILTIN_DELISTED)} 只")
    print(f"抽样 {len(picked)} 只（其中退市 {n_del} 只，种子 {args.seed}）\n")

    from data.base import DataError
    cache = Path("data_cache")
    cache.mkdir(exist_ok=True)

    ok, failed = [], []
    for i, item in enumerate(picked, 1):
        code = item["code"]
        path = cache / f"cn_{code}_{args.start}_{args.end}.csv"
        if path.is_file() and sum(1 for _ in path.open(encoding="utf-8-sig", errors="replace")) > MIN_ROWS:
            print(f"  [{i}/{len(picked)}] {code} 已有缓存，跳过")
            ok.append({**item, "rows": None, "note": "cached"})
            continue
        try:
            df = fetch_one(code, args.start, args.end)
            first, last = df["date"].iloc[0], df["date"].iloc[-1]
            df.to_csv(path, index=False, encoding="utf-8")
            print(f"  [{i}/{len(picked)}] {code} {item['tag']:<8} {len(df)} 行  {first} → {last}")
            ok.append({**item, "rows": len(df), "first": first, "last": last})
        except Exception as e:
            print(f"  [{i}/{len(picked)}] {code} {item['tag']:<8} 失败 {type(e).__name__}: {str(e)[:60]}")
            failed.append({**item, "error": f"{type(e).__name__}: {str(e)[:80]}"})

        time.sleep(args.sleep)

    cov = len(ok) / len(picked) if picked else 0
    del_ok = sum(1 for x in ok if x["tag"] == "delisted")
    print(f"\n覆盖率 {len(ok)}/{len(picked)} = {cov*100:.0f}%"
          f"（退市票 {del_ok}/{n_del} 拿到）")
    print(f"残余偏差：缺失的 {(1-cov)*100:.0f}% 样本就是仍未被覆盖的那部分，"
          f"后续任何结论都要带着这个折扣看。")

    meta = {"seed": args.seed, "start": args.start, "end": args.end,
            "adjust": "hfq", "pool_source": src,
            "requested": len(picked), "ok": len(ok), "failed": len(failed),
            "coverage": round(cov, 4), "delisted_ok": del_ok,
            "success": ok, "failures": failed}
    Path("universe.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("宇宙清单已写入 universe.json（后续结果都必须能追溯到它）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())