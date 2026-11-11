# 当前实现缺口修复方案

2026-11-11第四批更新：R3共享分配的显式JSON枚举栈及关系层数量/组合/回收/返回身份、facts→uses→joint接续已实施；原129反例与公开入口极小片完整见证通过。v25/b9，十个安全静态模块去重254项全通过，0失败/错误/跳过、Torch未加载。R3状态安排/随机分支和质量两阶段游标尚未实施，R5独立参考及后续包继续开放。见[第四批报告](../reports/2026-11-11-design-implementation-repair-batch-4-resume.md)及[最新独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-4-continuation.md)。训练、推理、CB/native、完整构筑、run-007保持暂停。

2026-11-11第三批更新：空墓/空场条件已接入同一必需联合、完整处理和共享副本区域分配，原空墓失败转绿；v24/b9，十个明确安全静态模块去重292项全通过。R3分配/状态安排/质量阶段真实续算及R5参考独立性仍开放，见[第三批报告](../reports/2026-11-11-design-implementation-repair-batch-3-state.md)与[R3具体执行书](2026-11-11-design-implementation-repair-resume-execution.md)。后续包继续按本方案，不恢复训练、推理、CB/native、完整构筑或run-007。

2026-11-11第二批更新：R1通用卡文处理及默认消费者已继续修复，规范化v23/字典b9。受影响九模块去重270通过、1空墓联合状态反例失败；原R3/F04、R5/F08仍失败，合计三项明确开放。先闭合R1/R2状态条件联合消费，再按本方案继续R3及未完包。详见[第二批报告](../reports/2026-11-11-design-implementation-repair-batch-2.md)和[最新接续](../handoffs/2026-11-11-design-implementation-repair-batch-2-continuation.md)，不以旧暂停/首批状态覆盖用户恢复与自主执行授权。

日期为 2026-11-10。逐包方案依据 [F01—F19 审计](../reports/2026-11-10-design-implementation-audit.md)，按[机械执行书](2026-11-10-design-implementation-repair-execution.md)实施。2026-11-11 的各包源码与验证状态见[当前验收](../reports/2026-11-11-design-implementation-repair-runtime.md)。首批的 344 项和两条开放失败保留原批次证据。训练、CB／原生引擎、完整构筑和 run-007 继续暂停。 [首批报告](../reports/2026-11-11-design-implementation-repair-batch-1.md)

## 目标与实施边界

目标是在既定设计内使完整卡文正确进入静态配置评价，有限计算真实续接，S0—S6状态正确推进，参考与候选同口径，保存/取消可恢复，近期回归覆盖真实默认入口。不得通过修改评分设计、降低参考比例、缩窄任务卡池、凭模型裸分排序、人工把 unknown 置真或增加真实对局输入来取得通过。

当前代码基线为 `N:\YGO-Kito\_publish_20261030` 的实际工作树，分支 `codex/optimization-20261031`、HEAD `3f57198`，包含大量既有修改、未跟踪和删除状态。不能从 HEAD 重建或覆盖；并行识别模块、既有权重、课程指针、暂停文件、原始规则资料、全部 run-007 成果保持原样。

后续仍使用 GPT-6.1 Sol Max，主进程执行，无子代理。没有 UI 工作。用户批准修复后，按下面顺序处理对应源文件与明确列出的测试/文档；未获批准前连 R0 都不执行。普通“启动修复”不自动恢复训练、完整构筑、CB、原生引擎、安装或收费调用。

设计不变量：

- S0任务目标、硬约束、时期全卡池和资产绑定不变；先无卡ID逻辑，狭义主题仅筛必需轴。
- 复用 InventoryDependencies、关系图、共享整数实体分配、唯一功能评分器；不增第二套求解器、评分器或独立模型决策账本。
- 保留 log2、P/V1/V2/S、Main E1及0.9、Extra 1及0.8、实际Main 40—60张、基础收益及主要+100%/次要+50%、Side方向上下文和0.8参考比例。
- 同一次处理和同一物理卡不重复获利或支付；all/any、替代处理、区域、所有者、代价/效果、条件和次数限制保持原意。
- 静态评价不需要当前手牌、实际盘面、随机命中或实际执行序列；必要联合条件与整回合冲突仍须验证。
- 真正待算保存可继续游标；语义未实现报告具体程序缺口；确定失败回S2，只有完成失败进入计数。
- 开发/训练内部片自动继续；上线到期停止生成、排空当前评价与Gate。用户停止优先，原数据保留。
- CB必须静态通过且有明确执行授权；未知或预算不足不计正常失败，不将“未找到”标为“不可能”。

## 顺序与依赖

R0 建立缺陷回归与覆盖 → R1 完整处理语义 → R2 静态限制范围 → R3 有限计算续接 → R4 主循环状态 → R5 参考阶段 → R6 性能与保存 → R7 服务生命周期 → R8 识别接口/标签 → R9 CB表达范围 → R10 后续运行保障 → R11 汇总验收。

R4的短调度修复可在R1—R3尚未闭合时先完成，但不能因此宣称静态构筑已通。R8训练数据/并行模块先核对当时实际工作树，不覆盖其他任务成果。R9只实施软件表达与静态测试，CB执行仍暂停。R10的真实native/GPU/PC验证按所属阶段另授权。

## R0：固化缺陷回归和真实默认入口

对应 F16、F19，并为 F01—F15 建立验收基线。

| 要素 | 执行内容 |
| --- | --- |
| 前置 | 用户已明确启动修复；读取当前AGENTS和代码执行细则；核对报告列出的目标代码是否被其他任务修改 |
| 文件/符号 | `scripts/check_merge_candidate.py:MODULES`；现有 `tests/test_construction_workflow.py`、`test_construction_text_completion.py`、`test_construction_static_entries.py`、`test_construction_runtime_processing.py`、`test_construction_condition_selection.py`、`test_construction_calculation_resume.py`、`test_construction_recognition.py` |
| 修改动作 | 将本报告的短反例转为现有模块中的有区分力回归；将上述7个安全模块显式登记；检查模块不加载native、不更新参数。保留 reviewed评分夹具，同时增加不传quality_evidence覆盖的真实默认路径；按R2修订与新设计相反的顺序断言 |
| 预期结果 | 未修复代码对对应缺陷出现明确失败；登记检查识别遗漏；测试从公开入口触达生产实现 |
| 验证方法 | 对所加方法按完整unittest方法名定向执行；AST比较MODULES与这7个模块；所有预期缺陷失败记录关联F编号，不以语法通过替代 |
| 通过标准 | 每个回归能区分当前错误行为与设计目标；没有全真事实替代、模型更新、真实引擎或未筛选discovery |
| 停止条件 | 测试意外启动训练/CB/native，立即停止该检查并修正测试隔离；遇并行修改冲突不覆盖，不扩大为全项目重构 |

## R1：完整卡文、处理边界和功能身份

对应 F01、F02。前置：R0相关回归已确定；只使用现有完整卡文和共享字典。

目标文件：`effect_records.py`、`effect_blocks.py`、`effect_mechanisms.py`、`construction_relations.py`、`construction_inventory.py`、`construction_layer_flow.py`；关键符号 `_zones`、`record_operations`、`_record_outputs`、`_function_semantics`、成本/条件/选择器投影。测试使用现有 effect 和 construction_text_completion/condition_selection/functional_flow 模块。

具体动作：

1. 区域解析区分“额外卡组”和“卡组”，动作来源与去向分开；解析“3张或6张”为同一处理的合法选择分支，保留里侧/随机/所有者，并将按支付数量决定抽卡数量的关系传入共享处理结构。
2. 完成旧式次数/发动边界、装备/指代对象、结束阶段延迟处理和替代处理的结构化范围；原文已覆盖而未解析的部分保留可定位程序诊断，不再伪装成用户缺资料。
3. 以处理身份关联“当作融合召唤”的类别与实际一次特殊召唤；不增加第二资源产出或第二功能family。免素材的效果召唤不因字面fusion_summon凭空要求融合素材。不同独立处理、目标集合及真实收益仍各自保留。
4. 将所有消费方统一接到修正结构；不要只修展示records而让relation/score继续读旧字段。若语义合同变化，明确版本影响并保存旧结果，禁止旧Evaluation冒充新版本。

验证与通过标准：强欲而金满之壶正确得到Extra来源、里侧除外去向、3/6择一与相应抽卡关系；简易融合一次实体转换、一个召唤功能身份、无虚构素材要求；紧急瞬间移动既有正确来源不回退。至少覆盖词序变化、同义表达和独立两次召唤的反例。原随机送墓仍不能指定命中。默认无人工事实覆盖路径正确，且原评分公式测试不变。

失败停止条件：需要按具体卡名/ID打补丁、引入第二事实库、删掉不认识的原文或将unknown置真时，停止该方案，回到通用处理结构；不得靠放宽断言通过。

## R2：静态用途、限制作用范围与自我联想

对应 F03，依赖R1的处理及限制边界。

目标：`construction_layer_flow.py:_bind_mandatory_impacts`、默认配置context、`construction_inventory.py`限制检查、`construction_relations.py`联动关系；测试 `test_construction_functional_flow`、`test_construction_static_entries`、`test_construction_runtime_processing`。

修改动作：将“实际发生先后”与“静态配置存在可满足的使用安排”分开。印刷明确的发动后限制只约束其作用范围；可选用途不要无条件两两同时采用。必要联合用途使用同一资源/关系表达检查前提和自肃；整回合限制始终覆盖对应回合。对方对象描述应对范围，自身资源来自牌表和可达配置，均不向用户索要当前盘面。

预期：报告F03的两个已知可选用途在无运行时顺序输入下可以得到确定静态结论；真实必需冲突能降低得分或判失败；不能把二者一并放行。

验证：同一卡文分别覆盖“发动后”“发动的回合”“仅此卡/该效果”“对方/自己”、可选与必需联合；检查顺序相容和形成环的情况；沿默认normalize_function_uses及统一评价器执行。通过标准为无虚构实战输入、无不必要unknown、无规则冲突漏判、Side/方向仍正确。若只能靠注入context.before消除unknown，R2不通过。

## R3：关系、分配和评分的真正续算

对应 F04、F05，依赖稳定语义身份。

目标：`construction_relations.py:_expression/_combine/_partial_allocations`及共享分配调用、`construction_layer_flow.py:normalize_function_uses/ConstructionLayerAdapter.evaluate`、`construction_quality.py:evaluate_functional_quality`。测试 `test_construction_relations`、`test_construction_calculation_resume`、`test_construction_functional_quality`。

修改动作：

1. 将当前一次性丢弃的枚举栈/位置接入已有工作状态；稳定排序、已发出集合和下一位置一起保存。相同输入续算必须跳过已处理前缀。
2. 表达式all/any共享子结构并在既有算法内做等价去重；节点或分支预算耗尽标为可继续，不把128变成永久语义上限。实体ID、不同副本、支付与目标关系不变。
3. 评分一致完成枚举、结果累积和失分解释设置独立阶段游标；中断时保留已求部分和正确上下界，不在下片重新从第一个组合开始。
4. 旧待算档若缺必要新游标，只重建受影响计算；完整旧成果继续保留并标版本，不能清空任务、候选、反馈和全部历史。

验证：129供应池需求1的小反例最终覆盖129个唯一方案；多片及中途JSON保存恢复与一次完成得到相同结果；all/any、共享同一张卡冲突、循环支持、不同需求量有正反例；在完成枚举和失分阶段分别停止，恢复后已处理索引严格前进。通过标准还包括“不重复已处理前缀”“不无限增长等价状态”“不把未算当失败”。

停止条件：只有提高常数或无限延长单片才能通过、分数随切片方式变化、恢复后重复资源使用、需要另写求解器时，停止推进R4验收，先闭合本包。

## R4：Gate、时间模式与CB回优化状态

对应 F06、F07；可先用调度桩完成，不运行模型或CB。

目标：`construction_progress.py:_functional_gate/record_reference_attempt`、`construction_fill.py:_construction_cycle/construction_cycle`及控制器调用方。测试 workflow/progress/runtime_processing/basic_cb_scope 中的纯静态调度方法。

修改动作：从同一Evaluation与Gate原因派生互斥状态：完成通过、完成未通过、算法待算、语义未实现、配置错误、用户停止。不要增加另一个评分来源。开发模式的完成未通过在内部片结束后回S2；算法待算续当前阶段；语义缺口准确报程序覆盖。每次实际完成评价只记一次失败，连续两次完成失败才提示。CB要求回S2时优先于静态passed的结束判断，保留已通过的静态证据。

预期及验证：首片完整但低于参考、第二片通过必须执行两片；硬条件失败同样回优化。pending不计完成失败，片边界不增失败次数。CB两次正常失败且片耗尽后仍进入下一S2；只有一次/未知/预算耗尽不触发两次规则。上线deadline只停止新候选并排空当前S3—S5；用户停止则保存退出。开发无隐式总时限/总迭代次数。

通过标准：上述每个分支从公开construction_cycle到实际状态一致，错误不得再伪装static_coverage_unresolved。停止条件：需要改门槛、跳过S5/参考、假定CB已经执行或把片次数当失败次数。

## R5：独立参考评价与阶段续接

对应 F08、F09，依赖R4状态和R3计算游标。

目标：`construction_fill.py`参考与pending_phase分支、`construction_binding.py:CatalogBindingAdapter`、`construction_layer_flow.py`统一适配器、`construction_progress.py`参考合同；测试 binding/progress/functional_flow/calculation_resume。

修改动作：参考硬条件来自固定BuildTask和实际参考资源，候选可选图只作候选诊断。参考仍走同一规范化/评分政策。将候选已评价、已比较、已选择的结果一次提交，接着保存明确reference阶段，不再将已完成候选回填成待评价。完整参考以任务/政策/评价器/资产/参考牌表及相关事实绑定复用；输入变化才失效。连续失败提示使用同一已验证参考。

验证与通过标准：合法参考不含模型自选可选节点仍可评价；用户必需功能缺失仍失败。参考切三片时，候选评价和66对比较仅发生一次，候选Evaluation ID/顺序不变。下一优化批次只改候选，完整固定参考不重算；政策、资产或参考变化会重算。半成品参考不冒充完整缓存。

停止条件：通过剥离用户硬约束使参考通过、参考改用私有分数、缓存跨版本/环境复用、已完成候选身份变化。

## R6：评价数据流、保存与正常停止

对应 F10、F11，依赖R3/R5结构稳定。

目标：`construction_layer_flow.py:ConstructionLayerAdapter.evaluate`、`construction_quality.py:functional_delta`、`construction_fill.py`状态搬运、`scripts/run_construction.py`保存/取消处理；测试 layer_flow/calculation_resume/cli。

修改动作：在外部输入/恢复边界验证Evaluation一次；内部使用不可变已验证对象和小摘要，缓存比较结果及已完成候选阶段。将大体积关系证据与必要调度状态引用清楚，避免每步deepcopy整份；停止检查覆盖比较和保存前后的安全边界。确定单一权威checkpoint与版本提交记录，session可导出但不可成为另一个不一致事实源；处理KeyboardInterrupt/用户取消时只完成当前安全写入，落盘用户停止原因后退出。

验证：用小而有代表性的大证据对象测调用次数/复制字节；12候选参考续片不重做66对比较，不重复整份Evaluation摘要；结果和ID不变。模拟普通写入异常、取消、导出落后一版、遗留tmp，恢复只选择已提交权威版本；原checkpoint和日志不删除。使用文件API的受控替身，不做崩溃/越界故障注入。

通过标准：重复工作可按调用次数证明消除；写入/读取版本一致；用户停止明确且不启动下一片；质量/完整性/版本校验保持。性能比例、最终时限仅在有真实测量后报告，不预填倍数。

停止条件：为提速删除来源校验、覆盖原run-007、依赖两份文件恰好同时成功、改变候选排序或分数而无设计依据。

## R7：本地服务使用同一生命周期

对应 F15。前置R4—R6已形成稳定公开接口。

目标：`construction_service.py:HostConstructionBackend.run`、宿主配置、`construction_controller.py`和现有agent工具注册；测试 `test_construction_service`、`test_agent_tools` 的隔离CPU路径。

动作：宿主明确development/online策略和片参数；受控session ID对应创建/继续/进度/取消，已有session继续原任务而不重建目标。复用construction_cycle与保存逻辑。校验外部请求不能传任意文件、打开训练、native或外部provider；不增加第二条内部循环。

验证：从实际RPC入口提交、读取进度、取消、恢复，原任务/候选保持；在线到期完成当前Gate；重复请求幂等；不同任务/版本/宿主session不能串用。通过标准是公开入口行为与CLI一致且权限边界不扩张。遇接口需UI改造则先限定为后端，不越过用户实施模型决定范围。

## R8：识别异常、监督数据与独立验收

2026-11-11 范围确认。认知模块由用户独立设计和训练，构筑在接入该模块前仍可根据卡文、库存和配套关系做基本判断。R8 沿原定程序和标签合同验收，识别水平留在能力报告中。原 46 例、16/18 个指定组合和两例旅鸟漏检均保留。 [本轮验收记录](../reports/2026-11-11-design-implementation-repair-runtime.md#识别数据和两例旅鸟)

对应 F12、F13。先修F12，数据部分依赖R1/R2及当时并行模块状态核对。

目标：`construction_recognition.py:recognition_evidence_validator`和待算处理；`training/axis_generic/full18_sources.py`及已有证据、生成器和独立诊断；对应 recognition/axis_generic 测试。

动作：修正ContractError导入/作用域与计算待算返回，内部实现错误不能被宽泛捕获成正常回退。对逐卡mechanism、receiver_compatibility补有原文证据的正负坐标；同一单位分别构造真实目标/资源有无、方向、数量、替代处理和自肃差异；未标注仍未知。自然组合生成应从当前事实及关系产生候选，不能拿手写单元证明自主发现能力。

验证：calculation_pending得到定义明确的待算/合同结果而无NameError；真正异常可追踪。标签生成离线检查每个负例证据及每个兼容冲突的具体关系；按卡片/组合/机制拆分，防训练终验泄漏；保留46个已有新材料压力案例来源和已见卡/未见组合范围。不得将单一总F1掩盖负例、兼容性、漏候选等分项。

通过标准：程序与标签合同先通过，能力提升只能由后续获准训练及独立预测验证得出。当前旧权重、M4/M5成果、训练配置/指针不覆盖；未授权训练时到数据与测试层停止，不自行重训。

## R9：通用CB目标表达与提案范围

对应 F14，依赖R1—R4，保持执行授权暂停。

目标：`basic_cb_inference.py:BLOCK_ROUTES/proposals`、`build_semantics.py`、`route_search.py`、已有LinearMainline、`duel_planning.py`。只改与通用目标表达/绑定/计划交接有关部分。

动作：扩展已有积木目标表达，支持link、ritual以及至少一种非召唤功能目标；从固定任务目标和卡库事实生成所需关系，不按卡名枚举路线。保留随机动作和后续依赖随机结果的分别表示；条件/成本/次数/实体资源由共享机制核对。输出仍为路线与适用条件，不变硬编码决斗序列。

验证：纯静态符号/绑定反例覆盖召唤类、非召唤类、随机处理可入主干和依赖特定命中不可作确定主干；真实引擎见证验收单列并继续等待授权。软件通过标准是表达与消费者接通，不宣称已取得引擎路线。缺少执行授权时禁止以“测试”名义跑CB/native。

## R10：后续阶段运行可靠性与监测

对应 F17、F18。此包分为纯软件补足和另行授权的环境实测，不作为R1—R7修复的先决条件。

目标：宿主引擎生命周期、`native.py`调用方、`bot_qualification.py`、`agent_monitor.py:RunReporter.resources`及已有存储统计；不修改原生ABI/回调/响应保护，不重写规则核心。

动作：在宿主进程边界建立可取消、可超时退出和可保留异常记录的引擎运行，C#会话watchdog与原生调用状态分别记录。补CPU/RAM/GPU/显存/I/O和阶段时延采集，绑定硬件、驱动、模型、精度、并发、预算和任务规模。没有设备的字段写未测而非零。

验证：可控阻塞替身证明到期能回收受控执行单元、保留日志且不误杀其他任务；伪采样器仅测试接口，真实指标不能以伪值交付。原生正常回归、GPU吞吐/恢复和PC端到端P95/P99由当时对应授权执行。禁止SIGSEGV/越界复现、未筛选native测试、重启电脑或粗暴终止全部Python进程。

停止条件：实现要求修改受保护ABI、运行无授权引擎/训练、采集器干扰主任务或把无采样记成已达硬件指标。

## R11：统一验收与资料收口

目标：受本轮修复影响的现有测试、`scripts/check_merge_candidate.py`、`docs/current/README.md`、`docs/plans/MASTER-CHECKLIST.md`、构筑验收表及具体开发说明。

动作：逐项勾对F01—F19与各包证据。保留原运行档；新验证使用新目录。更新当前接线、语义版本和恢复兼容范围；历史报告保留当时事实，活动入口只显示最新真实状态。不能把F17/F18尚未实测伪装为本轮修复失败，也不能把其待验写为通过。

静态验收顺序：

1. 本次改动Python AST/导入检查和定向缺陷回归；全部通过后运行受影响安全模块。
2. 默认真实卡文路径验证当前问题牌，禁止quality_evidence全真、人工选牌和降低完整性要求；共享资源/作用范围/评分不变量不变。
3. 切片与JSON恢复等价、参考独立性及缓存、开发失败回S2、上线排空、用户停止、服务生命周期和数据版本失效。
4. 核对安全CI登记、没有skip冒充通过；完整白名单含模型更新或native相关动作时，先遵守当时授权，不能因脚本名“CPU”自动运行全部。未执行的整套CI明确记录。
5. 仅用户另行允许完整构筑后，在同一2207任务与原指定参考上做新运行。必须使全部候选与参考达到真实完整静态评价，S5产生真实结论；未过按设计回优化。保持训练和CB禁令，除非另有明确授权。

最终交付必须列出：实际改动文件、真实入口效果、定向验证及完整CI分别结果、剩余语义/环境事项、旧档兼容与新运行状态。没有真实完整评分前，不把原indices1/9重新命名为静态排名前两名。

失败与回退：局部验证失败只修对应包，不整树回退，不删除原结果；并行修改冲突需保留双方状态再确定合并；若用户停止，结束当前非破坏性原子步骤后保存进度，不再开新阶段。不得提交/推送/合并或清理既有成果，除非后续明确授权覆盖当前暂停边界。

## 已知未决项与启动条件

当前没有需要用户补充卡文、参考、阈值或选择实施模型的待答问题。唯一启动条件是用户以后明确要求开始修复。训练、CB、完整构筑、原生/GPU/PC实测各自继续遵守当时授权；创建接收任务本身不满足这些条件。

正式评测的“接近50%”容差、统计决策及第三期分组等仍按有效设计中对应阶段冻结，不在本次静态修复中擅定，也不作为实现已确认缺陷的借口。
