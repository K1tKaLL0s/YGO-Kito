# YGO-Kito 项目状态审阅与交接

日期：2026-11-08。工作目录：`N:\YGO-Kito`。当前实施源码：`N:\YGO-Kito\_publish_20261030`。

## 1. 本次范围与结论

本次按用户要求审阅构筑模型、轴与泛用识别模块，并整理决斗模型和统筹模型的现有设计、源码与保存状态。已读取用户提供的 11 月 4 日构筑扣分方案，通过 MCP 核对 DSH 设计台，并沿实际调用链检查代码；同时读取了既有课程与识别训练记录。

没有运行测试、验收脚本、模型推理、训练、CB、原生决斗、构建或性能测量；没有加载权重。历史记录中的次数和结果仅描述已经保存的运行，不是本次复测。未修改程序、配置、权重、训练状态或设计台。本次只新增本报告，并按用户授权建立两个待启动交接聊天。

核心判断：构筑模型已有可复用的生成、优化和静态分层基础，但新收益与扣分体系尚未贯穿候选选择、学习反馈、准入和恢复。识别模块已有旧网络、真实训练产物及一轮标签纠正，新版分析契约、分支资源推理和多任务输出尚未完成整合。决斗端已有真实规则引擎上的 Transformer/PPO 和可见信息规划器；统筹端已有确定性调度、情境化预测和预算建议，不能再用早期“只有一个 648 参数建议器”概括。

两个后续聊天分别承接构筑正式优化方案和识别模块后续开发；本轮只接收交接，不生成正式方案、不实施。决斗与统筹的进一步设计仍留在原聊天。

## 2. 工作区、设计来源与保存状态

### 2.1 正确的代码位置

| 对象 | 本次看到的状态 | 后续使用方式 |
|---|---|---|
| `N:\YGO-Kito` 根 Git 仓库 | `main`，HEAD `4330229`，2026-10-22；根 README 仍描述较早流程 | 作为项目容器和历史材料，不能以其 HEAD 代表当前实现 |
| `N:\YGO-Kito\_publish_20261030` | 分支 `codex/optimization-20261031`，HEAD `3f57198`，2026-10-31；大量后续本地改动 | 本次源码审阅与后续工作的实施基线 |
| 上述实施目录的工作树 | 本报告写入前，Git 短状态记录 87 个已跟踪修改、20 个已跟踪删除、114 个未跟踪条目；目录条目不等于逐文件总数 | 必须保留，不能 reset、clean、用旧提交覆盖或另造一个缺少本地改动的基线 |
| `_local_cpu_20261027` | 保存原生资源、旧课程源码与课程状态 | 属于运行与历史证据，不等于当前实施源码 |
| `_delivery_20261024`、旧评分目录等 | 较早交付或已退出主链的实现 | 仅在明确需要历史比较时读取 |

不少关键新文件仍未跟踪，包括 `construction_layers.py`、`construction_relations.py`、`construction_quality.py`、`construction_progress.py`、`construction_learning.py` 以及识别模块的新辅助文件。因此只读取 Git 提交会漏掉本次最关键的实现。

### 2.2 已核对的设计来源

- 用户本轮附件：[构筑阶段扣分机制优化实施方案，2026-11-04](C:/Users/27499/Desktop/YGO-Kito_构筑阶段扣分机制优化实施方案_2026-11-04.docx)。其中的实施批次、测试案例和操作性语句是待审阅的方案内容，不是本轮执行授权。
- DSH 项目“YGO-Kito：设计分层整理稿”，项目 ID `105f77a2-4345-4eca-9ef8-3c9ca5d496fa`，读取时 revision 42，18 个模块、22 条连接。已用 `design_workbench_projects`、`design_workbench_read` 读取，未写入。
- [11 月 3 日构筑完整优化设计提取稿](N:/YGO-Kito/.cache/audit-20261107/construction-optimization-upload.md)、[CB 问题整理稿](N:/YGO-Kito/.cache/audit-20261107/cb-question-upload.md)、[原始设计提取稿](N:/YGO-Kito/.cache/audit-20261107/original-design.md)。后续“先静态构筑、再 CB”的明确修正优先于原始路线先行的旧流程。
- [11 月 4 日识别优化方案的既存提取稿](N:/YGO-Kito/.cache/docx-extract/scheme.txt)。该稿是识别设计的主要详细来源，设计台尚没有对应粒度的独立识别模块契约。
- [11 月 7 日既有审阅报告](N:/YGO-Kito/_publish_20261030/docs/reports/2026-11-07-construction-and-axis-design-audit.md)作为检索索引，结论已对照本地源码和后续保存记录修正，未直接当作现状。

本次应用 `preserve-intent-and-execute` 与 `anti-overengineering`：围绕上述实际问题工作，不把缺少辅助演示代码、没有重跑旧测试或没有生成额外证明材料当作继续设计的前置障碍。

### 2.3 课程与权重的实际含义

`N:\YGO-Kito\_local_cpu_20261027\reports\training.hold.json` 保存显式训练暂停状态，`formal_training_authorized_now=false`、`automatic_release=false`。本轮“不进行任何测试”的用户指令独立成立，旧文件里的历史训练授权不改变本轮范围。

`course-continuation.json` 当前指向 `reports\optimization-20261031\2207-course-006`。该目录仍保留 `initial-four-stage-construction.json`、旧四阶段交接绑定及路线结果。`course\latest.json` 指向 `checkpoint-1.weights`，revision 1。读取这些索引没有加载权重，也不能由文件存在推定最新评分或新版统筹特征已用于该权重。

该存档的 `runtime-restore-check.json` 记录 `formal_training_started=false`、`model_checkpoint_modified=false`；这些是当时恢复工作的记录。旧 `local-training\local-course-001\status.json` 不是当前课程指针，不能拿其次数当最新进度。当前新构筑政策的接口已存在，已读旧课程绑定未提供新政策，旧运行报告也记录 `quality_policy_unconfigured`；没有看到与新收益方案绑定的实际课程评分记录。

## 3. 设计台与四类模型的职责

设计台当前给出的主线是：构筑目标模型先生成一次轴骨架，构筑优化模型补齐伴生卡、数量、泛用和 Main/Extra/Side，并在原目标下多轮优化；评价器依次处理轴统计、关系和资源支持；合格构筑交给 Basic CB；决斗模型在真实规则和可见状态下选择动作；统筹模块调度任务、记录预测与实际结果、决定反馈或重建。

Basic CB 是构筑后的静态展开参考，目标是在不考虑对手场面、手牌和阻抗的条件下获取更多资源。它不应把构筑限制成某条固定路线。设计台没有冻结评分权重和阈值，也没有要求把识别置信度、抽到概率或一场输赢直接变成构筑扣分。

决斗设计要求公共历史、己方合法知识和合法动作输入，策略/价值学习，CB 可作参考。统筹设计是确定性程序加小型学习模块；任务与结果关联已有归属，不另造平行账本。所谓超级智能体仍是候选思路，不能据此更换当前架构。

训练设计保留 BO1 主训练、BO3/换备评估、留出对手、基础权重与环境适应分离。设计台说明职责，不自动证明所有模块已经联通或达到竞技能力。

## 4. 构筑模型：已实现的基础与未闭合的位置

### 4.1 当前实现链

[build_model.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/build_model.py) 中目标与优化角色使用独立的 `BuildRanker`。默认是小型 Transformer：宽度 32、卡嵌入 16、4 个注意力头、1 层、前馈宽度 64、最多 192 token。它读取机制目录、公开效果记录和效果块；当前不是用固定卡组配方替代构筑模型。

[construction_fill.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/construction_fill.py:306) 已有 `build_axis_skeleton`：先选一次部分骨架，再由 `fill_with_existing` 填充和编辑。`construction_cycle` 管理优化迭代、预算、续接和最终交接，已具备“目标一次、优化多轮”的主体，不必退回旧四次交接模型。

[construction_layers.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/construction_layers.py) 区分真实副本数 K、折减后的投入 E、功能数量、覆盖和未知项。[construction_inventory.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/construction_inventory.py:106) 读取实际 Main/Extra 库存，按效果来源检查必要对象、材料和缺口，且明确“库存存在”不等于已经到手、到场或入墓。

[construction_relations.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/construction_relations.py) 已有 all/any、整数资源池、消耗/存在性主张、required uses、互斥与顺序未知、预算不足保留 unknown，以及增量重算。仅将显式 required uses 放入联合检查；不需要把全卡组效果假设成同一时刻全部执行。可选概率接口存在，但不应自动并入本次纯静态评分。

[construction_layer_flow.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/construction_layer_flow.py:25) 将实际候选与上述静态层连接；[construction_learning.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/construction_learning.py) 以及课程脚本已有比较对和反馈消费通道。因此不能概括成“构筑模型没有学习代码”；真正的问题是新统一评价尚未贯穿这些通道。

### 4.2 直接影响新方案的缺口

下列均为源码静态检查，不是本轮运行复现。优先级表示未来工作的先后重要性，不表示已开始修复。

| 位置 | 当前行为与影响 | 后续正式方案必须处理的事项 |
|---|---|---|
| `construction_fill.py:398–495`、`construction_layer_flow.py:248` | 先按分层缺口、偏序和旧模型顺序排序；存在绑定预算及保留候选裁剪，先选 retained order 中首个合格者 | 新质量必须在其负责决定的排序与裁剪之前完成；未评估候选保留未评估状态，不能当作低分 |
| `construction_fill.py:658–670,748–777` | `quality_of` 主要在本轮已选候选上计算；调用仅传泛用、同名用途和 Side 信息，不传 `losses`、`slot_uses` | 新收益/损失事实应接入统一候选记录，不能只给最后的 best 补一个展示分 |
| `construction_fill.py:777,821–824` | 保留候选没有普遍携带逐候选质量记录，后续 gate 又读取该字段 | 排序、选中、反馈、准入必须消费同一份绑定到候选的评价 |
| `construction_quality.py` | 仍是七项指标与分区百分制，包括 supply、continuation、limits、duplication、generic、side；存在 `min(1,E/target)` 饱和 | 尚不是规范功能项的 `log2(1+x)` 双通道收益；不能混用新原始对数损失和旧百分总分 |
| `construction_layer_flow.py:109–148` | 功能标识主要来自图节点与 zone，自动细化关系集中在少数已识别效果；广义效果/角色标签仍有未知关系 | 明确功能、用途、收益族、效果来源的稳定归并，扩展真实效果语义覆盖，不能靠拆节点增加收益 |
| `construction_layers.py:266,317` | K/E 基础存在，但部分功能行只有 Main 投入 E，Extra 为 `None` | 不能把当前 E 直接视为所有调用型收益已具备的新计分量 |
| `construction_quality.py:748` | 损失去重键为 `(benefit_id, reason)`；同一收益换个原因仍可再次扣原始贡献 | 以同一实际收益及其尚存份额结算，原因是解释，不是再收费凭证 |
| `construction_quality.py:709` | 逐卡位声明按 `(zone,card_id)` 聚合；已 verified 的 `status=unknown` 走入 used 分支，无法表达同名不同副本用途差别 | 先落实新方案真正需要的用途/收益事实，不能沿用任意固定卡位罚款补丁 |
| `construction_quality.py:807–838` | 区间做 lower−lower、upper−upper，随后仅因端点相等就标 complete | 此运算不能一般性代表有效分范围；新方案应在同一组未知事实补全下联合重算，不能让相关未知互相抵消为已知 |
| `construction_quality.py:861` 附近 | harmful 泛用事实的处理先于实际库存和问题范围过滤 | 损失必须绑定当前候选中实际参与的用途及已计收益；宿主提供的宽范围事实不能直接扣当前卡组 |
| `construction_quality.py:923` | `compare_quality` 用毛值与原始区间作偏好，净损失变化只出现在返回的 total range，可能仍判 equivalent；未发现生产调用者 | 属于接口一致性缺口，不能夸大为当前线上排序调用已触发；迁移时统一使用新最终有效分 |
| `construction_progress.py:74,103,169` | gate/restore 已绑定层结果、政策版本、配置与卡组，但质量记录校验没有同等绑定自身评价器版本、task digest | 在现有绑定上补齐迁移一致性即可，无需建立另一套审计或状态系统 |

`construction_quality.py` 文件头仍有 60/25/15 的旧文字，但实际默认 `zone_weights=None`，按适用区等权计算；不能误报为当前计算固定采用 60/25/15。`construction_contract.py` 中的 70/56 是未接入生产链的 M1 草稿，不是当前准入的有效常量。

`construction_progress.py` 在政策缺失时返回 `quality_policy_unconfigured`，没有“缺政策就默认过关”。当前首要工作是使评分的语义和消费链完整，不是给它随意补一个能过关的阈值。

### 4.3 11 月 4 日扣分方案的关键含义

该方案与 11 月 3 日完整优化稿应一起理解。正式方案后续需要落实以下语义，本轮不替用户冻结新数值：

1. 真实副本数 K 决定整数资源可用性，折减数 E 决定重复投入收益。Main 的 1/2/3 张对应 1/1.9/2.8，Extra 对应 1/1.8/2.6；三张卡的配置价值不等于同一回合能发动三次。
2. 同一规范函数 V 依次求潜在收益 P、自身条件与完整代价约束后的 V1、显式联合资源约束后的 V2、对其他已计收益的强制损害后的 S。差值账本用于解释，不再从 S 扣一次。
3. 每个规范功能有基础与主题通道。普通 Main 项按实际 N 使用 `x=40E/N`；真正受到支持的调用用途可使用 `x=E`。一张卡可检索，不等于它所有功能都免密度折算。
4. “墓地相关”与“堆墓”可按原意分别获得主题收益；检索不能继承目标卡的堆墓效果，作为代价送墓不能伪称效果堆墓。归并同义描述不应吞掉真实不同收益。
5. all/any、替代路径、整个代价、区域、材料、事件、HOPT 与共享资源都作用于具体 use。缺少六份中的一份，不能按 5/6 假装整个六份代价已支付；独立的三份替代路径仍应保留。
6. 不自动增加 Main 超 40、Extra 留空、必要伴生卡、同名 HOPT、未计收益的可选副作用或接近 100 分等罚款。独立有害代价必须说清损害了哪项已计收益；尚未定价的独立效用保留为 `unpriced_effect`。
7. Side 按宿主固定方向权重比较当前情境 X 与常驻 R 的功能增量，覆盖失效、恢复和损害；不能只算 R+Y，也不能在换备前使用 Side 资源。方向权重不是抽取概率，不要求先列具体换入换出表。
8. unknown、not_applicable、deferred 分开。上下界来自一致的事实补全，不能独立拼接每项损失的极值。收益按来源归并一次，不用总分截断掩盖重复扣减。
9. 最终有效分 S 决定其应负责的候选比较，且同一评价贯穿反馈、学习、准入与恢复。政策由宿主固定；CB 不参与这个静态评分。

这些是附件对现有实现的约束和迁移方向，不是已经实施的成果。附件中的未来批次和测试案例本轮均未执行。

## 5. 轴与泛用识别：设计、实现和训练状态

### 5.1 新设计需要表达什么

11 月 4 日识别方案已经超出“五个标签分类器”：候选轴来自结构闭包和类型/资源关系，允许轴重叠；轴大小、核心/辅助地位不能互相代替。主/次/支持位置与内生/外接/混合来源分开，机制由动作、主体、对象、资源、条件和收益表达，胜利终点与获胜策略分开。

功能职责包括进入、调度、供给、转化、输出、回收、保护、干扰；承担机制与增强机制可以同时成立。泛用相关判断拆为可迁移性、接收卡组兼容性、当前状态就绪度、环境价值。某一局没行动、缺少路线角色或状态未就绪，不能直接作为结构上非核心/非辅助的负标签。

新版 `RoleInput v3` 设想有 unit_analysis、deck_analysis、candidate_insert、state_evaluation 四种模式；卡号等可作为关联端点，不能把名字、样本引用和标签泄漏为学习特征。`LabelCell` 的 value/status、confidence、evidence、review 分开，缺失标注不等于负标签。

条件表达式需支持 all/any/at_least_k/not，保留真实整数资源、位置、时序、消耗/占用/保留/复用。每条替代路径独立求解，不能把不同分支各拿一部分拼出虚构可行性。Main/Extra/Side 的空与缺失也要区分。

拟议接入界面是 `analyze_deck`、`assess_unit(unit, receiver, context, requested_function)`、`compare_copy_change`，按 off/observe/assist 逐步接入。识别提供事实和解释，构筑拥有收益定价；识别的状态概率、置信度和环境价值不能未经定义直接转成构筑惩罚。环境 LoRA 需要真实对局及环境信号，不能只用静态频率冒充。

### 5.2 源码现状

| 文件 | 已有内容 | 尚缺的连接或直接问题 |
|---|---|---|
| [contracts.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/contracts.py:365) | `LabelCell` 定义、原有组/关系/机制契约 | 主 `RoleInput.from_dict` 仍接受旧 v2/v7 结构，训练目标仍是 float/None；逐格契约未贯穿数据、损失和输出 |
| [analysis.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/analysis.py) | `DeckSpec`、`UnitSpec`、v3 迁移外壳 | v3 外壳不能直接送回现有 RoleInput 加载器；尚无完整 `analyze_deck`、`compare_copy_change` 服务 |
| [network.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/network.py:114) | 宽度 64、两轮消息传递的图网络，结构/角色双视图；五角色、兼容、效用、配对输出 | 新轴成员、功能、位置、机制及四分支泛用头尚未落地；机制元数据尚非完整学习输入 |
| [training.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/training.py:55) | 旧头训练、None 掩码、来源记录、独立适配支持 | 还没有新 LabelCell 驱动的完整多任务训练路径 |
| [scoring.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/scoring.py:145) | 已撤掉 core/support 的 `plan_known` 硬归零；保留最小成员和功能已知的泛用门槛 | 一段解释文字仍声称有旧门槛；`CandidateScorer` 未成为构筑主链消费者 |
| [functional_units.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/functional_units.py:141) | 有来源确认、required 闭包及条件单位评估 | `minimum_members` 只展开 required；评估把所有满足的 alternatives 合入，而非保留逐分支最小解，替代成员的递归依赖与泛用性判断不完整 |
| [conditions.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/conditions.py) | 新条件解析和局部资源判断外形 | 匹配主要找单个资源，不能一般聚合多个供给；all 贪心，any/at_least_k 未正确传播已耗资源；占用、distinct、三值未知及 not 约束不完整 |
| [splits.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/splits.py) | 划分接口和协议名称 | source_rowid/reference/case_id 按优先级择一，未把共享来源关系做传递合并；不同协议尚无相应独立实现链 |
| [metrics.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/multifactor/metrics.py) | 覆盖和分类指标接口 | precision+recall 为 0 时 F1 返回 None，macro 又排除 None，可能忽略彻底错的头；预测 None 的样本跳过分类计数，需要明确该指标与整体能力的关系 |

上述新条件、划分和指标文件尚未成为当前活跃训练链的完整消费者。因此不能把它们的缺陷反推为历史训练必然已受同样影响，也不能仅凭文件存在宣称新版能力已完成。

`functional_units.py` 的替代路径问题会同时影响最小单位成员数和泛用定义；应优先把事实语义接通，再扩模型头。既有卡片文本、效果记录、效果块、资源类型和整数库存可以复用，不需要另建第二套完整规则引擎。

### 5.3 当前数据准备与已保存训练

[prepare_base.py](N:/YGO-Kito/_publish_20261030/training/axis_generic/prepare_base.py) 已有 P0 标签迁移：撤回“路线演员缺席”的 core/support 负标签，将相关格改为 unknown；状态就绪类反例也有剔除记录。但现有 `dataset.json` 一旦存在便直接返回，缺少与请求语义/配置的显式一致性判断。默认配置仍指旧 `v7-repo-001` 缓存，不能假定改了准备代码就使所有旧数据自动升级。部分 set 遍历与随机状态提示也还未形成稳定的数据准备约定。

以下只读取 JSON 记录，没有打开 `.pt`：

| 已保存运行 | 本地记录 | 对当前能力的意义 |
|---|---|---|
| `training/axis_generic/runs/v7-dev-expand3` | 620 次更新，约 1430.36 秒；2026-11-03 完成保存；RTX 4060 Laptop GPU，CPU fallback=false | large_axis、generic_utility 退化，`eligible_to_replace_previous_limited_base=false` |
| `training/axis_generic/runs/v9-p0-smoke` | 149 次更新，407.375 秒；2026-11-04 完成保存；同一 GPU；迁移 4700 个 actor-absent 格为 unknown，剔除 1997 个 readiness-only 反例 | large_axis、support_role、generic_utility 未过保留门槛；仍 `eligible_to_replace_previous_limited_base=false` |
| `training/axis_generic/runs/v9-p0-n2` | v7.1 准备清单：train 4751、validation 1362、retrospective 18；来源数 3086/941/3；机制 known 20、unknown 98；同样记录 4700 格迁移 | 读取到准备产物，未见该目录的训练 checkpoint/status/results；不是另一轮已完成训练 |

两次有结果的运行都没有新增独立最终样本，`new_independent_final=false`、`human_gold=false`、`lora_stage=false`、`core_course_resumed=false`。固定参考池 118 个，包含已观察/训练见过的参考。新 checkpoint 的存在不代表它已安全替换旧基础模型；本次读到的候选记录恰好明确拒绝自动替换。

较早 v6.2 的训练和小样本记录仍可作为历史，但不能再用“只有 v6.2、后续尚未训练”描述当前状态。反过来，也不能把 P0 的一次小训练说成新版四分支识别器已完成。

## 6. 决斗模型：供原聊天继续设计的基线

[duel_model.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/duel_model.py) 已实现 Transformer actor-critic。默认宽度 32、卡嵌入 16、4 头、1 层、前馈 64、历史长度 32、最多 256 token，单页最多 2048 动作。状态编码包含己方与公开可见卡、位置、控制权、数值、LP、回合/阶段、公共历史、合法私有揭示、检索选择及求和约束；原始对方隐藏牌和完整私有回放不能作为模型状态。动作由卡指针、描述和动作特征评分，并有价值头。

[hierarchical_policy.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/hierarchical_policy.py) 对大量合法动作分页计算并按精确概率质量采样，可覆盖超过单页上限的动作集合；这里的“层次”是计算分页，不是已经学习了高层战术选项。

[cpu_training.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/cpu_training.py:234) 的命名虽含 CPU，接口支持配置 GPU。它连接真实原生引擎与逐座位可见 DTO；完整新鲜 episode 用于 GAE、PPO clip、value MSE、entropy、Adam 和学习率调度。主要奖励仍是终局胜 +1、负 −1、和 0。辅助资源/妥协信息存在于其他通道，不能说已成为默认 PPO 密集奖励。

[duel_planning.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/duel_planning.py:237) 是有限预算的可见信息 expectimax 风格规划器。默认预算约 96 节点、深度 4、12 个根动作、0.025 秒；它使用自身卡组知识、公开事实、次数限制和经过整理的 CB 计划，生成有界 bias 加到神经网络 logits。训练重放保存同一规划 bias，避免旧动作概率和更新时策略不一致。

其未来状态主要来自效果/材料/费用的投影、启发式价值与对手响应风险，而非逐分支克隆原生引擎状态。因此现有实现提供了实际的搜索辅助，但还不能直接称为完整规则级 MCTS 或完整对手信念求解。神经编码器本身也没有完整效果图编码；效果知识主要经独立规划器进入决策。

Basic CB 已有真实规则路线验证与继续搜索能力，但当前主路径主要找到满足范围的可行路线，尚不能将其等同于设计台“在静态条件下尽可能最大化资源”的完备优化结果。它与对抗场景的决斗规划应保持各自目标。

后续在原聊天需要明确的设计议题是：神经网络与规划器各自承担哪些决策；状态和历史如何表达长期资源、计划与未知对手信息；终局学习和中间目标怎样对应；BO1、BO3、换备及对手课程如何服务能力增长。这里列的是待讨论对象，不是本轮替用户选定的新路线。

## 7. 统筹模型：供原聊天继续设计的基线

[coordinator.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/coordinator.py) 已有 SQLite 支持的候选、冻结预测、任务、结果、检查、警报和解决记录。程序负责允许动作、任务认领、结果归属和窗口一致性。该部分已经承担真实控制职责，不应被小模型输出直接绕开。

[coordinator_model.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/coordinator_model.py) 已从早期结构发展为：14 个基础上下文特征、两层 16 宽 MLP、7 路路由输出、胜率预测，以及 64 维范围情境投影和预算头；可选机制 v3 再增加己方与对手公开效果摘要投影。7 路为 build_goal、build_optimizer、register_forecast、evaluate_duel、train_duel、diagnose、stop。学习使用路由 CE、预测 MSE，有预算标签时加入预算 MSE。执行动作仍受宿主允许集合和预算上限约束。

[course_models.py:88](N:/YGO-Kito/_publish_20261030/src/ygo_kito/course_models.py:88) 的 `coordinator_mechanism_inputs` 默认 false，新的基础初始化可以显式启用；旧权重和 LoRA 窗口不能因为源码存在 v3 就被认为已经升级。机制摘要通道的存在与它在当前保存课程中生效，是两件需要分别说明的事。

统筹训练并非只有合成规则模仿。[local_course_forecast.py:460](N:/YGO-Kito/_publish_20261030/scripts/local_course_forecast.py:460) 已可将完成的 BO1 训练对局结果，按事前记录的情境、模型和样本归属，交给预测头训练；但单场标签不是“实测胜率”，代码也保留 calibration pending。构筑阶段切换还可形成路由监督。预算头虽然存在，其有效调度能力和充分的真实预算监督不能从结构存在推得。

[coord_contracts.py](N:/YGO-Kito/_publish_20261030/src/ygo_kito/coord_contracts.py) 保留旧 100/1000 政策，也有 20/50 及响应式版本。当前 `CourseForecast` 默认响应式 20/50。20/50 是在冻结预测下出现不足时的条件检查，不能写成“每 20 场优化、每 50 场无条件重建”。已开始的旧窗口不应被新政策改写；静态构筑或 CB 的 unknown、未运行、预算耗尽也不能被冒充已完成失败。

后续在原聊天需要讨论的是：哪些动作由程序确定、哪些真正值得学习；预测目标应按什么卡组、对手分布和模型阶段分层；有限预算怎样分配给构筑、CB、训练与评估；怎样使反馈闭环与用户目标一致。已有任务与结果机制可以继续使用，无需先建设额外总账平台。

## 8. 两个后续交接的界面与禁止重复事项

构筑任务未来负责形成正式优化方案：把 11 月 3 日收益设计、11 月 4 日扣分设计、设计台和现有消费链逐项对应，明确保留、迁移与删除的旧机制；最先处理规范收益、条件/资源/损失语义和逐候选统一评价。正式方案应具体到数据契约、文件、调用链与逐项验收要求，但本轮不生成，也不执行其测试。

识别任务未来负责后续开发安排：以现有图网络和 P0 迁移为基线，先把新版输入、LabelCell、分支成员与资源事实接通，再扩展新输出及构筑接口，保留可回退的基础模型。上述候选均未过旧模型替换门槛，不能把“继续训练”默认为直接覆盖旧模型。

两任务共同保持的边界是：识别提供功能、成员、条件、资源及未知事实，构筑评价器按固定政策定价；实际执行与次数裁定沿用真实规则引擎；决斗模型决定当前动作，统筹模块安排任务与反馈。避免两任务各自重写一套相同的条件/资源求解，也避免把泛用概率或状态就绪度偷偷变成构筑扣分。

禁止重复：不要因本报告又重跑旧测试、复训模型、加载权重、运行 CB 或构建引擎；不要清理或覆盖当前未提交改动；不要恢复已退出主链的私有评分或旧四阶段流程；不要为缺失辅助演示代码创建新的证明工程；不要修改设计台来掩盖实现差异。后续真正启动代码修改时，再按用户的代码执行细则交付机械执行书，当前交接不是实施授权。

## 9. 交接状态与连续性

原始目标是先完成项目审阅，再创建两个仅交接聊天，之后在原聊天继续决斗与统筹设计。本报告完成了审阅部分，列明了真实文件、保存记录、源码缺口和后续范围。

没有待答问题；没有权限或外部服务阻塞。新聊天的启动条件是用户在对应聊天明确发出开始指令。新聊天收到交接后只简短确认并结束，不能主动检索、起草正式方案、修改文件或测试来填补等待。

已在同一个本地 YGO-Kito 项目中建立两个聊天，未创建新工作树、未指定新的实施模型。通过 `wait_threads` 确认二者都已回复接收、完成当前轮并处于 idle，快照未出现工具调用标记：

- 构筑模型正式优化方案交接（待启动）：`01a1bb9e-d51d-7181-8d89-fde957e4642f`。
- 轴与泛用识别后续开发交接（待启动）：`01a1bb9f-7525-7201-bfef-631a171c34ad`。

两个首条提示均已传入目标、当前源码与工作树状态、设计来源、主要发现、已保存记录、未完成工作、禁止测试/训练与覆盖文件的要求，以及提问等待和长任务交接规则；均明确要求本轮只确认，不读取更多文件或开始正式工作。

长任务继续规则仍适用：优先在当前聊天继续并允许压缩；若后续压缩可能损害目标、约束、文件状态或验证证据，或阶段形成合适安全边界，应完成当前非破坏性原子步骤后停止新阶段，建议新开聊天并给出独立可执行摘要。没有用户明确确认，不得自行创建续接聊天；不能把沉默视为授权，也不能声称看见精确上下文占用百分比。
