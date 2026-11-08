# 怎么参与

欢迎试用、报 bug、提改进。这个项目的规矩比一般项目多一点，写在下面，省得你白做功。

## 一、先把项目跑起来

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

python -m unittest discover -s tests -v     # 应该 128 个用例全绿
python -m app.server --open                 # 打开网页控制台
```

**跑测试不需要 yfinance / akshare / requests**（它们只在真拉数据时导入）。
如果 pip 装 akshare 失败，你可以跳过它，测试照样能跑。

## 二、报 bug 时请带上这些

没有这些信息，多半只能猜：

1. **你跑了什么**（完整命令，或网页上点了哪几个按钮、填了什么）
2. **期望什么 vs 实际什么**
3. **报错原文**（终端输出或浏览器 F12 → Console 的红字）
4. 如果和数据有关：**数据文件的前 3 行**（`date,open,...` 那段）以及市场、代码
5. Python 版本、操作系统

## 三、提改进时请守住这几条

### 1. 不许出现投资建议类表述

代码、注释、报告、网页文案里都不许有：
`建议买入` / `建议卖出` / `推荐` / `看好` / `一定涨` / `一定跌` / `目标价` / `值得买`

`tests/test_stock_report.py` 会检查报告里的禁词；这是一条硬规则，不是风格偏好。

### 2. 市场与代码必须匹配

`002541.SZ` 是 A 股代码。如果把它丢给「美股」去拉，Yahoo 会照单全收（深市代码在 Yahoo 就是这种写法），
结果是 A 股数据被打上 us 标签 —— 数据是对的，标签是假的，报告会撒谎。

`app/server.py::market_mismatch` 与 `tests/test_market_match.py` 锁住了这条。

### 3. 判定口径不许放宽

通过的条件是：**超额收益（相对买入持有）的 95% 置信区间下界 > 0，且在样本外数据上成立**。

想加新策略，就新建一张卡（`cards/*.json`）写清机制与参数，跑一次看结果；
**不许因为没过就改参数重跑** —— 那等于换一道题，会污染显著性判断。

### 4. 数据源必须是插拔式的

新增市场（比如港股、期货）请实现 `data/base.py` 的 `DataFetcher`，
然后在 `data/registry.py` 注册。第三方库请**在函数内导入**，不要放在文件顶部
（`tests/test_import_hygiene.py` 会拦住）。

## 四、跑测试之外，还能这样验证自己没改坏

```bash
# 独立复核器：不 import 项目代码，自己重算一遍再对账
python referee/profile_check.py --csv data_cache/cn_600519_2020-01-01_2025-12-31.csv
```

## 五、我不会合并的改动

- 加更多技术指标（MACD / KDJ / 布林带）却没说明为什么现有证据不足
- 把「通过」的门槛从 95% 降低，或改成比「绝对收益 > 0」
- 在回测里用未来数据（例如用当天的收盘价决定当天开盘就买）
- 只在小样本（少于 10 只票）上就宣布某策略有效