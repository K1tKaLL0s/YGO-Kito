# 轴与泛用模块设计核查、质量修复与旧入口清理

2026-11-09，香港时间。实际仓库：`N:\YGO-Kito\_publish_20261030`。主进程执行，无子代理、无待答问题。修改前交付[机械执行书及 R1–R7 增量](../plans/2026-11-09-axis-generic-review-cleanup.md)，按用户授权检查实现、修复确定缺陷并删除确认不再调用的旧文件。

## 结果与适用范围

先前的软件完成报告不足以排除实现缺口。本次对照 A01–A10、T1–T5 及实际消费者，发现并修复目标上下文未进入图网络、单图副本偏好、早停中断恢复、校准/评估来源与工件绑定、环境反馈预检等问题；清理了 28 个废弃文件和旧神经 CLI 分派。当前准备、训练、预测、评估和环境适配链已有实现及对应工程证据，本次发现的确定缺陷没有遗留未关闭项。

最终受控回归 177/177 通过，0 failure、0 error、0 skip，禁止调用尝试为空。包括 22 个本次设计复查专属方法。所有本轮批次合计 653 次物理执行，含 3 个中间 loader 失败，不将重跑次数说成不同测试数量。静态检查、三份配置、五个入口 help、纯导出/准备导入和当前文档链接检查通过。

这是源码与工程验收结论。真实资料准备、正式训练、真实独立校准/评估、GPU 实机、CB 搜索、原生引擎、CI 和实际能力发布均未执行。没有提交、推送、切换活动权重或指针；没有修改构筑定价/生产政策。旧资料、所有 runs/权重和无关既有改动保留。模型是否学会相应能力仍须真实监督及独立评估，不能由工程样本更新推定。

## 修复的实质问题

### 目标条件与固有性质分开编码

原 `graph_network.encode_graph_batch` 只编码图、模式、分区数量和局面/资源存在标志，没有读取 `RoleInput.context` 的结构化目标因子。同一物理配置即使提供不同目标，条件角色也无法据此改变。

现用 `task_queries.INTENT_FACTORS` 明确选择 `CONTEXT_FACTORS` 中非 `plan_` 因子，按原值/已知/置信度/不确定度四通道生成独立 intent，经 `intent_encoder` 进入条件读出和双配置比较。mechanism、成员、轴功能/来源、固有迁移性及旧规模头不读取 intent；axis_position 按其主/辅语义读取。single/dual 都保持这个边界，环境独立支路也能消费目标编码。

准备 `input_key` 同时包含实际编码目标通道，不同目标的监督不再合并成冲突；来源关联仍让它们进入同一隔离组。固有性质一致性排除目标因子与当前公共库存，保留定义和格式/时期/规则边界。特征/编码指纹更新，旧语义权重拒绝隐式恢复。仅修改目标因子时条件输出可变而固有输出逐值不变；修改不透明目标名、来源或旧计划代理字段不会改变 intent。实际构筑 `context_provider` 传入因子也已有对照验证。没有添加目标文本解析或恢复旧计划关键词规则。

### 副本偏好采用真实双配置

原批量训练/评估可用单图查询表达副本偏好，与服务对前后两配置独立观察、构图的路径不一致。现统一 `comparison` 契约，包含右配置观察、左右单元引用及真实 add/remove 操作；校验同目标、功能、规则，且操作确实得到右牌表。单图旧偏好、说明字符串操作和不相容比较在更新前拒绝。

准备对两端独立构图，输入键绑定两端和操作；派生变体沿用同一键算法，不丢已审核偏好。划分同时考虑两端牌表/卡引用，右侧留出卡也不能泄漏。批量编码追加右图、保留比较索引，训练、预测和服务共同调用 `GraphRoleNetwork.score_preference`，上下文只取指定两个配置。成对记录的图预算包含右图。服务和批量预测原始概率一致已有验证。

### 训练、恢复与推理职责

`train_supervised` 和 `train_accumulated` 合为同一个 v3 更新实现，按整个有效批量的来源/任务分母计算梯度。零证据头不前向，也不会因 AdamW 衰减改变参数。全未知、零置信度、无效标签和无法同微批表达的一致性对在更新前处理；不丢记录来满足预算。

早停/完成状态先写入 epoch checkpoint，边界中断恢复不会额外训练；缺失最优元数据可由已绑定的最优引用恢复。可变 JSON 使用唯一临时文件和原子替换，残留固定 `.tmp` 不再阻塞。恢复核对 partitions 及完整绑定。选定任务的训练标签、开发类别和正式任务坐标覆盖在构造模型前检查，不自动删任务凑分。

新增只读 inference 加载：验证权重与特征绑定，不恢复训练优化器/RNG，允许显式不同运行设备/环境，冻结模型且拒绝训练更新和训练 checkpoint 保存。预测和环境底座加载使用它；resume 继续严格恢复完整训练状态。fresh/warm_start 在数据检查后设置明确种子。

### 来源、预测、指标和宿主能力绑定

`record_sources` 核对记录 schema、标签协议、来源组、头部来源类别及每个已知格的实际来源、身份、置信度和允许的上下文来源。修改来源头部不能把工程标签伪装成真实证据。最终独立测试要求明确 `previously_consumed=false`；消费历史未知按回顾性资料处理。

预测 CLI 返回完整 `axis-predictions-v3` 工件，绑定实际权重 model_id、dataset_id 和完整记录 records_id。真实校准/评估拒绝外层绑定丢失的裸映射、错模型和错记录；纯算术工程夹具仍可用小映射。准备缓存与训练/评估读取核对完整准备实现，而非只检查两个文件。校准也绑定标签协议。

多标签指标先按每个固定坐标做来源等权，再做坐标宏平均，未覆盖坐标不删除，避免常见坐标掩盖稀少坐标失败。指标版本为 `axis-source-coordinate-macro-v3-review1`。基线须不同模型、相同记录/数据/组/协议和指标版本。发布候选绑定实际评估和基线报告摘要；宿主接线接收这两份实际报告并重算决定，手改 eligible 或错接文件会拒绝。决定逻辑移到运行时 `calibration.py`，宿主不再反向导入训练目录。

### 环境支路与代码维护

环境入口在加载底座或创建运行产物前验证整份反馈，坏尾行不再让前面样本先更新。真实适配须提供有真实训练状态、校准和独立验证依据的底座，checkpoint 绑定这些依据、数据、配方及批边界游标。环境输入是单个实际配置，拒绝把比较记录含糊地当作一个配置。非有限校准系数、错 adapter/base/environment 身份和失配来源组拒绝；provider 重查训练组、实际 MSE 及有限数值。三个分支只改独立副本。

删除未用导入和重复逻辑，公共类型从 contracts 直接导出。修复专属测试的 `sys.modules` 清理：只恢复测试使用的 training 别名，不卸载新导入的 Torch Python 模块，避免原生注册仍在时重复注册 `_inductor_test`。这一测试隔离问题的失败日志保留。

## 现行入口与废弃清单

| 任务 | 现行入口 | 配置/用途 |
|---|---|---|
| 准备 | `training.axis_generic.prepare_only` → `prepare_v3.prepare` | `config.v3.json` |
| 基础训练/恢复 | `training.axis_generic.train_v3` | 唯一 `config.train.v3.json` |
| 预测、消融配方、校准、评估、发布候选 | `training.axis_generic.workflow_v3` | 显式 action、输入/输出 |
| 独立环境训练/恢复 | `training.axis_generic.environment_v3` | `config.environment.v3.json` |
| 事实服务 CLI | `ygo_kito.multifactor` | 必选 `--service`，不接受旧神经参数 |

三份配置的 formal_training、automatic_lora、core_course_resumed 均为 false。基础训练已合并建议的 64/2、AdamW、dropout、梯度裁剪、有效批量和早停参数；重复 software 配置删除。准备/基础训练目录分别为 E 盘独立 `prepare-reviewed-001`/`base-reviewed-001`，环境底座及发布依据仍为空，未自动选择旧权重。完整命令与工件字段见[使用说明](../development/axis-generic-software-v3.md)。

以下 28 个文件经调用/依赖核对后删除。删除前仅把相关小型源码/配置备份到本任务 `.cache/axis-generic-review-20261109-01/before`；该目录不是运行入口，没有复制数据或权重。精确机器清单为同目录 `cleanup-manifest.json`。

```text
training/axis_generic/train_base.py
training/axis_generic/prepare_base.py
training/axis_generic/prepare_balanced.py
training/axis_generic/finish_existing.py
training/axis_generic/features_v4.py
training/axis_generic/check_scopes.py
training/axis_generic/goal_semantics.py
training/axis_generic/ASSESSMENT_PROTOCOL.json
training/axis_generic/config.train.software.v3.json
training/axis_generic/historical/build_runner.py
training/axis_generic/historical/configure_plan_graph.py
training/axis_generic/historical/configure_resource_flow.py
training/axis_generic/historical/configure_role_scope.py
training/axis_generic/historical/diagnose_existing.py
training/axis_generic/config.dev-expand.json
training/axis_generic/config.dev-expand2.json
training/axis_generic/config.dev-expand3.json
training/axis_generic/config.json
training/axis_generic/config.mechanism.json
training/axis_generic/config.mechanism.smoke.json
training/axis_generic/config.p0.json
training/axis_generic/config.p0.n.json
training/axis_generic/config.p0.n2.json
training/axis_generic/config.p0.smoke.json
training/axis_generic/config.p0b.json
training/axis_generic/config.smoke.json
training/axis_generic/config.smoke2.json
scripts/check_multifactor_roles.py
```

旧 `goal_semantics` 的文本计划规则和 `features_graph` 的旧聚合/身份特征已移除。迁移实际仍需的置信度、指名和旧标签审核集中到 `legacy_import.py`，仅只读迁移，不带训练或准备入口。`features_graph.py` 保留设计要求的 v3 观察适配、共用构图和训练查询辅助。

公共 legacy DTO/网络/适配器仍有明确兼容消费者、专属测试或 CI 引用，保留其显式兼容 API；未以版本旧为由删除。旧 runs、原始标签、审核资料及历史文档保留，文档已加废弃提示并指向现行入口。当前活跃代码不再导入已删除栈；新神经预测不走旧 v2 CLI。

## 设计逐项对照

| 设计项 | 实现与本轮结论 | 有效工程证据 |
|---|---|---|
| A01 四种模式/空与未知 | contracts 的 RoleInput/DeckSpec 和 analysis 主接口；未改变模式语义 | 未变契约复用 [Q1](2026-11-09-axis-generic-m7-q1q2.md)；本轮候选/服务/输入域检查 |
| A02 逐格标签/未知掩码 | LabelCell、task_queries、graph_training；来源/证据权重及零证据头已修 | learning、training_controls、review 专属损失/来源/零更新反例 |
| A03 身份隔离/真实目标与结构 | semantics、graph_network、INTENT_FACTORS；显式目标进入条件头，固有头隔离 | 重排、身份/标签不入张量、single/dual 目标反事实、实际 context_provider |
| A04 整数资源与三值逻辑 | conditions 及共享资源分配未改，未另建规则栈 | 复用 [Q2](2026-11-09-axis-generic-m7-q1q2.md)/[V10](2026-11-09-axis-generic-m7-v10.md)；本轮服务库存/冲突重算 |
| A05 功能独立最小分支 | functional_units 保留功能分支、完整定义/当前实例边界 | 未变核心复用 Q2；本轮候选和服务定义/接收实例对照 |
| A06 自然轴候选/漏召回 | axis_candidates、semantics、workflow 指标；不靠监督补自然域 | candidates 全组，learning 自然域不变，data 固定指标漏召回 |
| A07 多头/恢复/能力 | network、graph_training、training、train_v3；统一更新和只读推理已修 | learning、training_controls、inference；早停边界、AdamW、RNG、下一步恢复 |
| A08 来源隔离/留出 | splits、prepare_v3；双配置两端和显式资料消费状态均纳入 | SourceComponents、LabelPreparation、右端留出/不同目标去重专属反例 |
| A09 三服务/真实副本变化 | analysis、scoring；与训练共用实际双配置评分 | service 全组、批量/服务偏好一致、完整域无更新推理 |
| A10 off/observe/assist 消费者 | construction_recognition/宿主政策接口沿用；报告重算逐能力映射 | construction_recognition 全组、workflow/review；CB 只验纯提示契约，未真实执行 |
| T1 准备与迁移 | 入口直连 v3，旧审核薄迁移，全实现缓存绑定 | 人工 SQLite/gzip/JSON、分片/语义缓存、来源反转和双配置变体 |
| T2 基础训练/恢复 | 配方、有效批、覆盖预检、早停和推理模式贯通 | 有界 CPU 工程更新、临时保存恢复及 CLI 预测，不消费真实分片 |
| T3 消融/校准 | 四格/多种子配方与绑定比较；逐格来源、完整预测工件 | workflow、review；没有执行真实消融实验 |
| T4 独立评估/能力 | 固定坐标来源宏平均、独立资料要求、异模型基线及宿主重算 | workflow、FixedMetric、review 的隐藏来源/错工件/少数坐标等反例 |
| T5 独立环境适配 | head_only/lora_head/full_copy、整份预检、底座依据、恢复/provider | environment 全组及坏尾行/非有限校准/底座验证专属反例 |

未改资源求解器的历史专属证据按源码不变复用，没有为重复计数重新执行。V21 哈希种子子进程方法在本次 guard 中明确排除，未记为 skip 或本轮通过；原 [Q3](2026-11-09-axis-generic-m7-q3q4-facts.md) 四格子进程证据保留，本轮仍运行反转 SQL 的同过程方法。

## 实际验证与失败轨迹

解释器 `E:\Ana\envs\pcacgate\python.exe`，Python 3.10.20、Torch 2.2.2；CPU、`-B`、不写 pycache、OMP/MKL 各 2。本轮日志与工件根为 `.cache/axis-generic-review-20261109-01`。工程源与 checkpoint 路径限定在本任务 tmp 或 `.cache/multifactor-test-temp`；没有安装依赖或下载。

| 日志 | 实际执行 | 当批结果与处理 |
|---|---:|---|
| r1-r2-r4-first.log | 27 | 全通过 |
| r3-r5-first.log | 35 | 34 通过/1 error；来源夹具误用准备后观察外壳，修正 |
| paired-prepare-regression.log | 46 | 全通过 |
| quality-boundaries-final.log | 3 | 3 loader error；公共 ANALYSIS_MODES 间接导出缺失，改为 contracts 直接导出 |
| quality-boundaries-retry.log | 38 | 20 通过/17 error/1 failure；Torch 模块重复注册导致，修正测试别名隔离 |
| quality-boundaries-isolation-fixed.log | 38 | 全通过 |
| migration-variant.log | 2 | 1 通过/1 error；变体夹具漏 supervision.kind，补齐 |
| guarded-first.log / json | 173 | 全通过，随后最终设计反事实核对发现目标编码遗漏 |
| intent-final.log / json | 114 | 113 通过/1 error；构筑夹具 declared_goal 非真实 task.goal，修正夹具；其余目标反事实通过 |
| guarded-final.log / json | 177 | 最终全通过，包含全部目标编码/去重修复 |

最终日志运行时间 21.239 秒，带加载/收据开销 21.625 秒。最终受控运行记录 Adam.step 26 次、AdamW.step 18 次、torch.save 22 次、torch.load 23 次，均为有界人工工程夹具及临时工件。上述次数只描述最终一轮，不误称为整个会话累计。

最终 runner 明确选取 review_v3、training_controls_v3、learning_v3、workflow_v3、environment_v3、inference_v3、candidates、data_v3 的 SourceComponents/LabelPreparation/FixedMetric、service 和 construction_recognition；不 discovery。真实 CB/proposals、route search/replay、native verify/engine 和未授权子进程均装执行拦截；真实源读取与 checkpoint 路径另有限定。最终 `forbidden_call_attempts={}`，`loader_errors=[]`，无跳过。精确方法清单在 `guarded-final.json`；全部批次汇总在 `acceptance-summary.json`。

静态结果在 `static-verification.json`：33 个现行 Python 文件 AST/行尾检查，当前三配置 JSON 及暂停开关/准备训练路径匹配，删除清单实物不存在、活跃导入无旧栈；五个 CLI help 和纯公共导出/准备导入退出码均为 0，纯导入不加载 Torch。限定 tracked 差异用 `git -c core.whitespace=cr-at-eol diff --check`，兼容原 CRLF，没有全仓改行尾。当前说明、核查执行书/报告及更新入口的本地文档链接逐一检查；历史正文保留其当时路径，不把它们重新当运行指南。

当前默认配置尚不能直接启动真实训练：正式开关仍关闭，真实来源的标签/开发覆盖需先达到所选任务要求，环境底座与发布依据也尚未选定。这些真实阶段没有被本次代码核查自动启动。
