#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""工具清单端点测试 + 禁止硬编码个人路径。

事故背景
    app/server.py 的 tools() 里曾经硬编码了 `C:\Users\lenovo\...` 作为 referee 目录，
    并且在同一行之前引用了还没赋值的 p.name —— 一旦调用就 NameError。
    公开仓库里出现作者的个人路径也是不该的。
"""

import unittest
from pathlib import Path

from app import server as S

ROOT = Path(__file__).resolve().parent.parent


class TestToolsEndpoint(unittest.TestCase):

    def test_returns_entries(self):
        r = S.tools()
        self.assertGreaterEqual(len(r["tools"]), 5)
        self.assertGreaterEqual(r["test_files"], 10)

    def test_every_listed_file_exists(self):
        """清单里列出的文件必须真的在仓库里，否则用户点开是死链。"""
        missing = [t["path"] for t in S.tools()["tools"] if not t["exists"]]
        self.assertEqual(missing, [], f"这些文件不存在：{missing}")

    def test_lines_are_counted(self):
        r = S.tools()
        with_lines = [t for t in r["tools"] if t["lines"] > 0]
        self.assertGreaterEqual(len(with_lines), 5, "所有工具的代码行数都是 0，说明路径解析错了")


class TestNoPersonalPaths(unittest.TestCase):
    """仓库里（含文档与脚本）不许出现作者个人绝对路径。"""

    # 拆开写，免得这个测试把自己源码里的字符串当成命中
    PATTERNS = ("C:" "\\Users\\lenovo", "D:" "\\quant-agent")
    SKIP_DIRS = {".git", ".venv", "data_cache", "reports", "__pycache__"}

    def test_no_absolute_personal_paths(self):
        hits = []
        for p in ROOT.rglob("*"):
            if not p.is_file() or (set(p.parts) & self.SKIP_DIRS):
                continue
            if p.resolve() == Path(__file__).resolve():
                continue
                continue
            if p.suffix.lower() not in (".py", ".md", ".bat", ".yml", ".yaml",
                                        ".json", ".txt", ".html", ""):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in self.PATTERNS:
                if pat in text:
                    hits.append(f"{p.relative_to(ROOT)} <- {pat}")
        self.assertEqual(hits, [], "发现了硬编码的个人路径：\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main(verbosity=2)