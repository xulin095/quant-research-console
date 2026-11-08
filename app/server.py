#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""量化研究控制台（本地网页，零新依赖）。

定位
    它不是"投资建议仪表盘"，而是**研究仪器的操作面板**：
    写卡 → 跑 → 看判定 → 看账本。把 PowerShell 里的命令变成点按钮。

安全
    · 只监听 127.0.0.1，不对外开放
    · 不联网调用任何外部服务（数据都在本地 data_cache）
    · 页面顶部固定显示"研究工具，不构成投资建议"

启动
    cd D:\quant-agent
    .\.venv\Scripts\python.exe -m app.server
    浏览器打开 http://127.0.0.1:8765
    或者直接双击项目根目录的 启动研究台.bat
"""

import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
REGISTRY = ROOT / "registry.jsonl"
STATIC = Path(__file__).resolve().parent / "static"
HOST, PORT = "127.0.0.1", 8765

REQUIRED = ("id", "kind", "direction", "lookback", "top_n", "mechanism")
JOBS = {}


# ---------------------------------------------------------------- 数据层
def list_cards():
    out = []
    if not CARDS.is_dir():
        return out
    for p in sorted(CARDS.glob("*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        c["_file"] = p.name
        out.append(c)
    return out


def save_card(card):
    """保存卡片。会做最基本的护栏，防止把参数写成无意义的组合。"""
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
    p = CARDS / f"{cid}.json"
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
        frozen = ("lookback", "direction", "holdout")
        changed = [k for k in frozen if k in old and str(old[k]) != str(card.get(k))]
        if changed:
            raise ValueError(
                "这张卡已经跑过了，参数冻结：" + "、".join(changed) +
                "。要试新参数，请用新的 id 新建一张卡（旧卡留在账本里）。")
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": str(p.name)}


def read_registry(limit=200):
    if not REGISTRY.exists():
        return {"entries": [], "total": 0, "pass_rate": 0.0}
    rows = []
    with REGISTRY.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    total = len(rows)
    passed = sum(1 for r in rows if r.get("verdict") == "PASS")
    return {"entries": rows[-limit:][::-1], "total": total,
            "pass_rate": round(passed / total, 3) if total else 0.0,
            "passed": passed}


def data_status():
    cache = ROOT / "data_cache"
    files = list(cache.glob("*.csv")) if cache.is_dir() else []
    uni = {}
    up = ROOT / "universe.json"
    if up.exists():
        try:
            uni = json.loads(up.read_text(encoding="utf-8"))
        except ValueError:
            uni = {}
    return {
        "cache_files": len(files),
        "universe_size": len(uni.get("success", [])) if uni else 0,
        "coverage": uni.get("coverage"),
        "delisted_ok": uni.get("delisted_ok"),
        "held_out_from": "2021-01-01",
    }


# ---------------------------------------------------------------- 跑卡
def start_run(card_id):
    job = uuid.uuid4().hex[:8]
    JOBS[job] = {"status": "running", "output": "", "started": time.time(),
                 "id": card_id, "verdict": None}
    threading.Thread(target=_run, args=(job, card_id), daemon=True).start()
    return job


def _run(job, card_id):
    path = CARDS / f"{card_id}.json"
    cmd = [sys.executable, "-m", "tools.audit", str(path)]
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        JOBS[job]["output"] = (p.stdout or "") + (p.stderr or "")
        JOBS[job]["status"] = "done"
        JOBS[job]["exit_code"] = p.returncode
        # 判定从账本里取最后一条，比解析 stdout 可靠
        reg = read_registry(limit=1)
        if reg["entries"]:
            JOBS[job]["verdict"] = reg["entries"][0].get("verdict")
            JOBS[job]["metrics"] = reg["entries"][0].get("metrics", {})
    except subprocess.TimeoutExpired:
        JOBS[job]["status"] = "timeout"
        JOBS[job]["output"] = "超时（>30 分钟）"
    except OSError as e:
        JOBS[job]["status"] = "error"
        JOBS[job]["output"] = f"启动失败：{e}"


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):      # 安静一点
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
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            f = STATIC / "index.html"
            return self._send(200, f.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path == "/api/cards":
            return self._send(200, json.dumps({"cards": list_cards()}, ensure_ascii=False))
        if path == "/api/registry":
            return self._send(200, json.dumps(read_registry(), ensure_ascii=False))
        if path == "/api/status":
            return self._send(200, json.dumps(data_status(), ensure_ascii=False))
        if path.startswith("/api/job/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            if not job:
                return self._send(404, json.dumps({"error": "没有这个任务"}))
            return self._send(200, json.dumps(job, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = self.path.split("?")[0]
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
                running = [j for j in JOBS.values() if j["status"] == "running"]
                if running:
                    return self._send(429, json.dumps(
                        {"error": "已有任务在跑，等它结束（跑一张卡可能要几分钟）"}))
                return self._send(200, json.dumps({"job": start_run(cid)}))
        except ValueError as e:
            return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        return self._send(404, json.dumps({"error": "not found"}))


def main():
    if not CARDS.is_dir():
        CARDS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"研究控制台已启动：http://{HOST}:{PORT}")
    print("按 Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
