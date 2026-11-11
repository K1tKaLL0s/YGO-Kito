# 构筑功能评价：固有召唤与条件素材限制第十批

日期：2026-11-09（Asia/Hong_Kong）。实际源码为 `N:\YGO-Kito\_publish_20261030`，本批核对分支 `codex/optimization-20261031`、HEAD `3f57198`。沿用现有本地检出，保留全部既有未提交修改、删除和未跟踪文件；没有提交或推送。

## 本批结果

固有通常召唤、特殊召唤禁用已接到实际被召唤实体的库存选择，以及本卡的召唤成功触发检查。卡本身的禁用不会撤销其无关的抽卡、送墓、回收或费用用途。完整禁止特召的实体不能由调用效果提供特召成功触发；即使宿主另供召唤事件，规范化用途仍保留已知禁用。通常或特殊召唤的替代触发保留合法一支，不要求两种召唤同时成立。

融合素材不再按粗标签全局排除。`InventoryDependencies._check` 先确认实际素材用途和目标卡召唤类型，再检查候选自身完整限制及实际区域。无条件融合素材禁用只排除融合素材候选；手卡/墓地区域条件按明确起点判断。打印素材要求的 `origin=material` 不提供区域证明，场上/怪兽区域条件也不凭库存推定表侧适用状态，继续 unknown。

库存继续使用原有不同实体匹配，分别计算确定候选与可能候选。确定候选足够时，未选择的未知候选不阻止库存通过；仅可能候选能补齐时返回 unknown；连全部可能候选也不足才报告 missing。完整费用和素材仍共享原有不同实体检查，不缩减数量，不新增求解器。

完整的玩家通常召唤、明确括号盖放及攻击宣言限制接入既有非计分来源、必需采用、强制影响和最终 Evaluation。原始 `cannot_summon`、`cannot_set`、`cannot_attack` 只有完整原文符合对应动作时才能转成有限契约；不把别名本身当作充分条件。来源己方场上状态与限制作用玩家分开，实际行动控制方决定命中。结构化通召起点限制保留实际起点，混合起点未知；整回合和发动后继续复用第九批时限及 before 顺序。

`NORMALIZATION_VERSION` 升为 `construction-function-normalization-v9`。默认 `QUALITY_VERSION` 仍为 `construction-quality-evaluation-v3`。旧 v8 及更早规范化评价不能复用到当前绑定；生产政策、2207/2210 参考、2610 显式无参考和旧档迁移仍未开始。

本批承接[第九批报告](2026-11-09-construction-functional-hand-restrictions-phase9.md)与[正式方案](../plans/2026-11-08-construction-model-formal-optimization-plan.md)第 12 节。第八批实体生命周期、离场除外与第九批抽卡/加手限制继续复用。

## 原始记录、数据流与边界

原始效果识别和卡级字典保持原版本。构筑消费端从现有 `effect_blocks(...).card_restrictions` 补入已被字典观察、但此前未到达功能规范化的卡级特召禁用。字典原来可能只给短句，适配器会保留 `observed_source`，以实际完整句作为 `source` 校验；相邻未解析前言还会保留 `context_source` 与未知原因。跨句例外不能被第一句裸禁用抹掉。已识别次数前言和完整素材式继续复用现有记录，不重写识别层。

`_restriction_contract` 同时供映射判定及候选检查使用。固有限制必须为卡自身范围、支持的有效期及有限完整原文，不能携带未处理的选择、例外、作用方或未知。区域条件契约保留 `from_zones` 和具体条件；候选检查没有取得场上适用状态时仍未知。附带其他未解析召唤手续或跨句条件时也不硬排除。

`specs` 的修改只扩大已观察操作的消费：完整通常/上级召唤选择沿用原有选择语法，无法取得完整对象、数量或区域的操作仍有未知选择项。本批没有新增通常召唤规则生成器，也没有把未识别召唤手续变成可用入口。

`candidate_status` 定位当前候选实体、用途、起点和实际目标；`summon_trigger_check` 核对本卡的明确召唤成功事件。前者用于库存选择、已识别实体转移和接收方触发，后者接到规范化的库存端口及用途自身条件。原有 `ResourceTransfer` 保持生命周期契约；候选成员中仍有未知限制时，精确实体成员资格可以继续未知，没有把可能成员伪装成确定成员。

`_check` 的 `restriction_checks` 保留每个候选的完整限制、契约、用途及判断；`confirmed_available`、`confirmed_shortfall` 区分确定库存和可能库存。只有实际需要未知候选补齐时，`unknown_restrictions` 才进入库存未决及修复输入。确定替代已足够时，该列表为空，但逐候选原始记录仍保留。整数实体分配不变，同一张实体不能占两个槽位。

卡级攻击限制若仍未说明具体哪个效果发动、完整作用方或适用事件，会保留在构筑记录中并继续 deferred。没有因为顶层原始字典与效果记录之间曾缺接线而丢掉它，也没有将其套到全部效果。指定召唤手续、指定素材对象/例外、其他类条件素材禁用、未解析控制/位置状态继续按实际缺口保留 unknown/deferred。

## 执行和真实文件状态

用户已在新开前真实确认继续实施，沿用 GPT-6.1-sol、MAX 主进程要求；没有启动子代理或 astra。本批开始无待答问题，也未提出新的选择或确认问题。已读取代码执行细则、preserve-intent-and-execute、anti-overengineering 和完整第九批报告，修改前交付了四步具体机械执行书。

以下六个 Python 文件在本批开始前均已是未跟踪文件，不能把整份源码记为本批新建。两份活动文档此前已修改，本报告为新增。

| 文件 | 本批实际变化 |
| --- | --- |
| `src/ygo_kito/construction_inventory.py` | 补入原始卡级限制并核对完整句及前言；候选用途/起点检查；本卡召唤触发检查；确定/可能候选复用原匹配；未知限制进入原库存与修复结果。 |
| `src/ygo_kito/construction_relations.py` | 扩展有限完整限制契约；只在完整原文成立时适配召唤/盖放/攻击别名；实体转移保留候选禁用或未知。 |
| `src/ygo_kito/construction_layer_flow.py` | 映射消费统一契约；检查被召唤实体及本卡召唤触发；传递明确正常/特殊召唤事件；通常召唤锁保留起点和盖放范围；规范化 v8→v9。 |
| `tests/test_construction_inventory.py` | 新增 2 个业务方法，覆盖本卡/接收方、完整及跨句例外、区域条件、召唤类型、确定替代和实体数量。 |
| `tests/test_construction_relations.py` | 新增 1 个业务方法；既有第九批固有通召断言更新为已映射，原始关系事实仍单独保留限制未决。 |
| `tests/test_construction_functional_flow.py` | 新增 3 个业务方法，覆盖真实原始记录至最终 Evaluation、触发阻断、素材未知/失败、行动方及混合起点；版本断言更新为 v9。 |
| `docs/development/construction-logic.md`、`docs/plans/MASTER-CHECKLIST.md` | 增补本批当前入口，不改历史结果和并行识别段落。 |

未改原始效果识别、并行 M4/M5、`multifactor.conditions.solve_requirements`、质量计分器、模型结构、生产权重、暂停文件、课程指针或外部配置。没有依赖安装、discovery、CI、训练、CB、原生对局或真实模型推理。不追索、检查或运行 Pro 辅助演示代码。未创建工作树、清理文件、恢复既有删除、提交或推送。

## 实际静态验证

解释器为 `C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`；工作目录为实际源码目录。只在进程内设置 `PYTHONPATH=src`、`PYTHONUTF8=1`，以 `-B -m unittest <完整方法路径> -q` 调用具体静态方法。

14 个不同业务方法取得通过结果，6 个新增、8 个直接受影响的既有方法。实际逐组记录如下，重复不累计不同方法数：

- 首组新增库存和原始契约 3 项：`Ran 3 tests in 0.123s`，退出码 1；2 个库存方法通过，原始契约方法的 3 个盖放子场景失败。原因是同一完整原文还会被原始字典标记为 `cannot_set`，尚未进入有限别名适配。
- 加入该完整原文别名后，原始契约与 3 个新增端到端方法共 4 项：`Ran 4 tests in 2.213s`、`OK`，退出码 0。
- 补齐跨句例外、确定/可能库存及结构边界后，14 项主体：`Ran 14 tests in 2.301s`、`OK`，退出码 0。
- 随后补入本卡召唤成功事件禁用检查，并保留顶层未绑定攻击限制；只重跑直接受影响的 5 项：`Ran 5 tests in 0.957s`、`OK`，退出码 0。包含本卡/接收方、原始完整契约、最终召唤用途、既有离场生命周期和全局返回。
- 最后增加结构化通召锁的明确/不相交/混合起点断言，单独方法：`Ran 1 test in 0.321s`、`OK`，退出码 0。

不同方法清单：

```text
tests.test_construction_inventory.InventoryDependencyTests.test_intrinsic_summon_prohibitions_check_the_recipient_and_keep_other_uses
tests.test_construction_inventory.InventoryDependencyTests.test_material_prohibition_preserves_summon_kind_zone_and_uncertain_alternatives
tests.test_construction_relations.SupportAssessmentTests.test_raw_summon_and_attack_locks_require_complete_player_and_timing
tests.test_construction_functional_flow.FunctionalFlowTests.test_intrinsic_recipient_prohibition_reaches_required_summon_and_trigger
tests.test_construction_functional_flow.FunctionalFlowTests.test_conditional_fusion_material_reaches_evaluation_without_global_exclusion
tests.test_construction_functional_flow.FunctionalFlowTests.test_raw_normal_and_attack_locks_apply_only_to_matching_actor_and_use
tests.test_construction_inventory.InventoryDependencyTests.test_all_selected_extra_materials_checked_without_fixed_task_card
tests.test_construction_inventory.InventoryDependencyTests.test_overlapping_material_slots_cannot_reuse_one_physical_copy
tests.test_construction_relations.SupportAssessmentTests.test_raw_hand_locks_require_complete_sourced_applicability
tests.test_construction_functional_flow.FunctionalFlowTests.test_mandatory_restriction_mapping_obeys_whole_turn_and_known_order
tests.test_construction_functional_flow.FunctionalFlowTests.test_hand_lock_order_preserves_transitive_and_whole_turn_conditions
tests.test_construction_functional_flow.FunctionalFlowTests.test_leave_banish_lifecycle_reaches_bound_evaluation
tests.test_construction_functional_flow.FunctionalFlowTests.test_global_return_witness_discharges_bound_required_subgroup
tests.test_construction_functional_flow.FunctionalFlowTests.test_fusion_only_impact_uses_actual_origin_and_actor
```

六个 Python 文件的 `ast.parse` 和逐行行尾空白检查通过；最后的单方法新增断言另做同样静态检查。没有整套测试、恢复运行、引擎或训练检查。规范化继续使用同一个版本常量，不修改默认质量版本。

## 剩余工作与本批边界

1. 继续其他真实强制限制和完整适用条件，包括尚未绑定具体效果的卡级发动攻击锁、特殊召唤本卡回合的限制、指定召唤手续与例外，以及指定素材对象、其他素材类型、场上适用状态。不能凭粗标签全局排除，不能为了已映射而解除未知。
2. 保留本批确定/可能候选分层，再按真实需求补足未知候选参与实体转移时的精确适用及完整选择。现有有限跨区生命周期、三消费阶段与明确牌组端点继续复用，不重建求解器或来源框架。
3. 继续更广控制/选择范围、复杂返回费用、混合旧式/实体返回、更多阶段和顺序，再闭合自动 Main 调用、主题接收、方向用途、互斥换入、容量子集和共同修复反馈。Side 是资源视图，实际修复净分仍需完整重算 Evaluation。
4. 适用语义闭合后再迁移真实宿主政策和指定 2207/2210 参考，明确 2610 无参考并双方同口径重评；然后迁移 schema 2 旧百分制档案，最后退出旧 v3 和层回退。不能仅改常量或用 fixture 政策宣布生产上线。

本批有限召唤/素材适配、必要静态验证与文档形成可独立接续的安全边界。无外部阻塞和待答问题。未启动下一类限制或生产迁移；按长任务规则建议新开聊天继续，未经用户再次真实确认不创建下一聊天。

## 独立续接摘要

原始目标：目标模型一次生成轴骨架，优化模型在原目标下多轮补齐；候选选择、保留、反馈、学习、gate、重选、恢复消费同一最终有效分 S。宿主固定政策与参考，候选不能修改。预算/暂停不是失败，恢复不重生成目标骨架、优化图或已有候选。

真实源码与状态：继续使用 `N:\YGO-Kito\_publish_20261030` 现有本地检出，分支 `codex/optimization-20261031`，本批核对 HEAD `3f57198`。保留全部既有未提交修改、删除和未跟踪文件。本批修改三个原已未跟踪源码 `construction_inventory.py`、`construction_relations.py`、`construction_layer_flow.py`，三个原已未跟踪测试 `test_construction_inventory.py`、`test_construction_relations.py`、`test_construction_functional_flow.py`；增补两份原已修改活动文档，新增本报告。没有提交推送或清理。并行 M4/M5 的实现及验证不承接、不覆盖；不 reset/clean、不恢复既有删除、不新建遗漏本地改动的工作树。

已有成果：前九批已接通显式 v4 候选评价/S 排序、schema 3 pending/恢复、偏好 v2、固定参考/gate、重选/课程记录、all/any 分支、整数库存、完整费用子集、全局有限返回、来源级影响、Side 隔离/R/X、墓地与堆墓双主题、共同用途及原任务绑定、非计分必需采用和损失/修复解释。第八批有限实体生命周期、离场除外和明确单张单次牌组端点继续复用原 `multifactor.conditions.solve_requirements`，混合旧式/实体返回及超出三消费阶段仍 unknown。第九批完整抽卡/加手限制区分作用玩家、来源场上状态、真实起点/目的地/接收方；before 支持传递顺序，矛盾顺序未知。可选零收益来源不自动采用，必需功能被撤销会在最终用途硬条件失败，原始关系前提可另行成立。

本第十批新增：统一有限契约适配固有通召/特召及无条件或明确区域的融合素材禁用；从原始卡级字典补入特召禁用，核对完整句及未解析前言，保留短观察来源与跨句上下文。候选只按其实际召唤/素材用途检查，融合素材不再全局黑名单。库存复用原不同实体匹配，确定候选够用即通过，仅可能候选补足则 unknown，全可能不足才 missing；完整逐候选记录与实际需要的未知进入库存/修复结果。本卡和被调用实体分别检查，禁止的召唤不能提供成功触发，通常/特殊替代仍保留可行分支。完整玩家通召/明确括号盖放/攻击限制消费实际行动方、起点、持续/整回合/发动后范围及已有顺序；重复别名不会重复撤销收益。未绑定具体效果的顶层攻击限制保留 deferred，没有丢掉。没有新增求解器、评分入口或固定罚款，原始识别层不变。

版本与真实验证：`NORMALIZATION_VERSION=construction-function-normalization-v9`，旧 v8/v7/v6/v5/v4/v3/v2/v1 不能复用到当前规范化绑定；默认 `QUALITY_VERSION` 仍旧 v3。14 个不同静态业务方法取得通过结果，6 个新增、8 个既有；最后源码补丁后的直接受影响 5 项及最后补充起点断言的 1 项通过。首组曾有原始盖放别名的 1 个方法、3 个子场景失败，适配后通过，不能写成首组首次全通过。六个 Python 文件语法/行尾通过，全部方法名及真实逐组结果见本报告。没有 discovery、整套、CI、依赖安装、训练、CB、引擎或真实模型推理，也没有并行识别验证。

下一步：以上四项剩余工作为准，优先其他真实限制、指定召唤及素材完整条件，再扩控制/返回、调用/主题/方向组合与生产迁移。有限召唤/区域素材适配已闭合，场上适用状态、指定例外、其他素材类、精确未知转移成员等保留明确未决。没有外部阻塞或待答问题，下一实施阶段尚未启动。

持续不变量：K 为整数实体，E 为计分投入；普通 Main 按原候选实际 N 使用 40E/N，Main/Side 保留 N。完整费用不按比例缩减。仅显式共同用途联合检查，独立配置不因共享资源自动扣分；墓地与堆墓主题保留。未知按一致补全，不全部置真。同一收益多原因只撤销一次，独立收益损失保留，S 不再次扣损失账本。未定价负担记 unpriced_effect，不新增超 40、空 Extra、伴生、HOPT、LP 或弃牌固定罚款。Side 不支持 resident/gate，同名折算一次，负增量保留；recoverable 不能代替完整修复 Evaluation 重算。

执行约束：按用户已确认的 GPT-6.1-sol、MAX 主进程要求执行，不用 astra、不启动子代理。代码规划/修改前读 `C:\Users\27499\.codex\instructions\code-work.md`、preserve-intent-and-execute 和 anti-overengineering，依据实际代码交付具体机械执行项，再继续已授权非 UI 工作。只做变化必需的少量具体静态测试，不 discovery/装依赖/训练/CB/引擎/模型推理，不改并行识别、生产权重、暂停/课程指针或外部配置，不提交推送。Pro 辅助演示代码不追索、不检查、不运行。

等待规则：提出任何新选择、确认或补充问题后，必须等待真实回答，暂停全部依赖答案的检索、分析、选型、设计、实施及交付。工具 accepted、预选、超时、沉默或未回答该问题的新消息不算许可。没有明确独立必要工作即交还用户，不通过后台或委派继续。

长任务交接规则：优先在当前聊天继续并允许自动压缩。若继续压缩可能损害准确性、约束保真、文件状态或验证质量，或形成适合交接的安全阶段边界，先完成当前非破坏性原子步骤，不启动新实施阶段，主动建议新开并给出独立完整摘要。未经用户再次真实确认不得创建后续聊天，新聊天首条提示继续重申本规则。不声称精确上下文占用百分比。普通回复用简洁自然段，无无必要加粗、星号装饰或密集标题。

建议下一聊天首条提示：

> 继续 YGO-Kito 构筑模型剩余语义适配。先完整读取 `N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-09-construction-functional-summon-material-restrictions-phase10.md`，承接正式方案第 12 节；只在理解旧接线确有必要时读取更早报告。实际源码 `_publish_20261030`、分支 `codex/optimization-20261031`、第十批核对 HEAD `3f57198`，保留全部未提交修改、删除、未跟踪文件和并行 M4/M5，不新建遗漏改动的工作树。第十批把固有召唤禁用接到实际被召唤实体及本卡召唤触发；融合素材按用途、目标召唤类型和区域条件检查，确定/可能候选复用原不同实体匹配，跨句例外和未解析上下文保留未知。完整通召/明确盖放/攻击限制沿用实际行动方、起点、时限及 before 顺序；未绑定效果的顶层攻击限制仍 deferred。原始识别层、求解器和评分器不变。NORMALIZATION_VERSION=v9，默认 QUALITY_VERSION 仍旧 v3；14 个不同静态方法取得通过结果、6 个 Python 文件语法/行尾通过，真实逐组结果及剩余见报告。下一步优先其他真实限制、指定召唤/素材和场上状态，再补控制/返回、调用/主题/方向组合，最后迁移生产政策、参考、旧档及旧层退出。按已确认 GPT-6.1-sol、MAX 主进程执行，不用 astra、不启动子代理；先读代码执行细则及两项指定技能，修改前交付具体机械执行项。只做变化必需的少量具体静态测试，不 discovery/装依赖/训练/CB/引擎/模型推理，不改并行识别、权重、暂停/课程指针或外部配置，不提交推送，不追索/检查/运行 Pro 辅助演示代码。当前无待答问题；一旦提问必须等待真实回答并暂停全部依赖工作，accepted、预选、超时及沉默都不是回答。长任务优先当前聊天持续推进并允许自动压缩；准确性风险或安全阶段边界出现时完成当前原子步骤，主动建议新开并交付完整独立摘要，未经用户再次真实确认不得创建后续聊天，不声称精确上下文占用百分比。
