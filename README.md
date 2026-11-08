# 量化分析 agent v1

这个命令行程序读取历史日线，计算指标，用双均线规则做历史回测并生成中文报告。仅供学习。

## 安装

需要 Python 3.10+。在项目目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 最小运行

```powershell
.venv\Scripts\python.exe main.py --symbol AAPL --market us --start 2024-01-01 --end 2025-12-31
```

报告保存在 `reports/AAPL_us_2024-01-01_2025-12-31.md`。缓存位于 `data_cache/`；`--no-cache` 可重新拉取并更新缓存。`--end` 省略时为今天。

## 六个风控数字怎么读

- 总收益率：期末资金相对初始资金增减了多少。
- 年化收益率：把这段历史收益换算成每 252 个交易日的速度。
- 最大回撤：历史权益从峰值到后续谷底的最大跌幅。
- 夏普比率：平均超额日收益相对日波动的大小，越高只表示本次历史样本里越稳定。
- 胜率：已平仓回合里盈利回合所占比例。
- 交易次数：完成买入和卖出的回合数，未平仓不计入。

报告另列买入持有同期收益率、买卖成交笔数和回测样本交易日数。

## 怎么加一个新市场（3 步）

1. 新增 `data/xx.py`，继承 `DataFetcher`，实现 `get_history`，将字段和单位清洗为标准 8 列。
2. 在 `data/registry.py` 的 `FETCHERS` 添加一行。
3. 在本节写明新市场的数据来源和清洗口径。指标、回测、风控和报告文件不需修改。

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 已知限制

美股数据非实时，Yahoo 可能限流。A 股前复权历史价随除权变化，旧缓存需用 `--no-cache` 重拉。加密接口可能网络不可达，日线按 UTC 切分。回测未计印花税、涨跌停成交约束，也未做样本内外切分。

- 美股：本机访问 Yahoo 需设置 `QUANT_PROXY=http://127.0.0.1:7897` 走代理。
- A 股：本机访问东财需绕过系统代理；程序默认设置 `NO_PROXY=*`。
- 加密：Binance 在本机不可达，接口实跑尚未验证。
