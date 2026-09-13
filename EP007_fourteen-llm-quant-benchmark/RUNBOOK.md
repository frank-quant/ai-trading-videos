# RUNBOOK · 从零复现这场测评

> 回测用 Freqtrade **2026.6** 官方 Docker 镜像（冻结版本，全程没换）。
> 下文的 `<模型目录>` / `<完整数据目录>` / `<样本外数据目录>` 换成你自己的路径。

---

## 0. 目录约定

关键在于**样本外数据要放在模型够不着的地方**：

```
<工作根目录>/
├── ft_<模型>/             ← 模型在这里工作，只挂 TRAIN+VALID 数据
├── ...                    ← 每个模型一个干净目录，互不可见
└── data_shared/           ← 只到 2025-06-30 的数据

<另一个盘符或另一个根目录>/
└── data_full/             ← 含 2025-07 之后的完整数据，揭盲时才挂
```

> **不要**把样本外数据放在工作根目录下面的任何位置。模型如果开了自动确认模式，
> 是会自己 `ls` 到处翻的。**物理隔离比提示词约束可靠。**
> 这一点我在 EP004 就写过，这一季 14 个模型跑下来，越界扫描全部零命中。

每个模型目录开考前的内容 = `prompts/` + `scaffold/` + 数据软链，**完全一致**。
可以自己核：

```bash
md5sum ft_*/GOAL.md ft_*/README_FOR_MODEL.md \
       ft_*/strategies/cross_sectional_base.py ft_*/hyperopts/EP004ValidLoss.py
```

14 个模型这四个文件的 MD5 全部相同。

---

## 1. 开考

把 `prompts/GOAL.md` 的内容作为任务发给模型，让它自己读 `README_FOR_MODEL.md`、
写代码、跑回测、迭代到它认为完成为止。**全程不干预**，只做两件事：

1. **把审批停等关掉。** 这一季用到的 harness 里，`dsh` 默认每次改文件、跑命令都要停下来
   等人点同意。这题是让模型自己跑到底，一路点同意等于我在替它做决定。
   Codex / Claude Code / ZCode 等同理，用各自的免审批或自动模式。
2. **确认模型串。** 有的 harness 默认调的不是你以为的那个模型（Antigravity 尤其要核）。
   开跑前进设置确认一次，跑完再用平台账单的模型编码字段复核一遍。

这一季各家用的 harness：Codex Desktop / Codex CLI / ZCode / Qwen Code /
dsh (DeepSeek Harness) / Grok Build / Antigravity / Claude Code / Kimi Code。

---

## 2. 收卷

考题要求的交付物（`GOAL.md` 有完整清单）：

```
strategies/<策略名>.py     策略源码
config.json                最终参数 + seed
metrics.json               自报的 train / valid 指标
design.md                  设计说明
self_assessment.md         自评
run.md                     执行记录（跑了什么命令）
```

收卷后**先不看成绩**，先过硬门槛（下一节）。

---

## 3. 硬门槛（先淘汰后打分）

九项逐条查，任何一项不过直接出局，不进六根轴：

| 项 | 怎么查 |
|---|---|
| 能完整回测 | 用冻结镜像重跑一遍，不报错 |
| 有成交 | 成交笔数 > 0 |
| 真的双向 | 多头和空头都有成交 |
| 手续费未改 | `valid_ownfee` 与 `valid` 对比，差异即偷改 |
| 杠杆未加 | 逐笔核 leverage ≤ 1 |
| 脚手架未动 | `cross_sectional_base.py` / `EP004ValidLoss.py` 的 MD5 |
| 未来函数 | `scripts/factor_causality_check.py`，见下 |
| 越界读数据 | 扫描日志与代码里对样本外路径的引用 |
| 交付物合规 | 按上面的清单逐个点 |

**未来函数怎么查**：同一时点用全量数据算一遍信号，再用截断到那一刻的数据算一遍，
两者不一致就是偷看了未来。

```bash
docker compose run --rm freqtrade python factor_causality_check.py \
    --strategy <策略名> --timerange 20240701-20250630
```

> 有的策略会调用框架的数据接口，标准截断法跑不了（这一季 Grok 就是）。
> 这时换框架级的替代检验：逐根 K 线比对两种算法的信号，差异要能解释。

---

## 4. 独立复现

不要信模型自报的数字，全部重跑。三段各跑一次，再加两个对照：

```bash
# 三段
docker compose run --rm freqtrade backtesting --strategy <策略名> \
    --timerange 20210101-20240630 --export trades --export-filename verified/train.zip
docker compose run --rm freqtrade backtesting --strategy <策略名> \
    --timerange 20240701-20250630 --export trades --export-filename verified/valid.zip
docker compose run --rm freqtrade backtesting --strategy <策略名> \
    --timerange 20250701-20260701 --export trades --export-filename verified/test.zip

# 手续费翻倍（万六 → 万十二），看成本韧性
docker compose run --rm freqtrade backtesting --strategy <策略名> \
    --timerange 20240701-20250630 --fee 0.0012 --export trades \
    --export-filename verified/valid_2xfee.zip
```

**样本外那一段（test）要等所有模型都交卷之后才挂完整数据。** 这是揭盲。

---

## 5. 算指标

宿主机上按这个顺序跑（脚本都在 `scripts/`）：

```bash
python scripts/seg_metrics_host.py      # 目标函数口径的分段指标 → seg_*.json
python scripts/alpha_beta.py            # 逐日盯市权益对大盘回归 → alpha_beta.json
python scripts/mc_bootstrap.py          # 分块自助重采样 5000 次 → mc.json
python scripts/deflated_sharpe.py       # Deflated Sharpe → dsr.json
python scripts/subperiod.py             # 逐月拆分 → subperiod_M.json
python scripts/usage_cost.py            # 成本核算 → cost.json
```

然后是全场汇总与判定：

```bash
python scripts/exclude_forced.py        # 剔除末端强平后重算
python scripts/misreport_check.py       # 自报 vs 复现（虚报检查）
python scripts/argmax_table.py          # 交卷参数 vs 搜索里的 argmax
python scripts/make_dataset.py          # 汇总成 dataset_全量汇总.json/csv
python scripts/score_radar.py           # 六轴打分与综合排名
```

出图：

```bash
python scripts/make_cross_charts.py     # 横向比较的图（依赖 cross_data.py）
```

---

## 6. 两个必须守住的口径

**① 两套夏普别混。** 控制台的 `Sharpe (daily wallet balance)` 和目标函数的
`EP004ValidLoss._sharpe_daily` 差 0.4 ~ 0.6。虚报检查必须两端都用目标函数口径，
**用控制台那套去比模型自报的数字，会把所有模型判成虚报。**

**② 末端强平是回测的机械产物，不是策略能力。** Freqtrade 在回测最后一根 K 线把所有
持仓强制平掉。这一笔要单独拆出来看——这一季 14 个模型里有 11 个剔掉之后成绩变差，
其中 1 个是靠它从负翻正的。

口径的完整规则写在 [`results/报告口径规范.md`](results/报告口径规范.md)。

---

## 7. 已知的坑

- **`--end` 少一天**，我自己的脚本差点把结论算反了。改完脚本一定要拿一条已知结果回归验证。
- **每个模型只考了一次。** 要让名次真正站得住，得每家跑 3~5 次取分布——这一季没做到，下一季必修。
- **账单口径**：订阅制（Codex / Claude Code）拿不到逐笔账单，只能按会话日志的 token 量
  折算目录价，是等效成本不是实付；按量计费的才是账单原值。混着比要标清楚。
