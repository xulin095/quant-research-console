# 操作手册（RUNBOOK）

> 目标：把「一个想法」在两小时内变成「通过 / 不通过」的结论，并留下账。
> 所有命令在 `<项目根目录>` 下执行，用项目自己的解释器。

---

## 0. 每次开工前：30 秒环境自检

```powershell
cd <项目根目录>
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

看到 `OK` 才能开工。看到 `FAILED` 说明代码被改坏了，先修，别急着验证想法。

测一下数据在不在：

```powershell
Get-ChildItem data_cache\*.csv | Measure-Object
```

少于 20 个文件说明缓存丢了，跑一次 `python -m tools.universe --sample 45 --seed 7`。

---

## 1. 每周固定动作（两种时长，按你时间选）

### 30 分钟版：只跑已有卡，看账本

```powershell
cd <项目根目录>
type registry.jsonl
```

看两件事：
- 现在累计试了几次（`n_tests_before` 最大值 + 1）
- 通过率是多少

**通过率 > 20% 就要警惕**：要么你的卡写得太松，要么判定有 bug。

### 2 小时版：完整跑一张新卡

1. 复制模板：`copy cards\HK-001.json cards\你的编号.json`
2. 改 4 个字段（见第 2 节）
3. 跑（见第 3 节）
4. 看账本

---

## 2. 写一张卡：只改这 4 个字段

```json
{
  "id": "HK-003",
  "kind": "cross_section",
  "market": "cn",
  "direction": "reversal",
  "lookback": 5,
  "top_n": 3,
  "holdout": "2021-01-01",
  "cost": 0.0008,
  "universe": "universe.json",
  "mechanism": "一句话：为什么这个效应应该存在",
  "claims": "一句话：你预测什么"
}
```

| 字段 | 怎么填 | 注意 |
| --- | --- | --- |
| `id` | 自己编号，别重复 | 重复的 id 在账本里会混 |
| `kind` | `cross_section` 或 `time_series` | 目前只支持这两种 |
| `direction` | `reversal`（买跌得多）或 `momentum`（买涨得多） | 二选一，**不许两家都试** |
| `lookback` | 几个月（1–12） | **填完就冻结**，跑完不许改 |
| `mechanism` | 必须能说出「谁在亏钱」 | 写不出来的想法直接扔掉 |

**`holdout` 不要改。** 2021-01-01 之后的数据是唯一的干净考卷，改它等于销毁考卷。

---

## 3. 跑：一条命令

```powershell
cd <项目根目录>
.\.venv\Scripts\python.exe -m tools.audit cards\HK-003.json
```

要一次跑多张：

```powershell
.\.venv\Scripts\python.exe -m tools.audit cards\*.json
```

---

## 4. 读结果：只看 4 个数

```
  ic_ci_low      -0.0332      ← 必须 > 0
  excess_t       -0.8440      ← 必须 > 2
  strat_cagr     0.0616       ← 参考：策略年化
  bench_cagr     0.1461       ← 参考：等权基准
```

判定只有一条规则：**`ic_ci_low > 0` 且 `excess_t > 2`**。

- 两个都满足 → 通过
- 任何一个不满足 → 不通过

`strat_cagr` 比 `bench_cagr` 高，**不代表通过**——那可能只是承担了更多风险（前面踩过这个坑）。

---

## 5. 不通过之后：三件不许做

1. **不许改 lookback 再跑** —— 那是同一张卡换皮，账本会露馅
2. **不许把 `direction` 反过来再跑** —— HK-001 和 HK-002 互为镜像，两张都不过，这就是答案
3. **不许改 `holdout` 让它「好看一点」** —— 那就是自欺

正确动作：在 `cards/` 里留档，然后写**下一张机制不同的卡**。

---

## 6. 通过之后：三件要做

1. **先跑稳健性**：`python -m tools.cs_audit --symbols <同一批> --holdout 2021-01-01`
   看 lookback 邻域是不是成片（单点尖峰 = 假）
2. **再换宇宙验一次**：`python -m tools.universe --sample 45 --seed 99`（换种子 = 换一批票）
3. **最后才谈决策层**：`python -m tools.decide`

三步都过，才有资格谈「要不要做产品」。

---

## 7. 什么时候需要写代码

| 你想验的 | 要不要写代码 |
| --- | --- |
| 换个 lookback / topN / 方向 | ❌ 改 JSON 就行 |
| 换一批票 | ❌ 改 `--seed` 或 `universe.json` |
| 单个标的的均线策略 | ❌ 写 `kind: time_series` 卡 |
| 新信号（如按 ROE 排序） | ✅ 要改 `cross_section.build_observations` |
| 新市场（港股/期货） | ✅ 要加 fetcher |

**前四行覆盖你现在 80% 的想法。别一上来就写代码。**

---

## 8. 本机踩过的坑（省你几小时）

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| 美股拉不到数据 | Yahoo 限流 | `$env:QUANT_PROXY='http://127.0.0.1:7897'` |
| A股报 ProxyError | requests 读 Windows 注册表代理 | 代码已处理（NO_PROXY），自己写脚本要手动设 |
| `000001` 变成 `1` | PowerShell 把纯数字当整数 | 参数加引号 `--symbols "000001,000858"` |
| 命令卡住不动 | 把外部程序输出捕获进变量 / 走管道 | 重定向到文件再读：`... > log.txt 2>&1` |
| 中文显示成乱码 | PowerShell 默认编码 | `[IO.File]::ReadAllText($p,[Text.Encoding]::UTF8)` |
| A股长历史价格是负的 | 前复权 10 年 | 用 `adjust="hfq"`（本项目已改） |

---

## 9. 期望管理（最重要的一条）

到目前为止：**4 条路径、上百次检验、0 个通过。**

这是正常的。业余量化最常见的死法是「两周找到一个策略，第三周亏光」；你现在是「四周一个都没找到，但知道自己在找什么」。

- 一个月能写出 8–10 张卡，通过 0–1 张，是健康节奏
- 连续 20 张都不过 → 不是你不努力，是这条路（免费数据 + 简单信号）本来就窄
- 那时该换的是**数据**，不是参数

---

## 10. 一句话流程

```
想到机制 → 写卡（改 4 个字段）→ 跑一条命令 → 看 4 个数 → 记账 → 下一个
```

不通过就淘汰，不通过就淘汰，不通过就淘汰。**别改参数。**