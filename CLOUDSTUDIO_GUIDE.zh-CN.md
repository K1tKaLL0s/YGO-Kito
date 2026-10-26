# CloudStudio 与云端 Codex 交接

YGO-Kito 用真实游戏王引擎执行合法动作；四模型分别负责构筑目标、卡组优化、决斗策略和统筹调度。构筑目标生成条件路线，优化模型调整主／额外／副卡，决斗模型在受限观测和合法动作 DTO 上决策，统筹模型根据分账反馈安排后续任务。数据按训练、预跑和冻结评估隔离；更新与资源绑定、优化器、LoRA、RNG、预算及阶段状态一起保存。

## 当前状态（2026-10-26 同步）

源码基线：PR #4，6cef642cc840120fc6d445cfbf7b8bc082b61f0d。它已包含自主构筑、合法换备 BO3、输者选择先后、完整场计数、逐小局 LoRA、恢复和冻结评估；此前该提交的本地与远端回归为 617／617，零跳过。本次只做文件与静态核查，新增检查另列。

CloudStudio 主目录 /workspace 的 main 仍是 7e92994；原用户未提交文件保留。独立源码工作树 /workspace/.cache/codex-gpu-20261026 与 /workspace/.cache/codex-pr4-final 保持 6cef642。同步工作树是 /workspace/.cache/codex-cloudstudio-sync-20261026，分支 codex/cloudstudio-handoff-20261026，基于 PR #4 分支；不自动合并 main。

用户已切换到 CPU 4核8G：历史盘点为 Xeon Platinum 8255C，容器 4 CPU／8 GiB。CPU 环境 /workspace/.venv；独立 CUDA 环境 /workspace/.cache/cuda291-venv 保留。正式训练为 0；迁移后仍须核对资源绑定、真实路径和可加载性。

## 实测与起点

[完整 CPU／GPU 报告](GPU_COMPARE_20261026.zh-CN.md) 记录上午 A10 主机实验。16／16 真实冻结对局完成，CPU／GPU 各 8 局，失败和超时均为 0，配对轨迹相同。CPU 平均 67.312 秒，GPU 66.986 秒；波动不足以确认整体 GPU 优势。四模型串行周期 CPU 1.851 秒，GPU 2.466 秒；实际 DTO 批量 32 推理 GPU 较快。当前实现的整体 CPU 路线适合继续准备。这些耗时属于原 A10 主机；切换规格后用户取消重新计时，本轮未重测。

冻结对局源 checkpoint 为 step-2.weights，随机初始化种子 123 后完成 2 次工程 PPO 更新。四模型源 checkpoint 为 local-step-7.weights，四角色各完成 1 次 base 和 1 次 LoRA 工程更新。它们的正式训练更新为 0；角色、哈希、字节数和受控迁移方式见 [资产清单](docs/reports/cloudstudio-20261026/migration-assets.json)。汇总证据在 docs/reports/cloudstudio-20261026/；原始日志、权重和依赖仍在 CloudStudio 缓存中。

## 准备剩余项

1. 将原生引擎、C# bot、卡库／脚本、source_group checkpoint 及绑定迁到获授权的新运行宿主，按清单校验哈希；按哈希锁重建 Python 环境。先核四角色实际加载和恢复。
2. 将已获取的发行日期和禁表来源转换为逐期、逐卡可核验清单。来源收据已同步，完整第三方数据库留在缓存；再核 cdb、正式 OCG 发行、合法原始牌表和修订牌表。2610 设计截止 2026-11-01，当前时间尚未到达；当前可用子集按已发生的实际发行核实。
3. 补齐 active_environment、available_cards、bootstrap_task、source_group、合法牌表与独立 train／validation／final 对手分区，产出实际 host 配置。此前 course-host.partial.json 预检为 blocked；缓存里尚无已完成的 CPU 新机课程配置与功能 BO3 结果。
4. 必要功能预跑只核四模型加载、阶段启动、真实 BO3 换备与输者选先后、参数更新和完整保存恢复。预跑单列，保留原始起点。此轮不追加独立计时或性能对照。
5. 正式启动方案需给出阶段、工件哈希、牌表与对手、场数、累计 100 小时硬预算、恢复和停止方式；用户通知及授权后再启动。

## 阶段与数量规则

2207、2210 继续珠泪主训练，发行设计截止分别为 2022-09-30、2022-12-31。原批准规则和通过条件见 [统一设计](docs/plans/2026-10-22-unified-development-spec.md) 与 [历史完整操作说明](docs/development/cloudstudio-runbook-20261026.zh-CN.md)：含外部对手 BO3、镜像与独立冻结评估，按原门槛执行。

2610 依次自主选主题→构筑与 CB 推理→合格 bot BO1→当期常见卡组 BO3。先手胜率 >49%、后手 >39% 只适用于 2610，按实际小局先后手统计。BO3 包含合法换备、输者选下局先后和先得两胜的大场终局。

正式样本按完整大场：既有实际小局平均 ≤60 秒时至少 1000 BO1＋100 BO3；>60 秒时至少 1000 大场，BO1:BO3=6:4。计时预跑与冻结评估独立，不抵最低量。总训练预算 ≤100 小时，包含采样、更新、评估和失败开销。原硬件记录属于慢档；新宿主不沿用未经确认的精确预计完成时间，也不擅自减少样本或超预算。

## 可操作入口

在选定同步工作树，现有 CloudStudio CPU 解释器为 /workspace/.venv/bin/python；新宿主改成按 requirements/ci-cpu.txt 重建的解释器。先查看 [课程 runner 文档](docs/development/scenario-course-runner.md)，生成新模板：

```bash
PYTHONPATH=src /workspace/.venv/bin/python scripts/scenario_course.py --template --output .cache/course-host-template.next.json
```

填齐真实工件后，先用 --config 与 --output 做默认预检；预检通过才选择 --pilot。--run 是正式训练入口，需等待用户新授权。目前 .cache/actual-course-host.json 尚未生成，不能照抄文件名直接启动。恢复字段和暂停边界按 runner 文档及所用 host 配置执行；记录运行 ID、PID、日志、累计预算和 checkpoint 后再给出精确停止／恢复命令。失败保留结果与最后完整场 checkpoint，查原因后在新输出目录续接，冻结评估仍隔离。

## AI 对战、学习边界、自对练

底层已有真实引擎对局、模型动作、工程训练／更新、BO3 状态机和课程调度。详细能力地图见 [同步交接](docs/development/cloudstudio-sync-handoff-20261026.zh-CN.md)。仓库这些入口与图形客户端功能分开核验；这次没有新增图形对战界面，也未完成训练模型间对抗阶段。后续云端任务应先核双模型席位、独立对手权重与分区，再决定自对弈课程和冻结评估；原计划依赖的 2610 外部操作对练须另行安排实际模型／人工对手来源。

一句话接续：“从同步分支补齐迁移资产和 CPU 阶段配置，完成功能预跑；先报告正式启动方案，等我确认。”
