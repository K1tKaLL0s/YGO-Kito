# 构筑功能评价：实体转移与原始返回适配第六批

日期：2026-11-09（Asia/Hong_Kong）。实际源码为 `N:\YGO-Kito\_publish_20261030`；本批开始核对分支 `codex/optimization-20261031`、HEAD `3f57198`。现有未提交修改、删除和未跟踪文件均保留，没有提交或推送。

## 本批结果与基线

已把原始 recover/move 的有限选择对象接入现有返回分配：返回现在可以限定此前实际消耗的实体，不能以“返回 A”释放 B。同一次返回继续共享总量和完整费用，没有增加库存 K。源码保持使用现有关系闭包和 `multifactor.conditions.solve_requirements`，没有新增求解器。

一个真实记录解析路径的静态场景已闭合：己方墓地具名回收到手卡，连接宿主明确声明的“手卡消费到墓地→回收→再次手卡消费”。返回见证包含原始来源、起止区域、所有方、控制方、有限候选实体与实际分配槽位，并进入绑定用途、原任务硬条件及最终 Evaluation。把此前消费去向改成除外，返回来源仍在牌表中，原共同要求会失败，最终分数上界下降。将实际对象只放在 Side，同样不能支撑常驻要求。

本批承接[第五批完整基线](2026-11-09-construction-functional-global-recovery-phase5.md)和[正式方案](../current/construction-scoring.md)第 12 节步骤三、四。先完整读取第五批报告、代码执行细则、preserve-intent-and-execute 和 anti-overengineering；未重新盘点项目，未追索、检查或运行 Pro 辅助演示代码。第五批已有的全局资源重查、单返回事件、费用顺序和消费者失效继续复用。

`NORMALIZATION_VERSION` 现为 `construction-function-normalization-v5`，旧 v4/v3/v2/v1 规范化评价应失效。现有评价缓存和恢复检查已经读取该常量，本批未另建缓存机制。默认 `QUALITY_VERSION` 仍为旧 v3；真实生产政策、指定参考、旧档迁移和旧层回退退出尚未实施。

## 授权、执行书与实际范围

用户已于本次新开前真实确认继续。当前主进程执行，不使用 astra，不启动子代理，只做本次变化必需的少量静态检查，不运行训练或 CB。没有待答问题，也没有重复询问实施授权。

修改前已交付机械执行书：在 `Need/RelationFact/_record_facts` 增加可选消费去向与来源转移契约；在返回分支和现有整数分配器入口约束实际释放槽位；在候选投影中适配原始记录、传入 Evaluation 并升级规范化版本；增加定点业务用例和语法/行尾检查，更新本报告及两份活动文档。验收围绕实体不能替换、区域和控制范围、未知保留、完整费用、来源/对象删除及功能接线。失败只修本批片段，不覆盖既有工作树。

| 文件 | 本批实际变化 |
| --- | --- |
| `src/ygo_kito/construction_relations.py` | `Need.destination`；可选 `ResourceTransfer` 和 `RelationFact.transfer`；`_operation_transfer/_record_facts` 在有限投影内解析来源选择；`_check_recovery_transfer` 检查区域、所有方、控制方及未知边界；`_allocate_inventory_usage` 使用返回选择别名约束原物理槽位；见证保留转移和实际选择。 |
| `src/ygo_kito/construction_layer_flow.py` | `_functional_relations` 只从本候选资源视图提供实体集合，分开声明己方效果的行动控制方和记录中的对象所有方；保留实际转移数量；规范化版本 v4→v5。 |
| `tests/test_construction_relations.py` | 五个新增业务方法，覆盖实体选择、区域/控制范围、未知、单事件数量与完整费用、增量失效及原始记录适配。 |
| `tests/test_construction_functional_flow.py` | 新增原始回收到硬条件和 Evaluation 的用例，含错误区域、缺失去向与 Side 隔离；第五批既有版本断言更新到 v5。 |
| `docs/development/construction-logic.md`、`docs/plans/MASTER-CHECKLIST.md` | 只增加第六批构筑说明及报告链接，保留历史和并行识别 M4 段落。 |

四个 Python 文件原本均为未跟踪源码，不能把整份文件算作本批新建，也不能以整份 git diff 代替本批差异。未修改 `construction_quality.py`、`construction_inventory.py`、`construction_recognition.py`、原始效果识别模块、`multifactor` 分配器或识别网络。

## 转移契约与准确边界

`ResourceTransfer` 保存 `source/origin/destination/owner/controller/selection/inventory/reason`。`inventory=None` 表示实体选择未解析；空元组表示选择已经解析但当前投影无匹配对象。候选集合按 `(main|extra, card_id)` 指定，副本仍由原整数库存和物理槽位分配，不按有效投入 E 替代。超过 512 个候选实体或选择别名超过现有边界，继续为 unknown。

原始选择复用 `InventoryDependencies` 的选择解析、字段解析和实体匹配。只接受当前匹配器能完整处理的字段及值类型，未映射谓词保持未解析；不会把未知 selector_query 当成“全部卡”。已识别的非随机完整移动表达式可给出确定选择，随机移动保留未知。通用 `_record_facts` 不自行推断行动控制方；功能投影明确是当前候选己方效果的选定用途，因此为该来源声明 `controller=self`，仍独立保留操作的对象 `owner`。操作若明确声明其他控制方，不会被默认值覆盖。双方或其他未完成范围保留 unknown，已知对方所有/控制的转移不补充当前己方返回路径。

前次消费通过 `Need.destination` 声明实体到达的区域。返回起点必须与它相容；返回终点必须支撑具名的下一消费。对于本批能闭合的返回，实体回到此前使用的同一可用区域。返回释放的占用条件使用该事件、池和前次消费对应的选择别名；别名只匹配符合原始选择的实际库存槽位。这样可以在重叠池中证明“此前消耗的是 B，返回也必须能选中 B”，而不是仅核对总数量。

`PoolRecovery` 仍承担具名先后端点和完整费用时序。没有从卡名或在牌表中出现这一事实自动创造这些端点。旧 `transfer=None` 的 typed 返回仍按既有可信来源契约解释；新原始移动记录会携带转移元数据，使用它作为返回时须接受本批检查。消费未声明去向、转移缺区域/控制方/选择/实体映射、双方范围、随机结果、逻辑池无物理映射，均保留 unknown。已知跨可用区域的接续和牌组顶/底位置尚未由当前库存表示完成，保留 `recovery_transfer_cross_zone/recovery_transfer_deck_position` 等未知，不能把表示缺口直接写成失败。

第五批数量、完整费用、单事件和顺序边界保持：同一事实不因多条后续边重复返回或支付费用；前置费用不能借用未来返回；显式顺序环失败；三个消费阶段以外为 unknown；匹配、组合和分支预算未覆盖的范围保留 unknown。更深返回费用、跨区生命周期和任意真实区域移动没有在本批全部完成。

## 实际静态验证

解释器为 `C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`。工作目录为实际源码目录，进程内 `PYTHONPATH=src`、`PYTHONUTF8=1`，以 `-B -m unittest <完整方法路径> -q` 明确选择方法，没有 discovery、依赖安装、参数更新或引擎调用。

共有 10 个不同业务方法取得最终通过结果，其中 6 个为本批新增，4 个为受本批接线影响的既有方法。真实逐组过程如下，重复调用不累计为新增用例：

- 第一组 5 项：`Ran 5 tests in 0.934s`，退出码 1，4 项通过、1 项错误。实体见证测试误读现有分配器的字段，把 `slot=(physical_pool, copy_index)` 当作独立 `pool/slot`；按真实接口修正断言。
- 第二组 4 项：`Ran 4 tests in 0.569s`，退出码 1，3 项通过、1 项错误。端到端用例已通过有效返回、硬条件和分数变化的断言，最后的未知检查误读 `reason`；改为真实字段 `reason_code`。
- 最终主体组 8 项：`Ran 8 tests in 1.031s`、`OK`，退出码 0。包含全部 6 个新增方法、第五批全局硬条件用例及已有具名墓地调用/双主题用例。
- 边界补充后 2 项：`Ran 2 tests in 0.920s`、`OK`，退出码 0。原始记录确实包含 `owner=both`，据此保留双方未知并防止不支持的查询值类型进入整数匹配；同时覆盖牌组位置和逻辑池边界。这两个方法已计在主体组，不重复计数。

10 个不同最终通过方法为：

```text
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_reuses_only_selected_physical_entities
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_checks_zones_control_and_incomplete_evidence
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_keeps_shared_event_quantity_and_whole_fee
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_incremental_entity_and_source_removal_equals_full
tests.test_construction_relations.SupportAssessmentTests.test_raw_transfer_keeps_selector_identity_and_separate_parties
tests.test_construction_functional_flow.FunctionalFlowTests.test_catalog_return_witness_reaches_bound_requirement_and_evaluation
tests.test_construction_relations.SupportAssessmentTests.test_return_cost_order_pays_complete_cost_before_release
tests.test_construction_relations.SupportAssessmentTests.test_return_prerequisite_recovery_rechecks_costs_and_invalidates_consumers
tests.test_construction_functional_flow.FunctionalFlowTests.test_global_return_witness_discharges_bound_required_subgroup
tests.test_construction_functional_flow.FunctionalFlowTests.test_targeted_grave_call_and_both_theme_channels_share_source_support
```

最后一轮修改后，四个 Python 文件 `ast.parse` 和逐行行尾空白检查通过。本报告和两份活动文档新增段落/链接已核对；未重跑或清理整份活动文档的历史行尾问题，第五批记录的并行识别段问题保持原状。没有重跑旧批整套测试或历史缺 torch 依赖的方法；没有训练、CB、原生对局、真实模型推理、CI 或生产权重检查。原始效果记录的只读打印用于准备本批夹具，不计作测试通过。

## 剩余工作与本批接续边界

1. 在当前转移接口内继续适配尚缺的真实来源与移动语义：跨可用区域生命周期、牌组位置、更多控制/选择范围及更深返回费用。仍依托当前关系层和整数分配器，不能为有限阶段限制另建求解器。
2. 补齐无操作原始记录自动来源、其他强制影响、更多自动 Main 调用与主题接收链。第四批非计分必需来源 `contributes=False` 契约继续保留；可选且零正分的来源不因在牌表中就自动采用。未映射限制保持 deferred，不修改并行识别来凑完整性。
3. 方向特有用途、互斥换入组合、容量子集选择与共同修复反馈仍未完成。Side 仍是资源视图，实际修复净分继续完整重算 Evaluation。
4. 适用语义闭合后，迁移真实宿主政策和指定 2207/2210 参考、明确无参考的 2610，双方同口径重评；再做 schema 2 旧百分制档案迁移，最后退出旧 v3 和层回退。不能只改常量或用 fixture 政策宣布上线。

本批已完成上述实体返回接线、必要静态验证和文档，形成适合续接的安全边界；没有开始无操作来源、下一类强制影响或生产迁移。没有外部服务阻塞，没有待答问题。按用户长任务规则，建议新开聊天携带本报告继续；未经用户再次明确确认，不自动创建后续聊天。

## 独立续接摘要

原始目标：目标模型一次生成轴骨架，优化模型在原目标下多轮补齐；候选选择、保留、反馈、学习、gate、重选与恢复都消费同一最终有效分 S。宿主固定政策与参考，候选不能修改。预算与暂停不是失败；恢复不重生成目标骨架、优化图或已有候选。

真实源码与文件状态：源码是 `N:\YGO-Kito\_publish_20261030`，不是外层旧仓库。第六批开始核对分支 `codex/optimization-20261031`、HEAD `3f57198`。全部既有未提交修改、删除和未跟踪文件保留；本批四个 Python 文件原本已未跟踪。本批增加本报告，只追加/前置两份活动文档的第六批构筑说明，没有提交推送。并行聊天推进识别 M4，相关实现、报告及 MASTER-CHECKLIST 段落保留；不要承接其实施或验证，不新建遗漏本地改动的工作树。

可复用实现：第二批已接通逐候选显式 v4 质量评价、S 排序、schema 3 pending/恢复、偏好 v2、固定参考/gate、重选和课程记录；第三批已有 all/any 分支、重叠整数库存、用途到 V2、来源级影响、Side 隔离及 R/X、墓地调用/双主题及损失/修复组；第四批已有完整费用的整数供给子集/同池替代、有限连续返回、非计分必需来源与原任务绑定；第五批完成跨层资源重查、单事件有限返回、多边/多池数量分配、费用先后、直接消费者失效、可闭合嵌套费用全局证明及硬条件接线。

本第六批新增：`Need.destination`、`ResourceTransfer`、`RelationFact.transfer`；有限当前投影内的原始选择解析；返回选择直接限制此前占用的物理槽位；完整转移来源、区域、所有方、行动控制方和实体见证进入 Evaluation。闭合范围是回到原可用区域的实体返回。通用原始读取不假设控制方；功能投影声明己方选定效果的控制方，仍独立读取对象所有方。旧无转移字段的 typed 来源契约兼容，未从卡名推导具名时间端点。跨可用区域、牌组位置、双方/未知选择、无实体映射及不完整消费去向继续 unknown。NORMALIZATION_VERSION 现为 v5，旧 v4/v3/v2/v1 规范化缓存不得复用。默认 QUALITY_VERSION 仍旧 v3，生产配置与参考未迁移。

验证证据：本批 10 个不同业务方法的最终结果通过，其中 6 个新增；逐组真实失败、修正和完整方法名见上文。最后修改后四个 Python 文件语法/行尾检查通过；新增文档段落和链接已核对。只用已知 Python 3.12、进程内 PYTHONPATH/PYTHONUTF8 和 `-B`。旧整套、torch 缺依赖方法、CI、训练、CB、引擎及真实模型推理均未运行。历史 MASTER-CHECKLIST 识别段行尾问题未清理、未重跑整份 diff 检查。

未完成步骤以上四项为准。无外部阻塞和待答授权，主要缺口是尚未适配的真实语义与未迁移的生产政策、参考和旧档。下一批从当前代码的真实依赖继续，不重做旧研究，不把本报告写成全部上线。可从无操作记录自动来源/其他强制影响继续，同时按确切需要适配当前转移接口的剩余范围。

持续不变量：K 为整数实体，E 为计分投入；普通 Main 用实际 N 的 40E/N，普通 Main/Side 保留原候选实际 N。完整费用不按比例缩减。只在显式共同用途联合检查，独立配置不因共享资源自动扣分。墓地相关与堆墓主题奖励都保留；未知一致补全，不全部置真。同一已计收益多原因只撤销一次，独立收益损失保留，S 不再次减损失账本。未定价负担使用 unpriced_effect，不新增超 40、空 Extra、伴生、HOPT、LP 或弃牌固定罚款。Side 不支撑 resident/gate，同名折算一次、负增量保留；recoverable 不能代替实际修复后的 Evaluation 重算。

禁止重复事项：不 reset/clean/覆盖检出，不恢复既有删除文件；不追索、检查或运行 Pro 辅助演示代码；不覆盖并行识别或运行其验证；不启动子代理、astra、训练、CB、原生对局或真实模型推理；不改生产权重、暂停文件、课程指针或外部配置；不安装依赖、不提交推送。继续使用已有 InventoryDependencies、关系层及 solve_requirements，不另建求解器。

用户等待规则：一旦提出新的选择、确认或补充信息问题，暂停全部依赖该答案的检索、分析、设计、实施和交付，等待真实回答。accepted、预选、超时、沉默或未回答该问题的新消息不算许可；没有独立必要工作时立即交还用户，不通过后台或委派推进。普通回复用简洁自然段，无无必要加粗、星号装饰或密集标题。

长任务规则：优先当前聊天继续并允许压缩；若继续压缩可能损害目标、约束、真实文件状态或证据保真，或阶段形成适合交接的安全边界，完成当前非破坏性原子步骤，停止新阶段，主动建议新开并给出完整独立摘要。未经用户再次明确确认不得创建后续聊天，不声称看到准确上下文占用百分比。

建议下一聊天首条提示：

> 继续 YGO-Kito 构筑模型剩余语义适配。先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-physical-transfers-phase6.md`，仅确有必要时读取其中第五批或更早链接，承接正式方案第 12 节。实际源码为 `_publish_20261030`，分支 `codex/optimization-20261031`、第六批开始 HEAD `3f57198`；保留全部未提交修改、删除、未跟踪文件和并行识别 M4。第六批已完成有来源的实体转移契约、原始选择在当前投影中的解析、返回对前次消费实际槽位的约束，以及到用途/硬条件/Evaluation 的接线；跨区、牌组位置及其他未闭合范围仍按报告为 unknown。NORMALIZATION_VERSION=v5，默认 QUALITY_VERSION 仍旧 v3；本批 10 个不同业务方法最终通过，4 个 Python 文件语法/行尾通过。剩余从无操作记录自动来源、其他强制影响和真实转移缺口继续，随后完整调用/主题/方向组合及生产政策、参考、旧档迁移。当前主进程按已确认的 GPT-6.1-sol、MAX 路由实施，不用 astra、不启动子代理，只做变化必需的少量静态测试；不训练/CB/引擎/模型推理、不安装依赖、不改并行识别、生产权重、暂停/课程指针或外部配置，不提交推送，不追索/检查/运行 Pro 辅助演示代码。先读代码执行细则和两项指定技能，修改前依据实际代码交付具体机械执行项。当前无待答问题；提出新问题后必须等待真实回答并暂停全部依赖工作，不能把 accepted、预选、超时或沉默当回答。长任务优先当前聊天继续并允许压缩；压缩风险或适合交接的阶段边界到来时完成原子步骤，主动建议新开并交付完整独立摘要，未经用户确认不得自动创建下一聊天，不声称精确上下文占用百分比。
