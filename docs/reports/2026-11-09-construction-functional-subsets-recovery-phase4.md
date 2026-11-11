# 构筑功能评价：供给子集、连续返回与必需来源第四批

日期：2026-11-09（Asia/Hong_Kong）。实际源码：`N:\YGO-Kito\_publish_20261030`；本轮开始核对分支 `codex/optimization-20261031`、HEAD `3f57198`。继承全部未提交修改、删除和未跟踪文件，没有提交或推送。

## 当前结果

本批闭合了第三批留下的部分供给子集问题，并在已有整数分配器上接通多池重叠及三个消费阶段内的连续返回。返回事实、数量、前置费用、独立分支与宿主顺序共同参与检查。增加了原任务必需采用、但不计正分的显式来源，使其强制影响和损失解释不再依赖虚构一份正收益。

这是[正式方案](../plans/2026-11-08-construction-model-formal-optimization-plan.md)第 12 节步骤三、四的继续实施，承接[第三批完整基线](2026-11-09-construction-functional-resources-side-phase3.md)。`NORMALIZATION_VERSION` 现为 `construction-function-normalization-v3`，旧 v2 规范化评价必须失效。默认 `QUALITY_VERSION` 仍为旧 v3；没有迁移生产政策或参考，没有把显式 v4 路径宣布为默认上线。

## 授权与执行书

用户已明确确认新开并继续，指定 GPT-6.1-sol、MAX、主进程实施、少量必要静态检查，不使用 astra，不启动子代理，不运行训练和 CB。当前没有待答问题。已完整读取第三批报告、代码执行细则与 preserve-intent-and-execute、anti-overengineering，承接正式执行书。

修改前交付的执行项及验收是：

1. 在 `construction_relations._group` 中按池保留替代供给，枚举有界的整数数量分支；仅被选中的供给携带前置费用/条件。可行子集通过，全部分支失败才判失败，预算不足为 unknown，输入顺序不改变结论。
2. 在 `ResourcePool`、`_check_usage`、`_allocate_inventory_usage` 中增加多次返回声明并兼容旧契约，使用现有分阶段整数分配器；连续返回检查数量、来源、费用和顺序。不能闭合的范围保持 unknown，不新建求解器。
3. 用新增或确受影响的静态方法检查上述行为，随后做语法/空白检查，更新构筑文档。失败时只修复本批片段，不覆盖其他本地修改。
4. 随后追加交付必需来源执行项：`FunctionalUse.contributes=False` 不计 P/S，但原任务明确必需采用时参与影响与硬条件；损失账本保留具体原因。规范化传递原任务必需绑定并递增版本，验收零正分来源、可选来源和共享未知。

全部由主进程执行。没有修改 `construction_recognition.py`、`construction_inventory.py`、`effect_records.py`、`effect_blocks.py`、`multifactor` 或识别网络，没有借本次授权运行并行识别任务的验证。

## 实际文件与行为

| 文件 | 本批修改 |
| --- | --- |
| `src/ygo_kito/construction_relations.py` | 新增 `PoolRecovery(fact_id, before, after)` 及 `ResourcePool.recoveries`，兼容 `reusable_if/recovery_between`。`_partial_allocations` 有界枚举供给池/数量/替代来源，仍由已有分配器判断实体冲突。`_check_static_usage/_recovery_branch/_check_usage` 分开普通分配与返回分支，`_allocate_inventory_usage` 将返回映射到分阶段占用而非增加库存。返回事实纳入增量依赖；`_combine` 保留返回分支各自费用。 |
| `src/ygo_kito/construction_quality.py` | `FunctionalUse.contributes` 默认 True，可显式 False；非计分用途不能声明主题收益。必需采用的非计分来源参与 adopted/admitted/surviving 状态、来源级影响与硬条件；损失解释使用实际采用来源，S 不再扣账本。 |
| `src/ygo_kito/construction_layer_flow.py` | 规范化版本升为 v3；`_bind_functional_support` 将原任务必需关系对 functional_use_ids 的绑定传给 `required/requirement_origin`，包含方向内对应用途。 |
| `tests/test_construction_relations.py` | 修改原供给冲突用例为真实可行子集验收；增加同池替代/精确数量、多池连续返回/费用、有限返回数量、阶段/事件/增量/顺序边界。 |
| `tests/test_construction_functional_quality.py` | 增加无正分必需来源、可选来源及未知采用条件的计分/影响/账本验收。 |
| `tests/test_construction_functional_flow.py` | 已有共同用途用例增加原任务必需绑定传递检查。 |

这六个 Python 文件早已是未跟踪源码，不能把整个文件算成本批新建，不能用整个 git diff 推断本批差异。活动文档仅增加构筑段，保留并行识别任务段落。

## 供给与返回的精确边界

部分供给不再合并全部供应商来代表一个可行子集。同一输出池只能选一种供给证明；不同数量分配、不同前置费用、已知或未知的供给证明分别保留。实际选择 1+2 不会被迫支付未采用的另一个供应商的费用。每个分支完整占用自己的整数资源，外层 all 继续重新检查，不能混拼不同分支。

供给数量搜索和分支保留均有界，沿用 `RelationBudget.matches`，最多保留 128 个分支；耗尽时增加未知分支。已有确定可行证明仍可支持用途，不能从已检查分支都失败推出未检查分支也失败。

返回是声明池与有来源事实之间的显式绑定，不从“卡存在”或 `reusable_if` 自动推导顺序。一次返回释放被绑定的前次消费中的有限数量；没有通过增加 K 制造新实体。重叠的种族/属性池在同一物理卡副本上分配，回收前后的占用区间交给 `multifactor.conditions.solve_requirements` 检查。费用/HOPT 等占用仍合并在同一实际分支里，使用同一次发动的输出不重复扣次数。

现有分配器有 deck、activation、resolution、post_resolution 四阶段，本适配把 deck 留给存在性条件，支持三个消费阶段，即明确顺序的两次连续返回及相应多池组合。更多消费阶段保持 `recovery_stage_budget` unknown，未扩建另一套时间或实体求解器。

同一个返回事实不能被机械复制为不同阶段的多次返回。事实数量被多池共同引用时仍检查总量；复杂的部分返回分配、同次事件的多边返回和不完整时序可能保留 unknown。返回自身费用若消费所回收的同池/重叠池，尚无独立顺序时保留 `recovery_cost_order` unknown。

宿主的 `JointConstraint.before` 进入返回顺序检查；返回要求与宿主顺序矛盾时为 missing。子组尚未包含回收的具名后续端点，但更大表达式中存在该端点时，保留 unknown，不能提前判所有外层安排失败。该跨层范围尚未自动消去子组未知并产出完整全局顺序。没有指定顺序的消费者导致同时分配失败时，只有连最宽松的剩余库存也不足才判失败；仍可能通过其他时序安排时保留 unknown。

## 必需来源与未完成范围

`contributes=False` 是显式可信用途契约。来源的 self/joint 条件仍须成立，且必须由原任务明确要求采用，才会在没有正分的情况下触发强制影响。可选且没有正收益的来源不会因为牌表中存在就自动发动。它不增加基础分或主题分，受另一强制影响撤销时也会影响它自己的硬条件。损失原因可以定位到此来源。

本批没有完成“所有无操作原始记录自动产生采用用途”；宿主可通过已有、绑定候选的 typed FunctionalUse/UseImpact 事实提供该范围。尚未映射的原始限制继续 deferred。三类自动限制映射、具体墓地调用与双主题、Side 隔离和 R/X 重算保持第三批行为，没有借这次契约扩展宣称完整卡池语义。

下一阶段仍须按依赖继续：

1. 复杂跨层/部分返回和真实转移适配，特别是同一返回事件的有限数量如何分配到多条边，以及返回自身费用的明确顺序；仍用现有关系层和整数分配器。
2. 完整来源/控制方/区域/顺序下的其他强制影响、无操作记录自动来源、更多自动 Main 调用和主题接收链；不改并行识别模块来凑完整性。
3. 方向特有用途、互斥换入组合、容量子集选择与共同修复反馈。Side 资源视图仍不是具体换后牌表；实际修复后的净分继续完整重算 Evaluation。
4. 适用语义闭合后，才迁移真实宿主政策、既定 2207/2210 参考和明确无参考的 2610 模式；再补 schema 2 旧百分制存档迁移，最后退出旧 v3/层回退。不拿测试政策替代生产配置。

## 实际验证

解释器为 `C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`，工作目录为实际源码目录，进程内 `PYTHONPATH=src`、`PYTHONUTF8=1`，使用 `-B`。只调用下列明确静态方法，没有 discovery、模型更新或引擎调用。

第一组最终通过：`Ran 5 tests in 0.269s`，`OK`，退出码 0。

```text
tests.test_construction_relations.SupportAssessmentTests.test_surplus_supplier_conflict_cannot_disprove_feasible_subsets
tests.test_construction_relations.SupportAssessmentTests.test_partial_supply_retains_pool_alternatives_and_exact_quantity_branches
tests.test_construction_relations.SupportAssessmentTests.test_multiple_returns_share_physical_stock_and_check_return_costs
tests.test_construction_relations.SupportAssessmentTests.test_return_quantity_is_not_unlimited_and_optional_return_cost_is_not_forced
tests.test_construction_relations.SupportAssessmentTests.test_sourced_recovery_between_two_consumptions_and_explicit_order
```

第二组 6 项中以下 5 项通过；同组新增必需来源方法最初有测试断言字段错误，修复实现中非计分来源的 surviving 状态并更正断言后，单独通过 `Ran 1 test in 0.007s`、`OK`、退出码 0。六项的最终方法结果均通过；不将首次整组退出码 1 写成整组成功。

```text
tests.test_construction_functional_flow.FunctionalFlowTests.test_explicit_joint_group_withdraws_only_bound_functional_uses
tests.test_construction_relations.SupportAssessmentTests.test_joint_all_rechecks_whole_alternatives_without_mixing_branches
tests.test_construction_relations.SupportAssessmentTests.test_multi_output_effect_shares_one_activation
tests.test_construction_relations.SupportAssessmentTests.test_overlapping_material_pools_use_distinct_integer_entities
tests.test_construction_relations.EditComparisonTests.test_incremental_recovery_invalidation_equals_full
tests.test_construction_functional_quality.FunctionalQualityTests.test_required_non_scoring_source_applies_impacts_and_records_the_real_loss
```

第三组通过：`Ran 4 tests in 0.236s`、`OK`、退出码 0。

```text
tests.test_construction_relations.SupportAssessmentTests.test_return_events_preserve_order_bounds_and_incremental_invalidation
tests.test_construction_functional_quality.FunctionalQualityTests.test_source_scoped_damage_and_loss_ledger_do_not_double_charge
tests.test_construction_functional_quality.FunctionalQualityTests.test_direction_override_recomputes_restoration_and_negative_delta
tests.test_construction_functional_flow.FunctionalFlowTests.test_mandatory_restriction_mapping_obeys_whole_turn_and_known_order
```

收尾加强宿主顺序与跨层端点边界后，仅重跑第三组中的返回事件方法，最后结果 `Ran 1 test in 0.176s`、`OK`、退出码 0；重跑不另累计。本批共 15 个不同用例。六个改动 Python 文件通过 `ast.parse` 及行尾空白检查，收尾发生修改的两个资源文件再次复核。

可重复调用方式：设置上述两个进程变量后，用该解释器执行 `-B -m unittest`，参数为上述对应组的完整方法路径，末尾 `-q`。本轮没有无变化重跑第三批 16 项或第二批 18 项整批；三项历史 torch 依赖验证仍未运行，缺依赖不计通过。没有训练、CB、原生对局、真实模型推理、全库测试或 CI，没有安装依赖。

本报告与两个活动文档的新链接检查通过。整份活动文档的 `git diff --check` 在 MASTER-CHECKLIST 的两条识别段落（当时第 659、669 行）报告行尾空白；本轮未改这两段，也未扩展为并行任务的格式清理。不能把整份文档 diff 检查记为全绿；本批新增构筑段另做行尾检查。

## 独立续接摘要

原始目标：目标模型一次生成轴骨架，优化模型在原目标下多轮补齐，全部静态消费者使用同一最终 S；政策与参考由宿主固定。K 为整数实体、E 为计分投入；普通 Main/Side 使用原候选实际 N，完整费用不得按比例计价。独立配置不因共享资源自动扣分，只有显式共同用途联合检查。墓地相关和堆墓双主题均保留；未知一致补全，同一收益多原因只撤销一次，独立收益损失保留，S 不再次减账本。未定价负担仍为 unpriced_effect，不新加固定罚款。Side 不支撑 resident/gate，负增量保留。

已完成状态：第二批候选链/schema 3 恢复/学习/gate 保持；第三批完整基线见其报告。本批六个 Python 文件和两个活动文档的真实变化、15 个不同用例最终通过及语法检查如上。NORMALIZATION_VERSION 为 v3，默认 QUALITY_VERSION 为旧 v3。实际源码仍在 `_publish_20261030`，开始时分支/HEAD 为上述值；大量本地修改、删除和未跟踪文件都须保留。

未完成步骤以上节四项为准。没有外部阻塞或待答问题；风险集中在保留 unknown/deferred 的语义范围和未运行的真实资产/模型路径。当前停在“第四批补丁、必要静态验证与文档完成”的安全交接边界，没有开始生产政策迁移。

禁止重复事项：不重新全局盘点、不追索/检查/运行 Pro 辅助演示代码；不 reset/clean/覆盖检出，不恢复已有删除文件，不新建遗漏改动的工作树；不覆盖并行识别源码，不运行其验证，不启动子代理、训练、CB、原生对局或真实模型推理；不改生产权重、暂停文件、课程指针或外部配置，不提交推送。不回退规范化版本复用旧缓存，不把测试政策当真实政策，不把未知全部设真，不无变化重跑前几批整套检查。

建议下一聊天首条提示：

> 继续 YGO-Kito 构筑功能评价，先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-subsets-recovery-phase4.md`；需要旧语义细节时再读其第三批链接，承接正式方案第 12 节。实际源码 `_publish_20261030`，开始时分支 `codex/optimization-20261031`、HEAD `3f57198`，保留所有本地修改、删除及未跟踪文件。第四批已接通带前置费用的整数供给子集/同池替代、现有分配器三个消费阶段内的跨池连续返回、数量/费用/事件/宿主顺序检查、零正分必需来源与损失解释、原任务必需绑定。NORMALIZATION_VERSION=v3，默认 QUALITY_VERSION 仍为旧 v3；15 个不同定点用例最终通过，6 个改动 Python 文件语法/空白检查通过。剩余和限制以报告为准，尤其跨层/部分返回、无操作记录自动来源、未映射影响、复杂调用/主题/Side 组合及生产政策/参考/旧档迁移。继续使用 GPT-6.1-sol、MAX，由主进程执行，只做变化所需少量静态验证；不启动子代理，不使用 astra，不运行训练/CB/原生对局/模型推理，不覆盖并行识别工作，不改权重、暂停/课程指针或生产配置，不提交推送。先读取代码执行细则、preserve-intent-and-execute 与 anti-overengineering，修改前交付具体执行项。无待答问题；任何新问题提出后，必须等待真实回答并暂停全部依赖工作，沉默/accepted/预选/超时都不是回答。长任务优先当前聊天继续并允许压缩；若继续压缩危及约束、文件状态或证据保真，或阶段形成适合交接的安全边界，完成当前非破坏性原子步骤后停止新阶段，主动建议新开并提供独立摘要。未经用户明确确认不得创建后续聊天，不声称看到精确上下文占用百分比。

本轮只建议后续接续，没有自动创建另一聊天。
