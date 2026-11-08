import json, sys, time
from pathlib import Path
sys.path.insert(0, ".")

from app.server import fetch_symbol
from tools.profile import profile
from tools.validate import read_csv

CASES = [("cn","600519"),("cn","000001"),("cn","601318"),
         ("us","AAPL"),("us","MSFT"),("us","NVDA")]

results = []
for market, sym in CASES:
    t0 = time.time()
    r = fetch_symbol(sym, market, "2015-01-01", "2025-12-31")
    if not r.get("ok"):
        results.append({"market": market, "symbol": sym, "fetch": "FAIL",
                        "err": str(r.get("error"))[:100]})
        print(f"{sym:8} fetch FAIL: {str(r.get('error'))[:70]}")
        continue
    path = Path("data_cache") / r["file"]
    rows = read_csv(path)
    p = profile(rows)
    rec = {"market": market, "symbol": sym, "fetch": "OK", "rows": len(rows),
           "file": r["file"], "structure": p.get("structure"),
           "z": p.get("vr20_z"), "ac1": p.get("autocorr1"), "vr20": p.get("vr20"),
           "secs": round(time.time() - t0, 1)}
    results.append(rec)
    print(f"{sym:8} rows={len(rows):5}  structure={str(p.get('structure')):8}  z={p.get('vr20_z')}  {rec['secs']}s")

Path("eval_live.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved eval_live.json")