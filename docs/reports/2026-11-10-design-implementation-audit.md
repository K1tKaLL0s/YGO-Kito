# 设计与当前实现排查报告

日期：2026-11-10。范围：当前完整检出 `N:\YGO-Kito\_publish_20261030`。本轮只排查、整理修复方案和交接，未修复程序，未恢复试运营。

## 结论与证据范围

当前程序已经具有 S0—S6 主框架、统一功能评分、关系分配、课程、模型和本地服务代码，但构筑静态语义与计算续接没有闭合，阶段状态处理、参考评价和检查点存在具体缺陷。不能再以“必要资料未提供”解释本轮静态不完整，也不能用此前若干静态测试通过概括为全项实现完成。

本轮列出 19 项可追踪问题：F01—F16 为当前语义、计算、流程、接线或验证缺口；F17—F18 为后续运行可靠性与监测实现缺口；F19 为活动文档状态失真。后两类不自动提升为本轮启动训练、原生引擎或产品开发的理由。

实际检查包括：

- 对 `src` 162、`scripts` 39、`tests` 163、`training` 13 个 Python 文件进行 AST 解析，共 377 个，语法错误为 0；提取生产模块符号、导入和宽泛异常捕获位置。
- 逐条对照最新用户原话、S0—S6、原始设计及有效修订，沿实际构筑入口检查生产调用链；同时核对决斗观察、模型组、数据隔离、课程、统筹、LoRA、本地服务、引擎边界和部署阶段。
- 执行 7 个有界反例：开发循环、CB 回优化边界、识别异常、静态顺序、参考图绑定、分配枚举上限、同一次召唤重复投影。另检查 CI 登记，并只读投影 12 个真实卡名对应的 14 条本地卡库记录。
- 复用已保存的 run-007 结果和独立识别诊断。未重新执行完整 CI、权重推理、参数更新、训练、CB、原生引擎或完整构筑。

“377 个语法检查通过”是语法覆盖，不是逐行语义正确性证明。下表和问题项明确区分本轮反例、源码检查、历史运行证据及阶段待验；未执行的动态验证没有记为通过。

审查执行书见[本轮执行书](execution/2026-11-10-design-implementation-audit-execution.md)，修复动作与验收见[修复方案](execution/2026-11-10-design-implementation-repair-plan.md)，新任务边界见[交接文件](../handoffs/2026-11-10-design-implementation-repair-handoff.md)。

## 设计基准

优先级为最新用户明确要求 → 后续已确认修订 → 仍有效的原始设计。历史报告和代码注释不能覆盖这些要求。

| 基准 | 本次采用的约束 |
| --- | --- |
| [原始设计与原件位置](../current/README.md) | 三执行模型、统筹、共享数据、合法观察、分阶段开发与训练、LoRA、性能与资源记录；三份活动 DOCX 只读提取，原件未改 |
| [统一规范](../current/architecture.md) | 独立模型职责、持续召回、数据与时期隔离、课程和 BO3、统筹反馈、外部服务边界；GPU/正式训练及 PC 产品按所属阶段验收 |
| [S0—S6](../current/construction-workflow.md)及实际用户原话 | 先无卡 ID 粗逻辑，再狭义筛轴；优化保留目标；所有候选与参考同一评价器；静态完整后才准入，显式授权后才做 CB |
| [11月3日评分原文](../current/construction-scoring.md)、11月4日扣分原件、[正式方案](../current/construction-scoring.md) | 保留 log2、P/V1/V2/S、Main/Extra 参数、实际 Main 张数、主题增益、Side 方向和参考比例；不可改成模型裸分或降低门槛 |
| [验收对齐表](execution/2026-11-09-construction-acceptance-alignment.md)及最新静态澄清 | 构筑评价配置能力与配套，不索要实际手牌、盘面、随机命中、对方当前对象或执行顺序；完整卡文未消费属于实现缺口 |
| 最新时间模式澄清 | 开发/训练没有整个任务的上线时限或迭代上限；内部计算片应自动续接。上线到期停止产生候选，完成当前评价、选择和真实 Gate 后交付 |
| 当前授权 | run-007 已停止；仅排查和交接，不修复，不重启，不丢数据；仅 GPT-6.1 Sol Max，主进程执行，不用子代理 |

狭义主题指用户指定系列或种族作为必需轴，不能解释为纯轴、先固定整副候选池。没有待用户重新提供的评分阈值或同义结构化卡文。

## 全项目设计—实现覆盖

| 设计域 | 当前生产位置 | 本轮判断与边界 |
| --- | --- | --- |
| S0 固定目标、卡池、禁限、张数、版本 | `build_contracts.py`、`build_pipeline.py:BuildAssets`、`autonomous_construction.py` | 已有任务、合法性与资产绑定；run-007 原任务和 40/15/15 牌表保留。未发现需重建任务或缩小全时期卡池的依据 |
| S1 无卡 ID 逻辑、主题与轴骨架 | `construction_logic.py`、`construction_model.py`、`construction_controller.py`、`construction_theme.py` | 当前接口区分逻辑和具体绑定；实际模型能力未由本轮重测。不得从旧流程叙述恢复“先筛卡再造逻辑” |
| S2 优化、持续检索、候选与反馈 | `construction_fill.py`、`construction_candidates.py`、`build_training.py` | 候选及反馈接口已有；开发循环提前停止和 CB 回优化丢失见 F06/F07；自主识别质量见 F13 |
| S3 完整卡文到配置评价 | `effect_records.py`、`effect_blocks.py`、`construction_inventory.py`、`construction_relations.py`、`construction_layer_flow.py` | 当前核心阻塞，见 F01—F05；不能拿真实对局补静态输入 |
| S4 同一 Evaluation 排序、学习 | `construction_quality.py`、`construction_layer_flow.py`、`construction_fill.py` | 统一评分合同已有；同一功能身份、重复比较和语义不完整影响可信排序，见 F02/F10。12 份结果没有可用最终静态分 |
| S5 完整性、硬约束、参考比例、失败提示 | `construction_progress.py`、`construction_fill.py` | Gate 实现和失败计数存在，但失败状态混同，参考受候选图约束且重复计算，见 F06/F08/F09 |
| S6 基础 CB 与决斗计划 | `basic_cb_inference.py`、`basic_cb_scope.py`、`route_search.py`、`duel_planning.py` | 授权/静态前置和计划接口存在；回优化边界与自动路线范围缺口见 F07/F14。本轮没有运行 CB |
| 效果、主题、情境关系共享底座 | `effect_mechanisms.py`、`effect_blocks.py`、`construction_inventory.py`、`multifactor*` | 完整中文卡文确实在本地；解析、语义身份及标签监督存在 F01/F02/F13；不建立第二套评分器或实体求解器 |
| 决斗合法观察与动作 | `contracts.py`、`native.py`、`duel_model.py`、`hierarchical_policy.py` | PlayerEncoder 对 hidden 身份/攻守做拒绝检查；动作与引擎边界已有。未重跑原生验证，不能据此保证所有协议分支无错 |
| 决斗训练、模型组与反馈 | `duel_model.py`、`cpu_training.py`、`course_models.py`、`model_group.py`、`model_build_feedback.py` | 可调用模型与训练接口存在；本轮没有加载权重或训练。识别训练数据的已确认缺口单列 F13，不推断所有模型均缺失 |
| 时期、资料导入与训练/终验隔离 | `training_input.py`、`deck_intake.py`、`data_isolation.py`、`storage.py`、`scenario_course_host.py` | 分区、种子与版本校验存在；同物理资源种子跨 train/validation/final 被拒绝。未重做正式发行资料核验，不把旧日期待核叙述当当前缺资源证据 |
| BO1/BO3、共同场数和三期课程 | `scenario_course.py`、`training_scenarios.py` | 当前已有 BO1→BO3、完整大场计数、历史每组 200 BO3 与区间、2610 实际小局先后手双门槛。旧文档“BO3 未接线”不能直接当当前缺陷，见 F19 |
| 统筹、预测与强制重构 | `coordinator.py`、`coord_contracts.py`、`model_group.py` | 预测不可随意下调、预警不可清除、重构需独立验证等控制存在；具体正式统计参数按有效政策，未重开用户设计问题 |
| LoRA 生命周期 | `lora.py`、`lora_group.py` | 冻结基模、版本、适配器保存加载及回退接口存在；迁移收益和退化比较属于后续实际训练验收，本轮未测 |
| 本地 CLI/RPC 与宿主边界 | `scripts/run_construction.py`、`construction_service.py`、`agent_bridge.py` | CLI 新循环已接；服务入口缺运行模式/续接/取消接线，见 F15；不开放远程任意文件、训练或原生执行权限 |
| 断点、异常、停止与资源记录 | 上述 CLI、`agent_monitor.py`、`native.py` | F10/F11/F17/F18；当前保存成果完好，不能把缺陷报告写成已经丢数据 |
| 外部 bot、DSH、PC 产品与部署 | `windbot_room.py`、`bot_qualification.py`、`external_policy_bridge.py`；相应开发说明 | bot/host/原生边界分开；可选 LLM 不阻塞本地基础链，PC 客户端互操作/UI 属阶段3，手机暂缓。未安装、连接服务、跑客户端或扩大产品任务 |
| 测试与活动文档 | `scripts/check_merge_candidate.py`、`tests`、`docs/current` | 7 个近期关键测试未入白名单，部分测试前提与最新设计冲突，F16；历史完成叙述需校正，F19 |

## 问题清单

优先级 P0 表示直接影响当前构筑正确性或完成；P1 为接线、性能、恢复及验证质量；P2 为后续阶段运行保障和资料维护。优先级不改变暂停修复的授权边界。

### F01 · P0 · 完整卡文投影仍有实质错误和遗漏

位置：`effect_mechanisms.py:_zones`（约27行）、`effect_records.py`、`effect_blocks.py:record_operations`（440行）及 `construction_inventory.py` 的消费接口。

本轮直接从现有只读卡库生成当前记录。强欲而金满之壶“自己的额外卡组3张或6张……里侧除外”被投影为成本 `from_zones=[deck,banished]`、`quantity=3`、`to_zone=null`；额外区、来源/去向和择一数量被误解。流星龙的旧式“1回合1次”/发动边界、武神-目一箇的部分处理、变形斗士·动力装置的装备条件，以及次元吸引者的替代处理仍有结构化缺口。

证据为 `current-card-projections.json` 的原文和当前 records。raw unknown 不一律等于最终评分 unknown：下游有些条件已经消费；本项确认的是错误字段、未消费语义和已保存运行缺口，不把每个原始 unknown 都重复报为独立故障。

当前简易融合来源已正确为 Extra，紧急瞬间移动已有 effect 原因和手牌/卡组选择，不能沿用旧诊断声称这两处仍完全未识别。应修通用语法及共享投影，禁止卡名特判、要求用户手填全真事实或读取 Pro 辅助代码。

### F02 · P0 · 同一次处理被拆成不同功能身份

位置：`effect_blocks.py:record_operations`、`construction_relations.py:_record_outputs`（608行）、`construction_layer_flow.py:_function_semantics`（851行）及1054—1057行。

简易融合的一次“当作融合召唤……特殊召唤”输出 fusion_summon 与 special_summon 两个 operation；后者语义身份不同，前者还带不应凭空要求的 `materials=unknown`。评分 family 直接从这两个语义对象生成，现有 search/reveal/shuffle 合并只覆盖部分处理。

本轮反例确认同一处理产生两个不同语义身份；没有捏造这副牌已获得多少重复分。应以同一处理/实体转换保留召唤分类属性并只计一次功能，避免重复资源产出、功能收益和虚构素材需求。不能把所有特殊召唤合并为一个功能，真实独立操作仍需保留。

### F03 · P0 · 已知发动后限制仍依赖未给出的实际顺序

位置：`construction_layer_flow.py:_bind_mandatory_impacts`（725行起）、默认 context；现有 `test_construction_functional_flow.py` 约1134行。

当完整卡文已明确“发动后不能通常召唤”，默认无 before/after 执行顺序时，相关用途影响生成 unknown。本轮两个完整已知、可选静态用途得到 `complete=false`、分数区间[1,2]、一项未知影响。

这与用户最新“静态不要求实际顺序”冲突。应按静态用途选择、印刷限制作用范围及必要联动关系评价可配置性，允许可满足的静态先后关系；整回合限制、必须联合发生的冲突仍须生效。不能把未知统一置真。相应旧测试期待需要随设计修复。

### F04 · P0 · 内层枚举截断没有可续接状态

位置：`construction_relations.py:_expression`（1016行起）、`_combine`（1732行）、`_partial_allocations`（1779行）及实体分配分支。

外层工作队列已有续接，但内部存在128个分支/表达式节点上限，截断后只返回 exhausted/unresolved，未保存剩余枚举栈。反例提供129个各能供应1单位的独立池，需求1、预算100000，仍只返回128个；再调用得到相同前缀，无下一游标。

因此多等几片不一定会收敛，“预算未覆盖”在此是实现缺口。应在现有共享分配器中保存有限搜索前沿、去重与续算位置，保持具体实体、张数、all/any 和循环约束；提高上限或另写求解器都不能替代修复。

### F05 · P0 · 完成计算与失分计算没有阶段游标

位置：`construction_quality.py:evaluate_functional_quality`（534行起）及约680行完成枚举；`construction_layer_flow.py:ConstructionLayerAdapter.evaluate` 的超时续接。

正常化计算有工作状态，但评分一致完成组合和失分阶段超时后，下次仍从该阶段开头计算。超过完成枚举预算后提供保守界是正确的诚实行为，缺口在于可继续的计算没有连续推进途径，可能反复消耗同一片而不完成。

本项由控制流确认，没有在本轮跑长时间任务测量饥饿次数。修复应保留一致性约束和区间正确性，在现有评分模块内续接完成组合/连通分量与失分计算，并将算法待算与语义未实现分开。

### F06 · P0 · 开发循环把确定失败误当覆盖缺口

位置：`construction_progress.py:_functional_gate`（147—222行）、`construction_fill.py:construction_cycle`（约1152—1168行）。

Gate 以 pending 表示所有未过，包括静态完整但低于参考比例、硬性条件失败。外层内部片结束后遇 pending 且无待算状态即标记 `static_coverage_unresolved` 并退出。

调度反例首片为已完成但参考比例失败，第二片会通过；实际只调用一片。应对同一 Gate/Evaluation 区分确定失败、算法待算、语义缺口和配置错误，确定失败自动回 S2。仅两次完成失败才产生分层提示，不按内部片数重复计失败。

### F07 · P0 · CB 回 S2 请求在内部片边界丢失

位置：`construction_fill.py:_construction_cycle` 约1000—1070行和外层约1152行。

内部先计算静态 passed，CB 两次正常失败后设置 `basic_cb_optimization_requested=true`，但当前片没有余量时仍返回 `construction_passed=true`。外层先看 passed，提前结束，未执行已请求的优化。

本轮使用调度桩复现相同返回状态，未执行 CB。修复应区分静态准入证据和全流程交付状态，回优化请求优先于结束判断；保留 CB 的显式授权和两次“正常完成”的定义。

### F08 · P0 · 指定参考错误依赖当前候选逻辑图

位置：`construction_fill.py` 932—962行，特别是947行；`construction_binding.py:CatalogBindingAdapter.bind`。

参考先通过任务合法性，随后被强制绑定到 `session.logic` 的全部 goal nodes。模型提出、但不是用户必需功能的可选节点也可使参考报 `reference_invalid`。反例中合法参考不含可选“抽卡”图节点，绑定 unmatched。

参考应按固定任务必需目标、自己的牌表、同一政策与统一评价器独立评价；候选图诊断不能变成参考的额外硬条件。真正的用户必需功能和禁限张数必须继续验证。

### F09 · P1 · 参考阶段未独立推进，兼容完整参考未复用

位置：`construction_fill.py` 932—959行。每轮无条件重新进入参考评价，未验证并复用已有完整 reference_evaluation；参考未完时保存 pending_quality 与移除 stage_3 的 pending_phase，使下片再次通过已完成候选的评价/比较/选择。

应将阶段游标停在 reference 本身，固定候选结果、排序、反馈和 Evaluation ID；完整参考按任务、政策、评价器、资源及参考自身绑定复用。改变这些输入应失效；候选可选图版本变化不应独自使固定参考重算。

### F10 · P1 · 大体积评价被反复复制、序列化与比较

位置：`construction_layer_flow.py:ConstructionLayerAdapter.evaluate` 约1381—1449行、`construction_quality.py:functional_delta`（781行）、`construction_fill.py` 的批次状态复制。

12份已缓存评价每份自比较校验两次，再作66对比较、每对校验两份，单次进入这些路径至少156次完整 Evaluation 摘要校验；body 包含大体积关系状态。比较循环没有对应 should_stop 检查，复制/摘要/保存也可能越过名义时间片。

停止记录实际栈位于 `functional_delta / evaluation digest`，候选分配状态曾膨胀到数十 MB。这是具体重复工作证据；没有 profiling，所以不声称其占总耗时多少百分比。

应边界验证一次并内部复用不可变评价与小摘要，按输入变更失效比较缓存，及时检查停止，减少全量深拷贝。完整性校验和来源绑定保留，不能为提速删掉正确性约束。

### F11 · P1 · 双份巨型保存与用户停止记录不完整

位置：`scripts/run_construction.py` 的原子单文件写入与 progress 回调。run-007 kernel 409572012字节、session 408615095字节，合计818187107字节，每次保存都顺序写两份完整状态。

单文件 tmp→replace 不保证 kernel/session 两份共同一致。run-006 实际发生一次替换 PermissionError，异常处理保存了较新的 kernel，而 session 落后一片；此前恢复正确选择了 kernel。当前 run-007 两份已核对一致，没有丢弃成果。

SIGINT 不在普通 Exception 处理内，最终停机原因需要独立停止记录补充，原 checkpoint 仍写 time_slice_exhausted。应确定单一权威状态与提交版本，session 作为可重建导出或显式版本副本；正常用户取消在安全原子边界保存明确停止原因，再退出。

### F12 · P1 · 识别校验器待算分支抛 NameError

位置：`construction_recognition.py:recognition_evidence_validator` 188—197行。195行使用 ContractError，但该作用域未导入；其他函数内部导入不覆盖它。

当规范化返回 calculation_pending 时，本轮实际得到 `NameError: name 'ContractError' is not defined`。外层宽泛捕获可把实现错误变成回退结果。应修正异常契约，并使真正待算状态可诊断、可续接；不能扩大 except 或静默回填成功。该模块不是 run-007 静态缺口的唯一原因。

### F13 · P1 · 识别监督与兼容性标签覆盖偏窄

位置：`training/axis_generic/full18_sources.py` 138—179行。当前效果怪兽机制标签主要提供正例，完整负例集中于 NORMALS；unit 层负功能不等价于逐卡负机制。receiver_compatibility 由 normal_summon 与 normal_budget 两项决定，没有覆盖实际目标、额外资源、替代处理及作用方向。

已有[新材料独立诊断](2026-11-10-axis-generic-new-material-probes.md)与此一致：效果怪兽假功能负例仅1/48正确；8个兼容冲突全漏；自然组合指定18组只形成4组配置。该报告是有意构造的压力集，不能宣称总体准确率就是该样本比例。

应补有证据的逐卡正/负坐标、同一单位的必要资源有/无反例、真实关系生成和分类别验收。missing 仍不等于 negative。先修语义/标签/配置生成，是否训练由用户另行授权；本轮没有训练、重写权重或接管并行工作。

### F14 · P1 · 基础 CB 自动提案范围仍窄

位置：`basic_cb_inference.py:BLOCK_ROUTES` 20—27行及 proposals；`build_semantics.py`、`route_search.py`。

当前自动从额外区推导的目标路线集中于 fusion/synchro/xyz，尚未形成覆盖 link/ritual 及非召唤功能目标的通用提案链。不能把这份模板表等同于“不限动作类别的基础 CB 已完整实现”。每轮候选数量上限本身并非全局路线限制，本项针对表达和生成范围。

应在已有积木、绑定、条件/成本/资源检查及 LinearMainline 中拓展通用目标，保留随机动作与依赖随机结果的区别，沿已有 duel_planning 交付条件化参考，不硬编码具体行动序列。无需为本轮静态排查运行 CB。

### F15 · P1 · 本地服务未接运行模式、续接与取消

位置：`construction_service.py:HostConstructionBackend.run` 96—145行。请求只接 request/task/required_tags 和 base/scopes/feedback；每次新建 session，controller.run 未传入 run_mode、slice、在线期限、续接或停止控制。

CLI 已改用新的持续循环，而本地服务仍缺对应宿主接线。修复 F06 后，服务默认 development 可能持续执行，客户端也无法按已有 session 查询/停止/恢复。

应由宿主显式配置运行模式和生命周期，持有受控 session 标识、保存/进度/取消状态；RPC 不获得任意路径、训练、外部 provider 或原生执行开关。复用同一控制器，不另建服务版构筑循环。

### F16 · P1 · 近期回归未进 CI，测试结论超出覆盖

位置：`scripts/check_merge_candidate.py:MODULES`。现有115个登记模块缺少以下7个已存在测试：workflow、text_completion、static_entries、runtime_processing、condition_selection、calculation_resume、recognition，完整模块名见 probe-results.json。

部分功能测试用 reviewed fixture 将未知条件设为真，适合验证评分合同，却不能证明默认真实卡文路径已完整。静态顺序的旧断言还与最新要求冲突。语法检查不会发现 F12 这种运行期 NameError。

应将安全静态回归显式入白名单，并补默认入口、真实卡文、多片和错误分支验收；保留评分公式单测。禁止未筛选 discovery、故障注入或 `tests.test_native_response_buffer`。本轮没有冒称完整 CI 已通过。

### F17 · P2 · 正在执行的原生调用缺少宿主硬超时

位置：`native.py:NativeNormalEngine.next_decision` 495—504行；`bot_qualification.py` 231行明确声明边界。256次循环上限不能中断其中一次阻塞的同步 lib.process。C# owned-session watchdog 已存在，但不等价于该调用可被中断。

这是对局阶段的可靠性缺口，不是本轮静态运行慢的原因。本轮不复现崩溃/挂死。后续在宿主隔离/生命周期层实现截止与退出，先用可控替身验证，保留 ABI、响应与隐藏信息保护；真实原生回归仍需当时授权。

### F18 · P2 · 资源监测仅有部分进程指标

位置：`agent_monitor.py:RunReporter.resources` 103—112行。当前默认采集 elapsed、process_cpu、POSIX峰值RSS；允许字段包含GPU等，不代表实现了真实采样。

统一设计要求 CPU/RAM/GPU/显存、I/O、加载/端到端时延、吞吐及版本硬件绑定。应补宿主采集与阶段统计，设备不可用时明确未测，不写假零；1–3秒动作和3–30分钟构筑目标仍需实际目标环境验证。GPU实测属于后续阶段，不阻塞本轮方案交付。

### F19 · P2 · 活动文档沿用旧完成或旧缺失状态

当前 README/总清单含多轮历史“全部完成”及运行中状态；统一规范指向的训练准备说明仍有 BO3 未接线叙述，而当前 ScenarioCourse 已有实现。设计原文保留，历史报告也不删除；活动入口须明确最新状态和证据范围。

本轮只给资料入口和总清单添加本报告链接及当前状态，未重写历史成绩。后续每个修复包完成后按真实默认入口证据更新验收表，不能将新增测试数量等同于闭合需求。

## “静态不完整”和低效率的解释

本轮完整卡文、指定参考及任务资产均存在。已经确认的主要原因在程序侧：卡文结构/语义投影不充分，处理身份与作用范围不准，内层预算截断不能持续推进，以及阶段状态错误。它们造成的 unknown/deferred 应报告为具体实现缺口或计算待完成，而非向用户索取同一信息。

效率低由有限搜索分支膨胀、同一工作重复做、过大的状态流转共同造成。参考每片重新进入已完成候选比较，完整 Evaluation 被反复深拷贝和序列化，检查点再双份写出约818MB；名义120秒片并不覆盖所有这些操作。已有队列续算改进并没有解决所有内部枚举与后续计分阶段。

本轮未做长时间 profiling，不给出未经测量的加速倍数或耗时百分比。修复验收应先测可重复的操作次数、字节数、游标前进与分数一致性，再在用户允许后跑一次真实任务测端到端表现；不继续原耗时参考来“等它自然完成”。

## 当前运行与成果状态

run-007 已按用户要求用 SIGINT 停止，进程已退出，退出码1为中断结果；本轮未启动新的构筑进程。

| 项目 | 实际状态 |
| --- | --- |
| 原任务、图、候选 | 全部保留；12份40/15/15牌表，顺序 `[1,9,3,6,10,4,2,5,8,7,11,0]` |
| 候选 Evaluation | 已返回12份；静态 complete=true 为0；最终 score.value 均为空，不存在已完成静态最高分的两副 |
| 参考评价 | 未完成；resident阶段保存1326 states、queue115、read_cursor41；不是零进度，也不是已完成参考 |
| S5 / S6 | S5真实Gate未形成；本轮未运行CB |
| 模型计数 | 原记录 build_goal=5、build_optimizer=0 保留；本轮未更新参数 |
| 原存档 | kernel/session完整可解析且一致，日志、候选和停止记录全部保留，未覆盖或删除 |
| 先前展示的前两副 | 按原未校准模型排序展示 indices1/9及卡名；不应改称静态冠军/亚军。命名成果见原run的top-two-named-inspection.json |

原停止证据：[停止检查记录](../../.cache/construction-condition-selection-20261110/run-007/user-requested-stop-inspection.json)。

## 本轮验证与输出

证据目录：`N:\YGO-Kito\_publish_20261030\.cache\design-implementation-audit-20261110`。

| 文件 | 内容 |
| --- | --- |
| `code-map.json`、`training-code-map.json` | 377个Python文件的语法与符号范围；0语法错误 |
| `baseline-git-status.json` | 审查开始时的完整既有工作树状态；不是干净HEAD的替代品 |
| `probe-results.json` | 5个短反例、CI登记、当前卡文投影摘要、无Torch/训练/CB/native执行边界 |
| `boundary-probes.json` | 129供应池截断与重复前缀、简易融合双重功能身份 |
| `current-card-projections.json` | 14条现有卡库原文与当前生产解析结果 |
| 三份 `.txt` | 活动DOCX原件只读提取稿 |
| `artifact-validation.json` | 最终文档链接/问题编号/工作树状态检查，交付前生成 |

临时检查脚本为同目录 `inspect_inventory.py`、`inspect_probes.py`、`inspect_boundaries.py`。实际使用现有 `Chaos-Ubuntu-26.04` 与 `/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -B`，设置 `PYTHONDONTWRITEBYTECODE=1`，源码指向当前检出。只写本轮缓存证据与Markdown；没有修改长期保留的编程文件。

后续按修复方案逐包授权实施。新任务本轮只接收材料并等待；审查结束不等于修复开始。
