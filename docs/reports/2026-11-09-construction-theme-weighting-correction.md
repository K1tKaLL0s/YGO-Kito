# 主题／目标自动加权补正记录

后续状态：本报告的 68 项结果及文件内容摘要对应动态加权补正当时版本。后续[模块代码复查与清理](2026-11-09-construction-module-code-review.md)删除了未调用旧评分／排序，补齐连续不足提示并修正监督、预算和模式恢复；当前逐方法结果为 147 项最终通过。下文保留原始过程与失败记录，不将旧摘要当作清理后的源码摘要。

2026-11-09，实际目录 `N:\YGO-Kito\_publish_20261030`，主进程执行，无子代理、训练、CB、真实模型推理或依赖安装。实施依据见[执行书](../plans/2026-11-09-construction-theme-weighting-execution.md)。本次重开的 W3-2、W4-1、W6-2 已通过实际默认入口及下游静态验收，现已关闭。此前两次无依据的“全部完成”确认保持撤回；本次结论以以下实际运行记录为依据。

## 已明确的设计与当前代码

用户已回答：没有明确功能目标时，从主题卡的真实配合关系归纳核心机制；允许保持现行公式的百分比加权，并进一步要求区分主要目标、次要目标。当前实现默认基础权重 100%，主要目标额外 +100%，次要目标额外 +50%，换算为原公式中的增量 1、0.5。具体 100／50 是本次选取并向用户说明的默认值，不写成用户逐数指定。

`construction_theme.py` 从原任务、固定卡池、主题公开属性、明确功能目标和已有卡效归纳主要目标及直接配套。接收效果和资源准备分别归类；同一效果的同一处理同时担任两种作用时，归主要目标，不按配合条数叠加。明确功能目标优先；候选不能自报规则、百分比或主次顺序。卡名／系列号／频率本身不产生加分。

`construction_layer_flow.py` 按实际候选库存检查移动区域、所有方、原因、筛选条件，以及接收处理是否具备对象、代价、素材、次数和完整适用条件。接收效果“可以配合”与“实际已被发动”分开：随机送墓的接收条件仍可未知；潜在配合不能伪造指定卡已被送墓或已经发动。自检查、共同使用和已采用限制分别撤回对应的加权投入。继续复用原关系检查及整数分配，没有另建评分器或分配器。

`construction_inventory.py` 只使用既有完整移动判定补齐原记录缺失的区域、所有方和对象字段，并保留原观察；只有处理来源被完整覆盖，才清除对应剩余处理未知。没有修改并行卡效识别实现。

`construction_progress.py`、`autonomous_construction.py`、`construction_fill.py` 的默认入口已经改接自动规则生成。原有两期指定参考清单仍按原课程身份绑定，这部分身份用于选取用户指定的牌表，不能决定评分规则；其他主题不隐式继承参考。旧显式规则仍可消费。规范化版本升为 `construction-function-normalization-v13`；旧分数不得混入新比较。政策修订清除候选／参考旧分和旧准入，保留任务、牌表、原骨架及推进位置，并保留旧参考评价供核对。自动配合及实际功能证明同时复用既有换备容量检查；准备方、接收方及必要处理对象必须有足够位置，不能把分开的备选资源当作已经共同可用。容量筛选后只剩未知证明时，仍保留该证明的具体未知条件。

## 实际验证记录

| 检查 | 实际结果 | 可以证明的范围 |
| --- | --- | --- |
| 第一版 `tests.test_construction_theme`，6 个定向静态方法 | 6 通过 | 当时版本的匿名墓地机制、特殊召唤诱发、除外回收、百分比、默认填卡入口排序、配套删除、明确目标、必要输入未知。不是当前全部扩展检查的通过证明。 |
| 扩展后的同模块，13 个方法 | 10 通过、3 error | 完整 LP 代价及共同短缺、主次不重复、重复接收方、所有方／原因／对象反例、未采用限制与已采用限制等得到通过结果；2 项在现有多因子包公开导入处中断，1 项是测试单独编译真实方法时缺少 Python 包上下文。 |
| 上述失败的 3 个方法定点复查 | 1 通过、2 error | 已修复测试包上下文，真实 `quality_for_task` 方法静态调用通过；两项默认入口仍受同一个公开导入错误影响。没有运行完整模型模块。 |
| 当前 `tests.test_construction_functional_quality` | 28 通过 | 本次修改后的纯计分器、公式、损失、Side、未知及绑定静态回归。 |
| 当前 7 个实施模块、2 个测试文件 AST 检查 | 9 文件通过 | Python 语法；不代替业务验收。 |

## 公开接口恢复和最终检查

用户已真实授权主进程仅修公开接口衔接。复查时工作区现有 `multifactor/__init__.py` 已将 `ANALYSIS_MODES`、`DeckSpec` 等改由 `contracts` 导出。全新进程中 4 项导出身份检查通过，未加载 Torch；本轮没有对此再作源码修改，也不将现有修正归为本轮新增实现。原待答问题和导入阻塞均已解除。

恢复后的第一次主题 16 项检查得到 15 通过、1 失败。失败发生在准入测试夹具：没有给课程对象绑定该轮已经确定的政策，准入按原条件返回 pending。已补上测试夹具的宿主政策绑定，未放宽应用准入条件。其后 66 个不同定向静态方法整组通过。

收尾的直接换备对照又发现实际实现遗漏：只有 1 个额外卡组位置时，副牌准备方与接收方各需 1 个位置，自动共同配合仍为 true。已复用原容量检查修正，并保留容量筛选后剩余证明的真实 unknown。新夹具初次还缺少合法的主题常驻卡及可读取的融合素材文本，已补全夹具，没有通过置真未知来补证。最终用例确认：容量 1 时撤回该两卡配合，另一个尚未给出的接收方发动方式保留 unknown；容量 2 时恢复完整加权，S=3.5。该修正归原 W3-2／W3-3，不新增工作包。

| 最终检查组 | 不同方法数 | 结果 |
| --- | ---: | --- |
| 自动主题／目标及真实默认入口 | 17 | 全部通过 |
| 纯功能计分、损失、Side、未知及绑定 | 28 | 全部通过 |
| 受影响的实际功能适配、限制、换备、政策、参考及恢复 | 16 | 全部通过 |
| 受影响的完整库存、对象和素材选择 | 4 | 全部通过 |
| 原有纯静态选择／监督／样本消费契约 | 3 | 全部通过 |
| 合计 | 68 | 68 通过，0 失败、0 error、0 跳过 |

上述 68 个方法在修正后的同一轮中执行完成，不累加历史重复执行次数。实际日志及全部方法标识：[JSON](../../.cache/theme-weighting-20261109/targeted-static-final.json)、[文本日志](../../.cache/theme-weighting-20261109/targeted-static-final.txt)。JSON 同时记录本次 9 个实施／测试文件的内容摘要。该进程 `torch_imported=false`，训练、CB、真实模型推理均为 false。前述失败和中间 66 项通过保留历史语境，不能代替此最终记录。

最终收尾：9 个实施／测试文件语法、内容摘要绑定及行尾检查通过；6 份维护文档的 228 个本地链接和验收测试方法行号全部通过。逐项核对为 38 条验收已完成、固定 13 项已完成、补充结构 12 行保留对齐。没有待答问题。

复查相同 68 项可在仓库根目录执行：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
$themeChecks = (Get-Content -LiteralPath '.cache/theme-weighting-20261109/targeted-static-final.json' -Raw | ConvertFrom-Json).passed
& 'C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe' -m unittest $themeChecks
```

## 自动入口的具体证据

| 要求 | 当前测试方法 |
| --- | --- |
| 无手填规则，真实配合归纳主次；特召诱发、除外回收使用同一通用实现 | `test_default_inference_uses_percentages_for_two_non_grave_mechanisms` |
| 百分比转换为原公式增量；明确功能目标优先 | `test_explicit_function_goal_changes_roles_without_changing_formula` |
| 原任务只换主题，相同两份候选的优劣顺序反转 | `test_changing_only_the_task_theme_reverses_the_preference` |
| 实际默认填卡、最终 S 排序及有效偏好样本，不靠配置夹具证明自动功能 | `test_default_fill_uses_automatic_rules_and_strict_final_quality_order` |
| 默认持续构筑、参考同口径重评、政策修订保存推进位置、准入同口径 | `test_default_cycle_and_policy_revision_rebind_reference_and_preserve_progress` |
| 随机送墓与指定卡实际发动分开；移除配套保留基础功能 | `test_random_mill_proves_available_cooperation_without_claiming_a_specific_call`、`test_removing_actual_counterpart_withdraws_only_its_preparation_bonus` |
| 完整代价、共同短缺、真实资源代价和接收数量 | `test_full_payment_and_joint_contention_withdraw_secondary_bonus_at_the_right_stage`、`test_resource_cost_is_a_real_mechanism_and_does_not_label_unrelated_draw_effects`、`test_complete_recipient_quantity_is_required_without_deleting_the_source_function` |
| 所有方、代价／效果原因、完整对象和剩余原文反例 | `test_reason_owner_selector_and_incomplete_text_do_not_create_false_cooperation` |
| 主要目标优先，同一处理及多份配合证明不重复加权 | `test_primary_precedence_and_duplicate_counterparts_never_stack_bonuses` |
| 未采用的可选限制不影响；已采用限制撤回对应配合收益 | `test_unused_optional_lock_does_not_block_and_adopted_lock_withdraws_counterpart_bonus` |
| 卡名和编号替换保持同分；旧政策拒绝混用，实际宿主方法读取当前固定卡池 | `test_renaming_and_reidentifying_equivalent_cards_preserve_scores`、`test_stale_profile_is_rejected_and_kernel_policy_method_uses_actual_task_catalog` |
| 缺少必要主题输入保留具体 unknown；普通无主题任务明确空规则 | `test_missing_theme_input_is_unknown_and_explicitly_ordinary_task_is_empty` |
| 副牌的准备方、接收方与必要对象必须满足共同换备容量 | `test_automatic_side_cooperation_requires_both_cards_to_fit_the_extra_deck` |

方法均位于 [test_construction_theme.py](../../tests/test_construction_theme.py)。真实宿主方法以源代码中的实际 `quality_for_task` 单独编译调用，避免加载或初始化模型；其余填卡、构筑、参考、排序、学习样本校验及准入使用实际静态入口。宿主提供的阶段、代价和状态事实有具体来源，没有把全部未知置真。旧显式独立主题规则继续兼容，两个独立规则仍可同时成立；自动主次归类则按用户新口径对同一处理取较高档。

## 固定清单结项

- W3-2：已完成。自动依据任务与真实配合生成规则，主要目标额外 +100%、次要目标额外 +50%，保持原公式，正反例与两种非墓地机制通过。
- W4-1：已完成。默认入口、原指定参考、政策修订、同口径重评和准入通过；课程身份只用于选取指定参考，不决定加权机制。
- W6-2：已完成。当前 17 项自动主题检查及必要回归共 68 项整组通过，原结构证据继续复用，A10 关闭。

当前固定六包 13 项完成，38 条验收及 12 行补充结构证据均已对齐；本次重新关闭三个项目，其余 10 项复用既有完成证据。必要输入缺失和已声明预算范围仍按原契约保留，不以清除所有 unknown 为结束条件。所有原有未提交修改、删除和未跟踪文件保留，没有提交或推送。
