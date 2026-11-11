# 构筑功能评价：全局返回、有限事件与费用顺序第五批

日期：2026-11-09（Asia/Hong_Kong）。实际源码为 `N:\YGO-Kito\_publish_20261030`，本批开始核对分支 `codex/optimization-20261031`、HEAD `3f57198`。全部既有未提交修改、删除和未跟踪文件保留，没有提交或推送。

## 本批结果与依据

跨层 all 与共同用途现在会重新检查派生资源结论；外层补齐具名端点后，可消去子组的资源未知，同时保留卡效来源的真实未知。同一个返回事实只建立一个事件，多条后续边共同引用这一事件，并按此前各消费的有限整数数量分配返回量。返回量、实际实体、完整费用和宿主顺序同时参与检查，没有增加库存 K。

`PoolRecovery.cost_timing` 新增完整费用先后声明，默认 `unspecified` 兼容旧契约。明确为 `before` 时，完整前置消耗先于具名的前次消费；`between` 时，前次消费先于完整费用，费用先于返回事件。后续消费只能使用返回之后的库存，不能提前借用它支付费用。

补齐了闭包依赖：返回事实变化直接通知实际消费该池的效果或用途，不再依赖供给者自身状态发生变化。一个“返回 A 的费用需要先回收 B”的静态场景已经由同一关系层闭合：全局分支保留 A/B 两次返回、两份完整 B 费用；移除 B 的返回来源会同时撤销费用可行性和最终共同用途，增量结果与完整重算一致。

这些结果已接入功能规范化：全局共同证明支持绑定用途；对原任务必需条件，已成立的全局证明可消去其子组资源未知。`NORMALIZATION_VERSION` 升为 `construction-function-normalization-v4`，旧 v3/v2/v1 规范化评价应失效。默认 `QUALITY_VERSION` 仍是旧 v3；真实生产政策、既定参考与旧档迁移没有推进。

本批承接[第四批完整基线](2026-11-09-construction-functional-subsets-recovery-phase4.md)及[正式方案](../plans/2026-11-08-construction-model-formal-optimization-plan.md)第 12 节步骤三、四。先完整读取第四批报告、代码执行细则、preserve-intent-and-execute 和 anti-overengineering；没有重新盘点全项目，没有追索、检查或运行 Pro 辅助演示代码。

## 授权与机械执行书

用户已真实确认新开并继续，指定当前 GPT-6.1-sol、MAX 主进程执行，不用 astra，不启动子代理，只做变化需要的少量静态测试，不运行训练和 CB。新开、实施和这些检查没有待答授权，不重复提问。

修改前交付了四项具体执行内容：

1. 在 `_check_usage/_combine_summary/_map_branches` 中分离原始来源条件与可重查资源结论；验收跨层端点、来源未知保留和原分支替代行为。
2. 在 `PoolRecovery/_recovery_branch` 及返回枚举中增加费用顺序、单事件图和有限整数释放，沿用 `solve_requirements`；验收多边共用总量、重叠池、费用不预借和顺序/预算边界。
3. 升级规范化版本，检查共同证明实际进入功能用途、原任务硬条件与最终 Evaluation，使用明确静态方法；只修本批失败。
4. 语法与行尾检查，更新本报告和两份活动文档，保留现有工作树与并行识别内容。

实施中依据新增用例定位了消费者失效遗漏，并在同一 `relation_index` 范围补齐直接依赖。功能接线中发现单项硬条件仍持有子组未知，按执行项三改为在全局已证明成立时引用该共同证明。没有扩大为识别模块或分配器修改。

## 真实文件与接口变化

| 文件 | 本批实际变化 |
| --- | --- |
| `src/ygo_kito/construction_relations.py` | `PoolRecovery.cost_timing`；`resource_base` 记录资源检查前的四项来源状态，`_usage_input/_usage_result` 在分支变换/合并时重查资源；`_recovery_allocations` 有界枚举每个事件、池、前次消费的整数返回量；`_recovery_branch` 使用单事件节点和有向顺序检查、输出完整 `recovery_returns` 与现有分配器见证；新增实际消费者的返回失效依赖。旧 `reusable_if/recovery_between` 同样走可重查分支。 |
| `src/ygo_kito/construction_layer_flow.py` | 规范化版本 v3→v4；原任务必需子组为 unknown、但 `joint_required` 已 supported 时，硬条件引用完整共同证明。单独的子组评价仍保留其 standalone 状态。 |
| `tests/test_construction_relations.py` | 新增跨用途资源重查、一次返回多边、有限返回量在多个前次消费者/重叠池之间分配、明确费用先后、嵌套返回费用/消费者失效；原返回事件用例更新嵌套全局证明与真实事件顺序环的预期。 |
| `tests/test_construction_functional_flow.py` | 增加全局返回证明到绑定用途、必需条件及最终 Evaluation 的传递；移除返回来源后硬条件失败且分数上界降低。 |
| `docs/development/construction-logic.md`、`docs/plans/MASTER-CHECKLIST.md` | 只新增第五批构筑段及报告链接；既有第四批、历史与并行识别段落保留。 |

上述四个 Python 文件本来就是未跟踪源码，不能把整个文件算作本批新建，也不能从整份 git diff 推断本批差异。没有修改 `construction_quality.py`、`construction_recognition.py`、`construction_inventory.py`、`effect_records.py`、`effect_blocks.py`、`multifactor` 或识别网络。

## 返回与未知的精确边界

返回数量按 `(fact_id, pool_id, before_token)` 分配；同一来源消费连向多个后续端点时只释放一次，不为每条边重复释放。同一事实在多个池中的释放总量受该事实数量约束，同一个前次消费的总释放也不能超过其消费量。共享发动费用保持一个实际激活身份，选取少量返回不会缩减完整费用。

事件先于其全部后续消费者；后续消费者之间可有自己的宿主顺序，不要求它们处于同一阶段。若同一事件被声明在两个连续消费之间执行两次，其事件图可能形成确定顺序环，此时为 missing，不能复制成两个返回。已有宿主 `before` 的矛盾也保持失败。

现有分配器仍只有 deck、activation、resolution、post_resolution 四阶段，deck 保留给存在性条件，因此仍只支持三个消费阶段。超过范围为 `recovery_stage_budget` unknown；返回量/组合枚举仍受 `RelationBudget.matches` 与最多 128 个分支限制，未检查范围保留 unknown。没有以本批授权扩建时间求解器。

派生资源检查保存检查前的 `status/unknown/support_expression/conflicts`，外层只重查这些资源结论；真实来源未知仍进入同一支持表达式。匹配未覆盖、真实数量未知和条件表达式预算不会因为外层补齐一个资源端点就自动变真。原始用途仍有独立评价，共同证明只在它包含的显式共同要求中使用。

返回自身费用消费同池或重叠池，但未指定费用时序时仍是 `recovery_cost_order` unknown。费用的前置证明若还包含未纳入当前分配的返回安排，失败的平铺费用分配不能证明整个前置图失败，保留 `recovery_prerequisite_schedule` unknown；外层已纳入这些费用端点并能完成全局分配时可以消去该未知。本批只为实际闭合的嵌套场景记 supported，未宣称任意深度或全部真实区域转移已完成。

重复或非唯一的具名消费、不完整时序、未枚举的分支与更深费用/返回组合仍可能 unknown。本批使用的是可信来源的 typed 关系契约；尚未将所有原始 recover/move 操作自动变成带控制方、区域、实体同一性与顺序的真实转移事实。

## 实际静态验证

解释器：`C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`。工作目录为实际源码目录，进程内 `PYTHONPATH=src`、`PYTHONUTF8=1`，使用 `-B -m unittest <完整方法路径> -q`。没有 discovery、参数更新、引擎调用或依赖安装。

本批共有 12 个不同业务用例，其最终方法结果通过。保留真实逐组结果，不把早期失败写成整组成功：

- 第一组 5 项：`Ran 5 tests in 0.613s`，退出码 1，其中 3 项通过；费用方法最后一项夹具违反同名三张限制，返回事件方法沿用旧 unknown 预期。修正夹具及确定事件顺序环的业务预期后，这两项在第二组通过。
- 第二组 6 项：`Ran 6 tests in 0.741s`、`OK`，退出码 0。
- 第三组 4 项：`Ran 4 tests in 0.275s`，退出码 1，前三项通过。嵌套费用场景定位了真实闭包失效遗漏；修复后单项重试 `Ran 1 test in 0.222s`，因沿用 unknown 预期而退出码 1，全局安排实际已 supported。随后加强为验证两次真实返回、两份完整费用、来源删除及增量一致的用例。
- 最后两项：上述加强后的嵌套费用方法与已有增量返回方法，`Ran 2 tests in 0.217s`、`OK`，退出码 0。调试输出不计为通过用例，改名和重跑不重复累计。

12 个最终方法如下：

```text
tests.test_construction_relations.SupportAssessmentTests.test_cross_scope_recovery_rechecks_only_resource_unknowns
tests.test_construction_relations.SupportAssessmentTests.test_one_return_event_releases_once_for_multiple_later_edges
tests.test_construction_relations.SupportAssessmentTests.test_shared_return_quantity_is_split_between_prior_consumers
tests.test_construction_relations.SupportAssessmentTests.test_return_cost_order_pays_complete_cost_before_release
tests.test_construction_relations.SupportAssessmentTests.test_return_events_preserve_order_bounds_and_incremental_invalidation
tests.test_construction_functional_flow.FunctionalFlowTests.test_global_return_witness_discharges_bound_required_subgroup
tests.test_construction_relations.SupportAssessmentTests.test_multiple_returns_share_physical_stock_and_check_return_costs
tests.test_construction_relations.SupportAssessmentTests.test_sourced_recovery_between_two_consumptions_and_explicit_order
tests.test_construction_relations.EditComparisonTests.test_incremental_recovery_invalidation_equals_full
tests.test_construction_relations.SupportAssessmentTests.test_joint_all_rechecks_whole_alternatives_without_mixing_branches
tests.test_construction_relations.SupportAssessmentTests.test_partial_supply_retains_pool_alternatives_and_exact_quantity_branches
tests.test_construction_relations.SupportAssessmentTests.test_return_prerequisite_recovery_rechecks_costs_and_invalidates_consumers
```

四个修改 Python 文件通过 `ast.parse` 与逐行行尾空白检查。未无变化重跑前四批整套测试，未运行三项历史 torch 依赖方法；这些缺依赖项没有计入通过。没有训练、CB、原生对局、真实模型推理、CI 或生产权重检查。

本报告与两份活动文档的新增构筑段/链接检查通过。整份活动文档执行 `git diff --check` 时，MASTER-CHECKLIST 第 659、669、699 行的既有识别段报告行尾空白；最后一条是并行识别 M4 段。没有清理或覆盖这些段落，不能把整份 diff 记作全绿。包含该检查和随后 git status 的复合命令返回码由后者决定，不用它声称 diff 检查成功。

## 剩余顺序与安全边界

1. 继续真实转移和复杂返回适配：完整来源、控制方、区域和实体同一性；更深前置返回组合与不完整时序仍须依托当前关系层/整数分配器，超出现有界限保留 unknown，不为有限阶段限制另建求解器。
2. 补齐无操作原始记录自动来源、其他强制影响、更多自动 Main 调用与主题接收链。第四批 `contributes=False` 必需来源契约保留；可选且零正分的来源不因为卡在牌表中就自动采用。未映射限制继续 deferred，不修改并行识别模块来凑完整性。
3. 方向特有用途、互斥换入组合、容量子集选择与共同修复反馈仍未完成。Side 仍是方向资源视图；实际修复净分继续完整重算 Evaluation。
4. 适用语义闭合后才迁移真实宿主政策、指定 2207/2210 参考与明确无参考的 2610，双方同口径重评；再做 schema 2 旧百分制档案迁移，最后退出旧 v3 和层回退。不能只改常量或用 fixture 政策宣布上线。

本批已完成补丁、必要静态验证与文档，形成安全接续边界；没有开始下一类强制影响或生产迁移。没有外部服务阻塞，没有待答问题。此处建议新开聊天并携带本报告；未经用户再次明确确认，不自动创建后续聊天。

## 独立续接摘要

原始目标：目标模型一次生成轴骨架，优化模型在原目标下多轮补齐；候选选择、保留、反馈、学习、gate、重选与恢复都消费同一最终有效分 S。宿主固定政策与参考，候选不能修改它们。预算与暂停不是失败；恢复不重生成目标骨架、优化图或已有候选。

真实源码与状态：源码在 `N:\YGO-Kito\_publish_20261030`，不是外层旧仓库。本批开始核对分支 `codex/optimization-20261031`、HEAD `3f57198`。现有大量未提交修改、删除和未跟踪文件继续保留；本批四个 Python 文件原已未跟踪。本批新增本报告，追加两份活动文档第五批构筑段，未提交推送。并行聊天推进识别模块，MASTER-CHECKLIST 已包含其 M4 段，必须保留，不承接其实现或验证。

可复用状态：第二批已经接通逐候选显式 v4 评价、S 排序、schema 3 pending/恢复、质量偏好 v2、固定参考/gate、重选和课程记录；第三批已有 all/any 分支、重叠整数库存、用途到 V2、来源级影响、Side 隔离及 R/X、墓地调用/双主题和损失/修复组；第四批已有带完整费用的整数供给子集/同池替代、有限连续返回、非计分必需来源与原任务绑定。本第五批变化和精确限制见上文：跨层资源重查、单返回事件/有限多边与多池分配、费用先后、直接消费者失效、部分嵌套费用全局证明、硬条件接线。NORMALIZATION_VERSION 现为 v4，不能复用 v3/v2/v1 规范化缓存。默认 QUALITY_VERSION 仍为旧 v3，生产政策与参考未迁移。

验证：本批 12 个不同业务用例的最终方法结果均通过，具体逐组真实结果和完整方法名见上文；四个修改 Python 文件语法/行尾检查通过。只用已知 Python 3.12、`-B` 和进程内 PYTHONPATH/PYTHONUTF8。旧批整套未重跑，历史 torch 依赖方法仍未运行；没有 CI、训练、CB、引擎或模型推理。MASTER-CHECKLIST 其他段落的既有行尾问题没有借机清理。

未完成步骤以上四项为准。无外部阻塞、无待答授权；主要限制是依然 unknown/deferred 的真实语义范围和未迁移生产配置。下一批先从当前代码的实际依赖继续，不重新盘点项目，不重复旧研究，不把本报告误写成完整上线。

持续不变量：K 是整数实体，E 是计分投入；普通 Main 使用实际 N 的 40E/N，普通 Main/Side 都保留原候选实际 N。完整费用不能按比例冒充。只有显式共同用途联合检查，独立配置不因共享资源自动扣分。墓地相关与堆墓两个主题奖励都保留。未知一致补全，不全部置真。同一已计收益多原因只撤销一次，独立真实收益损失仍保留，S 不再次减损失账本。未定价负担用 unpriced_effect，不新增超 40、空 Extra、伴生、HOPT、LP 或弃牌固定罚款。Side 不支撑 resident/gate，同名折算一次，负增量保留，recoverable 不替代实际修复后的 Evaluation 重算。

禁止重复事项：不 reset/clean/覆盖检出，不恢复已有删除文件，不新建遗漏本地改动的工作树；不追索、检查或运行 Pro 辅助演示代码；不覆盖识别工作或运行其验证；不启动子代理、astra、训练、CB、原生对局或真实模型推理；不动生产权重、暂停文件、课程指针或外部配置，不安装依赖、不提交推送。继续使用现有 `InventoryDependencies`、关系层及 `multifactor.conditions.solve_requirements`，不另建求解器。

用户等待规则：一旦提出新的选择、确认或补充信息问题，暂停全部依赖答案的检索、分析、设计、实施与交付，等待真实回答；工具 accepted、预选、超时、沉默或未回答该问题的新消息不算许可。没有明确独立必要工作时立即交回用户，不通过后台或委派推进。普通回复使用简洁自然段，不加无必要加粗、星号或密集标题。

长任务规则：优先当前聊天继续，允许自动压缩；如果继续压缩可能损害目标、约束、真实文件状态或验证证据，或阶段形成适合交接的安全边界，完成当前非破坏性原子步骤后停止新实施阶段，主动建议新开并给出独立摘要。未经用户明确确认不得创建后续聊天，不声称看到精确上下文占用百分比。

建议下一聊天首条提示：

> 继续 YGO-Kito 构筑模型剩余语义适配，先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-global-recovery-phase5.md`，只有确有必要时才读取其中第四批/第三批链接，承接正式方案第 12 节。实际源码是 `_publish_20261030`，分支 `codex/optimization-20261031`、开始 HEAD `3f57198`；保留全部未提交修改、删除与未跟踪文件和并行识别 M4 工作。第五批已完成跨层资源重查、同一次返回的有限多边/重叠池分配、明确完整费用先后、返回消费者直接失效、可闭合的嵌套费用全局证明及必需条件接线。NORMALIZATION_VERSION=v4，默认 QUALITY_VERSION 仍旧 v3；本批 12 个不同业务用例最终通过、4 个 Python 文件语法/行尾通过。剩余及边界以报告为准，从真实转移/未闭合返回、自动无操作来源与其他强制影响继续，随后方向组合和生产政策/参考/旧档迁移。当前 GPT-6.1-sol、MAX 主进程执行，不用 astra、不启动子代理，只做变化必要的少量静态测试；不训练/CB/引擎/模型推理、不安装依赖、不改并行识别、生产权重、暂停/课程指针或外部配置，不提交推送，不追索/检查/运行 Pro 辅助演示代码。先读代码执行细则、preserve-intent-and-execute 与 anti-overengineering，修改前基于实际代码交付具体机械执行项。当前无待答问题；新问题提出后必须等真实回答并暂停全部依赖工作，不把 accepted、预选、超时或沉默当回答。长任务优先当前聊天继续并允许压缩；压缩风险或适合交接的阶段边界到来时完成原子步骤，主动建议新开并交付完整独立摘要，未经用户确认不得自动创建下一聊天，不声称精确上下文占用百分比。
