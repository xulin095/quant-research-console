#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""研究仪器（③ 产品化）：一张假设卡进 → 一个判定出 → 自动记账。

为什么要有它
    分散的 validate / cross_section / cs_audit 各自都能跑，但「跑过什么、结论是什么」
    只存在于人的记忆里。而人类的记忆会自动美化：忘了跑过 20 次，只记得最后那次过了。
    这个入口强制两件事：
        1. 假设必须以**卡**的形式先写下来（参数、判据、机制、样本）
        2. 每次运行都**追加**进 registry.jsonl，包括失败的

卡格式（JSON）
    截面：
        {"id": "HK-002", "kind": "cross_section", "market": "cn",
         "direction": "reversal", "lookback": 5, "top_n": 3,
         "holdout": "2021-01-01", "cost": 0.0008,
         "universe": "universe.json",
         "mechanism": "……", "claims": "……"}
    时序：
        {"id": "TS-001", "kind": "time_series", "symbol": "AAPL",
         "csv": "data_cache/us_AAPL_2010-01-01_2025-12-31.csv"}

判据（写死，不许每张卡自己定）
    cross_section：IC 的 95% CI 下界 > 0 且 月度超额 t > 2
    time_series  ：超额收益的 95% CI 下界 > 0

用法
    python -m tools.audit cards/HK-001.json
    python -m tools.audit cards/*.json
退出码：全部通过 0，否则 1
"""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.cross_section import build_observations, evaluate, load_panel  # noqa: E402
from tools.validate import find_cached, read_csv, walk_forward  # noqa: E402

REGISTRY = Path("registry.jsonl")


def card_hash(card):
    """卡指纹：只对「会改变结论的字段」取哈希，描述文字不影响。"""
    keys = ("id", "kind", "market", "direction", "lookback", "top_n",
            "holdout", "cost", "universe", "symbol", "csv", "fast", "slow")
    payload = {k: card.get(k) for k in keys if k in card}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def verdict_cross_section(metrics):
    ok = (metrics.get("ic_ci_low") is not None
          and metrics["ic_ci_low"] > 0
          and metrics.get("excess_t", 0) > 2)
    return ok, ("IC CI 下界 > 0" if metrics.get("ic_ci_low", 0) > 0 else "IC CI 跨越 0") + \
               ("，超额 t > 2" if metrics.get("excess_t", 0) > 2 else "，超额 t ≤ 2")


def verdict_time_series(metrics):
    ok = metrics.get("excess_ci_low") is not None and metrics["excess_ci_low"] > 0
    return ok, ("超额 CI 下界 > 0" if ok else "超额 CI 跨越 0")


def run_cross_section(card):
    meta = json.loads(Path(card["universe"]).read_text(encoding="utf-8"))
    syms = [x["code"] for x in meta["success"]]
    dates, panel, used = load_panel(syms, "data_cache")
    obs = build_observations(panel, dates, lookback_months=card["lookback"])
    obs = [o for o in obs if o["date"] >= card["holdout"]]
    if len(obs) < 24:
        return None, {"error": f"留出段只有 {len(obs)} 期，不足以检验"}
    if card.get("direction") == "reversal":
        for o in obs:
            o["sig"] = [-x for x in o["sig"]]
    r = evaluate(obs, top_n=card["top_n"], cost=card["cost"], boot=4000)
    if not r.get("ok"):
        return None, {"error": r.get("reason", "评估失败")}
    m = {"periods": r["periods"], "ic": r["ic_mean"], "ic_t": r["ic_t"],
         "ic_ci_low": r["ic_ci"][0], "ic_ci_high": r["ic_ci"][2],
         "strat_cagr": r["strat_cagr"], "bench_cagr": r["bench_cagr"],
         "excess_mean": r["ex_mean"], "excess_t": r["ex_t"],
         "universe_size": len(syms), "coverage": meta.get("coverage")}
    return r, m


def run_time_series(card):
    path = card.get("csv")
    if not path:
        sym = card["symbol"].upper()
        p = find_cached("data_cache", sym)
        if p is None:
            return None, {"error": f"缓存里找不到 {sym}"}
        path = str(p)
    rows = read_csv(path)
    res = walk_forward(rows, train=card.get("train", 252), test=card.get("test", 126))
    if not res.get("ok"):
        return None, {"error": res.get("reason", "评估失败")}
    m = {"periods": res["oos_days"], "overs_oos_return": res["oos_total_return"],
         "excess_mean": None, "excess_t": None,
         "excess_ci_low": res["ci"][0], "excess_ci_high": res["ci"][2],
         "verdict_raw": res["verdict"]}
    return res, m


def count_registry():
    """已记账条数。文件还不存在时返回 0 —— 原来直接 open 会在第一次运行时炸掉。"""
    if not REGISTRY.exists():
        return 0
    with REGISTRY.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def append_registry(entry):
    with REGISTRY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def audit_one(path):
    card = json.loads(Path(path).read_text(encoding="utf-8"))
    cid, kind = card.get("id", "UNKNOWN"), card.get("kind")
    h = card_hash(card)
    print(f"\n{'='*62}\n卡 {cid}  [{kind}]  hash={h}")
    if card.get("mechanism"):
        print(f"机制：{card['mechanism']}")

    if kind == "cross_section":
        _, m = run_cross_section(card)
        ok, why = (None, m["error"]) if "error" in m else verdict_cross_section(m)
    elif kind == "time_series":
        _, m = run_time_series(card)
        ok, why = (None, m["error"]) if "error" in m else verdict_time_series(m)
    else:
        m, ok, why = {"error": f"未知 kind：{kind}"}, None, "未知 kind"

    if ok is None:
        print(f"  无法检验：{why}")
        verdict = "ERROR"
    else:
        for k in ("periods", "ic", "ic_t", "ic_ci_low", "ic_ci_high",
                  "strat_cagr", "bench_cagr", "excess_mean", "excess_t",
                  "excess_ci_low", "excess_ci_high", "coverage"):
            if m.get(k) is not None:
                v = m[k]
                print(f"  {k:<14} {v:.4f}" if isinstance(v, float) else f"  {k:<14} {v}")
        print(f"  ▶ 判定：{'通过' if ok else '不通过'}（{why}）")
        verdict = "PASS" if ok else "FAIL"

    append_registry({"ts": datetime.now().isoformat(timespec="seconds"),
                     "id": cid, "hash": h, "kind": kind,
                     "verdict": verdict, "criterion": why,
                     "n_tests_before": count_registry(),
                     "metrics": {k: m[k] for k in m if isinstance(m[k], (int, float))}})
    return verdict


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    verdicts = []
    for p in args:
        try:
            verdicts.append(audit_one(p))
        except (OSError, ValueError, KeyError) as e:
            print(f"\n卡 {p} 解析失败：{type(e).__name__}: {e}")
            verdicts.append("ERROR")

    total = len(verdicts)
    passed = verdicts.count("PASS")
    print(f"\n{'='*62}")
    print(f"共 {total} 张卡：通过 {passed}，不通过 {verdicts.count('FAIL')}，"
          f"无效 {verdicts.count('ERROR')}")
    print(f"记账文件：{REGISTRY}（追加式，失败也记）")
    print("提醒：通过率本身就是信息。试了 20 张过 1 张，那张基本是运气。")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())