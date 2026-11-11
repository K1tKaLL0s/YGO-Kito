# 当前构筑设计符合性、优化接线与旧实现核验

结论：当前构筑尚不能验收为完整满足原设计或完成全部优化对接。正常自主构筑主链确实使用新两层评价，四阶段、任务身份、库存合法性与来源记录均有实际证据；但本次复现了未知选择条件被当作已覆盖、下游模型重排覆盖两层结论两个缺陷，确认缺口再检索没有越过初始候选窗口，并发现仍被可执行入口调用的旧构筑分支。旧实现尚未统一迁移，也不应把所有历史兼容代码一并删除。

核验日期为2026-11-02，开始于11月1日。源码为`N:\YGO-Kito\_publish_20261030`，分支`codex/optimization-20261031`，HEAD `3f57198`加当前未提交工作区。用户要求本轮重新核验，未要求实施删除；本轮没有修改生产Python文件、模型、牌表或课程状态，没有提交。CB与正式训练暂停约束继续有效。

## 1. 执行范围与依据

核验前已交付执行书：主进程对照设计，追踪真实入口和消费者；发现疑点后只做明确的隔离复现；CB、原生引擎或训练所需步骤不执行；产出可追溯问题和保留／迁移／删除判断。没有子代理或待答问题。

依据包括[原设计定稿](../current/游戏王AI项目设计定稿.docx)（特别是缺口再检索与构筑迭代）、[统一规范](../plans/2026-10-22-unified-development-spec.md)第2、3、5、18节、[第一层r3.1](../plans/2026-11-01-effect-block-axis-layer.md)、[第二层r3](../plans/2026-11-01-relationship-closure-layer.md)，以及现行[构筑入口说明](../development/construction-logic.md)。新明确设计优先；旧设计的基础CB步骤本轮受用户禁止CB指令约束，不运行它来补验。

## 2. 发现的问题

### CD-AUD-01／P1：未识别的必要选择条件仍可能获得确定覆盖

`construction_inventory.specs`将未解析的费用放入`unknown`，但`evaluate`仍只用已解析的requirements调用`_check`。已解析列表为空时得到`inventory_present`、shortfall=0；`unknown_selectors`随后只是附加字段。第一层接线只处理missing，没有将这种相关未知传入功能证据；比较器的`dependency_covered`又只看预算未覆盖卡，没有检查选择条件未知。

最小复现有两副匿名合法牌表：A的必要费用已知缺件，B把对应功能换成带“7星以上”未支持限定的费用。B得到`inventory_present`、K=1、E=1、unknown_copies=[]，并被明确判为preferred；其unknown_selectors实际非空。这是同一功能的必要费用未知，不能按“缺口已清除”给予确定优势。

位置：[未知选择条件记录](../../src/ygo_kito/construction_inventory.py#L98)、[状态计算及附加未知](../../src/ygo_kito/construction_inventory.py#L167)、[仅missing进入功能证据](../../src/ygo_kito/construction_layer_flow.py#L221)、[缺口比较覆盖判断](../../src/ygo_kito/construction_layer_flow.py#L323)。复现原始数据见机器回执的`probes.unknown_selector`。

处置方向：把与所选功能有关的未识别费用／对象保留为未知依赖；原有已知缺件仍可报告，但不能把未知依赖当作完整库存支持或确定覆盖。比较中区分相关未知与无关未知，补入本反例。上一轮三个已识别条件的修复仍有效，但不能据此把未知条件处理也记为完成。

### CD-AUD-02／P1：学习后的重选可绕过两层，并错误记录比较来源

`local_course_collaboration.cycle`在rubric偏好更新后调用`rank_after_update`，后者仅取模型分数最大值，随即写入course.deck并调用`select_retained`。没有重用两层偏序，也没有要求两层结论为取舍／等价／未定。`select_retained`无论调用原因是什么，都把来源记录为`completed_fair_comparison`。

最小复现使用相同匿名候选和固定模型分数9／1：两层已明确选择有配套的候选1；`rank_after_update`选择缺件候选0；`select_retained`接受并重新带回已知缺口，还写入“完成公平比较”。复现没有执行优化器更新，也没有实际公平对局比较，证明的是该生产重选函数的控制流。真实课程只有在取得完整rubric分差并执行该分支后才会触发，本次未启动课程。

位置：[课程重选及写入](../../scripts/local_course_collaboration.py#L247)、[纯模型argmax](../../src/ygo_kito/rubric_learning.py#L9)、[无条件比较来源](../../src/ygo_kito/construction_candidates.py#L352)。第一层设计第4.5节明确仅在取舍、等价和未知时继续使用旧模型次序；当前分支超出了该范围。

处置方向：统一候选重选接口，模型分数重选保留两层已确定的优先关系；真实对局比较改选单独记录其来源和范围。不要让模型重排冒用已完成公平比较的来源。

### CD-AUD-03／P2：缺口再检索仍封闭在首次内部候选池

原设计定稿“缺口驱动的再次检索”及统一规范第3.2节要求把资源／桥接缺口转成检索条件，不能将第一次召回封闭成永久候选池。当前`AutonomousConstructionKernel._pool`在创建任务时召回一次；实际2207任务窗口为32张。随后依赖修复的recall和incoming均只遍历`task.pool`，四阶段图修订和同任务重构没有根据缺口再次查找`available_ids`的路径。

因此，“按缺口找支撑件”已在窗口内部实现，但初次未召回的合法支撑件仍不可进入。它是原设计的未完成项，不能用增加局部修复步数替代。这里不要求突破用户显式限定卡池，问题在于把系统自己生成的候选窗口与用户授权的时期卡池混为同一边界。

位置：[首次窗口生成](../../src/ygo_kito/autonomous_construction.py#L322)、[任务池固定](../../src/ygo_kito/autonomous_construction.py#L375)、[缺口召回只查task.pool](../../src/ygo_kito/construction_inventory.py#L214)。这项结论来自源码调用核对及已有2207任务记录，没有运行新的构筑或CB。

处置方向：区分授权卡池与本轮工作窗口；必要缺口触发受预算限制的再召回，保留原目标、固定卡、发行与禁表约束及候选来源。任务／特征绑定须沿正式接口更新，不能临时把池外卡塞入牌表绕过校验。

### CD-AUD-04／P2：旧交替构筑仍是可达执行分支，未统一到新链

`build_pipeline.alternate_build`仍按模型分数选择、逐阶段使用旧目标验证，并从历史阶段候选按旧preference或平均印刷攻击力代理选best。它没有构筑逻辑图、第一层或第二层评价。它共享当前候选生成器，因此并非完全冻结的旧版本，也不能视为新流程的等价别名。

AST及调用核对发现5个生产源码调用位置：`build_training.py:387`、`construction_curriculum.py:190`、`group_runner.py:866`、`lora_group.py:234`、`model_group.py:229`。其中一部分为明示工程smoke，不能冒充当前正式课程；但`LocalCpuBackend`对`four-model-alternating-v1`的worker仍通向group_runner，这也不是无调用者的死代码。当前2207的PowerShell课程入口使用另一条新链，未误指向这条旧分支。

最小复现让新旧入口处理相同两副匿名候选：新fill选择配套完整牌表；旧alternate_build完成4阶段后仍选择缺件牌表，且没有layer_evaluation。没有调用CB或原生引擎。

位置：[旧选择循环](../../src/ygo_kito/build_pipeline.py#L325)、[group运行调用](../../src/ygo_kito/group_runner.py#L866)、[本地worker路由](../../src/ygo_kito/local_training.py#L482)。

处置方向：迁移仍应提供现行构筑语义的调用者；历史工程验证入口则明确版本与弃用边界。调用关系处理完后再删除旧执行分支，不能现在直接删除整个build_pipeline或build_training——它们同时提供新链正在使用的合法性、生成与训练公共接口。

## 3. 设计符合性与新优化对接范围

| 设计项 | 核验结果 | 证据／限制 |
| --- | --- | --- |
| 独立目标／优化模型、无LLM也可运行 | 已有实现 | 现有两个BuildRanker及共享协议；图枚举由程序完成，模型负责评分 |
| 原目标和硬约束保持、四次具体交接 | 当前自主链已接通 | 上轮run-03从空牌组4阶段连续，任务／时期校验通过；本轮复核源码 |
| 构筑逻辑→狭义主轴筛选→填卡 | 当前自主／controller链具备 | 内部显式主题任务不冒充用户文本分类结果；旧alternate分支不具备 |
| 新两层影响实际候选选择 | 已接通，但有缺陷 | 上轮63份阶段候选、465对比较；本轮CD-AUD-01、02限制其正确性与下游一致性 |
| 已识别费用／对象／选中额外素材的库存缺口 | 已接通 | 原三个缺口能识别并改变选型；未解析条件仍有CD-AUD-01 |
| 自动完整资源关系、竞争、自肃、替代与取得条件 | 部分接通 | 显式LayerContext内核已有实现；正常自动上下文仍有粗功能unknown，库存侧投影补充必要缺件；原run-03四阶段joint_required均unknown |
| 新K/E、关系与库存字段进入神经模型学习 | 尚未接入，现行设计明确后置 | BuildEncoder仍v6效果机制特征；相关训练接口没有消费layer_evaluation。不能把规则重排称为模型已学会新两层 |
| 按缺口再次召回初始窗口以外的合法组件 | 未完成 | CD-AUD-03 |
| 原70／56课程评分与新两层统一迁移 | 尚未完成，现行设计明确保留旧版本 | 当前课程factory仍指向unit-block-v1或绑定的历史epoch；新两层没有取代完整课程评分、准入或学习标签 |
| 泛用／Side策略及完整构筑总分 | 现行设计后置 | 不因本轮未实现而误称代码回退；也不能据部分两层检查宣告整套构筑质量完成 |
| CB及正式训练能力 | 本轮不执行 | 用户禁止CB且训练保持暂停；沿用已有证据，不增加能力通过结论 |

“joint_required=unknown”本身不应强改成missing或通过，它反映自动关系证据不足；已知库存缺口仍应独立可用。第一层第4.5、7、8节明确保留新特征学习、自动需求及完整总分的后续实施边界，不能把这些待办伪装成已接通，也不能反过来把全部待办当作本轮回归故障。

## 4. 旧代码与模块的处置判断

| 对象 | 当前用途 | 判断 |
| --- | --- | --- |
| alternate_build及重复的旧交替选择 | 仍有5个生产源码调用位置，另有历史fixture | 活跃并行旧路径；迁移／隔离调用者后移除重复执行，见CD-AUD-04 |
| rubric_learning.rank_after_update的纯模型重选、select_retained固定来源 | 当前课程反馈后的部署选择仍调用 | 必须修复接线及来源，不是删除整个学习模块，见CD-AUD-02 |
| reference_scoring旧积木合分、70／56、CourseAdmissionPolicy、FailureTracker | 历史课程评分、账本恢复及偏好学习仍消费 | 现行第一层第8节明确按原版本保留，不能当死代码删除；迁移前不得宣称已替换为两层总分 |
| engineering_proxy | 平均印刷攻击力工程标签、旧smoke数据校验及旧交替分支 | 不应进入现行完整构筑质量；历史fixture校验可保留隔离，生产旧分支随调用迁移退出 |
| build_intent中的规则分析 | LinearIntentClassifier实际特征提取仍调用，固定规则置信不作为模型置信 | 正在使用的辅助能力，保留；当前正常入口传入实际分类器 |
| LEGACY_FEATURE_VERSION、migrate_legacy_ranker、原18维布局 | v5→v6显式模型与Adam迁移；当前checkpoint兼容边界 | 保留，删除会损害恢复与迁移，不能只因命名legacy清理 |
| tests/legacy_course_5cf3dc1 | test_integrated_course_migration加载的固定旧状态实现 | 历史迁移测试资产，保留，不是生产运行源 |
| _local_cpu_20261027/source旧检出 | 资源／历史实现来源与其他明确入口 | 当前course入口已经指向_publish；不以目录旧就整树删除，须按实际引用处理 |
| basic_cb_inference及旧CB验证接口 | 现行CB能力及历史支持目标的验证，不是被两层替代的功能 | 保留；本轮禁止调用。两层并未承担动作编排和规则执行 |

本次未发现已撤回的T_f主题配额、4/6或75%/25%合分出现在新construction_layers计算链；这些在设计中作为历史算例保存。旧模型分数在新偏序不可确定时回退，是现行设计允许的行为，不应整体删除。需要清理的是绕过新结论的执行分支和错误来源，而不是统一删除所有名为旧、legacy或工程的代码。

## 5. 当前入口与验证证据

执行`local-training.ps1 -Action Check -Job course`得到：source_root=`/mnt/n/YGO-Kito/_publish_20261030`，resource_base=`/mnt/n/YGO-Kito/_local_cpu_20261027`，state_root为课程006，training_held=true，worker_started=false。旧资源副本没有冒充本次正式course源码。

本轮新执行3个定点反例：未知费用覆盖、两层后重选覆盖、旧／新入口选择差异。它们“复现成功”意味着缺陷存在，不是正确性验收通过。运行使用现有WSL Python与固定合成分数，不创建优化器，不更新参数，不加载生产checkpoint；CB推理、CB提案、NativeNormalEngine构造均设置调用即失败，最终计数全0。

上轮105＋15项测试与2207 run-03只作为既有证据复用，没有重复运行。定点反例揭示其未覆盖的边界。源码AST调用核对、报告数据及本批文档差异检查单列；本轮无GPU、远端CI、真实引擎或正式训练验证。

入口日志、探针和原始结果在`.cache/construction-design-audit-20261101/`；[可携带核验回执](2026-11-02-construction-design-audit.json)保存反例结果、旧调用位置和当前入口。训练继续暂停，未开放CB。下一步应先处理CD-AUD-01、02，再闭合再召回与旧分支迁移，之后重跑构筑验收。
