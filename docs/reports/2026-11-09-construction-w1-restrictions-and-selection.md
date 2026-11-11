# 构筑 W1 限制适用条件和选择检查

日期：2026-11-09（Asia/Hong_Kong）。源码为 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`、核对 HEAD `3f57198`。用户已授权按固定清单从 W1-1 开始并自主安排后续至完成；沿用 GPT-6.1-sol、MAX 主进程要求，不启动子代理。保留全部既有修改、删除和未跟踪文件；不提交推送。

## W1-1 已完成

已删除“全牌表出现一个未适配限制就把 impacts 设为全局 deferred”的扫描。只对取得收益或原任务要求采用、且实际可能成立的效果处理限制。未采用的可选零正分效果仍保留原始记录、未知条件和诊断，但这些未知不进入最终有效分的相关事实集合；宿主最终补充的条件也参与相关性判断。

未明限制确实附着于相关已采用效果时仍报告缺口。未知主体、例外和额外条件没有被置真。与当前召唤/素材选择有关的本卡限制继续由库存候选及召唤成功事件检查；与其无关的抽卡等效果不再因为卡级素材限制而被全局阻断。

已补送墓、除外、返回、解放、发动、盖放和特殊召唤等明确限制的消费。相同限制可以检查实际处理和整份发动代价，区分作用玩家、行动方、接收方、起点、到达区域、代价/效果原因、生效期间以及已有 before 顺序。使用现有记录和有限完整原文，不改识别。未处理的字段、选择或例外会保留 unknown，不能仅凭 kind 清除。

只增加现有布尔条件的部分求值 `support_state`，用于识别已知不可用和未采用效果；没有新增求解器、评分入口或固定罚款。`NORMALIZATION_VERSION` 为 `construction-function-normalization-v10`，默认质量版本仍旧 v3。

### 文件变化

本轮修改三个原已未跟踪源码 `construction_layer_flow.py`、`construction_quality.py`、`construction_relations.py`，以及三个原已未跟踪测试 `test_construction_functional_flow.py`、`test_construction_functional_quality.py`、`test_construction_relations.py`。它们整份文件不属于本轮新建。

### W1-1 实际静态验证

解释器为 `C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`，工作目录为实际源码，进程内设置 `PYTHONPATH=src`、`PYTHONUTF8=1`，以 `-B -m unittest <具体方法> -q` 运行。没有 discovery、依赖安装、真实模型推理、训练、CB 或原生对局。

27 个不同业务方法取得通过结果，8 个新增、19 个直接受影响回归。实际逐组记录：

- 可选采用/未知消费 5 项：`Ran 5 tests in 2.914s`、`OK`。
- 处理限制/既有顺序 6 项首次：`Ran 6 tests in 0.458s`，退出码 1。5 个方法通过，原始契约方法的三个解放句式子场景没有被现有识别导出。未修改识别；改用当前已导出的完整解放句，因效果解放仍由完整结构记录检查。
- 上述 6 项：`Ran 6 tests in 0.336s`、`OK`。
- 本卡素材限制/已有作用范围回归 9 项：`Ran 9 tests in 0.814s`、`OK`。
- 宿主最终绑定及未采用效果 4 项：`Ran 4 tests in 0.549s`、`OK`。
- 完整字段拒绝未处理条件及原始契约 4 项：`Ran 4 tests in 0.454s`、`OK`。
- 共同回收、实际选择和相关未知回归 3 项：`Ran 3 tests in 0.902s`、`OK`。

重复运行不累计不同方法数。八个新增方法为：

```text
tests.test_construction_functional_quality.FunctionalQualityTests.test_unused_optional_adoption_keeps_unknowns_out_of_effective_score
tests.test_construction_functional_quality.FunctionalQualityTests.test_known_unavailable_source_cannot_make_its_impact_unknown_relevant
tests.test_construction_functional_quality.FunctionalQualityTests.test_unmapped_restriction_scope_uses_final_bound_source_support
tests.test_construction_functional_flow.FunctionalFlowTests.test_optional_raw_unknown_restriction_does_not_defer_unrelated_draw
tests.test_construction_functional_flow.FunctionalFlowTests.test_unknown_intrinsic_material_clause_does_not_block_unrelated_effect
tests.test_construction_functional_flow.FunctionalFlowTests.test_processing_lock_checks_whole_payment_and_effect_reason_separately
tests.test_construction_functional_flow.FunctionalFlowTests.test_activation_and_return_locks_keep_actual_processing_conditions
tests.test_construction_relations.SupportAssessmentTests.test_complete_processing_locks_keep_player_cost_origin_and_destination
```

19 个回归方法为：

```text
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_non_scoring_adoption_binds_impact_and_source_removal
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_non_scoring_adoption_preserves_full_cost_and_unmapped_restrictions
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_normal_and_attack_locks_apply_only_to_matching_actor_and_use
tests.test_construction_functional_flow.FunctionalFlowTests.test_hand_lock_order_preserves_transitive_and_whole_turn_conditions
tests.test_construction_functional_flow.FunctionalFlowTests.test_fusion_only_impact_uses_actual_origin_and_actor
tests.test_construction_functional_flow.FunctionalFlowTests.test_intrinsic_recipient_prohibition_reaches_required_summon_and_trigger
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_draw_lock_reaches_required_adoption_and_evaluation
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_add_hand_lock_reaches_evaluation_and_direction_scope
tests.test_construction_functional_flow.FunctionalFlowTests.test_add_hand_lock_preserves_origin_receiver_and_unknowns
tests.test_construction_functional_flow.FunctionalFlowTests.test_extra_summon_impact_keeps_origin_controller_and_condition_unknowns
tests.test_construction_functional_flow.FunctionalFlowTests.test_non_scoring_extra_lock_keeps_directional_negative_delta
tests.test_construction_functional_quality.FunctionalQualityTests.test_comparison_shares_consistent_unknown_completions
tests.test_construction_functional_quality.FunctionalQualityTests.test_final_score_preference_and_binding
tests.test_construction_functional_quality.FunctionalQualityTests.test_deferred_scope_does_not_claim_exact_score
tests.test_construction_relations.SupportAssessmentTests.test_raw_summon_and_attack_locks_require_complete_player_and_timing
tests.test_construction_relations.SupportAssessmentTests.test_raw_hand_locks_require_complete_sourced_applicability
tests.test_construction_functional_flow.FunctionalFlowTests.test_global_return_witness_discharges_bound_required_subgroup
tests.test_construction_functional_flow.FunctionalFlowTests.test_quality_order_and_labels_use_final_score_without_a_model
tests.test_construction_functional_quality.FunctionalQualityTests.test_correlated_unknown_equal_endpoints_do_not_mean_complete
```

六个修改 Python 文件的语法和行尾空白检查通过。没有扩大为旧整套测试、训练、引擎或并行识别验证。

## 固定清单状态

[验收对齐表](execution/2026-11-09-construction-acceptance-alignment.md)的 A17 已闭合，当前为 21 条已完成、12 条证据待补、5 条含实现缺口。W1-1 已完成；原固定 13 项中剩余 12 项，不增加按卡名或卡组拆分的工作项。

上述为 W1-1 完成时的记录。随后已完成 W1-2，继续原六包清单，没有待答问题，不因局部完成要求另开聊天。

## W1-2 共用选择和额外卡组代价（已完成）

库存与实体转移共用完整选择条件检查，直接消费现有公开卡片谓词，包含嵌套条件、等级、种族、属性和实际卡片种类。未知限定不再被忽略；表侧表示仍需当前状态。对方对象不以己方牌表替代。额外卡组和除外状态起点已接入；完整原文可将旧式粗略 payment 在构筑端修正为实际代价，并保留原记录。

同一支付中的实体继续作整数匹配。素材禁用按融合、同调、超量、连接、仪式的实际种类检查，完整结构化素材可走同一路径，不添加各卡组专用分支。候选入口证明：额外卡组只作代价时没有独立效果分，移除必要代价资源后相应抽卡效果失效。

四个新增方法最终通过：

```text
tests.test_construction_inventory.InventoryDependencyTests.test_extra_cost_uses_actual_section_and_complete_integer_payment
tests.test_construction_inventory.InventoryDependencyTests.test_structured_selectors_external_targets_and_unknown_positions
tests.test_construction_inventory.InventoryDependencyTests.test_material_prohibitions_use_each_actual_summon_type
tests.test_construction_functional_flow.FunctionalFlowTests.test_extra_cost_resource_reaches_final_score_without_extra_function
```

另有六个既有方法通过：素材条件和不确定分支、重叠素材不复用、候选素材禁用、完整代价、指定手卡代价缺件及无关可选处理不阻断抽卡。运行记录为 7 项中的 6 项通过（对象“场上的”写法漏接后修正）、4 项中的 3 项通过（夹具的额外卡类型改为无效果融合怪兽）、最终 `Ran 4 tests in 0.244s, OK`。失败均已修复或纠正夹具，未靠置真未知条件通过。首次临时检查缺少 src 导入路径，之后使用显式路径；没有安装依赖。

W1 两项已完成；S06 已补实现和候选评价证据。后续 W2–W6 记录集中保存在[固定清单实施记录](2026-11-09-construction-fixed-worklist-implementation.md)。用户长任务、真实回答等待和未经确认不创建后续聊天的规则持续有效。
