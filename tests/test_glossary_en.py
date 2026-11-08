#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""术语库双语完整性测试：英文模式下不该看到中文解释。"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = ROOT / "glossary.json"
PAGE = ROOT / "app" / "static" / "index.html"
CJK = re.compile(r"[\u4e00-\u9fff]")


class TestGlossaryEnglish(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
        cls.entries = cls.data["entries"]

    def test_every_entry_has_english(self):
        missing = [e["term"] for e in self.entries
                   if not e.get("term_en") or not e.get("plain_en")]
        self.assertEqual(missing, [], f"这些词条缺英文：{missing}")

    def test_english_fields_have_no_chinese(self):
        """英文字段里不该出现中文（出现说明是复制粘贴没翻）。"""
        bad = []
        for e in self.entries:
            for f in ("term_en", "plain_en", "analogy_en", "why_en"):
                v = e.get(f)
                if v and CJK.search(v):
                    bad.append(f"{e['term']}.{f}: {v[:60]}")
        self.assertEqual(bad, [], "英文字段里混入了中文：\n" + "\n".join(bad[:10]))

    def test_analogy_and_why_pairing(self):
        """有中文类比/含义的，英文也必须有（否则英文模式会缺块）。"""
        bad = []
        for e in self.entries:
            if e.get("analogy") and not e.get("analogy_en"):
                bad.append(e["term"] + ".analogy_en")
            if e.get("why") and not e.get("why_en"):
                bad.append(e["term"] + ".why_en")
        self.assertEqual(bad, [], f"缺对照英文字段：{bad}")

    def test_frontend_uses_language_aware_getters(self):
        html = PAGE.read_text(encoding="utf-8")
        for token in ("function gv(e, f)", "function gTerm(e)", "function gLabel(f)"):
            self.assertIn(token, html, f"前端缺少 {token}")
        # 渲染时不能再直接读中文字段
        body = re.search(r"function renderGlossary\(q\)\{(.*?)\n\}", html, re.S)
        self.assertIsNotNone(body)
        self.assertIn("gv(e,'plain')", body.group(1))
        self.assertNotIn("esc(e.plain)", body.group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)