# 构筑功能评价：共同资源、强制影响与 Side 第三批

日期：2026-11-09（Asia/Hong_Kong）。实际源码：`N:\YGO-Kito\_publish_20261030`；分支 `codex/optimization-20261031`，本轮核对 HEAD `3f57198`。继承全部本地修改、删除和未跟踪文件；没有提交或推送。

## 当前结果

本批在已有显式 v4 候选生产链上增加了独立分支资源检查、重叠库存整数分配、明确顺序的单次回收、共同用途到 V2 的绑定、来源级强制影响、逐功能损失解释，以及 Side 方向资源投影和完整 R/X 重算。具体的定向送墓调用和已完整识别的主题接收方开始自动适配。

这批是[正式方案](../current/construction-scoring.md)第 12 节步骤三、四的实质推进，尚未闭合其中所有复杂语义。默认 `QUALITY_VERSION` 仍为旧 v3，真实 2207/2210 参考和 2610 政策未写入。不得把这批检查解释为默认生产切换或全卡池语义完成。

之前的候选接线、schema 3 暂停恢复、学习标签、gate、重选和课程记录状态继续以[第二批报告](2026-11-08-construction-functional-production-wiring-phase2.md)为准。本轮未重复其整批验证。

## 授权与实施范围

用户已明确确认新开并继续，由主进程实施，允许少量必要静态测试，不运行训练和 CB，不启动子代理；当前没有待答问题。已读取代码执行细则、preserve-intent-and-execute 与 anti-overengineering，并在修改前交付本批执行项，承接正式方案第 12 节。

本轮没有修改 `construction_recognition.py`、`effect_records.py`、`effect_blocks.py`、`multifactor` 或识别网络。共享整数分配器由 `multifactor.conditions.solve_requirements` 提供，构筑继续调用现有能力，未另建求解器。没有运行 Pro 辅助代码、训练、CB、原生对局、模型推理、全量测试或 CI；未操作生产权重、暂停文件、课程指针或外部配置。

## 真实文件与接口变化

| 文件 | 本批变化 |
| --- | --- |
| `src/ygo_kito/construction_relations.py` | `_combine` 保留有界的独立分支，外层 all 逐分支检查占用；`_allocate_inventory_usage` 将重叠库存池映射到已有整数分配器。新增 `ResourcePool.recovery_between`、`UseRequirement.functional_use_ids`；`JointConstraint.kind` 支持 `all` 和 `before`，检查顺序环。输出 `joint_groups`、共享 `support_expression` 和可追踪的库存投影。`evaluate_relations` 的方向计数输入不能凭空增加原牌表实体。 |
| `src/ygo_kito/construction_inventory.py` | 对材料要求的可用副本继续检查怪兽类型、不能作融合素材及目标自身排除；完整费用仍用整数副本匹配。 |
| `src/ygo_kito/construction_layer_flow.py` | `NORMALIZATION_VERSION` 升为 `construction-function-normalization-v2`。新增 `_functional_relations`、`_relation_support`、`_bind_functional_support`、`_bind_mandatory_impacts`。按 resident 和 Side 方向分别读取同一候选的资源视图；显式共同用途绑定到对应功能，真实已识别的转移可供应接收效果触发。普通用途与具体 called use 分开，两个主题通道分别保留。 |
| `src/ygo_kito/construction_quality.py` | `UseImpact` 增加 `affected_source_ids`，支持撤销某一副本的用途。方向内同一效果/功能/来源的重新评价覆盖常驻证明，完整重算 X。新增 `loss_records`、修复条件/组、阶段可恢复分以及各方向 R/X/增量；保留原阶段 totals，S 不再减一次损失。 |
| `tests/test_construction_relations.py` | 新增分支隔离、明确回收及顺序用例；将重叠材料池用例更新为整数分配验收。 |
| `tests/test_construction_functional_quality.py` | 新增来源级损害和逐收益损失对账、方向覆盖后的恢复与负增量用例。 |
| `tests/test_construction_functional_flow.py` | 新增定向墓地调用与双主题、显式共同用途、强制限制顺序、Side 隔离和零目标区域容量用例。 |

以上七个 Python 文件在本轮开始前就均为未跟踪源码；不能通过 `git diff --stat` 推算本批新增行数，也不能把整个文件当成本轮新建。两个活动文档仅更新构筑段，保留并行识别任务段落。

## 资源与共同用途的实际边界

`K` 是整数库存；同名折算后的 `E` 没有进入材料、次数和容量。独立配置用途不会被自动并为共同发动，三张 HOPT 配置仍按三张投入计价。多个输出属于同一次发动时继续共用该次发动的占用身份。

all/any 的分支分别保存，不能把不同替代分支的资源混拼。重叠的种族/属性等库存池通过同一物理卡副本分配，已存在另一完整分配时通过；仅一实体不能同时支付两个消费。分支保留上限为 128，并受当前匹配预算约束；预算不足保留 unknown。

`reusable_if` 单独表示存在一个返回事实，仍不能证明顺序。`recovery_between=(first_need, second_need)` 显式绑定一次有来源的返回，要求返回事实已 supported、数量足够，并检查返回的额外资源费用。它不表示无限次补充。多池重叠回收、更多连续返回与尚无具体转移顺序的费用/素材复用仍为 unknown。

当多个部分供给的总量超过一个需求，且完整供给集合冲突时，现有保守路径没有枚举所有带前置费用的供给子集；结果继续为 unknown，不能从“全部供给不能一起用”推出“所有合法子集都不存在”。本批修复了此处错误降为 missing 的分支，未把这个范围冒充完全求解。

只有 `UseRequirement.functional_use_ids` 明确绑定的功能才消费相应 `joint_groups` 的结论。required 用途同时保留原任务硬条件；可选用途未声明共同要求时不因共享资源被统一扣分。`before` 保存有来源的顺序，环为失败；`order_unknown` 是独立未知条件。

关系层的未知前提以 `support_expression` 经过 all/any 传播，接收用途复用同一个上游未知原子。纯解析事实在方向间共享；执行、库存和顺序事实留在自身方向。它没有把所有未知置真，也没有用中点替代未知。未读卡片进入关系未覆盖范围；预算造成的未生成绑定用途不会被当作已知错误绑定。

## 影响、主题与 Side 的实际边界

`UseImpact` 只撤销被绑定用途的指定通道及可选指定来源。触发来源须实际取得收益，或在 `FunctionalUse.required` 中明确要求采用；已在 V1/V2 撤销的收益不会在 S 再扣一次。所有损失仍由有效输入重算，未新增固定 HOPT、空 Extra、超 40 张、伴生卡或 LP 罚款。其他资源负担保留 `unpriced_effect`。

当前自动限制映射覆盖不能通常召唤、额外融合限定、不能宣言攻击所对应的已识别用途。整回合与发动后限制分开，已有明确安全顺序时保留目标收益。控制方、限制条件或顺序缺失时保留 unknown；对方限制不当作己方损害。其他限制（包括尚未映射的去向替换、离场除外、复杂选择器限制等）仍令 impacts 范围 deferred。旧识别记录缺控制方或细分语义时，不改写并行识别模块来凑完整性。

自动转移只使用已识别的自己卡片区域移动和完整选择器。定向送墓可支撑具体接收效果，并在其完整支撑成立时将该功能计为 called；同卡的其他真实功能仍独立计量。随机堆墓保留接收方的不确定性，不自动把特定卡改成 called。没有支撑的闭环仍不能自举。

主题先检验政策语义谓词，再检查当前资源视图中的实际接收方、触发原因及完整输入。可确定的墓地相关和堆墓奖励分别保留；不能由检索另一个主题的卡继承其主题。未完整识别的接收条件仍为 unknown，并未覆盖所有主题和所有 Main 调用方式。

Side 方向使用独立资源视图，保留物理来源 `side:*`，按卡片类型投影到 Main/Extra。检查同名实体上限、区域容量和换入数量；目标区容量为零时排除相应 Side 来源。视图不是已经生成的换后牌表，没有具体换出名单。普通 Main/Side 的密度始终使用原候选实际 N。

每个方向重新评价常驻用途和 Side 用途。恢复与损害都进入 X，R 仍来自未换入的资源视图；同名来源合并后才折算，负增量不截零。默认投影考察方向内全部允许的 Side 配置来源；复杂的方向用途选择、互斥组合及换入容量超限时的子集选择仍需要明确事实或保持 deferred，不自动选一组有利工具宣称完整。

`loss_records` 按阶段、方向、功能和通道汇总受损来源、原因、证据及前后投入，数值不重复计入 S。共同缺件可归到同一修复条件组。`recoverable` 的含义是“在本阶段恢复这些已撤销投入”的条件性可恢复分；没有对任意真实修复编辑重新运行全局评价，不能当作修复后最终净增益承诺。

## 本批验证

解释器：`C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`。工作目录为实际源码目录，进程内 `PYTHONPATH=src`、`PYTHONUTF8=1`，使用 `-B`。

最终集中定点命令如下；只运行列出的静态方法，没有 discovery、模型更新或引擎调用。

```powershell
$env:PYTHONPATH=Join-Path $PWD 'src'
$env:PYTHONUTF8='1'
& 'C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe' -B -m unittest tests.test_construction_relations.SupportAssessmentTests.test_joint_all_rechecks_whole_alternatives_without_mixing_branches tests.test_construction_relations.SupportAssessmentTests.test_sourced_recovery_between_two_consumptions_and_explicit_order tests.test_construction_relations.SupportAssessmentTests.test_overlapping_material_pools_use_distinct_integer_entities tests.test_construction_relations.SupportAssessmentTests.test_multi_output_effect_shares_one_activation tests.test_construction_relations.SupportAssessmentTests.test_all_keeps_missing_input_and_any_keeps_alternatives tests.test_construction_relations.SupportAssessmentTests.test_no_source_cycle_is_a_gap_and_seed_propagates tests.test_construction_relations.SupportAssessmentTests.test_surplus_supplier_conflict_cannot_disprove_feasible_subsets tests.test_construction_functional_quality.FunctionalQualityTests.test_source_scoped_damage_and_loss_ledger_do_not_double_charge tests.test_construction_functional_quality.FunctionalQualityTests.test_direction_override_recomputes_restoration_and_negative_delta tests.test_construction_functional_quality.FunctionalQualityTests.test_correlated_unknown_equal_endpoints_do_not_mean_complete tests.test_construction_functional_flow.FunctionalFlowTests.test_side_projection_restores_inventory_without_supporting_resident tests.test_construction_functional_flow.FunctionalFlowTests.test_unread_semantics_and_side_are_not_complete tests.test_construction_functional_flow.FunctionalFlowTests.test_targeted_grave_call_and_both_theme_channels_share_source_support tests.test_construction_functional_flow.FunctionalFlowTests.test_explicit_joint_group_withdraws_only_bound_functional_uses tests.test_construction_functional_flow.FunctionalFlowTests.test_mandatory_restriction_mapping_obeys_whole_turn_and_known_order -q
```

结果：`Ran 15 tests in 0.516s`，`OK`，退出码 0。随后单独运行 `tests.test_construction_functional_flow.FunctionalFlowTests.test_real_effects_outside_graph_and_candidate_local_sources`：`Ran 1 test in 0.638s`，`OK`，退出码 0。本批共 16 个不同用例，前面的失败与修复重跑不另计数。

收尾时补强“返回事实本身为 unknown 时，共同取用也必须为 unknown，不能误判 missing”，仅重跑本批已有 `test_sourced_recovery_between_two_consumptions_and_explicit_order`：`Ran 1 test in 0.220s`，`OK`，退出码 0；这仍是上述 16 项中的一项。随后两个发生修改的 Python 文件重新通过语法和行尾空白检查。

七个相关 Python 文件通过 `ast.parse` 和行尾空白检查。没有重跑第二批整套 18 项；三个依赖 torch 的历史待验证方法仍未运行，也没有安装依赖。全库测试、CI、真实模型与真实引擎均未运行。

## 下一阶段与独立续接摘要

原始目标仍是完整构筑优化：目标模型一次生成骨架，优化模型在原目标下多轮补齐；全部静态消费者消费同一最终 S。政策和参考属于宿主，候选不能改变它们。墓地相关与堆墓双奖励、K/E 区分、实际 N、完整代价、共享未知和不重复扣损等约束继续有效。

已完成的可复用状态：第二批候选生产接线保持；本批上述资源、影响、Side 和损失接口已实现并有 16 项定点通过证据。`NORMALIZATION_VERSION=v2` 使旧规范化评价失效；不要回退为 v1 来复用旧缓存。源码包含大量前轮未提交修改和删除，外层仓库不是基线。没有 reset/clean/覆盖检出，也没有恢复删除文件或创建新工作树。

未完成步骤按依赖顺序继续：

1. 在已有整数分配器上补齐带前置条件的部分供给子集、多池回收及复杂转移；扩展事实适配时继续不另建求解器、不改识别网络设计。当前明确留 unknown 的情况不能机械置真。
2. 继续映射真实来源/控制方/区域/顺序齐全的强制影响，补无独立正分但原任务明确要求采用的强制来源，以及复杂自动 Main 调用与主题接收链。未映射原始限制仍保留 deferred。
3. 补齐方向特有的用途与互斥换入组合事实、容量子集选择；现有方向资源视图不等于具体合法换备操作。完善修复条件组的跨阶段反馈，实际修复后的分数仍通过完整 Evaluation 重算。
4. 上述适用语义闭合后，再迁移真实宿主政策、既定 2207/2210 参考及明确无参考的 2610 模式，同口径重评；补完整 schema 2 旧百分制存档迁移，最后退出旧 v3/旧层选择回退。不能只改公共版本常量宣布上线。

没有外部服务阻塞或待答授权。风险集中在尚未适配的语义和未经本轮测试的真实资产/模型路径；没有要求启动训练或 CB 来解决它们。本轮停在“第三批补丁及定点验证完成、当前状态文档已更新”的安全交接边界，不开始生产政策迁移。

禁止重复事项：不重新全局盘点、不追索 Pro 辅助演示代码、不重跑未变化旧整批测试、不把未知全部设真、不拿测试政策当生产政策、不覆盖并行识别工作、不提交推送。继续主进程实施；本会话授权不包含子代理、训练、CB、原生对局、权重/暂停/课程指针操作。

建议新聊天首条提示：

> 继续 YGO-Kito 构筑功能评价。先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-resources-side-phase3.md`，必要时才读其引用的 phase2 报告，按正式方案第 12 节继续。实际源码 `_publish_20261030`，分支 `codex/optimization-20261031`，核对 HEAD `3f57198`；保留全部本地修改、删除与未跟踪文件，外层仓库不是基线，不创建丢失改动的工作树。本批已实现独立资源分支、重叠库存整数分配、明确顺序单次回收、共同用途到 V2 绑定、来源级影响、Side 隔离与 R/X 重算、定向墓地调用/双主题和逐收益损失记录；NORMALIZATION_VERSION 已为 v2，默认 QUALITY_VERSION 仍是旧 v3。最终 15 项定点检查加 1 项候选排序隔离检查通过，共 16 个不同用例，7 个 Python 文件语法/行尾检查通过。未完成范围与下一步以报告逐项说明为准，特别是带前置条件的部分供给子集、多池回收、未映射限制、复杂主题/调用/Side 组合，以及真实政策/参考/旧档迁移。先读代码执行细则并承接执行书。用户授权主进程继续及少量必要静态测试，不启动子代理，不运行训练/CB/原生对局，不改权重、暂停或课程指针，不覆盖并行识别源码，不提交推送。不把 unknown 全置真，不重做旧研究或 Pro 辅助验证。当前没有待答问题；任何新问题发出后都必须等待真实回答并暂停全部依赖工作。长任务优先当前聊天继续并允许压缩；若继续压缩危及约束/状态/证据保真，或阶段形成适合交接的安全边界，完成当前非破坏性原子步骤，停止新阶段，主动建议新开并提供独立摘要。未经用户明确确认不得创建新聊天，不声称看到精确上下文占用百分比。

本轮只建议续接，没有自动创建下一聊天。
