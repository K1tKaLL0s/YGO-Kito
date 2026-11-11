# 模型、评价与服务接口

版本：2026-11-11。此处规定角色和数据流；CLI 参数及完整调用样例见 [Agent 操作说明](../development/generic-agent-integration.md)。

## 4 数据契约与来源责任

下列契约由现有模块承接。优先扩展已有 `CardCopy`、`FunctionEvidence`、`UseRequirement`、`RelationFact`、`ResourcePool` 及质量结果，不另建规则语言或存储系统。具体可调用符号及命令以当前源码和操作说明为准。

### 4.1 五种身份与收益归并

| 身份 | 含义与归并规则 |
| --- | --- |
| `effect_id` | 卡片规则身份、文本版本、效果作用域和稳定段落位置共同定位真实效果；不能只用可能重复的①②编号 |
| `function_id` | 规范语义：动作、来源与到达区域、自己/对方、成本/效果、随机/定向、结果和对象条件；数量、时点、次数作为结构化属性保存 |
| `score_family_id` | 对同一实际计分功能汇总全部来源的键；同义词、解析步骤、图节点和轴名称不能制造新家族 |
| `use_id` | 该效果以什么模式、在什么用途范围和条件下承担功能；用于表达替代、共同要求及强制影响 |
| `source_id` | 当前牌表的真实来源及必要时的副本身份；同名别名归组沿用已有卡库规则；不是一条报告或证明的 ID |

`benefit_id` 由规范计分功能和真实投入来源确定，基础/主题作为其通道。`scope_id`、`reason_code`、证据数量和图节点编号不进入创建另一份同源收益的键。一个来源在同一功能通道中只贡献一次；多条合法替代支撑以“或”支持这份贡献，只有所有替代都失败才撤销。

检索、确认对象、把对象加入手牌若属于同一次检索处理，只计一个检索功能；真实不同的堆墓和融合分别计分。随机堆墓、定向送墓、成本弃牌、因效果送墓触发不能被归并成同一语义。所谓组合增量只有存在已定价的真实功能时才建立收益身份，不能因增加一条关系便奖励联动分。

同一物理来源属于多个轴时，各轴可以展示参与关系，全局只归并一次。通常怪兽、必要搭档、指定素材和代价库存通过支撑关系起作用；有独立战斗或其他功能时才为该功能另建记录。

### 4.2 规范用途记录

`construction_layer_flow.normalize_function_uses` 从当前候选完整 Main/Extra/Side 和 `MechanismCatalog.effect_records` 生成以下逻辑结构，并结合宿主任务与识别提供的事实补齐。图负责用途组织与解释，不决定候选有哪些真实效果；轴外卡也要进入效果覆盖检查。

| 字段组 | 必需内容 |
| --- | --- |
| 身份与来源 | 上述五种身份、`benefit_id`、来源区域、副本或数量、原始效果引用、`evidence_refs` |
| 计量 | `valuation_mode=main_density/called`、同名组、受支持副本数量或副本状态；模式由可信适配器确定 |
| 用途范围 | `scope_id`、常驻或 Side 方向、`requirement_mode=configuration/all/any`、替代分支与依赖组 |
| 硬要求 | `requirement_ids`、`requirement_origin`、`required`、`requirement_status`；原任务或规则来源与组合方式分开 |
| 条件与资源 | 对象/素材谓词、区域/表里/事件/时点、完整代价、整数需求、效果次数键、限制作用范围、合法转移或回收事实 |
| 主题 | 待判定规则 ID、每个通道的语义命中与配套状态；不能直接信任模型给出的“主题卡”标签 |
| 必然影响 | 与正面用途绑定的 `mandatory_impacts`，受损收益/来源/通道及作用范围 |
| 事实状态 | `supported/failed/unknown`；与是否已处理的 `evaluated/deferred/not_applicable` 分开 |

`required` 不能因为一条效果自身存在 all 条件而自动为真。原任务必须共同取得的收益才进入硬要求；可选效果的 all 条件失败意味着该效果不能取得相应分数。外部对手目标与响应条件按固定用途情境解释，不要求从己方库存中找到。

`coverage` 单独记录每张卡、每个相关效果是否已读、是否完成规范化及缺口。已审阅且没有独立计分功能的空集合是合法结果；资产缺失、解析未覆盖和预算未读不能输出同样的空集合。粗功能标签已覆盖不代表具体条件、对象和完整素材已解析。

### 4.3 输入事实与输出损失分开

关系模块输出的是事实变化，不是金额。建议使用现有质量模块中的 `UseImpact` 结构表达 `affected_benefit_ids/source_ids/channel_ids`、`scope_id`、`stage`、`reason_codes`、`evidence_refs`、状态及受影响的有效投入。完整费用失败、共享资源和强制影响都先映射到具体用途，再由计分器重算金额。

旧 `QualityLoss.share` 是旧收益预算单位，不能直接当作对数分或新投入比例沿用。旧 `SlotUse(zone,card_id)` 不能表达同名副本差异，迁移为来源/用途支撑事实，不再产生 `slot_budget` 罚分。旧宿主只有无法无损转换的标量 loss 时返回 `legacy_loss_requires_semantic_rebind`，保留原记录供定位，不静默忽略，也不把该错误生成构筑负样本。

输入仍可使用 `quality_evidence` 这一现有宿主挂接点。基础事实由 ConstructionLayerAdapter 从真实牌表、现有资产和关系层默认生成，不要求外部调用者手填每张卡。宿主 hook 可补充版本化的、绑定候选的 `uses`、`impacts`、`coverage`、Side 情境和 unknown 约束；与已有事实冲突时显式报告，不能覆盖原任务或吞掉不利事实。历史 `generic_fits`、`duplicate_purposes`、`slot_uses`、`losses` 由适配层转换并校验。不能只把两个旧参数补传进旧百分制算法就宣布完成。

每个诊断引用统一生成的损失记录：`loss_id`、受损对象、通道、阶段、原因集合、前后投入、差值或区间、`accounted_by`、共同修复条件和修复后的可恢复分。浓度变化、同名折算等写为 `already_accounted_note`。`unpriced_effect` 记录尚无独立价格的资源负担，不写成“已确认零成本”。

### 4.4 唯一 Evaluation

`evaluate_quality` 保留为纯评价入口，读取同一候选的层结果、规范用途和固定政策，返回以下内容：

| 输出 | 内容 |
| --- | --- |
| 绑定 | 评价器/规范化版本、task、deck、logic、policy、资产/事实版本、评价范围；复用现有摘要机制 |
| 总分 | `score.unit=functional_log2`，`score.value/lower/upper`；value 只在数值已确定时提供 |
| 完整性 | `scope_complete`、相关未知、deferred、系统错误、保守界说明；不靠上下界相等推断完整 |
| 条件 | 原任务硬要求的 satisfied/failed/unknown 与来源；普通可选缺口另列 |
| 解释 | P/V1/V2/S、各功能基础及主题投入、各方向 R/X/增量、统一损失记录、未定价负担 |
| 消费索引 | 各卡/轴/泛用/组合到同一功能记录的引用，以及实际候选版本 |

一份候选记录保存 `deck`、`layer_evaluation`、`quality_evaluation`、评价状态及绑定。评价与排序期间各候选使用自己的结果。批次完成后保存最优构筑及评价，其他候选只保留标识、状态、分值和比较记录。`total.value/min/max` 若因兼容保留，只能是新 `score` 的同值投影并显式带单位，不能维护第二套计算。

绑定分为共同口径与候选输入两部分：共同口径包含 task、policy、评价器、规范字典、资产和事实契约版本、评价范围；候选输入包含 deck、logic 和实际使用的事实内容。比较双方时要求共同口径一致，不要求不同牌表具有相同事实内容。`evaluation_id` 复用现有 digest 对绑定与规范结果生成，供保存和消费引用；无需另造文件校验台账。参考与候选各自绑定自己的输入，不能互换结果。

### 4.5 接口与宿主装配

`coordinator` 接收[任务原文](training-and-acceptance.md#三期课程与数量)。统筹侧用关键词和句式规则识别三期构筑任务受支持的中文、英文和日文表述，从输入中提取环境、指定或自主主题及构筑目标。统筹保留原文并把提取出的结构化任务交给 `build_goal`。遇到不支持的输入或环境矛盾时返回具体原因。统筹网络使用状态与预算提供调度建议，目标网络使用结构化任务的特征。

`build_goal` 交给 `build_optimizer` 的积木草案保留效果、连接件及配套需求。卡片所属字段使用 `field`，卡文限定对象和素材的字段分别使用 `selector_setcode` 和 `material_setcode`，同时保留相关区域和触发条件。优化模型按各自用途和实际卡文绑定具体卡片，未确认的配套保持未决。

以下为逻辑接口，实现可沿用现有签名并保持数据流和绑定。

```text
evaluate_quality(layer_evaluation, *, policy, facts) -> QualityEvaluation
compare_quality(before, after) -> QualityComparison
ConstructionLayerAdapter.evaluate(..., *, policy, quality_evidence=None)
    -> (selection_order, candidate_evaluations, trace)
construction_gate(..., quality=None, reference_quality=None) -> Gate
```

`candidate_evaluations[index]` 包含 `layer_evaluation`、`quality_evaluation`、`evaluation_status`；原来直接取两层结果的调用点统一改为读取该字段。`trace` 保存比较结果、已评/待评索引及预算原因，不再承载另一套总分。`quality_evidence(task, deck, layers)` 的签名保留，返回上一节定义的事实补充，统一适配后成为 `facts`。

宿主仍由 `source_binding.construction_quality_policy` 提供固定政策；增加 `construction_quality_reference` 承载指定参考的 ID、实际 deck、来源及环境绑定。它只在 reference_ratio 模式必需，与政策中的参考描述一致。由层适配器沿同一路径评价参考并存入当前构筑进度，再传给 gate。无参考模式显式不装配参考，不扫描候选池挑选替代标尺。

单个候选的事实范围来自自己的库存和共同宿主用途契约；同批其他候选的卡只能帮助复用只读资产索引，不能给它提供对象、材料、主题接收方或新增硬目标。改变批次组成不能改变同一候选的完整评价。

## 9 候选 反馈与学习的接线

### 9.1 评价必须先于质量选择

保留 `portfolio` 的有界候选生成、合法池过滤和依赖修复提案。生成预算只定义本轮提出了哪些候选，不是质量判断。模型分可以在生成前批量排序换卡方案，并安排待评顺序和预算，不再替代最终有效分。

`ConstructionLayerAdapter.evaluate` 改为：对已入本轮候选集合的每个候选完成绑定及层事实，组装规范用途，调用统一质量入口，然后调用统一比较器。旧 `compare_layer_candidates` 的缺口和优劣原因继续可用于诊断及修复建议，但不再产生最终质量优先边。

候选进入以下不同状态，不能互相偷换：

| 状态 | 用途 |
| --- | --- |
| 已完成、硬条件成立 | 进入按 S 的质量排序；可生成质量偏好样本；再由相对门槛决定准入 |
| 已完成、原任务硬条件失败 | 保留具体失败与修复方向；不成为准入候选，不伪装为一般低分样本 |
| 相关事实 unknown | 保留区间与决定性缺口，可安排局部核对；不填中点 |
| deferred / 预算未覆盖 | 保留候选、待评索引和原因；不填零、不算连续失败 |
| 配置/解析接口错误或绑定错误 | 返回可定位错误；不生成构筑负样本；已知语义资料不足仍用 unknown |

全部已生成且进入本轮比较的候选必须在最终排序和保留裁剪前取得自己的评价。预算耗尽时保存 `pending_candidates` 和评价游标；可以记录当前已评最优作为 working candidate，但结果标为选择尚未完成。只有剩余候选均已评价，或有可靠上界证明不会影响所需的前若干名，才能确定本轮最优构筑。这里不要求枚举所有可能牌表。

完整且硬条件成立的候选按 S 降序，真实同分才使用现有模型顺序和稳定候选索引。原有策略多样性可以用于生成和同分取舍，不能让更低 S 覆盖已确定的更高 S。本轮最优构筑保存自己的 Evaluation，所有候选各自完成静态评价和适用的参考比较。

`fill_with_existing` 提供本轮候选评价、比较、待评游标和选择状态，供 `construction_cycle` 消费。`construction_cycle` 直接使用该结果，不再在选中后另算 quality。静态构筑选择使用同一比较器。后续已获授权的真实对战部署比较保留原职责，其结果不得反写静态 S。

### 9.2 统一比较和反馈

`compare_quality(before,after)` 先校验双方任务、政策、评价器、范围、资产及事实口径一致，再比较最终 S。毛值 P、缺件数量、损失比例和模型 logits 不得决定新质量偏好。

比较结果包含双方评价身份、最终差值/区间、`preferred/equivalent/unresolved/incomparable`、硬条件状态和变化的功能引用。事实不足时，可提供有依据的区间优势用于核对优先级，但本次质量学习样本只取完整、硬条件成立的双方。系统错误不比较。

反馈显示 S、适用时的参考比例、本轮真实变化的功能通道、导致变化的来源与条件，以及可修复条件组。归因直接来自 Evaluation；另一个解释模型不能自造分值。各卡与轴的分摊只作展示，按有效输入比例分摊时各份额应回到该通道总分，不能再次累计为全局分。

### 9.3 学习标签与模型边界

`construction_learning.SOURCE` 迁移为 `construction_quality_preference_v2`。`comparisons/candidate_pairs/cycle_pairs/validate_pair` 读取新质量比较，继续使用已有成对偏好训练接口的 1/0 标签；1/0 只表示明确顺序，不表示胜率或 CB 成功。

每对样本绑定 task、双方 deck、双方 Evaluation、政策/评价器/事实版本和实际优化轮次。已完整评价的落选候选只保存严格偏好、分值与标识。已获授权的后续真实对战训练仍可使用最优构筑与既有部署构筑。沿用每轮限额、跨轮公平取样和去重；同一评价重复恢复或消费不重复增加更新。存在反向冲突的旧记录先检查版本和绑定，不投票决定真值。

选定构筑以有效分的已确认顺序为准，模型分只处理真实同分。`semantic_training.validate` 和现有监督投影接纳新 source 并验证评价绑定，不能继续接受一条旧 `layer_comparisons` 作为新质量标签。历史旧标签保留原版本，不混入新版课程样本。

本次不把最终 S 当作 BuildRanker 的预测输入，也不扩大网络规模。现有卡片与机制特征保持；新评价提供监督和修复反馈。若实施时确实改变已有机制向量的含义，必须走现有 feature/version 兼容检查，不能宣称权重布局相同便自动兼容。

真实参数更新、更新后的决策和 checkpoint 恢复闭环需在将来训练获准后验证；不能把样本契约接通写成模型已经学会。实际执行状态由独立报告记录。

## 10 准入 记录与恢复

### 10.1 准入条件

完整静态准入依次检查：当前牌表原有合法性；原任务明确必要能力及配套；要求的静态评价完整；新 Evaluation 的完整绑定；适用时的 80% 参考比例。高 S 不能抵消必要条件，普通可选功能失败也不能被升级为新的硬门槛。

`InventoryDependencies` 仍读取全候选库存。`known_deficits` 保留为所有相关缺口的诊断，gate 改为读取带 `requirement_origin` 的必要缺口，而不是看到任意缺件就拒绝。未获得潜在分的必需能力缺失仍会拒绝准入，其数值损失可以为零。

参考必须是事先指定且合法有效的牌表，使用同一政策和评价器重新评价。新政策不接受裸 `reference.score` 替代 Evaluation，不把参考重新标成 70。参考为零分、非法、缺失或不完整时给出具体参考状态；不除以零、不任选当前低分候选充当参考、不自动降级到无参考模式。

`construction_gate` 和 `CourseAdmissionPolicy.record_completed_construction` 读取最优构筑的同一份 Evaluation。记录入口缺该候选结果时标为待评价，不读取别的候选分，也不回退到旧七项评分。

相对门槛失败计数只累计已正常完成、确认低于比例门槛的构筑尝试。复读、重试、预算耗尽、unknown、配置或资产错误不增加次数。沿用现有 cycle/attempt 归属，连续两次确认不足后的主轴→副轴→泛用提示给功能和配套建议，不泄露参考的卡名配方或精确投入。CB 失败计数另行保留，不转为静态扣分。

### 10.2 恢复与政策变更

扩展现有 continuation 为 schema 3，保存当前候选、待评候选的评价状态、评价游标、参考结果、原目标骨架、交接链及优化游标。只在候选评价原子步骤完成后提交结果；暂停时保存尚未评价项，不发布半份完整分。

恢复先核对任务、牌表和交接链，再核对评价器、政策、功能字典、资产/事实、图及范围绑定。只有绑定一致的质量记录可复用。旧 v3 百分分、旧 gate 或事实版本变化导致的分数标为 stale，保留牌表和优化进度，作废旧通过状态，安排候选与参考同口径重评。

同一任务的宿主政策修订使用显式 `revise_quality_policy` 路径：记录新政策、作废旧质量/偏好/门槛缓存、保留原候选、骨架和游标、重评后再选择。模型不能调用此路径修改自己的评分条件。原任务身份变化不是政策修订，仍按现有契约拒绝错绑，不自动改任务。

schema 2 的新式单骨架 continuation 可按字段迁移为待重评状态；更早固定四阶段档案保留为历史，不恢复已删除的四阶段执行器。课程 006 的文件存在不代表新链已运行。迁移需保留其存档、暂停文件、checkpoint 和 latest 指针，按具体任务执行。

设备迁移通过显式宿主命令创建新的完整课程状态。普通 `CourseModels.from_state/restore_state` 继续验证原设备合同；`migrate_to_cuda` 先恢复合法 CPU 对象，再搬运参数、优化器和适配器，返回可按正常合同恢复的 CUDA 对象。迁移事件同时保留原课程及新设备边界，DataIndex、记录和反馈游标不能只靠模型权重文件代替。


## 决斗、统筹与外部 Agent

统筹通过固定角色的结构化协议托付候选、登记预测、租用任务与回收终局结果；模型建议不能覆盖程序的合法性、预算和状态判断。BuildTask、原目标、Main/Extra/Side、候选父版本、模型/LoRA、规则/卡池/禁表、合法观察、预算与错误原因贯穿交接。不同任务、候选或版本的结果不可互借。

预测在评估前登记，绑定候选、冻结决斗策略、对手分布、实际先后手、BO1/BO3单位及环境。终局结果幂等写入；冲突回执拒绝并回滚。修改候选保留父谱系，不能换 ID、调低预测或清空计数消除重构信号。操作失误、构筑缺陷、系统异常和未知归因分别返回；不能将全部输局交给构筑承担。

本地 Agent 使用 UTF-8 JSON Lines/stdio，信封含 schema_version、id、method、params，成功返回 ok/result，失败返回 ok:false/error.code/message。版本为1，id匹配 [A-Za-z0-9][A-Za-z0-9_-]{0,63}；单行不超过1 MiB。能力以 capabilities.methods 实际返回为准，不依赖外部厂商 SDK。

宿主固定 monitor、trainer、manager 或 opponent 角色；请求不能改角色。monitor只读，trainer控制训练，manager管理环境/牌表及构筑，opponent仅有合法单席位决斗和查卡能力。权限不是OS沙箱，宿主还须隔离对手不可读的台账、种子、双方牌表和全状态。RPC不得自行指定任意文件路径、打开原生验证或外部provider。

构筑生命周期为 construction.plan/run/start/continue/progress/cancel，服务与CLI使用相同kernel和存档语义。控制操作带 expected_revision；过期拒绝。相同id同参数幂等，换参数冲突；执行不确定返回不可自动重试。暂停/取消只影响该作业及其子进程，不终止无关进程。

训练状态 created/running/paused/completed/failed/stopped，revision单调递增。failed先recover再决定是否resume，running不能另起恢复者争抢存档，stopped/completed不作为直接续作候选。未配置后端明确报告；进程停止不能当作云实例已停止计费。缺失监测字段表示未采集，不填0。

四模型检查点保存权重、适配器、优化器/调度器、RNG、游标、任务、有效数据/规则版本和预算。布局相同但特征语义改变仍须兼容核对。只有成功结束的事务才计更新；半局或优化器结果不确定时在相应边界处理，不盲重放。

## 认知接口与实现定位

构筑基本认知读取完整卡文、实际投入、主题事实与关系；认知模块输出有来源的功能、轴/泛用及联动判断和未知，不能修改固定任务或可信卡效事实。无模型、未经训练、离线预测与已验证连接分别报告。原46例、full18及后续数据保留各自版本和留出边界，不用同一材料的训练成绩冒充泛化。

实际入口：autonomous_construction、construction_fill、construction_layer_flow、construction_quality、construction_progress、construction_service、construction_learning；决斗通过duel_model/duel_planning与合法动作适配器；统筹通过coordinator/coord_contracts/course_feedback；共享卡效通过MechanismCatalog.effect_records/effect_blocks。后续模块修改须同步真实消费者，不能只增加配置接口。
