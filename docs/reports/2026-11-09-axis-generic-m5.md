# 轴与泛用识别 M5 实施记录

日期：2026-11-09，香港时间。状态：M5 代码已实施、待运行验证；未运行测试、项目导入/编译、推理、训练或数据准备，未进入 M6。

## 机械执行补充

承接执行书 M5，由主进程实施，不使用子代理。修改前 31 条路径已登记至 `.cache/axis-generic-m5-20261109-01/manifest.json`，其中 24 个既有文件已保存并逐字节核对，7 条新增路径原不存在。保留当前 dirty/untracked/deleted 状态，不替换基线、权重、旧配置、课程暂停或构筑政策。

1. `contracts.GRAPH_ATTRIBUTES/semantics.condition_nodes`、新增 `task_queries.py/graph_network.py`、`network.NetworkConfig/encode_batch/RoleNetwork`：在现有图上增加明确的结构/状态条件范围，建立独立于金标的受控任务查询空间。v3 使用稀疏全局边索引、按预算分块，所有节点/候选参与；宽 64、两轮，单流/双流与路线特征分别显式配置，默认双流、路线关闭。旧 v7 编码与参数名保留。输入仅取 observations；ID 只作端点寻址，机制/角色值不输入编码。通过标准：Q4 的排列、混批、分块、状态分流和金标不进入张量等用例源码齐备，逐处文本回读；实际前向待授权。未知任务/坐标、混合 schema、超预算或缺端点明确拒绝，不能截断或填零冒充已知。
2. `training.Targets/RoleTrainer`、新增 `graph_training.py`：接通 v3 全部可学习头、完整单元/功能查询、独立成员与 carrier/enhancer、多类位置/来源/迁移/兼容及有向关系和副本偏好。先逐格验证状态/域/来源/分区/协议，再计算已知格 BCE/CE；来源组平衡只参与有效格分母，证据置信度只乘分子，分组任务先归一再组合。全部未知或零证据批次不前向、不优化、不更新能力计数。明确声明、同来源/目标的反事实一致性可单独加入损失；state_readiness 仍为确定性任务，environment_value 保持禁用。通过标准：人工标签的掩码、弱证据缩放、混合逐格来源、无监督跳过、关系方向及各头独立计数用例源码；不运行。发现不可信上下文来源或标签坐标不属于事实查询空间，停止本批更新，不改成负例。
3. `training.RoleTrainer.save/load/warm_start`、`adapters.base_binding`：v3 checkpoint 绑定架构/特征/查询词表、标签、数据/划分、校准及训练配方，保存 Adam、逐头状态、采样游标与 Python/Torch/已加载 NumPy/CUDA 随机状态。resume 要求相同绑定与显式预期配置，严格检查权重/Adam；warm_start 只复制语义与形状一致的共享编码器，重建优化器、游标、新头与能力状态，不用 strict=False。v3 权重保存使用新文件，旧权重不覆盖；LoRA 绑定扩展版本状态，v3 本批不自动启用环境适配。通过标准：绑定不符拒绝、随机/采样续接、共享参数显式清单及新头清零用例源码，Q5 运行继续暂停。失败时保留原文件，不退化加载。
4. `train_base.batches/update/fit/main`、新增 `train_v3.py/config.train.v3.json`、`finish_existing.finish`：显式 v3 配方消费 M4 分片，确定性打乱与可恢复下一批游标，训练和开发来源隔离；只在开发集按固定任务覆盖选模，校准/最终留出不自动打开，评估只调用统一 assessment。准备与训练输出目录分开，新配置维持正式训练和课程暂停。旧入口显式委托，旧固定五头收尾不误消费 v3。通过标准：数据到训练/保存/恢复/保存预测评估均有可调用路径及源码用例；实际加载数据、预测和训练全部不执行。未知配方、目录冲突、旧/新任务混用时写入前拒绝。
5. 新增 `tests/test_multifactor_learning_v3.py`；更新执行书/MASTER-CHECKLIST 与本记录。只做 PowerShell 文本/JSON、差异空白及文件保护核对，列明真实未验证项；不得把用例源码、构筑任务成绩或旧 checkpoint 状态当作本批通过证据。只逆向撤回本批差异，不覆盖其他任务改动；停在 M5 边界。

## 已实施的网络与查询

新增 `task_queries.py` 定义固定输出词表及由输入事实限定的查询域，`graph_network.py` 承担稀疏图编码和查询读出。`NetworkConfig.v3()` 与训练配方默认宽 64、两轮、双流和关闭路线特征；工程用例允许小宽度。旧默认构造与 v7 参数路径保留，v3 必须显式指定 schema 并提供 GraphBuild 或 M4 四块记录，旧 RoleInput 不会被静默送入新编码器。

节点用连续全局索引，边按块发送消息并分别汇总入/出方向；跨块边不丢失，图间不互相聚合。三分区空/未知和副本数均保留，数值按版本绑定的 signed-log1p 变换输入；不使用卡号、主题、来源、标签或不透明引用的嵌入。节点/边预算超限明确报错，节点块预算不等于图节点总量上限。查询每 32 项计算，继续遍历后续块。

条件节点新增受控 scope_structure/scope_state 特征，公共构造器在整个条件子树保留范围。双流的结构路径屏蔽状态条件与资源池实例，情境路径保留它们；单流使用同一完整表示。路线开关独立控制观察边上的两跳供需汇总，没有引擎成功轨迹或金标机制图输入。该受控属性扩展已改变特征指纹；未来准备/训练必须匹配新源码清单，不能误复用修改前的 v3 缓存。本批没有重建缓存。

| 学习头 | 查询范围与独立输出 |
|---|---|
| mechanism | 已观察卡/效果/功能节点；受控功能及费用、目标、自肃、回收等辅助多标签 |
| axis_membership | 自然候选轴 × 全部观察卡/单元；独立 sigmoid，同卡可多轴，不以候选支持集硬限成员 |
| axis_function | 候选轴 × 固定功能词表 |
| function_role / contribution | 单元、可选机制节点、受控功能查询；功能角色多标签，carrier/enhancer 独立两格 |
| axis_position / axis_origin | 各自三类，监督与状态独立 |
| transferability | 完整单元/功能的三类；省略功能只允许从输入唯一功能明确解析 |
| receiver_compatibility | 单元在接收结构中的二类预测 |
| pair_relation | 有序单元对的 dependency/substitute/support/conflict 多标签，保留方向 |
| copy_preference | 有序对的 left/equal/right；跨图比较还要求相同冻结目标、规则/时期、请求功能和显式比较操作 |
| legacy 摘要 | 五角色、兼容、关系仍为独立旧语义任务，不替代新头 |

共 18 个可学习任务登记逐头能力计数。state_readiness 返回 deterministic_only，不建立神经损失；environment_value 为 disabled。新模型的学习头状态初始全部 untrained；没有能力发布或校准通过标志。

## 损失与来源边界

`Targets.graph_cells()` 统一输出具名逐格目标，v3 `RoleTrainer.train_supervised` 消费完整四块记录。known 格先校验任务域、事实查询端点、train 分区、协议及 cell_sources；mixed 记录逐格认定来源，不能拿 engine/candidate 结果冒充上下文角色。unknown/conflict/not_applicable 不进入 BCE/CE，遗漏格不补负。准备器仅调整逐格来源 JSON 键的 Unicode 规范，使非 ASCII 引用与共用预测键一致。

每头损失为 `sum(source_weight × evidence_strength × cell_loss) / sum(source_weight)`。来源权重沿用 M4 的 train 有效格统计，直接工程调用未提供权重时按批内来源组计算。证据强度使用目标/原始格来源置信度的受限值，再乘独立来源置信度，避免将同一置信度重复平方；证据不进入分母。功能相关各头先归一再组成任务组，其余组采用执行书初值，最终按有效任务组权重均值组合。

全部未知、零置信度或全部相关任务组关闭的批次跳过前向和 Adam，步数、数据更新摘要及能力计数不变。没有有效监督的头不增加能力计数。明确给出同来源、同内在单元定义和证据的 transferability 反事实对可加入一致性项；接收角色不会自动被声明为不变。副本偏好要求可信比较来源并单独记数，没有偏好标签不更新。

训练支持 `supervision.training_queries`，每项只有 `source_candidate_ref` 和 `members`：功能、模式、条件与可信度借自已有自然查询，支持集只能引用观察到的物理成员。训练专用虚拟查询池化已有表示，不改编码图、自然候选表，也不将“是否注入”放进数值特征。默认推理/评价域忽略该字段。金标轴没有自然或显式训练查询时保留真值并计 unrepresented_candidate_cells，不能凭空造输入；评估该格记拒答/漏检。

M4 的轴评价消费者同步接线：预测成员可超出原候选支持集，但须来自全部实际观察卡/单元；不再要求预测集合等于候选种子。开发诊断对所有自然轴遍历全部成员查询，按来源组、自然候选召回及最优 IoU 口径评价。只有显式 raw 诊断输出；未拟合的 calibrated/applied 层留空并按统一口径计拒答。全量成员查询超公开预算时报错，不对一部分候选出成绩。

## 保存、恢复与训练入口

v3 checkpoint 使用独立 axis-checkpoint-v3-m5 版本，记录架构、受控特征/查询词表、标签协议、数据、来源划分、未拟合校准和配方绑定，以及模型、Adam、逐头计数、滚动数据摘要、下一批采样游标、选模进度、Python/Torch/已加载 NumPy/CUDA 随机状态。当前使用固定学习率，scheduler 明确为 None。Torch/CUDA 版本、线程数、浮点与后端设置亦登记；resume 不会把不同运行设置称为同一续跑。

resume 必须提供预期配置与数据等绑定；检查完整参数名/形状/类型/有限性、Adam 参数组/矩状态、来源计数、游标、设备与运行设置，之后恢复随机状态。不存在 `strict=False` 或缺参数自动补齐。warm_start 创建新实验，只按明确前缀复制语义、形状一致的共享图编码器；输出头、函数查询读出、优化器、游标与能力计数全部重新初始化。旧 v7 没有相容的图编码器，不能假称迁移了旧权重。

每个 v3 权重快照写新文件，通过同目录临时文件和不替换已有目标的原子链接提交；原文件存在即拒绝。底座绑定包含 v3 实验与任务权重，当前 v3 基础阶段不自动开启 LoRA。旧权重、旧运行与原源码绑定保持原样，不承诺修改后的源码可直接恢复全部历史 checkpoint；修改前包已保存。

新增 `train_v3.py/config.train.v3.json`，旧 batches/update/fit/main 及 finish 显式委托。配置中正式训练、自动 LoRA 和课程恢复均保持关闭；直接入口先检查暂停，再触及 Torch/设备和数据。准备目录与训练目录隔离，旧或非空新实验目录不被覆盖；运行时使用进程退出即释放的 OS 锁。

训练读取 train/validation 两种分片，核对解析内容摘要和来源组件，不打开 final、retrospective 或 quarantine 分片。校准组必须是明确保留的 validation 来源，训练和开发选择均排除它们。确定性打乱按种子、时期和分片文件名重建，checkpoint 保存下一批位置；保存恢复同时保留开发选择进度。开发选择使用预先固定、具有全局类别覆盖的任务集合，按来源组平均整体准确率；无需每个独立来源自己包含所有类别。覆盖不足保留 selection_score=null，不自动删头凑通过。全部头的 F1、覆盖和三层结果仍由共用 assessment 报告。未拟合校准、独立最终评估、发布和活动指针切换均留在后续阶段。

## 验证状态

新增 `tests/test_multifactor_learning_v3.py` 共 33 个用例源码：大图、排列/混批/分块、状态分流、双开关、标签与来源不进入张量、全域成员与有向关系、训练注入隔离、逐格掩码与弱证据缩放、混合来源、偏好/一致性、下一步恢复、Adam 损坏拒绝、warm_start 清零、不可覆盖快照、批次游标及训练暂停。执行数为 0，未收集测试；这些源码不是 Q4/Q5 或 A07 已通过的证据。

本批仅使用 PowerShell 文件/文本读取、JSON 解析、Git 差异和文件保护检查；未启动 Python、导入 Torch 或项目、进行 AST/语法编译、准备数据、加载 checkpoint、运行前向/推理、优化器测试、训练、CB、原生引擎或 CI。数值稳定性、实际 CUDA 稀疏算子/确定性支持、损失梯度、保存恢复后一致更新、吞吐和实际数据覆盖均尚待运行验证。没有提交、推送或发布。

静态回执位于 `.cache/axis-generic-m5-20261109-01/static-review.json`：31 条修改前登记路径中，本批 19 条声明变更路径以外的 12 个文件内容摘要一致；20 个原 tracked deletion 均未恢复。声明路径行尾空白为 0，Git `diff --check` 返回 0。新增 JSON 配方可由 PowerShell 解析，64 维/两轮/双流/路线关闭及 18 个选择任务已回读，formal_training/automatic_lora/core_course_resumed 均为 false。回执只证明文本和文件保护核对，不证明语法、运行行为或 A07 已通过。

## 独立续接摘要

原目标是按 `docs/plans/2026-11-08-axis-generic-execution-plan.md` 分批迁移轴/泛用识别，同时保留全部既有修改。本阶段已形成 M5 源码交接边界。实际工作区为 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，本批未提交，基线 HEAD 为 `3f57198e5e366152bbb672be8910e6800f8adbb4`；整个仓库仍有大量其他任务的 dirty/untracked/deleted 改动，不得 reset/clean/stash 或据 HEAD 替换。

已完成状态为 M0 修改前保存，以及 M1–M5 代码实施、运行验证待授权。M1–M4 的实际说明见相邻报告；M5 真实变更集中在 multifactor 的 contracts/semantics/network/training/adapters，新增 task_queries/graph_network/graph_training，训练目录 train_base/finish_existing/prepare_v3/assessment/runtime，新增 train_v3/config.train.v3 及本批测试源码。旧配置、数据、权重和暂停状态未改写；M5 受控条件范围导致特征缓存身份变化，T1 将来应准备匹配的新数据，不能删旧缓存强行复用。旧主计划尚未进入 v3 图的 core/support 标签继续 unknown，需在资料阶段补有依据的观察/标签。

当前没有代码运行或能力验证证据，只有文本/JSON/差异与文件保护核对；33 个 M5 用例、前批用例均没有在本聊天执行。严禁把并行构筑聊天的测试成绩借给识别模块。M5 默认 formal_training=false；新头全部未发布，calibrated/applied 未拟合。当前没有待答问题，也没有让用户批准的执行中动作。

下一阶段仅在用户明确要求后实施 M6：三个分析服务、capability/off/observe/assist、候选 scorer 和真实构筑消费者最小接线；读取共享文件的最新状态，保留并行构筑到第六批及以后的改动，不添加构筑定价。M7 和 T1–T4 仍未开始；当前测试、推理、训练、CB、原生引擎、实际数据准备、权重/活动指针切换全部禁止。禁止重复建立 M0–M5 基线、恢复既有删除、重跑旧验证或擅自创建新聊天。

建议新任务首条提示：

> 请在 N:\YGO-Kito\_publish_20261030 继续按执行书实施 M6。先读 AGENTS.md、用户代码执行细则、docs/plans/2026-11-08-axis-generic-execution-plan.md 及 docs/reports/2026-11-09-axis-generic-m5.md。M0–M5 已保存并实施源码，全部待运行验证；保留所有 dirty/untracked/deleted 及并行构筑修改。仍不运行测试、推理、训练、Python 导入/编译、数据准备、CB 或原生引擎，不切换权重/暂停/课程指针。交付 M6 机械执行补充后由主进程执行，不启用子代理。遵守原上下文窗口与任务交接规则：优先在当前聊天继续；当再次压缩可能损害准确性/约束保真，或形成适合交接的安全边界时，完成当前非破坏性原子步骤后主动建议新任务，同时提供完整独立交接摘要；未经用户明确确认不得创建新任务。
