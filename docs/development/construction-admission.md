# 构筑运行与续接

设计以 [现行流程](../current/construction-workflow.md)、[评分](../current/construction-scoring.md) 和 [接口](../current/model-interfaces.md) 为准。本页仅保留可执行入口说明；历史运行状态见 [整合报告](../reports/2026-11-11-baseline-consolidation.md)。

## 只运行构筑与续接

维护入口为`scripts/run_construction.py`，使用当前源码及已有课程资源。该入口使用现有权重进行构筑推理，默认运行于 `cuda:0`，CUDA 不可用时报错。`--basic-cb` 授权静态 Gate 通过后的基础 CB，默认关闭。`device.json` 保存实际模型设备、前向调用及显存证据。默认开发模式自动续算并按片保存 kernel／session。`--slice-seconds` 和 `--iterations` 只控制片内工作；`--seconds` 仅用于 `--mode online`，开发模式拒绝将它设为任务时限。上线到期先排空静态评价，CB 仍按实际授权及预算执行。按 `--period` 使用[三期正式任务](../current/training-and-acceptance.md#三期课程与数量)。可用 `--request` 提供统筹支持的中文、英文或日文表述，原文和解析结果一并保存。`--theme` 只核对选定的主题。以下命令在现有 WSL 环境执行：

```sh
cd /mnt/c/Users/27499/.codex/worktrees/ygo-construction/_publish_20261030
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
PYTHONPATH="$PWD/src:$PWD/scripts" \
/home/chaos/.local/share/ygo-kito/cuda312/bin/python -u scripts/run_construction.py \
  --checkpoint /mnt/n/YGO-Kito/_local_cpu_20261027/reports/optimization-20261031/2207-course-006/course/checkpoint-1.weights \
  --model-binding /mnt/n/YGO-Kito/_local_cpu_20261027/reports/optimization-20261031/2207-course-006/model-binding.json \
  --environment /mnt/n/YGO-Kito/_local_cpu_20261027/source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json \
  --workspace /mnt/n/YGO-Kito/_local_cpu_20261027 \
  --native-root /mnt/n/YGO-Kito/_local_cpu_20261027/assets/native \
  --period 2022-07 --theme setcode-181 --device cuda:0 --candidate-budget 5 --mode development --slice-seconds 120 --iterations 4 \
  --output .cache/construction-next-slice
```

续接时增加`--resume 上一片目录/kernel.json.gz`。可指定该存档所在目录继续，也可指定全新输出目录。同一正式任务可读取压缩或未压缩存档。带旧课程 12／3 约束的存档，以及已经生成未保留字段限定的旧草案的存档，保留原记录并另开输出目录开始正式任务。kernel 保存任务原文、效果积木草案、待评批次和查询／评价游标。完成后只导出最优牌表，待评牌表在输出索引中只列标识与状态。输出包括任务、结果、会话、可续接kernel、候选牌表和摘要；`listing_complete`只说明张数齐全，是否通过看`construction_passed`及Gate原因。

纯牌表构筑按锁定时期规则、实际投入、代价及配套直接评价。参考按相同政策独立计算。`score`、`stages` 和 `use_details` 提供分数及用途解释。`static_rules` 给出来源及登记接入诊断，单条未映射登记不延后 Side 或总分。指定路线或显式续办的原生查询由锁定内核检查。旧规范化版本的评分和 Gate 在恢复时失效，牌表保留并按现行入口重算。

静态融合用途在普通入口调用锁定规则的素材资格检查。`use_details` 的 `inventory_checks.fusion` 保存实际额外对象、素材副本和适用区域。显式共同用途继续通过现有分配器检查共用资源。遇到已知功能漏读，按同一政策以更换配套后的用途和分数变化核对修复。
