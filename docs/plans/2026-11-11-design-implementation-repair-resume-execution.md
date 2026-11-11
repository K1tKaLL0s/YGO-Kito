# R3真实续算执行书补充

## 固定中文卡库复核发现的R1补项

只读核对本地卡片炮击士原文和KONAMI当前OCG条目后确认两处漏读。`_cost_records`将“最多3张”记录为固定3张并丢失随机身份，`_refine_record`未将按实付张数的攻击力增益绑定到费用，第二段旧式被破坏送墓触发仍为未识别。用户本轮要求复杂卡文余项必须修复。主进程将在`effect_records.py/effect_blocks.py`沿原结构实施，仅改两个通用原文形状及相应测试，原卡库和运行档保持原位。

| 次序 | 符号、前置与动作 | 结果、验证和停止条件 |
| --- | --- | --- |
| A | `_cost_records/_scope_payment_choices`复用已有有限支付分支。对明确无指定对象的牌顶送墓费用保留卡组来源、随机身份、送墓去向及实付下限1和印刷上限。`_refine_record`将“因为这个效果发动而送去墓地的数量×K”绑定对应已解析的唯一费用和系数。 | `construction_text_completion`以同形匿名变体检查1/2/3、同一功能身份和按实付数量规则。任何重复计分或把零张记作合法费用时先修本步。 |
| B | `_refine_record.known_event`在明确发动边界内消费这张卡被破坏后送达墓地的事件，保留明示场上来源、实际墓地和印刷的破坏方式。`_connectors`提供相应的同一公开分类。 | 原文变体区分破坏送墓与单纯送墓，默认`normalize_function_uses`保留已知静态用途并复用共享分配。不能借用随机送墓来证明破坏。 |
| C | `BLOCK_REVISION`更新共同字典绑定；用既有WSL CPU静态命令验证上述用例、受影响关系/触发/归一化。 | 不按卡名或ID分支，不提高评分，不加入实际盘面输入。发现与官方定义矛盾则只回退本补项的错误动作再修。 |

官方原文与数量选择说明见[卡片炮击士官方问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=6939&ope=4&request_locale=ja)。

补项默认入口首测在三个增益分支仍为未知。源头是 `effect_block_rules.structural_records` 把牌顶支付句的数量上限误标为 `deck_copy_limit`。只读核对固定中文库的旧规则命中原文后，确认这条规则也会把同名选择数和效果处理数量认作卡组投入数量。补充修改 `effect_block_rules.py` 与 `effect_blocks.block_view`。只有明示卡组投入措辞才产生投入限制。未有结构绑定的效果数量条款保留原文及局部作用域，避免移除现有的未决判断。由既有费用解析器确认为牌顶随机支付范围的原文片段可直接消费。其余规则仍看完整句。字典修订为 b11。

在已有卡文专项同时检查真实投入措辞、未绑定的同名选择数量、多个支付选项和无额外限制的牌顶支付。复跑真实默认入口、五个原受影响模块和R3静态组去重汇总。通过要求三个费用选择各自有静态见证，同一增益仅计一次，破坏送墓抽卡独立计一次，真实限制保留。若任一处理被错误判为已完成，定点修复对应句法再进入参考阶段。

## 步骤4本轮执行书

步骤3共享条件21项通过，默认入口的随机身份三种判定及拓扑/分配单步恢复均通过。两条原空墓反例曾因默认直接调用新增片边界而中断，已恢复无显式预算的直接状态调用兼容行为，四项定向复验通过。步骤4由本聊天主进程实施，修改`construction_quality.py`、`ConstructionLayerAdapter.evaluate`及对应既有静态测试。原统一评分函数、实际N、方向、加权、损失来源和参考比例保持不变。

| 次序 | 目标、前置和具体动作 | 验证与失败处理 |
| --- | --- | --- |
| 4a | `evaluate_functional_quality`当前只取本片组合或保守样例，时间退出后重头开始。新增输入绑定的JSON工作，保存下一个一致补全集索引、已完成组合的最终分及分项、硬条件和方向界，以及尚待解释的一项。真实候选消费者按原completion_budget逐片推进，直接读数在超预算时沿设计返回保守外界。 | 用同一政策分别一次完成和极小片JSON恢复，比较所有分项、可行组合、硬条件和Evaluation ID；错事实/任务/政策拒绝恢复。若预算重放前缀或改变分数，先修本步。 |
| 4b | `_functional_loss_records`现遍历全部已评组合且超时重算。对每个当前完成组合沿原渠道计算解释，保存已解释组合计数与各失分条目的来源、修复条件和区间。条目仅在部分组合出现时纳入零失分。解释结束后释放该组合的详细四阶段数据，保留正式输出所需的分数及界。 | 停在组合与解释之间时仍可恢复；评分函数调用次数与一次完成一致。验证损失范围、来源、修复条件、方向和完整Evaluation ID一致。错误先定点修复本阶段。 |
| 4c | `ConstructionLayerAdapter.evaluate`目前只保留规范化工作。将评分工作挂到该候选的同一calculation_progress，遇到预算或停止则返回待算，完成前不放入evaluation缓存或比较。既有候选合法/排序、时间停止优先和归一化投影复用保持。 | 保持原质量超时后规范化不重跑测试，新增真实预算退出后保存、恢复和一次提交的公开入口回归。不会形成半成品Evaluation。 |

测试沿现有WSL CPU前缀运行`tests.test_construction_functional_quality`、`tests.test_construction_calculation_resume`及受影响静态消费者，核对同口径边界、逐阶段进度、错误/跳过及Torch加载。保守直读保持原测试，R5参考独立性反例继续单列。评分语义不变，最终完整输出使用原v4合同。暂停的运行及原资料保持原位。

本批实施结果（2026-11-11）：步骤1及步骤2的共享分配、关系数量/组合/回收/返回身份及facts→uses→joint接续已进入真实消费者，原F04/129与公开入口allocations=1每片JSON恢复通过。终端直接无条件联合用同一共享分配器取存在性见证；需供下游选择的替代集仍完整续枚举。非resumable读数保留已知正向前缀及pending标记，不提交到完成缓存。规范化v25/b9，最终十个明确静态模块按ID去重254项通过，0失败/错误/跳过，Torch未加载；库存tuple恢复的初轮合同失败已定点修复。步骤3/4状态安排、随机分支及质量游标仍未改，整个R3未关闭。细节和安全接续见[第四批报告](../reports/2026-11-11-design-implementation-repair-batch-4-resume.md)及[独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-4-continuation.md)。

## 步骤3本轮执行书

用户当前已明确授权自主在本聊天或新任务推进全部剩余修复。本阶段选择原聊天主进程，在唯一完整检出实施。没有待答事项。目标是让空状态约束、印刷处理顺序和随机实体分支在实际规范化中可中断并逐片求完。此前已读执行细则、原设计与步骤1/2实际通过证据。修改范围为`multifactor/conditions.py`、`construction_layer_flow.py`及现有对应静态测试。原评分、参考比例、资产和已暂停的运行保持原合同。

| 次序 | 真实符号、前置及动作 | 验证与失败处理 |
| --- | --- | --- |
| 3a | `Condition/_Search.state_frame/advance/solve_requirements`现将所有槽组合按存在性选取。添加显式随机状态帧，在每个可行身份下用同一DFS寻找后续可选动作，所有身份均有见证才为真，全部不满足为假，有差异或不完整证据为未知。随机帧保留当前组合、子栈、已证结果和代表见证。对已确定真假分歧可停止其余等价结论的枚举。保留旧非随机条件的序列化绑定和完整分配语义。 | 共享条件专项测试全真、全假、混合、随机翻开后选择、连续随机移动、在组合及子栈内每步JSON恢复。验证已处理次数与一次完成一致，代表见证标注随机身份。若有利身份被置真、恢复改变见证或原条件失败，先修本步。 |
| 3b | `_state_movements/_joint_state_order`现丢掉无指定选择器的牌顶移动，安排栈和共享分配在预算耗尽时丢失。对已识别的无选择器牌顶送墓、抽卡和随机支付使用其原区域和已知数量。翻开后选择使用同一共享分配的随机暴露集合及集合内玩家选择，剩余牌维持卡组区域。成功送达才继续的印刷依赖及明示送墓费用在去向替代时校验实际去向。 | 原空墓/Token/替代/区域方向验收保持。默认入口对随机送墓后空墓、部分身份可清除、全身份可清除以及顺序送墓被替代给出对应确定性。实测输出不新增功能得分或另取牌表。 |
| 3c | `_joint_state_order/_bind_mandatory_impacts/normalize_function_uses`在既有归一化工作保存按用途范围绑定的拓扑DFS栈、活动安排和分配continuation。将已完成组结果复用，使用allocations及停止回调限制当片，未完成返回calculation_pending。复用已完成卡文读取和关系投影。 | 现有公开规范化和共享条件专项分别在安排和分配时中断，JSON恢复直到完成，与一次完成得到相同支持与见证；单片零预算返回pending。若继续重复已完成安排、失去游标或把预算记成硬失败，先修本步。 |

验证沿既有WSL CPU命令前缀，显式运行`tests.test_multifactor_conditions`、`tests.test_construction_static_entries`和`tests.test_construction_calculation_resume`的受影响静态测试。通过条件为无失败/错误/跳过、无模型或引擎加载、切片与一次结果一致。规范化版本在状态合同变更时更新，旧运行与既有证据留存。步骤4在本阶段实际验证后实施。

官方依据复核包括牌顶三张送墓、翻开数量后从暴露集合选择、送墓被替代导致同一效果后段不处理。见[KONAMI牌顶送墓卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=17414&ope=2&request_locale=ja)、[翻开后选择问答](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=15756&ope=4&request_locale=ja)和[去向替代问答23915](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=23915&ope=5&request_locale=ja)。静态身份分支的聚合来自本项目的配置判断设计，以上官方材料用于确定印刷操作的原义。

2026-11-11，Asia/Hong_Kong。继承R0—R11原方案、执行书和S0—S6，主进程实施，无子代理、无UI或新工作树。只在`N:\YGO-Kito\_publish_20261030`修改；训练、推理、CB/native、完整构筑、run-007继续暂停。不提交/推送/合并、不覆盖混杂成果。

目标是让有限关系、共享实体分配、空状态次序及唯一质量评分保存下一枚举位置，JSON恢复后只处理剩余分支。当前证据：`construction_relations._partial_allocations/_combine/_expression`及回收分支仍有128永久截断；`multifactor.conditions.solve_requirements`是递归生成器，预算退出没有可序列化枚举栈；`evaluate_functional_quality`中完成组合及失分说明超时后从头开始。现有事实匹配、更新队列及规范化投影已有游标，保留并扩展。原129供应池反例仍为普通失败，不提高常数掩盖。

允许修改：`multifactor/conditions.py`的共享分配实现与公开可选续接参数、`construction_relations.py`、`construction_recognition.py`的共享分配消费者、`construction_quality.py`、`construction_layer_flow.py`及其已有纯静态测试、当前证据/文档。禁止改网络/训练内部实现、权重、原资产、参考牌表及旧运行档。默认API继续返回原有合同字段；增加游标字段不让半成品进入完整Evaluation缓存。固定log2、P/V1/V2/S、Main/Extra折算、实际N、主题加权、Side方向和0.8参考比例。

| 步骤 | 文件/符号、前置与具体动作 | 验证与通过标准 | 失败停止条件 |
| --- | --- | --- | --- |
| 1 | `multifactor.conditions._Search/solve_requirements`；R1/R2状态专项通过。用显式DFS任务帧替换不可保存的递归枚举，帧保留all/any/at_least_k/not、原子组合位置、分支预约和区域/发动源绑定；保存输入绑定、下一帧、已发出分支及稳定去重。可选`continuation`进入同一实现，步数/方案数只限制当前片。 | 原条件测试及新增大量替代、数量组合、not、状态移动中途JSON恢复；小片与一次枚举的完整见证集合一致，已处理前缀计数不重复，同一物理副本/支付不重复。 | 栈未前进、只提升常数、未知变真或丢失分支即停止本步骤，不接入上层。 |
| 2 | `relations._partial_allocations/_combine/_expression`、回收选择/数量/转移及`recognition.allocate_relation_group`；步骤1完成。用已有RelationEvaluation的continuation保存局部枚举任务、共享分配游标和已完成子结果；预算中断保留当前fact/use位置，不能弹出后丢失；移除128永久语义截断，表达式保留规范化去重与公共项。 | 129方案原反例通过；数量、多供应、共享实体、回收、环及正反例；强制每片极少工作并JSON恢复，累计新工作与一次完成相同，完整结果无budget未知。 | 无法续接的旧游标只失效相关计算，不清空任务/候选/反馈；实际恢复不等价则先修本步骤。 |
| 3 | `layer_flow._joint_state_order/_bind_mandatory_impacts/normalize_function_uses`；步骤1/2接口稳定。保存拓扑安排的DFS栈、当前安排及共享分配游标；规范化最后状态消费可挂起并恢复；已完成牌表/关系投影不重复。随机移动不得因选择一次有利身份被当作确定命中或确定避开，需保留其分支影响。 | 在空状态安排与其实体分配中分别中断、JSON恢复，与一次完成相同；Token、规则离场、清除/返回、替代及方向隔离保持。 | 中断被记硬失败、恢复重建完整前缀或随机特定命中被置真即停本步骤。 |
| 4 | `quality.evaluate_functional_quality/_functional_loss_records`与`ConstructionLayerAdapter.evaluate`；步骤1—3通过。分别保存Boolean完成组合索引、分项累积和失分说明游标；采用同一评分公式和来源；计算待算返回pending并保留质量工作，不缓存完整Evaluation。 | 在完成枚举及失分阶段分别中断恢复，已处理索引严格前进；最终score、loss_records、Evaluation ID与一次完成一致。已有规范化完成后质量超时恢复专项保持。 | 切片影响得分、完整性或ID则先修；不降低完整性门槛、不新建私有分数。 |
| 5 | 上述全部真实消费者和安全测试登记；各阶段通过。明确执行calculation_resume、relations、functional_quality、functional_flow、static_entries、condition_selection及共享条件模块，按完整测试ID去重，AST/本批差异空白检查；R5参考独立性仍单列开放。 | 所有已实施R3缺陷回归转绿，0错误/跳过，资源/收益守恒；完整CI与完整构筑未运行时如实记录。 | 不运行未筛选discovery、训练/推理/引擎；与R3无关旧故障不扩展成本包任务。 |

验证沿既有WSL P前缀，证据写`.cache/design-implementation-repair-20261111-resume`。每步先完成当前非破坏性原子动作和验证再进入下步。输入绑定变化拒绝旧计算游标；兼容性通过现有规范化/版本检查失效相关计算，旧成果保留。用户停止时保存当前游标并结束，不开新阶段。没有待答问题，不增加审批。

## 共享分配栈的确定实现补充

本主进程已核对实际`_Search.atomic/state_atomic/solve/sequence`和公开消费者。步骤1直接替换同一类内部的递归生成器，不保留第二实现；显式帧仅有待访问序列、组合选择、原子槽组合及否定子栈。节点用稳定遍历编号，原子帧保存候选槽及下一个组合索引，否定帧保存已见未知与其子栈；状态保留预约、pending、choices、slot_zones、state_bindings和destination_replacements。

公开函数增加可选`continuation=None, should_stop=None`，当前片预算不进入输入绑定，树/库存/coverage/state_provided进入绑定。返回原字段并增加`continuation`和累计工作计数；`branches`保留累计唯一见证、稳定branch_id，只有当前片新工作消耗预算。游标仅含JSON数据，恢复时严格校验版本及输入；不匹配抛原合同错误。默认单片仍可返回overflow，但同时保留未完成栈；上层在步骤2/3消费游标后才能声称其真实续算已完成。

修改文件为`multifactor/conditions.py`及`tests/test_multifactor_conditions.py`。新增129选择、all/any/at_least_k/not、未知覆盖、共享槽冲突、清除/返回/绑定的极小片JSON回归，比较一次完成的见证集合和累计工作量，拒绝错树/错库存恢复。命令为既有WSL/P前缀加`-m unittest tests.test_multifactor_conditions -v`，随后条件消费者的显式静态模块。通过标准为0失败/错误/跳过、无Torch加载、切片输出与一次完成相同、前缀工作不重复；任一失败先定点修复本步，不推进关系消费者。禁止安装、训练、推理、native和旧运行档变更保持。

步骤1实测18项全通过，随后static_entries/relations/recognition三个明确静态模块132次执行全通过（最终汇总另按ID去重，不累加为独立方法）。步骤2确定将原`evaluate_relations`队列扩展为facts→uses→joint三个阶段，活动单元保存局部操作游标和已完成子结果。当前fact仅在完整求值后出队；用途/联合组同样仅在完成后推进索引。旧v1队列可迁入v2，输入绑定保持；completed子结果按JSON等值规范恢复，局部工作只活到当前单元完成。`_partial_allocations`、笛卡尔组合、回收子集/数量/返回身份均保存下一位置；共享分配的存在性检查取得已知见证即可结束，需完整替代集的recognition消费者必须枚举至栈空。表达式保留原有约简和稳定排序，去掉128节点语义截断。验证增加allocations=1等极小片、129替代及中途JSON恢复；比较最终uses/joint、累计新工作与一次完成，不重复已完成前缀。失败时仅修当前关系单元，不进入步骤3/4。
