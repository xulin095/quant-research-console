# referee —— 独立裁判

这里的脚本**故意不 import 项目自己的代码**。理由只有一句：
用被测代码验证被测代码，等于让被审的人自己出庭作证。

| 文件 | 作用 |
| --- | --- |
| `profile_check.py` | **报告复核器**：自己从 CSV 重算自相关 / 方差比 / 置换检验，再和 `reports/` 里的报告逐项对账。退出码 0 = 一致，1 = 有对不上。 |
| `verify.py` | v1 的 13 条机械验收（文件结构、报告五章、禁词、退出码三档、缓存命名等） |
| `audit_recalc.py` | 从缓存 CSV 独立重算回测与 6 个风控数字，和报告对比 |

## 用法

```bash
# 复核一份报告（最常用）
python referee/profile_check.py \
  --csv data_cache/cn_603345_2010-01-01_2025-12-31.csv \
  --report reports/603345_分析报告_2026-11-08.md

# v1 的机械验收
python referee/verify.py --root .

# 只要有缓存，就能独立重算回测
python referee/audit_recalc.py --root . --report reports/AAPL_us_2024-01-01_2025-12-31.md
```

## 它验不了什么

- 不做「这个策略能不能赚钱」的判断 —— 那是 `tools/audit.py` 与 `cards/` 的事
- 置换检验的 z 值依赖随机种子，因此只保证**判定一致**，不保证小数点一致