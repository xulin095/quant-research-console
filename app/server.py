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
    GET  /api/md?name=xxx.md   读取报告原文（白名单）
    POST /api/run {id}         跑卡
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
    ("referee/verify.py", "13 条机械验收（独立于项目代码）", "python referee/verify.py --root D:\\quant-agent"),
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
        p = (ROOT.parent / "referee" / p.name) if rel.startswith("referee/") else (ROOT / rel)
        if rel.startswith("referee/"):
            p = Path(r"C:\Users\lenovo\Documents\deepseek-harness\default-workspace") / rel
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


def read_md(name):
    if name not in ALLOWED_MD:
        raise ValueError("不在白名单里")
    p = ROOT / name
    if not p.is_file():
        raise ValueError("文件不存在")
    return p.read_text(encoding="utf-8", errors="replace")


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