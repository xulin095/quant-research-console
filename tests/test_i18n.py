#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i18n 覆盖率测试：英文模式下界面不该残留中文。

引擎规则（与 app/static/index.html 内的 trText 一致）：
    1. 整句精确命中（空白已规范化）
    2. 长词条（>=8 字符）自由替换
    3. 短词条只在非中文边界处替换（防止「数据」吃掉「…的数据考它…」）
"""

import json
import re
import unittest
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "app" / "static" / "index.html"
CJK = re.compile(r"[\u4e00-\u9fff]")
SP = re.compile(r"\s+")
# 语言切换按钮里「中文」二字必须保持原样
ALLOW = {"中文"}


def load_dict():
    html = PAGE.read_text(encoding="utf-8")
    m = re.search(r"var I18N_EN = (\{.*?\n\};)", html, re.S)
    assert m, "index.html 里找不到 I18N_EN"
    return json.loads(m.group(1)[:-1]), html


def make_tr(d):
    exact = {SP.sub(" ", k).strip(): v for k, v in d.items()}
    long_keys = sorted([k for k in d if len(k) >= 8], key=len, reverse=True)
    short = [(k, v) for k, v in d.items() if len(k) < 8]

    def tr(s):
        norm = SP.sub(" ", s).strip()
        if norm in exact:
            return exact[norm]
        out = s
        for k in long_keys:
            if k in out:
                out = out.replace(k, d[k])
        for k, v in short:
            out = re.sub(r"(^|[^\u4e00-\u9fff])" + re.escape(k) + r"(?![\u4e00-\u9fff])",
                         lambda mm: mm.group(1) + v, out)
        return out
    return tr


class TestI18nCoverage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d, cls.html = load_dict()
        cls.tr = staticmethod(make_tr(cls.d))   # 否则会被当成绑定方法
        body = cls.html[cls.html.index("<body>"):cls.html.index("</body>")]
        cls.body = re.sub(r"<script>.*?</script>", "", body, flags=re.S)

    def test_dictionary_is_substantial(self):
        self.assertGreaterEqual(len(self.d), 150, "词典太小，翻译不完整")

    def test_no_chinese_left_in_visible_text(self):
        texts = re.findall(r">([^<>]*[\u4e00-\u9fff][^<>]*)<", self.body)
        attrs = re.findall(r'(?:placeholder|title|aria-label)="([^"]*[\u4e00-\u9fff][^"]*)"', self.body)
        uniq = list(dict.fromkeys([t for t in texts + attrs if t.strip()]))
        self.assertGreater(len(uniq), 50, "没抓到文本，提取逻辑失效了")
        bad = [(t.strip(), self.tr(t).strip()) for t in uniq
               if CJK.search(self.tr(t)) and t.strip() not in ALLOW]
        self.assertEqual(bad, [], "英文模式下仍会显示中文：\n" +
                         "\n".join(f"  {a!r} -> {b!r}" for a, b in bad[:15]))

    def test_engine_rules_present(self):
        """引擎的三级匹配规则必须还在，否则短词条会吃掉长句。"""
        for token in ("I18N_EXACT", "I18N_KEYS", "i18nNorm", "applyI18n"):
            self.assertIn(token, self.html, f"i18n 引擎缺少 {token}")


if __name__ == "__main__":
    unittest.main(verbosity=2)