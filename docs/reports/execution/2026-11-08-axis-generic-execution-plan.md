# 轴与泛用识别模块执行方案与机械执行书

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

设计核查更新（2026-11-09）：已根据用户本轮要求继续审查源码、修复缺口并清理旧入口，见[核查执行书](2026-11-09-axis-generic-review-cleanup.md)与[结果](../2026-11-09-axis-generic-review-cleanup.md)。当前准备、训练、神经工作流、环境入口和配置以[使用说明](../../development/axis-generic-software-v3.md)为准，下方历史入口/配置不再执行。

软件完成更新（2026-11-09）：主进程已补齐整个模块至 T1–T5 的源码、配置、CLI/API、纯 CB 提示契约及允许的工程验收。本轮 94 个不同方法最终通过，158 次执行，首次 3 项 error 已闭合，禁止调用为 0。见[完成报告](../2026-11-09-axis-generic-software-completion.md)和[当前使用说明](../../development/axis-generic-software-v3.md)。下文阶段状态保留制定/各批次历史；“T 阶段未开始”仅继续适用于被禁止的真实运行，不再表示其软件未实现。

最新范围修正（2026-11-09）：用户明确要求主进程自主完成整个模块的源码与允许的工程交付，不以 M7 收尾为终点；并已真实回答保留“正式训练、真实资料准备、CB、原生引擎、CI”运行禁令。T1–T5 所需代码与工程夹具验收继续自主补齐，真实运行/模型能力另列未验证。新阶段目标、当前证据和初步代码缺口见[整个模块软件交付接续](../2026-11-09-axis-generic-module-software-handoff.md)；下方“当前授权内已完成”描述截至 V10 的 M7 选定范围，不表示整个模块软件已完成。

建立日期：2026-11-08；状态更新：2026-11-09，香港时间。当前状态：M0 已完成，M1–M6 代码及 M7 文档/专用源码已交付；Q1 13 项、Q2 30 项、Q3 35 项、Q4 事实路径 54 项、神经编码/预测/评分 25 项、Q5 30 项及 V10 补充 5 项，共 192 个不同方法已有通过结果，累计实际执行 231 次。当前授权内选定工程目标已完成；此前对应 CPU 前向/反向、工程更新和临时 checkpoint 保存恢复已执行，本批 V10 无模型或更新。正式训练、真实资料准备、CB provider/搜索、原生引擎或 CI 未执行，M7 整体仍按 CB 等剩余范围登记。实施记录见[首批报告](../2026-11-08-axis-generic-m0-m2.md)、[M3 报告](../2026-11-08-axis-generic-m3.md)、[M4 报告](../2026-11-09-axis-generic-m4.md)、[M5 报告](../2026-11-09-axis-generic-m5.md)、[M6 报告](../2026-11-09-axis-generic-m6.md)、[M7 报告](../2026-11-09-axis-generic-m7.md)、[Q1/Q2 实际验收](../2026-11-09-axis-generic-m7-q1q2.md)、[Q3/Q4 事实路径记录](../2026-11-09-axis-generic-m7-q3q4-facts.md)、[Q4 神经实际验收](../2026-11-09-axis-generic-m7-q4-neural.md)、[Q5 实际验收](../2026-11-09-axis-generic-m7-q5.md)及[V10 实际验收](../2026-11-09-axis-generic-m7-v10.md)。下文原第 2–8 节保留制定时的设计/状态，当前实际结果以最新报告为准。

M6 已按用户明确授权由主进程实施，修改前交付[M6 机械执行补充](2026-11-09-axis-generic-m6-execution-supplement.md)。三个分析服务、能力/输出 DTO、可选评分、事实 CLI 与 off/observe/assist 消费者源码已接通；新增 37 个测试方法源码，执行数 0。构筑共享接口已按并行第九批的当前源码核对并保留；生产定价、权重、暂停和活动指针未切换。A09/A10 与 V23–V27 仍待运行验证。M7 首批实施文档交付和限定文本核对，T1–T5 未开始。后续交接指定 gpt-6.1-sol、推理强度 MAX。

M7 首批按用户授权在交付[文档批机械执行补充](2026-11-09-axis-generic-m7-execution-supplement.md)后直接执行：同步[当前开发入口](../../development/multifactor-role-analysis.md)、v2 历史说明和 MASTER，登记 A01–A10、V01–V30 对应位置及能力状态。后续按最新明确授权先交付[四项专用用例机械执行补充](2026-11-09-axis-generic-m7-coverage-execution-supplement.md)，再补齐 V11/V12/V16/V21 五个方法源码；原专用源码缺口已补，运行仍待验证。全部 A 项及 M7 测试/集成验收仍未执行。

后续 Q1/Q2 已按最新授权先交付[验收机械补充](2026-11-09-axis-generic-m7-q1q2-execution-supplement.md)再执行：Q1 13 个、Q2 30 个均首次通过，失败/错误/skip 和模型/更新/加载拦截尝试均为 0；新增 V11/V12 工程断言已通过，无源码修复。上段的未运行状态描述前批，V16/V21 与其他未执行子范围仍待验证。后续由主进程按授权自主安排，明确禁令保持，M7 整体验收未完成。

随后按自主安排授权先交付[Q3/Q4 事实路径补充及精确修复增量](2026-11-09-axis-generic-m7-q3q4-facts-execution-supplement.md)，完成 Q3 35 项（含 V21 四格子进程）和 Q4 54 项事实/接线路径。实际修复一处 assist 无既有证据时的 `{}` 中性回退，以及 UTF-8 读取、计时/Mock 和本地发动句夹具；首轮及各次复验保留，共实际执行 166 次，132 个不同方法取得通过结果。V16、Q4 神经评分/预测、Q5 和 CB 接口排除项仍未运行；整个 M7 尚未完成。

前批按用户明确放行对应模型前向的授权，先交付[Q4 神经机械执行补充](2026-11-09-axis-generic-m7-q4-neural-execution-supplement.md)，再由主进程执行 11 个 v3 图方法、6 个旧网络性质、4 个既有评分方法和 4 个新增无更新方法。25 项首次全部通过，0 failure/error/skip、禁止动作尝试为空，无生产或既有测试源码修复；累计 157 个不同方法、191 次物理执行。实际前向验证完整查询分块、候选支持集外成员和完整前后副本评分，参数/优化器/计数/steps/模式不变。此前“未前向/剩余神经 Q4”描述各旧批次；当时 Q5、V16 梯度、CB 和真实资料/能力阶段继续待验证。

前批按用户明确工程更新/保存恢复授权，先交付[Q5 机械补充](2026-11-09-axis-generic-m7-q5-execution-supplement.md)，初选 29 项实际运行后为两处真实失败先交付精确增量，再修复 Windows no-replace 保存路径和旧 LabelCell 断言，并新增并发目标保护对照。最终 30 个不同方法通过、物理执行 35 次；累计 187/226。V16 双正格梯度、掩码/弱证据、严格恢复/下一步更新/warm_start/游标均有通过证据；实际工程 Adam step 22 次、torch.save/load 16/14 次，全在本任务临时范围。首轮 1 failure/4 error 与复验保留，没有重跑原已通过 24 项或前批集合。

最新按对应测试和自主续办授权，先交付[V10 机械补充](2026-11-09-axis-generic-m7-v10-execution-supplement.md)，补齐并运行回收时点/来源、别名有限库存、未知观察、占用释放及同名额度五个专用方法。5/5 首次通过，0 failure/error/skip/禁止动作，无生产或既有测试修改；累计 192/231。V10 原单独运行证据缺口已闭合，不再列作下一步。

实施目录：`N:\YGO-Kito\_publish_20261030`。本轮只读确认分支为 `codex/optimization-20261031`、HEAD 为 `3f57198`。下文文件路径除完整路径外，均相对此实施目录。

## 1. 目标、当前授权与交付范围

当前用户明确允许对应测试及必要导入、后续由主进程自主安排直到目标完成；不启用子代理，保留全部现有改动。先前 Q5 工程前向/反向/更新/保存恢复授权继续有效，Q1–Q5 选定范围已有通过结果。本批补齐并通过 V10 五个纯资源专用方法，无生产或既有测试修改；当前授权内选定工程目标已完成。正式训练、真实资料准备、CB provider/搜索、原生引擎和 CI 仍禁止；配置、真实资料、既有/活动权重及暂停状态不变，CB 等范围继续待验证，T1–T5 未开始。

开发目标是把现有识别模块接成一条完整链路：真实牌表、单元与效果事实 → 分支成员和资源需求 → 允许重叠的轴候选 → 多任务识别 → 带证据状态的分析服务 → 构筑与 CB 的明确消费者。沿用小型图网络和已有事实解析，不把角色识别重写成卡名规则表。

本计划覆盖新版输入与标签契约、条件求解、候选轴、学习输入与输出、数据准备与评估、三个分析接口，以及构筑侧最小接线。决斗模型、统筹模型的新设计和构筑收益定价由原任务及构筑任务负责。环境 LoRA 保留后续阶段，不用静态牌表频率代替环境监督。

实施由本聊天主进程顺序执行，不启动子代理，不涉及 UI。执行书本身不增设审批。原方案阶段及 M0–M6 已按各批后续授权实施，当前范围包括 M7 文档/专用用例补齐、Q1–Q5 选定工程验收、实际失败修复和限定差异检查。工程更新与保存恢复按本批明确授权执行，正式训练等禁令保持，方案内的命令和设计文件内的操作描述均不自动解除禁令。

主要依据：

- [项目状态审阅与交接](N:/YGO-Kito/_publish_20261030/docs/reports/2026-11-08-project-state-review-and-handoff.md)，重点第 5、8 节。
- [11 月 4 日识别完整优化方案提取稿](N:/YGO-Kito/.cache/docx-extract/scheme.txt)，作为详细设计来源；其中旧实现描述以当前源码和交接报告修正。
- [代码执行细则](C:/Users/27499/.codex/instructions/code-work.md)及实施目录 `AGENTS.md`。当前工程测试/前向/反向/更新/保存恢复授权与正式训练等禁令优先于仓库内历史运行授权。

## 2. 已核对的实现基线

本轮使用静态文本读取核对以下位置，没有执行被读代码。历史训练结果直接承接交接报告，不重新加载 checkpoint。

| 对象与真实位置 | 当前行为 | 本次计划对应动作 |
|---|---|---|
| `multifactor/contracts.py:413` 的 `RoleInput` | 主加载器接受 `multifactor-input-v2` 和当前 v7，拒绝 v3 外壳 | 建立真实 v3 解析与序列化路径，旧版显式迁移 |
| `multifactor/analysis.py:40,90` 的 `DeckSpec`、`migrate_v2_input` | 分区默认空 tuple；迁移添加字段但不能交回现有加载器 | 区分未提供与已知空区，打通四种模式和可回读对象 |
| `multifactor/contracts.py:365` 的 `LabelCell` | 四种状态已存在，value 目前限于 0..1 数值 | 支持各头的值域；Targets、标注、损失与评估统一使用逐格契约 |
| `multifactor/training.py:55,202` | Targets 仍用 float/None；角色损失分母含证据权重 | 迁移旧目标，按已知格和来源组归一化，避免全弱证据批次抵消权重 |
| `multifactor/functional_units.py:141,165` | required 闭包；所有满足的 alternatives 合入 effective；成员角色仍主要来自 required | 为每个功能保留逐分支最小成员、递归替代依赖和独立实例判断 |
| `multifactor/conditions.py:89–149` | 单条供给匹配、all 贪心、any/at_least_k 不传播剩余库存，not 只读首个孩子 | 有界分支分配、整数聚合、三值逻辑及资源占用 |
| `multifactor/network.py:12,23,56` | 类默认宽 48；训练入口 `train_base.py:64` 显式采用宽 64、两轮消息传递；旧五角色及兼容/效用/配对头 | 新版本配置明确写 64/2，扩展输入及输出；旧配置仍按原值解释 |
| `multifactor/scoring.py:145–164,168` | core/support 已无 plan_known 硬清零，解释仍写旧门槛；默认候选成员只取 required | 修正说明与选定分支重查，结构事实和模型分数分开 |
| `multifactor/splits.py`、`metrics.py` | 来源键择一；F1 完全错误时可能为 None 并被宏平均排除 | 来源关系传递合并；固定类别口径，拒答和完全错误计入整体指标 |
| `training/axis_generic/prepare_base.py:63`、`config.json` | dataset.json 存在即返回；默认仍指 v7-repo-001 | 新协议检查语义清单，显式配置新输出目录，旧数据保持原状 |
| `multifactor/adapters.py` | 已承担 LoRA 生命周期与底座绑定 | 保留此职责，下游接线另设薄适配模块 |
| `construction_inventory.py`、`construction_relations.py` | 已有选择器、实际库存、效果来源、资源匹配、整数供给、条件关系与概率函数 | 复用这些事实与统计；共享分支分配核心只实现一份 |

表内 `multifactor/` 前缀均指 `src/ygo_kito/multifactor/`。源码行号仅用于定位本轮观察，执行时以符号和当前文件为准。

交接报告记录 v7-dev-expand3 已更新 620 次、v9-p0-smoke 已更新 149 次，两者均未通过旧基础模型替换条件；v9-p0-n2 只见准备产物。P0 已迁移 4700 个 actor-absent 标签格、剔除 1997 条 readiness-only 反例。这些是历史记录，不是本轮复测，也不是后续迁移必须凑出的固定数量。

工作树有大量既有修改、删除及未跟踪源码。交接时的 87/20/114 是当时状态，本轮未重新全量统计。不得依据 Git HEAD 覆盖当前文件，不恢复既有删除，不执行 reset、clean、stash 清场或建立丢失本地改动的新工作树。

## 3. 逐项验收目标

| ID | 目标行为与通过标准 |
|---|---|
| A01 | 四种模式均能解析、序列化、回读；已知空 Main/Extra/Side 与缺失区域保持区别；旧输入迁移不虚构牌表或局面 |
| A02 | 每个任务只用 known 且值域合法的标签格；unknown/conflict/not_applicable 不变成负例；未标注成员不自动成为非成员 |
| A03 | 改标签、reference、名字或追踪 ID 不改变学习张量；卡号只连接实体和精确指名关系；数量、区域、动作、费用和限制进入结构特征 |
| A04 | all/any/at_least_k/not 使用一致的整数资源分配；不同分支不拼接，同一资源不重复支付；观察不足、预算不足保持 unknown |
| A05 | 每个所评功能有自己的最小成员分支；完整包的可迁移性与当前实例完整性、可执行性分别输出；包标签不广播到单卡 |
| A06 | 候选轴由输入事实生成，支持共享成员和不同位置/来源；自然候选漏召回计入端到端漏检 |
| A07 | 新头的编码、逐格损失、能力状态和保存恢复贯通；旧五角色仅提供有定义依据的兼容摘要 |
| A08 | 来源关系传递合并后再划分和扩展；四类泛化协议有不同实际隔离条件；旧参考不伪装成独立最终测试 |
| A09 | 三个分析接口对实际完整配置返回功能、条件、资源及未知；副本变化重算真实分母与受影响关系，不私自给构筑扣分 |
| A10 | off/observe/assist 有实际消费者；observe 不影响候选选择、学习标签和准入；assist 仅启用已有相应证据的能力；旧权重和暂停状态保持完整 |

软件接口交付、工程验证、模型能力达标分别记录。训练和独立评估尚未发生时，允许交付已实现的程序，但模型头不能登记为已验证能力。

## 4. 确定采用的技术路线

### 4.1 输入、标签和输出边界

将 `DeckSpec`、`UnitSpec`、模式及公共 DTO 定义归入 `contracts.py`；`analysis.py` 保留原导入名的兼容导出，并承担分析编排，避免 contracts 反向导入 analysis 造成循环。

v3 记录使用四个区块：`observations`、`targets`、`supervision`、`provenance`。`RoleInput` 只承载 observations；`encode_batch` 只接收该对象。标签证据、复核状态、来源名、参考 ID、划分信息不进入学习特征。

`RoleInput.from_dict` 按版本分派旧解析和 v3 解析。`migrate_v2_input` 返回可以立即被 v3 主加载器读取的字典。旧调用者可显式走 legacy 路径，不靠伪造 v3 必需字段完成转换。

| 模式 | 必需输入 | 明确语义 |
|---|---|---|
| unit_analysis | 单元定义、所评功能、声明公共资源及规则上下文 | receiver 可空；该 receiver 的 compatibility 为 not_applicable；未声明公共资源保持未知 |
| deck_analysis | 真实牌表与上下文 | 分区字段必须存在，值可为 null（未知）或列表（包括已知空列表）；不根据 Main 自动补 Extra/Side |
| candidate_insert | 基础牌表、候选单元、插入/移除配置及允许槽位 | 先构造候选后的牌表，再分析；不能把未入卡组的单元当已投入 |
| state_evaluation | 所评单元/功能、合法可见状态与规则上下文 | 结构评价所需牌表同时提供或显式未知；不补对手隐藏信息、不把缺省字段当不存在 |

每个分区保留 `None` 与空 tuple 的区别，known_count=0 只用于已知空区。空区 density 为 not_applicable；缺失区的数量和 density 为 unknown。牌表合法性由现有格式校验器判断，识别 DTO 不硬编码 40/15/15，也不能以通过 DTO 校验表示已合法。

`LabelCell.value` 支持布尔、有限数值或受控枚举字符串，具体值域由任务 schema 校验；不接受任意嵌套对象。known 必须有合法值，其他状态 value 为 null。conflict 的候选标签保存在监督元数据，不强压成一个真值。known mask 每次由 status 派生。成员和功能标签增加 annotation_complete；只有完整标注或明确逐格否定才生成负例。

输入规范键只覆盖规范化 observations、特征版本及结构引用。牌表、集合和关系稳定排序；有时序的动作保留原顺序。沿用已有 digest 实现满足去重和缓存身份需要，不增加全库重复哈希流程。

输出版本定为 `axis-result-v3`；包含 `capabilities`、`deck_summary`、`units`、`axis_memberships`、`functions`、`requirements`、四分支泛用结果、`raw_prediction`、`derived_summary`、`requirement_assessment`、`calibrated_scores`、`legality` 和 `explanation_refs`。每个可未知的字段携带 status/reason_code；理由只影响对应功能或字段。

规范角色是功能多标签以及 carrier/enhancer；主/次/支持位置与内生/外接/混合来源分别表达。core/support 按选定机制和功能推导，可同时成立。机制不足时保留已知功能，只将相应摘要设为 unknown。胜利终点与策略各列字段。large/small 不按新卡数阈值重定义；无可靠旧定义映射时输出 null。

### 4.2 单元定义、分支与资源求解

`conditions.py` 承担唯一的纯条件与资源分配核心。保留该已有模块，不引入 SMT、通用规则引擎或整场对局模拟器。`functional_units.py` 承担指定功能的成员闭包；它把分支条件交给同一求解核心。

资源记录补充稳定的物理资源/共享池标识、整数容量、owner、deck_section、state_zone、可用时段、来源和观测完整范围。不同特征描述指向同一物理副本时共享容量，不能以两个标签当成两份卡。选择器和输出匹配复用 `construction_inventory.selector/matches`、`construction_relations.Resource.accepts` 的语义。

求解采用有界深度优先回溯和独立的分支分配状态。结果保留可行分支、残余条件、已消耗/占用资源、冲突和依据。首版配置采用最大深度 16、展开状态 4096、保留解 128；它们是运行预算，超限返回 overflow 与未决范围，不能宣称穷尽或不可行。

具体操作规则：

- 原子需求允许从多个不重叠的供给聚合整数数量；部分可支付不等于整个代价已支付。多供给方案参与回溯，避免 all 先取到不合适供给而错判失败。
- all 沿选定分配状态继续求解；某选择阻塞后续需求时回溯。any 的各候选从同一个父状态开始，各自返回自己的剩余资源，父节点只消费选中分支的状态。
- at_least_k 在同一个联合分配中满足至少 k 个不同子条件，不能独立计算 k 个 true 后忽略共享耗用；若后续确需更多满足项，保留相应可行组合。
- not 恰有一个不产生资源消耗的谓词子树。只有观测范围完整且子条件确定为 false 才得到 true；没有匹配记录但覆盖不完整时为 unknown。禁止把消耗型子树直接放入 not。
- consume 支付后减少容量；occupy 在声明时段内占用容量；retain 要求相应资源在声明时点仍存在并满足保留约束；reusable 只重复读取非消耗事实。资源记录标了 reusable 也不能使 consume 免支付。回收复用须有明确的转换事实及前后时序。
- distinct_group 约束同组需求使用不同物理实例；同名次数池与卡副本池分别计数。使用次数/发动次数、按卡名/按实例、发动/处理/持续时段不互换。
- 只有确定冲突或完整覆盖下的确定缺口能判否。输入损坏抛出带字段路径的 `FactorContractError`；信息不足返回结构化 unknown，不把两者混淆。

required 与 alternatives 转成统一分支表达。每个替代分支中的成员继续递归展开其 required 与 alternatives。成员存在性要求按同一实体最大必要数量合并；同时发生的资源消耗按实际需求累加，由资源求解器裁定。循环成员依赖以有限不动点去重，不因相互引用凭空创造资源。

新增 `minimum_member_branches` 返回每个分支的数量表、功能、外部需求和条件。旧 `minimum_members` 对无歧义的旧 AND 契约保持返回字典；遇多个非等价最小分支返回明确的分支选择错误，所有内部消费者改用新版接口，不能继续把 required-only 字典称作完整最小单元。

只删除成员、条件、资源消耗和产出均等价的重复解；支配关系必须对同一功能、同一已知条件成立。不同代价、不同外部条件或未知差异的分支保留。chosen_branch 默认 null；宿主选定后重查该分支的完整成员和资源。`prepare_function_candidate` 的成本提供者接收选定分支及实际可选副本，默认路径同样重查。

`unit_definition` 的迁移性、`unit_instance` 的结构完整性和当前 readiness 分开。结构 complete/partial/conflict/unknown 与状态 executable/blocked/unknown 使用各自语义；没有局面不会把完整结构判坏。

### 4.3 与构筑共用事实，不复制求解器

`construction_inventory.py` 继续拥有真实副本库存、选择器、补件候选和区域归属。`construction_relations.py` 继续拥有效果来源、资源类型匹配、关系传播、资源池及计数事实。识别层从它们生成规范观察，不重新解析一套卡效。

计划新增 `src/ygo_kito/construction_recognition.py`，作为牌表/构筑事实与识别 DTO 之间的薄适配层。它导入双方契约；`multifactor/conditions.py` 不导入构筑控制器、Torch 或训练模块。选择器匹配由适配层预先生成可用供给关系，分配核心只处理事实与容量。

构筑的 `InputGroup/Need/ResourcePool/Claim` 中能完整表达的条件转给同一分配核心；现有关系传播仍留在 `construction_relations.py`。无法无损转换的条件保留 unknown 和原表达式，不丢约束，不直接把已有 conservative unknown 改成 supported。禁止为“接通”绕开 `construction_relations` 中费用、来源、用途或联合限制检查。

共享文件的未来改动只限于这个委托接口及结果映射。若构筑任务已引入统一分配核心，应把上述条件语义合入那一个核心，并保留本书的接口与验收目标，不保留两套同义实现。实施前读取实际最新共享文件并合并已有改动，不覆盖另一任务成果。

识别提供功能、成员、条件、整数资源、冲突、分支和未知。构筑拥有收益函数、主题权重、损失及准入政策。11 月 4 日识别稿中 `base_contribution/theme_contribution` 等定价内容在这里转为事实引用及宿主政策的可选结果，不在识别层实现分值。state_readiness、抽取概率、预测置信度、环境价值不得直接变成构筑扣分。

### 4.4 候选、编码与输出头

新增 `multifactor/axis_candidates.py`；`semantics.py` 扩展为运行时效果事实和图输入的公共构造入口，训练目录的 `features_graph.Features` 委托该入口。运行时不反向导入 training 目录。

候选从已知调用闭包、类型/资源供需和组合定义生成。首版普通关系展开两轮，每轮每种子保留八个候选分支，按事实可信度、功能覆盖及稳定结构键排序；明确指名依赖继续闭合。超预算报告 overflow。按功能、成员数量和条件规范化去重，不用标签或轴名字去重。

单卡独立功能先作为 unit，不自动成为轴。候选允许重叠；桥接卡不触发传递式合并。大轴只在已有明确供需连通依据时组合子候选，并保留父子关系。候选评分每批 32 个，分批遍历全部候选，32 不作为总轴数上限。

编码保留宽 64、两轮消息传递；增加卡、功能、候选轴、依赖及区域汇总的受控类型和特征。重复卡用数量表达，只有分配冲突需要时展开资源实例。Main/Extra/Side 分开汇总，padding 和已知空区分开。现有 64-group 上限只保留给旧输入，新输入按节点/边预算分块；不能把 60 Main 加 Extra/Side 合法输入直接截断到 64 个节点。

| 输出 | 实现与监督方式 |
|---|---|
| mechanism | 动作、收益、限制等已知格的辅助多标签头；初版不预测整个复杂机制图 |
| axis_membership | 卡/单元 × 候选轴独立 sigmoid；可同卡多轴；候选支持范围不硬限制成员全集 |
| axis_function、function_role | 分别按轴和单元-机制-功能输出多标签 |
| contribution | carrier/enhancer 两格独立输出 |
| axis_position、axis_origin | 各自三分类；位置和来源监督独立，缺一不补另一 |
| transferability | 完整单元/功能的 open、conditional、closed；unknown 是证据/决策状态 |
| receiver_compatibility | 接收结构的兼容预测与已知冲突、残余条件分开返回 |
| pair_relation | 按依赖、替代、支持、冲突等类型输出；有方向的关系不沿用旧对称单标量头 |
| copy_preference | 同目标、同对比操作的成对偏好；无可信比较标签不更新 |

四分支泛用结果中，transferability 与 receiver_compatibility 接入相应学习头；state_readiness 首版由可见状态和条件求解返回；environment_value 在环境阶段前为 unknown/未启用。缺少该阶段数据不妨碍前三类工程接口交付。

机制查询来自固定词表、输入事实产生的候选或明确 declared_goal。监督机制标签不参与查询选择。可选路线特征只来自可复现输入事实；`use_route_features` 与 `stream_mode` 分别配置。新首轮默认关闭路线特征、保留现有双视图，不把这项默认当作消融结论。

旧五角色作为带 `legacy_semantics_version` 的摘要；raw_prediction 不被确定性结论改写。没有有效训练/校准/发布记录的头，公共结论保持 null 并给出能力状态，原始随机 logits 只在明确诊断路径可见。

### 4.5 数据、损失、评估与版本

先建立来源关系的连通分量，再划分、扩展与拟合预处理。关系包括所有有效的 source_rowid/reference/case_id、父子派生、同场对局/比赛来源以及相同规范牌表，采用带命名空间的键避免同数字碰撞。不再按优先级只取一个字段，也不按“同主题”合并全部来源。

近重复采用公开配置规则：同格式/时期、三个分区均已知且对应总数相等时，各区替换距离为该区数量向量 L1 距离的一半；Main、Extra、Side 均不大于 2 时并组。此为首版隔离初值，保留合并依据和组件规模；不得用最终测试结果调阈值。区域未知不能由近重复规则证明相同，已有明确来源关系仍然合并。

四种协议实际执行不同限制：unseen_deck 留出独立牌表组；unseen_receiver 按 receiver family/机制组合整体留出；unseen_card 将指定卡/组合及其派生训练图、标签和训练统计全部排除；cross_period 按明确时间截点隔离资料和标注。跨划分的来源组件整体留出或隔离，不能拆散以凑比例。普通 unseen_deck 不因共用泛用卡将所有牌组合并。

P0 迁移规则保留，按新模式映射具体标签：actor 缺席不是非核心；不适用的在组角色标为 not_applicable，未知格保持 unknown；原 readiness-only 样本只有局面证据充分时才转入 state 任务，其 generic 标签不恢复为负值。逐格保存迁移前后和原因，实际数量由输入决定。旧弱标签只迁入能明确对应的旧任务；新成员/机制/迁移性标签缺证据则不生成。

新缓存身份包含 input/feature/label/dataset/split 版本、来源版本、准备参数、所选协议及随机种子。已有 dataset.json 只有语义清单一致才复用；缺清单或不一致时要求新目录，不能覆盖旧缓存。标签更新不改变 input_key，但会改变数据/标签版本。规范记录一致即可，不追求 gzip 文件字节一致。

二元头使用未归约 BCE；类别头使用各自 CE；偏好头使用有依据的成对目标。先把非 known 格安全替换再遮罩。每头先按来源组平衡有效格数，证据权重只乘分子，分母是有效来源平衡权重之和。全弱证据批次的梯度应相应减小。一个头全未知时不更新该头的能力计数；全部头均无监督时不执行 optimizer step。

任务组合采用有效任务的加权均值。设计初值为成员 1.0、轴功能/功能角色/贡献先各归一化再合组 1.0、迁移性 1.0、兼容 0.75、关系 0.5、位置/来源合组 0.4、机制 0.2、副本偏好 0.2、明确反事实一致性 0.1。权重属于未来运行配置，不修改当前配置文件。

评估同时返回 raw、calibrated、applied 三层，不以规则修正后的成绩冒充网络成绩。已知标签拒答计入整体分母和相应真类漏检；另报已回答子集指标和覆盖率。F1 使用 `2TP/(2TP+FP+FN)`，有错误且分母非零时必须得到 0；没有该类有效真值时记未覆盖。固定任务/类别集合，已覆盖任务得分和完整能力状态分别报告，不删除缺失类别后称全任务通过。

迁移性输出 3×4 混淆矩阵，unknown 为预测列；成员评估包括自然候选召回及最优轴匹配 IoU，漏候选计漏检。按来源组聚合，并按来源组重采样区间，不能把同参考变体当独立样本。选模与校准按组隔离，最终留出集不参与准备、阈值、模型选择。旧 118 条参考保留为开发/历史诊断资料。

新 checkpoint 分别记录架构、特征、标签、数据、划分、校准版本及配置。resume 要求同一实验和数据游标相容，恢复优化器、调度器和随机状态；warm_start 是新实验，只复制语义和形状均相容的共享参数，重建优化器及新头状态，不能使用裸 `strict=False` 掩盖遗漏。

当前 `RoleTrainer.load` 绑定整个 multifactor 源码指纹，新增任何包内文件都会影响旧恢复。因此代码保留、权重保留和旧恢复可用性分别处理：修改前保存当前包的小型源码回退副本；旧权重继续绑定其原源码/回执，未来明确获准加载时再核对。不能承诺现有工作树与所有历史权重天然匹配，也不能删掉源码校验来强行恢复。

### 4.6 分析服务和消费行为

在 `analysis.py` 实现 `RoleAnalyzer`，构造时注入事实提供者、可选 scorer、能力状态和预算。公开方法为：

```text
analyze_deck(deck, context) -> DeckAnalysis
assess_unit(unit, receiver_deck, context, requested_function) -> UnitAssessment
compare_copy_change(base_deck, add_card, remove_card, functions, context) -> CopyComparison
```

底层 `functional_units.assess_unit` 是功能契约检查；在服务模块中用明确的别名导入，避免与公开服务混淆。context 携带格式、时期、规则版本、模式、可见状态及明确目标，不携带监督标签。事实提供者读取既有卡效/库存，不在请求内触发训练或自动换模型。

`compare_copy_change` 的 add/remove 都携带区域与数量。等牌数替换必须给出移除项；remove 为 null 表示增加总数。减量操作要给出实际变化，缺替代对象时只报告已确定的本卡/功能差异，整体偏好保持 unknown。重算受影响的依赖、调用目标、资源冲突及所有相关分母。

浓度按实际分区总数计算。简单接触概率复用 `construction_relations.single_event_probabilities`；只有声明抽样方式和抽取张数才计算。联合功能需要条件和资源联合判断，不能相乘独立概率或把接触率当成功率。复杂联合概率无法在预算内确定时报告 unknown 和需求，不借本任务增建对局模拟器。

`construction_recognition.py` 把分析结果映射到现有 layer/fill 的事实接口。`build_axis_skeleton`、`fill_with_existing`、`construction_cycle` 接收可选识别 provider：off 不调用；observe 记录到已有结果对象但不改变排序、筛选、学习或 gate；assist 按已验证的 capability 提供候选及事实，最终评分仍由构筑政策计算。一个能力失效只停用它本身。

CB 只接收功能候选、起始资源、分支、时序及缺件作为搜索提示；合法动作与路线成功仍由现有 CB/引擎确认。统筹只接收既有任务结果中的能力/覆盖信息，不修改其网络、调度政策或数据库结构。`legality` 无外部结果时为 unknown，带 producer/version 的结果才可沿用。

## 5. 文件范围

下列是后续实施的拟改范围，不表示本轮已获得代码实施授权。

| 范围 | 文件与用途 |
|---|---|
| 核心识别 | `src/ygo_kito/multifactor/{contracts,analysis,annotations,conditions,functional_units,semantics,network,training,scoring,splits,metrics,__init__,__main__}.py` |
| 必要新增 | `src/ygo_kito/multifactor/axis_candidates.py`、`src/ygo_kito/construction_recognition.py` |
| 数据与评估入口 | `training/axis_generic/{prepare_base,prepare_only,features_graph,goal_semantics,train_base,finish_existing,assessment,runtime}.py`；确实仍被新版调用的 `features_v4.py/prepare_balanced.py` 仅做所需委托，不全盘重写 |
| 新版配置 | 新增独立 `training/axis_generic/config.v3.json` 与 `ASSESSMENT_PROTOCOL.v3.json`；旧配置保留其历史语义 |
| 共享接线 | `construction_relations.py` 的条件分配委托；`construction_fill.py`、`construction_layers.py` 的 provider/事实传入；已有 CB provider 的输入映射，不改引擎 |
| LoRA 兼容 | `multifactor/adapters.py` 只同步新底座/任务版本校验，当前不新增环境训练或更换其职责 |
| 验证与说明 | 受影响的 `tests/test_multifactor_*.py`、必要新增的候选/服务测试、构筑接线定点测试；当前说明与 MASTER-CHECKLIST 只登记真实已完成状态 |

禁止修改：历史 runs、原始数据与参考标注、现有 `.pt/.weights`、活动模型指针、`training.hold.json`、课程状态、原生 ABI/guard、决斗和统筹模型、构筑评分权重与阈值、凭据、部署和 DSH 设计台。原标注迁移输出到新版记录，不覆写源文件。没有实施需要时不编辑共享模块。

## 6. 分步机械执行书

各步的“检查方法”规定未来验证方式。本轮全部未运行。前置条件是已有接口/文件和授权范围；尚未运行的测试不伪记通过，也不自动变成额外用户审批。失败处理只撤回本次增量，保护全部先前本地改动。

### M0：保存正确实施基线

- 目标文件/符号：当前 multifactor 包、拟改训练入口和拟改共享文件；`RoleTrainer.load/source_fingerprint` 的版本约束。
- 前置条件：用户已要求开始实施；仍在当前完整工作树。
- 修改动作：先保存拟改文件的修改前内容；对于旧恢复所绑定的 multifactor 包，保存整个小型包源码及原相对路径。记录原本不存在的新文件和原本已删除的文件。回退副本仅用于本次代码恢复，不复制大数据或权重，不创建新 Git 工作树。
- 不变量：本地未提交/未跟踪/已删除状态不被 HEAD 替换；原活动模型和训练暂停记录不动。
- 预期结果：能够逐文件恢复本次修改前内容，能够区分本次新增与原有未跟踪文件。
- 检查方法/通过标准：文本清单和文件存在性检查；目标路径全部位于预期实施目录或明确的回退目录，保存内容可读。此步不加载模型、不计算无用途的全树哈希。
- 停止/回滚条件：实施目录或最新共享修改无法确认时停在受影响文件；保存失败则不修改该文件。回退使用保存内容，不使用 reset/checkout。

### M1：打通 v3 契约、标签格与旧版迁移

- 目标文件/关键符号：`contracts.py` 的 `RoleInput/LabelCell`；`analysis.py` 的 `DeckSpec/UnitSpec/migrate_v2_input`；`annotations.py` 的 `AnnotationRecord/training_view`；`training.py` 的 `Targets.validate`。
- 前置条件：M0；第 4.1 节模式和字段语义确定。
- 修改动作：移动公共 DTO 并兼容导出；增加 v3 主解析器、旧版本显式迁移；空区/未知区双态；分类 LabelCell 值域；Targets 与 AnnotationRecord 的逐格读取；成员/功能完整标注标志；旧 float/None 只在迁移边界转换。
- 不变量：解析不导入 Torch/训练宿主；无标签泄漏；未知不补零；v2/v7 输入不静默冒充完整 v3。
- 预期结果：迁移输出能被主加载器回读，训练与推理使用同一 observations 对象。
- 检查方法：Q1 的契约用例和旧机制不入特征用例；人工对照四种模式的缺字段、空列表、null、known 0 和类别枚举。
- 通过标准：A01–A03 对应契约部分全部满足；现有合法旧 DTO 仍可显式读取，非法结构有字段定位。
- 停止/回滚条件：循环导入、未知被转负、旧接口被无提示改变或移入标签特征时，停止该契约的下游迁移并修复；必要时仅恢复 M1 文件。

### M2：完成逐分支成员和统一资源分配

- 目标文件/关键符号：`conditions.py` 的 `Condition/ConditionGroup/Resource/solve_requirements`；`functional_units.py` 的 `minimum_member_branches/minimum_members/assess_unit/derived_unit_factors`；`scoring.py` 的 `prepare_function_candidate`；共享事实适配。
- 前置条件：M1 DTO；现有 construction_inventory/relations 的真实最新契约。
- 修改动作：按第 4.2 节实现回溯和观测覆盖；递归展开替代成员；逐分支返回完整成员/残余/冲突；改用选定分支生成候选及整包成本；同一个事实分配核心供识别和构筑委托；无法转换的旧条件保留未决。
- 不变量：不消耗 Side 作为当前局资源；整数资源不重复支付；指名与类型条件不丢失；分支之间不拼资源；预算耗尽不判失败。
- 预期结果：缺件、替代、共享资源、自肃与状态阻碍分别有局部结果；两种不同最小包不会合成一个假“最小包”。
- 检查方法：Q2 及 V04–V12；特别核对外层 all(any(...), consume(...)) 和 at_least_k 的剩余资源，检查构筑与识别对同一已支持条件返回一致事实。
- 通过标准：A04、A05；所有匹配都有来源，选定分支复查发生在调用成本提供者前，未选分支仍保留。
- 停止/回滚条件：出现跨分支拼接、超容量、Side 误用或丢约束则停用该接线并修复，不用降置信度掩盖确定性错误；不改构筑政策来适应错误输出。

### M3：共用特征构造并生成自然轴候选

- 目标文件/关键符号：`semantics.py` 的公共 `build_analysis_graph`；新增 `axis_candidates.py/generate_axis_candidates`；`features_graph.Features.make/graph`；`contracts.py` 的图节点/关系契约。
- 前置条件：M1 输入、M2 分支与事实适配。
- 修改动作：把事实到图的必要逻辑归入运行时包；生成候选、闭合指名依赖、保留重叠与父子关系；独立编码三分区及数量；候选分块评分；监督注入候选仅在训练构造中标 provenance。
- 不变量：训练目录不是服务依赖；候选生成不读 Targets、金标机制、角色名或成功路线答案；单卡独立功能不自动膨胀成轴。
- 预期结果：相同 observations 得到同一规范候选集合；60 Main 加合法 Extra/Side 不被旧 64-group 限制截断；自然候选与训练注入候选可区分。
- 检查方法：新增 `tests/test_multifactor_candidates.py`、现有 structure/real_effects 的受影响用例；V13–V16 和 V22。
- 通过标准：A03、A06；重命名追踪 ID、换节点输入顺序或改监督答案不改变对应结构张量，candidate overflow 可见。
- 停止/回滚条件：标签参与召回、桥接卡导致无依据合轴、无提示截断或身份泄漏时停止候选接入，不扩模型掩盖召回错误。

### M4：迁移准备流程、划分与评价口径

- 目标文件/关键符号：`splits.group_rows/assign_group_splits`、`metrics.binary_metrics/macro_f1`；`prepare_base.prepare/targets/role_identity`；`prepare_only`；`assessment.summarize/comparison`；`goal_semantics.resolve_plan`；新 v3 配置/协议。
- 前置条件：M1 标签、M3 规范输入；现有来源文件只读可定位。
- 修改动作：来源关系连通合并；实现四种协议；先划分后扩展；P0 逐格迁移；移除静态标签跨变体无条件复制；语义缓存一致性检查；稳定集合/SQL顺序；所有新评估入口调用统一 metrics；修复拒答与零 F1 统计。
- 不变量：旧 runs、源标注及已消费参考不改写；相同来源不跨集；金标缺失不补负；新标签不沿用旧优化器语义。
- 预期结果：新版数据清单可解释来源组、标签状态、迁移去向和协议；不同配置不会误读旧 dataset.json；旧参考继续标开发/历史用途。
- 检查方法：Q3、V17–V21；获准准备数据后，才做一次不同哈希种子和反向读取顺序的规范记录比较。
- 通过标准：A02、A08；同一组三种来源键之间的传递关联不泄漏；类别完全预测错误得 F1=0；拒答不减少整体有效分母；规范记录比较忽略 gzip 容器差异。
- 停止/回滚条件：新输出目录与旧运行目录重合、来源跨集、未声明重写标签或未知变负时停止数据生成；只删除或撤回本次新产物，不清理旧缓存。

### M5：扩展网络、损失和恢复协议

- 目标文件/关键符号：`network.NetworkConfig/encode_batch/RoleNetwork.forward`；`training.Targets/RoleTrainer.train_supervised/train_preference/save/load`；`train_base.batches/update/fit`；`finish_existing.finish`；`adapters.base_binding`。
- 前置条件：M1–M4 的输入、任务定义、分组与指标接口完成；写代码不要求先完成全量补标。
- 修改动作：实现第 4.4 节各头和双开关；逐格/来源组损失；输出能力状态；显式 v3 配置；resume 与 warm_start 分开；保存必要的随机/采样状态；新版任务不继承旧头的达标标志。
- 不变量：未知格无伪监督；证据权重不在分母中抵消；无监督 batch 不更新；机理标签不读回输入；旧 checkpoint 不覆盖，LoRA 不污染基础路径。
- 预期结果：新任务从数据记录、张量、损失到 checkpoint 完整可调用；未训练的新头仍如实报告未训练。
- 检查方法：Q4 的前向、mask、排列/批填充、版本拒绝用例；允许微型优化器测试后再运行 Q5；正式训练另属 T 阶段。
- 通过标准：A07；在人工构造的已知格上各头损失只作用于对应格；全弱证据批次按比例减小；保存恢复后下一步采样/更新与连续运行一致；不相容 resume 明确拒绝。
- 停止/回滚条件：输入泄漏、源协议混用、恢复吞掉新参数缺失、旧权重被覆盖时停止相关加载/训练入口；只恢复本次源码变更或选择原版本运行，不放松恢复校验。

### M6：交付三个服务与 off/observe/assist 接线

- 目标文件/关键符号：`analysis.RoleAnalyzer` 三个方法；`scoring.CandidateScorer` 与旧摘要；新增 `construction_recognition.py`；`construction_fill.build_axis_skeleton/fill_with_existing/construction_cycle` 及 layer/CB provider 的事实映射；包导出和 CLI。
- 前置条件：M1–M3 可提供确定性事实；M5 预测能力按实际状态可选接入；共享构筑文件的最新版本已读取。
- 修改动作：构造完整候选后再评估；副本操作重新计算相关配置；修正旧解释文字；接入模式开关；把输出传入真实消费者；按 capability 局部启停，复用既有结果记录。
- 不变量：off 不加载识别模型；observe 不改变候选/学习/gate；识别不增加分值政策；当前模型、课程和训练开关不被切换。
- 预期结果：调用者能通过接口获得成员、功能、修复需求、分支与差异，实际构筑入口能接收这些结果。CB 接到搜索提示但不被宣称已完成。
- 检查方法：新增 `tests/test_multifactor_service.py`、`tests/test_construction_recognition.py`，V23–V27；使用受控 provider，不加载历史权重、不运行 CB。
- 通过标准：A09、A10；observe 与 off 的原候选顺序、评分、学习请求和 gate 结果一致；assist 的所有变化能追到明确 capability 和宿主政策。
- 停止/回滚条件：产生隐藏扣分、修改目标、observe 影响决策、未经授权加载/训练或调用引擎时关闭该 provider，恢复原调用行为；保留独立事实接口。

### M7：同步交付状态与限定验证

- 目标文件/关键符号：受影响测试、当前开发说明、`docs/plans/MASTER-CHECKLIST.md`；本执行书的实际完成记录。
- 前置条件：相应代码批次完成；运行验证还须对应禁令已解除。
- 修改动作：只登记实际文件变化、已执行检查及结果；记录未执行项和 capability 状态。执行受影响测试与一次相应集成检查，覆盖通过后无新证据不扩大范围。
- 不变量：历史成绩不当新成绩；软件实现不当模型能力；未运行不勾选通过；未获得本任务的发布指令不提交、推送、发布或合并。
- 预期结果：每个 A01–A10 都能定位到文件与已执行证据，或准确标为待验证；之后可直接进入获准的训练/能力阶段。
- 检查方法：交付文档与本次差异逐项对应；验证命令按第 7 节执行。仓库安全 CPU CI 仅在对应检查获准且必要时运行，不借合并脚本启动被禁止的测试。
- 通过标准：实现、工程验证、训练、能力验收状态分开，活动模型仍按实际发布状态报告。
- 停止/回滚条件：发现报告把未执行项写成通过时先改正报告；发现某能力具体失败只停用该能力并修复，不扩大成无关全项目重审。

## 7. 验证设计：当前均未执行

本轮没有运行 Python，连模块导入、编译检查、测试收集和模型前向也未运行。下面的命令用于后续明确允许相应验证时执行。不得以 unittest、冒烟或 CPU 工程检查的名字绕过当前禁令。

解释器采用原设计指明的 `E:\Ana\envs\pcacgate\python.exe`；本轮只确认该文件存在，未核验环境版本、依赖或设备。未来执行前读取现有环境配置，不升级 Python/Torch/CUDA，不安装另一份环境。命令中的新增测试模块须先由对应步骤实现。

验证前在 PowerShell 中设置当前项目和项目源码路径，`PYTHONDONTWRITEBYTECODE=1`，OMP/MKL 各 2 线程；临时输出显式指向本任务新目录。使用 `& 'E:\Ana\envs\pcacgate\python.exe' -m unittest <明确模块或方法> -v`，不使用 discovery。

| 检查组 | 命令后面的明确模块/方法或检查方法 | 范围 |
|---|---|---|
| Q1 | `tests.test_multifactor_analysis tests.test_multifactor_labels`；`tests.test_multifactor_mechanism.MechanismContractTests.test_mechanism_is_not_encoded_as_input` 单独选取 | 契约和信息隔离；是否涉及网络按具体方法筛选 |
| Q2 | `tests.test_multifactor_conditions`；`tests.test_multifactor_units` 中改动后的成员/替代/准备候选方法 | 分支和资源；整模块前先排除其中会训练或加载权重的用例 |
| Q3 | `tests.test_multifactor_splits`，新增缓存/协议测试；一次准备确定性比较 | 分组、指标与缓存；全数据准备需另在允许的准备阶段运行 |
| Q4 | `tests.test_multifactor_candidates tests.test_multifactor_service tests.test_construction_recognition`；structure 的 permutation/padding/identity 方法 | 无历史权重的服务与前向；需要允许模型前向测试 |
| Q5 | structure 中 masked loss、next update resume；新增各头归一化测试 | 会执行微型优化器更新，仅在明确允许这类工程测试时执行 |
| Q6 | `git diff --check` 限本次文件；源码差异与禁止范围对照；必要时已筛选 CPU CI | 静态/仓库检查；本轮也未运行 |

本任务修改 Python 模块和调用契约，没有独立的原生构建步骤。若后续交付需要 Python 包构建，仅在对应授权和既有打包入口明确后执行，不顺带重建规则引擎。

以下用例补进对应测试文件。断言围绕语义和调用副作用，不复制实现逐行自证。

| ID | 输入或变化 | 必须观察到的结果 | 归属 |
|---|---|---|---|
| V01 | v2/v7 迁移为 v3 再序列化回读 | 模式、数量、未知与已知空保持；无伪造字段 | M1/Q1 |
| V02 | 已知 0、unknown、conflict、not_applicable；分类枚举 | 状态不混淆；只有合法 known 格参与监督 | M1/Q1 |
| V03 | 只标轴的正成员，未声明标注完整 | 集合外成员保持 unknown | M1/Q1 |
| V04 | required 的替代成员还有递归依赖 | 递归依赖进入相应分支，其他分支不被污染 | M2/Q2 |
| V05 | A+B 或 C+D，现有 A+D；A+B 或 A+C，现有 A+C | 前者不能拼成功；后者保留合法替代 | M2/Q2 |
| V06 | 两个 consume 只有一份资源；两个供给各 1 支付 2 | 前者拒绝重复支付，后者允许合法聚合 | M2/Q2 |
| V07 | 外层 all 包含 any，第一选择阻碍后续而第二选择可行 | 回溯找到可行分配；正确传播剩余库存 | M2/Q2 |
| V08 | at_least_k 的独立子条件争用同一资源 | 只有能联合支付的组合算满足 | M2/Q2 |
| V09 | not 多孩子、消耗子树、不完整观测 | 非法形状拒绝；观测不全返回 unknown | M2/Q2 |
| V10 | occupy、retain、distinct、明确回收时序及同名限制 | 占用期和计数域正确，复用须有依据 | M2/Q2 |
| V11 | 缺件只在 Side；0 Extra 无依赖；15 Extra 只供成本 | 当前局 Side 不供给；后两者分别完整/成本资源依赖 | M2/Q2 |
| V12 | 删扩展功能目标，但基础功能仍完整；求解预算耗尽 | 基础功能保留；未展开范围为 unknown | M2/Q2 |
| V13 | 同卡两轴、桥接卡及有依据的父子大轴 | 多成员成立，桥接不自动合并 | M3/Q4 |
| V14 | 删路线注释、改监督机制/角色标签和 reference | 没有机械清零，observations 编码不变 | M3/M5/Q4 |
| V15 | 改 opaque ID、节点顺序、批量 padding | 对应结构预测等变/集合输出不变 | M3/M5/Q4 |
| V16 | 包可迁移、成员单卡缺配套；carrier 与 enhancer 同时成立 | 不广播包角色；两个贡献标签可同时存在 | M3/M5/Q4 |
| V17 | 来源 A 与 B 共 reference、B 与 C 共 source_rowid | A/B/C 整组在同一划分 | M4/Q3 |
| V18 | unseen_card、unseen_receiver 与跨时期协议 | 真实隔离对象不同，统计与派生数据遵守各自限制 | M4/Q3 |
| V19 | dataset.json 存在但标签/特征/划分配置改变 | 拒绝误复用，旧文件不覆盖 | M4/Q3 |
| V20 | 某类全部预测错误、全部拒答、没有真值 | 错误为 0 分；拒答降低整体与覆盖；无真值为未覆盖 | M4/Q3 |
| V21 | 文件顺序和哈希种子改变 | 规范输入、标签、mask、来源组及划分一致 | M4/Q3 |
| V22 | 自然候选漏掉真实轴 | 端到端漏检增加，不能用训练注入候选补评估 | M3/M4/Q4 |
| V23 | 40/41/45/50/55/60 Main；Extra/Side 为零、部分、满额 | 分区分母正确，空与缺失不同；不因张数直接加减分 | M6/Q4 |
| V24 | 等总数换卡、40→41、减量补替代、缺替代对象 | 操作边界正确，整体未知不虚构偏好 | M6/Q4 |
| V25 | 效果送墓改费用送墓；使用次数改发动次数 | 对应功能和限制重新判定，不复用错误语义 | M2/M6/Q2/Q4 |
| V26 | 相同候选运行 off/observe/assist | observe 不改变任何决策；assist 变化可归属到已启用能力 | M6/Q4 |
| V27 | 重复功能描述、同义证据及重复轴归属 | 事实/收益来源不被重复计为构筑贡献 | M6/Q4；定价断言由构筑测试负责 |
| V28 | 某头全未知、全批无监督、全弱证据 | 局部零损失；全批无更新；弱证据梯度仍减小 | M5/Q5 |
| V29 | 新协议恢复旧优化器、显式 warm_start、同实验续跑 | 不相容恢复拒绝；新实验重建状态；同实验正确续接 | M5/Q5 |
| V30 | 环境适配开关 | 固定底座输出不变；留至环境 LoRA 阶段验证 | 后续环境阶段 |

## 8. 后续训练、能力验收与发布

这些工作不在本轮授权内，也不是先交付软件接口的前置要求。先完成工程语义和数据路径；不得以继续旧 v7/v9 小训练代替新版链路。

| 阶段 | 进入条件 | 具体工作与退出结果 |
|---|---|---|
| T1 数据准备与补标 | 对应准备工作获准，v3 语义实现完成 | 保留旧资料，生成新版迁移记录与来源组；按缺失结构补独立案例。已有完成新标注的资料加约 40 个独立开发案例可开始首轮，不为凑 280 组复制来源 |
| T2 基础训练 | 训练明确获准，工程关键错误已修复，首批有效标签及开发划分可用 | 显式新 run；64/2，小模型 GPU，无 CPU 静默回退；保留旧模型。未有标签的头保持未启用 |
| T3 最小消融与校准 | T2 可运行，所需运行预算获准 | 同数据同预算比较路线开/关 × 单/双流四格；先单种子，仅有效基线与候选补至三种子；按来源组隔离选模与校准 |
| T4 独立评估与能力发布 | 候选与协议固定，真正未消费的留出资料可用，评估获准 | 逐能力报告 raw/calibrated/applied；只把通过能力从 observe 切到 assist；实际发布仍由后续发布指令控制 |
| T5 环境 LoRA | 基础能力稳定，真实对局/环境反馈及训练授权具备 | 固定基础路径；环境支路学习投入价值。比较只训环境头、LoRA 加环境头和独立副本低学习率全量微调；环境适配器独立保存 |

首轮训练配置沿设计建议采用 AdamW、学习率 0.001、weight_decay 0.0001、dropout 0.1、梯度范数上限 1.0；微批 32 图并受节点/边数约束，累计有效批量 64，最多 20 轮、耐心 4 轮、最小改善 0.002。FP32 起步；没有显存证据不引入混合精度，不扩大模型或开展大范围超参数搜索。实际配置在新 run 中保存，不重写旧配置。

能力验收初值沿原方案：候选召回 0.95；成员、功能、迁移性宏 F1 各 0.80；open 精确率 0.90；closed→open 不高于 0.05；覆盖率 0.90；未见接收结构宏 F1 0.70；同协议关键任务退化不超过 0.03。它们是新能力配置的初值，不是既得成绩或构筑评分权重。无有效真值、零分母或关键切片不足时登记未覆盖，不能填 1 或删除类别后发布。

原始 N 盘数据原地只读，旧 runs 保留。后续新大体积缓存、分片和训练产物默认使用 `E:\CodexData\artifacts\ygo-kito\axis-generic\v3` 下独立版本目录；执行时检查实际空间、权限及 TEMP/TMP、缓存和输出路径，不在本轮创建目录或复制数据。源码、协议和小型标注仍在当前实施目录。已有 N 盘资源不为统一路径再次搬迁。

发布复用现有宿主模型绑定入口；只有该入口确实缺少活动版本引用时才补一个 `active_base.json`，不并存两套活动指针。本轮不创建或切换任何指针。回退切换到保留的相容代码/模型版本，不覆盖历史权重；来源绑定不明的旧产物保持待核对，不能假称已验证可恢复。

## 9. 原首批安排、当前状态与停止范围

原定首批为 M0、M1、M2，先交付 v3 输入/标签和逐分支需求接口，再推进 M3 以后的候选、学习与服务。当前 M0 保存及 M1–M6 源码交付已经实施，M7 已同步文档；旧首批安排保留设计顺序，不再表示这些步骤尚未开始。

制定时的静态核对已足以确定上述路线，没有待答问题或当前外部阻塞。后续已确认当前解释器/依赖、CPU 工程前向/更新及本批新建 checkpoint 的严格恢复；GPU 状态、历史生产 checkpoint 与保存源码的相容性、真实数据经 v3 迁移后的覆盖、新模型准确率及下游真实运行表现仍未验证。它们分别在对应执行步骤核验，不作为已授权工程工作的额外全局门槛。

当前软件状态为 M1–M6 和 M7 交付已实施，Q1–Q5 及 V10 选定工程范围共 192 个不同方法已有通过结果，累计 231 次物理执行，V10/V11/V12/V16/V21 专用方法均有通过证据。最新 V10 五项首次通过，先前 Q5 首轮 1 failure/4 error、精确修复及六项复验历史保留。A01–A10 按实际已测子范围登记，当前授权内选定工程目标已完成；M7 整体仍保留未执行的 CB 对接范围。

Q5 损失/梯度/工程更新和恢复、V10 回收时序工程对照均已完成。剩余顺序为允许对应范围时验收排除的 CB 提示接口，再按 T1–T5 承接真实资料/SQL 迁移、正式训练、独立评估与校准/宿主能力发布；历史生产权重绑定、GPU/设备和真实宿主运行留对应阶段。CB 和 T 阶段尚未获准，本批不启动。既有/活动权重、训练暂停和设计台不变，没有发布模型能力；当前授权内工程检查无未闭合失败，不重复已通过集合或自动进入禁止阶段。

后续继续遵守提问等待规则：一旦就关键前提提出问题，暂停所有依赖该回答的研究、设计、实施和交付，收到真实回答后再恢复；当前没有待答问题。长任务优先在本聊天继续；若压缩或阶段边界影响约束和证据保真，再给出完整交接摘要并建议新开，未经用户确认不创建聊天。
