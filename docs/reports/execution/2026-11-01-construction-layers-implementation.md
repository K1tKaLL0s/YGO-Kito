# 2026-11-01 两层构筑评价首轮实施书

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

2026-11-02 更新：本文保存首轮实施过程。后续已修复未知覆盖、图外配套、字段子串误判、召回及学习重选，并删除旧参考评分和并行构筑实现；当前状态以[统一修复报告](../2026-11-02-construction-unification.md)为准。

状态：两层内核、显式适配和主流程接线已实现。现有控制器的候选选择、四阶段交接及后续保留候选改选使用两层评价；20项新接线CPU测试、既有两层72项及限定旧回归通过，新增真实GPU检查完成。当前接线与证据见第11—12节，第9—10节保留逐层实施历史。正式训练继续暂停；主进程实施，复用当前检出，未启用子代理或新工作树。

工作目录：`N:\YGO-Kito\_publish_20261030`。依据为[第一层r3.1](../../current/construction-workflow.md)和[第二层r3](../../current/construction-scoring.md)，评价与取舍沿后者第4节。既有[构筑逻辑](../../development/construction-logic.md)和[效果语义接口](../../development/effect-mechanism-construction.md)说明当前可复用能力。

## 1. 任务目标与本轮实现范围

实现可直接调用的CPU两层评价入口：接收选定骨架、用途要求、卡片张数及有来源的效果事实，输出第一层分项、第二层支撑/条件/竞争、改卡差异及推荐或取舍理由。现有候选列表可以通过适配入口获得同一评价。

首轮包含已确定的第一层统计、关系匹配、静态共享资源检查、有限改卡比较、单次取得/留库概率及候选列表适配。它不承担自动选择所有主轴、完整整副总分、模型新特征训练、泛用/Side优化、CB求解或运行快照迁移。输入骨架由调用方已有选择提供，不能用珠泪参考表作为默认生成答案。

验收结果应同时满足：

- 同一物理库存被多个模块引用时，统计去重；K/E、密度与U符合第一层既定公式。
- 多输入、替代、区域/原因、共享次数和资源竞争能产生正确的支撑说明及改卡差分。
- 同名增量、不同限次组与独立来源不会混成相同收益；不按关系数奖励。
- 已知支撑、明确缺口、语义未知及预算未覆盖范围分别保留。
- 对完整候选调用既有卡表约束校验；部分骨架保留未分配位置，不被伪装成完整合法牌表。
- 可从现有事实记录构造输入，并读取现有portfolio候选；评价本身不调用CB或训练。
- 匿名机制、卡号重命名、模块拆分及枚举重排下，关系评价保持相同含义。
- 预算计数可见，静态事实复用，增量与完整评价结果一致。

## 2. 当前代码依据

| 实际文件/符号 | 已有行为 | 首轮使用方式 |
|---|---|---|
| `effect_mechanisms.py: EffectSemantics / MechanismCatalog.card / effect_records` | 保存效果、素材、次数、区域移动及未知；卡文变化时更新缓存 | 读取事实及既有来源标识，不重新写一套卡文解释器 |
| `effect_records.py: effect_records` | 按效果导出条件、支付、操作、次数、限制和知识状态 | 保留效果索引、来源、数量与未知，供关系适配 |
| `construction_effect_blocks.py: reviewed_effect_blocks` | 提供来源绑定的粗标签；当前默认主要覆盖卡组送墓与墓地融合 | 复用已有明确分类；其他已审核角色作为显式输入，缺失不伪造覆盖 |
| `build_contracts.py: DeckParts / BuildTask` | 卡表数量、分区、固定要求、环境与候选预算 | 保持原DTO和schema；新增层级输入单独承载模块、用途及未分配量 |
| `construction_binding.py: CatalogBindingAdapter` | 保存语义目录与来源绑定的功能判断 | 调用方可复用其目录与判断，不重建自动绑定流程 |
| `construction_candidates.py: portfolio / changes / axis_edits` | 构造有界候选和改动；最终保留最多32项，已支持有来源的小包 | 适配已有候选输出；不复制候选生成器或绕过卡表检查 |
| `construction_fill.py: fill_with_existing` | 候选生成、现有模型排序和后续核验相连 | 作为后续主流程接线位置；首轮不把新分析入口挂到CB调用链 |
| `build_model.py: BuildEncoder / BuildRanker` | 已有模型输入及机制特征 | 本轮不改张量宽度、特征含义或checkpoint版本 |

特别注意：`EffectSemantics.route_ready`服务于现有起手提议，要求无费用、无对象等条件。第二层不能用它作为统一准入条件，否则会错误排除有支付、有对象或依赖条件的正常构筑关系。适配读取各项事实及知识状态，分别记录需求。

工作树已有其他未提交程序、测试、配置和文档变更。实施前查看目标文件差异；只叠加本实施书范围内的改动，不重置、清理或恢复其他任务的文件。

## 3. 文件范围与路由

计划新增：

- `src/ygo_kito/construction_relations.py`：关系输入、索引、支撑与竞争评价、配置比较及局部更新。
- `src/ygo_kito/construction_layers.py`：骨架输入、第一层统计、既有事实适配及公开组合入口。
- `tests/test_construction_relations.py`、`tests/test_construction_layers.py`：对应的CPU行为检查。

计划修改：`scripts/check_merge_candidate.py`只向显式CPU白名单追加上述两个测试模块；三份现行设计/入口文档及MASTER记录真实实现和验证状态。

保持原样：CB与原生模块、现有模型/训练/恢复逻辑、评分数据及参考卡表、现有卡文识别规则、旧DTO及旧候选生成/排序接口。首轮通过新适配入口消费已有候选，不自动改变旧构筑主流程的选择结果。

上述接口现已实现，具体调用方式以第10节为准。内核采用标准库，未引入图数据库、通用逻辑求解器、额外模型或新依赖。

## 4. 数据与接口决定

`construction_relations.py`定义以下记录：

| 记录 | 必要内容 |
|---|---|
| `UseRequirement` | 稳定用途标识、原任务优先级、必需/可选、数量及明确的all/any输入组 |
| `RelationFact` | 供给/接收效果引用、区域/原因/类型条件、数量与消耗方式、共享资源/次数组、限制、来源及知识状态 |
| `RelationEvaluation` | 每用途supported/missing/unknown、条件与缺口、共享瓶颈和竞争、统计/预算覆盖 |
| `ConfigurationComparison` | preferred/equivalent/tradeoff/undetermined、方向、支撑/条件/瓶颈/占位变化及原用途损失 |

`construction_layers.py`定义`SkeletonSpec`与`LayerContext`：前者保存候选实际库存、所选模块引用、已分配及未分配位置；后者保存原任务、用途、功能角色判断及预算。每个候选有自己的骨架分配，不能把基线模块归属不加检查地套到换卡后的候选上。

模块是对库存的引用，不复制物理卡。用途标识与效果/卡名限次组分开。候选卡号用于事实与库存身份，不参与主题特判。第一层角色判断q来自已有功能或有来源的明确判断；未知不自动等于0，字段相关的0.5也不用于核心功能覆盖。

已实现公开函数（原实施接口表）：

| 函数 | 行为 |
|---|---|
| `evaluate_axis(skeleton, context)` | 按r3.1输出模块及骨架总览的q/A、K/E、密度、U和占位 |
| `relation_index(catalog, context)` | 读取当前所选与已召回事实，规范化并索引；不调用路线提议或CB |
| `evaluate_relations(skeleton, context, index)` | 整理支撑、条件、共享资源与瓶颈，输出范围内评价 |
| `compare_configurations(before, after, context)` | 按既定用途与第4节顺序给出差异及取舍；函数内部不新召回 |
| `evaluate_layers(skeleton, context, catalog)` | 组合两层结果，输出独立版本的评价记录 |
| `evaluate_portfolio_layers(rows, skeletons, context, catalog)` | 消费现有候选行及逐候选骨架，逐一评价并返回比较；保留原候选身份、顺序及已有分数字段 |

返回版本使用`construction-layer-evaluation-v1`，与旧模型特征版本无关。结果不设置合法CB、实战强度或完整评分通过标记。完整候选校验复用调用方已有的`assets.validate`；适配器接收已有assets/catalog，不自行构造原生资源环境。

语义规范化只处理现有字段可表达的条件、公开属性和明确的all/any组合，不解析任意条件表达式。粗图合流没有明确需求依据时保留未定。区域相同而原因不同、状态与事件、固定数量与未知数量，均不得在规范化时合并。

## 5. 确定采用的计算路线

先按不同卡及效果取得事实，建立供给/需求和共享组索引。已有取得来源或给定输入作为依赖整理的起点，有限工作表更新支撑组；这只更新配置支撑状态，不移动卡片、不消耗一次实际效果。没有外部来源的循环不能自行产生正向支撑。

多输入需求共用一组计数与条件，替代按供应者集合保留，不枚举供应者组合。资源容量只在角色、数量和共享关系明确时下结论；宽素材集合的全局分配、回收时点和动作顺序保留条件。不能以成对无冲突证明全部共同用途成立。

张数修改复用静态事实和匹配索引，更新涉及的库存、用途和竞争组；新增/删除卡或改变模块时更新对应依赖。改变目标或卡文来源则重新建立受影响评价。完整评估函数是增量结果的对照，两个入口应给出相同语义结果。

候选和召回预算在本层开始工作前固定，候选数服从`min(32, task.candidate_budget)`及宿主更小的上限。本层只处理所选/已召回的有限集合，不为补齐一个未知条件扫描全卡池；调用方给出的匹配/依赖计数或时间上限在检查边界生效。预算不足返回已完成部分与未覆盖需求，不把截断样本作为负例或质量扣分。

本轮不新增自动小包组合搜索。已有明确小包与单卡增减可作为编辑提案输入；比较完整包的实际支撑、净占位及原用途损失。上游portfolio生成成本另记，最终保留32项不代表其生成阶段已经受同一计算上限约束。

## 6. 分步骤执行与逐项验收

每步通过后进入下一步。下表测试类名为本实施任务新建的明确检查入口；不运行未筛选测试发现。

| 步骤 | 目标文件/符号与前置条件 | 修改动作与保持的不变量 | 验证及通过标准 | 失败处理 |
|---|---|---|---|---|
| 1. 输入与第一层 | 新增`construction_layers.py`的SkeletonSpec/LayerContext/evaluate_axis；已读两层设计 | 实现库存/模块引用、q/A、K/E、密度、U和未分配量；共享卡去重，Side不补主卡，主/额外分列 | `tests.test_construction_layers.AxisEvaluationTests`：1/1.9/2.8与1/1.8/2.6、模块共享、空分区、未知角色、错误数量全部按设计 | 只修本步契约或统计；不得用主题配额填缺口 |
| 2. 关系内核 | 新增`construction_relations.py`的UseRequirement/RelationFact/relation_index/evaluate_relations；步骤1输入稳定 | 处理区域/原因/类型、all/any、共享限次与支撑工作表；不执行动作，未知局部化 | `tests.test_construction_relations.SupportAssessmentTests`：A＋B缺B、替代供给、无源循环、同名次数、事件/状态、明确竞争与顺序未定结果正确 | 保留未识别范围；不调用引擎来补实现 |
| 3. 改动取舍 | 同文件compare_configurations及增量更新；步骤2通过 | 实现支撑差异、真实优势/取舍、小包净占位、单次组合计数；重排不改变结论 | `tests.test_construction_relations.EditComparisonTests`：同名与异名替代区别、零净位仍有损失、共享支撑不重复、局部概率、增量/全量一致 | 修差分或失效范围，不添加任意权重强排 |
| 4. 事实与候选适配 | `construction_layers.py`的evaluate_layers/evaluate_portfolio_layers；步骤1—3通过 | 接入既有effect_records、材料和功能判断；消费现有候选行；不改原模型分数、旧行顺序或旧协议 | `tests.test_construction_layers.AdapterTests`：有费用/对象的条件关系不被route_ready误删、未知事实不伪造、真实记录可导入、候选身份及卡表约束保持 | 错误输入抛ContractError；语义未知进入报告，不静默跳过候选 |
| 5. 规模与接续 | 两份新测试、CI白名单、设计与MASTER；步骤1—4通过 | 加入预算计数、无CB调用、匿名机制与模块/卡号重命名检查；记录运行耗时；只追加对应白名单 | `BudgetAndGeneralityTests`及两份模块全跑无失败/skip；选定已有回归通过；文档真实列明未接模型训练和主流程自动选择 | 区分新增回归与无关旧故障；停止受影响接线，不修订CB、权重或旧检查点来绕过 |

所有步骤都使用当前允许路径，不迁移或清理现有运行目录。若目标文件出现无法解释的同期变更，停止该文件的写入，先核实差异归属；已完成的独立模块可继续验证。

## 7. 验证命令与计算负担记录

### 2026-11-01 第一层与GPU执行补充

以下保留第一层任务当时的范围；第二层当前完成状态及验证入口见第10节。

本任务只交付第6节步骤1及该层的白名单/文档收尾；步骤2—4和第二层规模检查留给下一任务，不提前建立空关系实现。第一层使用`CardCopy(zone, card_id, copy_index)`引用实际`DeckParts`库存。每项功能按实际支持副本的并集、同分区同名身份及固定卡号/副本序号建立唯一折扣记录，所有模块及总览引用它，拆分模块不会重置首张；未分配或不支持该功能的副本不消耗该功能的首张贡献。额外U使用已分配额外并集的折扣记录。显式`same_name_groups`可供宿主传入别名等同名身份。`AxisModule`说明用途与必要分区；`FunctionRequirement`引用所选粗逻辑节点，`RoleAssessment/FunctionEvidence`携带来源和限定；`LayerContext`保留原`BuildTask/ConstructionLogic`。未表达为功能统计或给定输入的功能节点输出`logic_gaps`。详细事实与portfolio适配仍属步骤4。

GPU新增允许文件为`scripts/validate_construction_layers_gpu.py`，只作显式工程验证，不加入CPU白名单。既有`build_model.py`、`device.py`、模型特征版本及运行权重保持原样。GPU验证不是新第一层特征已经接入训练。

| 步骤 | 前置条件与动作 | 验收标准 | 失败处理 |
|---|---|---|---|
| GPU输入传递 | 第一层CPU通过；复用已有CUDA环境，建立独立匿名骨架，将已确定K/E/密度数值传入CUDA并读回 | 真实CUDA张量且精确读回；输出设备/驱动/Python/Torch/CUDA版本 | 不回退CPU冒充GPU；报告具体环境错误 |
| 既有构筑模型兼容 | 使用`BuildEncoder.batch`及两个独立随机初始化`BuildRanker`角色，不读取旧checkpoint | CPU/CUDA FP32前向误差满足rtol=1e-5、atol=1e-6；所有梯度有限并满足rtol=5e-4、atol=2e-5，梯度总量非零 | 只定位新脚本或现有相关兼容问题，不迁移旧权重、不展开训练 |
| 工程证据 | CUDA同步后记录执行时间、峰值显存、实际误差及检查范围 | 真实运行成功才记录通过，缺CUDA失败而非skip | GPU未通过时第一层CPU结果单列，不能用可用性查询代替实际执行 |

复用环境优先为`N:\YGO-Kito\_local_cpu_20261027\venv-cuda-linux-291-cu128`（WSL），源码及日志仍来自当前完整检出。TEMP/TMP/TMPDIR、CUDA缓存和输出重定向当前N盘检出的`.cache/construction-layer-validation`；不安装依赖，不运行优化器更新、不读写既有checkpoint。既有回归选择具体CPU入口，排除`AdamMigrationContinuation`、CB路线和原生执行。下方原两层命令保留供后续按步骤使用，本任务不批量执行尚未实现的模块。

从工作目录执行，复用已安装Python；不安装依赖、不启动正式课程。新模块的测试保持标准库可运行，适配回归按现有环境提供依赖。

```powershell
$env:PYTHONPATH = 'src'
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_layers.AxisEvaluationTests -v
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_relations.SupportAssessmentTests -v
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_relations.EditComparisonTests -v
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_layers.AdapterTests -v
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_relations tests.test_construction_layers -v
# 相邻回归使用第9节的16个精确入口，不运行整组迁移或CB测试。
git diff --check
```

逐步执行并检查退出码，前一步失败不连续排队启动依赖步骤。选定旧回归若需要现有环境中未安装的依赖，报告具体缺项，不将skip计为通过，也不影响已经完成的标准库内核检查结论。

规模检查放在`tests.test_construction_relations.BudgetAndGeneralityTests`：分别检查稀疏/宽条件、共享资源高关联、1与32个候选、只改张数和新增事实。固定样例报告F/A/M/L/R、受影响用途数、解析缓存命中、冷/热耗时及候选数量；纯计数上限和预算行为作为确定性通过条件，不以未经测量的毫秒门槛制造失败。样例翻倍时核对增长是否符合第8.3节，若出现供应者组合数量乘积，修正算法。

新API测试将CB/引擎执行入口设为一旦调用就失败的哨兵，检查它们从未执行；不运行原生故障注入。合并发布时再在项目指定Linux锁环境运行`scripts/check_merge_candidate.py`及CI；本地定点回归不冒称远端CI结果。

## 8. 兼容性、风险与完成边界

保留旧BuildTask/DeckParts、模型编码及候选排序。新增评价为显式调用，不把“关系有支撑”改写为旧流程的目标/CB已核验，也不改变旧checkpoint绑定。

主要工程风险是事实适配遗漏、未知与缺口混淆、跨模块重复计位、共享资源被多次兑现、增量失效遗漏和调用旧流程时意外触发CB。分别由来源字段检查、局部知识状态、统一库存、共享组、全量对照及无CB哨兵覆盖。语义覆盖仍有限，最终模型排序和完整总分尚待接入；当前不假定其已经完成。

失败回滚仅撤销本次新增模块、白名单条目或本次接口改动，保留原有未提交工作；不执行reset/clean，不改训练数据、旧评分或检查点来使检查通过。若发现必须改变原任务、引入CB搜索或重定义旧模型特征才能继续，停止相关步骤并明确具体冲突。

本轮实施完成的标志是：两层评价API可调用，既有事实和候选可以适配，局部改动能给出可复核的支撑差异与取舍，目标测试和计算预算检查通过。后续主流程采用新排序、模型特征训练、完整总分与正式训练分别推进，不把它们记作首轮已经完成。

## 9. 第一层实际验收与第二层接续摘要

本节保留第一层完成时的历史交接；第二层现已完成，当前状态以第10节为准。

原始目标：以效果积木和第一层骨架为基础，建立通用的供给—用途关系评价，支持卡片/张数/小包取舍，控制计算量，CB求解保留在后续。用户最新决定为逐层实现、每层完成先汇报再新开下一层，并要求真实GPU工程验证；正式训练暂停。第一层已完成，本节是第二层可独立承接的真实状态。

已完成：新增`construction_layers.py`的`SkeletonSpec/LayerContext/evaluate_axis`及必要的小记录类型，落实q/A、覆盖、K/E/轴内和整副密度、额外U、物理库存与未分配用途；原任务D不随骨架缩小。共享副本按同一折扣记录投影，未知保留在相关功能。新增22项标准库行为测试，包含匿名r3.1固定验收值；给CPU白名单仅追加`tests.test_construction_layers`。新增独立GPU验证脚本，未改旧模型特征。没有创建`construction_relations.py`或其测试，也没有空的第二层API。

真实文件状态：完整检出仍为`N:\YGO-Kito\_publish_20261030`，当前HEAD为`3f57198`；本批未提交。新增源模块、测试、`scripts/validate_construction_layers_gpu.py`及[GPU原始回执](../2026-11-01-construction-layer-gpu.json)；修改白名单、本书、两层设计、construction-logic和MASTER。大量原有未提交程序/测试/配置继续原样保留，不reset/clean。源码来自当前检出，`_local_cpu_20261027`只复用解释器环境，没有修改运行源码快照、旧权重或检查点。当前2210参考仍是`configs/user-deck-references/main-02-source-v2.json`（40/15/15，主卡22种、额外14种），旧v1保留。

实际验证如下；没有远端CI、真实引擎或模型能力成绩：

| 检查 | 本次实际结果 | 证据 |
|---|---|---|
| 第一层`tests.test_construction_layers` | Windows Python 3.12.1，22项通过，0失败/错误/skip，unittest计时0.331秒 | `.cache/construction-layer-validation/axis-cpu.log` |
| 限定相邻回归 | 16项通过，0失败/错误/skip，unittest计时64.434秒；包含绑定10项、语义3项、portfolio3项 | `.cache/construction-layer-validation/existing-cpu.log`及下方精确模块列表 |
| 实际CUDA | RTX 4060 Laptop，驱动617.42，WSL Python 3.12.14，Torch 2.9.1+cu128/CUDA12.8；第一层数值与编码器张量往返精确一致，两个BuildRanker角色前向/梯度一致性通过 | [GPU回执](../2026-11-01-construction-layer-gpu.json) |

GPU最大前向绝对误差1.1920928955078125e-7，最大梯度绝对误差3.5762786865234375e-7；所有梯度有限、总量非零。PyTorch峰值分配18,823,680字节（17.95 MiB）；CUDA初始化后的检查计时21.623秒，不含解释器导入和WSL启动，不作训练吞吐预测。使用两个独立新初始化模型，没有优化器步骤，参数在反传前后逐一保持相同，没有checkpoint IO。第一层新特征尚未写入模型输入，验证的是数值传输及既有构筑模型GPU兼容性。首跑遇到的新测试UTF-8读取和GPU显存统计初始化顺序问题已修正，最终结果如表。

第一层复验命令（工作目录为完整检出，`PYTHONPATH=src`、OMP/MKL各2）：

```powershell
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_layers -v
```

相邻回归在已有WSL CUDA环境以CPU执行，精确选择为：

```text
tests.test_construction_binding
tests.test_effect_semantic_review.EffectReviewRegressions.test_isolde_parenthesis_separates_cost_from_resolution
tests.test_effect_semantic_review.EffectReviewRegressions.test_unrecognized_activation_boundary_is_not_a_positive_operation
tests.test_effect_semantic_review.EffectReviewRegressions.test_fusion_summoned_protection_is_not_a_summon_instruction
tests.test_construction_portfolio.ConstructionPortfolioTests.test_atomic_axis_spans_regions_and_preserves_all_constraints
tests.test_construction_portfolio.ConstructionPortfolioTests.test_small_budget_reserves_group_and_both_regions_without_forcing_edit
tests.test_construction_portfolio.ConstructionPortfolioTests.test_sourced_mechanism_input_preserves_a_complete_package
```

这些入口刻意避开`AdamMigrationContinuation`及CB提议/执行测试；不是运行原第7节全部旧测试模块。GPU执行命令如下，目录已在本批创建；缓存及临时文件都位于当前N盘检出：

```powershell
$layerCheck = '/mnt/n/YGO-Kito/_publish_20261030/.cache/construction-layer-validation'
wsl.exe -d Chaos-Ubuntu-26.04 --cd /mnt/n/YGO-Kito/_publish_20261030 -- env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 "TEMP=$layerCheck/tmp" "TMP=$layerCheck/tmp" "TMPDIR=$layerCheck/tmp" "CUDA_CACHE_PATH=$layerCheck/cuda-cache" "TORCH_HOME=$layerCheck/torch" "XDG_CACHE_HOME=$layerCheck/cache" /mnt/n/YGO-Kito/_local_cpu_20261027/venv-cuda-linux-291-cu128/bin/python -B -u scripts/validate_construction_layers_gpu.py --output .cache/construction-layer-validation/gpu.json
```

Windows同名CUDA虚拟环境未装Torch，复用Linux环境；初始沙箱WSL查询权限不足后经正常审批成功，没有安装依赖或改系统设置。最后`git diff --check`、三个新增Python文件的AST语法检查以及白名单单次追加检查均通过。

第二层可以接收：`SkeletonSpec.inventory/modules`的实际整数库存与引用、`LayerContext.task/logic/requirements/assessments`、分区/模块/功能来源、`evaluate_axis`已知与未知分项。K与E保持不同含义，材料和支付只能读取实际库存；函数不改变输入、不运行CB、不自动排名。完整候选的合法性仍由步骤4复用`assets.validate`，不能将`inventory_complete`当作卡表合法性结论。

待完成：从第6节步骤2开始，完成`construction_relations.py`与测试、关系匹配/多输入/替代/共享次数及资源检查、差分和有限比较、增量更新与单次概率、已有事实/portfolio显式适配、预算及规模计数；随后追加第二层测试白名单并更新真实状态。GPU验证也需覆盖第二层新增边界的有意义部分，不把静态字典计算强行张量化，不重复未受影响的环境冒烟来替代新接口验证。第一层综合粗评分、完整总分、模型新特征学习及主流程自动选用另列后续。

关键约束：主进程执行，不启用子代理或新工作树；正式训练暂停，不执行CB、原生故障、未筛选discovery、权重/检查点迁移或完整参考牌表重评分。未知局部化；主/额外/Side、同名库存/次数和K/E分开；源变化不绕过旧checkpoint绑定。上游portfolio最多保留32项不代表生成前过程受限。当前无待答问题，无阻塞；若真正提出新问题，必须等待真实回答并暂停所有依赖步骤。

禁止重复：不重新设计既定折扣、不重算未变化的2207/2210例子、不恢复旧2210为当前输入、不将珠泪卡号或已知CB写成通用默认答案；不顺手重构已有未提交工作。完整实施书已交付，非UI步骤无需再增加形式审批。

接续与上下文规则：第一层完成汇报后创建下一层任务已获用户明确条件授权；超出两层设计的后续新任务仍需用户确认。长任务优先原地继续，单次压缩不自动中断；若继续压缩会损害准确性/约束/状态，或形成适合交接的安全边界，先完成非破坏性原子步骤，不启动新实施阶段，提供包含目标、完成项、真实文件、实际验证、未完项、阻塞/风险、约束、禁止重复及建议首条提示的独立摘要；获明确授权后才创建新任务。新任务首条提示重申这些规则。

建议新任务首条提示：

> 在N:\YGO-Kito\_publish_20261030承接第二层静态构筑关系评价。第一层已完成22项CPU检查、16项限定回归及实际GPU工程验证，详见本书第9节。读取AGENTS、现行两层设计、实施书和本批源代码，按第6节步骤2—5继续关系内核、配置比较及显式适配，补有意义的CPU/GPU验证。主进程实施，复用当前未提交检出，训练暂停，不展开CB，不改旧模型特征或检查点。沿用第9节完整状态、禁止重复和上下文交接规则；新的关键问题若发问，等待真实回答后恢复依赖工作。

## 10. 第二层实现与实际验收

本节替代第9节历史交接中的“第二层待完成”状态。原目标、第6节步骤2—5、第一层保持行为及第二层GPU边界均已完成。所有代码仍在`N:\YGO-Kito\_publish_20261030`，基线HEAD仍为`3f57198`，本批未提交；没有创建工作树或子代理，既有未提交修改保留。

### 10.1 当前文件及接口

新增`src/ygo_kito/construction_relations.py`及`tests/test_construction_relations.py`；扩展第一层模块、测试及原GPU验证脚本；CPU白名单在已有第一层条目之后只追加`tests.test_construction_relations`。未改原模型特征、旧候选排序、原训练/恢复/CB接口、2210参考或任何运行权重。

| 接口 | 实际行为 |
|---|---|
| `Resource / Need / InputGroup` | 资源条件匹配、整数数量、消费/存在、显式all/any；粗图合流不自动变AND |
| `RelationFact / ResourcePool / Claim` | 有来源的效果级供给、明确输入、共享次数/资源容量、实际物理库存、恢复依赖 |
| `UseRequirement / JointConstraint` | 原用途、必需标记、priority（数值大者优先）、已知不相容或顺序未定 |
| `RelationContext / RelationBudget` | 仅本次已选/已召回的事实范围、显式目录卡ID和卡片/端口/需求/匹配/更新/候选预算 |
| `relation_index(catalog, context)` | 先限读取与匹配再建索引；复用`MechanismCatalog.effect_records`，卡文或同名身份改变则拒绝旧索引 |
| `evaluate_relations / update_relations` | 返回`RelationEvaluation`，`to_dict()`给出用途、联合需求、数量缺口、条件、瓶颈、来源事实、预算与计数；增量只更新受影响支撑，汇总/概率刷新 |
| `compare_configurations` | 同原任务内比较，返回`ConfigurationComparison`及`to_dict()`；保留改卡、净占位、用途损失和具体条件/缺口差异 |
| `single_event_probabilities` | 缓存整数组合计数；单次取得与留库分列，无多阶段概率乘法 |
| `evaluate_layers` | 默认返回两层字典；`return_state=True`返回`(record, RelationEvaluation)`供后续增量；完整库存要求宿主assets并调用`validate` |
| `evaluate_portfolio_layers` | 对齐既有rows与逐候选SkeletonSpec；保留身份、顺序、旧分数。返回已评价rows和未覆盖位置，上游生成工作由`generation_work`单列 |

调用方仍提供原BuildTask/ConstructionLogic及第一层角色事实，仅增加`LayerContext(..., relations=RelationContext(...))`。关系上下文可单独传给关系内核用于局部分析；完整构筑候选经组合/portfolio入口完成原卡表校验。先用`relation_index(catalog, context)`建立本轮共享索引，再调用`evaluate_layers(spec, context, catalog, index=index, return_state=True)`；局部候选继续传同一index及上一`RelationEvaluation`作为previous。

资源池容量只接受固定整数或实际已分配主/额外库存。物理供给使用unit副本，不能把E或每次堆墓量当材料数；同一物理卡在多个模块中去重。共同处理共用效果引用和choice；不同选择保留各自choice以及共享限次Claim，新增副本不重置卡名次数。已支持的恢复仅将超量改成恢复顺序未定，不宣称可无限复用。

适配保留已识别费用、对象、触发、操作、同名次数、素材all条件及原始记录。`route_ready`不参与第二层准入。未知数量、额外条件和未识别限制局部保留；无类型可定位的未知效果标记其所影响的未满足需求。没有自动扫描全卡池、自动选择所有小包或自动把属性库存放入所需对局区域。

### 10.2 计算边界与实际检查

本层没有供应者笛卡尔积、全局材料分配或CB分支。每项单独支撑与全部必需用途的联合支撑分列。明确同池超量为缺口；重叠素材集合、需选供应者子集、恢复时序和顺序限制保留unknown。供给总量有冗余时，不能把“全部供应者并用冲突”判成所有子集不成立。组合条件说明另有128节点上限；超过时报告预算未覆盖并保留原规范化事实图，防止交替菱形依赖复制指数规模条件说明。

72项当前两层检查全部通过，0失败/错误/skip，Windows Python3.12.1，0.981秒；日志`.cache/construction-layer-validation/relations-cpu.log`。其中42项关系测试、8项显式适配、22项原第一层测试。原测试中的匿名r3.1固定统计继续通过；没有重读或重算2207/2210牌表示例。

| 实测样例 | 确定性计数与结果 | 本机观测 |
|---|---|---|
| 宽匹配20→40 | F/A各20→40，M/L为400→1600；翻倍后4倍，未展开供应者组合 | 含建索引总计约17.5→68.1毫秒 |
| 稀疏24端口 | F/A/M/L均24、R=0；改一个卡名张数只更新3个效果/用途，增量与全量相同 | 冷约29.8毫秒、热约18.6毫秒，tracemalloc峰值399,722字节 |
| 共享资源24端口 | F/A/M/L/R均24；共同容量冲突可见，热更新3个效果/用途 | 冷约29.3毫秒、热约17.8毫秒，tracemalloc峰值464,738字节 |
| 1/32候选 | 最多`min(32, task.candidate_budget, budget.candidates)`；每批目录只读一次，0候选预算不读目录 | 不把上游40项输入或其生成成本记成已受32项预算限制 |
| 29端口交替菱形 | 更新次数小于200；条件预算截断定位最终用途，原29条事实保留 | 返回unknown，不把截断当负例 |

稀疏/共享样例启用了tracemalloc，耗时只作这台机器的工程观测。计数约束及增量语义相等是通过标准，未建立训练吞吐结论。

限定旧回归使用第9节原来的16个精确入口，全部通过、0skip、51.998秒，日志`.cache/construction-layer-validation/relations-existing-cpu.log`。没有运行整组效果语义迁移测试、未筛选discovery、CB或原生故障测试。新增五个相关Python文件AST语法与`git diff --check`通过；白名单仅累积保留此前5项、第一层1项、本层1项新增。没有本提交的远端CI结果。

### 10.3 真实GPU边界

第二层GPU在原RTX 4060 Laptop、驱动617.42、WSL Python3.12.14/Torch2.9.1+cu128/CUDA12.8环境执行。四个匿名合法40/1/0候选只有材料实张数0/1/2/3及相应替换变化；每个候选完成组合评价、完整卡表校验及增量/全量对照。

实际传输int64库存、int8支撑状态（unknown=-1）、独立bool已知掩码及FP64取得/留库概率。双素材需求得到false/false/true/true，未把第一层1.9代入。未知用途在四个候选中仍是unknown；零净位替换仍列出被换出的卡。数值往返及概率差分误差为0。相同四个候选经过原BuildEncoder的五个张量和新初始化BuildRanker，CPU/GPU前向满足rtol1e-5/atol1e-6。实际误差、显存和时间以[第二层GPU原始回执](../2026-11-01-construction-relations-gpu.json)为准。

静态字典、集合、关系闭包和组合计数留在CPU。新关系数值没有接入旧模型特征，没有优化器步骤、反传或checkpoint IO；第一层已有前向/梯度兼容证据保留，不重复进行旧权重或训练迁移。GPU命令沿第9节环境变量和解释器，脚本参数改为：

```text
scripts/validate_construction_layers_gpu.py --layer relations --output .cache/construction-layer-validation/relations-gpu.json
```

TEMP/TMP/TMPDIR、CUDA_CACHE_PATH、TORCH_HOME、XDG_CACHE_HOME均指向当前N盘检出的验证目录。没有安装依赖；WSL启动输出既有代理配置提示，脚本正常完成，未修改代理或WSL配置。

### 10.4 完成边界和接续约束

两层本轮范围无未完成步骤或待答问题。综合粗评/完整总分、旧主流程自动采用新比较、模型新特征学习、泛用及Side优化仍是后续独立范围；正式训练暂停。新代码与模型权重的旧绑定不能绕过，`_local_cpu_20261027`只借用解释器，未改其源码快照、权重或检查点。

当前无须创建下一任务：逐层授权覆盖的两层已完成，不扩张成第三层授权。若用户继续指定后续目标，先承接本节的真实文件及[验证回执](../2026-11-01-construction-relations-validation.json)，不重做已经有效的环境整理、旧概率算例或未变接口检查。第9节上下文规则继续适用：长任务优先原地继续，单次压缩不自动中断；遇确需交接的安全边界先完成原子步骤，给出完整独立摘要，获得明确授权后才新建任务。发问后等待真实回答，暂停所有依赖答案的工作。

## 11. 主流程接线机械执行补充

用户已明确授权“确认新开任务并继续，把两层评价接入现有构筑主流程”。本节将第10节中的主流程采用新评价从后续范围移入本次实施；由主进程执行，不启用子代理，不新增工作树。复用当前检出及既有未提交改动。

### 11.1 目标、证据与验收

真实调用链为`HostConstructionBackend/CLI/AutonomousConstruction → ConstructionController.run → construction_cycle → fill_with_existing → goal_candidates/edit_candidates → portfolio → retained_order → binding_provider → evaluate_fill`。当前`fill_with_existing`按旧证据、模型分数和策略多样性排序，至多保留3份工作候选；四次交接传递所选完整牌表。两层接口尚未在这条链上调用。

本次要求每次填卡在选择前评价实际候选，固定本轮原任务/图/用途，按候选自己的实际库存重建模块引用，保留旧分数与生成工作。明确必需缺口优先于可选收益；相同范围的明确优势形成优先关系；真实取舍、等价及不能判定沿原排序决策，保留具体双方优势与未知。不得生成固定权重总分。完整牌表始终经过原`assets.validate`。结果须沿尝试、候选记录及四阶段最终输出携带评价来源和选择理由。

逐项验收：正常目录控制器自动触发两层；有明确关系时能改变实际选择；新张数/换卡同步骨架与库存；静态字段不能变为q=1功能；缺关系条件保留unknown；硬约束、Side后置、旧分数及候选身份不变；预算在新目录读取和评价前生效且上游生成成本另列；旧普通调用仍可用；四阶段及实际GPU候选传递一致；不启动训练、CB或checkpoint读写。

### 11.2 技术路线与接口

新增`construction_layer_flow.py`作为现有填卡环节的适配器，不新增构筑生成器。`ConstructionLayerAdapter`持有原目录绑定器及可选宿主`context_provider(task, logic) → LayerContext`。正常控制器默认装配；直接使用目录绑定器的旧fill调用也自动装配。自定义旧binding callable没有足够的来源信息时保留旧流程，并明确`source_context_unavailable`，不编造全覆盖或全缺件。宿主显式上下文必须保持原task/logic；其中角色事实按当前候选过滤并重建实张模块，关系用途在整批候选间固定，静态索引在批内共享。

自动上下文只读取预算内候选涉及的主/额外卡。功能判断复用目录绑定器的当前来源判断；字段/种族仅作q=0.5，未知保留。原图中的功能节点形成要求，替代节点不因合流自动变AND，只有明确目标节点作为必需用途。来源覆盖跨分区时分列统计，不强制每个分区各有一份。具体效果沿`effect_records`保留触发、费用、对象、限制；缺宿主取得/发动条件使用显式unknown输入。指定额外目标的素材要求沿原目录，物理库存上界与进入可用区域的未知分列。没有来源的功能—效果关联仍是unknown，不把粗标签当发动证明。

排序采用有限两两比较与稳定拓扑排序（最多32候选、496对），只为明确优先建立边。第一层比较覆盖、K/E、A/U和物理占位；第二层使用原`compare_configurations`的用途、条件、资源及数量差分。必需用途按原priority（轴功能默认为0）比较，不按缺口个数抵消；其他分项互有损益则保留取舍。未知变化不被当作收益。若出现优先环，环内保持原序并记录，不能任意消除矛盾。详细比较绑定原候选与被选候选；摘要保留排序依据。旧模型只做原五张量前向，不修改特征版本或参数。

### 11.3 分步骤实施

| 步骤 | 文件/符号、前置条件与动作 | 预期结果及保持项 | 检查/通过标准 | 失败处理 |
|---|---|---|---|---|
| 1 | 新增`construction_layer_flow.py`的适配器、逐候选投影和分项比较；前置为本节已交付、两层既有接口有效 | 原task/logic绑定；索引批内复用；未知条件与物理库存分开；没有主题配方 | 新`tests.test_construction_layer_flow`验证来源、张数、缺口、取舍、未知和预算；0失败/skip | 修复本模块；不放宽旧契约，不继续错误排序接线 |
| 2 | 修改`construction_fill.fill_with_existing/construction_cycle`及`construction_controller`；在旧排序之后、最终选择之前为预算内候选绑定、投影、评价和稳定重排；复用绑定结果 | 保留旧模型分数、候选身份、生成trace；原合法性和文字核验继续；最终所选牌表来自新顺序 | 实际fill选择与四次交接测试；对照旧无来源callable和不支持信息回退；检查最终输出与被选索引一致 | 保留未通过结果为未完成，局部撤回本次接线，不覆盖其他任务改动 |
| 3 | 新增端到端测试；扩展`validate_construction_layers_gpu.py --layer flow`；CPU白名单仅追加新测试模块 | 明确关系改变选择，未知/取舍沿旧顺序；实际CPU/GPU候选一致，参数不变 | 选定新/旧CPU入口0失败/错误/skip；CUDA原五张量和实际fill输出、库存/状态/概率比较符合前向rtol1e-5/atol1e-6及精确整数/状态要求 | 缺CUDA或数值不符视失败；不安装依赖、不自动CPU降级、不调用训练 |
| 4 | 更新本书、两层设计当前入口、construction-logic、MASTER及JSON验证回执 | 真实完成状态与局限、可重复命令和证据对应 | AST语法、`git diff --check`、JSON回读、相关链接、白名单只增一项 | 仅修正文档/本批文件；无依据不得标CI或能力通过 |

### 11.4 验证、错误和范围

CPU优先Windows Python3.12（`-B`、`PYTHONPATH=src`、OMP/MKL各2），需要Torch的实际fill/controller/GPU沿用WSL现有解释器。运行显式新测试模块、原两层72项、绑定10项、编辑trace及选定四阶段/服务回归；不运行全量discovery或训练迁移测试。GPU新增模式实际调用`fill_with_existing`，使用新初始化旧架构模型，比较CPU/GPU候选分数与所选结果，检查参数/梯度未改、无优化器步骤。缓存、临时文件和日志沿用N盘本检出`.cache/construction-layer-validation`，不安装依赖、不改WSL/代理。

允许修改仅以上源文件/测试/验证脚本/白名单与相关文档。`build_pipeline`和`construction_candidates`的生成与旧排序保持原接口；不改旧模型特征、原训练、恢复、checkpoint绑定、native、CB、用户参考及其他任务改动。若实际接点需要扩大范围，先记录具体原因和机械步骤。非法或过期宿主上下文抛`ContractError`，不得悄悄用默认上下文掩盖。预算未覆盖候选保持旧候选身份和原次序依据，单列未覆盖；未知不是硬拒绝。完整参考重评分、总分标定、泛用/Side策略及正式训练不在本次范围。

接线后源码核对补充：`construction_candidates.select_retained`会在已有公平比较后更换第四阶段候选。将其评价记录同步纳入步骤2：前置为候选已在原保留集中通过原任务校验；改选时同步stage_3、最终候选及trace的layer_evaluation、所选索引与理由，原比较引用另存为初选记录；用已有两两摘要对齐改选后的比较。生成器、模型分数和公平比较结论不变。新增真实四阶段后改选测试，要求三个位置的inventory等于新牌表；失败时只修复本次元数据接线，不能放宽task_checked条件。

## 12. 主流程接线结果与验证

本节替代第10节中“旧主流程自动采用仍为后续”的状态；本次授权范围已完成。新增`construction_layer_flow.py`和20项`test_construction_layer_flow`测试，修改`construction_fill`、`construction_controller`、`construction_candidates.select_retained`、原GPU验证脚本及CPU白名单。原`build_pipeline`、候选生成器、旧`retained_order`和模型特征未改。源码继续位于当前完整检出，HEAD仍为`3f57198`，全部本批修改未提交，其他任务未提交改动和2210 v2参考保留。

### 12.1 实际调用与选择行为

`ConstructionController`默认装配两层适配器，CLI、本地HostConstructionBackend及已有自主构筑调用均沿这条现有链进入。`fill_with_existing`在原生成和旧模型前向后，为预算内候选绑定、校验并投影自己的物理骨架；按同一用途索引评价，最多32候选、496对分项比较。明确必需缺口按原priority优先，明确分项优势建立优先边；稳定拓扑排序在等价、取舍和未定之间使用原证据/模型/策略顺序。优先关系成环时保留剩余原序并说明。模型分数、候选身份、改卡内容和上游生成工作不被改写。

逐候选评价在`candidate_trace.candidates[*].layer_evaluation`，比较摘要在`candidate_trace.layers.pairs`，详细差分在`comparison_with_selected`，真实选择理由在`layer_selection`。每次四阶段交接重建本轮图和候选的上下文，最终`construction_candidate`携带其评价。后续`select_retained`改选时同步最终候选、第四阶段fill与trace，并保留初选依据，避免牌表已变而评价仍指向旧候选。

默认适配复用目录绑定器的源判断和EffectSemantics。基础字段只给q=0.5；可明确定位的既有`卡组送墓/墓地融合`标签与对应效果记录关联，保留费用、对象、触发和限制。其他有来源卡片判断可供第一层使用，其未定位的关系/发动前提保留unknown。图的目标节点成为必需用途，其他节点不因合流自动变成必需AND。原任务明确指定额外目标时读取其素材规则和候选物理库存，进入可用区域的条件仍单列未知。显式用途递归引用到的资源组件纳入候选骨架，不把所有目录观察卡自动当轴组件。

宿主已有精确用途、数量或共同使用条件时，使用`ConstructionController(..., layer_context_provider=provider)`；provider接收原task和本轮logic，返回含relations的LayerContext。直接调用fill也可以传`ConstructionLayerAdapter(binder, context_provider=provider)`。骨架从当前实际库存及固定角色/关系组件重建，换卡后不复用过期副本引用。上下文改变任务/图或回调篡改任务立即拒绝。无来源契约的旧callable保留原流程并标`source_context_unavailable`；预算外候选标未覆盖。两者均不伪造支持或缺件。

### 12.2 CPU、GPU与静态证据

20项新接线测试在Windows Python3.12.1通过，0失败/错误/skip，0.905秒，见`.cache/construction-layer-validation/flow-cpu-final.log`。用`PYTHONUTF8=1`解决旧测试夹具默认编码读取中文的问题，未改旧夹具。包含实际fill换选、0/1/2/3物理张数、同优先级必需用途的取舍、原priority、未知回退、字段q=0.5、卡文费用/对象、Side、非法牌表、0/1/32预算、任务篡改拒绝、四阶段以及后续保留候选改选。原72项两层测试在本批首次接线后的84项组合检查中再次通过（1.342秒）；内核此后未修改。

限定旧回归是目录绑定10项、编辑记录4项、实际控制器1项和实际服务2项，精确入口与最终日志记录在[CPU验证回执](../2026-11-01-construction-flow-validation.json)。没有运行未筛选discovery、Adam迁移组、CB推理或原生引擎。

新增GPU模式`--layer flow`在RTX4060 Laptop、驱动617.42、WSL Python3.12.14、Torch2.9.1+cu128/CUDA12.8通过。实际目标/优化模型原分数都将0份材料候选排第一，两层将实际顺序改为`[2,3,1,0]`并选中2份材料候选；CPU/GPU选择相同。两个角色前向最大误差分别4.47e-8、8.94e-8，满足rtol1e-5/atol1e-6。整数库存、支撑状态、独立未知掩码与FP64概率精确往返；原BuildEncoder五张量一致。

同一GPU检查另以原候选生成器运行真实控制器，四阶段各4份候选，均自动调用目录来源的两层评价，最终评价库存与牌表一致。检查阶段41.962秒（不含解释器导入/WSL启动），Torch峰值分配35,690,496字节。没有反传、优化器步骤、checkpoint IO或新特征接入；原始机器回执见[GPU JSON](../2026-11-01-construction-flow-gpu.json)。首次运行在控制器启用确定性计算后遇CuBLAS配置要求，重跑时仅为该进程设置`CUBLAS_WORKSPACE_CONFIG=:4096:8`，没有改模型或系统配置。

复现沿第9节WSL命令，仅额外加入上述CuBLAS环境变量，脚本参数为`--layer flow --output .cache/construction-layer-validation/flow-gpu.json`。Windows新测试命令为：

```powershell
$env:PYTHONPATH='src'; $env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'
$env:OMP_NUM_THREADS='2'; $env:MKL_NUM_THREADS='2'
& 'C:\Users\27499\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest tests.test_construction_layer_flow -v
```

七个本批Python文件AST检查与`git diff --check`通过；CPU白名单只新增`tests.test_construction_layer_flow`，相对HEAD累计8个新增测试入口（保留此前5个及两层2个），没有删旧项。无本批远端CI记录。

### 12.3 完成边界与接续

主流程已经实际评价、比较并选择候选；具体效果关系未被现有来源识别时仍是局部unknown，需要后续来源补充。旧模型分数继续只表示原模型输出，当前没有训练它学习新关系字段。综合总分、完整参考重评分、泛用/Side策略、CB推理和正式课程未启动；没有修改旧权重、运行快照或checkpoint绑定，也没有安装依赖。

本次无待答问题或阻塞。后续接续以第11—12节和两份flow JSON为准，不把第9—10节历史待办重新执行。长任务/等待规则仍按用户约束：优先当前任务继续；只有实际上下文连续性风险或适合交接的阶段边界才提请新任务，附完整摘要并等用户明确授权。已发问事项必须等真实回答，不能用超时、工具accepted或沉默代替。

## 13. 2207 真实课程权重的一次全流程运行

随后用户要求尝试一次实际构筑全流程。当前环境核定为2207／截止2022-09-30／暂停的`2207-course-006`。已用生产checkpoint的只读模型副本，从空牌组完成四阶段、两层比较和真实原生基础CB；详细执行与产物见[单次运行报告](../2026-11-01-2207-construction-flow.md)。60份阶段候选、426对比较，第2和第4阶段实际首选被两层改变，最终40／15／15牌表合法。3份候选共9次CB路线搜索均为预算内未找到，成功CB为0；本次流程执行完成，构筑质量未过关。

本轮遇到真实灵摆卡两段均编号①，导致关系ID碰撞。修复仅对重复编号附加文本片段序号，区分端口、效果及单效果次数池，保持未明作用范围unknown；普通编号和原冲突保护不变。`construction_layer_flow`新增对应回归，连同原关系和第一层共93项通过。生产权重、checkpoint指针、训练计数和暂停文件不变；没有正式训练。第12节的“未展开CB”是接线任务当时的边界，本节更新了真实CB已运行但未找到路线的状态。

## 14. 配套缺口漏检修复与当前禁止CB约束

用户随后要求先诊断两层漏检、修复后重跑2207，明确禁止开始CB，训练继续暂停。此约束优先于第13节历史运行授权。实际根因是自动素材接线局限于任务固定目标、费用／对象未匹配库存、功能投入只看标签，以及全局unknown拦住局部已知比较；原候选生成也未接收这些缺口。

本轮新增有来源的必要库存投影，Main／Extra与Side分开，已选额外素材按独立实体检查；缺件功能不计K/E，已知缺口向量参与比较。候选生成增加有界依赖修复家族，并与本轮图采用同一作用范围，先提交严格改进链末端；旧模型特征、权重、任务、预算和checkpoint绑定不变。详细执行书与范围见[配套漏检修复记录](2026-11-01-inventory-dependency-fix.md)。

修复后以原课程006权重从空牌组完成四阶段，63份已绑定候选、465对比较，原红玉之宝札、弹匣及卡雷多哈特指名素材缺口由程序处理。最终40／15／15牌表仍有三类已识别缺口，涉及五张实卡，未达到无已知缺口；这些缺口均已进入评价并扣除相应功能投入。105项两层相关回归加15项针对性CPU回归全部通过，CB提案／CB推理／原生引擎均0次，训练暂停及参数不变。完整证据见[禁用CB重跑报告](../2026-11-01-2207-inventory-fixed.md)。不得把本节完成状态理解为允许恢复CB或正式训练。

