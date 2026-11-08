#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入卫生测试：项目本身只应该依赖 pandas。

为什么需要它
    data/us.py 原来是 `import yfinance as yf` 写在文件顶部，
    于是任何 `import data.registry` 的人都必须装 yfinance。
    CI 上直接挂在 `ModuleNotFoundError: No module named 'yfinance'`。
    第三方网络库（yfinance / akshare / requests）应该只在实际拉数据时导入。

这个测试用一个子进程把三个库「屏蔽掉」（sys.modules[name] = None），
再 import 项目模块；如果能导入成功，说明导入链是干净的。
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BLOCKED = ("yfinance", "akshare", "requests")

SNIPPET = """
import sys
sys.path.insert(0, {root!r})
for name in {blocked!r}:
    sys.modules[name] = None          # 之后任何 import 都会 ImportError

import data.registry
import data.us, data.cn, data.crypto
import app.server
from tools import validate, profile, stock_report, cross_section
print("OK")
"""


class TestImportHygiene(unittest.TestCase):

    def test_project_imports_without_network_libs(self):
        code = SNIPPET.format(root=str(ROOT), blocked=list(BLOCKED))
        r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(
            r.returncode, 0,
            "项目在缺少第三方网络库时无法导入（说明有模块级 import）：\n"
            + (r.stderr or r.stdout)[-1500:])
        self.assertIn("OK", r.stdout)

    def test_no_module_level_network_imports(self):
        """静态拦截：data/*.py 顶部不允许出现这三个库。"""
        offenders = []
        for p in (ROOT / "data").glob("*.py"):
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                # 只看顶格（模块级）的 import；函数内缩进的属于延迟导入，允许
                if line[:1] in (" ", "\t") or not line.strip():
                    continue
                s = line.strip()
                if s.startswith(("import ", "from ")) and any(
                        s.split()[1].split(".")[0] == b for b in BLOCKED):
                    offenders.append(f"{p.name}:{i} {s}")
        self.assertEqual(offenders, [], "这些行应改为函数内延迟导入：\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)