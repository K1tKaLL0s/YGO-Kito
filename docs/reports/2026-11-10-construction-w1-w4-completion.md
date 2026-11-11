# W1／W4通用卡文、限制和内部续算补齐

2026-11-10，Asia/Hong_Kong。实际源码为`N:\YGO-Kito\_publish_20261030`，沿用现有检出并保留全部既有修改、删除和未跟踪文件。按用户授权由主进程实施，无子代理、训练或CB。执行依据为[本轮执行书](execution/2026-11-10-construction-w1-w4-completion-execution.md)及已回读的本聊天原文；压缩后先回读实际对话，再恢复实施。

## 已实施及静态证据

公共卡文记录按发动前分句分开代价与取对象；已补省略“自己”的手卡除外代价、后文指代的数量／所属方／区域／选择条件、明确发动条件、组合次数及不进入连锁的特殊召唤手续。印刷属性、种族、等级和攻击力／守备力条件复用现有库存选择；超量怪兽的阶级与连接值不当作等级。未理解的后缀、歧义的多个对象不会静默丢弃。

两条完整特召限制使用公共允许条件表达等级／阶级或种族，再按实际被召唤对象及玩家判断；全部允许、全部禁止及混合候选分开。整回合和发动后沿用既有顺序检查。没有卡名、系列号或具体卡号特例。

完整有限候选的读取、主题配合连接、资源匹配和关系更新接入现有待评队列，分别保留读取位置、已查连接、匹配游标及状态／待更新队列；JSON恢复与足额计算一致。匹配分片不再误缩小资源分配的状态预算。未完成计算不缓存为完成unknown。参考分片保留已评价候选及原优化阶段，恢复不重建目标骨架、逻辑或候选，也不提前累计正常不足。

规范化v16，公共积木修订`public-text-completion-20261110`；旧评价重评。质量公式v4、准入v3、网络、词表和权重不变。

最终35个不同定向静态方法整组通过，0失败、0error、0跳过，未加载Torch。新增12项卡文／限制及5项预算／参考续算，另18项直接受影响回归。13个源码／测试文件语法及行尾检查通过。[最终逐方法JSON](../../.cache/construction-w1-w4-20261110/static-targeted-final.json)、[文本日志](../../.cache/construction-w1-w4-20261110/static-targeted-final.txt)。

真实失败保留：首次卡文8项中2项失败，修正除外对象区域及歧义指代后通过；首次低层续算方法误读不存在的计数字段；集成3项报临时卡片属性进入评分契约，已在完成限制判断后移除内部字段；主题极小预算检出匹配和分配预算混用，已分开；两次调用含错误测试方法名，未计作业务通过。以上日志均保留于同一缓存目录，最终计数只统计不同方法一次。

## 实际2207构筑

第一次运行`run-001`使用v16、原course-006权重、2022.7禁表／2022-09-30发行截止、珠泪宿主目标，完整环境12237个卡号；初始时间片600秒、一轮优化。实际走完S0—S5，13份候选各有完整保存的Evaluation，无内部待评；输出40／15／15。总用时742.404秒，其中进入构筑前288.364秒。Gate为pending，原因是候选／参考静态不完整及80%区间无法判定；更新次数前后5／0，无训练、CB或人工事实／选牌／阈值干预。

所选候选1616项unknown，参考3991项unknown，双方deferred为空；原读取／匹配／主题预算标志不再出现在事实原因中。未知总量不是缺资料数，也不是工作量完成比例：完整计算纳入了旧版本未覆盖的配合。进一步追溯还发现条件解释的重复展开会触发128节点上限，落为笼统`effect_support_and_access`，这一层也属于程序问题，不能据显式预算标志为零便宣布所有内部限制消失。

运行后的通用修正：次数只按本效果及未识别条款判断，不让①的已知次数使②变成次数未知；非取对象的“那张卡”不再误报多对象歧义；明确准备／主要／结束阶段和通常魔法直接处理可识别；表侧／里侧表示保留到既有位置条件。条件表达提取全体或部分分支共用的条件，保持真假值与资源分支，避免重复展开。对应匿名反例及原14层交汇条件检查通过；未扩大原解释上限或新造求解器。

后续规范化升为v17，积木修订`public-text-completion-20261110-b2`。最终43个不同必要静态方法整组通过，0失败、0error、0跳过、未加载Torch；15个源码／测试文件语法及行尾通过。[v17逐方法JSON及源码摘要](../../.cache/construction-w1-w4-20261110/static-targeted-v17.json)、[v17文本](../../.cache/construction-w1-w4-20261110/static-targeted-v17.txt)。此前35项及各次失败记录保留，数字不累加。

第二次运行`run-002`在272.567秒报`KeyError: owner`，尚未完成候选生成：新解析保留的旧取对象记录没有owner，指代细化直接读字段。已对旧记录重新使用完整取对象解析，仍不完整时保留unknown，不凭默认值认定自己的对象；对应匿名择一效果回归通过，积木修订升为`public-text-completion-20261110-b3`，规范化仍v17，旧修订由资产绑定失效重评。

修正后44个不同必要静态方法整组通过，0失败、0error、0跳过、未加载Torch；15个源码／测试文件检查通过。[b3逐方法JSON和源码SHA256](../../.cache/construction-w1-w4-20261110/static-targeted-b3.json)、[文本](../../.cache/construction-w1-w4-20261110/static-targeted-b3.txt)。因真实故障发生在全池查询，又对本次12237个卡号的18631条效果记录做了生成、对象必需字段及JSON序列化检查，30.531秒、0异常，未运行模型／训练／CB。此项仅验证公共记录接口，不代表全卡文语义已验收。[全任务池接口检查](../../.cache/construction-w1-w4-20261110/static-task-pool-records.json)。

第三次运行`run-003`正常完成S0—S5，737.734秒，加载及准备282.962秒；13份候选全部保存Evaluation、0内部待评，40／15／15。候选1598项unknown，参考3954项unknown，deferred均为空；双方规范化、政策、资产及逻辑相同，更新次数前后5／0。Gate仍pending，未算作正常不足，无训练或CB。

所选候选的解释截断已清除；参考还有27处`effect_support_and_access`。逐条追溯确认：27处资源检查均保留完整分支，49或52个分支，各分支解释最多12个节点、深度2，没有截断；只是在合并的短摘要触发128节点上限。已让规范化直接复用完整分支条件，保留每个分支的资源及未知关联，不放大摘要上限、不再另做资源搜索。未完成分支仍不能据此宣布完整，剩余解释预算会明确给`relation_expression_budget`，不冒充缺输入。

当前规范化v18、积木b3。45个必要静态方法整组通过，0失败、0error、0跳过、未加载Torch；15个源码／测试文件检查通过；原27条真实参考记录全部成功转换成合法条件表达，不再生成笼统fallback。[v18逐方法及源码摘要](../../.cache/construction-w1-w4-20261110/static-targeted-v18.json)、[文本](../../.cache/construction-w1-w4-20261110/static-targeted-v18.txt)、[27条真实参考检查](../../.cache/construction-w1-w4-20261110/static-real-reference-support.json)。顺便恢复了无合法候选时清除旧待评阶段的原控制流程，避免下一片错误重放失效的待评批次。

第四次`run-004`以相同原资源及预算从S0走完v18流程，总用时735.282秒；保存摘要在最终写盘前记735.184秒。进入构筑前260.435秒，构筑及保存约474.847秒。12237卡号、13份候选均返回Evaluation，内部待评0；其中9份状态deferred、4份unknown，没有完整静态候选。保存40／15／15牌表，所选候选1598项unknown、参考3966项unknown，所选候选与参考deferred均为空。其他候选的deferred来自语义覆盖，不能混称预算没算完。

所选候选与参考的预算／未覆盖计算原因及笼统`effect_support_and_access`均为0。参考使用的原始短摘要仍可保留截断诊断，但实际计分条件已经消费完整分支，不再把该摘要当缺输入。未知数随具体条件展开变化，不能视为缺失文件数或工作量完成比例。

候选／参考政策、资产、逻辑和规范化均一致，45项静态绑定的15个源码／测试SHA256在实际运行后全部一致；更新次数前后目标模型5、优化模型0，未训练、未运行CB。Gate仍pending，原因保持`quality_evaluation_incomplete`、`reference_evaluation_incomplete`及`quality_pass_line:reference_ratio:unknown`，没有正常不足计数或强行放行。[最终核对及原因统计](../../.cache/construction-w1-w4-20261110/run-004/inspection.json)、[程序牌表](../../.cache/construction-w1-w4-20261110/run-004/deck.ydk)、[候选完整Evaluation](../../.cache/construction-w1-w4-20261110/run-004/candidate.json)。

## 尚须继续的真实程序问题

[原始11月3日方案P0031—P0032](../current/construction-scoring.md)明确：静态构筑评价配置功能、投入和配套；具体起手及操作验证属于基础CB。当前`_functional_relations`仍在没有host关系事实时，为未被效果直接提供的activation／payment／target前提统一补`functional:unresolved`。明确的发动时点、通常召唤等规则入口与固定用途情境并未完整自动接入。[正式方案第6.1节](../current/construction-scoring.md)也要求保留正常召唤等真实入口，不能把未找到入口当作没有入口。这部分需要继续按原始配置用途补齐，不能要求用户给当前起手或盘面，也不能把所有条件置真。

完整来源原文仍须继续细化：复杂触发条件、融合素材及多区域选择、择一效果内部条件／指代／代价的作用范围。当前已支持简单完整句、实际对象和完整数量，并不等于这些组合都已支持。后续必须继续使用既有积木、InventoryDependencies及关系层，不新建通用决斗求解器；默认规则与候选／参考需同口径。

## 独立续接摘要

原始目标仍未全部达成：修复W1-1、W1-2、W4-1的通用卡文、限制及内部预算续接，不把程序缺口当用户缺输入；必要静态验证后用原2207环境、珠泪目标完整运行S0—S5，不含CB。不得将本轮局部修复、接口可用或实际流程返回写成整体完成。后续还要补本报告上节列出的默认静态用途／规则入口和复杂卡文消费。

当前源目录`N:\YGO-Kito\_publish_20261030`，分支`codex/optimization-20261031`、核对HEAD`3f57198`。继续使用现有检出。Git状态：`construction_fill.py`、`effect_records.py`、`effect_count_limits.py`为已有跟踪文件的修改；另外7个生产文件`construction_inventory.py`、`construction_layer_flow.py`、`construction_progress.py`、`construction_recognition.py`、`construction_relations.py`、`construction_theme.py`、`effect_blocks.py`仍为此前已有的未跟踪文件，本轮是在其上修改。5个测试文件均未跟踪；本轮新增`test_construction_text_completion.py`和`test_construction_calculation_resume.py`，其余`test_construction_layer_flow.py`、`test_construction_functional_flow.py`、`test_construction_relations.py`为已有文件修改。不要仅从HEAD重建，不reset／clean，不恢复原有删除，不覆盖并行M4／M5文件，不提交推送。其他既有修改、删除、未跟踪成果全部保留。

已完成：公共代价／取对象／指代／次数／手续／印刷条件提取；两条明示召唤限制按对象、玩家及期限判断；读取／主题连接／匹配游标／关系状态队列及参考进度接入既有待评批次；短摘要截断时复用完整资源分支；旧目标缺owner的兼容错误已修。版本为规范化v18、公共积木b3，质量v4、准入v3不变。固定主次加权额外100%／50%、80%参考门槛、公式、网络及词表不变，没有珠泪专用解析或评分分支。

验证：45个不同定向静态方法最后同组通过，15个源码／测试文件语法及行尾通过；记录绑定在`static-targeted-v18.json`。全任务池12237卡号／18631效果的接口检查0异常；27条原参考条件直接转换成功。真实4次尝试与失败全部保留；最后v18实际13份候选、0内部待评、40／15／15到S5，Gate未通过。最终核对为`run-004/inspection.json`，实际代码与静态源码摘要相同。所有构筑进程已经结束，没有后台训练／CB或等待的内部续算。`run-004`虽有kernel存档，但没有待评队列，直接resume会进入下一轮S2，不能声称是在接续尚未算完的13份候选。

下一阶段先读本报告、[资料总入口](../current/README.md)、[原始11月3日正文](../current/construction-scoring.md)P0031—P0032和[正式方案](../current/construction-scoring.md)第6—8节。不要只承接旧阶段摘要中“缺盘面”的错误归因。定点检查`construction_layer_flow._functional_relations`的`seeds`、`_record_facts/_record_applicability`、`InventoryDependencies`的完整选择和召唤检查、`effect_records._refine_record`、`effect_blocks.record_operations`及静态默认入口。已识别的召唤手续还需作为配置用途入口供后续功能使用，不能只以记录里有字段作为落地。

剩余实施与完成标准：

1. 按原稿的可择一配置用途接上默认发动时点、通常召唤／卡的发动及其他已有规则入口；外部对象按固定用途情境解释。保留完整资源、次数和自肃检查，不要求用户手填当前起手／盘面，不用把所有条件置真来制造通过。
2. 补实际候选／参考暴露的复杂触发、融合素材、多区域和择一效果的条件／代价／对象作用范围；保留原文和精确未覆盖原因。采用公共语法及既有选择／关系机制，匿名迁移到其他主题，禁止卡ID／系列专用分支。
3. 默认入口的验收不能使用`quality_evidence=reviewed`给全部unknown置真。必要定点静态验证通过后，再从原环境／原权重实际构筑；候选／参考用同一Evaluation口径。真实游戏结果不确定与程序缺口分开，未过Gate如实保存，不用训练解决确定性的程序问题。

资源：Windows Python为`C:\Users\27499\AppData\Local\Python\pythoncore-3.12-64\python.exe`，用`-X utf8 -B`、`PYTHONPATH=src;.`。真实模型使用已安装WSL `Chaos-Ubuntu-26.04`的`/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python`，`PYTHONDONTWRITEBYTECODE=1`、OMP／MKL线程2，PYTHONPATH指当前`_publish_20261030/src`与scripts。入口`scripts/run_construction.py`；checkpoint为`_local_cpu_20261027/reports/optimization-20261031/2207-course-006/course/checkpoint-1.weights`，绑定为同课程根`model-binding.json`，环境为`source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json`，native-root为`assets/native`。时期2022-07、截止2022-09-30、主题setcode-181，初始预算600秒／一轮。实际可读卡库在`assets/native/engine-src/database/locales/zh-CN/cards.cdb`；不要把Windows不能解析旧WSL source链接误报资源缺失。2207／2210指定参考在configs/user-deck-references，不能作种子或删除以绕过门槛。

关键约束：主进程执行，沿用用户指定GPT-6.1-sol／MAX，不启动子代理；只做必要静态测试，不discovery、不训练、不运行CB或原生对局、不安装依赖，不改权重、课程指针、暂停文件、网络或词表。用游戏王官方／常用术语，不引入新评分器、资源求解器或泛化到无具体需求的额外工程。Pro辅助代码一律不读取、不追索、不运行。任务固定完整环境池，S1先无卡ID逻辑，明确必需系列／种族的狭义主题才筛轴；不能恢复48种封池或手动调整牌表。已有正确成果与45项通过记录继续复用，只在新变化／反例影响时重验。

连续性：本聊天发生压缩后已先实际回读聊天原文再继续实施。今后每次压缩也必须先回读实际对话，不只读本摘要。原聊天ID`01a1bc6f-1bc7-7952-8f03-3ac9d27ce0b6`，host为local；`read_thread`每页最多10轮，按游标回读，只输出必要的用户消息及结论，避免把巨大工具正文直接打印。下一聊天首条提示必须重申：优先在当前聊天继续，若进一步压缩可能损害准确性／连续性，或形成适合交接的安全边界，先完成当前非破坏性原子步骤，不启动新实施阶段，交付完整摘要并主动建议新开；未经用户真实确认不得创建，不声称精确上下文占用百分比。已发问题必须等待真实回答，暂停所有依赖答案的工作，不把accepted、预选、超时或沉默当答案。

本轮代码／验证／实际运行及核对已形成安全交接边界。下一阶段的新规则入口与复杂卡文实施暂停，等待用户选择新开续接，或明确要求继续当前聊天；并未把原目标标成完成，也未创建新聊天。

建议新任务首条提示：继续完成YGO-Kito现有W1／W4修复，先完整读取`N:\YGO-Kito\_publish_20261030\docs\reports\2026-11-10-construction-w1-w4-completion.md`的独立续接摘要及其原始设计引用；按原配置用途补齐默认规则入口和复杂卡文消费，不能要求用户补起手／盘面，不把接口或静态样例当功能落地。沿用主进程GPT-6.1-sol／MAX，无子代理、训练或CB，完成必要静态后用原2207权重重新跑S0—S5。保留全部未提交成果与失败记录，不重做已闭合修复。每次压缩先回读实际对话；形成安全边界或进一步压缩有准确性风险时按上述规则提出完整交接，未经真实确认不新建下一聊天。若出现真正需要设计选择的问题，提出最小问题并等待真实回答，暂停依赖工作。
