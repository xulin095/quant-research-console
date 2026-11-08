"""Two measurable accuracies:

A) System accuracy -- is the computation correct, reproducible, independently verifiable?
B) Verdict stability -- if we classify on the first 70% of history, does the same
   verdict hold on the last 30%? This is the closest honest analogue of "accuracy".
"""
import csv, json, random, subprocess, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, ".")

from tools.profile import profile
from tools.validate import read_csv

def profile_rows(rows):
    return profile(rows)

# ---------- B) verdict stability across a time split ----------
files = sorted(Path("data_cache").glob("*.csv"))
split_result = []
for f in files:
    try:
        rows = read_csv(f)
    except Exception:
        continue
    if len(rows) < 750:
        continue
    cut = int(len(rows) * 0.7)
    a, b = profile(rows[:cut]), profile(rows[cut:])
    if not a.get("ok") or not b.get("ok"):
        continue
    split_result.append({
        "file": f.name,
        "first": a["structure"], "second": b["structure"],
        "first_raw": a.get("structure_raw"), "second_raw": b.get("structure_raw"),
        "z1": a["vr20_z"], "z2": b["vr20_z"],
    })

same = sum(1 for r in split_result if r["first"] == r["second"])
n = len(split_result)
strong = [r for r in split_result if r["first"] != "无明显结构"]
strong_same = sum(1 for r in strong if r["first"] == r["second"])

# z 值在前后两段的相关性
def corr(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = sum((x-mx)**2 for x in xs) ** 0.5
    dy = sum((y-my)**2 for y in ys) ** 0.5
    return None if dx*dy == 0 else num/(dx*dy)

zs = [(r["z1"], r["z2"]) for r in split_result if r["z1"] is not None and r["z2"] is not None]
zcorr = corr([p[0] for p in zs], [p[1] for p in zs])

print("=== B) 判定稳定性（前 70% 判型 → 后 30% 验真）===")
print(f"  样本: {n} 只标的")
print(f"  判定一致率: {same}/{n} = {same/n*100:.1f}%")
print(f"  其中「判出了结构」的: {len(strong)} 只，一致 {strong_same} 只 = "
      f"{(strong_same/len(strong)*100 if strong else 0):.1f}%")
print(f"  前后段 z 值相关: {zcorr:+.3f}" if zcorr is not None else "  z 相关: 样本不足")

raw_strong = [r for r in split_result if r["first_raw"] == r["second_raw"]
              and r["first_raw"] not in ("无明显结构", None)]
raw_same = len(raw_strong)
raw_claimed = sum(1 for r in split_result if r["first_raw"] not in ("无明显结构", None))
print(f"  对照（未加持续性过滤）: 同一结构 {raw_same}/{raw_claimed} = "
      f"{(raw_same/raw_claimed*100 if raw_claimed else 0):.1f}%")
print("  混淆矩阵（前段 → 后段）:")
cm = Counter((r["first"], r["second"]) for r in split_result)
for (a_, b_), c in cm.most_common():
    print(f"    {a_:8} -> {b_:8}  {c}")

# ---------- A) 系统正确性 ----------
print("\n=== A) 系统正确性 ===")
bad_prices = bad_dates = ok_files = 0
for f in files:
    try:
        rows = read_csv(f)
    except Exception:
        continue
    ok_files += 1
    if any(r["close"] <= 0 for r in rows):
        bad_prices += 1
    dates = [r["date"] for r in rows]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        bad_dates += 1
print(f"  缓存文件: {ok_files}")
print(f"  含非正价格的: {bad_prices}")
print(f"  日期乱序或重复的: {bad_dates}")

# 可复现性：同一份数据算两遍
sample = files[0]
rows = read_csv(sample)
r1, r2 = profile(rows), profile(rows)
print(f"  同数据两次计算结果一致: {json.dumps(r1, sort_keys=True, ensure_ascii=False) == json.dumps(r2, sort_keys=True, ensure_ascii=False)}")

Path("eval_split.json").write_text(json.dumps(
    {"n": n, "same": same, "strong": len(strong), "strong_same": strong_same,
     "zcorr": zcorr, "rows": split_result}, ensure_ascii=False, indent=1), encoding="utf-8")