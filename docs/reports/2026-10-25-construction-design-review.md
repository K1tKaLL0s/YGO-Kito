# 构筑设计到代码的独立复核

2026-10-25；复核代码基线 `9be766876a26c1b5692c87c196bf98b007c9051d`。所列构筑源码相对该提交没有工作树修改。本次只读源码、运行选定CPU用例并新增本报告；未运行原生引擎、故障测试、付费调用或正式训练，也未改源代码。

**结论：本轮确认的构筑软件路线已落实，未发现需要阻止合并的必需代码缺口。** 判断依据是实际函数组合、真实模型前向/参数更新/恢复及具体拒绝行为。图候选由程序枚举、现有模型评分；卡效语义标注和测试卡库的来源范围照实保留。GPU实机/性能、模型能力训练、PC产品和外部LLM连接不作为此次合并前置；DP另行取得的历史数据也不冒充本轮已经导入。

## 设计与真实实现

| 确认设计 | 实际调用/约束 | 本轮证据与边界 |
| --- | --- | --- |
| 无卡ID的轻量图，积木与连接件分开 | [construction_logic](../../src/ygo_kito/construction_logic.py) 的 `LogicTag/LogicNode/LogicConnector/ConstructionLogic`；node只有tags与metadata，connector只有端点与粗kind；`from_dict`拒未知card_id字段 | 分支、合流、替代路径及codec往返实际运行；连接kind为开放短词，不执行条件语言。旧BuildTask仍保留具体卡池/硬约束，图本身不预绑定卡ID |
| 标签身份独立于注释，仅联合展示用· | `LogicNode.tag_identity`只含dimension/value；metadata另存source/layer/note；`display_label`连接标签；基本tag拒绝· | 已读实际字段及校验，重布线/改注释不改变tag身份的既有用例与图结构相符 |
| 先图，狭义才筛主轴，广义保留图跳第二阶段 | `ConstructionController.run → construction_cycle → session.propose_logic → select_main_axes → fill_with_existing` | `stage_route`分别返回[1,2,3]/[1,3]/[1]；低置信/歧义在第二/三阶段前停止。主轴用显式 `ThemeScope` 对照setcode/race事实；不据未知主题名猜字段，也不削掉通用支持卡池 |
| 非LLM可训练入口；词典辅助，主题开放 | [intent_model](../../src/ygo_kito/intent_model.py) 的 `_raw_features/fit/_scores/predict`；字符ngram/词特征加作用域辅助，softmax线性分类；`DomainLexicon.extended`与未知显式主题槽 | 实际fit降低损失、改变权重并输出归一化分数；反向标签试验证明辅助规则没有直接决定模型输出。未训练、低置信、低margin及低词表覆盖拒判；合成混合/否定/外挂样例不硬二选一。未把小样本准确率当泛化或校准 |
| 复用目标/优化模型，不加新大模型 | [construction_model](../../src/ygo_kito/construction_model.py) 的 `LogicModelAdapter.from_builder`直接复用BuildTrainer的两个BuildRanker及各自optimizer；`LogicFeatureEncoder`编码图与反馈；`rule_graph_candidates → scores → propose` | 实际对象身份相同、角色权重独立；输出明确 `bounded_program_graphs / existing_BuildRanker`。偏好训练确实更新指定角色、损失下降，保存加载后下一次更新一致；没有声称自回归自主造图 |
| 第三阶段按具体文本、卡与数量填充并核验 | [construction_binding](../../src/ygo_kito/construction_binding.py) 的 `bind/reviewer/_tag_status`；[construction_fill](../../src/ygo_kito/construction_fill.py) 复用 `goal_candidates/edit_candidates`及原BuildRanker评分 | 名称/卡文命中仅作召回；功能标签需显式source-bound评估，race/setcode可用公开事实。检查卡库哈希、desc哈希、摘录及全部标签；未知/不满足/过期文本拒绝。数量由旧候选生成/编辑与validate校验，非接口空壳 |
| 合法卡表、既有目标核验与合法CB分开 | `evaluate_fill → assets.validate → existing_goal_verifier → build_pipeline.verify_goal`，并核对task/deck摘要与accepted_status | 代码实际分派计数约束、组合路线、额外路线/搜索及普通召唤核验；本次只运行计数分支。没有verifier时明确未验；输出始终保留任意粗图 `graph_execution_verified:false`，不会把粗连接当合法CB |
| 反馈可修改或整图重构，目标→优化不中断原目标 | `record_feedback/propose_logic/submit_logic/revise_logic`保留六种来源、revision/parent链；`check_goal`钉住request与task；controller钉住required-tags摘要 | 多轮目标→优化重构实际保留目标、反馈与谱系；图变更清除旧accepted-fill证据。失败时只可返回带原图/原proof的旧候选，不为新图洗白；required tags在实际可达绑定路径集中补齐 |
| 已有统筹与manager连接 | [construction_controller](../../src/ygo_kito/construction_controller.py) 实际调用CoordinatorTrainer.advice；可显式handoff到既有Coordinator SQLite/route；[construction_service](../../src/ygo_kito/construction_service.py)由AgentBridge manager调用 | 实际CPU前向、目录绑定、旧评分、计数检查和SQLite托付组合通过。DP参考Client→Loopback→Bridge→实际后端也通过；仅资料是合成。RPC固定 `verifier=None/host=None`，故返回engine未验而不伪造完成；CLI显式核验选项可接原目标接口 |

旧模型和引擎入口可调用，不意味着完整卡效解析器已存在。当前卡效语义由带来源的评估记录/公开事实承接；缺失时返回unknown，符合“粗逻辑不等于合法CB”的闭合要求。模型权重缺失时默认未训练拒判，随机图评分也如实标明更新数和未校准状态。这些是实际软件行为范围，不追加“必须先练会所有主题”的合并门槛。

## 选定CPU验证

实际执行20项，耗时1.483秒，`OK`、无跳过。以下是本轮精确选择的方法；没有运行未筛选discovery。分类器/图训练只使用明示小合成样本验证工程代码，不生成正式权重或声称学会构筑。

```python
tests = [
  "tests.test_intent_model.IntentModelTests.test_real_fit_changes_weights_decreases_loss_and_emits_learned_scores",
  "tests.test_intent_model.IntentModelTests.test_untrained_classifier_abstains_even_when_auxiliary_rule_is_certain",
  "tests.test_intent_model.IntentModelTests.test_auxiliary_scope_rules_do_not_decide_the_learned_label",
  "tests.test_intent_model.IntentModelTests.test_learned_confidence_margin_and_oov_can_each_abstain",
  "tests.test_construction_model.ConstructionModelTests.test_real_candidate_generation_model_selection_and_codec_roundtrip",
  "tests.test_construction_model.ConstructionModelTests.test_actual_role_parameter_updates_loss_and_checkpoint_continue",
  "tests.test_construction_model.ConstructionModelTests.test_concrete_binding_covers_requested_tags_across_active_branches",
  "tests.test_construction_model.ConcreteControllerTests.test_actual_graph_models_binding_old_coordinator_and_count_goal_without_native",
  "tests.test_construction_binding.CatalogBindingTests.test_functional_words_recall_cards_but_never_certify_effects",
  "tests.test_construction_binding.CatalogBindingTests.test_explicit_assessment_binds_identity_text_and_catalog_source",
  "tests.test_construction_binding.CatalogBindingTests.test_actual_candidate_and_model_scoring_pipeline_uses_catalog_adapter",
  "tests.test_construction_logic.LogicGraphTests.test_graph_roundtrip_branch_merge_alternative_and_no_card_identity_field",
  "tests.test_construction_logic.ConcreteFillTests.test_unknown_or_unsatisfied_text_rejected_before_engine_and_can_fall_back",
  "tests.test_construction_logic.ConcreteFillTests.test_list_legality_and_engine_receipts_are_independent_from_text",
  "tests.test_construction_scenarios.ConstructionScenarioTests.test_open_theme_alias_and_multiple_functional_goals_do_not_define_a_closed_topic_list",
  "tests.test_construction_scenarios.ConstructionScenarioTests.test_all_feedback_sources_survive_repeated_target_optimizer_reconstruction",
  "tests.test_construction_service.ConstructionServiceTests.test_actual_run_reaches_existing_controller_models_binding_without_native",
  "tests.test_construction_service.ConstructionServiceTests.test_repeated_rpc_reuses_model_instances_but_keeps_new_session_evidence",
  "tests.test_construction_service.ConstructionServiceTests.test_rpc_schema_rejects_paths_options_hidden_fields_and_unknown_methods",
  "tests.test_construction_cli.ConstructionCliTests.test_actual_run_cli_connects_models_catalog_and_coordinator",
]
```

运行环境为 `OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest` 后接以上名称及 `-q`。本报告没有把Loopback当真实厂商模型连接，也没有把合成卡文/计数检查当真实核心的卡效证明。测试通过是当前本地证据；远端CI与PR合并状态由root另核。

## 给DP的数据导入速记

- 完整运行卡库：`.cache/engine-src/database/locales/zh-CN/cards.cdb`；静态收件共用reader读取 `datas(id,alias,ot,type)`，运行BuildAssets还读取完整datas与texts(name,desc)。物理资源摘要在 `.cache/engine-build/receipt.json`，上游pin在 `configs/native-sources.lock.json`。不能只交一张最小datas表冒充完整运行卡库。
- 禁表：`.cache/engine-src/client/lflist.conf`；每期明确 `banlist_section=2022.7/2022.10/2026.10`。共享严格reader拒绝节缺失/重复、重复卡号、缩进或异常限额行，按已有合计别名规则检查。
- 输入环境：`configs/user-deck-intake-template-v1.json` 的每个 `catalog/releases/banlist` 均为 `{path,sha256,source}`，路径在给定workspace内；发行文件为 `{schema_version:1,period_id,release_cutoff,cards:[{card_id,ocg_release_date:"YYYY-MM-DD"}]}`。保留逐卡真实发行与来源，预告/卡效公开不当发行。
- 设计截止：2022-09-30、2022-12-31、2026-11-01（JST含当日正式OCG发行）；2026最后卡池截至10月25日仍待核。数据缺项按期保留；`selected_period="2022-07"` 可只编译已齐期，不宣布全计划齐备。
- 现成只读审计：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python scripts/historical_listing_audit.py --index configs/historical-listing-sources-v1.json --workspace . --output .cache/historical-listing-audit/report.json`。收件/训练编译沿用Python `prepare_intake`、`compile_training_inputs`；完整加载由 `configs/period-host-template-v1.json` 描述宿主资源，不另造不存在的导入CLI。
- 百鸽入口：[about](https://ygocdb.com/about)、[API文档](https://ygocdb.com/api)。文档单卡 `/api/v0/card/:id?show=all`、发行 `/api/v0/releaseDates.json`、禁限 `/api/v0/limits.json?show=all`；本轮JSON正文未取得，普通GET的代理403已停，不重试绕过。实际HTML及地区分离证据见[百鸽来源核验](2026-10-25-baige-source-review.md)。不把这些文档链接当完整数据已取得。
