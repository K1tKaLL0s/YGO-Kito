# 轴与泛用 v3：本地一键训练

2026-11-10，香港时间。本入口在普通本地 Python 进程中执行，启动后不调用 Codex、外部模型或 API，也不需要助手逐轮续办。使用现有 v3 准备/训练/校准/评估模块，没有另建训练器。用户已授权补齐全部 18 项资料并在全面就绪后脚本启动；Dot 负责到时重启对话检查。当前实际结果见[完整 18 项运行报告](../reports/2026-11-10-axis-generic-full18-training.md)，[前次报告](../reports/2026-11-09-axis-generic-automatic-training.md)保留历史。

## 启动、准备和状态

完整代码目录为 `N:\YGO-Kito\_publish_20261030`。正式启动或恢复，双击仓库根目录的 `Start-Axis-Training.cmd`。双击是本次运行的显式训练选择；仅打开文档、导入模块或执行无参数 PowerShell 脚本不会训练。准备未满足时退出 2，缺口写入 coverage.json，不能通过双击绕过。

也可在 PowerShell 执行以下命令。启动和恢复使用同一命令：

```powershell
& 'N:\YGO-Kito\_publish_20261030\scripts\axis-generic-training.ps1' -Start
```

只准备资料、检查 CUDA/空间、预留校准组和输出覆盖报告：

```powershell
& 'N:\YGO-Kito\_publish_20261030\scripts\axis-generic-training.ps1'
```

读取当前保存状态（不会准备、训练或评估）：

```powershell
& 'N:\YGO-Kito\_publish_20261030\scripts\axis-generic-training.ps1' -Status
```

训练过程保留本地窗口；Codex 无需打开。电脑保持运行，关机、睡眠或关闭训练窗口会中断执行。Ctrl+C 可以停止；再用同一 Start 命令从最近完整 checkpoint 接续，尚未保存的批次会重算。训练结束后再次启动不产生额外训练更新，已验证的预测/评估工件按绑定复用。

退出码 0 表示本次请求完成（可能是只准备或读取状态），2 表示真实资料尚未满足选模/校准要求，1 表示错误，130 表示 Ctrl+C。CMD 显示退出码并保留窗口，PowerShell 透传 Python 的退出码。并发重复启动会被 OS 文件锁拒绝；进程退出后锁自动释放，不需要删除锁文件。

## 配置与位置

唯一自动编排配置为 `training/axis_generic/config.automatic.v3.json`，引用 `config.v3.json` 和 `config.train.v3.json`。通过 PowerShell 的 `-Config '绝对路径'` 可以选择另一个显式配置。解释器默认 `E:\Ana\envs\pcacgate\python.exe`，可用 `-Python` 显式指定已有相容环境；没有安装/下载步骤或 CPU 回落。

用户指定新工件保留在 N 盘本项目内：

| 内容 | 本次路径 |
|---|---|
| 补充源资料、卡文、协议、冻结划分 | `N:\YGO-Kito\data\axis_generic\v3\full18-20261110-008` |
| 准备数据和分片 | `N:\YGO-Kito\data\axis_generic\v3\prepare-full18-20261110-006` |
| 模型、checkpoint、训练配方、最优引用 | `N:\YGO-Kito\data\axis_generic\v3\base-full18-20261110-001` |
| 自动流程状态、日志、覆盖和后处理 | `N:\YGO-Kito\data\axis_generic\v3\automatic-full18-20261110-002` |
| 运行临时目录 | `N:\YGO-Kito\data\axis_generic\v3\temporary` |

源资料继续只读使用 `N:\YGO-Kito\data\axis_generic\source`。新的准备结果在独立 attempt 内完成后发布；失败的未完成 attempt 保留供诊断，下次尝试不会把它当成完整数据。不要手改 manifest 或删除旧实验来让预检通过。

源配置的 formal_training 始终为 false。Start 只在本次调用内明确打开基础训练，生成本次调用配方。自动 LoRA、核心课程恢复始终关闭。基础配置保持 64/2、dual、route off、AdamW、微批 32/有效批 64、最多 20 轮、patience 4，不因显存不足自动换设备或改模型；本次每个有效批保存一次，另有初始和每轮 checkpoint。CUDA 与磁盘空间在每次启动预检，当前默认最少保留 5 GiB 空间。

训练器在构造模型前检查固定 selection_tasks 的有效训练标签、开发类别与正式输出坐标；自动脚本另要求至少 2 个校准来源组。未显式填写 calibration_groups 时，按固定 seed 对 validation 来源组作确定排序，预留约 25%、至少 2 组，并至少保留 1 个开发选择组。实际来源不足时明确失败。划分结果冻结为 reserved-partitions.json，后续不能悄悄重选；不使用 final 结果选择划分。

本次补标使用真实卡库、118 个历史案例中的 63 份不同牌表及 14 个逐卡文审阅的功能单位，形成 1819 条源记录。新补标明确为助手审阅的弱情境监督，未知格保留未知，不当人类金标或引擎实测。完整旧变体只用于保留 30 个历史关联来源分量，不作为独立标注复制。建图前冻结 22 个训练组、3 个选模组、2 个校准组、3 个历史评估组；配置的通用随机比例 1/0/0 表示由逐源 reservation 指定实际留出，不表示全量进入训练。准备后检查实际分区与冻结清单完全一致。

`full18-readiness.json` 逐项核对全部 18 个任务、全部固定坐标在训练/选模/校准中的类别及来源组，并检查真实查询、双配置操作、卡文引句及来源历史；任一缺口都禁止更新。`-Start` 通过此检查后，先以相同模型/优化器/有效批执行有界 CUDA 实测，在独立 timing 目录验证 checkpoint 恢复后的下一步完全一致，再进入正式 fit。实测不是正式模型成绩。

## 查看结果和恢复边界

自动目录的 `state.json` 给出当前阶段、状态、进程号和最近训练进度；`events.jsonl` 是逐次累积事件，包含数据加载及每 128 条准备进度。`attempt-0001.log` 等保留每次控制台输出和错误栈；`summary.json` 给出最近一次结果、耗时、CPU 用时、设备、磁盘与 CUDA 峰值分配。`coverage.json` 列出 18 个任务的训练/开发/校准类别、坐标、标签数量和来源组，`hardware.json` 保存实际设备预检。

`timing/measurement.json` 保存实测批耗时、开发预测耗时、CUDA 峰值和恢复验证；`estimate.json` 根据后续实际批/轮更新剩余时长及香港时间的预计完成/检查时刻。检查时刻在估计剩余时长上加 25% 余量，最多 20 轮的外推不预测早停是否发生。`dot-handoff.json` 保存首次启动时的 PID、日志和路径；其中的初始检查时刻是快照，最新时刻以 `estimate.json` 为准。Dot 到时读取状态和日志，再决定是否进入结果检查或按相同 Start 命令恢复。

训练目录的 `experiment.json`、`recipe.json`、`partitions.json` 绑定模型、配方、数据和来源；`latest.json` 是最近快照，`best-development.json` 指向开发集最优快照。首次更新前保存零步快照；若快照已发布而 latest 尚未提交，下次从本实验已发布的最新相容快照恢复。缺失的可重建元数据由实际绑定重建，损坏或不相容 checkpoint 会拒绝，不能自动改用旧权重。

修改数据、源处理实现、网络或优化器等会使原绑定失效。新资料使用新的 prepare 目录，新配方使用新的训练和自动状态目录；保持旧目录原样。没有自动覆盖、清空、热迁移、旧 best 猜测或活动权重切换。

默认在基础训练完成后运行预留组校准，并分别评估存在的 test 和 retrospective_test。使用实际 best 的 inference 加载及完整 model_id/dataset_id/records_id 预测工件。缺少某个评估分区时记录 unavailable，未覆盖的校准任务保持 uncovered。所有旧资料的消费历史保持；retrospective 成绩不能标成新的独立测试。

`postprocess.calibrate=false` 且 `evaluate_folds=[]` 可显式关闭后处理；这是新运行配方设置。消融、环境支路沿 [v3 软件说明](axis-generic-software-v3.md) 的独立显式入口进行，不在自动默认链中。此脚本不生成发布候选、不激活模型，也不运行 CB、原生引擎、整仓 CI 或核心训练课程。
