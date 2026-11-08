#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
第 0 棒交付：机械裁判（verify.py）

作用
    把 prompts-v2.md 里那 12 条验收标准，变成一组不需要人判断的检查。
    跑完直接得到一张 PASS / FAIL 表，每条都带证据。

铁律
    本文件 **不 import 被测项目的任何模块**，只做：读文件、grep、起子进程。
    这样开发者写得再"自洽"，也糊弄不过去。

用法
    python verify.py --root ..\quant-agent                 # 静态检查 + 运行时检查（用缓存，不发网络请求）
    python verify.py --root ..\quant-agent --net           # additionally 跑一遍真实拉数据（要联网）
    python verify.py --root ..\quant-agent --only 1,3,4    # 只跑指定编号

退出码
    0  12 条全 PASS
    1  有 FAIL（SKIP 不算通过，会单独列出）
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------- 契约常量
EXPECTED_FILES = [
    "README.md", "requirements.txt", "config.py", "main.py",
    "indicators.py", "backtest.py", "risk.py", "report.py",
    "data/__init__.py", "data/base.py", "data/registry.py",
    "data/us.py", "data/cn.py", "data/crypto.py",
    "tests/__init__.py", "tests/test_core.py",
    "reports/.gitkeep", "data_cache/.gitkeep",
]

# 不属于 16 文件契约、但**必须允许**存在的东西。
# research.md / design.md / test-report.md 是前三棒各自的过程交付物，落在项目根目录很正常；
# 把它们算成"多余文件"会让第 3 棒一开始就红。
ALLOW_EXTRA = {
    ".gitignore", ".gitattributes", "reports/__init__.py",
    "research.md", "design.md", "test-report.md", "ROADMAP-v2.md",
    # v2 新增（开源与文档）
    "README.md", "README.zh-CN.md", "LICENSE", "CONTRIBUTING.md",
    "RUNBOOK.md", "glossary.json", "启动研究台.bat",
    # 项目自身的运行产物（账本与结论数据，随仓库发布）
    "profiles.json", "registry.jsonl", "results.json", "universe.json",
}

# v2 允许新增的目录（工具、策略、数据仓库）。v1 的 16 文件契约仍然有效，
# 但这些目录里的东西不该被算成"多余文件"。
ALLOW_PREFIXES = ("tools/", "strategies/", "store/", "tests/",
                  "referee/", "docs/", ".github/", "app/", "cards/", "samples/")

# v1 回测报告与 v2 分析报告是两种文档，各自有一套章节；报告只要满足其中一套即可
CHAPTER_SETS = [
    ["## 1. 基本信息", "## 2. 近期价格", "## 3. 回测结果", "## 4. 交易记录", "## 5. 风险提示"],
    ["## 1. 数据体检", "## 2. 结构判断", "## 3. 能做什么", "## 4. 已知风险", "## 5. 免责声明"],
    ["## 1. Data health", "## 2. Structural verdict", "## 3. What is worth testing",
     "## 4. Known risks", "## 5. Disclaimer"],
]
CHAPTERS = CHAPTER_SETS[0]   # 向后兼容旧引用

BANNED = ["建议买入", "建议卖出", "推荐", "看好", "一定涨", "一定跌", "目标价", "值得买"]

REQUIRED_PHRASE_SETS = [
    ["只代表过去，不代表未来", "不要用实盘资金直接照抄"],
    ["describes the past, not the future", "Do not trade real money"],
]
REQUIRED_PHRASES = REQUIRED_PHRASE_SETS[0]

RISK_LABEL_SETS = [
    ["总收益率", "年化收益率", "最大回撤", "夏普比率", "胜率", "交易次数"],   # v1 回测报告
    ["年化收益", "年化波动", "最大回撤"],                                  # v2 分析报告
    ["Annualised return", "Annualised volatility", "Maximum drawdown"],     # 英文版
]
RISK_LABELS = RISK_LABEL_SETS[0]

# config.py 必须出现的字面量（弱检查：只证明写了，不证明用了）
CONFIG_LITERALS = {
    "初始资金 100000": "100000",
    "手续费 0.0003": "0.0003",
    "滑点 0.0005": "0.0005",
    "无风险利率 0.02": "0.02",
    "年交易日 252": "252",
    "最少数据 60": "60",
}

DANGER_PATTERNS = [
    (r"\bimport\s+talib|\bfrom\s+talib\b", "import 了 ta-lib（本轮禁用）"),
    (r"\bimport\s+matplotlib|\bfrom\s+matplotlib\b", "import 了 matplotlib（v1 不画图）"),
    (r"\bapi_key\s*=", "出现 api_key 赋值"),
    (r"\bAPI_KEY\s*=", "出现 API_KEY 赋值"),
    (r"\bsecret\w*\s*=", "出现 secret 赋值"),
    (r"\bpassword\s*=", "出现 password 赋值"),
    (r"券商|下单接口|place_order\b|create_order\b|broker", "出现交易/券商相关关键词"),
]


# ---------------------------------------------------------------- 小工具
def read_text(p):
    try:
        return Path(p).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def py_files(root):
    root = Path(root)
    out = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or "__pycache__" in rel or rel.startswith(".venv"):
            continue
        out.append(p)
    return out


def newest_report(root):
    d = Path(root) / "reports"
    if not d.is_dir():
        return None
    cands = [p for p in d.glob("*.md") if p.name != ".gitkeep"]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def run_cli(root, args, timeout=300):
    """跑 main.py，返回 (exit_code, stdout, stderr)。跑不起来返回 (None, '', 原因)。"""
    if not (Path(root) / "main.py").is_file():
        return None, "", "main.py 还不存在"
    try:
        p = subprocess.run(
            [sys.executable, "main.py"] + args,
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return None, "", f"超时（>{timeout}s）"
    except OSError as e:
        return None, "", f"启动失败：{e}"


# ---------------------------------------------------------------- 各条检查
def check_1_files(root):
    root = Path(root)
    missing = [f for f in EXPECTED_FILES if not (root / f).exists()]
    present = set()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or "__pycache__" in rel or rel.startswith("data_cache/") or rel.startswith(".venv"):
            continue
        if rel.startswith("reports/") and rel != "reports/.gitkeep":
            continue
        present.add(rel)
    extra = sorted(x for x in (present - set(EXPECTED_FILES) - ALLOW_EXTRA)
                     if not x.startswith(ALLOW_PREFIXES))

    # 两个问题必须一起报：原来 missing 非空就提前 return，导致 extra 被完全藏起来，
    # 等文件补齐了才突然冒出来，浪费一轮返工。
    problems = []
    if missing:
        problems.append(f"缺 {len(missing)} 个路径（契约 16 文件 + 2 个 .gitkeep）：{', '.join(missing[:6])}"
                        + ("…" if len(missing) > 6 else ""))
    if extra:
        problems.append(f"多出 {len(extra)} 个不该有的文件：{', '.join(extra[:6])}"
                        + ("…" if len(extra) > 6 else ""))
    if problems:
        return "FAIL", "；".join(problems)
    return "PASS", "18 个路径齐全（16 文件 + 2 个 .gitkeep），无多余文件"


def check_2_report_exists(root):
    rp = newest_report(root)
    if rp is None:
        return "FAIL", "reports/ 里没有 .md 报告"
    text = read_text(rp) or ""
    nbytes = rp.stat().st_size
    nchars = len(text)
    # 口径说明：st_size 是 UTF-8 字节数，len(text) 是字符数。中文报告两者差 ~1/3，
    # 原来把字符数标成「字节」会让人核对不上（第 4 棒就是靠这个抓到的）。
    if len(text.strip()) < 300:
        return "FAIL", f"{rp.name} 只有 {nchars} 字符 / {nbytes} 字节，像是空报告"
    return "PASS", f"{rp.name}（{nchars} 字符 / {nbytes} 字节）"


def all_reports(root):
    """所有报告，不只最新一份。第 4 棒抓到过这个坑：只看最新份，写错/写空的那份会被漏掉。"""
    d = Path(root) / "reports"
    if not d.is_dir():
        return []
    return [p for p in sorted(d.glob("*.md")) if p.name != ".gitkeep"]


def _each_report(root):
    """逐份检查的小工具：返回 (报告列表, 每份的文本)。"""
    repos = all_reports(root)
    return repos, [(rp, read_text(rp) or "") for rp in repos]


def check_3_chapters(root):
    repos, pairs = _each_report(root)
    if not repos:
        return "SKIP", "没有报告，跳过"
    bad = []
    for rp, text in pairs:
        best = min(CHAPTER_SETS, key=lambda cs: sum(1 for c in cs if c not in text))
        missing = [c for c in best if c not in text]
        if len(missing) == len(best):          # 一套都不满足
            bad.append(f"{rp.name} 不匹配任何已知报告格式")
        elif missing:
            bad.append(f"{rp.name} 缺 {', '.join(missing)}")
    if bad:
        return "FAIL", f"{len(bad)}/{len(repos)} 份报告缺章节：{'；'.join(bad[:2])}"
    return "PASS", f"{len(repos)} 份报告章节齐全（v1 回测 / v2 分析 / 英文版任一）"


def check_4_banned(root):
    repos, pairs = _each_report(root)
    if not repos:
        return "SKIP", "没有报告，跳过"
    hits = []
    for rp, text in pairs:
        for line_no, line in enumerate(text.splitlines(), 1):
            for w in BANNED:
                if w in line:
                    hits.append(f"{rp.name} 第{line_no}行「{w}」")
    if hits:
        return "FAIL", f"{len(hits)} 处禁词：{'; '.join(hits[:4])}" + ("…" if len(hits) > 4 else "")
    return "PASS", f"{len(repos)} 份报告，8 个禁词零命中"


def check_5_required(root):
    repos, pairs = _each_report(root)
    if not repos:
        return "SKIP", "没有报告，跳过"
    bad = []
    for rp, text in pairs:
        best = min(REQUIRED_PHRASE_SETS,
                   key=lambda ps: sum(1 for x in ps if x not in text))
        missing = [x for x in best if x not in text]
        if len(missing) == len(best):
            bad.append(f"{rp.name} 缺免责声明（中英两套都没有）")
        elif missing:
            bad.append(f"{rp.name} 缺 {', '.join(missing)}")
    if bad:
        return "FAIL", "；".join(bad[:2])
    return "PASS", f"{len(repos)} 份报告都含两句必选文本"


def check_6_risk_table(root):
    repos, pairs = _each_report(root)
    if not repos:
        return "SKIP", "没有报告，跳过"
    bad = []
    for rp, text in pairs:
        best = min(RISK_LABEL_SETS, key=lambda ls: sum(1 for l in ls if l not in text))
        missing = [l for l in best if l not in text]
        if len(missing) == len(best):
            bad.append(f"{rp.name} 没有任何已知的风险指标组合")
        elif missing:
            bad.append(f"{rp.name} 缺风控项 {', '.join(missing)}")
        elif ("样本" not in text) and ("Sample" not in text):
            bad.append(f"{rp.name} 没写样本交易日数（防过拟合要求）")
    if bad:
        return "FAIL", "；".join(bad[:2])
    return "PASS", f"{len(repos)} 份报告：6 个风控数字 + 样本天数齐全"
def check_7_config(root):
    p = Path(root) / "config.py"
    if not p.is_file():
        return "FAIL", "config.py 不存在"
    text = read_text(p) or ""
    missing = [k for k, v in CONFIG_LITERALS.items() if v not in text]
    if missing:
        return "FAIL", f"config.py 缺这些参数：{', '.join(missing)}"
    return "PASS", f"{len(CONFIG_LITERALS)} 个关键参数都在（字面量检查，弱）"


def check_8_dangerous(root):
    hits = []
    for p in py_files(root):
        rel = p.relative_to(Path(root)).as_posix()
        if rel.startswith(("tests/", "referee/")):
            continue          # 测试与裁判脚本里出现关键词是正常的（它们自己就定义了关键词表）
        text = read_text(p) or ""
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat, desc in DANGER_PATTERNS:
                if re.search(pat, line):
                    hits.append(f"{rel}:{line_no} {desc}")
    if hits:
        return "FAIL", f"{len(hits)} 处需人工确认：{'; '.join(hits[:5])}"
    return "PASS", f"扫了 {len(py_files(root))} 个 .py，无 ta-lib / matplotlib / 密钥 / 交易调用"


def check_9_tests(root):
    tdir = Path(root) / "tests"
    if not tdir.is_dir():
        return "FAIL", "没有 tests/ 目录"
    has_pytest = False
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                           capture_output=True, text=True, timeout=60)
        has_pytest = p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        has_pytest = False

    cmd = [sys.executable, "-m", "pytest", "tests", "-q"] if has_pytest else \
          [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    try:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "SKIP", f"测试跑不起来：{e}"

    full = (r.stdout or "") + (r.stderr or "")
    tail = full.strip().splitlines()[-1] if full.strip() else ""
    if r.returncode != 0:
        return "FAIL", f"测试失败（{'pytest' if has_pytest else 'unittest'}）：{tail[:160]}"
    # 注意：必须扫全文，不能只看最后一行。空 tests/ 目录下 unittest 会打印 "Ran 0 tests" 然后
    # 以 "OK" 结尾并返回 0 —— 只看尾行就会把「一个用例都没跑」误判成「全绿」。
    if "no tests ran" in full or "Ran 0 test" in full or "collected 0 items" in full:
        return "FAIL", "测试是 0 个用例，等于没测（tests/ 里没有真正的 test_*.py）"
    return "PASS", f"{'pytest' if has_pytest else 'unittest'} 全绿：{tail[:120]}"


def check_10_exit_codes(root, do_net=False):
    if not (Path(root) / "main.py").is_file():
        return "SKIP", "main.py 还不存在"
    notes, bad = [], 0

    def must_fail(code, err, label, want):
        """失败路径的统一判定：退出码对、没抛栈、且真的打了一行中文原因。

        只查退出码不够 —— 程序因为别的错（比如网络挂了）也会返回 1，
        那种"碰巧对了"不能算通过，所以要求 stderr 有中文说明。
        """
        nonlocal bad
        has_cn = bool(re.search(r"[\u4e00-\u9fff]", err or ""))
        ok = (code == want) and ("Traceback" not in (err or "")) and has_cn
        detail = (err or "").strip().splitlines()
        notes.append(f"{label}→退出码{code}{'✓' if ok else '✗'}" + (f"「{detail[-1][:40]}」" if detail else "（stderr 为空）"))
        if not ok:
            bad += 1

    code, _, err = run_cli(root, ["--symbol", "AAPL", "--market", "us",
                                 "--start", "2025-12-01", "--end", "2025-12-20"])
    if code is None:
        return "SKIP", err
    must_fail(code, err, "样本不足", 1)

    code2, _, err2 = run_cli(root, ["--symbol", "AAPL", "--market", "us",
                                   "--start", "2025-01-01", "--end", "2024-01-01"])
    must_fail(code2, err2, "start>end", 2)

    code3, _, err3 = run_cli(root, ["--symbol", "AAPL", "--market", "jp",
                                   "--start", "2024-01-01", "--end", "2025-01-01"])
    must_fail(code3, err3, "非法市场", 2)

    if do_net:
        code4, _, err4 = run_cli(root, ["--symbol", "AAPL", "--market", "us",
                                       "--start", "2024-01-01", "--end", "2025-12-31"], timeout=600)
        ok4 = code4 == 0 and "Traceback" not in err4
        notes.append(f"正常跑→{code4}{'✓' if ok4 else '✗'}")
        bad += 0 if ok4 else 1
    else:
        notes.append("正常跑→未测（加 --net）")

    return ("FAIL" if bad else "PASS"), "；".join(notes)


def count_lines(path):
    """数行数。用 with 关句柄 —— 缓存目录里可能躺着几十个 CSV，句柄泄漏在 Windows 上会锁文件。"""
    n = 0
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for _ in f:
            n += 1
    return n


def check_11_cache(root):
    d = Path(root) / "data_cache"
    if not d.is_dir():
        return "FAIL", "没有 data_cache/ 目录"
    pat = re.compile(r"^(us|cn|crypto)_[A-Za-z0-9._-]+_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$")
    csvs = list(d.glob("*.csv"))
    if not csvs:
        return "FAIL", "没有缓存 CSV（说明没真拉过数据，或缓存没落地）"
    bad = [p.name for p in csvs if not pat.match(p.name)]
    if bad:
        return "FAIL", f"{len(bad)} 个缓存文件名不合规（应为 {{market}}_{{symbol}}_{{start}}_{{end}}.csv）：{bad[:3]}"
    # 行数门槛用 61：CSV 首行是表头，61 行 = 60 个交易日，和"最少 60 个交易日"严格对齐。
    # 用 60 会让"表头 + 59 天"混过去，然后 audit_recalc 一跑就报数据不足。
    small = [p.name for p in csvs if count_lines(p) < 61]
    if small:
        return "FAIL", f"{len(small)} 个缓存数据不足 60 个交易日（含表头不足 61 行）：{small[:3]}"
    return "PASS", f"{len(csvs)} 个缓存文件，命名与行数都合规"


NAME_RE = re.compile(r"^(?P<symbol>[A-Za-z0-9._-]+?)_(?P<market>us|cn|crypto)(?=_|\.|$)")


CACHE_IN_REPORT = re.compile(r"`([a-z]+_[A-Za-z0-9._-]+_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv)`")


def _cache_for(root, report_path):
    """找到报告**实际使用**的那份缓存。

    不能按名字猜：同一只票可能有多份不同区间的缓存（2015-2025 / 2020-2025 / ...），
    猜错就会出现「报告数字与复算不符」的假警报 —— 我踩过一次。
    报告头部写了数据文件名，从这里读最可靠。
    """
    d = Path(root) / "data_cache"
    text = read_text(Path(report_path)) or ""
    m = CACHE_IN_REPORT.search(text)
    if m:
        p = d / m.group(1)
        if p.is_file():
            return p
    nm = NAME_RE.match(Path(report_path).name)
    if nm:
        hits = sorted(d.glob(f"{nm.group('market')}_{nm.group('symbol')}_*.csv"))
        if hits:
            return hits[-1]
    hits = sorted(d.glob("*.csv"))
    return hits[-1] if hits else Path("")


def audit_one(root, report_path, script):
    """复算单份报告。返回 (ok, 消息)。

    v2 的分析报告里没有回测指标，用 audit_recalc 比六项风控数字必然「对不上」。
    所以先按内容判定报告类型：分析报告用 profile_check（结构数字对账），
    v1 回测报告才用 audit_recalc（六项风控对账）。
    """
    rp = Path(report_path)
    text = read_text(rp) or ""
    is_analysis = ("结构判断" in text or "Structural verdict" in text
                   or "数据体检" in text or "Data health" in text)
    if is_analysis:
        script2 = Path(__file__).with_name("profile_check.py")
        try:
            r2 = subprocess.run([sys.executable, str(script2),
                                 "--csv", str(_cache_for(root, rp)), "--report", str(rp)],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, f"分析报告复算失败：{e}"
        if r2.returncode == 0:
            return True, f"{rp.name} 结构与独立复算一致"
        return False, f"{rp.name} 分析报告对不上：{(r2.stdout or r2.stderr)[-160:]}"
    m = NAME_RE.match(rp.name)
    extra = []
    if m:
        extra = ["--market", m.group("market"), "--symbol", m.group("symbol")]
    else:
        n_cache = len(list((Path(root) / "data_cache").glob("*.csv")))
        if n_cache != 1:
            return None, (f"报告名 {rp.name} 没带市场与代码，而缓存有 {n_cache} 个，无法确定该跟哪个比")

    try:
        r = subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--report", str(rp)] + extra,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"复算脚本跑不起来：{e}"

    out = (r.stdout or "").strip()
    if r.returncode == 0:
        which = f"{m.group('market')}_{m.group('symbol')}" if m else "唯一缓存"
        return True, f"{rp.name} 6 项一致（对 {which}）"
    fails = [l.strip() for l in out.splitlines()
             if l.rstrip().endswith("FAIL") and not l.strip().startswith("结论")]
    if fails:
        return False, f"{rp.name} {len(fails)} 项对不上： " + " ; ".join(fails[:3])
    return False, f"{rp.name} 复算失败： " + out.replace("\n", " ")[-160:]


def check_12_audit(root):
    """**每一份**报告都要和它自己市场的缓存对得上。

    原来只看最新一份 —— 结果 AAPL 报告写错了、600519 报告是对的，检查照样 PASS。
    这个漏洞是靠"多市场都跑了一遍"才暴露出来的，所以改成逐份审。
    """
    d = Path(root) / "reports"
    if not d.is_dir():
        return "SKIP", "没有 reports 目录，跳过"
    reports = [p for p in sorted(d.glob("*.md")) if p.name != ".gitkeep"]
    if not reports:
        return "SKIP", "没有报告，跳过"

    script = Path(__file__).with_name("audit_recalc.py")
    ok_msgs, bad_msgs, skipped = [], [], []
    for rp in reports:
        ok, msg = audit_one(root, rp, script)
        if ok is None:
            skipped.append(msg)
        elif ok:
            ok_msgs.append(msg)
        else:
            bad_msgs.append(msg)

    if bad_msgs:
        return "FAIL", f"{len(bad_msgs)}/{len(reports)} 份报告对不上： " + " ; ".join(bad_msgs[:3])
    if skipped:
        return "SKIP", "；".join(skipped[:3])
    return "PASS", f"{len(ok_msgs)} 份报告全部与独立复算一致：" + "；".join(ok_msgs[:3])


def check_13_git(root):
    """附加项：核心 4 文件是否被改过（证明"换市场零改核心"）。"""
    root = Path(root)
    if not (root / ".git").is_dir():
        return "SKIP", "不是 git 仓库，无法用 diff 证明（建议第 0 棒先 git init）"
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "SKIP", f"git 跑不起来：{e}"
    dirty = [l[3:] for l in (r.stdout or "").splitlines()
             if l[3:].strip() in ("indicators.py", "backtest.py", "risk.py", "report.py")]
    if dirty:
        return "FAIL", f"核心文件有未提交改动：{', '.join(dirty)}"
    return "PASS", "核心 4 文件无未提交改动"


CHECKS = [
    (1, "文件结构 16+2", check_1_files, False),
    (2, "报告存在且非空", check_2_report_exists, False),
    (3, "5 章标题齐全", check_3_chapters, False),
    (4, "禁词零命中", check_4_banned, False),
    (5, "第5章两句必含", check_5_required, False),
    (6, "风控数字+样本天数", check_6_risk_table, False),
    (7, "config 参数写死", check_7_config, False),
    (8, "无密钥/交易/禁用库", check_8_dangerous, False),
    (9, "测试全绿", check_9_tests, False),
    (10, "退出码三档", check_10_exit_codes, True),
    (11, "缓存命名与行数", check_11_cache, False),
    (12, "报告 vs 独立复算", check_12_audit, False),
    (13, "核心文件零改动(git)", check_13_git, False),
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="机械裁判：12 条验收 + 1 条附加")
    ap.add_argument("--root", default=".", help="项目根目录")
    ap.add_argument("--net", action="store_true", help="额外跑一遍真实拉数据（要联网）")
    ap.add_argument("--only", default=None, help="只跑指定编号，逗号分隔，如 1,3,4")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[错误] 根目录不存在：{root}")
        return 1
    only = {int(x) for x in args.only.split(",")} if args.only else None

    print(f"项目根目录 {root}\n")
    print(f"{'#':<3}{'检查项':<22}{'结果':<6}证据")
    print("-" * 100)

    results = []
    for num, name, fn, needs_net in CHECKS:
        if only and num not in only:
            continue
        try:
            status, detail = fn(root, args.net) if needs_net else fn(root)
        except Exception as e:                                  # 裁判自己不许崩
            status, detail = "FAIL", f"检查过程出错：{type(e).__name__}: {e}"
        results.append((num, name, status, detail))
        print(f"{num:<3}{name:<22}{status:<6}{detail}")

    passed = sum(1 for r in results if r[2] == "PASS")
    failed = [r for r in results if r[2] == "FAIL"]
    skipped = [r for r in results if r[2] == "SKIP"]

    print("-" * 100)
    print(f"PASS {passed} / {len(results)}   FAIL {len(failed)}   SKIP {len(skipped)}")
    if failed:
        print("\n必须先修的：")
        for num, name, _, detail in failed:
            print(f"  #{num} {name} —— {detail}")
    if skipped:
        print("\n没验成的（不算通过）：")
        for num, name, _, detail in skipped:
            print(f"  #{num} {name} —— {detail}")

    return 0 if (passed == len(results) and not failed) else 1


if __name__ == "__main__":
    sys.exit(main())
