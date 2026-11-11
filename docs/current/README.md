# 项目资料与运行位置

2026-11-11 GPU 快速试运行：真实 CUDA 推理完成 24 次前向并生成两份 40/15/15 候选；9 分 43 秒试运行中第一份静态评价仍未返回，候选最终分、指定参考分、S4/S5 与 CB 均未完成。已安全保存结束，旧 run-007 未恢复。补齐 CLI 显式 GPU、CuBLAS 确定性配置、宿主小批候选预算和暂停候选导出；本次 7 个不同定点测试通过。当前不能宣布构筑全流程通过，下一运行问题是 CPU 静态组合评价与状态膨胀。[试运行结果及两份牌表](../reports/2026-11-11-construction-gpu-trial.md)

2026-11-11 卡库专项完成本轮修复：项目 15,071 行与百鸽 14,423 条已全量逐条核对，原待复核的 1,945 张卡、2,223 个片段已逐项裁定。确认问题已接入运行入口，正式 b19 词典包含 14,299 张独立非衍生物卡；b18 整库读回及 b19 的 133 项本地回归、全库差异检查通过。迷宫变化的费用与发动时点已按官方调整补正。详见[修复结果与证据](../reports/2026-11-11-card-library-repair.md)，[原逐卡核对表](../reports/2026-11-11-card-library-semantic-review.md)保留审查过程。

R0—R11 本轮软件修复与定向验收已完成，末次补齐资格检查的资源监测入口。基础卡文与配套判断由现有程序提供，认知模块的后续能力提升单独评估。 [最终验收及源码入口](../reports/2026-11-11-design-implementation-repair-runtime.md)

2026-11-11 当前源码为规范化 v30、效果字典 b19、评分 v4。构筑已接入候选比较、暂停存档与续接、Agent 会话控制和基础 CB 静态目标。机器人资格检查支持单独停止本作业的子进程。现有程序能根据卡文和实际投入做基本配套判断，原案例命中 18 个指定组合中的 16 个，两例旅鸟漏检保留。认知模块由用户独立设计和训练，后续提供更强的体系识别能力。本轮按原 R0—R11 软件标准验收。完整构筑、训练、权重推理、实际 CB／原生引擎与硬件实测保持暂停，原 run-007 保留停止时的状态。 [R0—R11 验收](../reports/2026-11-11-design-implementation-repair-runtime.md) · [Agent 构筑接续](../development/generic-agent-integration.md#11-构筑逻辑分类器与本地-agent-的实际接续)

较早批次中，R3 的状态、随机身份、质量及失分续算通过 v26/b11 静态 360 项。R5 固定参考已独立于候选可选图接入同一评价，12 个候选跨三片参考恢复只做 66 对比较。下方进度保留各批次当时的状态。 [第五批报告](../reports/2026-11-11-design-implementation-repair-batch-5-calculation.md) · [R5 执行书](../plans/2026-11-11-design-implementation-repair-reference-execution.md) · [R6 接续记录](../handoffs/2026-11-11-design-implementation-repair-after-reference.md)

当前R3共享分配与关系局部续算（2026-11-11）：显式共享DFS栈、数量/组合/回收/返回身份游标及facts→uses→joint接续已实际接入；原F04/129反例和公开入口极小片JSON恢复通过。规范化v25/字典b9，十个明确静态模块去重254项全通过，0失败/错误/跳过，Torch未加载。R3状态安排/随机分支、质量完成/失分游标及R5和后续包继续开放，不能写为全部修复完成。见[第四批报告](../reports/2026-11-11-design-implementation-repair-batch-4-resume.md)、[最新独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-4-continuation.md)及[R3执行书](../plans/2026-11-11-design-implementation-repair-resume-execution.md)。用户已授权必要时自主同模型主聊天接续，直接开始下一实际步骤；训练、推理、CB/native、完整构筑、run-007继续暂停。下方旧F04失败及v24状态保留各批证据，不覆盖本段。

当前空状态联合专项（2026-11-11）：原必需先送墓再空墓反例已修复，新增共享副本区域、清空/返回、Token、规则离场和去向替代消费，规范化v24/字典b9。十个显式安全静态模块按ID去重292项通过，0失败/错误/跳过，未加载Torch；R3真实续算、R5独立参考及后续包仍开放。见[第三批状态报告](../reports/2026-11-11-design-implementation-repair-batch-3-state.md)、[最新独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-3-continuation.md)、[状态执行书](../plans/2026-11-11-design-implementation-repair-state-execution.md)和[R3续算执行书](../plans/2026-11-11-design-implementation-repair-resume-execution.md)。下方第二批失败和历史状态保留当时证据；训练、CB/native、完整构筑、run-007继续暂停。

最新第二批状态（2026-11-11）：已实施复杂卡文的通用次数/触发、Token与可选放置、支付实体/不同卡名、完整翻开选择及全局去向替代，规范化v23/字典b9。当前受影响九模块按ID去重270项通过、1项空墓联合条件反例失败；另R3枚举截断和R5参考独立性两项仍失败，完整CI未执行。R1/R2联合状态消费及后续包仍未完成。下一主进程先修空状态反例，再继续R3—R11；见[第二批报告](../reports/2026-11-11-design-implementation-repair-batch-2.md)和[最新独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-2-continuation.md)。用户已授权必要时自主新开同模型主任务并立即开始，无子代理；训练、CB/native、完整构筑、run-007继续暂停。下方重启暂停和首批计数均保留历史，不覆盖本状态。

最新恢复（2026-11-11）：用户已明确“继续修复”，解除下方重启暂停。沿原完整工作树由主进程继续R1及其余修复，无子代理；训练、CB/native、完整构筑、run-007仍暂停。本批确定动作见[执行书补充](../plans/2026-11-11-design-implementation-repair-r1-execution.md)。

最新暂停（2026-11-11）：用户要求先暂停工作，准备重启电脑以启用新的虚拟内存设置。接续主进程已停止推进，等待用户明确恢复；本轮仅完成技能、执行细则、设计、真实源码及官方卡文的只读核对，尚未修改程序、运行测试或启动后台任务。R1剩余语义尚未实施，原344项通过/2项开放失败状态保持。训练、CB/native、完整构筑、run-007继续暂停。重启后从现有完整工作树继续，不能自动重启旧运行。暂停细节见[完整接续摘要](../handoffs/2026-11-11-design-implementation-repair-continuation.md)。

最新授权补充（2026-11-11）：用户要求自主完成全部剩余修复，必要时可自主新开任务接续，仅gpt-6.1-sol/max、主进程执行、无子代理。复杂卡文余项必须修复；对照设计和当前官方口径仍无法定界的事项，完成其他修复后集中询问。额度以实时get_usage_limits为准，剩余≤1%且未完成时允许使用已有重置卡，更新旧20%停止/禁用条件。训练、CB/native、完整构筑和run-007继续暂停。已更新[完整接续摘要](../handoffs/2026-11-11-design-implementation-repair-continuation.md)，接续任务直接开工，不再等待启动或接续确认。

最新任务状态（2026-11-11）：用户已明确启动R0—R11修复，主进程执行、无子代理。首批建立R0基线并完成R1部分语义、R2专项、R4调度及R8/F12异常修复；344项明确静态回归通过，R3/129截断与R5/参考图约束两项开放反例仍失败。全部包尚未完成，见[首批报告](../reports/2026-11-11-design-implementation-repair-batch-1.md)、[执行书](../plans/2026-11-10-design-implementation-repair-execution.md)、[R0—R11方案](../plans/2026-11-10-design-implementation-repair-plan.md)及[接续摘要](../handoffs/2026-11-11-design-implementation-repair-continuation.md)。训练、CB/native、完整构筑继续暂停，run-007未恢复；下方“待命”“不再展开”和运行中说明保留各历史阶段，不覆盖本次启动及暂停指令。

本轮最新状态：已按用户最新要求停止run-007，运行进程已退出，不自动恢复。12份候选Evaluation与原始kernel／session／日志全部保留，完整存档一致；参考评价及S5未完成。“静态不完整”的设计问题留待后续优化，本轮不再展开工作。见[最终停止记录](../reports/2026-11-10-construction-condition-selection.md#按用户最新要求结束本轮)；下方运行中说明均为停止前历史。

更新：2026-11-10。先沿本页读取设计和最新修订，再沿对应源码核对。历史报告只说明当次证据，不能替代设计或本对话后续纠正。

## 目录职责

| 位置 | 用途 |
| --- | --- |
| `N:\YGO-Kito\_publish_20261030` | 当前完整源码检出及下列活动资料；全部构筑命令在此执行。含既有未提交修改、删除、未跟踪成果，不能按旧HEAD重建。 |
| `N:\YGO-Kito` | 外层历史仓库和归档来源。这里的README及旧源码不作为当前运行入口。 |
| `N:\YGO-Kito\_local_cpu_20261027` | 已有CPU环境、课程权重、环境清单和资源；不使用其中source副本的Python源码。 |
| `N:\YGO-Kito\_delivery_20261024` | 历史审查/交付副本，不能独立启动当前项目。 |

## 有效设计的阅读顺序

最新实际运行已接至`.cache/construction-condition-selection-20261110/run-007`：run-006一次保存替换访问拒绝后，以异常处理成功保存的较新完整kernel立即恢复，未用较旧session。代码未改、23文件绑定再次一致，必要静态仍94项通过；原v21／b7、任务、图、12份牌表及批次保留，3个原Evaluation ID保持。当前12份候选全部返回并通过同口径不变量核对，均仍静态不完整；正继续原指定参考及真实S5，不能宣布整体通过。入口与结果以[本轮报告末节](../reports/2026-11-10-construction-condition-selection.md#保存访问拒绝后的原任务续跑)及run-007实际输出为准，以下较早运行说明保留阶段证据。

当前最新实际进程为`.cache/construction-condition-selection-20261110/run-003`：run-002在完成常驻及先攻后真实返回主题支持合约异常，已保留原始失败和完整kernel。按原存档立即续接，支持条件分组及相同完整视图复用后的87项必要静态、22文件绑定通过；规范化v21／积木b7、原12份牌表及兼容计算保留。最新证据以[本轮报告末节](../reports/2026-11-10-construction-condition-selection.md#支持合约异常与相同视图复用)为准；下方run-001／run-002文字保留各自阶段。

最新续接见[完整条件与选择消费及实际续算](../reports/2026-11-10-construction-condition-selection.md)与[机械执行书](../plans/2026-11-10-construction-condition-selection-execution.md)。规范化v21／积木b7，完整条件／选择及JSON分配见证续接修正后的84项必要静态、21文件检查通过；完整2207任务池公共接口和786条择一关系投影无异常。run-001实际复现JSON容器差异造成重复入队，定点修正后从其最新完整kernel立即恢复到`.cache/construction-condition-selection-20261110/run-002`，保留原任务、图、12份牌表及兼容计算。实际候选、参考和Gate以新报告后续记录为准。进入跑通阶段后持续跟进，不为上下文交接主动停止；下方“无后台进程”仅属上一轮停止点。

最新时间与完整处理修复见[当前报告及独立交接](../reports/2026-11-10-construction-runtime-processing.md)及[执行书](../plans/2026-11-10-construction-runtime-processing-execution.md)。开发／训练没有上线时限，内部片自动续算；上线到期进入当前批次评价、选择、真实Gate及交付。当前规范化v20／积木b6，74项必要静态及20文件最终绑定通过。实际2207沿原12份候选完成5片保存后，为安全交接由助手主动中断；最新恢复档为`.cache/construction-runtime-processing-20261110/run-001/kernel.json`，12份仍待评，参考和Gate未形成，当前无后台进程。下表较早版本与旧挂起结论保留历史范围，以本段及当前报告为准。

| 材料 | 路径与适用关系 |
| --- | --- |
| 初始设计 | [项目设计定稿](游戏王AI项目设计定稿.docx)；原11份资料见[归档清单](../../archive-manifest.json)。 |
| 后续统一设计 | [统一规范](../plans/2026-10-22-unified-development-spec.md)，尤其§3.2持续召回、§18无卡ID逻辑和狭义筛轴、§19目标/优化分工。 |
| 10月29日原始优化清单 | [原件](YGO-Kito-优化工作清单-20261029.docx)，原来源外层docs；本目录副本为活动读取路径，外层保留归档。70/56等已经被后续方案修订。 |
| 11月2日职责修订 | [分层职责](../plans/2026-11-02-construction-role-reassignment.md)。 |
| 11月3日评分原设计 | [当时提取的正文](2026-11-03-construction-optimization-source.md)。保留原段落与表格编号；所注桌面DOCX目前不存在，不能称已找到原件。来源为外层.cache/audit-20261107的既有提取稿。随文Pro辅助代码不读取、不检查、不运行。 |
| 11月4日扣分修订 | [原件](YGO-Kito_构筑阶段扣分机制优化实施方案_2026-11-04.docx)，此前仅在桌面；本目录为活动读取路径，桌面原件不删除。 |
| 11月8日生产接线 | [正式方案](../plans/2026-11-08-construction-model-formal-optimization-plan.md)。原38条、12行补充结构、六包固定清单见[验收对齐表](../plans/2026-11-09-construction-acceptance-alignment.md)。其中后续自动加权、主流程纠正优先于早期状态。 |
| 本对话最新确认 | [S0—S6](../plans/2026-11-10-construction-s0-s6-workflow.md)是阶段骨架；[自动加权补正](../reports/2026-11-09-construction-theme-weighting-correction.md)记录真实配合归纳与主要+100%/次要+50%。 |
| 当前修复与验证 | [默认静态用途执行书](../plans/2026-11-10-construction-static-entries-execution.md)、[本轮实现与实际运行](../reports/2026-11-10-construction-static-entries.md)；[上一轮W1／W4](../reports/2026-11-10-construction-w1-w4-completion.md)、[此前流程修复](../reports/2026-11-10-construction-workflow-repair.md)及[初次运行排查](../reports/2026-11-10-2207-construction-attempt.md)保留历史。这些链接保留 v19／b5 的历史结果；当前规范化 v30、积木 b19 的状态见本页顶部及[卡库修复报告](../reports/2026-11-11-card-library-repair.md)。 |

本对话已逐轮回读：先对齐38条及补充结构，再执行固定清单；不把配置接口算功能落地；不做珠泪专用默认逻辑；unknown须区分缺输入与实现缺口。狭义主题是用户指定系列/种族作为必需轴，只在无卡ID逻辑之后筛轴，不等于纯轴或固定整副卡池。全项修复包括已知流程偏差，不能缩成两处运行报错。重跑使用2207、珠泪目标、已有权重，模拟正式运行，不人工填卡效事实、选候选或改牌表；不运行训练和CB。

2026-11-10 最新用户纠正：构筑是静态配置评价，不要求当前手卡、盘面、具体堆墓结果、对方对象或实际操作序列；自身状态联想用于资源转换与配套，对方对象描述应对范围。默认入口不得以这些状态未给而阻断计分或完整性，不造对手场面，也不把随机送墓冒充指定调用。完整卡文未消费之处归程序覆盖缺口，不能再要求用户另补同义结构化信息。该纠正优先于旧报告中的“缺少盘面／缺少输入”解释。

## 代码及实际资产

构筑代码入口为[自主任务](../../src/ygo_kito/autonomous_construction.py)、[固定任务与主循环](../../src/ygo_kito/construction_fill.py)、[统一评价](../../src/ygo_kito/construction_layer_flow.py)、[政策/参考/恢复/Gate](../../src/ygo_kito/construction_progress.py)。使用方法见[构筑说明](../development/construction-logic.md)和[准入说明](../development/construction-admission.md)。效果资料来自 effect_blocks、effect_records 和 MechanismCatalog。识别本批更新了共享卡文事实、自然候选和离线监督，已有模型状态沿[识别活动说明](../development/axis-generic-software-v3.md)。

指定参考保存在[2207](../../configs/user-deck-references/main-01-source-v1.json)、[2210](../../configs/user-deck-references/main-02-source-v2.json)，仅用于独立评价和符合条件的分层提示，不作构筑种子。

本地资产根`N:\YGO-Kito\_local_cpu_20261027`：`reports/course-continuation.json`给出实际课程根；`reports/optimization-20261031/2207-course-006/model-binding.json`为宿主绑定，`course/checkpoint-1.weights`为既有权重；`reports/native-runtime-cache-source-manifest.json`和`cache/native-runtime-42b468cc.tar`为已有规则资源；`source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json`给出2022.7禁表及2022-09-30发行截止。`reports/training.hold.json`保持原样。路径中的source只作数据定位，PYTHONPATH必须指向当前源码src。

本页是位置与阅读顺序，不建立额外审批。最新用户明确指令优先；活动状态以实际代码及本次结果更新，不把历史未验项机械变成新任务。

2026-11-10 资源访问补充：当前实际规则资源实体在`N:\YGO-Kito\_local_cpu_20261027\assets\native\engine-src`，中文卡库为其`database\locales\zh-CN\cards.cdb`，禁表为其`client\lflist.conf`。来源清单中的`source/.cache/engine-src`涉及WSL链接；Windows只读核对使用上述实体位置。原卡库、完整卡文和指定参考已经存在，最新未知归因及重新打开的实现项见[验收表第12节](../plans/2026-11-09-construction-acceptance-alignment.md#12-已有资源未被正确使用归因与验收纠正)，不能再次从程序unknown推定用户未补资源。
