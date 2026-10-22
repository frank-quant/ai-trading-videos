# 命令速查

以下命令都在research目录、激活本地环境后执行。日期与筛选定义见rules.md。不会自动调用大模型，A/B配置需通过第4步提示词产生。

```powershell
# 无行情也能运行的检查；完整检查需先下载raw
python tools/check.py
python tools/check.py --full
python tools/fetch_tushare.py --help
python tools/fetch_tushare.py
python tools/data_check.py

# 单配置/单轮搜索（--dir只扫描本层目录，不递归）
python engine/backtest.py strategies/examples/b_trend_value.yaml --group example
python engine/run_batch.py --dir strategies/a/round1 --group A --workers 2

# 主随机组：示例637必须替换为本次实际A组基础配置数
python engine/funnel.py gen-monkey --seed 43 --count 637 --out strategies/random
python engine/run_batch.py --dir strategies/random --group monkey_43 --workers 2

# 正式全量漏斗；先检查任务状态，不能把资源错误当筛选失败
python engine/funnel.py layers --formal --workers 2
python engine/funnel.py shortlist --group AI
python engine/funnel.py shortlist --group monkey_43
python engine/funnel.py report

# 20组随机对照；正式任务较长，按本机资源调度并保留进度
python engine/funnel.py farm --seeds 1-20 --count 637 --formal --workers 2
# 农场完成后用共同池重新终判，再生成名单
python engine/funnel.py layers --formal --workers 2
python engine/funnel.py shortlist --group AI
python engine/funnel.py shortlist --group monkey_43
python engine/funnel.py report
python engine/compare.py
```

配置仅允许rules.md指定档位。例子与测试使用group=example/test，不计入研究组N。CLI直接调用会写本地台账；审计请使用tools/check.py的隔离工作区。

`engine/run_pipeline.py`还包含自动验证与组合阶段，不用于绕过八步数据权限纪律，尤其不能在搜索角色中调用全流程去预看验证表现。

锁定六席后按第7步提示词评估，不在此处提供自动开封命令，避免提前读取测试集。
