# 轴与泛用识别 M7 交付记录

后续完成更新（2026-11-09）：整个模块源码与允许工程交付现已完成，T1–T5 软件、环境 V30 工程隔离及纯 CB hints 握手已有验证。本报告的 192/231 及下方阶段描述保留历史；最新范围、94 个本轮不同方法及158次执行见[软件完成报告](2026-11-09-axis-generic-software-completion.md)。真实训练、资料准备、CB/原生、CI 和实际能力发布继续未执行。

总目标修正（2026-11-09）：本报告仅记录截至 V10 的 M7 各批证据。用户已明确要求自主完成整个模块的源码和允许的工程交付，同时真实确认保留正式训练/真实准备/CB/原生/CI 禁令；后续 T1–T5 所需软件不因真实运行未获准而全部暂停。完整续办状态见[整个模块软件交付接续](2026-11-09-axis-generic-module-software-handoff.md)，本报告不是总任务终点。

最新运行状态（2026-11-09）：Q1 13 项、Q2 30 项、Q3 35 项、Q4 事实/接线 54 项、神经编码/预测/评分 25 项、Q5 30 项及 V10 补充 5 项，共 192 个不同方法已有通过结果，实际执行 231 次。V10/V11/V12/V16/V21 专用工程方法均有通过证据，当前授权内选定工程目标已完成。最新先交付[V10 机械补充](execution/2026-11-09-axis-generic-m7-v10-execution-supplement.md)再新增并运行五个纯资源方法，5/5 首次通过、0 failure/error/skip/禁止动作，无生产或既有测试修改；见[V10 实际报告](2026-11-09-axis-generic-m7-v10.md)。历史依据见[Q1/Q2](2026-11-09-axis-generic-m7-q1q2.md)、[Q3/Q4 事实路径](2026-11-09-axis-generic-m7-q3q4-facts.md)、[Q4 神经](2026-11-09-axis-generic-m7-q4-neural.md)和[Q5](2026-11-09-axis-generic-m7-q5.md)；Q5 首轮 1 failure/4 error、两处修复及六项复验保留。此前工程前向/反向/更新与保存恢复已经执行，本批没有模型、更新或 checkpoint I/O；正式训练、真实资料准备、CB provider/搜索、原生引擎和 CI 未执行，T1–T5 未开始。M7 整体仍保留未执行的 CB 对接范围，下方旧状态属于各历史批次。

四项专用源码补充时的状态（2026-11-09）：后续已按用户明确授权，先交付[四项专用用例机械执行补充](execution/2026-11-09-axis-generic-m7-coverage-execution-supplement.md)，再补齐 V11、V12、V16、V21 共五个专用方法源码。当时四项均为“专用源码已补、运行待验证”，M7 运行验收和 T1–T5 没有启动。本文四行用例索引和末尾后续交付节已更新；下方首批文件数、引用数和“未修改测试”等记录继续描述首批文档工作，不扩展为后续成绩。

首批日期：2026-11-09，香港时间。用户当时授权 M7 状态同步，要求先交付机械执行补充后直接执行，由主进程完成，不启用子代理；当时测试、导入、编译、推理和训练继续禁止。以下首批记录只交付文档，最新运行状态见页首及 A/V 末列。

## 本批范围与实际状态

实际仓库为 `N:\YGO-Kito\_publish_20261030`，复用分支 `codex/optimization-20261031` 的现有检出；本聊天接续确认 HEAD 为 `3f57198e5e366152bbb672be8910e6800f8adbb4`。没有建立新工作树、按 HEAD 重建文件、checkout/reset/clean/stash、恢复既有删除或覆盖未跟踪成果，没有提交、推送、合并或发布。

修改前已交付 [M7 机械执行补充](execution/2026-11-09-axis-generic-m7-execution-supplement.md)。本批修改四份既有文档：主执行书、MASTER、`multifactor-role-analysis.md`、`multifactor-functional-units-and-lora.md`；新增本报告及机械补充。`.cache/axis-generic-m7-20261109-01/manifest.json` 登记六条交付路径，四份既有文档保存并逐字节比较，两个新文档原不存在。没有重建 M0–M6 基线，也没有备份或读取权重、大数据和旧分片。

M0 保存完成，M1–M6 源码已实施、运行待验证；M7 的本批工作是同步说明、定位验收项及登记未执行范围。M7 的测试与集成验收尚未执行，不能把文档交付写成整个 M7 已验收。T1–T5 尚未开始。

源码与用例定位使用 `rg` 和 PowerShell 文本读取，不导入、解释或收集测试。下表说明已有代码和用例的落点；用例存在和方法名称不构成完整覆盖或断言已通过的证据。

## A01–A10 交付与验收对应

源码位置均相对仓库根；`multifactor/` 在本表中指 `src/ygo_kito/multifactor/`。A 项按末列记录当前已测工程子范围及剩余范围，不将部分通过扩大为整体能力验收。

| ID | 交付内容与当前源码位置/关键符号 | 已有用例源码定位 | 实际证据与剩余 |
|---|---|---|---|
| A01 | [contracts.py](../../src/ygo_kito/multifactor/contracts.py) 的 `RoleInput/DeckSpec/UnitSpec/AnalysisContext`，`analysis.migrate_v2_input`：四模式、缺失/空区和显式迁移 | [test_multifactor_analysis.py](../../tests/test_multifactor_analysis.py) 的 `AnalysisInputTests`；[test_multifactor_batch1.py](../../tests/test_multifactor_batch1.py) 的 `V3ContractTests` | Q1 四模式、缺失/空区、序列化/迁移工程用例已通过；真实资料覆盖另属 T1 |
| A02 | `contracts.LabelCell/LabelSet`、[annotations.py](../../src/ygo_kito/multifactor/annotations.py) 的 `AnnotationRecord.training_view`、[training.py](../../src/ygo_kito/multifactor/training.py) 的 `Targets.graph_cells`、`graph_training.compile_records/_reduce` | [test_multifactor_labels.py](../../tests/test_multifactor_labels.py) 的 `LabelCellTests`；`V3ContractTests`；`MaskedLearningTests` | Q1 契约、Q3 部分/冲突及 Q5 逐格损失/零监督/弱证据/双正格梯度均通过，工程头独立计数成立 |
| A03 | [semantics.py](../../src/ygo_kito/multifactor/semantics.py) 的 `build_analysis_graph`、`contracts.AnalysisGraph`、[graph_network.py](../../src/ygo_kito/multifactor/graph_network.py) 的 `encode_graph_batch` | `SharedGraphTests`、`TrainingDelegationTests`、`GraphEncodingTests` | Q1 机制编码、Q4 事实图及 CPU/FP32 v3 张量隔离、排列/混批/分块预测等变和双流隔离已通过；设备扩展仍未验证 |
| A04 | [conditions.py](../../src/ygo_kito/multifactor/conditions.py) 的 `solve_requirements`；[construction_recognition.py](../../src/ygo_kito/construction_recognition.py) 的 `allocate_relation_group` 委托共用整数核心 | [test_multifactor_conditions.py](../../tests/test_multifactor_conditions.py) 的 `RequirementTreeTests`；`AllocationTests/SharedConstructionTests`；[test_multifactor_v10_resources.py](../../tests/test_multifactor_v10_resources.py) 的 `V10ResourceRecoveryTests` | Q2 分支/资源/共用分配器及 V10 回收时序、有限别名库存、未知、预约释放和同名额度五项通过；CB/原生规则另验 |
| A05 | [functional_units.py](../../src/ygo_kito/multifactor/functional_units.py) 的 `minimum_member_branches/assess_unit`；`scoring.prepare_function_candidate`；服务定义/实例分别评价 | [test_multifactor_units.py](../../tests/test_multifactor_units.py) 的 `MultifactorFunctionalUnitTests`；`FunctionalBranchTests`；`ServiceTests` | Q2 成员/费用、Q4 定义/实例和 Q5 缺成员拒绝/包标签不广播均通过；真实资料覆盖另验 |
| A06 | [axis_candidates.py](../../src/ygo_kito/multifactor/axis_candidates.py) 的 `generate_axis_candidates`；[task_queries.py](../../src/ygo_kito/multifactor/task_queries.py) 的 `query_domain`；`metrics.axis_set_metrics` | [test_multifactor_candidates.py](../../tests/test_multifactor_candidates.py) 的 `CandidateGenerationTests`；`FixedMetricTests/GraphEncodingTests`；`InferenceWithoutUpdatesTests` | Q4 候选/预算、Q3 漏检指标及神经完整查询分块、支持集外成员评分已通过；真实召回/泛化仍留对应独立评估 |
| A07 | [network.py](../../src/ygo_kito/multifactor/network.py) 的 `NetworkConfig.v3`；`graph_network.GraphRoleNetwork`；[graph_training.py](../../src/ygo_kito/multifactor/graph_training.py) 的 `train_supervised/train_preference/save/load/capability`；[train_v3.py](../../training/axis_generic/train_v3.py) | [test_multifactor_learning_v3.py](../../tests/test_multifactor_learning_v3.py) 的 `GraphEncodingTests/MaskedLearningTests/RecoveryTests/RunnerTests`；`ServiceTests` | Q4 前向及 Q5 learned 头独立损失/工程计数、临时权重严格恢复/下一步更新/warm_start/游标通过；历史生产权重/设备仍未验证，未发布能力 |
| A08 | [splits.py](../../src/ygo_kito/multifactor/splits.py) 的 `build_leakage_groups/assign_group_splits`；[prepare_v3.py](../../training/axis_generic/prepare_v3.py) 的 `prepare_records/validate_cache/prepare`；[assessment.py](../../training/axis_generic/assessment.py) 的 `assess_records`；[metrics.py](../../src/ygo_kito/multifactor/metrics.py) | [test_multifactor_data_v3.py](../../tests/test_multifactor_data_v3.py) 的 `SourceComponentsTests/LabelPreparationTests/FixedMetricTests` | Q3 工程分组/四协议/语义缓存/指标及跨哈希种子和 SQL 反序通过；真实资料准备与 SQL 迁移未执行 |
| A09 | [analysis.py](../../src/ygo_kito/multifactor/analysis.py) 的 `RoleAnalyzer` 三服务；`contracts.CopyChange/AnalysisRequestContext/DeckAnalysis/UnitAssessment/CopyComparison`；[scoring.py](../../src/ygo_kito/multifactor/scoring.py) 的 `score_graph/score_copy_graphs` | [test_multifactor_service.py](../../tests/test_multifactor_service.py) 的 `ServiceTests`；[test_multifactor_inference_v3.py](../../tests/test_multifactor_inference_v3.py) 的 `InferenceWithoutUpdatesTests` | Q4 事实服务 23 项、两个 trainer 评分方法及实际图/完整副本数值评分已通过；参数/优化器/计数/模式不变，真实校准/学得能力仍未验证 |
| A10 | `construction_recognition.ConstructionRecognitionProvider/assist_fact_view/cb_search_hints`；[construction_fill.py](../../src/ygo_kito/construction_fill.py) 的 `build_axis_skeleton/fill_with_existing/construction_cycle` | [test_construction_recognition.py](../../tests/test_construction_recognition.py) 的 `ConstructionRecognitionTests` | Q4 11 个非 CB 消费者方法及预算/assist 工程接线最终通过；CB 提示方法、真实宿主/模型能力仍未验证 |

M1–M6 的修改前保存和当批文本检查分别见 [M0–M2](2026-11-08-axis-generic-m0-m2.md)、[M3](2026-11-08-axis-generic-m3.md)、[M4](2026-11-09-axis-generic-m4.md)、[M5](2026-11-09-axis-generic-m5.md)、[M6](2026-11-09-axis-generic-m6.md)。这些历史回执继续保留，本批没有重跑，也没有将并行构筑成绩转记为识别成绩。

## V01–V30 用例文本对应与缺口

下表保留源码定位并在末列同步当前实际结果；工程更新/恢复和 V10 对照已有通过证据，CB 及真实能力子范围继续待验证。方法所在文件可由上表同名类定位。V30 的环境适配验收属于后续 T5。

| ID | 已定位的现有用例/范围 | 当前未决 |
|---|---|---|
| V01 | `V3ContractTests.test_empty_missing_and_four_modes_roundtrip` | Q1 四模式序列化、迁移和缺失/空区工程用例已通过 |
| V02 | `LabelCellTests.test_known_and_unknown_roundtrip`；`V3ContractTests.test_targets_keep_cells_and_unknown_masks` | Q1 状态/分类值域、Q3 标签准备及 Q5 实际逐格损失/未知掩码已通过 |
| V03 | `V3ContractTests.test_partial_annotations_and_categorical_domains`；`LabelPreparationTests.test_identical_input_conflict_is_preserved_without_negative_fill` | Q1 部分标签契约和 Q3 冲突/未知不补负工程用例已通过 |
| V04 | `FunctionalBranchTests.test_recursive_alternatives_and_explicit_selection` | Q2 递归最小成员与替代分支用例已通过 |
| V05 | `FunctionalBranchTests.test_two_complete_branches_are_not_merged`；`FunctionalBranchTests.test_alternative_resource_conditions_stay_with_their_members` | Q2 不拼接分支和资源条件绑定用例已通过 |
| V06 | `AllocationTests.test_aggregated_supply_and_backtracking`；`SharedConstructionTests.test_constructed_group_uses_same_allocation_core` | Q2 聚合供给、共享库存及构筑共用分配器工程用例已通过 |
| V07 | `AllocationTests.test_aggregated_supply_and_backtracking` | Q2 any 阻塞后续时的回溯用例已通过 |
| V08 | `AllocationTests.test_at_least_k_and_pool_aliases_share_stock` | Q2 k 子条件联合支付用例已通过 |
| V09 | `AllocationTests.test_not_unknown_and_invalid_shape` | Q2 非法 not 和不完整观察用例已通过 |
| V10 | `AllocationTests.test_occupancy_retention_and_distinctness`；`V10ResourceRecoveryTests` 的五个专用方法 | Q2 原预约/独立实体及 V10 显式回收时点/来源、别名有限库存、unknown、占用/保留释放和同名额度对照均通过；原单独运行证据缺口已闭合 |
| V11 | `FunctionalBranchTests.test_v11_fifteen_extra_cards_are_cost_resources_not_members`；原 Side/空 Extra/定义实例用例保留 | Q2 新增专用方法及 Side/空 Extra 相关用例已通过；工程范围内成员与费用资源隔离成立 |
| V12 | `FunctionalBranchTests.test_v12_removing_extension_keeps_base_function_complete`；原预算未知用例保留 | Q2 新增删除扩展保留基础功能及预算未知用例已通过 |
| V13 | `CandidateGenerationTests.test_independent_card_is_a_unit_and_axes_can_overlap`；`CandidateGenerationTests.test_explicit_cross_supply_can_form_large_parent` | Q4 候选生成的重叠、桥接不自动合轴及有依据父子轴工程用例已通过 |
| V14 | `TrainingDelegationTests.test_training_v3_delegates_and_ignores_labels_routes_and_families`；`GraphEncodingTests.test_labels_and_source_ids_do_not_enter_graph_tensors`；`InferenceWithoutUpdatesTests.test_training_queries_do_not_change_inference_tensors_or_natural_domain` | Q4 图委托/张量隔离和额外查询自然域检查通过；Q5 原混合训练方法实际准入也已通过 |
| V15 | `GraphEncodingTests.test_permutation_equivariance_with_global_edge_addresses`；`GraphEncodingTests.test_other_batch_members_do_not_change_valid_scores`；`SharedGraphTests.test_card_identity_renaming_preserves_numeric_graph_structure` | Q4 图身份结构及 CPU/FP32 v3 重排、混批、节点/边分块实际预测等变已通过；6 个旧网络性质方法同时通过 |
| V16 | `MaskedLearningTests.test_v16_carrier_and_enhancer_are_independent_positive_cells`；原整包不广播和逐头用例保留 | Q5 双正格梯度均为 -0.25、一次工程更新/贡献头计数及整包不广播实际通过 |
| V17 | `SourceComponentsTests.test_transitive_keys_and_namespaces`；`SourceComponentsTests.test_cross_namespace_parent_link_is_explicit` | Q3 传递来源和跨命名空间组件工程隔离已通过 |
| V18 | `SourceComponentsTests.test_receiver_card_and_time_holdouts_are_distinct`；`SourceComponentsTests.test_cross_period_checks_annotation_time_and_missing_dates` | Q3 四类协议及缺元数据/时间边界工程用例已通过；真实数据隔离留 T1 |
| V19 | `LabelPreparationTests.test_input_key_ignores_source_and_labels_but_cache_identity_does_not`；`LabelPreparationTests.test_semantic_cache_ignores_gzip_headers_but_rejects_changed_records` | Q3 语义身份、gzip 头变化及缓存误复用拒绝工程用例已通过 |
| V20 | `FixedMetricTests.test_all_wrong_is_zero_and_all_refused_stays_in_denominator`；`FixedMetricTests.test_fixed_category_matrix_has_unknown_prediction_column` | Q3 零 F1、拒答分母、类别覆盖及固定矩阵工程数值已通过 |
| V21 | `LabelPreparationTests.test_v21_reverse_sql_preserves_records_masks_groups_and_splits`；`LabelPreparationTests.test_v21_hash_seeds_and_reverse_sql_preserve_preparation`；原反序用例保留 | Q3 两个专用方法及原反序方法已通过；四格哈希种子/SQL 工程对照成功，真实 catalog/deck_cache 迁移仍未验证 |
| V22 | `FixedMetricTests.test_missing_natural_axis_cannot_be_rescued_by_gold_injection`；`GraphEncodingTests.test_missing_natural_axis_stays_a_known_miss`；`InferenceWithoutUpdatesTests.test_missing_natural_axis_remains_known_without_an_inference_query` | Q3 指标、Q4 编译/推理域及 Q5 原训练 skip 方法通过；known 漏检不被改负或注入自然域 |
| V23 | `ServiceTests.test_v23_actual_section_denominators_at_all_requested_sizes`；`ServiceTests.test_unknown_and_known_empty_regions_are_distinct` | Q4 事实服务的全部指定 Main/Extra/Side 分母和未知/空区工程用例已通过 |
| V24 | `ServiceTests.test_v24_addition_replacement_and_reduction_are_actual_changes`；`ServiceTests.test_invalid_removal_and_unknown_region_fail_before_provider` | Q4 实际加量/替换/减量、缺替代及 provider 前拒绝工程用例已通过 |
| V25 | `ServiceTests.test_v25_changed_effect_reason_and_count_event_are_reobserved` | Q4 费用/效果和使用/发动次数变化重新观察工程用例已通过 |
| V26 | `ConstructionRecognitionTests.test_v26_observe_preserves_order_scores_learning_feedback_and_gate_inputs`；`ConstructionRecognitionTests.test_observe_latency_does_not_consume_cycle_budget_or_reach_cb`；assist 宿主证据方法 | Q4 off/observe 全结果及 session 等价、延时预算和 assist 宿主事实工程接线通过；没有真实模型能力发布 |
| V27 | `ServiceTests.test_v27_repeated_function_facts_do_not_duplicate_contribution`；`ConstructionRecognitionTests.test_v27_duplicate_candidate_decks_only_observed_once` | Q4 功能事实/候选观察去重通过；实际构筑贡献定价的完整断言仍归构筑任务 |
| V28 | `MaskedLearningTests.test_unknown_conflict_and_not_applicable_never_forward_or_step`；`MaskedLearningTests.test_zero_confidence_never_forwards`；`MaskedLearningTests.test_weak_evidence_scales_numerator_without_canceling` | Q5 零监督/零置信度无前向或更新、未监督头不变、独立 Adam/计数及弱证据缩放均通过 |
| V29 | `RecoveryTests.test_resume_next_update_and_rng_equal_continuous_run`；`RecoveryTests.test_warm_start_copies_only_shared_encoder_and_resets_heads`；`RunnerTests.test_batch_cursor_replays_same_remaining_records_without_final_reads`；`RecoveryTests.test_checkpoint_publish_preserves_a_concurrent_file` | Q5 严格恢复/RNG/下一步更新、warm_start、游标、绑定/Adam 损坏拒绝及 Windows 并发文件不覆盖均通过；历史生产权重未加载 |
| V30 | `MaskedLearningTests.test_deterministic_readiness_and_environment_are_not_neural_counts` 当前关闭保护 | Q5 关闭/确定性头保护工程方法通过；环境价值/LoRA 实际收益及底座不变比较仍留 T5，未开始 |

V11、V12、V16、V21 的四组专用源码缺口由 M7 首批文本核对定位；首批没有修改测试源码。后续已按明确授权补齐上述五个方法，随后 V11/V12 随 Q2、V21 随 Q3、V16 双格梯度随 Q5 取得实际工程通过结果。原“未定位专用断言”和源码补齐时的零运行记录继续保留历史语境，详见最新运行报告。

## 当前开发接口与能力状态

当前说明入口为 [多因子角色分析](../development/multifactor-role-analysis.md)，v2 的 [功能单元与 LoRA](../development/multifactor-functional-units-and-lora.md) 保留历史说明并指回当前入口。旧训练交接和 M0–M6 报告不重写成今日成绩。

输入 `axis-input-v3` 包含 unit_analysis、deck_analysis、candidate_insert、state_evaluation 四模式；服务 DTO 另用 `AnalysisRequestContext`。学习记录的 observations/targets/supervision/provenance 四块分开，未知格不补负，训练虚拟查询默认不进入推理或自然候选评价。自然候选成员支持集不硬限于学习成员全集。

`NetworkConfig.v3()` 明确为 64 维、两轮、双流、路线特征关闭；它不同于仍保留的旧 `NetworkConfig()` 默认。18 个学习任务已接线，新任务没有发布记录。`graph_training.capability` 的更新/来源计数只能给训练状态，不能代替校准和发布。

| 对象/状态 | 当前可交付范围 | 应用边界 |
|---|---|---|
| 无 scorer、unavailable/untrained/engineering_only | 确定性事实、能力缺口和 unknown；工程数值不能作已训练识别 | 不输出可应用的新头结论 |
| trained_uncalibrated/weakly_supervised_uncalibrated | 显式宿主注入后的 raw 诊断；校准层没有拟合则保持空/unknown | 不因更新计数转为 available |
| available | 宿主显式提供 validated、calibrated、producer/version 和证据，且查询/分层校验通过 | assist 才可交给宿主政策；本批没有发布该能力 |
| state_readiness、function_facts、requirements | 默认 deterministic_only，来自逐功能契约/观察事实 | 默认未 validated，不能仅凭确定性状态标志进入 assist；仍需宿主验证依据 |
| environment_value | 固定 disabled，服务会覆盖调用方试图开启的标志 | 无估计器、无环境价值应用 |
| failed | 单头失败、候选溢出或契约不匹配的原因与未知 | 停该头，独立事实/其他可用头保留 |

服务的 `AnalysisRequestContext.mode` 默认 observe，构筑包装入口的 `recognition_mode` 默认 off，两者不能混为同一默认。off 不触及 provider/模型；observe 延后到整个构筑切片决策确定后只追加记录；assist 只把明确可用且有实际数据的能力事实交给版本化 `layer_policy(task, deck, layers, facts)`，宿主继续负责收益、损失和 gate。CB 提示须 provider 显式声明接收，legality/route_success 保持 unknown，真正验证权威不变。

三个服务为 `analyze_deck`、`assess_unit`、`compare_copy_change`。副本操作携带实际区域/数量，前后完整配置分别重观察、构图和求解；缺替代对象或比较能力不充分时整体偏好 unknown。只有显式单次均匀起手抽样声明时复用已有单卡接触率，不将其变成联合功能成功率。

事实 CLI 接受 `axis-service-request-v3` 和显式 `--service`，按源码设计不构造/加载模型；神经评分由宿主显式注入。旧候选评分 CLI 仍接受 `multifactor-candidates-v2`，现在必须给显式 checkpoint。本批没有运行任何 CLI。

## 限定检查与以后验证的分界

本批只做文档和引用的检查；测试收集数 0、测试执行数 0、前向/推理数 0、训练/微型更新数 0、CI 运行数 0，没有 Python/项目/Torch 导入、AST/编译、构建、实际数据准备、checkpoint 加载、CB 或原生引擎运行。

主计划 Q1–Q5 及集成检查均保留为待验证，不在本次执行。下列是未来获准后使用现有用例的选择范围，须按当时文件和授权核对，不能整模块运行而顺带越过前向、更新或数据准备禁令。

| 检查组 | 现有定位与应单列的行为 | 本批结果 |
|---|---|---|
| Q1/Q2 | AnalysisInputTests、LabelCellTests、V3ContractTests、RequirementTreeTests、AllocationTests、FunctionalBranchTests 及选定单元方法；其中涉及 Targets 的方法会导入训练模块 | 未收集、未执行；所有导入仍禁止 |
| Q3 | SourceComponentsTests、LabelPreparationTests、FixedMetricTests 的工程夹具；真实资料迁移、缓存生成和跨哈希种子/SQL 对照分开 | 未执行；真实准备留 T1 |
| Q4 | CandidateGenerationTests、SharedGraphTests、ServiceTests 和 GraphEncodingTests 的对应方法；部分方法会构造 Torch 模型和前向 | 未执行；没有历史权重加载 |
| Q5 | MaskedLearningTests、RecoveryTests、RunnerTests 中更新/保存恢复/游标方法 | 未执行；微型优化器更新也没有获准 |
| 一次相应集成 | `ConstructionRecognitionTests.test_observe_latency_does_not_consume_cycle_budget_or_reach_cb` 定位 fill/cycle 的观察延时隔离；assist 宿主证据另有 `ConstructionRecognitionTests.test_assist_passes_available_facts_to_existing_host_evidence_protocol` | 均未执行；模拟 provider 不能当真实宿主能力 |
| Q6 本批文档部分 | 六份文档的相对链接、路径/符号、A/V 编号、历史段落保留、改动范围和行尾；tracked 文档使用命令级 CRLF 空白规则 | 文本与引用检查通过，Git 空白检查结果写入本批回执；不含源码语法/业务验证 |

限定文本检查实际通过：A01–A10 共 10 项、V01–V30 共 30 项，无缺号或重复；19 个源码文件中的 56 个关键符号、55 处去重的具名用例文本引用、54 个新增/改动区相对链接均可定位，错误数 0。两份开发说明历史正文完整保留，MASTER 原有内容和主计划第 2–8 节未改，六份文档没有新增行尾空白。主计划和两份开发说明原为 LF；MASTER 原有 3 个 CRLF 保留，没有整文件转换行尾。新增文档使用 LF。

最终回读首次发现 MASTER 页首被并行构筑任务新增第十批摘要，旧前缀完全相等检查因此返回 1。与本批保存原文的差异只有该并行插入和 M7 追加，原有内容没有丢失。本批保留该新增摘要，并在内存核对时单独识别这一插入，不删除或回写并行段落；初次结果和最终核对分别记录。第十批摘要指向 `2026-11-09-construction-functional-summon-material-restrictions-phase10.md`，其源码、测试及成绩不由本任务接续或验证。

检查回执为 `.cache/axis-generic-m7-20261109-01/document-review.json`，保存上述结果及本批 tracked 文档的最终命令级 Git 空白检查退出码。`git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check -- <本批文档>` 不修改 Git 配置；Git 对未跟踪文档不作差异检查，因此三份未跟踪交付文档另由文本检查覆盖。检查只针对本批新增或改动范围，不重跑前批文件保护、哈希、语法或业务验证。所有运行验收继续待验证。

## 首批文档交付的历史接续摘要

当前原始目标仍是按主执行书完成轴/泛用识别链路及真实消费者，并保留全部既有改动。M0 保存、M1–M6 源码交付完成，M7 本批补齐当前说明与验收索引；源码、配置、用例、数据、权重、活动指针和暂停状态均未由 M7 改动。并行构筑第九批及后续共享文件修改继续保留，实际最新状态以后读取共享文件确认，不拿本报告覆盖它。

本批交付为主执行书、MASTER、两份开发说明及 M7 补充/报告六份文档；其中四份既有文档在 `.cache/axis-generic-m7-20261109-01/manifest.json` 登记保存，两份新文档原不存在。文本核对实际为 10 个 A 项、30 个 V 项、19 个源码文件的 56 个符号、55 处具名用例引用、54 个相对链接，错误数 0；两份历史正文、MASTER 原有内容、主计划第 2–8 节保留。MASTER 并行新增的构筑第十批页首摘要保留，首次旧前缀检查因此返回 1，后按实际并行插入与 M7 增量分别核对。最终文档空白检查退出码及零运行记录见同目录 `document-review.json`；这些结果只属于文档与引用检查。

未完成：M7 运行验收，A01–A10/V01–V29 的实际语义/数值/恢复/消费者结果，V11/V12/V16/V21 五个新增专用方法的语法及运行结果，真实牌表与卡效覆盖、实际校准器/能力发布和宿主政策兼容。四组专用源码已由后续补齐。M5 条件范围特征改变缓存身份，T1 应在新目录准备匹配数据；旧 core/support 观察和标签覆盖缺口继续 unknown。旧源码/权重绑定不能因文档更新而认定相容，未来获准加载时仍按原绑定检查。

当前测试、导入、编译/AST、构建、推理、训练、实际资料准备、CB、原生引擎和 CI 禁令继续有效。T1–T5 各按后续明确授权推进，训练/课程暂停、自动 LoRA 和发布指针不切换。不提交、推送、合并、发布，不重建前批基线、不恢复既有删除、不重复旧盘点或保护检查。没有待答问题，也不询问是否可以运行测试。

后续仍由 gpt-6.1-sol、MAX 主进程完成，不启用子代理。任何后续代码修改先交付对应机械执行补充；共享文件重新读取最新后增量修改。提出问题后暂停所有依赖回答的工作，实际回答前不能用 accepted、预选、超时或沉默代替许可。

长任务优先在当前聊天继续并允许自动压缩；若继续压缩会损害准确性、约束、文件状态或证据连续性，或达到适合交接的安全边界，先完成当前非破坏性原子步骤，不启动新阶段，主动建议新聊天并交付完整独立摘要。未经用户再次明确确认不得创建；获准创建时下一首条提示继续重申本规则，不声称精确上下文占用百分比。

建议后续聊天首条提示：

> 使用 gpt-6.1-sol、MAX 主进程，在 N:\YGO-Kito\_publish_20261030 承接轴与泛用识别。先读 AGENTS.md、代码执行细则、主执行书及 docs/reports/2026-11-09-axis-generic-m7.md。M0 保存、M1–M6 源码、M7 文档同步及四项专用用例源码已交付，运行验收全部待验证；V11/V12/V16/V21 已补五个专用方法，尚未收集、导入、编译或运行，T1–T5 未开始。保留全部 dirty/untracked/deleted 和并行构筑改动，不启用子代理，不 reset/clean/stash/checkout、不据 HEAD 重建、不提交发布。仅按用户本次明确指定的阶段与授权继续；未指定下一阶段时只接续就绪。未解除的测试（含收集/静态业务用例）、导入、编译/AST、构建、前向/推理、微型更新、训练、实际资料准备、CB、原生引擎和 CI 禁令继续有效；权重、活动/暂停/课程指针和自动 LoRA 保持。代码修改先交付机械执行补充，共享文件读最新后增量修改，不重建前批基线或重复旧检查。一旦提问，暂停全部依赖工作并等待真实回答，不将 accepted、预选、超时或沉默当成许可。长任务优先在当前聊天持续推进并允许压缩；出现准确性/状态/证据风险或适合交接的安全边界时，完成原子步骤后主动建议新聊天并给完整摘要，未经用户再次明确确认不得创建，下一首条提示继续重申本规则。

## 四项专用用例后续交付（2026-11-09）

用户明确要求继续补齐 V11、V12、V16、V21，先交付[本批机械执行补充](execution/2026-11-09-axis-generic-m7-coverage-execution-supplement.md)后直接实施。全部由主进程完成，无子代理。本批增加三份测试文件中的五个方法和一个局部 SQL/准备快照函数，同步本报告、主计划当前状态和 MASTER 追加条目；未修改任何生产源码、配置、真实标签/数据、旧 runs、权重或运行指针。

| 项目 | 本批新增源码与明确断言 | 实际运行状态 |
|---|---|---|
| V11 | [test_multifactor_batch1.py](../../tests/test_multifactor_batch1.py) 的 `test_v11_fifteen_extra_cards_are_cost_resources_not_members`：15 张 Extra 各有唯一槽位并只支付声明的费用；最小成员只有 A，14/0/Side 不能支付，无 Extra 依赖的功能仍完整；readiness 保持 unknown | 未收集、未执行 |
| V12 | 同文件 `test_v12_removing_extension_keeps_base_function_complete`：完整基础/扩展都成立；移除 C 和扩展费用后扩展缺件，删除扩展目标后的 A+B 基础仍完整，原成员、角色和功能范围保留 | 未收集、未执行 |
| V16 | [test_multifactor_learning_v3.py](../../tests/test_multifactor_learning_v3.py) 的 `test_v16_carrier_and_enhancer_are_independent_positive_cells`：一个 LabelSet 两个正格及来源均准入；零初始化贡献层下两个 BCE 梯度均为负，每个坐标可同时趋向正例，贡献头计数只增一次 | 未导入、未前向、未更新 |
| V21 SQL | [test_multifactor_data_v3.py](../../tests/test_multifactor_data_v3.py) 的 `test_v21_reverse_sql_preserves_records_masks_groups_and_splits`：内存 SQLite 工程源记录表确实升/降序读取；传递来源、标签冲突/缺失状态和三个非空划分下，完整输出及 known 掩码、来源组/划分相同 | SQL 和工程准备均未执行 |
| V21 哈希 | 同文件 `test_v21_hash_seeds_and_reverse_sql_preserve_preparation`：`PYTHONHASHSEED=1/97` × `ASC/DESC` 四格独立解释器；比较完整规范 JSON 快照，控制读取顺序及实际哈希探针，超时/非零退出直接失败 | 子进程启动数 0 |

V21 只把报告中依赖输入位置的 grouping 行索引转换为来源 ID 到组的映射；完整准备记录不在测试端重排或删字段。它是工程源记录读取对照，没有验证实际 catalog/deck_cache SQL 迁移或真实资料覆盖。V16 的一次微型更新只存在于未来用例源码，工程梯度断言不是能力发布。

本批保存清单为 `.cache/axis-generic-m7-coverage-20261109-01/manifest.json`：只保存六份本批拟改文件的当前字节，不重建前批全树基线，不保存权重、不计算哈希；七条交付路径包含新增机械补充。三份测试的原文已用剔除本批新增块后的文本比较确认保留，旧方法和夹具没有改写。最终限定文本检查回执写入同目录 `text-review.json`，记录五个方法/链接定位、原内容保留、主计划第 2–8 节、MASTER 旧内容和本批新增行尾检查；不包含语法或业务运行验证。

本批测试收集 0、测试执行 0、Python/项目/Torch 导入 0、AST/编译 0、构建 0、模型前向/推理 0、优化器更新 0、训练 0、实际资料准备 0、checkpoint 加载 0、CB/原生引擎 0、CI 0。没有运行新用例中的 SQL 或子进程。A01–A10、V01–V29 和相应集成继续待验证，V30 留 T5；T1–T5 未开始。保留全部既有与并行改动，没有提交、推送、合并或发布。

## 当前剩余验收与接续边界（2026-11-09）

Q1/Q2 选定 43 项、Q3 工程 35 项、Q4 事实/接线 54 项、神经编码/预测/评分 25 项、Q5 30 项及 V10 补充 5 项已有通过结果，累计 192 个不同方法、231 次物理执行。最新 V10 五项首次全过、无生产修复，见[V10 报告](2026-11-09-axis-generic-m7-v10.md)。Q5 首轮 1 failure/4 error、两处修改及六项复验和此前各批失败历史均保留，不重复已通过且不受影响的集合。

当前授权内 M7 选定工程目标已完成，没有待补的已知专用源码缺口或未闭合失败。Q5 损失/梯度/工程更新、原四个训练方法、严格恢复/下一步更新/warm_start/游标和 V10 回收时序专用对照均已完成。剩余按主计划顺序为允许对应范围时单独验收排除的 CB 提示接口，再承接 T 阶段真实牌表/卡效/SQL 迁移、正式训练/独立评估、真实校准与能力发布；真实宿主运行、设备和历史生产权重绑定也留对应阶段。V30 实际环境适配留 T5，T1–T5 未开始；CB 和真实阶段仍未获准启动，整个 M7 不越过这些范围写成全部通过。

后续继续由主进程安排，不启用子代理。对应模型前向/反向、工程更新、保存恢复和必要导入已按本批授权执行；正式训练、真实资料准备、CB provider/搜索、原生引擎和 CI 保持未执行。不改变既有/活动权重、训练/课程暂停、LoRA 或构筑定价/学习/调度及数据库，不提交、推送、合并或发布。新代码修改先读最新文件并交付机械增量，已通过且不受影响的测试不重复。提问后等待真实回答的规则、共享文件增量合并及长任务交接规则继续有效。
