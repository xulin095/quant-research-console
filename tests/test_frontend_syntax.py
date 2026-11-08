#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前端语法检查：把 index.html 里的 JS 抽出来交给 node --check。

为什么需要它：一个漏掉的括号会让整个页面白屏 —— 但所有 Python 测试照样全绿。
这类事故只有静态语法检查能拦住（我就是这样白屏过一次）。
没有安装 node 时跳过，不让它变成环境依赖。
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "app" / "static" / "index.html"


def extract_js(text):
    i = text.find("<script>")
    j = text.rfind("</script>")
    if i < 0 or j < 0 or j <= i:
        return None
    return text[i + len("<script>"):j]


class TestFrontendSyntax(unittest.TestCase):

    def setUp(self):
        self.html = PAGE.read_text(encoding="utf-8", errors="replace")

    def test_page_exists_and_has_script(self):
        self.assertTrue(PAGE.is_file(), "index.html 不见了")
        js = extract_js(self.html)
        self.assertIsNotNone(js, "找不到 <script> 块")
        self.assertGreater(len(js), 5000, "JS 太短，可能被写坏了")

    def test_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("没装 node，跳过语法检查")
        js = extract_js(self.html)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "page.js"
            tmp.write_text(js, encoding="utf-8")
            r = subprocess.run([node, "--check", str(tmp)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            self.assertEqual(r.returncode, 0,
                             "前端 JS 语法错误：\n" + (r.stderr or r.stdout)[:800])

    def test_key_views_present(self):
        for vid in ("v-overview", "v-data", "v-reports", "v-paths",
                    "v-cards", "v-ledger", "v-glossary"):
            self.assertIn('id="' + vid + '"', self.html, f"缺少视图 {vid}")

    def test_internal_views_removed(self):
        """「四棒流水线」「工具链」是开发过程的内部逻辑，不该出现在用户界面里。"""
        for gone in ("四棒流水线", "工具链", 'id="v-pipeline"', 'id="v-tools"'):
            self.assertNotIn(gone, self.html, f"不应再展示：{gone}")

    def test_balanced_parens_heuristic(self):
        """粗检查：glossify 调用必须有闭合括号（这就是上次白屏的原因）。"""
        self.assertNotIn("glossify(out.join('\\n');", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)