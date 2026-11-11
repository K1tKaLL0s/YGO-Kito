# 构筑功能评价：抽卡/加手限制与完整适用条件第九批

日期：2026-11-09（Asia/Hong_Kong）。实际源码为 `N:\YGO-Kito\_publish_20261030`；本批核对分支 `codex/optimization-20261031`、HEAD `3f57198`。沿用现有本地检出，保留全部既有未提交修改、删除和未跟踪文件，没有提交或推送。

## 本批结果

已将原始记录中的 `cannot_draw`、`cannot_add_hand` 接入现有非计分来源、强制影响及最终 Evaluation。己方怪兽区域中的明确持续来源仍需宿主给出该来源的真实适用状态；牌表中有卡不提供场上证明。可选、零正分的来源不会自动采用；原任务必需采用时才按现有契约触发影响。

不能抽卡只撤销实际抽卡用途。不能加入手卡根据实际目的地、起点与接收方定位用途：明确“从卡组”会影响抽卡和检索，不会因此撤销墓地回收或场上回手。多起点混合、未知目的地或接收方继续 unknown。己方、对方、双方是限制作用的玩家范围，与持有限制卡的己方场上状态分别保留。

完整限制契约由 `_restriction_contract` 提供给 `_record_applicability`、`_mapped_restriction` 和 `_bind_mandatory_impacts`。对原始粗标签，仅接受本批有限、完整匹配的原文；未解析例外、卡片类别限定和额外适用条件不能仅凭 kind 解除未知。已有明确结构字段也必须同时给出作用方、条件与有效时间范围，且不能携带本适配器未处理的选择或例外。

已有召唤锁同步保留实际起点和行动控制方。`extra_fusion_only` 不再仅凭“同调/超量/连接召唤”名称就对明确墓地起点扣除；从额外卡组进行的泛化特殊召唤仍不能据此确定其融合类型。只有已实际接到库存材料检查、原文完整的卡级融合素材禁用可保持已映射；尚未有用途适配的固有通常/特殊召唤禁用及条件不完整的素材限制继续 deferred。

整回合限制不被先后顺序解除。发动后限制复用现有有来源的 `before` 约束，支持传递顺序；缺少顺序或出现相互矛盾的顺序时保留 unknown。没有新建求解器、来源框架或评分入口。方向来源仅作用于同方向用途，负增量保留。

`NORMALIZATION_VERSION` 升为 `construction-function-normalization-v8`。缓存与恢复继续消费同一个常量，v7/v6/v5/v4/v3/v2/v1 评价不再满足当前规范化版本绑定。默认 `QUALITY_VERSION` 仍旧 v3，生产政策、指定参考、旧档迁移和旧层回退退出均未开始。

本批承接[第八批跨区生命周期报告](2026-11-09-construction-functional-zone-lifecycle-phase8.md)和[正式方案](../current/construction-scoring.md)第 12 节步骤三、四。第八批的跨区物理槽位、有限牌组端点、离场除外及成功/失败证据继续复用，没有重做。

## 授权、执行及真实文件状态

本聊天由用户真实确认新开并继续，按已确认的 GPT-6.1-sol、MAX 主进程路由要求实施，没有启动子代理或 astra。当前没有待答问题。已读取代码执行细则、preserve-intent-and-execute 和 anti-overengineering，并在修改前根据实际源码交付四步机械执行书。

本批修改四个 Python 文件，均在本批开始前已经是未跟踪文件，不能将其整份源码记为本批新建。两份活动文档此前均已修改。本报告为本批新增。

| 文件 | 本批实际变化 |
| --- | --- |
| `src/ygo_kito/construction_relations.py` | 新增有限完整限制契约；扩展纯限制来源的场上适用端口。在完整纯限制契约成立时清除旧的未解析结算标记，额外条件仍保留未知。 |
| `src/ygo_kito/construction_layer_flow.py` | 映射判定消费完整契约；抽卡/加手影响定位实际用途、接收方及起点；已有召唤锁保持实际起点/行动方；消费传递顺序并保留矛盾顺序未知；规范化版本 v7→v8。 |
| `tests/test_construction_relations.py` | 新增 1 个业务方法，覆盖原始限制契约、场上状态、原文、作用方、时限及未解析条件和未接线固有限制。 |
| `tests/test_construction_functional_flow.py` | 新增 5 个业务方法；既有未映射限制用例改为带未解析例外的真实句子，版本断言更新到 v8。 |
| `docs/development/construction-logic.md`、`docs/plans/MASTER-CHECKLIST.md` | 增补本批入口和真实状态，保留历史及并行识别段落。 |

未修改原始效果识别、`construction_inventory.py`、`multifactor` 整数分配器、质量计分器、模型结构、并行识别 M4/M5、生产权重、暂停文件、课程指针或外部配置。没有训练、CB、原生对局、真实模型推理、CI、依赖安装、提交或推送。不追索、检查或运行 Pro 辅助演示代码。

## 数据流与适用边界

原始粗限制句的有限完整适配接受“这张卡在怪兽区域存在”“这个效果发动后”“发动这个效果的回合”三个明确前缀及本批明确动作。原始记录完整保留；适配结果不回写识别层。结构记录的默认时长不能覆盖原文明确给出的整回合/发动后范围。完整结构契约可被直接消费，但来源自己的触发、费用、次数和其他未知仍由既有关系层判断；识别出限制契约不等于证明其来源可用。

纯持续限制来源必须没有操作、费用、对象或次数声明，且全部限制均满足本批完整契约，才获得 `effect_applicability` presence 端口。端口标识来源卡和己方怪兽区域状态；没有宿主状态时，该来源继续 unknown。只有满足这些条件的完整纯限制记录会清除旧解析器残留的 `unparsed_resolution_or_restriction`，不据此清除其他来源缺口。

对加手用途，已知目的地为 hand 才能确定命中；检索、回收、回手等动作若目的地缺失，只建立未知影响。若限制带起点范围，目标的全部明确起点落在该范围内才能确定命中；完全不相交不受影响，混合或缺失起点保留 unknown。接收方读取用途的 owner；召唤及攻击锁读取行动控制方，不用所有权替代行动控制。

强制影响仍通过 `UseImpact` 作用于来源、用途和已有基础/主题通道。没有全局扣分、独立罚款或重复撤销收益。原关系层的访问前提可以继续成立，但被撤销的必需功能用途会在最终 Evaluation 的用途硬条件中失败；其原始关系前提与最终用途存活分别列示，最终 gate 检查全部硬条件。

Side 方向用例复用了原始规范化来源明细，再用固定静态方向视图检查影响范围；没有把它描述为真实换入对局。更复杂的容量子集、互斥换入、完整修复反馈仍未闭合。

本批不增加通用中文限制解析器。抽卡阶段例外、指定卡类加手禁用、额外指示物条件、泛化特殊召唤的融合类型、尚未适配的固有限制等继续 unknown/deferred。没有为了完成映射把未知统一置真。

## 实际静态验证

解释器为 `C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`，工作目录为实际源码目录。只在进程内设置 `PYTHONPATH=src`、`PYTHONUTF8=1`，用 `-B -m unittest <完整方法路径> -q` 运行具体方法；没有 discovery、依赖安装、模型或原生引擎运行。

14 个不同静态业务方法取得最终通过结果，6 个新增、8 个直接受影响的既有方法。实际逐组结果如下，重复运行不累计不同方法数：

- 首组 5 项新增：`Ran 5 tests in 0.633s`，退出码 1，4 项通过、1 项失败。完整纯限制来源仍携带旧解析器的未解析结算标记。
- 将该标记的清除限定在完整纯限制适用契约后，同组 5 项：`Ran 5 tests in 0.735s`、`OK`，退出码 0。
- 加入原始加手/方向用例及既有回归后，主体 14 项：`Ran 14 tests in 3.193s`，退出码 1，13 项通过、1 项失败。新增断言误把原始关系前提的状态当作最终用途硬条件；前提可以存在，而用途因强制影响失效。
- 将断言定位到原任务绑定的实际必需抽卡用途，并使方向夹具来源卡号与原始明细一致后，2 项原始抽卡/加手 Evaluation 用例：`Ran 2 tests in 0.615s`、`OK`，退出码 0。没有修改计分器来迁就断言。
- 收紧卡级固有限制映射，增加未接线固有通常召唤限制的原始记录断言后，原始限制契约和既有未映射边界 2 项：`Ran 2 tests in 0.453s`、`OK`，退出码 0。

不同方法清单：

```text
tests.test_construction_relations.SupportAssessmentTests.test_raw_hand_locks_require_complete_sourced_applicability
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_draw_lock_reaches_required_adoption_and_evaluation
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_add_hand_lock_reaches_evaluation_and_direction_scope
tests.test_construction_functional_flow.FunctionalFlowTests.test_add_hand_lock_preserves_origin_receiver_and_unknowns
tests.test_construction_functional_flow.FunctionalFlowTests.test_hand_lock_order_preserves_transitive_and_whole_turn_conditions
tests.test_construction_functional_flow.FunctionalFlowTests.test_fusion_only_impact_uses_actual_origin_and_actor
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_non_scoring_adoption_binds_impact_and_source_removal
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_non_scoring_adoption_preserves_full_cost_and_unmapped_restrictions
tests.test_construction_functional_flow.FunctionalFlowTests.test_extra_summon_impact_keeps_origin_controller_and_condition_unknowns
tests.test_construction_functional_flow.FunctionalFlowTests.test_non_scoring_extra_lock_keeps_directional_negative_delta
tests.test_construction_functional_flow.FunctionalFlowTests.test_mandatory_restriction_mapping_obeys_whole_turn_and_known_order
tests.test_construction_functional_flow.FunctionalFlowTests.test_leave_banish_lifecycle_reaches_bound_evaluation
tests.test_construction_functional_flow.FunctionalFlowTests.test_global_return_witness_discharges_bound_required_subgroup
tests.test_construction_relations.SupportAssessmentTests.test_raw_no_operation_source_preserves_scope_and_field_applicability
```

新增用例实际覆盖完整原始作用方/条件/原文、额外条件未知、来源移除或仅放 Side、可选零收益不自动采用、最终必需功能被撤销、卡组加手与墓地/场上加手区别、多起点/接收方未知、己方/对方/双方、先攻负增量、发动后传递顺序、整回合限制、矛盾顺序以及融合锁的真实起点和行动方。既有离场生命周期与全局返回硬条件用例通过。

最后代码修改后，四个 Python 文件的 `ast.parse` 和逐行行尾空白检查通过。缓存/恢复的版本判断已定点核对，仍引用同一 `NORMALIZATION_VERSION`；没有另跑恢复或训练验证。

本报告与两份活动文档新增段落的行尾、相对链接检查通过，14 条方法引用、v8 规范化、默认旧 v3 及历史/并行段落存在性检查通过。最终七条目标路径状态、分支和 HEAD 已核对；未清理历史文档或承接并行实现检查。

## 剩余工作及停止边界

1. 继续适配其他真实强制限制、固有通常/特殊召唤限制的实际用途、条件素材禁用及完整适用条件。不能将本批有限原文匹配扩成粗标签全局规则；原始识别层与并行识别不承接。本批的纯持续抽卡/加手限制及已有完整契约继续复用。
2. 按真实需要补更广控制/选择范围、复杂返回费用、混合旧式/实体返回、更多阶段和牌组内顺序。第八批的有限跨区生命周期不重建；三消费阶段和单张单次端点之外继续保留既有边界。
3. 完成更多自动 Main 调用、主题接收、方向用途、互斥换入组合、容量子集选择和共同修复反馈。Side 是资源视图，实际修复净分仍须完整重算 Evaluation。
4. 适用语义闭合后再迁移真实宿主政策和指定 2207/2210 参考，明确 2610 无参考，双方同口径重评；然后迁移 schema 2 旧百分制档案，最后退出旧 v3 与层回退。不能只改常量或用 fixture 政策宣布上线。

本批两类限制、映射完整性、必要静态验证和文档形成可独立接续的安全边界，未启动下一类限制或生产迁移。无外部阻塞和待答问题。按长任务规则建议新开聊天继续；本聊天创建时的确认只授权本次，未经用户再次真实确认不创建下一聊天。

## 独立续接摘要

原始目标：目标模型一次生成轴骨架，优化模型在原目标下多轮补齐；候选选择、保留、反馈、学习、gate、重选、恢复消费同一最终有效分 S。宿主固定政策与参考，候选不能修改。预算/暂停不是失败，恢复不重生成目标骨架、优化图或已有候选。

真实源码与状态：继续使用 `N:\YGO-Kito\_publish_20261030` 现有本地检出，分支 `codex/optimization-20261031`、核对 HEAD `3f57198`。保留全部既有未提交修改、删除和未跟踪文件。本批改动四个原已未跟踪 Python 文件：`construction_relations.py`、`construction_layer_flow.py`、`test_construction_relations.py`、`test_construction_functional_flow.py`；增补两份原已修改的活动文档，新增本报告。`construction_inventory.py` 未在本批修改。并行 M4/M5 的实现和验证均不承接，不覆盖文件；不 reset/clean，不恢复原有删除，不新建遗漏本地改动的工作树，没有提交推送。

可复用已有实现：前八批已接通显式 v4 候选评价/S 排序、schema 3 pending/恢复、偏好 v2、固定参考/gate、重选/课程记录、all/any 分支、整数库存、完整费用子集、全局有限返回、来源级影响、Side 隔离/R/X、墓地与堆墓双主题、共同用途及原任务绑定、非计分必需采用、损失和修复解释。第八批按实际槽位和阶段区域复用原 `multifactor.conditions.solve_requirements`；`leave_field_banish` 限本效果召唤实体，成功/失败保留声明/实际去向、槽位、原召唤和规则来源，重复未来 banish 投影不计独立正分。单张单次明确卡组端点可用，多张/多次仅闭合成员资格，精确位置 unknown；混合旧式/实体返回及超过三消费阶段仍 unknown。完整具名特殊召唤沿用原库存选择语法，未知排除不放宽。

本第九批新增：`_restriction_contract` 在原始限制层之后提供有限完整契约，供场上适用、映射及强制影响共用。纯持续 `cannot_draw`、`cannot_add_hand` 可从原始记录自动接到非计分来源与最终 Evaluation；作用玩家与来源己方场上状态分开，访问事实仍须来源支持。抽卡只定位 draw，加手按真实 hand 目的地、起点及接收方定位；未知/混合仍 unknown。已有召唤锁保留真实起点和行动方。整回合与发动后分开，既有 before 约束支持传递顺序，矛盾顺序未知。未接线的固有通常/特殊召唤限制继续 deferred。可选零正分不自动采用，必需采用触发影响；受损的必需功能在最终用途硬条件失败，即使原关系访问前提仍满足。没有新增求解器、独立评分入口或固定罚款。

版本及验证：`NORMALIZATION_VERSION=construction-function-normalization-v8`，旧 v7/v6/v5/v4/v3/v2/v1 不可复用；默认 `QUALITY_VERSION` 仍旧 v3。14 个不同静态业务方法最终通过（6 新增、8 既有），四个 Python 文件语法/行尾通过；全部方法名及真实逐组成功/失败结果见上文。首组曾因旧未解析结算标记失败 1 项，修复完整纯限制来源后通过；主体组曾有 1 项断言定位错误，改验最终必需用途后通过。未运行 discovery、整套、CI、训练、CB、引擎、真实模型推理或并行识别验证，无依赖安装及生产参数更新。

下一步：以上四项剩余工作为准，优先其他真实强制限制与完整条件、尚未接线的固有召唤/条件素材实际用途，再扩复杂控制/返回和完整调用/主题/方向组合。不得重建无操作来源、实体生命周期或分配器，不重新盘点项目、不重做旧研究。当前无待答问题及外部阻塞，下一阶段尚未启动。

持续不变量：K 为整数实体，E 为计分投入；普通 Main 用实际 N 的 40E/N，Main/Side 保留原候选实际 N。完整费用不按比例缩减。仅显式共同用途联合检查，独立配置不因共享资源自动扣分；墓地与堆墓主题保留。未知按一致补全，不全部置真。同一收益多原因只撤销一次，独立收益损失保留，S 不再次扣损失账本。未定价负担用 unpriced_effect，不新增超 40、空 Extra、伴生、HOPT、LP 或弃牌固定罚款。Side 不支持 resident/gate，同名折算一次，负增量保留；recoverable 不能替代完整修复 Evaluation 重算。

执行约束：沿用用户已确认的 GPT-6.1-sol、MAX 主进程要求，不用 astra、不启动子代理。先读 `C:\Users\27499\.codex\instructions\code-work.md`、preserve-intent-and-execute、anti-overengineering，修改前交付具体机械执行项，非 UI 已授权工作可继续。只做变化必需的少量具体静态测试，不 discovery/装依赖/训练/CB/引擎/模型推理，不改并行识别、生产权重、暂停文件、课程指针或外部配置，不提交推送。Pro 辅助演示代码不追索、不检查、不运行。

等待规则：提出任何新选择、确认或补充问题后，必须等待真实回答，暂停全部依赖答案的检索、分析、选型、设计、实施和交付。工具 accepted、预选、超时、沉默或未回答该问题的新消息均不算许可；没有明确独立的必要工作即交还用户，不通过委派或后台推进。

长任务交接规则：优先在当前聊天继续并允许自动压缩。若继续压缩会损害准确性、约束保真、真实文件状态或验证质量，或形成适合交接的安全阶段边界，先完成当前非破坏性原子步骤，不启动新阶段，主动建议新开并给出可独立执行的完整摘要。未经用户再次真实确认不得创建下一聊天；新聊天首条提示继续重申本规则。不声称精确上下文占用百分比。普通回复用简洁自然段，不加无必要星号装饰或密集标题。

建议下一聊天首条提示：

> 继续 YGO-Kito 构筑模型剩余语义适配。先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-hand-restrictions-phase9.md`，承接正式方案第 12 节；只在理解旧接线确有必要时读取更早报告。实际源码为 `_publish_20261030`，分支 `codex/optimization-20261031`、第九批核对 HEAD `3f57198`，保留全部未提交修改、删除、未跟踪文件及并行 M4/M5，不新建遗漏改动的工作树。第九批已将原始持续抽卡/加手限制的完整作用方、时限、适用状态、真实起点/目的地/接收方接到非计分来源、强制影响和最终 Evaluation；已有召唤锁保留实际起点/行动方，before 支持传递顺序、矛盾顺序 unknown。可选零收益不自动采用，必需功能被撤销会在最终用途硬条件失败；原始关系前提可另行保持 satisfied。未接线的固有通常/特殊召唤及条件素材限制继续 deferred，不凭 kind 清未知。第八批有限实体生命周期、离场除外和位置边界继续复用，不重建来源或分配器。NORMALIZATION_VERSION=v8，默认 QUALITY_VERSION 仍旧 v3；14 个不同静态业务方法最终通过、4 个 Python 文件语法/行尾通过。下一步继续其他真实强制限制和完整条件、固有召唤/条件素材实际用途，再补复杂控制/返回、调用/主题/方向组合和生产政策、参考、旧档迁移。按已确认的 GPT-6.1-sol、MAX 主进程执行，不用 astra、不启动子代理；先读代码执行细则及两项指定技能，修改前交付具体机械执行项。只运行变化必需的少量具体静态测试，不 discovery/装依赖/训练/CB/引擎/模型推理，不改并行识别、权重、暂停/课程指针或外部配置，不提交推送，不追索/检查/运行 Pro 辅助演示代码。当前无待答问题；一旦提问必须等待真实回答并暂停全部依赖工作，accepted、预选、超时和沉默都不是回答。长任务优先当前聊天持续推进并允许自动压缩；出现准确性风险或安全阶段边界时完成当前原子步骤，主动建议新开并交付完整独立摘要，未经用户再次真实确认不得创建后续聊天；不声称精确上下文占用百分比。
