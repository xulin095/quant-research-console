#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据上传校验：列齐全 / 去重排序 / 非正价 / 行数下限 / 中文表头。"""

import tempfile
import unittest
from pathlib import Path

from app import server as S


def csv_text(rows, header="date,open,high,low,close,volume"):
    out = [header]
    for i in range(rows):
        d = "2024-%02d-%02d" % (i // 28 + 1, i % 28 + 1)
        out.append("%s,10,11,9,10,1000" % d)
    return "\n".join(out)


class TestIngest(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_root = S.ROOT
        S.ROOT = Path(self.td.name)
        (S.ROOT / "data_cache").mkdir()

    def tearDown(self):
        S.ROOT = self.old_root
        self.td.cleanup()

    def test_valid_file_becomes_standard_table(self):
        ok, info = S.ingest_csv(csv_text(80), "us", "mystock")
        self.assertTrue(ok, info)
        self.assertEqual(info["rows"], 80)
        p = S.ROOT / "data_cache" / info["file"]
        self.assertTrue(p.exists())
        head = p.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(head, "date,open,high,low,close,volume,symbol,market")
        self.assertIn("MYSTOCK", p.read_text(encoding="utf-8"))

    def test_missing_column_rejected(self):
        ok, info = S.ingest_csv("date,open,close\n2024-01-01,1,1", "us", "X")
        self.assertFalse(ok)
        self.assertIn("缺少列", info["error"])

    def test_chinese_header_accepted(self):
        rows = ["日期,开盘,最高,最低,收盘,成交量"]
        for i in range(70):
            rows.append("2024-%02d-%02d,10,11,9,10,1000" % (i // 28 + 1, i % 28 + 1))
        ok, info = S.ingest_csv("\n".join(rows), "cn", "600000")
        self.assertTrue(ok, info)

    def test_negative_price_dropped(self):
        txt = csv_text(80) + "\n2024-12-31,-5,1,1,1,100"
        ok, info = S.ingest_csv(txt, "us", "BAD")
        self.assertTrue(ok, info)
        self.assertEqual(info["dropped_bad_price"], 1)

    def test_duplicate_dates_deduped(self):
        txt = csv_text(80) + "\n2024-01-01,10,11,9,10,1000"
        ok, info = S.ingest_csv(txt, "us", "DUP")
        self.assertTrue(ok, info)
        self.assertEqual(info["dedup"], 1)

    def test_unsorted_input_is_sorted(self):
        lines = csv_text(80).splitlines()
        body = lines[1:]
        body.reverse()
        ok, info = S.ingest_csv("\n".join([lines[0]] + body), "us", "SHUF")
        self.assertTrue(ok, info)
        self.assertEqual(info["first"], "2024-01-01")

    def test_too_short_rejected(self):
        ok, info = S.ingest_csv(csv_text(10), "us", "SHORT")
        self.assertFalse(ok)
        self.assertIn("少于", info["error"])

    def test_bad_market_rejected(self):
        ok, info = S.ingest_csv(csv_text(70), "jp", "X")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)