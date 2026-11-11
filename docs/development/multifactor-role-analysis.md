# 多因子神经角色分析：独立增量

## 当前 v3 交付入口（2026-11-09）

第二次核查更新：先前“软件完成”结论已按实际源码进一步复核，旧入口残留和实现缺口已修复，包含结构化目标进入条件读出、真实双配置偏好和训练/评估绑定；当前入口、接口变更和删除清单以[核查报告](../reports/2026-11-09-axis-generic-review-cleanup.md)及[使用说明](axis-generic-software-v3.md)为准。带执行拦截的 177 项检查全部通过，实际能力阶段仍未运行。

首轮软件补齐交付了 M1–M7 及 T1–T5 所需的训练控制、分组校准/独立评估、逐能力宿主接线、环境三路适配及入口，当时 94 个不同方法最终通过、158 次物理执行，首次 3 项 error 已修复，见[历史完成报告](../reports/2026-11-09-axis-generic-software-completion.md)。本次进一步核查和修复后的结论以页首新报告为准。未变化的资源/分支等证据按原报告复用；真实准备、正式训练、CB/原生、CI 与实际能力发布仍未运行。

本节说明当前 v3。下方 v1/v2 原文、旧协议、分母、网络、命令和成绩保留为历史记录；它们不覆盖本节和主执行书。旧稿中的“尚未接入构筑”、旧五维输出及旧示例不能描述当前 v3 服务或充当当前运行证据。两份旧开发说明的既有正文保留。

### 输入、事实与学习记录

`contracts.RoleInput` 的 `axis-input-v3` 输入有 unit_analysis、deck_analysis、candidate_insert、state_evaluation 四模式。`DeckSpec` 保留真实 main/extra/side 数量，缺失区域为 unknown，已知空区与缺失区域分开；可见状态只能显式提供或保持 null。`LabelCell/LabelSet` 区分 known、unknown、conflict、not_applicable，未标注成员不补负，包的泛用标签不广播到单卡。

运行时与训练共用 `semantics.build_analysis_graph`。卡片/效果事实、费用、次数、区域、结构关系、逐功能成员与条件进入图；名字、卡号的身份编码、来源引用、监督答案不作为可学习身份特征。卡号仍用于连接实际实体和精确指名关系。自然候选允许重叠和有依据的父子供需关系；候选支持成员不等于已识别成员，评价成员全集不硬限于候选支持集，自然漏召回仍计漏检。

`functional_units.minimum_member_branches/assess_unit` 按所问功能分别解析成员、替代分支和条件；共用 `conditions.solve_requirements` 进行有界整数资源分配，构筑的有限适配也委托该核心。分支不拼接，未知资源/预算不足不伪装为确定失败。完整单元定义、当前接收实例的结构完整性和局面 readiness 各自输出；Side 不直接提供当前 Main/Extra 伴随件。

学习记录分为 observations、targets、supervision、provenance。来源关联先传递合并再划分和派生；支持 unseen_deck、unseen_receiver、unseen_card、cross_period 四种协议。未知标签不进入损失，来源和证据权重分开，零监督/零证据批次跳过前向和更新。训练专用虚拟查询只在显式 `supervision.training_queries` 中使用，默认推理和自然候选评价忽略它。

### 网络、准备与恢复

显式 `NetworkConfig.v3()` 使用 64 维、两轮、双流、路线特征关闭；保留独立的单/双流与路线开关，旧 `NetworkConfig()` 默认仍属于旧特征路径，不能省略 v3 选择。18 个可学习任务覆盖机制、成员、功能角色、贡献、位置/来源、迁移性、接收兼容、有向关系、副本偏好和旧语义任务。carrier/enhancer 分格，core/support 可并存；large/small 没有可靠映射时保持 unknown，不设新张数阈值。

`training/axis_generic/prepare_v3.py` 提供独立新版准备入口和语义缓存，`train_v3.py` 接通逐格训练、开发选模与恢复。原配置、旧标签、runs 和权重保留。M5 的条件范围特征改变缓存身份，后续应在新目录准备匹配数据；旧 core/support 所需观察/标签的覆盖缺口尚未补齐，继续 unknown。本批没有准备数据或调用训练入口。

v3 checkpoint 单独绑定实验、架构、受控特征、任务/标签协议、资料、来源划分、配方、Adam、随机状态和采样/选模游标。resume 要求同实验完整相容；warm_start 只复制明确相容的共享图编码器，重建输出头、优化器、游标和能力计数。旧权重按原源码绑定保留，不关闭检查强行兼容。`config.train.v3.json` 中 formal_training、automatic_lora、core_course_resumed 仍为 false。

### 三个服务与输出

宿主通过 `RoleAnalyzer(fact_provider, scorer=..., capabilities=..., budget=...)` 注入已有事实和可选评分，服务不自动创建或加载模型。请求使用 `AnalysisRequestContext`，保留规则/时期/格式、明确目标、off/observe/assist、公共资源覆盖、可见状态和可选抽样，不接收监督/标签区块。

| 入口 | 返回与实际处理 |
|---|---|
| `analyze_deck(deck, context)` | 返回 `DeckAnalysis`，含单元、功能、成员查询、条件/资源、分区浓度、能力、未知及解释依据 |
| `assess_unit(unit, receiver_deck, context, requested_function)` | 返回 `UnitAssessment`，分别评价完整定义和接收实例；未提供 receiver 不虚构兼容性 |
| `compare_copy_change(base_deck, add_card, remove_card, functions, context)` | 返回 `CopyComparison`；add/remove 各声明区域与数量，分别重观察前后完整配置、构图、重算库存/依赖/调用/资源冲突及实际分母 |

移除不足或修改未知区域会在 provider 前拒绝。remove=null 是实际增加，add=null 是实际减量；无替代对象或可靠比较证据时整体偏好 unknown。只有显式声明单次均匀初始抽样、区域与抽数时，才复用已有单卡接触率；它不等于联合功能成功率。外部 legality 必须绑定确切配置、目标、规则/上下文、producer/version 和证据，缺失或不匹配为 unknown。

`CandidateScorer.score_graph` 在整头预算通过后以 32 查询分块遍历，不把 32 当候选总上限。单头失败只停该头；候选枚举溢出时相关头不应用。raw_prediction、calibrated_scores、applied_prediction 分开；校准器需宿主显式注入，未拟合时没有默认阈值或 argmax 代替校准。

### 模式、能力与真实消费者

构筑 `build_axis_skeleton/fill_with_existing/construction_cycle` 的可选参数为 `recognition_provider`、`recognition_mode`，默认 off。服务 `AnalysisRequestContext.mode` 默认 observe；两种入口的默认分别保留。

| 模式 | 当前消费行为 |
|---|---|
| off | 不触及识别 provider 或模型，沿用原构筑路径 |
| observe | 在整个构筑切片的排序、分值、学习输入、停止原因、gate 和 CB 授权确定后追加记录；不把观察耗时计入优化/CB 决策预算，不写学习候选或 session 反馈 |
| assist | 仅传递有实际数据和明确能力依据的事实；版本化宿主 `layer_policy(task, deck, layers, facts)` 可映射到既有功能质量证据，再由原规范化器/evaluator/gate 处理；默认没有自动采用新头的政策 |

无 scorer 时学习能力为 unavailable，有 scorer 但未发布时默认 untrained。训练/弱监督未校准状态只能作 raw 诊断；available 要求显式 validated、calibrated、producer/version 和证据。state_readiness、function_facts、requirements 默认 deterministic_only，默认未 validated，进入 assist 也要有宿主验证依据。environment_value 默认 disabled，只有独立环境支路、相容校准和真实验证工件构造的显式 environment_provider 才能提供输出，单传能力开关不能开启。当前没有发布真实学习能力；校准拟合与宿主绑定源码已补齐，仍由宿主显式选择工件。

识别层不新增 losses/slot_uses、私有分值或构筑定价，不覆盖原有证据，不切换生产 QUALITY_VERSION。CB 提示只给显式声明 `accepts_recognition_hints=True` 的 provider，内容为候选、资源、分支、时序和缺件；提示的 legality/route_success 保持 unknown，实际 CB 执行授权和规则验证权威不变。统筹读取原阶段结果，不改网络、调度或数据库。

### CLI 与当前验证边界

事实 CLI 必须显式提供 `--service analyze_deck|assess_unit|compare_copy_change`，只接受 `axis-service-request-v3`，延迟导入且不构造/加载模型，也不接受 checkpoint/adapter；服务神经评分由宿主注入。旧 `multifactor-candidates-v2` 神经 CLI 及其 checkpoint/adapter 参数已删除，神经批量预测统一使用 `training.axis_generic.workflow_v3 predict`。本次已执行五个现行入口的 help、人工文件 CLI 往返及旧参数拒绝检查；下方 v1/v2 示例只保留历史说明，不能作为当前训练或预测命令。

M7 初次文档交付时没有执行运行验收；之后 Q1–Q5/V10 及本次整个模块的软件检查已完成。A01–A10 与 V01–V30 的工程证据按历史报告和本次完成报告读取，包括纯 CB hints 与环境基础路径不变性。T1–T5 的源码、配置和接口已交付，实际资料准备、正式训练、真实消融/校准/独立能力评估、环境真实反馈训练及发布仍未运行。历史/活动权重、活动指针和暂停状态保持。

## v1/v2 历史实现记录

**当前 v2**：[最小功能单元与 LoRA](multifactor-functional-units-and-lora.md)补充用户确认的严格联动泛用定义、必要配套/成员接口、开发标注契约与可选适配器；该页优先于本文 v1 实现记录。当前协议为 `user-confirmed-functional-unit-v2`，输入与基础 checkpoint 为 v2，未训练公开概率/评分为 null；v1 的原始交付与受测字节保留在提交 `ddaf81e`。

本模块位于 `ygo_kito.multifactor`，只消费版本化数据契约。它不导入未合并的效果或构筑模块，不接入活跃构筑循环，不改变已有规则验证，也不成为既定修复/训练的新增前置条件。本轮交付可训练代码与工程证据；没有正式训练、角色能力验收或生产权重。

## 标签、对象和目标

角色是给定目标、当前构筑、资源预算和候选包时的操作性描述，不宣称唯一官方标准。**大轴不等于主轴，小轴不等于辅助。** 占用规模、策略核心性、依赖强度分别保留；较大组件也可服务另一核心，小组件也可能不可替代。当前工作协议 `working-size-centrality-utility-v1` 对机制组给五个独立标签，允许跨维度重叠：

* `large_axis`：相对当前构筑预算与比较集合，占用规模较大的机制组。卡位、额外占用、必要废件与通召负担作为证据，不指定通用张数阈值。
* `small_axis`：相对相同预算与比较集合，占用规模较小的机制组；规模小不表示依赖弱或贡献低。
* `strategic_core`：承担当前主要目标、启动及资源循环骨架，移除后产生显著目标损失的程度；损失尚未测量时保留未知。
* `support_role`：以局部组合补充目标、启动/续航/交互而主要路径由其他组承担的程度；这一组可以规模很大。局部依赖、废件和占用需一起评估。
* `generic_utility`：在不同主要骨架中能以相对独立的条件提供当前所需功能的程度；有字段也可泛用，泛用也有代价、自肃及不适配情境。

人工标注须冻结原目标、时期、具体候选包/数量、主/额外预算及用于比较规模的组件集合，先单独记连续规模和依赖因子，再分别判断五个标签。`large_axis/small_axis` 仅用于已有机制边界的组，不把任何少量卡自动称为轴；中间规模、定义歧义、未测贡献或跨骨架证据不足均可填 null。独立标注者各自打软标签并记录分歧、来源及干预范围，不用多数票强造唯一真值。新增项目可调整这套工作定义，须保存自己的协议正文和 SHA256；`Supervision`、`RoleTrainer`、评分及 checkpoint 同时绑定该摘要，不同协议的角色标签拒绝混训或静默恢复。

未知标签不等于负例；没有被选中也不自动等于负例。角色监督不足时可以仅学可测的适配性或成对偏好，不从卡名、字段、出现频次捏造角色真值。例如同一八张组件可以是一个目标下的较大核心，也可以是在另一核心旁的较大支援；目标变化无需强迫其规模标签反转。

输入是机制组的集合与有向关系；单卡可作为单元素组。多卡包在上游按具体版本/数量汇总证据，内部机制可拆成节点关系；成员引用只用于追溯，不进入网络。效果识别、启动可达性、独立性、内外依赖、必要废件、检索/回收闭环、成本收益、自肃冲突、目标贡献及主/额外空间分开输入。每项有值、可靠度、不确定度和来源；缺测显式保留。所有数值归一到 [0,1]，具体分母由契约固定。

模型以共享节点编码、两轮有向关系消息、对称 mean/sum 集合池化产生上下文表示，无卡 ID、名称、字段代码、节点位置或牌表频率嵌入。sum 保留集合占用/重数信息。节点输出对重排等变，集合输出不变，成对兼容性对两端对称；有向依赖仍分别聚合。独立 sigmoid 角色头、适配性头与效用头允许同包随上下文改变。网络参数只是可学习表达，随机初始概率没有语义保证。

目标为已观察标签的 masked BCE（角色与兼容性）以及同上下文、同口径成对候选的 `softplus`/logistic 偏好损失。角色分量不做 softmax。证据不足、超预算搜索、引擎未支持均保留未知，不作为失败监督。样本更新测试仅证明损失、梯度和恢复路径可运行。

对每个已激活监督头，先对所有已观察项平均 BCE，再对有监督的头取均值；null 项不进分母。成对效用使用 `BCEWithLogits(u_left - u_right, preferred_left)`，不把偏好变成单卡角色标签。角色各维单独记录是否有过真实/工程监督更新；即使其他角色维被更新，未标注的泛用维也不会被声称已训练。`trained_uncalibrated` 仅表示该输出有过声明为真实来源的优化更新，不表示质量达标或理解成立。

## 数值契约

所有通道依次为 `[value * confidence, known, confidence, uncertainty]`。known 是是否提供观察，confidence 是来源可靠度，uncertainty 是该观察的未决程度。未知值为 null、可靠度 0、不确定度 1；实测零有正可靠度和已评估的不确定度。来源、成员 ID、名字、注释及上下文引用只作追溯，均不数值化。

| 因子组 | v1 数值口径 |
| --- | --- |
| 主/额外空间与剩余空间 | 具体数量分别除以 60 和 15；不是当前卡组大小的比例。当前预算同时体现在上下文与来源中。 |
| 可达性、独立性、内部/外部依赖、废件 | 冻结试验分布、目标、预算下的频率或比例，来源须保留分子/分母及干预定义；未采集不填零。 |
| 通常召唤负担/余量 | 消耗或剩余次数除以本试验明示的可用通常召唤预算；额外召唤能力未核实时不猜分母。 |
| 检索可达、回收闭环、目标贡献、锁风险、功能效用 | 当前目标下的测量/人工有序评分，使用同一被冻结的评估口径；原始证据和量尺进入 context_ref 所指材料。 |
| resource_cost / resource_return | 源侧固定资源账本中消耗/增加的卡资源数量除以 10；超范围须源侧显式截断并注明。LP 等异质资源不能直接当张数，v1 无一致换算时留未知并保留注释。 |
| 目标权重、缺口、先手权重 | 宿主显式提供的 [0,1] 意图或已测缺口；不按主题名称自动生成。 |
| 已识别效果与关系 | 正观察为 1；有明确范围的否定观察才可为 0。未看到关键词或未列边不等于没有效果/依赖。 |

v1 不自动从文本估计以上量尺；不兼容的测量协议须分开数据/模型或升级特征版本，不能把不同单位的数静默混训。效果快照适配器的可靠度默认 0、不确定度默认 1，调用方有审核依据时显式提供，库不虚构 50% 的解析器准确率。费用、次数、作用主体/区域和自肃作用域还保留在观察注释中；压成部分因子没有把完整效果语言变成已解决问题。

## 监督来源与防泄漏

1. 卡效来源：使用版本绑定的已识别操作与明确未知项；文本观察只能提供功能因子，不能自己产生主/辅/泛用标签。保留费用/处理、主体、次数及自肃作用域；缺来源不构造已知因子。
2. 引擎验证：在合法自生成候选上，记录固定起手分布、目标、规则/脚本版本下的可达次数/总数、消耗、废件及依赖干预。由这些记录生成相应因子或局部兼容性标签；成功的单条路线不等于整体稳定性。既有验证器未支持时不补猜。
3. 合法候选：在宿主已有合法范围中增删/替换单卡或整个包，固定目标、预算、决斗驾驶模型和对手分布做配对。整体胜负/表现只监督整个候选效用，不能直接归因到某张卡的角色。
4. 真实反馈：人工基于明确标签定义给多标签、分歧和未知；固定驾驶者的真实配对反馈给偏好。程序检查来源种类、train 分区及训练作用域；来源字符串不代替上游真实审核。

拒绝把 reference/opponent/外部热门成品牌表作为此 learner 的监督来源。库中不包含外部牌表、牌频统计或卡 ID 词表。ID/名字/来源重命名张量应完全一致。协同需要机制关系和干预测量；共同出现、同字段、同包名均不是效果可达或正协同标签。

每份输入还应冻结“评分当时可获得”的证据截止点。用于计算训练/最终评估标签的同批赛果、隐藏信息、事后移除贡献或留出骨架统计，不能反灌成该次评分特征；预先可得的公开效果、同预算合法探针摘要和既有在线反馈才可用。部署时缺少的因子在训练也应按同样缺测方式处理。当前库检查类型/用途声明并记录摘要，不认证来源字符串，也没有跨数据集的全局防重标登记器；生产数据隔离仍由宿主现有索引和审核负责。

## 早期泛用补位与宿主接口

宿主先保留原始目标/时期/卡池/数量硬约束，从已识别的交互、解场、续航或启动缺口召回有来源的单卡/机制包，再构造每个候选加入当前部分构筑后的同上下文输入。独立评分器只接受这组显式候选与召回来源；没有枚举全池或按卡 ID 兜底补容量的代码。必要废件、额外占用、通常召唤竞争和锁冲突可压低适配性，不能被“泛用”标签豁免。

`score_candidates()` 返回保持输入顺序的候选记录，绑定上下文引用、目标节点、外部合法性状态、角色概率、上下文兼容性、原始效用和因子解释。未训练/仅工程样本更新时 advisory score 为 null；合法性 unknown/fail 也不输出可用评分。完成真实监督更新后分数仍是未校准建议，由宿主自己组合已有目标/优化评分并继续调用规则/引擎。分数不能授权动作、证明合法 CB 或替换规则结果；函数不自动挑选或注入牌表。

默认只有候选效用头有真实监督更新，且所需启动/目标贡献/锁风险因子具有有效观察、上下文有可靠观察、外部合法性 pass 时才给 advisory_score。其他头的随机输出不会参与该分数，各角色维状态单列。这是本独立分析接口对输出的诚实标识，不是既有构筑/训练的新准入流程。`legality_ref` 是宿主验证记录的引用，库不认证其真实性或擅自扩大验证范围。

解释同时给原始已知/未知因子及逐项置未知的局部输出差；这是模型敏感性，不是因果证明。输入不确定度、覆盖率和未校准状态分别报告，不把概率熵冒充认识不确定性。

## 独立验证设计与当前边界

* 结构性质：节点/边重排、批次 padding、成员/来源/ID 重命名、已知零与未知、关系方向、兼容性对称、序列化和下一次优化恢复。它们检验程序性质，不证明角色理解。
* 模拟因子例：有意识地构造同数量但不同依赖/自肃、同包不同目标，以及未知和明确失败对照。只做有限工程更新/梯度测试，不把同批手工标签拟合与测试称为独立能力验证。
* 真实卡效例：仅测官方卡文经人工局部识别后进入契约的语义边界，未训练角色头，也不声称执行真实引擎。完整卡文理解、裁定、历史卡池资格另由宿主处理。
* 未见主题：按机制家族/主题和卡身份分组留出，所有同包的数量变体、改名、上下文反事实放在同一独立分区；训练、调参、最终评估分开。增加跨机制组合留出，防止只记包的功能指纹。比较无关系/仅数量/打乱关系基线，报告多标签 PR、Brier/ECE、选择性覆盖和偏好准确率。
* 同包不同角色：在从未参与训练的包上，分别冻结主目标构筑和外挂补充构筑，由独立标注者及引擎干预记录确认角色/贡献变化；目标不变而只改显示名的对照应不变。标签和测量来自独立人员/运行，不能重用训练手工真值。
* 泛用迁移：在留出骨架的早期构筑缺口上评估候选召回覆盖、合法通过率、所需功能增益、废件/占用和固定驾驶者配对结果。比较宿主原补位路径；拒判计入覆盖损失，不挑有利案例。

上述能力验证本轮均未运行。当前没有高质量上下文角色标注集，没有引擎干预采集器，也没有正式训练或校准结果。模块交付完整；模型学会区分主/辅/泛用仍待这些真实监督与独立验证。

## 对接观察

2026-10-28 读取共享快照 `fefd44c` 的原训练设计，以及效果窗口 `0850819` 的 `CardSemantics.to_dict()` / `EffectSemantics`（`public-effect-clauses-v2`）和构筑窗口 `041c72b` 的 `BuildTask` / `FillProposal` / `construction_candidates`。它们不是本模块的运行依赖，后续提交也不能假定已经部署。效果适配器只接收 dict 快照；数量/空间/可达性须调用方用当前资产补充。`construction_mechanism_groups()` 的 group_id/zones/source 可由宿主映射到本模块节点，不能从其存在推导角色真值。

原需求依据：[训练设计复核](../plans/2026-10-27-training-design-reconciled.md)、[构筑逻辑](construction-logic.md)。本次只新增专属包、测试、说明及本地证据，不改四个活跃模型/管线或原 checkpoint。

## 调用与恢复

使用现有 PyTorch，无新增安装、模型下载或外部服务。Python 接口：

```python
from ygo_kito.multifactor import RoleInput
from ygo_kito.multifactor.scoring import Candidate, CandidateScorer
from ygo_kito.multifactor.training import RoleTrainer

example = RoleInput.from_dict(host_exported_factor_input)
candidate = Candidate(
    candidate_ref="host-candidate-17", example=example,
    target_key="host-package-key", recall_source="host-interaction-gap-recall",
    legality="unknown",  # 从宿主规则结果读取；示例不冒充通过
)
trainer = RoleTrainer()  # 独立、随机初始，advisory_score 为 null
scores = CandidateScorer(trainer).score_candidates((candidate,))
trainer.save("roles.pt", data_cursor="host-data-revision:next-row")
restored = RoleTrainer.load("roles.pt")
```

`Targets.roles` 的顺序取自 `contracts.ROLES`。`train_supervised(examples, targets, sources)` 与 `train_preference(left, right, ...)` 是供宿主显式调用的训练接口，本次不会自动运行正式训练。checkpoint 同时保存模型、Adam、分头/分角色更新计数、数据滚动摘要、宿主游标、标签协议摘要及代码/特征绑定。模块使用确定性无 dropout 操作，初始化隔离 RNG；恢复不污染宿主 RNG。代码/特征/角色协议不同则明确拒绝隐式迁移。

独立 CLI 不提供训练命令；样例完全合成，包含的数据不是可用牌表：

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONDONTWRITEBYTECODE = "1"
& N:\YGO-Kito\_local_cpu_20261027\venv\Scripts\python.exe -m ygo_kito.multifactor --input docs/examples/multifactor-candidates-v1.json --output .cache/multifactor-demo.json
& N:\YGO-Kito\_local_cpu_20261027\venv\Scripts\python.exe scripts/check_multifactor_roles.py --output .cache/multifactor-check
```

JSON 输入为 `multifactor-candidates-v1`，每项使用 `Candidate.to_dict()/from_dict()`；输出为 `multifactor-scores-v1`。可选 `--checkpoint` 只加载本模块显式工件，不读取活跃构筑 checkpoint。自定义协议用 `--label-protocol-sha256` 明示期望值。测试入口仅列名加载本模块三个测试文件，不运行 discovery、原生测试或活跃构筑流程；临时工件放在本 worktree 的 `.cache`。

真实卡效样例的一手依据是 Konami 当前英文卡文：[灰流丽](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=12950&ope=2&request_locale=en)、[强欲而贪欲之壶](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=12465&ope=2&request_locale=en)、[烙印融合](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=17066&ope=2&request_locale=en)。样例是人工局部结构化摘要，完整卡文哈希为 null，不能冒称由生产解析器处理过全文或已核 OCG 历史资格；运行测试无需联网。
