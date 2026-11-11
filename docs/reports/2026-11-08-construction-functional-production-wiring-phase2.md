# 构筑功能评价：候选生产接线与续接状态

开始日期：2026-11-08；收尾日期：2026-11-09（Asia/Hong_Kong）。实际源码：`N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，本轮起点 HEAD `3f57198`。工作树含大量此前修改、删除和未跟踪文件，本轮保留了这些现状；未提交或推送。

## 当前结果

显式 v4 政策现在能进入实际 `ConstructionLayerAdapter → fill_with_existing → construction_cycle → gate` 链路。候选各自先规范化和评价，完整且硬条件成立的候选按最终 S 排序，然后裁剪保留集。未评完的候选、已有评价、原始生成顺序及游标可保存并恢复。学习、重选及课程记录已增加对同一 Evaluation 的消费。

这是生产接线的一批实现，不是整个正式方案完成。真实效果的共同资源、主题配套及 Side 情境尚未全部适配，相关范围保留 unknown/deferred。真实 2207/2210 参考、2610 政策配置未写入或重评。`QUALITY_VERSION` 仍为旧 v3；公开 `evaluate_quality/compare_quality` 已能按显式 v4 输入分派，旧百分制实现和非 v4 候选路径仍保留。没有默认启用未完成的 v4 生产政策。

继续依据[正式方案](../plans/2026-11-08-construction-model-formal-optimization-plan.md)第 12 节。上一批内核证据见[phase1](2026-11-08-construction-functional-core-phase1.md)，不要重新盘点项目或重跑其未变化的全部用例。

## 授权与执行边界

用户已明确授权“新开并继续构筑模型的生产接线，带上简洁交接摘要。允许少量必要测试，仍不运行训练和 CB”。本轮由主进程直接执行，没有子代理。已读取 `C:\Users\27499\.codex\instructions\code-work.md`、preserve-intent-and-execute、anti-overengineering，承接正式方案执行书并在修改前交付本轮具体执行项。

没有运行训练、CB、原生对局、真实模型推理、全库测试、CI 或性能测量。没有修改生产权重、暂停文件、课程指针、外部配置或设计台。`basic_cb_inference.py` 本轮只扩展可识别的 gate 版本；执行授权条件保留，未运行 CB。

## 文件与行为

| 文件 | 本轮实际修改 |
| --- | --- |
| `src/ygo_kito/construction_layer_flow.py` | 新增 `NORMALIZATION_VERSION`、`functional_asset_version`、`normalize_function_uses` 和宿主事实补充校验。v4 路径逐候选装配完整库存，复用目录效果、InventoryDependencies 和关系评价；建立实际效果/语义功能/用途/物理来源身份、卡与效果覆盖、事实与用途诊断、独立原任务硬要求。逐候选调用新评价器，再按 S 排序；支持已评缓存、暂停、待评索引和候选预算。 |
| `src/ygo_kito/construction_inventory.py` | `_check(..., distinct=True)` 复用整数实体匹配用于完整代价。原 `joint=True` 的怪兽素材过滤不再误用于魔法/陷阱等普通费用资源；未新增求解器。 |
| `src/ygo_kito/construction_quality.py` | 新旧配置和纯入口按显式版本分派；v4 可接收规范化诊断、独立硬要求及真实库存。结果绑定规范化/字典版本。新增 `functional_delta`，共享明确事实身份时联合计算候选/参考差值，不能靠相同端点宣布完整。未删除旧 v3。 |
| `src/ygo_kito/construction_fill.py` | 新增政策/事实/暂停/待评批次输入；全部已生成候选先评价，未完成时保存批次且不提交最终 portfolio。每个候选、learning_candidates、portfolio 保存自己的质量结果。v4 cycle 直接消费，保存 schema 3 待评状态，恢复不重生成骨架、优化图或候选；预算与暂停不增加停滞次数。支持既定参考列表及功能分反馈。 |
| `src/ygo_kito/construction_progress.py` | 新增功能版 gate v3；显式无参考正常检查，指定参考消费实际 Evaluation 和 80% 比例。可选库存缺口保留诊断，硬要求单独检查。恢复验证候选/政策/事实/资产和图绑定，陈旧结果失效。新增宿主显式 `revise_quality_policy`，保留牌表、骨架和游标。旧 gate 与 schema 2 非 v4 路径仍保留。 |
| `src/ygo_kito/construction_learning.py` | `SOURCE=construction_quality_preference_v2`；新比较、标签和验证绑定双方 Evaluation；旧 layer_comparisons 不生成新标签。保留被裁候选的严格偏好、实际优化轮次和评价去重。`quality_order` 及 `rank_candidates` 按 S 排序，模型分只破同分。 |
| `src/ygo_kito/construction_candidates.py` | 功能版 retained 重选校验自身 gate/政策/质量绑定，并拒绝较低 S 覆盖已通过的更高 S；选中后的阶段质量记录随候选切换。旧非 v4 分支保留。 |
| `src/ygo_kito/semantic_training.py` | 现有监督校验路由接纳新的质量偏好 source。没有参数更新。 |
| `src/ygo_kito/autonomous_construction.py` | 从宿主 `source_binding.construction_quality_reference` 转发既定参考；默认事实由适配器提供。未写入真实政策。 |
| `src/ygo_kito/course_admission_policy.py` | 完成记录消费该候选自己的质量与已存参考，保留质量身份并使用实际 gate 版本。 |
| `src/ygo_kito/basic_cb_inference.py` | 仅允许门槛检查识别新 gate 版本；原显式执行授权、任务、牌表与版本检查保留。 |
| `scripts/local_course_collaboration.py` | 质量偏好的 artifact/source 展示名称和收据字段迁移；未运行脚本。 |
| `tests/test_construction_functional_flow.py` | 新增 12 项无模型/无引擎的候选规范化、排序、恢复、gate、记录及标签静态用例。 |
| `tests/test_construction_functional_quality.py` | 新增共享未知差值用例；原内核用例保留。 |
| `tests/test_construction_unification.py` | 三项既有标签/跨轮/裁剪用例改为功能质量契约，其他测试未扩展。 |
| `tests/test_construction_selection.py` | 三项既有模型替身/监督/模拟消费用例迁移为新契约；当前解释器缺 torch，尚未运行成功。 |

上述若干源码本来就未跟踪，`git diff --stat` 不能显示它们；其余 diff 同时包含以前的工作，不能将整个 diff 当成本轮新增。识别任务也在同一工作树修改文件；本轮未修改 `effect_records.py`、`effect_blocks.py`、识别网络、`construction_recognition.py` 或 `multifactor`。

## 当前规范化边界

- 每份候选按自己的 Main/Extra/Side 读取；同批其他牌表不能提供材料或对象，也不能占用它的读取预算。新功能身份不用图节点或轴名；同源重复证明仍由质量内核归并。
- 普通 Main 使用实际 N；Extra 的调用用途仍须满足自身支撑。普通 Main 的自动“具体调用”识别尚未完成，不应把整卡改为 called。
- 库存存在与实际区域/事件/支付支持分开。完整费用缺口不给部分比例；已确定失败条件下不保留不相关执行未知。没有独立潜在分的原任务硬要求仍能阻断 gate。
- 关系层消费完整 resident 库存和显式 host required uses，不把所有可选效果联合为硬目标。当前复杂分支、回收、顺序及自肃没有被自动证明；缺失的执行观察仍为 unknown。
- Side 记录读取与 resident 分离；非空 Side 的方向投影尚未完成，当前标 deferred。空 Side 可为已评零。复杂限制尚未映射到 UseImpact 时 impacts 范围保留 deferred。
- 主题语义谓词与实际配套分开；当前尚未自动完成全部主题支撑，宿主可以提供有来源、绑定候选和资产的未知事实补充。已知失败不能被覆盖。旧标量 loss 等输入报 semantic rebind 错误，不混入 log2。
- 检索附带的检视/展示/洗切不能直接另奖一份功能；无法确定是处理步骤还是独立功能时保留具体语义缺口。完整效果词典与资产解析覆盖仍由识别事实接口承担。
- 默认执行/库存未知使用候选绑定的事实 ID；只有宿主明确共享的事实 ID 才用于跨候选或参考的联合补全，避免把不同候选的资源可用性错误相关联。
- 损失目前仍是阶段总差值。逐功能/来源/通道损失、原因合并、共同修复组和可恢复分尚未补齐。

## 实际验证

解释器：`C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`。工作目录为实际源码目录；进程内 `PYTHONPATH=src`、`PYTHONUTF8=1`，`-B` 禁止字节码缓存。

最终集中定点命令：

```powershell
$env:PYTHONPATH=Join-Path $PWD 'src'
$env:PYTHONUTF8='1'
& 'C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe' -B -m unittest tests.test_construction_functional_flow tests.test_construction_functional_quality.FunctionalQualityTests.test_comparison_shares_consistent_unknown_completions tests.test_construction_functional_quality.FunctionalQualityTests.test_correlated_unknown_equal_endpoints_do_not_mean_complete tests.test_construction_functional_quality.FunctionalQualityTests.test_failed_self_support_is_not_deducted_twice tests.test_construction_unification.ConstructionUnificationTests.test_quality_labels_bind_actual_inventory_and_reject_changed_evidence tests.test_construction_unification.ConstructionUnificationTests.test_early_quality_signal_keeps_actual_iteration_and_deduplicates_evaluations tests.test_construction_unification.ConstructionUnificationTests.test_valid_comparison_survives_top_three_retention -q
```

结果：`Ran 18 tests in 8.695s`，`OK`，退出码 0。随后补强“资产文本变化导致缓存失效后，重新评价仍受候选预算限制”分支，仅重跑相应用例 `test_paused_evaluation_keeps_pending_and_resumes_same_candidates`：`Ran 1 test in 1.369s`，`OK`，退出码 0。此项属于前面 18 项之一，不能累计为 19 个独立用例。

16 个本轮相关 Python 文件通过 `ast.parse` 语法检查；涉及的 tracked 源码和脚本 `git diff --check` 通过。没有运行整个旧内核 18 项或全库发现。

收尾文档链接已核对；文档范围的 `git diff --check` 在 MASTER-CHECKLIST 的并行识别任务末行报告 trailing whitespace。该行不属于本批修改，没有扩展为无关清理；不将这次文档检查记为通过。

首次运行旧 fixture 时 Windows 默认文本编码导致配置中的连接符读错；仅在测试进程设置 `PYTHONUTF8=1` 后恢复，未修改配置原件。三个依赖 torch 的 `test_construction_selection` 测试因 `ModuleNotFoundError: No module named 'torch'` 未能运行，不算通过。没有安装依赖或切换到训练；其中排序和标签绑定的关键行为已由纯静态 `quality_order`、`validate_pair`、重选与课程记录用例检查。实际 torch 模型前向、完整 semantic_training 监督校验/消费和参数更新仍未验证。

这些测试使用匿名卡表、现有效果解析、明确的静态宿主复核和替身宿主，不证明真实卡池全部语义已覆盖；也不代表正式方案 A01–A38 全部验收。

## 未完成与下一原子阶段

当前没有外部服务阻塞，也没有未回答的实现/测试授权问题。下一阶段应优先补齐事实适配的剩余语义，再完成默认生产切换；不要先改公共版本常量或拿 fixture 政策充当真实参考。

1. 按正式执行书步骤三，完成共同资源/强制影响：在已有 InventoryDependencies、construction_relations 与共享识别事实接口上处理完整 all/any、整数资源、次数、顺序、自肃、回收与显式共同用途；不要再建求解器，不修改识别网络设计。扩展 effect/use 事实时与并行识别任务的现状合并。
2. 补齐 Main 的具体 called use、自动主题谓词与接收方支撑；保留墓地相关和堆墓两个通道。不能把当前 unknown 变量全部置真作为生产策略。
3. 完成 Side 方向隔离投影、容量和同名限制、完整 X−R、恢复与损害；不能将 Side 库存倒灌 resident。处理强制负面事实到已计收益 UseImpact 的映射。
4. 补齐逐收益损失解释、全部原因和共同修复组。现有阶段 totals 可继续使用，不再额外扣一次 D。
5. 迁移并核对宿主真实政策、既定参考及明确 none 模式；真实参考同口径重评。当前 cycle/reference 接口已存在，但没有写入实际 2207/2210/2610 配置。补充 schema 2 旧百分制存档到待重评的完整迁移/政策修订工作流；不能把当前“显式 v4 schema 3 已可恢复”外推为所有旧档迁移完成。
6. 在依赖可用且检查仍获授权时，补跑已迁移的三项 torch 依赖契约测试，以及当前变化确有必要的静态验收；不运行训练、CB、原生对局或旧整库白名单。复核配置/解析错误的进度保存、参考陈旧结果和绑定的边界分支，不把它们变成负样本。
7. 这些范围闭合后，退出旧 v3 七项百分制、旧层选择回退和旧结构批准开关，统一公开版本，更新活动文档。当前旧路径保留是迁移状态，不是最终设计。

## 续接约束与提示

保留全部本地修改、删除和未跟踪文件，不 reset/clean/checkout 覆盖，不恢复已删除文件，不新建遗漏本地修改的工作树。当前源码在 `_publish_20261030`，外层仓库不是实施基线。主进程执行，不启动子代理；禁止训练、CB、生产权重/暂停文件/课程指针操作；不擅自提交推送。不要追索或运行 Pro 辅助演示代码，不重做旧研究，不把其他聊天的测试授权扩大到本聊天或反向引用。

本批结束于“显式 v4 候选链路、保存恢复及消费接口已接通且有定点证据；复杂真实语义与默认生产迁移尚未完成”的安全边界。下一阶段会修改共同资源、影响和方向情境，需保留本报告的未完成范围。建议新开聊天接续，未经用户明确确认不创建。若用户明确要求留在本聊天继续，则从上述下一阶段恢复，不重做已完成接线。

建议新聊天首条提示：

> 继续 YGO-Kito 构筑模型生产接线。先读 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-08-construction-functional-production-wiring-phase2.md`，再按其引用的正式方案第12节继续。实际源码为 `_publish_20261030`，分支 `codex/optimization-20261031`，起点 HEAD `3f57198`，保留全部本地修改、删除与未跟踪文件。用户已授权主进程实施及少量必要静态测试，但禁止训练、CB、原生对局、生产权重/暂停/课程指针操作，不启动子代理。显式 v4 现在已接通候选自身规范化、选择前全部评价、pending/schema3 恢复、S 排序、质量偏好标签、gate/参考和课程记录；默认生产政策和旧 v3 尚未替换。18项定点检查通过，随后加强的缓存失效预算用例单项通过，16个文件语法检查通过。三个 torch 依赖测试因当前Python缺 torch 未运行成功，不当作通过。下一阶段是已有求解器上的完整共同资源/强制影响、Main具体调用、自动主题、Side完整X−R和详细损失账本，再迁移真实政策/参考及旧档，最后退出旧评分。不得把 unknown 全置真或提前宣布完整上线。先读代码执行细则并承接已有执行书；不重复旧研究或 Pro 辅助代码。任何新问题提出后必须等真实回答并暂停依赖工作。长任务优先当前聊天继续并允许压缩；若继续压缩危及约束/状态/证据保真，或阶段形成安全交接边界，先完成当前非破坏性原子步骤、停止新阶段、主动建议新开并给独立摘要；未经确认不创建，不声称看到精确上下文占用比例。
