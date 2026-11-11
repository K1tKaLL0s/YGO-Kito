# 构筑固定清单实施记录

后续状态：当前实现以[模块代码复查与清理](2026-11-09-construction-module-code-review.md)及[验收表第 9 节](../plans/2026-11-09-construction-acceptance-alignment.md#9-模块复查与旧入口清理)为准。旧 Python 评分类型和死分支现已删除；原档案仍以字典保留，不依赖旧类型。此前漏验的连续不足提示、监督和代码状态问题已补齐。下文保留实施当时的源码说明与运行记录。

2026-11-09 动态加权复核补正完成：原先无依据的“固定 13 项全部闭合”结论保持撤回；本次经自动归纳和主次百分比实施、真实默认入口及下游静态检查后，重新关闭 W3-2、W4-1、W6-2。当前固定 13 项完成，38 条验收及补充结构对齐，68 个不同定向静态方法整组通过。公开接口阻塞已解除，测试夹具和换备容量修正均保留实际失败／修正记录。最新实现及全部验证见[主题加权补正记录](2026-11-09-construction-theme-weighting-correction.md)和[验收表](../plans/2026-11-09-construction-acceptance-alignment.md)。以下是原实施与运行日志，不把历史手工规则夹具通过当作自动入口证据。

日期：2026-11-09。源码 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，原 HEAD `3f57198`。本记录承接[验收对齐表](../plans/2026-11-09-construction-acceptance-alignment.md)的固定 13 项，不另增按卡组拆分的批次。主进程执行，无子代理；仅必要静态检查，无训练、CB、真实模型推理、识别修改或并行识别验证。

## W2 共同通召和回收（两项已完成）

实际通常召唤及其规则入口使用一次通常召唤次数；不同替代用途分别判断，仅共同要求合并资源。由效果进行的召唤沿用该效果自身许可；已给出的额外通常召唤次数及其条件通过同一资源接口参与检查。宿主已声明某条入口时，不再用一个凭空的 unknown 替代入口绕过已确定的次数不足。规则入口与效果进行召唤的区别参考[官方“二重召喚”说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=6772&keyword=&ope=5&request_locale=ja&tag=-1)和[“連撃の帝王”问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=14947&keyword=&ope=5&request_locale=ja&tag=-1)；实现按已声明的实际入口消费次数，不按卡名。

完整旧式返回声明的消费后去向、后续所需区域和库存实体可适配到现有实体转移检查。它与明确转移混用时，使用同一有界整数安排和实体状态，不凭空增添副本。所有方、控制方、错误起点、到达区域、完整代价及离场除外仍由原检查处理。未给的区域保持未知，未扩展阶段或精确牌组顺序。

三个新增方法通过：

```text
tests.test_construction_relations.SupportAssessmentTests.test_normal_summon_capacity_only_combines_explicit_joint_uses
tests.test_construction_relations.SupportAssessmentTests.test_complete_legacy_and_entity_returns_share_one_physical_schedule
tests.test_construction_functional_flow.FunctionalFlowTests.test_declared_normal_entry_combines_only_when_functions_are_joint
```

回归通过：`test_cross_zone_transfer_preserves_quantity_fee_and_incremental_updates`、`test_cross_zone_transfer_tracks_same_slots_and_final_state`、`test_summoned_leave_rule_changes_only_selected_entity`、候选层 `test_intrinsic_recipient_prohibition_reaches_required_summon_and_trigger`、`test_explicit_joint_group_withdraws_only_bound_functional_uses`。4 项运行 `0.508s, OK`；3 项运行中通召候选对照发现 unknown 替代入口绕过次数不足，修正后 `Ran 3 tests in 0.397s, OK`（含 W1 额外代价回归）。不同方法数不按重复运行累加。

以上为 W2 完成时的记录。当时完成 4／13，随后继续完成下列工作；该阶段原记为 13／13；本次已更正并重开动态加权三项。

## W3 具体配套、通用主题和换备（自动加权未完成）

具体调用不再限定卡组起点；墓地起点的召唤配套只改变被支持用途的计量方式，同卡另一效果仍按自身条件判断。移除实际配套后撤销调用支持。主题判断使用宿主给定的处理条件，空主题、墓地主题、抽卡主题及手卡特殊召唤主题共用同一评价器；更换匿名卡名仍同分。

方向视图保留原主卡组张数和权重。独立工具按可容纳的副本组合保留价值；明确共同用途检查来源、供应卡、代价/素材的物理副本及容量。现有整数匹配结果同时供容量检查使用，仍不生成具体换出名单。互斥共同模式不得拼接收益；已声明返回的资源继续按原返回规则处理，超出已核实安排时保留具体 unknown，而不是假定多一张资源。

新增三个静态方法最终通过：`test_non_deck_call_changes_only_the_supported_function`、`test_non_grave_themes_and_empty_theme_share_the_same_evaluator`、`test_side_alternatives_fit_individually_but_joint_sources_need_capacity`。后者直接覆盖额外卡组容量 1/2、可分别使用、共同使用和互斥声明。原墓地双主题、方向恢复、加入手卡限制及方向负增量对照通过。初次移除配套的夹具误用了已满三张的填充卡，改为合法替换后通过，没有扩大卡片上限。

## W4 宿主政策和实际参考（真实参考已接，通用政策待补）

`host_construction_quality` 装配固定政策；自主构筑内核按宿主时期和已选主题读取，拒绝候选选项覆盖政策/参考。课程准入调用同一政策装配。2207、2210 的珠泪任务分别读取实际 `main-01-source-v1.json`、用户授权替换的 `main-02-source-v2.json`，核对数值牌表摘要并绑定任务环境。2610 显式 none；其他主题没有珠泪参考回退。墓地相关、堆墓各 +1 只属于该主题政策，通用任务为空主题。

`test_host_policy_reads_actual_references_and_keeps_other_themes_unbound` 通过，实际读取两份项目文件而非另造参考牌表。既有候选/参考同入口评价、错绑拒绝和 none 模式对照继续通过。该项完成的是静态生产接线；参考自身缺少场上、手卡或其他适用事实时继续给出相应未知，不把其条件全部置真。

## W5 旧档、版本与活动入口（三项已完成）

schema 2 恢复保留任务、图、骨架、牌表、候选、迭代、停滞计数和游标，原百分评价完整归档，列出 SlotUse 和损失待重新绑定的位置。已 verified、仍 unknown 的原用途及来源保持原样。旧标量不转换为 log2。宿主政策已有时进入同一重评流程；尚未装配政策时保持未配置，不虚造原主题。

候选、参考、保留候选、排序和偏好样本核对当前规范化/功能版本，直接准入和实际重选另核对政策、牌表及当前资产/卡文。陈旧参考独立撤下重评，不因当前候选有效而沿用旧参考。保留原牌表和待评队列，不重生成目标骨架。

当前默认质量为 `construction-quality-evaluation-v4-functional-log2`，规范化为 v12，活动准入为 v3。公开评价、填卡、排序、重选和准入不再调用旧七项百分制、旧层优先排序或结构批准开关；百分计分函数已删除，旧记录类型仅用于读取/重绑。层评价仍提供诊断和骨架依据，不作为最终分数的回退。旧百分制历史测试的评分断言不再是活动评分要求，本轮使用迁移与新入口对照验证替代行为，没有伪报它们仍通过。

新增 `test_schema_two_migration_preserves_progress_and_unknown_slot_sources`、`test_stale_reference_and_direct_consumers_require_current_normalization` 通过；既有暂停恢复、四评三留、待评 JSON 继续、资产变化重评和最终分标签方法通过。迁移保真断言最初错误比较了 JSON 前后的元组/整数键表示，改为比较实际存档表示后通过；原数据没有改写。

## W6 指定验收与补充结构（自动加权入口证据待补）

十二条待补证据已合并为下列静态场景，方法均位于原功能评价测试模块：

| 方法 | 实际覆盖 |
| --- | --- |
| `test_acceptance_split_discounts_channels_and_extra_withdrawal` | A02/A03/A16/A27：log2(3) 的合并/拆分，主/额外各 1/2/3 张，(4,3,2)→(3,2,1)，额外 2.6→1.8 及重排。 |
| `test_acceptance_independent_unknown_loss_and_shared_log_channel` | A29：[8,11]→[6,9]；共用对数通道须联合重算，不能平移损失。 |
| `test_acceptance_side_direction_increment_is_withdrawn_once` | A25：0.5849625007211562 的增量只在失败方向撤销后乘权重，R=1 保持。 |
| `test_complete_structures_and_removed_support_keep_actual_main_size` | A04/A05，S01–S08：40/15/15、50/60 主卡组、空/少量额外、额外代价、空副牌组；每例检查完整牌表与替换必要配套后的合法性及分数下降。40 张 E=12 与 60 张 E=18 均为 log2(13)，E=10 的 40→50 张变化为 0.289506617194985；无害额外填充同分。 |
| `test_six_part_payment_fails_and_independent_three_part_mode_survives` | A08：六份代价只有五份，三份独立模式有效；没有 5/6 收益或虚构损失。 |
| `test_reference_numeric_boundaries_invalid_zero_and_static_cb_markers` | A26/A34/A36：90/60 不放行，50/42、70/56 达标；零/非法参考不放行；三种静态 CB 标记不改分或偏好。 |
| `test_external_target_and_delayed_condition_use_the_supplied_route` | S09/S10：合法对方对象、明确无对象、结束阶段才适用、未来条件未知及未给对象分开。完整宿主对象事实不再额外卡在己方库存检查。 |
| `test_lp_payment_is_complete_and_unpriced_with_joint_contention` | S12：2000 LP 代价，可合法支付的基本分足额/仅 1999 时及两次共同支付争用；可支付时功能分正常，负担仍为 unpriced_effect。这里消费宿主已核实的合法支付额度，不把当前 LP 总额直接当作可全额支付的数量。 |
| `test_no_source_cycle_is_a_gap_and_seed_propagates` 的现有扩展 | S11：实际通常召唤规则入口打通循环，移除入口后循环用途失败，独立用途保留。 |

实际改牌后的最终 S 已在结构场景中由修改后的牌表重新计算，没有读取条件性的 recoverable 作为净分。通用主题及五种实际素材种类与 W1/W3 证据共用，不按卡组再拆工单。

三个此前受 torch 导入阻挡的方法现已全部通过：`test_updated_model_preference_cannot_replace_higher_final_quality`、`test_quality_preferences_enter_existing_semantic_learning_contract_without_updates`、`test_pre_cb_slice_ingests_strict_optimizer_samples_once_without_real_updates`。只使用手写分数对象和消费替身。纯监督投影移至现有 `semantic_training` 并由原入口重用，质量样本校验不再无条件导入训练或辅助模型模块；没有复制另一套校验器，没有读取/运行 Pro 辅助演示或进行参数更新。另一个真实模型入口方法未运行。

后续运行记录：7 项初次运行中 4 个方法通过，另外两个夹具错误分别是 called 参数重复传递、50/60 张任务沿用了 40 张最大怪兽数；修正各自夹具后 `Ran 5 tests in 2.199s, OK`。三个消费契约 `Ran 3 tests in 1.360s, OK`。W2/W3/恢复定点回归 `Ran 6 tests in 1.350s, OK`，最终分/消费回归 `Ran 4 tests in 1.565s, OK`；对象延后范围最终 `Ran 1 test in 0.233s, OK`。重复方法不累计不同方法数。

额外卡夹具曾人为加入通常怪兽标记 0x10，此写法不应代表无效果融合怪兽；已改为实际类型 0x41 和完整素材说明，重新通过额外代价及完整结构对照。随之出现的零正分素材说明记录也不应被当作共同工具收益，已收紧相应断言；最终换备、限制、回收和陈旧参考 5 项定点检查 `Ran 5 tests in 1.175s, OK`。这些修正没有修改卡文识别实现。

## 完成状态与保留边界

原“固定 13 项全部闭合”结论已撤回。当前 10 项保留完成，A10 的通用自动主题加权仅部分完成；既有补充结构对照保留，不能代替自动入口验收。输入未给、原文只含粗标签或既有有界检查不足时，相关 unknown 及其来源继续保留；这不是新增的无限工作清单。不以全卡池原文穷举、未知清零、真实模型学习效果或 CB 结果作为本轮终点。

保留所有预先存在的修改、删除和未跟踪文件；未提交、推送或改动权重、暂停文件、课程指针及外部配置。代码与文档最终静态检查结果见验收表的收尾记录。

最终检查：18 个本轮涉及的 Python 文件 AST 语法及行尾检查通过；5 份维护文档的 206 个本地链接检查通过，验收表测试行号均指向实际方法起始行。直接重选另补原任务错绑拒绝，暂停/保留候选/课程准入的静态方法最终 `Ran 1 test in 1.016s, OK`。这些检查没有调用训练、CB 或模型推理。
