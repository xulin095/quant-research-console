# 量化分析 agent v1 —— 设计文档

> 依据：`research.md`（第 1 棒）+ `prompts-v2.md` 附录 A/B/C。
> 冲突处理原则：**research.md 的数据源结论采纳；凡是与附录 A 的口径冲突，一律以附录 A 为准**（因为下游复算按它来）。本文件第 6 段「冲突裁决」逐条列出改了哪些。

## 1 总体架构与数据流

命令行程序，5 步串联。**所有模块只认一张标准 OHLCV 表**，换市场只换数据源适配器，指标/回测/风控/报告一行不改。

```
                    ┌──────────────────────────────────────────┐
  命令行参数         │  main.py（唯一入口，只串流程）             │
  --symbol AAPL     │  argparse → 校验 → 调 5 步 → 退出码        │
  --market us       └────┬─────────────────────────────────────┘
  --start / --end        │
                         ▼
       ①  data/registry.py 查表 → USFetcher.get_history()
          ├─ 命中 data_cache/us_AAPL_2024-01-01_2025-12-31.csv → 直接读
          └─ 未命中 → yfinance 拉 → 清洗成标准表 → 写缓存
                         ▼  标准表 8 列
       ②  indicators.py → MA5/MA20/MA60、MACD(12,26,9)、RSI14、VOL20、日收益率
                         ▼  同一张表 + 指标列
       ③  backtest.py  → 信号（金叉/死叉）→ 次日开盘成交 → trades + equity
                         ▼
       ④  risk.py      → 6 个数字（总收益/年化/最大回撤/夏普/胜率/交易次数）+ 基准
                         ▼
       ⑤  report.py    → reports/{symbol}_{market}_{start}_{end}.md（5 章中文）
```

**标准表契约（全项目唯一数据接口）**

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `date` | str `YYYY-MM-DD` | 无时区；升序；唯一；不补缺失交易日 |
| `open` `high` `low` `close` | float | 已复权口径见 2.1 |
| `volume` | float | **统一为「股」**；A股「手」×100 |
| `symbol` | str | 大写，如 `AAPL` / `600519` / `BTCUSDT` |
| `market` | str | 小写 `us` / `cn` / `crypto` |

## 2 模块接口与职责

### 2.1 数据模块（可插拔）

**接口**（`data/base.py`）

```python
class DataError(Exception): ...

class DataFetcher(ABC):
    market: str                      # "us" / "cn" / "crypto"
    @abstractmethod
    def get_history(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """返回标准 8 列表；列不全、行数不足、全 NaN 一律 raise DataError。"""
```

**注册表**（`data/registry.py`，main.py 只查表，不写 if-else）

```python
FETCHERS: dict[str, type[DataFetcher]] = {"us": USFetcher, "cn": CNFetcher, "crypto": CryptoFetcher}

def get_fetcher(market: str) -> DataFetcher:
    if market not in FETCHERS:
        raise KeyError(market)       # main 转成退出码 2，并列出可用市场
    return FETCHERS[market]()
```

**加一个新市场 = 3 步**（二期做可切换选项就靠这个）
1. 新增 `data/xx.py`，继承 `DataFetcher`，实现 `get_history` 并做本市场的字段/单位清洗；
2. 在 `FETCHERS` 里加一行；
3. 在 README「怎么加一个新市场」抄一遍。**核心 4 文件（indicators/backtest/risk/report）零改动。**

**复权口径**（写进报告）
- `us`：yfinance `auto_adjust=True`，OHLC 已调整 = 已复权，不再单独维护 `Adj Close`；
- `cn`：akshare `adjust="qfq"` 前复权；缓存要记录拉取日期（前复权价是时变的，除权后需重拉）；
- `crypto`：无复权概念，原始成交价；日线按 UTC 00:00 切分。

**网络策略（2026-11-08 本机实测，必须按市场分开设，一个开关搞不定）**

| 市场 | 通路 | 实测证据 |
| --- | --- | --- |
| `us` | **必须走代理** | Yahoo 直连 429/403；走 `127.0.0.1:7897` 成功拉到 AAPL 41 行 |
| `cn` | **必须绕过代理** | 系统注册表代理开着 7897，会拒绝东财请求（ProxyError）；绕过代理后 600519 返回 38 行 |
| `crypto` | 当前不可达 | Binance 直连超时、走代理 SSLError。代码照写，实测标「未验证」，不得因此判 v1 失败 |

实现要求（否则第 3 棒的 5 条验收永远是 SKIP）：
- `config.py` 增加 `PROXY = os.environ.get("QUANT_PROXY", "")`（空串 = 不用代理）
- `main.py` 启动时先 `os.environ.setdefault("NO_PROXY", "*")` 与 `setdefault("no_proxy", "*")`，
  让 requests / akshare 默认**绕过**系统注册表代理（Windows 上 requests 会读注册表，这是东财失败的真凶）
- `data/us.py`：yfinance 1.8 **没有 `proxy` 参数**，所以调用前若 `PROXY` 非空 → 临时设
  `HTTPS_PROXY`/`HTTP_PROXY` 并临时清掉 `NO_PROXY`，**用 try/finally 恢复原值**（别污染其它市场）
- `data/crypto.py`：显式 `requests.Session()` + `session.trust_env = False`；`PROXY` 非空则传 `proxies=`
- 标准跑法：`$env:QUANT_PROXY='http://127.0.0.1:7897'` 之后再跑 `main.py`
- README「已知限制」必须写明这三条通路差异
**缓存**（不做 meta.json，口径靠文件名字段+报告声明）
- 路径：`data_cache/{market}_{symbol}_{start}_{end}.csv`，symbol 大写
- 命中条件：文件存在且**数据行 ≥ 60**
- `--no-cache`：强制重拉但仍写缓存
- 不命中就拉；拉取失败 **不允许**回退到「随便找一份旧缓存」——必须报错退出

### 2.2 指标模块

只算数，不给建议。全部 pandas 手写，**禁用 ta-lib**；不引入 matplotlib（v1 不画图）。

输出列：`ma5` `ma20` `ma60` `dif` `dea` `macd_hist` `rsi14` `vol20` `ret`。计算式见 2.4 后的口径总表。

### 2.3 回测模块

- 策略：双均线 MA5/MA20，**只做多**；金叉买入、死叉卖出（严格穿越，见口径总表）
- 成交：信号次日**开盘价**；最后一根没有次日 → 不成交，期末按最后收盘价结算，报告注明「期末仍持仓」
- 仓位：全仓、不加杠杆、不做空；同一时间只持有一只
- 成本：手续费 0.0003/笔、滑点 0.0005/笔，**买卖两侧都扣**；v1 不计印花税（美股口径，报告注明）
- 输出：`trades`（逐笔）+ `equity`（逐日权益），交给 risk.py

### 2.4 风控模块

只算 6 个数字 + 1 个基准，不算别的：总收益率、年化收益率、最大回撤、夏普比率（无风险 2%）、胜率、交易次数，以及**买入持有同期收益率**（基准，用于回答「这个策略比躺着不动强吗」）。

**口径总表（下游据此复算，不得自创）**

| 项 | 定义 |
| --- | --- |
| MA_n | `close.rolling(n).mean()`，n ∈ {5,20,60} |
| EMA_n | `close.ewm(span=n, adjust=False).mean()` |
| DIF / DEA / HIST | DIF=EMA12−EMA26；DEA=DIF.ewm(span=9).mean()；**HIST=2×(DIF−DEA)** |
| RSI14 | Wilder：涨/跌分别 `ewm(alpha=1/14, adjust=False).mean()`；RSI=100−100/(1+RS)；均跌为 0 → 100；前 14 个 NaN |
| 日收益率 | `r_t = close_t/close_{t−1} − 1`，首行 NaN（不填 0） |
| VOL20 | `r.rolling(20).std(ddof=1) × sqrt(252)` |
| 金叉 | `MA5>MA20` 且前一日 `MA5<=MA20`；死叉反之 |
| 买入 | `shares = floor(cash/(open×1.0008) × 1e6)/1e6`；成本 = `shares×open×1.0008`；cash 不得为负 |
| 卖出 | 进账 = `shares×open×0.9992` |
| 权益 | 逐日 `cash + shares×close`（当日开盘成交后按当日收盘估值） |
| 总收益率 | `E_end/100000 − 1` |
| 年化收益率 | `(E_end/100000)^(252/N) − 1`，N = 权益天数−1 |
| 最大回撤 | `\|min(equity/cummax(equity) − 1)\|`，报告显示为正百分比 |
| 夏普比率 | `mean(excess)/std(excess, ddof=1) × sqrt(252)`，`excess = 日权益收益率 − 0.02/252`；样本<2 或 std≈0 → None |
| 胜率 | 盈利回合 / 已平仓回合；无平仓 → None |
| 交易次数 | 已平仓回合数（一买一卖=1），另单列买入/卖出成交笔数 |
| 基准 | 买入持有 = `close_last/close_first − 1`（同期、同区间） |
| 最少数据 | 60 个交易日 |
| 退出码 | 0 成功 / 1 数据失败或数据不足 / 2 参数错误 |

### 2.5 报告模块

固定 5 章 Markdown，标题一字不差（下游 grep）。

> 下面代码块里的是**报告文件**的字面模板，不是本设计文档的章节 —— 本文件只有 5 个一级标题（`## 1`–`## 5`）。

```
## 1. 基本信息
## 2. 近期价格
## 3. 回测结果
## 4. 交易记录
## 5. 风险提示
```

- 第 3 章必须是表格：6 个风控数字 + **买入持有同期收益率** + 回测样本交易日数；夏普/胜率样本不足时写「样本不足」
- 第 4 章必须是逐笔交易表：序号 | 买入日 | 买入价 | 卖出日 | 卖出价 | 股数 | 收益额 | 收益率 | 持有天数 | 状态（已平仓 / 期末持仓）
- 第 5 章必须逐字含：「只代表过去，不代表未来」「不要用实盘资金直接照抄」；并写防过拟合三件套（本次样本交易日数、换时间段结果可能不同、震荡市双均线会频繁假信号）
- 全文中文；价格 2 位小数；百分比 2 位小数带 %；比率 2 位无单位
- 禁词：建议买入 / 建议卖出 / 推荐 / 看好 / 一定涨 / 一定跌 / 目标价 / 值得买（「卖出价」是字段名，不算禁词）
- 文件名：`reports/{symbol}_{market}_{start}_{end}.md`（质检靠它匹配缓存做独立复算）

## 3 文件结构、技术栈与实现顺序

### 3.1 技术栈

Python **3.10+**（本机 `python` = 3.10.0，别写只在 3.11+ 才有的语法）、pandas、numpy、yfinance、akshare、requests。
测试用标准库 `unittest`（不额外装 pytest 也行，二选一写进 README）。
**不引入** matplotlib / ta-lib / 任何券商 SDK。

### 3.2 文件结构

16 个代码文件 + 2 个 .gitkeep，**一个不多一个不少**（`research.md` / `design.md` / `test-report.md` 是前三棒的过程文档，允许留在根目录，不计入）：

| 文件 | 职责（一句话） |
| --- | --- |
| `README.md` | 安装、最小可跑命令、报告在哪、6 个数字怎么读、**怎么加一个新市场（3 步）**、测试怎么跑、已知限制 |
| `requirements.txt` | pandas / numpy / yfinance / akshare / requests |
| `config.py` | 全部参数写死（见下） |
| `main.py` | 唯一入口：argparse → 校验 → 串 5 步 → 退出码 |
| `indicators.py` | 9 个指标列，纯 pandas |
| `backtest.py` | 双均线、次日开盘成交、全仓、权益曲线 |
| `risk.py` | 6 个数字 + 基准 |
| `report.py` | 5 章 Markdown |
| `data/__init__.py` | 空 |
| `data/base.py` | `DataFetcher` 抽象基类 + `DataError` |
| `data/registry.py` | `FETCHERS` 注册表 + `get_fetcher` |
| `data/us.py` | yfinance（`auto_adjust=True`） |
| `data/cn.py` | akshare（`adjust="qfq"`，手→股） |
| `data/crypto.py` | Binance 公开 K 线（无 key，UTC 日线） |
| `tests/__init__.py` | 空 |
| `tests/test_core.py` | 合成数据源 + 3 项手算断言（断网可跑） |
| `reports/.gitkeep` | 占位 |
| `data_cache/.gitkeep` | 占位 |

`config.py` 必须包含：`CAPITAL=100000`、`FAST=5`、`SLOW=20`、`LONG=60`、`MACD=(12,26,9)`、`RSI_N=14`、`FEE=0.0003`、`SLIP=0.0005`、`RF=0.02`、`TRADING_DAYS=252`、`MIN_ROWS=60`、`VOL_N=20`、`PROXY=os.environ.get("QUANT_PROXY","")`。

### 3.3 实现顺序（每步跑通才进下一步）

| 步 | 做什么 | 怎么算跑通 |
| --- | --- | --- |
| ① | `config.py` + `data/base.py` + `data/registry.py` + `data/us.py` | `python -m data.us` 打印标准表前 5 行 |
| ② | `indicators.py` | 打印最后 3 行，MA60/DIF/DEA/HIST/RSI14/VOL20 均非 NaN |
| ③ | `backtest.py` + `risk.py` | 打印 trades、权益首末值、6 个数字；每笔买入价与当日 open 的偏差 = 0.0008 |
| ④ | `report.py` + `main.py` | `python main.py --symbol AAPL --market us --start 2024-01-01 --end 2025-12-31`，退出码 0，生成报告，5 章齐全 |
| ⑤ | `data/cn.py` + `data/crypto.py` + `tests/test_core.py` | 合成数据源跑通全流程；`python -m unittest discover -s tests -v` 全绿 |

## 4 验收标准

**12 条主验收，每条对应一条裁判命令**（在 `C:\Users\lenovo\Documents\deepseek-harness\default-workspace\referee` 下跑，`--root D:\quant-agent`）：

| # | 标准（yes/no） | 怎么验证 |
| --- | --- | --- |
| 1 | 文件结构 16+2，无多余文件 | `python verify.py --root D:\quant-agent --only 1` |
| 2 | 报告存在且非空 | `--only 2` |
| 3 | 报告 5 章标题一字不差 | `--only 3` |
| 4 | 8 个禁词零命中 | `--only 4` |
| 5 | 第 5 章含「只代表过去，不代表未来」「不要用实盘资金直接照抄」 | `--only 5` |
| 6 | 第 3 章含 6 个风控数字 + 买入持有基准 + 样本交易日数 | `--only 6` |
| 7 | `config.py` 10 个参数写死 | `--only 7` |
| 8 | 无 ta-lib / matplotlib / 密钥 / 交易调用 | `--only 8` |
| 9 | `tests/` 有真用例且全绿（含合成数据源跑通全流程 + 3 项手算断言） | `--only 9` |
| 10 | 退出码三档：样本不足→1、`start>=end`→2、非法市场→2，且都是中文一行原因、无 Traceback | `--only 10` |
| 11 | 缓存命名合规且 ≥60 个交易日；命中缓存时不再发网络请求（断网可跑） | `--only 11` |
| 12 | 报告 6 个数字与**独立复算**一致（含手续费/滑点确实扣除） | `--only 12` |

**附加 1 条（不计入 12）**

| # | 标准 | 怎么验证 |
| --- | --- | --- |
| 13 | 换市场不改核心 4 文件 | `--only 13`（git 无未提交改动）+ `main.py --market cn --symbol 600519` 真实跑通（A股直连可用）+ `python -m unittest discover -s tests -v` |

> 第 13 条用**合成数据源**证明，不依赖真实网络（加密源可能被墙，不能拿它当验收前提）。
> 全部跑：`python verify.py --root D:\quant-agent`；要真实联网验证再加 `--net`。

## 5 边界与不做

- 不做：自动下单、券商登录、实盘账户、付费数据、账号密码 API Key 存储
- 不做：分钟线、多策略框架、机器学习、网页 / App / 数据库、图表
- 不做：价格预测、买卖建议、收益承诺；**不把回测结果当未来表现的证据**
- 不做：样本内/样本外切分（v1 只跑单一时间区间，在第 5 章明说这是局限）
- 不做：印花税、融券、做空、杠杆、多标的组合

**附录（不计入 5 节编号）：research.md ↔ 附录 A 的冲突裁决**

| # | research.md 说 | 本设计定为 | 理由 |
| --- | --- | --- | --- |
| 1 | 缓存路径 `data_cache/{market}/{symbol}/{start}_{end}.csv` + `meta.json` | **扁平** `data_cache/{market}_{symbol}_{start}_{end}.csv`，无 meta | 质检按文件名匹配缓存做独立复算；多一跳目录就无法自动配对 |
| 2 | Python 3.11+ | **Python 3.10+** | 本机 `python` 就是 3.10.0，写 3.11 语法会当场炸 |
| 3 | `market ∈ {US, CN, CRYPTO}` 大写 | **小写 `us/cn/crypto`** | 与 CLI 入参、缓存文件名、退出码提示统一，避免大小写映射 bug |
| 4 | 「必须同时输出买入并持有基准」 | **采纳**，但并入第 3 章一行、第 3 条验收，不新增章节与条数 | 教学价值高、成本一行；不动已冻结的 12+1 条框架 |
| 5 | 样本内/样本外切分 | **不做**，第 5 章明说是局限 | v1 范围冻结；切分会让表结构翻倍 |
| 6 | volume 美股/A股统一为「股」 | **采纳** | A股「手」×100，否则成交额差 100 倍 |
