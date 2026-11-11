# 当前构筑准入与学习接口

本轮最终状态：已按用户最新要求停止run-007，不自动恢复。12份候选评价已返回并保留，当前实现记录的静态完整性均未通过；参考评价和真实S5尚未完成，不宣布准入通过。该设计问题留待后续优化，本轮不再分析或修复。原始存档与结果保留，详见[停止记录](../reports/2026-11-10-construction-condition-selection.md#按用户最新要求结束本轮)；下方运行中表述均为历史。

2026-11-10 最新规范化v21／积木b7的实现、运行中通用修正后的94项必要静态、23文件绑定及当前2207的run-007连续续算见[本轮报告](../reports/2026-11-10-construction-condition-selection.md)。run-006一次保存替换访问拒绝后，以异常处理成功保存的较新完整kernel立即恢复，源码和评价条件未改。开发无任务时限，内部片自动继续；一旦进入尝试跑通阶段，不为上下文或交接主动停止。质量v4、准入v3和80%参考门槛不变，实际候选、参考和Gate按本轮结果记录，下方旧版本段落保留对应历史范围。

2026-11-10 最新静态边界：构筑直接评价卡文能力、牌表投入、资源转换与配套，不要求当前手卡、盘面、具体堆墓结果、对方当前对象或实际操作序列。默认入口已按规范化v19／积木b5接入完整印刷适用来源；未解析或未接通的条款归程序覆盖缺口，不要求用户重填同义字段，不用人工置真。具体起点、实际命中和执行路线属于后续基础CB，仍须静态通过及显式授权。当前证据与未完项见[默认静态用途报告](../reports/2026-11-10-construction-static-entries.md)。

2026-11-10 当前接线及真实结果见上方最新报告，[此前流程修复与2207重跑](../reports/2026-11-10-construction-workflow-repair.md)保留历史。完整环境卡池与检索批次分开；无卡ID图先于筛轴和卡效查询；候选生成后同口径评价参考，参考问题由Gate保留。当前规范化v19，质量v4、准入v3保持。最新状态按[S0—S6](../plans/2026-11-10-construction-s0-s6-workflow.md)及本轮结果判断，不能把局部静态通过换算成整个构筑已经通过。

11月9日静态阶段使用质量v4、准入v3及规范化v13；本轮规范化已升v19。旧入口删除依据见[模块代码核对报告](../reports/2026-11-09-construction-module-code-review.md)，当前验收见[38条及主流程对齐](../plans/2026-11-09-construction-acceptance-alignment.md)。旧七项百分制、固定70／56草稿及旧最终层排序均已退出。

## 构筑和比较

固定任务入口 `construction_fill.construct_task`、`ConstructionController` 和自主主题内核共享 `construction_cycle`。目标模型通过 `build_axis_skeleton` 交付部分轴骨架，优化模型补齐并持续修改主卡组、额外卡组、副牌组；骨架不承受完整成品牌表门槛。`model_group`、`lora_group`、`build_training`、`group_runner` 仍有实际调用，均接当前构筑入口。

狭义主题是明确要求为必需轴的系列／种族。固定任务只读取正最低投入的系列／种族约束；可选条件不触发筛轴。筛轴发生在无卡ID逻辑后，不限制后续配套、泛用及整副卡组的检索范围，也不自动添加12／3等数量。自主任务和固定任务均从通用词表生成粗逻辑，不以本轮具体卡的识别结果决定必需标签。

`host_construction_quality`／`AutonomousConstructionKernel.quality_for_task` 在骨架交付后、评价候选前固定政策和指定参考。主题／目标规则由原任务、主题卡的真实配合及明确功能归纳，主要目标额外 +100%、次要目标额外 +50%，同一处理取高档；继续使用原 log2 公式。完整环境中的无关卡不挤占主题归纳的读取预算。候选只影响配合是否成立，不能改变自己的权重。其他主题不继承珠泪规则或参考。2207／2210 既定课程读取各自指定参考，2610 显式无参考。`reference_ratio` 使用同政策重评后的参考 S 和0.8比例，不把历史人工约70分换成固定56的当前通过线。

`fill_with_existing` 逐候选完成规范化和质量评价，再以完整、原任务硬条件成立的最终有效分 S 选择并保留。模型分安排待评顺序及同分取舍；静态语义尚未覆盖或未评完时保存队列、游标及原因，不按旧排序给出最终优劣。库存诊断、K／E 和轴信息继续供解释及骨架使用。

候选trace使用`quality_evaluation_id`和`quality_summary`，完整Evaluation保留在候选、学习候选及待评记录中。摘要不作为Evaluation消费；比较、Gate和学习仍核对完整评价。续接中的最后一轮记录只保留重选所需证据，不复制本片学习批次和已经独立保存的保留集。破坏保护按其自身用途处理，不当作未适配玩家限制全局deferred；未解析的印刷适用条件仍保留明确覆盖缺口。

`construction_gate` 检查实际牌表合法性、原任务必要能力、当前质量完整性、宿主明确指标及指定参考比例；无政策保持 `quality_policy_unconfigured`。未采用的可选效果缺件不再全局否决，必要能力未知仍阻止通过。副牌组不补足第一局主卡组／额外卡组配套，方向内换备按真实容量和完整条件评价。构筑通过不等于 CB 成功，CB 调用仍需独立执行授权。

保留候选各有自己的质量与门槛。`quality_selection_allowed`、`select_retained`、反馈和学习标签使用同一当前 S 比较，核对原任务、政策、牌表、资产及卡文来源；重选同步候选版本和续接状态。旧 `retained_order`、`layer_selection_allowed`、旧评分类型及草稿 `construction_contract` 已删除，不作为恢复或训练入口。

`scripts/design_supervisor.py` 使用当前准入及质量契约核对保存证据，分别读取部分骨架与完整优化提案，继续检查牌表、时期、角色交接和 CB 输入归属。任务条件复用公开判断，支持嵌套、字段子类及等级区间。单独的 passed 标志不能替代这些检查。

## 恢复、提示与学习

开发／训练没有上线运行时限，时间、轮数和候选数量只限制内部单片；默认入口自动消费保存的片内进度。上线到期停止新增候选，完成当前批次及参考的同口径评价、选择和 Gate，再交付当前最好方案、验证范围和未满足项；真实 Gate 与独立 CB 授权仍保留。显式 `run_mode='slice'` 供已有外层调度器消费单片，不能将其挂起结果作为开发任务完成。用户暂停、异常和静态覆盖缺口按具体原因保存。schema 3 保存原任务、骨架、候选、评价游标、交接和反馈；政策、规范化、资产或事实绑定变化使候选和参考重新核对，保留牌表和批次，不复用不兼容内部计算。

自主工作流元数据为2。旧版把预筛名单当成任务卡池的资料只作历史归档，权重和累计更新不变，原主题在完整环境中重新绑定；不再恢复旧封池入口。当前schema3保存`query_cursor`及本轮检索名单，待评恢复不重新选图或生成候选。同卡异画复用已有模型行；规则上当作同名的其他卡使用自己的发行日期及模型身份。

指定参考模式下，`record_reference_attempt` 只计真实完成且确认低于门槛的构筑尝试。同一迭代不重复计数；参考缺失、unknown、错误、暂停和预算耗尽不计不足。第二、三、四次确认不足分别给主轴、副轴、泛用的功能与配套建议，进入后续优化反馈；不暴露参考卡名、配方或精确投入。确认通过重置连续计数。

`construction_learning.cycle_pairs` 从实际优化候选提取严格质量偏好，未知或未能确定优劣时不制造标签。`consume_optimizer_slice` 仍是课程消费接口，绑定原任务和候选并去重；本轮仅用静态替身核对消费，不进行参数更新。没有改模型结构、词表或训练算法。

字段名称表作为包内规则资源发布，绑定实际卡库提交及文件摘要，不依赖旧运行包是否附带 `strings.conf`。明确字段用卡库 `setcode` 匹配；歧义名称保持未知，名称表缺失或版本不符直接报错，不能把整类已知依赖悄悄降为未知后宣布缺口已清除。

`CourseAdmissionPolicy` 根据当前牌表、当前卡文及宿主质量政策重算同一构筑门槛，不要求外部评分文件。正式对战独立要求当前牌表自己的成功条件 CB 证据及 `basic-cb-linear-mainline-v1` 范围；旧回执、随机结果分支和静态评价不能替代它。

## 唯一事件状态和预测反馈

真实完成的 CB 信号及完成构筑后的确认存入既有课程事件，随同一个 checkpoint 保存。not_run、预算未展开、未知故障和重复回执不累计失败；连续两次合格失败产生优化请求。确认只消费构筑开始前的触发边界，本轮新失败仍保留。

20/50 胜率反馈继续属于冻结预测与实际终局比较；仅达到局数不构成低表现证据。这一功能不由已删除的参考评分账本提供。真正不确定的原生或优化器事务仍停在相应事务边界。

## 当前执行边界

11月9日静态阶段的147个不同方法及失败修正见核对报告；本轮检查和真实构筑独立记录在[修复与重跑报告](../reports/2026-11-10-construction-workflow-repair.md)。已实际加载原课程权重运行构筑，未启动训练、CB、原生对局或监督进程，课程权重、暂停文件和指针保留。历史[职责报告](../reports/2026-11-02-construction-role-basic-cb.md)、[统一修复记录](../reports/2026-11-02-construction-unification.md)及[旧质量报告](../reports/2026-11-02-construction-quality-scoring.md)保留对应当时状态，不能据其旧版本恢复执行。

## 只运行构筑与续接

维护入口为`scripts/run_construction.py`，使用当前源码及已有课程资源。它不提供训练开关，输出到全新目录；`--device cuda:0` 显式选择 GPU 推理，CUDA 不可用时报错，不改写原始训练检查点。`--basic-cb` 授权静态 Gate 通过后的基础 CB，默认关闭。`device.json` 保存实际模型设备、前向调用及显存证据。默认开发模式自动续算并按片保存 kernel／session。`--slice-seconds` 和 `--iterations` 只控制片内工作；`--seconds` 仅用于 `--mode online`，开发模式拒绝将它设为任务时限。上线到期先排空静态评价，CB 仍按实际授权及预算执行。下例在现有WSL环境内执行，`--theme`核对宿主已经选定的目标，不改写宿主配置：

```sh
cd /mnt/n/YGO-Kito/_publish_20261030
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
PYTHONPATH="$PWD/src:$PWD/scripts" \
/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -u scripts/run_construction.py \
  --checkpoint /mnt/n/YGO-Kito/_local_cpu_20261027/reports/optimization-20261031/2207-course-006/course/checkpoint-1.weights \
  --model-binding /mnt/n/YGO-Kito/_local_cpu_20261027/reports/optimization-20261031/2207-course-006/model-binding.json \
  --environment /mnt/n/YGO-Kito/_local_cpu_20261027/source/.cache/local-base-training-20261027/2207-base-005/active-environment.local.json \
  --workspace /mnt/n/YGO-Kito/_local_cpu_20261027 \
  --native-root /mnt/n/YGO-Kito/_local_cpu_20261027/assets/native \
  --period 2022-07 --theme setcode-181 --mode development --slice-seconds 120 --iterations 4 \
  --output .cache/construction-next-slice
```

续接时增加`--resume 上一片目录/kernel.json`并指定另一个全新输出目录。保留原任务、骨架、候选、Evaluation及查询／评价游标；不能删参考、人工补牌或改变通过线来制造通过。输出包括任务、结果、会话、可续接kernel、候选牌表和摘要；`listing_complete`只说明张数齐全，是否通过看`construction_passed`及Gate原因。
