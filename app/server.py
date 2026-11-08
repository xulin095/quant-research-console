#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""量化研究台 —— 后端 API（标准库，零依赖）。

设计原则
    1. 只读本地文件 + 跑本地子进程，不联网
    2. 所有数字都来自真实产物（results.json / registry.jsonl / data_cache / *.md），
       前端不允许凭空生成结论
    3. 只监听 127.0.0.1

端点
    GET  /                     单页应用
    GET  /api/overview         概览：路径统计、宇宙、账本、数据
    GET  /api/pipeline         四棒流水线状态与产物
    GET  /api/results          四条路径的结论表 + IC 曲线
    GET  /api/tools            工具清单（行数、作用、用法）
    GET  /api/cards            假设卡列表
    POST /api/cards            保存卡片（含参数冻结护栏）
    GET  /api/registry         账本
    GET  /api/status           数据状态
    GET  /api/cache            缓存文件清单
    GET  /api/profile?symbol=X 单标的结构画像（描述统计）\n    GET  /api/profile_all     批量结构画像（120 秒缓存）\n    GET  /api/glossary        术语白话库\n    GET  /api/md?name=xxx.md   读取报告原文（白名单）
    POST /api/report {symbol}  生成单只股票的分析报告\n    POST /api/fetch {symbol}   按代码自动拉数据（美股走代理/A股绕过）\n    POST /api/upload           上传自备 CSV（校验并落成标准表）\n    POST /api/run {id}         跑卡
    GET  /api/job/{job}        轮询任务

启动
    双击 启动研究台.bat，或 python -m app.server
"""

import json
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
REGISTRY = ROOT / "registry.jsonl"
STATIC = Path(__file__).resolve().parent / "static"
HOST, PORT = "127.0.0.1", 8765

REQUIRED = ("id", "kind", "direction", "lookback", "top_n", "mechanism")
JOBS = {}
_PALL = {"t": 0.0, "data": None}   # 批量画像结果缓存（120 秒）

# 报告白名单（防止路径穿越）
ALLOWED_MD = ("research.md", "design.md", "test-report.md", "ROADMAP-v2.md", "RUNBOOK.md", "README.md")

TOOL_DOC = [
    ("tools/audit.py", "统一入口：卡片 → 判定 → 追加记账", "python -m tools.audit cards/HK-001.json"),
    ("tools/validate.py", "时序验证：walk-forward + deflated Sharpe + 块自助 CI", "python -m tools.validate --symbols AAPL"),
    ("tools/cross_section.py", "截面验证：rank IC + 置信区间 + 扣成本回测", "python -m tools.cross_section --symbols ..."),
    ("tools/cs_audit.py", "三重审计：邻域 / Bonferroni / 留出段", "python -m tools.cs_audit --symbols ..."),
    ("tools/decide.py", "决策层：规则表历史回放", "python -m tools.decide --symbols ..."),
    ("tools/universe.py", "诚实宇宙：含退市样本抽样 + 覆盖率量化", "python -m tools.universe --sample 45"),
    ("tools/prereg_reversal.py", "预注册卡 HK-001 的单次检验", "python -m tools.prereg_reversal"),
    ("tools/fetch_basket.py", "批量拉数据落缓存", "python -m tools.fetch_basket --market us --symbols ..."),
    ("referee/verify.py", "13 条机械验收（独立于项目代码）", "python referee/verify.py --root ."),
]


# ---------------------------------------------------------------- 读取层
def read_json(path, default=None):
    p = Path(path)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def list_cards():
    out = []
    if not CARDS.is_dir():
        return out
    for p in sorted(CARDS.glob("*.json")):
        c = read_json(p)
        if c:
            c["_file"] = p.name
            out.append(c)
    return out


def read_registry(limit=300):
    if not REGISTRY.exists():
        return {"entries": [], "total": 0, "pass_rate": 0.0, "passed": 0}
    rows = []
    with REGISTRY.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    total = len(rows)
    passed = sum(1 for r in rows if r.get("verdict") == "PASS")
    return {"entries": rows[-limit:][::-1], "total": total, "passed": passed,
            "pass_rate": round(passed / total, 3) if total else 0.0}


def data_status():
    cache = ROOT / "data_cache"
    files = sorted(cache.glob("*.csv")) if cache.is_dir() else []
    uni = read_json(ROOT / "universe.json", {}) or {}
    return {
        "cache_files": len(files),
        "universe_size": len(uni.get("success", [])),
        "coverage": uni.get("coverage"),
        "delisted_ok": uni.get("delisted_ok"),
        "requested": uni.get("requested"),
        "held_out_from": "2021-01-01",
        "markets": sorted({f.name.split("_")[0] for f in files}),
    }


def overview():
    res = read_json(ROOT / "results.json", {}) or {}
    reg = read_registry()
    st = data_status()
    paths = res.get("paths", [])
    return {
        "paths_tested": len(paths),
        "paths_passed": sum(1 for p in paths if p.get("verdict") == "PASS"),
        "headline": res.get("headline", ""),
        "conclusion": res.get("conclusion", ""),
        "registry": {"total": reg["total"], "passed": reg["passed"], "pass_rate": reg["pass_rate"]},
        "data": st,
        "generated": res.get("generated", ""),
    }


def pipeline():
    """四棒流水线：每棒的产物、体量、结论。产物为真实文件。"""
    def size(name):
        p = ROOT / name
        return {"exists": p.is_file(),
                "bytes": p.stat().st_size if p.is_file() else 0,
                "lines": sum(1 for _ in p.open(encoding="utf-8", errors="replace")) if p.is_file() else 0}
    return {"roles": [
        {"role": "① 研究员", "agent": "Trae CN", "artifact": "research.md",
         "status": "done", "what": "核实免费数据源、字段映射、8 周学习路线、6 个概念",
         "key": "19 个来源链接；4 处「未核实」；Yahoo 官方 Real-time 与社区 15min 的矛盾如实记录", **size("research.md")},
        {"role": "② 架构师", "agent": "DSH", "artifact": "design.md",
         "status": "done", "what": "5 节固定编号、模块接口、口径总表、12+1 条验收",
         "key": "裁决 6 处 research 冲突；补网络策略（美股走代理 / A股绕代理）", **size("design.md")},
        {"role": "③ 开发者", "agent": "Codex 桌面版", "artifact": "main.py + data/",
         "status": "done", "what": "16 文件 + 2 .gitkeep，双均线回测，5 章中文报告",
         "key": "13/13 机械验收；真跑出 AAPL/600519 两份报告，独立复算一致", **size("main.py")},
        {"role": "④ 质检员", "agent": "Trae / Grok（禁 Codex）", "artifact": "test-report.md",
         "status": "done", "what": "独立测试、逐笔复算、边界实测、未验证项清单",
         "key": "发现 8 个问题（全为中/低危）；抓到裁判把字符数标成字节", **size("test-report.md")},
    ]}


def results():
    return read_json(ROOT / "results.json", {}) or {"paths": [], "error": "results.json 缺失"}


def tools():
    out = []
    for rel, what, usage in TOOL_DOC:
        # referee/ 现在也在仓库里，统一按项目根目录解析（不再硬编码任何人的路径）
        p = ROOT / rel
        lines = 0
        if p.is_file():
            lines = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
        out.append({"path": rel, "what": what, "usage": usage, "lines": lines,
                    "exists": p.is_file()})
    tests = sum(1 for _ in (ROOT / "tests").glob("test_*.py")) if (ROOT / "tests").is_dir() else 0
    return {"tools": out, "test_files": tests}


def cache_list(limit=40):
    cache = ROOT / "data_cache"
    if not cache.is_dir():
        return []
    files = sorted(cache.glob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)[:limit]
    return [{"name": p.name, "kb": round(p.stat().st_size / 1024, 1),
             "rows": sum(1 for _ in p.open(encoding="utf-8", errors="replace")) - 1} for p in files]


def list_reports(limit=50):
    """列出 reports/ 下已生成的报告（新的在前）。"""
    d = ROOT / "reports"
    out = []
    if not d.is_dir():
        return out
    for f in d.glob("*.md"):
        try:
            st = f.stat()
        except OSError:
            continue
        out.append({"name": f.name, "kb": round(st.st_size / 1024, 1),
                    "mtime": st.st_mtime})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    for x in out:
        x["mtime"] = datetime.fromtimestamp(x["mtime"]).strftime("%m-%d %H:%M")
    return out[:limit]


def read_md(name):
    """读报告原文。允许根目录白名单文件，以及 reports/ 下的 .md（禁止路径穿越）。"""
    if name not in ALLOWED_MD:
        sub = name[8:]
        ok = (name.startswith("reports/") and name.endswith(".md")
              and ".." not in name and "/" not in sub and "\\" not in name)
        if not ok:
            raise ValueError("不在白名单里")
    p = ROOT / name
    if not p.is_file():
        raise ValueError("文件不存在")
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 数据接入
STD_COLS = ["date", "open", "high", "low", "close", "volume"]
CN_MAP = {"日期": "date", "时间": "date", "开盘": "open", "最高": "high", "最低": "low",
          "收盘": "close", "成交量": "volume", "成交额": "amount", "代码": "symbol"}
MIN_ROWS = 60


def _norm_header(h):
    h = h.strip().strip('"').lower()
    return CN_MAP.get(h, h)


def ingest_csv(text, market, symbol, start=None, end=None):
    """把用户上传的 CSV 变成项目标准表，并校验。

    校验项（不满足就明确拒绝，不静默修补）：
        · 必需列齐全（支持中文列名：日期/开盘/最高/最低/收盘/成交量）
        · 日期可解析；重复日期去重并计数；乱序自动排序
        · 价格必须为正（前复权长历史会出现负价，这是本项目踩过的坑）
        · 至少 60 个交易日
    返回 (ok, 信息字典)
    """
    import csv as _csv
    import io
    from datetime import datetime

    if not market or not symbol:
        return False, {"error": "必须填写 market 与 symbol"}
    market = market.strip().lower()
    symbol = symbol.strip().upper()
    if market not in ("us", "cn", "crypto"):
        return False, {"error": "market 只能是 us / cn / crypto"}

    reader = _csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return False, {"error": "文件内容为空"}

    header = [_norm_header(c) for c in rows[0]]
    missing = [c for c in STD_COLS if c not in header]
    if missing:
        return False, {"error": "缺少列：" + "、".join(missing) +
                                "（表头是：" + "、".join(rows[0]) + "）"}
    idx = {c: header.index(c) for c in STD_COLS}

    good, dropped_bad_price, seen, dup = [], 0, set(), 0
    for r in rows[1:]:
        if not r or len(r) <= max(idx.values()):
            continue
        try:
            d = r[idx["date"]].strip()[:10]
            datetime.strptime(d, "%Y-%m-%d")
            o, h, l, c = (float(r[idx[k]]) for k in ("open", "high", "low", "close"))
            v = float(r[idx["volume"]] or 0)
        except (ValueError, IndexError):
            continue
        if min(o, h, l, c) <= 0:
            dropped_bad_price += 1
            continue
        if d in seen:
            dup += 1
            continue
        seen.add(d)
        good.append((d, o, h, l, c, v))

    if len(good) < MIN_ROWS:
        return False, {"error": f"有效数据只有 {len(good)} 行，少于 {MIN_ROWS} 行",
                       "dropped_bad_price": dropped_bad_price}

    good.sort(key=lambda x: x[0])
    d0, d1 = good[0][0], good[-1][0]
    fname = f"{market}_{symbol}_{d0}_{d1}.csv"
    path = ROOT / "data_cache" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,open,high,low,close,volume,symbol,market"]
    for d, o, h, l, c, v in good:
        lines.append(f"{d},{o},{h},{l},{c},{v},{symbol},{market}")
    path.write_text("\n".join(lines), encoding="utf-8")

    return True, {"file": fname, "rows": len(good), "first": d0, "last": d1,
                  "symbol": symbol, "market": market,
                  "dedup": dup, "dropped_bad_price": dropped_bad_price,
                  "hint": "已可被 tools.validate / cross_section / audit 直接使用"}

# ---------------------------------------------------------------- 写操作
def save_card(card):
    missing = [k for k in REQUIRED if not card.get(k)]
    if missing:
        raise ValueError("缺少字段：" + "、".join(missing))
    cid = str(card["id"]).strip()
    if not cid.replace("-", "").replace("_", "").isalnum():
        raise ValueError("id 只能包含字母、数字、- 和 _")
    if card["kind"] not in ("cross_section", "time_series"):
        raise ValueError("kind 只能是 cross_section 或 time_series")
    if card.get("kind") == "cross_section":
        lb = int(card.get("lookback", 0))
        if not 1 <= lb <= 12:
            raise ValueError("lookback 必须在 1–12")
        if card.get("direction") not in ("reversal", "momentum"):
            raise ValueError("direction 只能是 reversal 或 momentum")
    CARDS.mkdir(parents=True, exist_ok=True)
    p = CARDS / f"{cid}.json"
    if p.exists():
        old = read_json(p, {})
        frozen = ("lookback", "direction", "holdout")
        changed = [k for k in frozen if k in old and str(old[k]) != str(card.get(k))]
        if changed:
            raise ValueError("这张卡已经跑过了，参数冻结：" + "、".join(changed) +
                             "。要试新参数请用新的 id（旧卡留在账本里）。")
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": p.name}


def start_run(card_id):
    job = uuid.uuid4().hex[:8]
    JOBS[job] = {"status": "running", "output": "", "started": time.time(),
                 "id": card_id, "verdict": None}
    threading.Thread(target=_run, args=(job, card_id), daemon=True).start()
    return job


def _run(job, card_id):
    """跑一张卡 —— 进程内调用 tools.audit，不起子进程（原因同 fetch_symbol）。"""
    import contextlib
    import io

    buf = io.StringIO()
    try:
        import os as _os
        _os.chdir(str(ROOT))
        from tools import audit as AUD
        with contextlib.redirect_stdout(buf):
            AUD.main([str(CARDS / f"{card_id}.json")])
        JOBS[job]["status"] = "done"
        reg = read_registry(limit=1)
        if reg["entries"]:
            JOBS[job]["verdict"] = reg["entries"][0].get("verdict")
            JOBS[job]["metrics"] = reg["entries"][0].get("metrics", {})
    except Exception as e:
        JOBS[job]["status"] = "error"
        buf.write(f"\n运行出错：{type(e).__name__}: {e}")
    finally:
        JOBS[job]["output"] = buf.getvalue()

# ---------------------------------------------------------------- 数据接入
STD_COLS = ["date", "open", "high", "low", "close", "volume"]
CN_MAP = {"日期": "date", "时间": "date", "开盘": "open", "最高": "high", "最低": "low",
          "收盘": "close", "成交量": "volume", "成交额": "amount", "代码": "symbol"}
MIN_ROWS = 60


def _norm_header(h):
    h = h.strip().strip('"').lower()
    return CN_MAP.get(h, h)


def ingest_csv(text, market, symbol, start=None, end=None):
    """把用户上传的 CSV 变成项目标准表，并校验。

    校验项（不满足就明确拒绝，不静默修补）：
        · 必需列齐全（支持中文列名：日期/开盘/最高/最低/收盘/成交量）
        · 日期可解析；重复日期去重并计数；乱序自动排序
        · 价格必须为正（前复权长历史会出现负价，这是本项目踩过的坑）
        · 至少 60 个交易日
    返回 (ok, 信息字典)
    """
    import csv as _csv
    import io
    from datetime import datetime

    if not market or not symbol:
        return False, {"error": "必须填写 market 与 symbol"}
    market = market.strip().lower()
    symbol = symbol.strip().upper()
    if market not in ("us", "cn", "crypto"):
        return False, {"error": "market 只能是 us / cn / crypto"}

    reader = _csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return False, {"error": "文件内容为空"}

    header = [_norm_header(c) for c in rows[0]]
    missing = [c for c in STD_COLS if c not in header]
    if missing:
        return False, {"error": "缺少列：" + "、".join(missing) +
                                "（表头是：" + "、".join(rows[0]) + "）"}
    idx = {c: header.index(c) for c in STD_COLS}

    good, dropped_bad_price, seen, dup = [], 0, set(), 0
    for r in rows[1:]:
        if not r or len(r) <= max(idx.values()):
            continue
        try:
            d = r[idx["date"]].strip()[:10]
            datetime.strptime(d, "%Y-%m-%d")
            o, h, l, c = (float(r[idx[k]]) for k in ("open", "high", "low", "close"))
            v = float(r[idx["volume"]] or 0)
        except (ValueError, IndexError):
            continue
        if min(o, h, l, c) <= 0:
            dropped_bad_price += 1
            continue
        if d in seen:
            dup += 1
            continue
        seen.add(d)
        good.append((d, o, h, l, c, v))

    if len(good) < MIN_ROWS:
        return False, {"error": f"有效数据只有 {len(good)} 行，少于 {MIN_ROWS} 行",
                       "dropped_bad_price": dropped_bad_price}

    good.sort(key=lambda x: x[0])
    d0, d1 = good[0][0], good[-1][0]
    fname = f"{market}_{symbol}_{d0}_{d1}.csv"
    path = ROOT / "data_cache" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["date,open,high,low,close,volume,symbol,market"]
    for d, o, h, l, c, v in good:
        lines.append(f"{d},{o},{h},{l},{c},{v},{symbol},{market}")
    path.write_text("\n".join(lines), encoding="utf-8")

    return True, {"file": fname, "rows": len(good), "first": d0, "last": d1,
                  "symbol": symbol, "market": market,
                  "dedup": dup, "dropped_bad_price": dropped_bad_price,
                  "hint": "已可被 tools.validate / cross_section / audit 直接使用"}

# ---------------------------------------------------------------- 写操作
def save_card(card):
    missing = [k for k in REQUIRED if not card.get(k)]
    if missing:
        raise ValueError("缺少字段：" + "、".join(missing))
    cid = str(card["id"]).strip()
    if not cid.replace("-", "").replace("_", "").isalnum():
        raise ValueError("id 只能包含字母、数字、- 和 _")
    if card["kind"] not in ("cross_section", "time_series"):
        raise ValueError("kind 只能是 cross_section 或 time_series")
    if card.get("kind") == "cross_section":
        lb = int(card.get("lookback", 0))
        if not 1 <= lb <= 12:
            raise ValueError("lookback 必须在 1–12")
        if card.get("direction") not in ("reversal", "momentum"):
            raise ValueError("direction 只能是 reversal 或 momentum")
    CARDS.mkdir(parents=True, exist_ok=True)
    p = CARDS / f"{cid}.json"
    if p.exists():
        old = read_json(p, {})
        frozen = ("lookback", "direction", "holdout")
        changed = [k for k in frozen if k in old and str(old[k]) != str(card.get(k))]
        if changed:
            raise ValueError("这张卡已经跑过了，参数冻结：" + "、".join(changed) +
                             "。要试新参数请用新的 id（旧卡留在账本里）。")
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": p.name}


def start_run(card_id):
    job = uuid.uuid4().hex[:8]
    JOBS[job] = {"status": "running", "output": "", "started": time.time(),
                 "id": card_id, "verdict": None}
    threading.Thread(target=_run, args=(job, card_id), daemon=True).start()
    return job


def _run(job, card_id):
    path = CARDS / f"{card_id}.json"
    try:
        p = subprocess.run([sys.executable, "-m", "tools.audit", str(path)],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        JOBS[job]["output"] = (p.stdout or "") + (p.stderr or "")
        JOBS[job]["status"] = "done"
        reg = read_registry(limit=1)
        if reg["entries"]:
            JOBS[job]["verdict"] = reg["entries"][0].get("verdict")
            JOBS[job]["metrics"] = reg["entries"][0].get("metrics", {})
    except subprocess.TimeoutExpired:
        JOBS[job].update(status="timeout", output="超时（>30 分钟）")
    except OSError as e:
        JOBS[job].update(status="error", output=f"启动失败：{e}")


# ---------------------------------------------------------------- 按代码拉数据
SYM_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,20}$")


def normalize_symbol(symbol, market=None):
    """把各种写法统一成数据源认的写法。

    支持：600519 / 600519.SH / SH600519 / sh600519 / 002541.SZ / 603345.SH
    美股只做大写并保留点号（BRK.B 是合法代码）。

    注意：**不管有没有指定市场**，只要看起来是 A 股写法就归一化成 6 位数字。
    否则「市场选自动」时 603345.SH 会找不到 cn_603345_*.csv。
    """
    import re as _re
    s = (symbol or "").strip().upper()
    core = s.split(".")[0]                       # 去掉 .SH / .SZ
    m = _re.match(r"^(SH|SZ|BJ)?(\d{6})$", core)
    if m:
        return m.group(2)
    return s

CN_SUFFIXES = (".SZ", ".SH", ".SS", ".BJ")


def market_mismatch(market, symbol):
    """判断「这个代码是不是这个市场的」。

    为什么必须有这条：Yahoo 上深市代码写 `002541.SZ`，所以把 A 股代码
    丢给「美股」拉取，yfinance 会照单全收，于是 A 股数据被打上 us 标签、
    报告里写着「市场 us」—— 数据是假的，标签也是假的。

    注意：这里对「带后缀」的写法宽容（cn 接受 002541.SZ / SH600519），
    因为用户从行情软件复制出来就是这种格式。
    """
    import re as _re
    s = (symbol or "").strip().upper()
    if not s:
        return "代码不能为空"
    core = s.split(".")[0]                      # 去掉 .SZ / .SH
    is_cn_code = bool(_re.match(r"^(SH|SZ|BJ)?(\d{6})$", core))

    if market == "us":
        if s.endswith(CN_SUFFIXES) or is_cn_code:
            return f"{s} 是 A 股代码，市场应选 cn"
    elif market == "cn":
        if not is_cn_code:
            return f"{s} 不是 A 股代码（应为 6 位数字，可带 .SZ/.SH）"
    elif market == "crypto":
        if is_cn_code or s.endswith(CN_SUFFIXES):
            return f"{s} 不像加密交易对（一般形如 BTCUSDT）"
    return None

def check_fetch_args(market, symbol, start, end):
    """校验拉取参数。返回错误信息或 None。"""
    from datetime import datetime
    if market not in ("us", "cn", "crypto"):
        return "market 只能是 us / cn / crypto"
    if not SYM_RE.match(symbol or ""):
        return "代码格式不对（只能是字母、数字、. - _，长度 1–20）"
    mm = market_mismatch(market, symbol)
    if mm:
        return mm
    for label, v in (("开始日期", start), ("结束日期", end)):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except (TypeError, ValueError):
            return f"{label}格式必须是 YYYY-MM-DD"
    if start >= end:
        return "开始日期必须早于结束日期"
    return None


def build_fetch_args(market, symbol, start, end):
    """拼出调用批量拉取器的命令。单独抽出来是为了可测。"""
    return [sys.executable, "-m", "tools.fetch_basket",
            "--market", market, "--symbols", symbol,
            "--start", start, "--end", end, "--sleep", "0"]


def fetch_symbol(symbol, market, start, end, proxy=""):
    """拉一只票的数据并落缓存 —— **进程内直接调用**，不起子进程。

    为什么不起子进程：受限环境下子进程的管道 stdio 会被拒绝，表现为
    连接被意外关闭（我实测踩到过）。进程内调用没有这个问题，还快一点。
    """
    symbol = normalize_symbol(symbol, market)
    err = check_fetch_args(market, symbol, start, end)
    if err:
        return {"ok": False, "error": err}

    import os as _os
    saved = {k: _os.environ.get(k) for k in
             ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")}

    def restore():
        for k, v in saved.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v

    try:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
            _os.environ.pop(k, None)
        if market in ("us", "crypto"):
            p = proxy or _os.environ.get("QUANT_PROXY", "") or "http://127.0.0.1:7897"
            _os.environ["HTTPS_PROXY"] = p
            _os.environ["HTTP_PROXY"] = p
        else:
            _os.environ["NO_PROXY"] = "*"
            _os.environ["no_proxy"] = "*"

        from data.registry import get_fetcher
        df = get_fetcher(market).get_history(symbol, start, end)
        if df is None or len(df) < 60:
            return {"ok": False, "error": f"只拿到 {0 if df is None else len(df)} 行，不足 60 行"}
        path = ROOT / "data_cache" / f"{market}_{symbol}_{start}_{end}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False, encoding="utf-8")
        # 双保险：落盘后再核对数据自己声明的市场（防止数据源张冠李戴）
        if "market" in df.columns:
            got = str(df["market"].iloc[0]).lower()
            if got and got != market:
                path.unlink(missing_ok=True)
                return {"ok": False, "error": f"数据源返回的是 {got} 市场数据，与请求的 {market} 不符，已丢弃"}
        return {"ok": True, "file": path.name, "rows": len(df),
                "first": str(df["date"].iloc[0]), "last": str(df["date"].iloc[-1])}
    except Exception as e:                      # 网络/接口/解析，统一成一行中文
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        restore()

# ---------------------------------------------------------------- HTTP
ROUTES_GET = {
    "/api/overview": overview,
    "/api/pipeline": pipeline,
    "/api/results": results,
    "/api/tools": tools,
    "/api/cards": lambda: {"cards": list_cards()},
    "/api/registry": read_registry,
    "/api/status": data_status,
    "/api/cache": lambda: {"files": cache_list()},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path in ("/", "/index.html"):
            f = STATIC / "index.html"
            return self._send(200, f.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path == "/api/glossary":
            g = read_json(ROOT / "glossary.json", {}) or {}
            return self._send(200, json.dumps(g, ensure_ascii=False))
        if path == "/api/profile_all":
            now = time.time()
            if _PALL["t"] and now - _PALL["t"] < 120:
                return self._send(200, json.dumps(_PALL["data"], ensure_ascii=False))
            try:
                from tools.profile_all import scan
                rows, summary = scan(ROOT / "data_cache")
                data = {"summary": summary, "rows": rows, "count": len(rows)}
                _PALL.update(t=now, data=data)
                return self._send(200, json.dumps(data, ensure_ascii=False))
            except (OSError, ValueError, ImportError) as e:
                return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
        if path == "/api/reports":
            return self._send(200, json.dumps({"files": list_reports()}, ensure_ascii=False))
        if path == "/api/profile":
            mk = (parse_qs(u.query).get("market") or [""])[0].strip().lower() or None
            sym = normalize_symbol((parse_qs(u.query).get("symbol") or [""])[0])
            if not sym:
                return self._send(400, json.dumps({"error": "缺少 symbol"}, ensure_ascii=False))
            try:
                from tools.profile import profile as _prof
                from tools.validate import find_cached, read_csv
                p = find_cached(ROOT / "data_cache", sym, mk)
                if p is None and mk:
                    alt = find_cached(ROOT / "data_cache", sym)
                    if alt is not None:
                        owner = alt.name.split("_")[0]
                        return self._send(404, json.dumps(
                            {"error": f"{sym} 的数据属于 {owner} 市场，不是 {mk}。请把市场改成 {owner}。"},
                            ensure_ascii=False))
                if p is None:
                    return self._send(404, json.dumps(
                        {"error": f"数据里没有 {sym}，先上传或拉取"}, ensure_ascii=False))
                return self._send(200, json.dumps(_prof(read_csv(p)), ensure_ascii=False))
            except (OSError, ValueError) as e:
                return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
        if path == "/api/md":
            name = (parse_qs(u.query).get("name") or [""])[0]
            try:
                return self._send(200, json.dumps({"name": name, "content": read_md(name)},
                                                  ensure_ascii=False))
            except (ValueError, OSError) as e:
                return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        if path.startswith("/api/job/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            return self._send(200, json.dumps(job or {"error": "没有这个任务"}, ensure_ascii=False))
        fn = ROUTES_GET.get(path)
        if fn:
            try:
                return self._send(200, json.dumps(fn(), ensure_ascii=False))
            except OSError as e:
                return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        payload = {}
        if length:
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                return self._send(400, json.dumps({"error": "JSON 解析失败"}))
        try:
            if path == "/api/cards":
                return self._send(200, json.dumps(save_card(payload), ensure_ascii=False))
            if path == "/api/report":
                raw = (payload.get("symbol") or "").strip().upper()
                sym = normalize_symbol(raw, (payload.get("market") or "").lower()) or raw
                try:
                    from datetime import date as _date
                    from tools.stock_report import build_report, report_filename
                    from tools.validate import find_cached, read_csv
                    mk2 = (payload.get("market") or "").strip().lower() or None
                    path_ = find_cached(ROOT / "data_cache", sym, mk2)
                    if path_ is None and mk2:
                        alt2 = find_cached(ROOT / "data_cache", sym)
                        if alt2 is not None:
                            owner2 = alt2.name.split("_")[0]
                            return self._send(404, json.dumps(
                                {"error": f"{sym} 的数据属于 {owner2} 市场，不是 {mk2}。请把市场改成 {owner2}。"},
                                ensure_ascii=False))
                    if path_ is None:
                        return self._send(404, json.dumps(
                            {"error": f"数据里没有 {sym}，先拉取或上传"}, ensure_ascii=False))
                    rows = read_csv(path_)
                    market = path_.name.split("_")[0]
                    lg = (payload.get("lang") or "zh").lower()
                    lg = "en" if lg.startswith("en") else "zh"
                    md = build_report(rows, sym, market, path_.name, lang=lg)
                    out = ROOT / "reports" / report_filename(sym, path_.name.split("_")[0], lg)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(md, encoding="utf-8")
                    return self._send(200, json.dumps(
                        {"ok": True, "symbol": sym, "markdown": md,
                         "path": str(out.relative_to(ROOT)), "chars": len(md)},
                        ensure_ascii=False))
                except (OSError, ValueError, KeyError) as e:
                    return self._send(500, json.dumps(
                        {"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
            if path == "/api/fetch":
                r = fetch_symbol(payload.get("symbol", ""), payload.get("market", "us"),
                                 payload.get("start", "2010-01-01"),
                                 payload.get("end", "2025-12-31"),
                                 payload.get("proxy", ""))
                return self._send(200 if r.get("ok") else 400,
                                  json.dumps(r, ensure_ascii=False))
            if path == "/api/upload":
                ok, info = ingest_csv(payload.get("content", ""), payload.get("market", ""),
                                      payload.get("symbol", ""))
                return self._send(200 if ok else 400,
                                  json.dumps(dict(ok=ok, **info), ensure_ascii=False))
            if path == "/api/run":
                cid = payload.get("id")
                if not cid or not (CARDS / f"{cid}.json").exists():
                    return self._send(400, json.dumps({"error": "找不到这张卡"}))
                if any(j["status"] == "running" for j in JOBS.values()):
                    return self._send(429, json.dumps(
                        {"error": "已有任务在跑，等它结束"}, ensure_ascii=False))
                return self._send(200, json.dumps({"job": start_run(cid)}))
        except ValueError as e:
            return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))


def main():
    import webbrowser
    CARDS.mkdir(parents=True, exist_ok=True)
    url = f"http://{HOST}:{PORT}"
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        print(f"端口 {PORT} 被占用（可能研究台已经开着了）：{e}")
        print(f"直接打开浏览器访问 {url} 即可；若要重启，先关掉已有的那个窗口。")
        webbrowser.open(url)
        input("按回车关闭本窗口…")
        return

    print(f"研究台已启动：{url}")
    print("浏览器会自动打开。这个窗口就是服务本体，关掉它即停止。")
    if "--open" in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()