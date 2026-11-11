# 构筑功能评价：跨区生命周期与离场除外第八批

日期：2026-11-09（Asia/Hong_Kong）。实际源码为 `N:\YGO-Kito\_publish_20261030`；本批核对分支 `codex/optimization-20261031`、HEAD `3f57198`。保留全部既有未提交修改、删除和未跟踪文件，没有提交或推送。

## 本批结果

已有有限返回链现在可把同一物理实体从原可用区域转移到另一可用区域。分配器先选择返回的实际槽位，再把该槽位各阶段的区域视图交给现有 `multifactor.conditions.solve_requirements`；没有增加库存，也没有另建求解器。回到手卡后不能再从旧卡组区域使用同一张卡，返回 A 仍不能释放 B。完整费用、返回事件总量、重叠池、明确顺序和候选内实体范围继续共同检查。

已接入原始记录的 `leave_field_banish`：明确由该效果召唤到场上的实体携带带原文证据的离场去向；后续明确离场时，实际去向改为除外。依赖墓地起点的接续会失败，依赖真实除外起点的接续可成立；独立实体不受这条来源规则影响。实际去向与声明去向、物理槽位、原召唤事实及规则原文进入成功见证或失败证据。影响经现有共同用途和硬条件传入最终 Evaluation，不做全局扣分或固定罚款。

原始记录有时同时把同一句未来离场规则投影为独立 banish 操作。适配层只在本效果召唤及离场规则已明确关联时，将这个重复投影并入生命周期，不再把它算成独立正面功能；原始记录仍完整保留。

原始操作明确的卡组顶部/底部位置现在保留在转移中。单张、单次的明确位置支持对应位置及普通卡组成员资格；底部不能证明顶部。普通返回未说明位置时，精确位置需求仍 unknown。多张一同返回或链上有多次卡组移动时，只闭合成员资格，精确位置继续 unknown，不宣称已实现组内或多次移动的牌序计算。

`NORMALIZATION_VERSION` 升为 `construction-function-normalization-v7`，旧 v6/v5/v4/v3/v2/v1 规范化评价不得复用。缓存与恢复检查继续消费同一常量。默认 `QUALITY_VERSION` 仍为旧 v3，生产政策、指定参考及旧档迁移没有开始。

本批承接[第七批无操作来源报告](2026-11-09-construction-functional-no-operation-impacts-phase7.md)与[正式方案](../plans/2026-11-08-construction-model-formal-optimization-plan.md)第 12 节步骤三、四。没有重新盘点项目、重做旧研究，未追索、检查或运行 Pro 辅助演示代码。

## 授权、执行与真实文件状态

本聊天由用户真实确认新开并继续，沿用已确认的 GPT-6.1-sol、MAX 主进程实施要求；没有启动子代理或 astra。当前没有待答问题。已读取代码执行细则、preserve-intent-and-execute 和 anti-overengineering，修改前依据实际代码交付四步机械执行书，覆盖转移契约、实际槽位状态、功能评价及静态验证/文档。

首组测试发现完整具名特殊召唤尚不被现有库存选择语法接受，因此追加了一个必要范围：在 `construction_inventory.py` 现有完整匹配语法中增加特殊召唤终词，并接入原依赖检查。已在修改前向用户说明原因和范围；没有另写通用中文选择解析器。带未解析排除限定的选择仍不产生确定实体集合。

| 文件 | 本批实际变化 |
| --- | --- |
| `src/ygo_kito/construction_relations.py` | `ResourceTransfer` 增加 `leave_destination/leave_source`；关联本效果召唤的离场规则，保留卡组位置并抑制规则的重复收益投影；新增有限槽位/阶段区域适配，复用原分配器；接通成功与失败的实体、去向及规则来源证据。 |
| `src/ygo_kito/construction_inventory.py` | 原 `_MOVE` 完整匹配语法接受 `特殊召唤` 终词，`InventoryDependencies.specs` 将该动作交给同一完整选择检查；其余未知限定保留。 |
| `src/ygo_kito/construction_layer_flow.py` | 只有可关联本效果召唤的离场规则才视为已映射；其他限制继续 deferred。规范化版本 v6→v7。 |
| `tests/test_construction_relations.py` | 5 个新增业务方法；既有返回边界方法中的跨区和单张底部返回断言更新为当前支持行为。 |
| `tests/test_construction_functional_flow.py` | 2 个新增方法，覆盖原始跨区返回和离场除外到共同用途、硬条件及 Evaluation；版本断言更新。 |
| `docs/development/construction-logic.md`、`docs/plans/MASTER-CHECKLIST.md` | 新增本批构筑说明和报告入口，保留各历史批次及并行识别段落。 |

五个 Python 文件在本批开始前均已是未跟踪文件，不能把其整份源码记为本批新建。本报告为本批新增。并行识别 M4/M5 的既有文件全部保留，没有承接其实施或验证；仍使用现有本地检出，没有新建丢失本地改动的工作树。

未修改质量计分器、原始效果识别模块、`multifactor` 分配器、模型结构、生产权重、暂停文件、课程指针或外部配置。没有依赖安装、训练、CB、原生对局、真实模型推理、CI、提交或推送。

## 数据流与适用边界

`ResourceTransfer.leave_destination/leave_source` 必须同时提供，且只能附在转移到 field 的事实。原始自动映射只接受本条效果明确的 `scope=this_effect_summoned_card`、`condition=summoned_by_this_effect`、`duration=until_leave_field`，并要求同效果有已识别的 special_summon 到 field。其他效果、卡级未关联来源或未知适用条件不被强行映射。

`_record_outputs` 保留真实 operation 下标。只有与已映射规则原文完全对应、从 field 到 banished 且数量未单列的重复规则操作被折入生命周期；没有重写原始记录，也没有创建第二套无操作来源。

`_allocate_transfer_inventory` 在现有返回数量分支内有限选择各次转移的实际物理副本。每个副本的阶段区域视图共享一个物理池，所有需求、费用和重叠预约仍交给原 `solve_requirements`。输出见证恢复为既有的 `(physical:区域:卡号, 副本槽位)` 表示，并增加 `transfer_states`。消费默认去向与有效离场规则共同决定下一次转移的真实起点；离场后旧规则解除，新的召唤规则由新事件独立附着。

所有方、行动控制方、选择集合、原因或区域缺失仍保留 unknown；明确不匹配仍失败。状态/物理选择受现有匹配预算、128 个有限分支、512 条资源视图和原三消费阶段边界约束，超出时 unknown。混合使用缺少实体转移信息的旧式返回与显式状态转移，本批保留 unknown。没有把库存中有卡解释为手卡、场上或墓地访问证明；未发生转移的副本只保留宿主已有的访问事实。

卡组端点只在单张、单次明确移动下确定。多张返回、多个卡组移动、未知顺序不求解完整牌序；普通 deck 视图仍可成立。带离场规则但消费去向不能判断为本批已闭合的离场区域，例如 xyz_material，继续保留未知，不推导通用规则例外。

`leave_field_banish` 的作用体现在实体状态的后续可达性及现有共同用途条件。没有将它写成作用于全部卡或全部墓地用途的 UseImpact。原第七批 `contributes=False` 必需采用、可选零收益不自动采用、来源删除/仅 Side 使常驻要求失败等契约继续保留。其他未映射限制仍 deferred。

## 实际静态验证

解释器为 `C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`，工作目录为实际源码目录。仅在进程内设置 `PYTHONPATH=src`、`PYTHONUTF8=1`，用 `-B -m unittest <完整方法路径> -q` 选择具体方法；没有 discovery 或依赖安装。

14 个不同业务方法取得最终通过结果，其中 7 个新增、7 个直接受影响的既有方法。实际逐组结果如下；重复执行不累计不同方法数：

- 首组 7 项新增：`Ran 7 tests in 0.949s`，退出码 1，5 项通过、2 项失败。现有完整选择语法未接受具名特殊召唤，导致原始转移的选择集合与接续条件仍未知。
- 增加该终词并接回同一依赖检查后，7 项新增：`Ran 7 tests in 0.898s`、`OK`，退出码 0。
- 主体组 14 项：`Ran 14 tests in 1.630s`、`OK`，退出码 0。包括全部 7 个新增方法及 7 个受影响既有方法。
- 补充失败证据后，2 个离场方法及既有返回边界方法：`Ran 3 tests in 0.760s`、`OK`，退出码 0。
- 补齐多张/多次卡组移动的精确位置边界后，位置、既有区域边界、数量/完整费用和离场 Evaluation 4 项：`Ran 4 tests in 1.016s`、`OK`，退出码 0。

不同方法清单：

```text
tests.test_construction_relations.SupportAssessmentTests.test_cross_zone_transfer_tracks_same_slots_and_final_state
tests.test_construction_relations.SupportAssessmentTests.test_cross_zone_transfer_preserves_quantity_fee_and_incremental_updates
tests.test_construction_relations.SupportAssessmentTests.test_deck_position_transfer_keeps_membership_and_unknown_order
tests.test_construction_relations.SupportAssessmentTests.test_summoned_leave_rule_changes_only_selected_entity
tests.test_construction_relations.SupportAssessmentTests.test_raw_summon_transfer_keeps_leave_rule_scoped_to_effect
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_cross_zone_return_reaches_bound_requirement_and_evaluation
tests.test_construction_functional_flow.FunctionalFlowTests.test_leave_banish_lifecycle_reaches_bound_evaluation
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_reuses_only_selected_physical_entities
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_checks_zones_control_and_incomplete_evidence
tests.test_construction_relations.SupportAssessmentTests.test_typed_return_keeps_shared_event_quantity_and_whole_fee
tests.test_construction_functional_flow.FunctionalFlowTests.test_catalog_return_witness_reaches_bound_requirement_and_evaluation
tests.test_construction_functional_flow.FunctionalFlowTests.test_global_return_witness_discharges_bound_required_subgroup
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_non_scoring_adoption_preserves_full_cost_and_unmapped_restrictions
tests.test_construction_inventory.InventoryDependencyTests.test_selector_preserves_level_name_and_type_and_unknown_qualifiers
```

新增方法实际覆盖：同槽位跨区与旧区域失效、输入次序、错误返回实体、双副本与完整费用、返回数量、对象/来源移除后的增量和完整重算一致、卡组成员/端点分离、多张/多次移动位置未知、本效果召唤实体与独立实体的离场区别、未知排除选择、原始来源作用域，以及最终硬条件由 satisfied→failed 且分数上界降低。离场造成的失败同时检查原召唤事实 ID 与规则证据仍可追溯。评价用例使用显式静态访问事实；没有将其称为真实引擎对局能力。

最后代码修改后，五个 Python 文件的 `ast.parse` 与逐行行尾空白检查通过。本报告及两份活动文档新增段落的行尾与相对链接检查通过，14 条方法引用、v7 状态和历史/并行段落保留检查通过；最终八条目标路径状态已核对。未清理历史文档行尾问题。

## 剩余工作与本批停止边界

1. 继续适配其他真实强制影响、持续/固有限制、完整适用条件与更广的控制/选择范围。无操作来源框架及本批生命周期不重建；对未映射范围继续 unknown/deferred。
2. 扩展确有实际需求的复杂返回费用、混合旧式/实体返回、更多阶段及牌组内部顺序；本批三消费阶段、单端点位置范围外不宣称闭合。继续复用现有关系层和分配器。
3. 完成更多自动 Main 调用、主题接收、方向特有用途、互斥换入组合、容量子集选择与共同修复反馈。Side 仍是资源视图，实际修复净分仍完整重算 Evaluation。
4. 适用语义闭合后迁移真实宿主政策及指定 2207/2210 参考、明确无参考的 2610，双方同口径重评；再迁移 schema 2 旧百分制档案，最后退出旧 v3 和层回退。不能仅改常量或用 fixture 政策宣布上线。

本批跨区实体状态、离场除外、有限位置边界、必要静态验证及文档形成可独立接续的安全边界；没有启动下一类强制限制或生产迁移。无外部阻塞及待答问题。按用户长任务规则建议新开聊天继续；未经用户再次真实确认，不创建下一聊天，也不能复用本聊天创建时的确认。

## 独立续接摘要

原始目标：目标模型一次生成轴骨架，优化模型在原目标下多轮补齐；候选选择、保留、反馈、学习、gate、重选和恢复消费同一最终有效分 S。宿主固定政策与参考，候选不能修改。预算/暂停不是失败，恢复不重生成目标骨架、优化图或已有候选。

真实源码：`N:\YGO-Kito\_publish_20261030` 的现有本地检出，分支 `codex/optimization-20261031`、本批核对 HEAD `3f57198`。全部既有未提交修改、删除和未跟踪文件保留；本批涉及的五个 Python 文件原先均已未跟踪。本批新增本报告，并只更新两份活动文档的构筑说明。并行识别 M4/M5 文件已存在，不覆盖、不承接、不运行其验证。不新建遗漏本地改动的工作树，不 reset/clean，不恢复原有删除文件，没有提交推送。

已有可复用实现：前七批已接通显式 v4 候选评价/S 排序、schema 3 pending/恢复、偏好 v2、固定参考/gate、重选和课程记录；all/any 分支、整数库存、完整费用子集、全局有限返回、来源级影响、Side 隔离/R/X、墓地与堆墓双主题、共同用途/原任务绑定、非计分必需采用与损失/修复解释。第七批的无 operations 非风味来源保留费用/对象/次数/条件，`contributes=False`、无主题分；可选零收益来源不会自动采用。己方怪兽区域适用状态须由来源支持；额外召唤限制保留起点、行动控制方及方向边界。

本第八批新增：`ResourceTransfer.leave_destination/leave_source` 带证据关联本效果召唤对象；跨区返回有限选择实际物理槽位，按阶段提供区域视图给原整数分配器。消费实际去向会受该实体已有离场规则影响，旧区域不能继续使用，离场后旧规则解除。成功 `transfer_states` 与失败 `transfer_failures` 保留实际槽位、声明/实际去向、原召唤事实及规则来源；结果经共同用途/硬条件进入 Evaluation。重复的未来 banish 操作投影不会多计正分。库存完整选择语法新增特殊召唤终词，排除/未知限定不放宽。

位置范围：单张、单次明确 deck_top/deck_bottom 支持端点和普通卡组成员资格。普通 deck 返回对精确端点未知；多张返回或多个卡组移动只闭合成员资格，精确位置 unknown。所有方、控制方、完整选择缺口仍 unknown；混合旧式/实体返回及超出现有三消费阶段仍 unknown，不再造求解器。

版本：`NORMALIZATION_VERSION=construction-function-normalization-v7`，旧 v6/v5/v4/v3/v2/v1 缓存不可复用；默认 `QUALITY_VERSION` 仍旧 v3。没有迁移生产政策、真实参考或旧档，没有退出旧层回退。

验证：14 个不同静态业务方法最终通过，7 新增、7 受影响既有；真实逐组结果和全部方法名见上文。主体 14 项通过后，因增加失败解释复核 3 项，因收紧多张/多次位置边界复核 4 项，均通过；不累计重复方法。最后五个 Python 文件语法/行尾通过。首组曾因旧选择语法不接受具名特殊召唤失败 2 项，补齐同一语法终词后通过。未运行 discovery、整套、CI、训练、CB、原生引擎或真实模型推理；没有参数更新、依赖安装或生产检查。

下一步：以上四项剩余工作为准。先定点检查尚未映射的真实强制限制及其完整适用条件，或实际需要的复杂控制/选择与返回；然后补完整调用/主题/方向组合和生产政策、参考、旧档迁移。不重新盘点项目、不重做旧研究，不重建无操作来源或实体分配框架。当前无待答问题和外部阻塞，下一阶段尚未启动。

持续不变量：K 是整数实体，E 是计分投入；普通 Main 用实际 N 的 40E/N，普通 Main/Side 保留原候选实际 N。完整费用不按比例缩减。只有显式共同用途联合检查，独立配置不因共享资源自动扣分；墓地与堆墓主题保留。未知按一致补全，不全部置真。同一已计收益多原因只撤销一次，独立收益损失保留，S 不再次扣损失账本。未定价负担用 unpriced_effect，不新增超 40、空 Extra、伴生、HOPT、LP 或弃牌固定罚款。Side 不支撑 resident/gate，同名折算一次且负增量保留；recoverable 不能替代完整修复 Evaluation 重算。

执行约束：沿用用户已确认的 GPT-6.1-sol、MAX 主进程要求，不用 astra，不启动子代理替代主进程。先读 `C:\Users\27499\.codex\instructions\code-work.md`、preserve-intent-and-execute 和 anti-overengineering，修改前交付具体机械执行项；已授权非 UI 工作可直接推进。只做变化必需的少量具体静态测试，不 discovery、不装依赖、不训练/CB/引擎/模型推理。不改并行识别、生产权重、暂停/课程指针或外部配置，不提交推送。Pro 辅助演示代码不追索、不检查、不运行。继续复用 InventoryDependencies、关系层和 multifactor.conditions.solve_requirements。

用户等待规则：提出新问题后，必须等待真实回答，暂停全部依赖答案的检索、分析、设计、实施及交付。工具 accepted、预选、超时、沉默、没有回答该问题的新消息都不是许可；无明确独立的必要工作时立即交还用户，不以后台或委派推进。

长任务规则：优先在当前聊天持续推进并允许自动压缩。若继续压缩会损害准确性、约束保真、真实文件状态或验证质量，或已形成适合交接的安全阶段边界，先完成当前非破坏性原子步骤，不启动新阶段，主动建议新开并给出可独立执行的完整摘要。未经用户再次真实确认不得创建下一聊天；新聊天首条提示须重申本规则。不声称能看到精确上下文占用百分比。普通回复用简洁自然段，无无必要加粗、星号装饰或密集标题。

建议下一聊天首条提示：

> 继续 YGO-Kito 构筑模型剩余语义适配。先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-zone-lifecycle-phase8.md`，承接正式方案第 12 节，只在理解旧接线确有必要时读取更早报告。实际源码为 `_publish_20261030`，第八批核对分支 `codex/optimization-20261031`、HEAD `3f57198`，保留所有未提交修改、删除、未跟踪文件及并行识别 M4/M5，不新建遗漏改动的工作树。第八批已把有限跨区生命周期、实际槽位和 leave_field_banish 的本效果召唤对象/真实去向接入原关系层、整数分配器、共同用途、硬条件与 Evaluation；重复未来 banish 投影不计独立正分。单张单次卡组端点已保留，多张/多次移动只闭合成员资格、精确位置仍 unknown；混合旧式/实体返回、完整控制/选择缺口及超出三消费阶段仍 unknown。无操作来源、非计分必需采用与可选零收益不自动采用契约保留。NORMALIZATION_VERSION=v7，默认 QUALITY_VERSION 仍旧 v3；14 个不同静态方法最终通过，5 个 Python 文件语法/行尾通过。下一步定点继续其他真实强制限制和完整适用条件、更多控制/选择/复杂返回，再补完整调用/主题/方向组合与生产政策、参考和旧档迁移；不重建来源或分配框架。按已确认的 GPT-6.1-sol、MAX 主进程执行，不用 astra、不启动子代理；先读代码执行细则及两项指定技能，修改前交付具体机械执行项。只做变化必需的少量具体静态测试，不 discovery/装依赖/训练/CB/引擎/模型推理，不改并行识别、生产权重、暂停/课程指针或外部配置，不提交推送，不追索/检查/运行 Pro 辅助演示代码。当前无待答问题；一旦提问必须等待真实回答并暂停全部依赖工作，accepted、预选、超时或沉默不算回答。长任务优先当前聊天继续并允许压缩；出现准确性风险或安全阶段边界时完成当前原子步骤，主动建议新开并给出完整独立摘要，未经用户确认不得自动创建后续聊天；不声称精确上下文占用百分比。
