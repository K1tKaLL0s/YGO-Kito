# R0—R11 设计修复与定向验收

2026-11-11，Asia/Hong_Kong。使用 `N:\YGO-Kito\_publish_20261030` 的现有工作树，分支 `codex/optimization-20261031`，HEAD `3f57198`。当前为构筑规范化 v30、效果字典 b13、质量评分 v4。评分公式、主题权重及指定参考比例 0.8 沿原设计。 [逐包方案](execution/2026-11-10-design-implementation-repair-plan.md) · [F01—F19 审计](2026-11-10-design-implementation-audit.md) · [S0—S6](../current/construction-workflow.md)

按原方案的软件通过条件，R0—R11 已完成本轮修复和定向验收。末次复核补齐了 R10 的 GPU 采样入口和阶段耗时记录，并核对其余包的源码入口与已有回执。完整构筑、训练、真实 CB／原生引擎及实机指标按原方案继续单列待验。

## 缺口与证据

| 缺口 | 实施和验收范围 |
| --- | --- |
| F01 · 完整卡文投影 | 默认效果记录、库存和关系已消费原回归中的费用、随机身份、实体引用、触发时点、次数、装备、Token、替代去向及复杂选择。末批补非效果融合目标、同时取两类指定牌、效果内通召、展示牌的异名选择与本体召唤、除外回收和召唤范围。 |
| F02 · 完整处理身份 | 同一次处理共享功能身份及同一库存。多种费用量、指定双输出、前序选择与实际去向均有定点反例。 |
| F03 · 发动限制与顺序 | 联合用途按可满足的静态顺序和真实实体分配判定，保持整回合、处理后、自己／对方和作用范围。手卡实体重复用、空墓和去向替代有正反对照。 |
| F04 · 局部枚举续算 | 共享分配、随机组合和关系 facts→uses→joint 的可序列化游标接入默认路径。原 129 个替代方案反例通过。 |
| F05 · 完成和失分计算 | 保存一致补全索引、已解释失分和待算工作，完成后才生成 Evaluation，跨片保留已算关系。 |
| F06 · 开发失败分类 | 明确静态完成失败回 S2，连续两次才提示。同一工作片恢复保持计数，预算待算、覆盖缺口与合同错误按各自状态返回。 |
| F07 · CB 回 S2 | 调度替身中，回 S2 的请求跨片生效，保留此前静态通过证据。 |
| F08 · 参考独立 | 固定参考用原任务、实际牌表、宿主必需用途和同一评分政策，参考计算独立于候选可选图。必需库存确实缺失和零分参考均有拒绝用例。 |
| F09 · 参考续片与复用 | 独立参考工作游标、完整缓存绑定和已选候选保存。相关输入变化重算，候选可选图变化时复用参考。 |
| F10 · 评价复制和比较 | 每批先绑定 Evaluation，再用紧凑不可变输入做有序比较。12 个候选跨比较、参考和学习恢复只算 66 个不同的配对。 |
| F11 · 权威提交与停止 | CLI 以带版本的 `kernel.json` 为恢复来源，旧裸 kernel 可读，`session.json` 为终态导出。安全保存完成后记录用户暂停，下一片可恢复；写失败保留上次提交。 |
| F12 · 识别待算异常 | 待算返回明确合同结果，真正内部异常沿调用链保留。 |
| F13 · 离线标签与候选检查 | 离线标注生成和分项检查已接通。原 46 例中，候选程序找到了 18 个指定组合中的 16 个。两例旅鸟的漏检保留为认知模块的验收材料。 |
| F14 · 基础 CB 目标 | 已接连接、仪式、抽卡和无指定身份的牌顶送墓目标。印刷条件、同一效果的处理证据和公共回放绑定用符号夹具验证。 |
| F15 · Agent 会话 | manager RPC 启动、继续、进度和取消复用实际调度与安全提交。Loopback 和调度替身覆盖幂等、版本、宿主隔离、取消和上线预算排空。 |
| F16 · 白名单与覆盖 | 近期构筑回归及自然候选回归在现有 CPU CI 白名单显式登记。下节记录本地定向结果。 |
| F17 · 宿主取消隔离 | 机器人资格入口为每个作业启动受控子进程并保留日志，宿主超时／取消回收本作业。Windows 和 WSL 的普通子进程测试通过。 |
| F18 · 资源监测 | CPU、内存和 I/O 的采样带来源和任务信息。资格检查命令行可显式选择 GPU，作业结束后采集设备信息、占用率和显存。报告分别保存宿主与工作进程的数据，以及预检、作业、采样和总耗时。 |
| F19 · 活动资料 | 当前索引、总清单、验收对齐表、RPC 及 BO3 入口说明已同步。 |

R0—R5 的阶段性证据保留在各批报告。v26/b11 的 360 项静态验证，以及 R5 中修正后的随机主题断言与固定参考对照，适用于当时源码。 [首批](2026-11-11-design-implementation-repair-batch-1.md) · [复杂卡文](2026-11-11-design-implementation-repair-batch-2.md) · [状态分配](2026-11-11-design-implementation-repair-batch-3-state.md) · [局部续算](2026-11-11-design-implementation-repair-batch-4-resume.md) · [计算及固定参考](2026-11-11-design-implementation-repair-batch-5-calculation.md)

## 本轮修改的主要入口

下列运行时代码均位于 `src/ygo_kito`，脚本、离线标注与检查按表中路径定位。

| 范围 | 文件 |
| --- | --- |
| 卡文、库存及共享资源 | `effect_records.py`、`effect_blocks.py`、`effect_block_rules.py`、`effect_count_limits.py`、`effect_mechanisms.py`、`construction_inventory.py`、`construction_relations.py`、`multifactor/conditions.py` |
| 静态评价、候选比较和续算 | `construction_layer_flow.py`、`construction_quality.py`、`construction_fill.py`、`construction_progress.py`、`construction_learning.py` |
| 任务保存和 CLI | `autonomous_construction.py`、`construction_checkpoint.py`、`scripts/run_construction.py` |
| 本地服务 | `construction_service.py`、`agent_bridge.py` |
| 基本识别和离线诊断 | `construction_recognition.py`、`multifactor/semantics.py`、`multifactor/axis_candidates.py`，以及 `training/axis_generic` 下的 `full18_annotations.json`、`full18_sources.py`、`prepare_v3.py`、`assessment.py` |
| CB 目标表达与交接 | `basic_cb_scope.py`、`basic_cb_inference.py`、`build_contracts.py`、`build_semantics.py`、`build_model.py`、`build_pipeline.py`、`cb_effect_points.py`、`route_search.py`、`duel_planning.py` |
| 作业停止和资源监测 | `owned_runtime.py`、`bot_qualification.py`、`agent_monitor.py`、`scripts/bot_qualification.py` |
| 回归登记 | `scripts/check_merge_candidate.py` 与回执列出的 `tests/test_construction_*`、`test_basic_cb_scope.py`、`test_multifactor_*`、`test_agent_tools.py`、`test_bot_qualification.py` |

## 识别数据和两例旅鸟

离线监督包含 6 个有原文坐标的机制正负对照，5 个接收配置的成对对照，覆盖目标资格、额外支付数量、送墓去向和发动限制。固定卡库上的一份原接收牌表实际生成 16 条记录，额外支付最小值复核为 3。未标注的坐标保持未知，源组和历史留出绑定沿原协议。旧 full18 实验已完成 20 轮、420 次更新及 88 条历史回顾，保留其数据、模型、校准、配置和拆分。 [旧 full18 实验](2026-11-10-axis-generic-full18-training.md)

沿用原牌表和固定中文卡库，让程序自行找组合，再逐例对照标注的成员和用途。18 个指定组合中，历史版本命中 4 个，当前版本命中 16 个。原 46 例及标签保留。命中的组合包括简素融合特召的非效果融合怪兽，以及魔玩具补缀同时检索的「融合」和「锋利小鬼」怪兽。`probe-001:imperm_storm40` 原标签写成了发动无效，印刷卡文是使效果无效，原记录保留以便追溯。 [原案例诊断](2026-11-10-axis-generic-new-material-probes.md) · [简素融合](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=16255&ope=2&request_locale=ja) · [魔玩具补缀](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=12866&ope=2&request_locale=cn) · [无限泡影](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=13631&ope=4&request_locale=ja)

`probe-038:floo_full_primary` 与 `probe-039:floo_full_support_goal` 用同一组六张牌，分别问主轴和支援轴。程序能找到部分配合，例如谜之地图先展示手卡中的怪兽，从卡组除外异名本家卡，然后通常召唤刚才展示的怪兽。两例各生成了 109 个候选，均未命中指定六张。牌表里还投入了巨嘴鸟、鸵鸟和未知之风，这些卡也为本家提供配合。 [KONAMI 帝企](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=16503&ope=2&request_locale=ja) · [谜之地图问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=16544&ope=4&request_locale=ja)

用户进一步明确，构筑在认知模块接入前可以具备基本认知能力，识别水平不足不使本轮修复失败。当前基本判断来自卡文、实际投入的卡和配套关系。认知模块由用户独立设计和训练，后续接入更强的体系识别能力。R8 按原定程序和标签合同验收，16/18 和两例旅鸟漏检继续如实记录。 [识别与构筑的接口分工](execution/2026-11-08-axis-generic-execution-plan.md)

## 调度、保存和验证范围

开发模式继续跨内部片运行。上线模式用共享调度停止新增候选并排空当批 S3—S5。CLI 正常暂停在提交边界落盘，服务续接以当前 `revision` 为准。CLI 与持久服务均沿原任务、原始资源绑定和权威存档恢复。旧完成证据保留，需重算的游标按实际绑定判断。 [Agent 会话](../development/generic-agent-integration.md#11-构筑逻辑分类器与本地-agent-的实际接续)

资格作业宿主限时覆盖子进程生命周期，原 C# 看门狗覆盖其内部会话。Windows 和 WSL 以普通子进程验证超时、取消和独立进程保留，资源采样只核对结构与替身。完整构筑、训练、权重推理、实际 CB／原生引擎及硬件测量仍处于原暂停范围。原 run-007 保持停止，其实际 Gate 仍以该次的已保存结果为准。 [run-007 最终记录](2026-11-10-construction-condition-selection.md#按用户最新要求结束本轮) · [Windows 进程树回收](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill) · [NVIDIA 指标接口](https://docs.nvidia.com/deploy/nvidia-smi/index.html)

Windows 筛选合组按方法 ID 去重 553 项全通过，零失败、错误和跳过，Torch 未加载。初跑的两条断言分别改为核对明确费用和对象、给发动见证绑定场上区域，最终合组均通过。Windows 无法建立的旧符号链接夹具在 WSL 单项通过，另用 WSL 复验普通子进程隔离。60 个 Python 文件的 AST、JSON 合同、目标空白及本报告本地链接通过。现有白名单 123 项登记无重复。

末次复核补上资格检查 CLI 的 `--gpu-device-index`。GPU 采样在受控作业结束后进行，用户停止或进程树回收结果不明时跳过该次设备采样。`host_resources` 记录宿主数据和阶段耗时，每行 `resources` 记录其工作进程的数据。`native_worker_wall_seconds` 是每个工作进程的限时配置，实际耗时由该行 `worker.elapsed_seconds` 与阶段计时记录。 [资格检查参数](../development/bot-qualification.md)

这次补修的 Windows 25 项、WSL 15 项定向测试全部通过，零失败、错误和跳过，Torch 未加载。验证覆盖 CLI 参数、默认行为、缺设备、取消、进程树回收结果不明及决策吞吐计算。设备值来自替身，普通子进程用于超时和取消验证。新回执为 `verification-r10-host-telemetry-final.json` 和 `verification-r10-host-telemetry-wsl.json`。原 553 项合组回执保留其验证时点。

回执在 `.cache/design-implementation-repair-20261111-resume`，对应 `verification-runtime-objectives-v30`、`verification-natural-candidates-v30.json`、`verification-offline-contrasts-v30.json` 和 `artifact-validation-runtime-v30.json`。完整 CPU CI 与远程 Actions 以各自运行回执为准。 [CPU CI 说明](../development/safe-cpu-ci.md)
