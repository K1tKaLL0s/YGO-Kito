# 构筑实现与历次运行记录

本页是历史实现与执行记录，各日期段落只描述当时状态。当前设计统一见 [构筑流程](../current/construction-workflow.md)、[评分与扣分](../current/construction-scoring.md)；后续修订以现行正文为准。

本轮最终状态：用户最新要求已改为结束试运营，run-007进程已停止，不自动续跑。12份候选Evaluation与完整一致的kernel／session均保留；参考Evaluation和S5未完成。“静态不完整”的设计问题留待后续优化，本轮不展开新工作。[停止记录](../reports/2026-11-10-construction-condition-selection.md#按用户最新要求结束本轮)优先于下方历史运行状态。

2026-11-10 最新完整条件和选择消费为规范化v21／积木b7，含JSON分配见证恢复、支持条件分组与失分解释修正后的94项必要静态、23文件检查通过，原2207任务、course-006权重和12份候选正在本轮run-007以开发模式连续续算；run-006一次保存替换访问拒绝后已用异常处理成功保存的较新完整kernel立即恢复，代码未改、23文件绑定再次一致。见[当前报告](../reports/2026-11-10-construction-condition-selection.md)。完整己方存在条件与发动时点、卡名记述选择、后置区域及互斥处理按完整原文消费；未解析限定继续保留程序原因，静态构筑不要求当前对局状态。下方较早版本和历史预算挂起仅说明原批次。

2026-11-10 最新时间及处理纠正：开发／训练默认持续推进，内部时间和轮数分片自动续算；上线到期停止新增候选，完成已生成批次的评价、参考、选择和真实 Gate 后交付，不能靠超时越过静态完整性或 CB 授权。规范化v20／积木b6将同一完整处理的实体要求接到现有整数分配及区域转移接口，一份手卡怪兽不能兼作自身特召和后续手卡送墓对象，合法转移／返回及择一用途保留。最终74个必要静态方法同组通过，跨片返回保留已完成阶段；实际原2207的5片保存、主动交接中断和剩余见[当前报告](../reports/2026-11-10-construction-runtime-processing.md)。下方版本与预算段落是对应历史证据，以本段及当前准入说明为准。

2026-11-10 静态用途纠正：默认构筑读取卡文、牌表、规则与配套关系，不要求当前手卡、场上状态、具体堆墓结果、对方当前对象或实际操作序列。规范化v19／积木b5为完整印刷条件提供静态适用来源，默认候选适配器与最终Evaluation均消费；已识别召唤手续为非计分能力，分支条件／代价／对象独立，融合素材按完整谓词和不同实体检查。随机送墓的兼容配合可计入，但不能作指定调用。61个必要定点静态方法同组通过；实现、失败记录和原资源重跑见[本轮报告](../reports/2026-11-10-construction-static-entries.md)。旧报告中把当前对局状态未给归为正常输入unknown的口径已撤回。

2026-11-10 当前源码及实际重跑见[本轮修复记录](../reports/2026-11-10-construction-workflow-repair.md)，资料先读[统一入口](../current/README.md)。按[S0—S6](../current/construction-workflow.md)修正：完整环境固定任务，通用积木词表先生成无卡ID图，狭义再筛轴；优化在原卡池内持续检索，候选与参考同口径评价、选择和Gate。当前质量v4、准入v3、规范化v15。旧预筛封池及默认珠泪CB加分已退出；CB正常失败按候选归属，预算内两次正常失败回S2。本次实际运行关闭CB和训练，最终结果以本轮报告为准；下方各日期段落保留历史，不覆盖本段。

2026-11-09 当前模块已完成原方案逐项源码核对及旧入口清理，见[核对报告](../reports/2026-11-09-construction-module-code-review.md)和[当前准入与学习接口](construction-admission.md)。质量 v4、准入 v3、规范化 v13 是活动版本；固定任务和自主主题共用 `construction_cycle`。本轮补齐连续不足提示，修正监督、预算和模式恢复，删除未调用评分草稿及旧排序；147 个不同静态方法均取得最终通过记录，原始失败和定点修正完整保留。训练、CB、真实模型推理未启动。下列按日期的批次段落和旧运行成绩是历史记录，当前调用以本段及准入说明为准。

2026-11-09 动态加权补正完成：此前无依据的“13／13 全部完成”确认保持撤回，本次以实际自动入口证据重新关闭 W3-2、W4-1、W6-2。规则从原任务、固定卡池和真实配合归纳，主要目标额外 +100%、次要目标额外 +50%，保持原公式；同一处理取高档，完整代价、数量、限制及换备容量决定实际投入。默认入口、排序、偏好样本、参考重评、政策修订与准入已接通。当前 68 个不同定向静态方法整组通过（含 17 个自动主题用例），未加载 Torch。用户已授权仅修公开接口，复查时现有导出已修正，本轮未再修改并行模块。固定六包 13 项、38 条验收及 12 行补充结构均已对齐；无待答问题，无训练／CB／真实模型推理或子代理。见[补正与实际验证](../reports/2026-11-09-construction-theme-weighting-correction.md)。以下历史批次保留其当时状态。

2026-11-09 W1-1 已完成：未采用的可选零正分效果不再因所带未知限制造成全局 deferred，原始明细保留；最终采用/支撑条件决定限制是否相关。已补明确处理限制的作用方、区域、代价/效果原因、时限及顺序，本卡素材限制不阻断无关抽卡效果。规范化 v10，默认质量版本仍旧 v3；27 个不同静态方法取得通过结果。A17 已闭合，验收状态为 21 已完成、12 证据待补、5 含实现缺口；固定 13 项剩余 12 项，按用户新授权继续 W1-2。见[W1 实施记录](../reports/2026-11-09-construction-w1-restrictions-and-selection.md)和[验收固定清单](../reports/execution/2026-11-09-construction-acceptance-alignment.md)。以下对齐与批次段落保留当时状态。

2026-11-09 验收与剩余工作已逐项收敛：[38 条验收及补充结构对齐](../reports/execution/2026-11-09-construction-acceptance-alignment.md)记录当前 20 条已完成、12 条仅待指定证据、6 条含实际实现缺口，并固定六包 13 项剩余。已区分真实输入未知与漏接实现；自动主题目前偏向墓地处理、未适配限制的全局 deferred、通常召唤次数及参考版本绑定等缺口已明确列项。该清单替代下面历史批次宽泛的“继续扩展”描述，保留历史运行证据；本次未改源码、未运行测试，代码实施暂停。后续沿用游戏王常用术语，通用构筑不套用珠泪主题或参考政策。

2026-11-09 功能评价迁移第十批：固有通常/特殊召唤禁用已接到被召唤实体与本卡召唤成功触发，融合素材改为按实际用途、目标召唤类型和完整区域条件检查，不再凭粗标签全局排除。确定/可能候选复用原不同实体匹配，确定替代足够则库存通过，仅可能候选能补齐则 unknown；完整句、跨句例外和未解析前言保留。完整玩家通召、明确盖放和攻击锁沿用实际行动方、起点、时限及 before 顺序；未绑定具体效果的顶层攻击限制保留 deferred。NORMALIZATION_VERSION 升为 `construction-function-normalization-v9`，默认质量版本仍旧 v3；14 个不同静态业务方法取得通过结果，6 个 Python 文件语法/行尾通过。真实文件、逐组成功/失败、剩余边界及完整续接摘要见[第十批固有召唤/条件素材报告](../reports/2026-11-09-construction-functional-summon-material-restrictions-phase10.md)。以下各批保留当时状态。

2026-11-09 功能评价迁移第九批：原始持续不能抽卡/不能加入手卡已通过完整限制契约接入非计分必需采用、强制影响及最终 Evaluation。限制作用玩家与来源己方场上状态分开，加手按实际目的地、起点和接收方定位；已有召唤锁保留真实起点及行动方。整回合/发动后范围分开，原 before 约束支持传递顺序，矛盾顺序 unknown；未解析例外及尚未接线的固有召唤限制继续 deferred，不仅凭 kind 清除未知。可选零正分来源不自动采用，必需用途被撤销会在最终硬条件失败，方向负增量保留。NORMALIZATION_VERSION 升为 `construction-function-normalization-v8`，默认质量政策仍旧 v3；14 个不同静态业务方法最终通过，4 个 Python 文件语法/行尾通过。真实文件、逐组结果、边界及完整独立续接摘要见[第九批抽卡/加手限制报告](../reports/2026-11-09-construction-functional-hand-restrictions-phase9.md)。以下各批保留其当时状态。

2026-11-09 功能评价迁移第八批：有限跨区返回按实际物理槽位提供分阶段区域视图，复用原整数分配器；返回后不能再从旧区域使用该实体。leave_field_banish 已绑定本效果召唤对象，真实离场去向及原召唤来源进入成功/失败证据，墓地接续会因实际除外而撤销；重复的未来 banish 投影不再多计正分。完整具名特殊召唤复用现有库存选择语法。单张、单次明确卡组端点可支持位置及普通成员资格，多张/多次移动的精确位置继续 unknown；混合旧式/实体返回及超出原三消费阶段仍 unknown。NORMALIZATION_VERSION 升为 `construction-function-normalization-v7`，默认质量政策仍旧 v3。14 个不同静态业务方法最终通过，5 个 Python 文件语法/行尾通过；文件状态、真实逐组结果、剩余与完整续接摘要见[第八批跨区生命周期报告](../reports/2026-11-09-construction-functional-zone-lifecycle-phase8.md)。以下各批保留其当时状态。

2026-11-09 功能评价迁移第七批：无 operations 的非风味原始记录自动生成保留费用/对象/次数/条件的来源，并接成 `contributes=False`、无主题分的用途。原任务必需采用可触发强制影响，可选零收益来源不因位于牌表中而采用。已识别的己方怪兽区域持续限制通过独立适用端口取得支持，库存不能证明场上状态；新增“不能从额外卡组特殊召唤”的来源/起点/行动控制方/方向映射，多起点及未知条件继续 unknown，未映射限制 deferred。来源删除或仅放 Side 会使常驻要求失败；先攻来源的负增量保持。NORMALIZATION_VERSION 升为 `construction-function-normalization-v6`，默认质量政策仍旧 v3。11 个不同业务方法最终通过，4 个 Python 文件语法/行尾检查通过；真实文件、逐组结果、剩余和完整续接摘要见[第七批无操作来源状态](../reports/2026-11-09-construction-functional-no-operation-impacts-phase7.md)。以下各批保留其当时状态。

2026-11-09 功能评价迁移第六批：原始 recover/move 现在保留有来源的转移契约，并在当前候选资源视图内解析有限实体集合。回到原可用区域的返回直接约束此前实际消耗的物理槽位，不能以返回 A 释放 B；消费去向、区域、所有方、控制方、完整费用与单事件总量共同检查。原始具名墓地回收已通过规范用途、硬条件及最终 Evaluation 的接线；Side 对象不能补足常驻要求。跨可用区域、牌组位置、双方或未解析选择等范围仍 unknown，未扩建求解器。NORMALIZATION_VERSION 升为 `construction-function-normalization-v5`，默认质量政策仍旧 v3。10 个不同业务方法最终通过，4 个 Python 文件语法/行尾检查通过；真实文件、逐组结果、剩余工作和独立续接摘要见[第六批实体转移状态](../reports/2026-11-09-construction-functional-physical-transfers-phase6.md)。以下历史批次保留其当时状态。

2026-11-09 功能评价迁移第五批：跨层 all 和共同用途重新检查派生资源结论，保留真实来源未知；同一次返回按有限整数数量分配到多条边和重叠库存池，不重复计返回量或发动费用。PoolRecovery 新增兼容旧声明的完整费用时序，返回与宿主顺序合并到同一有限事件图，继续复用现有整数分配器。返回事实变化直接通知实际消费者；已闭合的嵌套返回费用可进入全局证明，未闭合安排保留 unknown。全局共同证明已传入规范用途和必需条件，规范化版本升为 `construction-function-normalization-v4`。12 个不同业务用例最终通过，4 个 Python 文件语法/行尾检查通过；默认质量政策仍是旧 v3。真实文件、验证、剩余范围与独立续接摘要见[第五批全局返回状态](../reports/2026-11-09-construction-functional-global-recovery-phase5.md)。下列各批段落保留其当时状态。

2026-11-09 功能评价迁移第四批：带前置费用的部分供给改为独立的整数数量/子集分支，同池替代来源分别保留；显式返回可跨重叠库存池复用同一实体，并在现有分配器的三个消费阶段内检查连续返回、次数、费用与宿主顺序。零正分但原任务必需采用的来源可触发强制影响并进入损失解释，原任务必需绑定已传给规范用途。规范化版本升为 `construction-function-normalization-v3`；默认质量政策仍是旧 v3。15 个不同定点用例最终通过，6 个 Python 文件语法/行尾检查通过。完整结果、剩余语义和独立续接摘要见[第四批供给与回收状态](../reports/2026-11-09-construction-functional-subsets-recovery-phase4.md)。以下第三批段落保留其当时范围；复杂跨层返回、未映射限制、自动调用/主题、方向组合及真实政策迁移仍未闭合。

2026-11-09 功能评价迁移第三批：显式 v4 候选链新增独立资源分支、重叠库存整数分配、明确顺序的单次回收、共同用途到 V2 的绑定、来源级强制影响、Side 隔离与完整 R/X 重算，以及逐功能损失/修复条件记录。定向墓地调用和已完整识别的主题接收方开始自动适配，墓地与堆墓双通道保留；本批 16 个不同定点静态用例、7 个 Python 文件语法检查通过。复杂供给子集、多池回收、未映射限制及复杂主题/Side 组合仍为 unknown/deferred；真实政策与参考未迁移，默认旧 v3 保留。当前文件、证据和续接摘要见[第三批资源与 Side 状态](../reports/2026-11-09-construction-functional-resources-side-phase3.md)，已有候选链见[第二批](../reports/2026-11-08-construction-functional-production-wiring-phase2.md)，完整目标见[正式优化方案](../current/construction-scoring.md)。训练和 CB 继续禁止。

2026-11-02 历史职责设计（现行分工见[构筑流程](../current/construction-workflow.md)）：[目标模型完成第一层轴骨架，优化模型完成第二层、多轮修订及泛用配置](../current/construction-workflow.md)。优化模型接收统筹、决斗和外接 AI 反馈；训练模式未达构筑门槛持续迭代，达标后才进入线性基础 CB，允许固定随机堆墓而不展开命中分支。该分工已接入实际入口，验证见[当前报告](../reports/2026-11-02-construction-role-basic-cb.md)。完整质量指标与阈值尚未配置，未通关时保存并挂起。效果词典与实际 CB 归属见[核验](../reports/2026-11-02-effect-block-dictionary-and-cb-owner-audit.md)；训练和 CB 继续暂停。

2026-11-02 统一修复：费用／对象／素材未知不再算覆盖，全牌表必要配套与图内用途分开核算；池外配套按合法词表有界召回，字段归属使用同一卡库的代码映射。固定任务与自主主题均进入同一职责分离和持续优化入口。旧 `alternate_build`、70/56 参考评分、提示模块、私有准入账本绑定及一次性迁移实现已删除。当前行为见[统一修复报告](../reports/2026-11-02-construction-unification.md)与[构筑准入及学习接口](construction-admission.md)；原[核验报告](../reports/2026-11-02-construction-design-audit.md)记录的是修复前状态。

两层事实由 `ConstructionController → construction_cycle → fill_with_existing` 调用。当前唯一路径在质量选择前评价全部本轮候选，以完整、硬条件成立的最终 S 排序；模型只安排待评顺序和同分取舍。学习 source 为 `construction_quality_preference_v2`，不从旧 layer_comparisons 产生新标签。旧最终层排序及非 v4 回退已删除，层投影只供当前诊断和骨架依据；未评完时保存待评队列。两层设计与首轮 GPU 历史记录见[第一层](../current/construction-workflow.md)、[第二层](../current/construction-scoring.md)及[首轮实施书](../reports/execution/2026-11-01-construction-layers-implementation.md)。

正常目录绑定器从当前任务／图、有来源的判断和效果记录投影两层。字段／种族单独只给 q=0.5；未提供的发动、费用／对象可用性和材料取得条件保留 unknown。宿主可通过 `ConstructionController(..., layer_context_provider=provider)` 提供固定用途的 `LayerContext`，不允许改变原目标。直接 `fill_with_existing` 使用目录绑定器也自动接入；无来源契约的自定义 callable 报告 `source_context_unavailable`。现有权重结构未变，当前优化计数仍为 0；学习标签接通不等于权重已经学习。训练与 CB 继续暂停。下面三阶段是既有工作步骤，与两层评价分工分别使用。

2026-10-24；独立新增工程实现，基线为远端 `codex/phase-1-cpu-foundation` 的 `6549717`。首次框架提交 `5d4336b` 后继续补齐可训练/实际调用实现，见[当前增量报告](../reports/2026-10-24-construction-trainable.md)。本次不承接原生崩溃/缓冲区修复、导出或预算工作。

## 三阶段

1. **构筑逻辑**：先表达无具体卡 ID 的轻量图。节点保存效果、卡片所属字段与卡文指定的对象或素材字段，并保留相关区域和触发条件。连接件独立，用 `ns`、`ss`、`送墓时发动` 等宽泛描述。分支、合流、替代路径可以直接表示，合流不自动解释为精密 AND 条件。图不执行卡效，也不解析条件语言。
2. **主题主轴筛选**：仅狭义主题执行。根据有来源的字段 `setcode` 或种族 `race_any` 找主轴候选；混轴各自保留明确最低张数。保留通用/辅助卡候选池，不把整副卡组硬过滤成纯轴。广义主题从第一阶段直接到第三阶段。歧义或低置信只保留第一阶段，等待澄清。
3. **卡文填卡与核验**：复用现有候选生成、数量约束、目标/优化评分、卡表合法性、支持范围内的目标核验接口。按当前完整卡文审核具体节点绑定。粗逻辑、词命中、文本摘要和合法牌表都不能替代合法 CB。

珠泪、植物、神碑、堆墓、除外只是默认词典例子。词典可以扩展；未知裸名保留未决，未见过的“X主题／字段／族”显式词槽可识别为狭义，但不会捏造该主题的真实字段代码。

## 数据和修改

`construction_logic.py` 提供 `LogicTag / LogicMetadata / LogicNode / LogicConnector / ConstructionLogic`。标签身份只有 `dimension + value`；来源、层次、说明在独立元数据中。单标签不含 `·`，只有联合展示用 `·`。旧 `BuildTask` v1–4 及其注释编码保持原接口。

统筹侧先接收原文并解析支持的任务表述，目标模型使用结构化任务。`ConstructionSession` 绑定原文和完整 `BuildTask` 摘要。`submit_logic` 与 `revise_logic` 记录父版本、修订号、角色、原因和反馈；可以替换整个图。需求、填卡、决斗和各模型反馈用 `record_feedback` 输入。变更用户目标须显式建立新的请求/会话，不能借优化修改旧任务。`to_dict()` 可保存完整目标、图、阶段记录和反馈。

`logic_cycle` 是独立的图提议工具。实际 `construction_cycle` 首次调用目标模型为结构化任务选择无具体卡的效果积木草案，再由优化模型按配套需求和卡文选卡、补全和持续修订。恢复时继续优化。`ConstructionSession` 保存 `construction_progress` 与 `optimization_feedback`，记录原任务、候选版本、真实角色输入输出、游标和反馈消费。时间、轮数或候选预算耗尽均为 `construction_suspended`，不生成通关或 CB 成功标记。

现在提供具体实现：`LogicCodec` 无卡 ID 编码/解码图，`rule_graph_candidates` 按明确请求的基本标签枚举有界粗图，`LogicModelAdapter` 用现有目标/优化 **同一组 BuildRanker 对象和优化器**评分选择。图特征进入已有 numeric/kind/position 投影，卡 ID 槽保持 0，没有把标签索引冒充旧卡嵌入，也没有另造大网络。`train_preference` 真实执行图偏好损失、反向传播和优化；独立图 checkpoint 绑定特征版本、词典、原任务和旧卡词表，可保存模型/Adam状态并连续恢复。原四模型 checkpoint 不被静默迁移。

候选由程序枚举、模型选择；不声称神经网络自由生成任意图。图词表中的标签作为本次明确请求的必要特征钉住；运行时改词表拒绝，绑定器会在可达分支并集中覆盖这些标签，但标签覆盖仍不证明效果实际执行。示例 JSON 仍是工程示意，不是训练成果。

`CatalogBindingAdapter` 是实际目录绑定者：读取现有候选牌表的卡文/属性，对种族/字段做真实公开属性匹配，按来源绑定审核记录支持功能标签，选择可达路径并给出节点→卡绑定。功能关键词只召回，未知卡效仍返回 `unknown`。不存在虚构的自动卡文理解器。

`ConstructionController` 直接组合上述模型适配和绑定器，真实调用既有 `CoordinatorTrainer.advice`。有已核验候选和真实源 ledger 时，经旧 `Coordinator` 的 `handoff.submit` 及 `route_with_model` 写入托付、取得规则权威路由并记录实际网络建议。无托付时只运行预构筑聚合上下文的建议，不假装已完成账本/决斗循环。

## 入口分类器

`intent_model.py` 的 `LinearIntentClassifier` 是实际可训练的 CPU 线性 softmax 分类器：字符 ngram、英文词及词典/作用域辅助特征经归一化后学习权重；`fit / predict / save / load` 均已实现。预测输出实际模型分数、margin、词汇覆盖和模型摘要，置信/差距/覆盖不足拒判；无模型或未训练一律 `ambiguous`。新 CLI 和会话都走此模型路径。旧 `build_intent.py` 规则判别仅作辅助实体/作用域特征及兼容函数，其固定规则置信不进入模型预测。

小合成拟合仅检验实现，未证明生产语义泛化或置信校准。下表描述路由意图；只有实际模型接受该类别且主题事实已明确时才进入相应阶段，不能当作任意表述的能力成绩。

| 请求 | 路由 |
| --- | --- |
| 植物族堆墓 | 1→2→3 |
| 不要珠泪和神碑，只要堆墓 | 1→3 |
| 神碑只作外挂，以堆墓为目标 | 1→3 |
| 植物族或者龙族堆墓 | 1，待澄清 |
| 星河织梦主题 | 1→2→3；第二步需要有来源的主题事实 |
| 未收录的裸名称 | 1，待澄清或扩展词典 |

入口只判断构筑范围，不把自然语言全部编译成数量/排除约束；具体硬要求仍须显式保留在原 `BuildTask`。复杂省略、双重否定、跨句指代等自然语言泛化未完成校准/训练；需要继续扩词典和保留反例，而非宣称任意表述均已理解。

词典 JSON 形状为 `{"terms":[{"canonical":"星河织梦","kind":"theme","aliases":["星织"]}]}`。`kind` 支持 `theme / field / race / mechanism`。CLI 的 `--lexicon` 在默认词典上扩展，别名冲突拒绝；Python 也可用 `DEFAULT_LEXICON.extended(...)`。

## 第三阶段的证据边界

`FillProposal` 单独保存具体三部分牌表、节点→卡绑定、所选连接路径，并绑定任务/图摘要。卡数量仍由 `DeckParts` 和现有校验器处理。

`NodeTextReview` 明确为 `satisfied / unsatisfied / unknown`，须覆盖节点标签及绑定卡，给出来源、解释、当前卡文摘要和实际摘录。评审者收到完整公开卡文和静态属性；系统核对摘要、摘录与来源，但**不声称因此形式化理解卡效**。没有评审者或评审未知时不进入真实目标核验；明确不满足时拒绝，并将问题反馈给后续构筑逻辑修订。

回退绑定任务、图版本、当前意图和主题主轴约束；主轴最低数量变化不能借旧缓存通过。相同节点/卡集合的旧评审被明确否定时缓存失效，卡集合顺序无关。缓存/返回值深复制，防止调用方误改后续证据。

默认生产适配 `existing_goal_verifier` 委托 `build_pipeline.verify_goal`。它只验证旧接口支持的具体目标：通常召唤、限定同调/超量、schema4 约束及组合目标。资源缺失或未支持时如实未验；不修改原生绑定，也不扩大其验证范围。

- `list_constraints_verified_logic_unproven`：具体卡表约束通过，效果执行未证。
- `task_goal_verified_logic_unproven`：既有具体目标核验通过，任意图边仍未证。
- `graph_execution_verified` 固定为 `false`；本次没有任意构筑逻辑→完整合法 CB 的通用证明器。

## CPU 入口

在隔离工作区使用已安装 Python，不安装依赖：

```bash
cd /workspace/YGO-Kito-construction
PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m ygo_kito construction-plan \
  --request '不要珠泪，只要堆墓' \
  --logic configs/construction-logic-example-v1.json
```

该命令不加载 Torch、不访问卡库、不执行引擎。未提供 `--intent-model` 时会拒判并只保留第一阶段；图结构通过不代表能填卡。可显式拟合工程样本并加载（输出须选未存在路径）：

```bash
PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m ygo_kito construction-intent-fit \
  --input configs/construction-intent-engineering-examples-v1.json \
  --output /tmp/ygo-intent-engineering.json --epochs 180 --learning-rate 3
PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m ygo_kito construction-plan \
  --request '我要堆墓' --intent-model /tmp/ygo-intent-engineering.json
```

`construction-fill-check` 接受 `--request --task --logic --proposal`，可提供 `--intent-model --scopes --reviews --lexicon --root`。默认不会执行引擎；显式 `--verify-existing-goal` 才调用现有支持接口。CLI 返回 JSON 中的 `status / unmet / graph_execution_verified` 必须一起判断，退出 0 只表示请求已正常处理。

`construction-run --request TEXT --task TASK --intent-model MODEL --required-tags TAGS --binding-data DATA` 通过当前控制器执行图选择和绑定；TAGS是基本标签数组，不是用户手写整张图。`--logic-checkpoint`可加载图偏好训练权重；不提供则两个现有小模型随机初始化、图训练计数为0。`--base`可给已有合法牌表，使用现有有界编辑；无base的schema4从零生成需要现有任务求解器的可选SciPy依赖。绑定数据是 `CatalogBindingAdapter.to_dict()` 格式的事实映射、来源绑定审核和召回词。显式 `--verify-existing-goal --candidate-id ID --state-root DIR` 才启用具体目标核验及既有统筹账本托付。

2026-10-24 的工程测试使用明示合成卡库/审核数据，运行了当时的分类拟合、两模型图偏好更新/恢复、图选择、目录绑定、填卡评分、计数目标及统筹网络/SQLite账本；这些是[历史工程报告](../reports/2026-10-24-construction-trainable.md)与[首次框架报告](../reports/2026-10-24-construction-logic.md)的成绩，不是本轮重新运行的训练或推理结果。
