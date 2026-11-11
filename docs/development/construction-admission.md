# 构筑运行与续接

设计以 [现行流程](../current/construction-workflow.md)、[评分](../current/construction-scoring.md) 和 [接口](../current/model-interfaces.md) 为准。本页仅保留可执行入口说明；历史运行状态见 [整合报告](../reports/2026-11-11-baseline-consolidation.md)。

## 只运行构筑与续接

维护入口为`scripts/run_construction.py`，使用当前源码及已有课程资源。它不提供训练开关，输出到全新目录；`--device cuda:0` 显式选择 GPU 推理，CUDA 不可用时报错，不改写原始训练检查点。`--basic-cb` 授权静态 Gate 通过后的基础 CB，默认关闭。`device.json` 保存实际模型设备、前向调用及显存证据。默认开发模式自动续算并按片保存 kernel／session。`--slice-seconds` 和 `--iterations` 只控制片内工作；`--seconds` 仅用于 `--mode online`，开发模式拒绝将它设为任务时限。上线到期先排空静态评价，CB 仍按实际授权及预算执行。下例在现有WSL环境内执行，`--theme`核对宿主已经选定的目标，不改写宿主配置：

```sh
cd /mnt/n/YGO-Kito/_publish_20261030
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
PYTHONPATH="$PWD/src:$PWD/scripts" \
/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -u scripts/run_construction.py \
  --checkpoint /mnt/n/YGO-Kito/_local_cpu_20261027/reports/optimization-20261031/2207-course-006/course/checkpoint-1.weights \
  --model-binding /mnt/n/YGO-Kito/_local_cpu_20261027/reports/optimization-20261031/2207-course-006/model-binding.json \
  --environment /mnt/n/YGO-Kito/_local_cpu_20261027/source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json \
  --workspace /mnt/n/YGO-Kito/_local_cpu_20261027 \
  --native-root /mnt/n/YGO-Kito/_local_cpu_20261027/assets/native \
  --period 2022-07 --theme setcode-181 --mode development --slice-seconds 120 --iterations 4 \
  --output .cache/construction-next-slice
```

续接时增加`--resume 上一片目录/kernel.json`并指定另一个全新输出目录。保留原任务、骨架、候选、Evaluation及查询／评价游标；不能删参考、人工补牌或改变通过线来制造通过。输出包括任务、结果、会话、可续接kernel、候选牌表和摘要；`listing_complete`只说明张数齐全，是否通过看`construction_passed`及Gate原因。
