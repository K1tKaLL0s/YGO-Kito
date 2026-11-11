# 轴与泛用识别 v3：完整软件入口与后续运行

2026-11-10 后续更新：用户已授权补齐全部 18 项任务并在全面就绪后通过[本地脚本](axis-generic-automatic-training.md)开始训练，新增工件位于 N 盘项目内，Dot 负责到时重启对话检查。[本次运行报告](../reports/2026-11-10-axis-generic-full18-training.md)和自动目录实际状态记录当前阶段；下文“没有运行”和显式启动限制记录此前核查批次，不撤销本次准备及训练授权。

2026-11-09，香港时间。本页已按第二次设计/代码核查更新，当前状态以[核查与清理报告](../reports/2026-11-09-axis-generic-review-cleanup.md)为准；前批[软件完成报告](../reports/2026-11-09-axis-generic-software-completion.md)保留历史证据。新旧训练入口、重复配置和旧计划启发规则已经清理。

本轮完成源码与允许的工程验收，最终受控回归 177 项全部通过。真实资料准备、正式训练、CB 搜索、原生引擎、CI 及实际能力发布没有运行。下列真实阶段命令供后续获准后的新运行使用；三份现行配置保持 formal_training=false，不会自动继续课程或激活模型。

## 路径与依赖

从完整仓库 N:\YGO-Kito\_publish_20261030 运行。解释器为 E:\Ana\envs\pcacgate\python.exe，工程版本 Python 3.10.20 / Torch 2.2.2，没有安装新环境。设置 PYTHONPATH=仓库/src;仓库、PYTHONDONTWRITEBYTECODE=1、OMP/MKL 各 2。当前只有 CPU 工程证据；显式 CUDA 请求不会回落 CPU。

本次准备和基础训练默认输出到 N:\YGO-Kito\data\axis_generic\v3 的独立目录；旧源资料原地保留。人工临时数据和 checkpoint 位于本仓库 .cache。不用旧 _local_cpu/_work 副本，不改活动指针。尚未启动的环境分支按其另行显式配置执行。

## T1：数据准备

唯一准备入口为 prepare_only → prepare_v3.prepare；prepare_v3.prepare_records 提供纯内存 API。旧资料仅经 legacy_import 中的只读审核函数迁移，不导入旧准备/特征/训练栈。来源分组、留出、标签迁移、未知与不适用、冲突、分片和缓存校验保持。新缓存同时绑定全部准备实现，源码不相容时要求新版本目录。

    & 'E:\Ana\envs\pcacgate\python.exe' -B -m training.axis_generic.prepare_only --config training/axis_generic/config.v3.json

输出 dataset.json 与分区分片。记录为 axis-training-record-v3，四块是 observations、targets、supervision、provenance；标签和来源不进入编码器。补标使用 LabelCell/LabelSet，未标注坐标不补负。真正独立测试保留 final_eval_eligible=true、previously_consumed=false；旧资料放 retrospective_test。

副本偏好来源记录另带顶层 comparison，固定字段 right、left_key、right_key、operation。主 observations 为左配置，right 使用相同来源观察白名单；operation 是真实 add/remove 对象及可选 kind，不能用说明字符串代替。准备过程对两端独立构图，两端的牌表、卡引用、操作和父子派生共同纳入去重/留出隔离。标签 subject 匹配两个配置引用，允许两端都叫 query:unit；没有右配置的旧单图偏好标签拒绝准备和更新。

明确目标、功能需求和资源预算通过 RoleInput.context 的结构化 Factor 输入；白名单为 CONTEXT_FACTORS 中除 plan_ 开头以外的因子，每项保留值、已知性、置信度和不确定度四通道。不解析 declared_goal/context_ref 的不透明文本，不根据卡名、旧计划词或 plan_known/plan_reference_coverage 生成目标。宿主可通过现有 context_provider 提供这些因子。

目标编码独立进入条件角色、主/辅位置、接收兼容、贡献和双配置偏好读出；mechanism、成员、轴功能/来源、固有迁移性及旧规模头不消费目标编码，single/dual 两种流均保持此边界。准备 input_key 包含实际编码的目标通道，同一物理配置在不同目标下保留独立监督，来源关联仍令它们处在同一个隔离组。显式同单元固有迁移性一致性可跨目标成立。编码指纹已更新，旧语义权重不能从当前入口隐式恢复。

## T2：基础训练和恢复

唯一基础训练配置为 config.train.v3.json，已合并建议参数：64/2、AdamW、学习率 .001、weight_decay .0001、dropout .1、梯度范数 1、微批 32、有效批量 64、最多 20 轮、patience 4、minimum_improvement .002。重复的 software 配置已删除。学习率固定，没有隐含调度器或混合精度；真实运行开关仍为 false，数据/输出指向独立 reviewed 目录。

    & 'E:\Ana\envs\pcacgate\python.exe' -B -m training.axis_generic.train_v3 --config training/axis_generic/config.train.v3.json

有效批量跨分片拼接，微批再受节点/边预算约束。所有记录及监督先验证，按整个有效批量的来源/任务分母计算梯度，再执行一次 optimizer step。单图越界拒绝，不截断；无有效监督不更新。跨微批反事实一致性须放在同一有效微批内，接口拒绝不能同时表达的配对。

训练前必须明确固定 selection_tasks。选定任务没有有效训练标签、开发类缺失或正式运行的输出坐标未覆盖时，在构造模型/更新前给出缺口，不会运行若干轮后才发现不能选模。不会自动删除未覆盖任务来凑分。副本偏好训练、批量预测和服务都使用同一个双配置评分路径；默认更新与显式微批也已合为同一实现。

新 run 保存 experiment.json、完整 recipe.json、训练/选模/校准组 partitions.json、不可覆盖 checkpoint、latest.json、best-development.json 和逐轮开发报告。选模不读取 test/retrospective_test。calibration_groups 须预留，自动从选模排除；未覆盖的选择任务不给分数。

load_mode=resume 恢复同实验的模型、优化器、RNG、有效批游标、最优文件和早停状态。早停/完成决定与 epoch checkpoint 一起保存，边界中断恢复不会多训；缺失的最优元数据由 checkpoint 的绑定引用修复。可变 JSON 元数据原子替换，废弃临时文件不会挡住续写。改变协议/架构/数据/优化器配置会拒绝。warm_start 是新实验，仅复制相容共享编码器并重建状态。mode=inference 只加载相容权重和能力计数，不恢复宿主 RNG/优化器，也不能用于更新或保存训练 checkpoint；预测和环境底座加载使用该模式。旧工件按对应相容源码复现，不从新入口自动恢复。

工程模式 execution_mode=engineering_fixture 要求 formal_training=false、CPU、最多 3 轮和显式不超过 64 条记录；所有来源与逐格来源仅允许工程夹具或定义开发资料。

## T3：消融和校准

统一 CLI：

    & 'E:\Ana\envs\pcacgate\python.exe' -B -m training.axis_generic.workflow_v3 <action> --input <新输入.json> --output <新结果.json>

| action | 输入与结果 |
|---|---|
| ablation-plan | base 为训练配置，生成 single/dual × route off/on 四格，同数据、预算、种子；selected 指定两个有效格、seeds 指定三个不同种子时生成两格三种子配方。仅生成配方，各配方通过 T2 入口运行。 |
| ablation-compare | results 各项含 cell、seed、score、scope=development、comparison_binding。binding 含 dataset、split、epochs、effective_batch_size、optimizer、selection_groups。不同预算、来源、种子集合或最终测试成绩拒绝比较。 |
| predict | evaluation_authorized=true，checkpoint、network、binding、label_protocol_sha256、device，以及 records 或 dataset_dir/fold/groups。binding 取该 run 的 experiment.json 中四个实验摘要。返回完整 axis-predictions-v3 工件，含实际权重 model_id、dataset_id、records_id、predictions；按批/图预算遍历全部配置和比较对。 |
| calibrate | records、predictions、model_id、dataset_id、training_groups、selection_groups、reserved_groups。只消费预留 validation 来源，三组互斥；来源等权 NLL 拟合温度，来源等权宏 F1 选二元阈值。默认至少 2 个校准来源组。 |
| evaluate | records、predictions、calibration 工件、完整 assessment protocol；可另给 training_groups。只消费 test/retrospective_test；省略训练组也不能绕过工件绑定的训练组排除。 |
| release-candidate | report、calibration、requested_tasks、baseline 及可选完整 policy；生成逐能力 eligible/reasons，不切换模型或指针。 |

calibrate/evaluate 也可用 dataset_dir/fold/groups 代替 records。读取器核对完整准备实现、分片数、语义摘要、ID、来源与分区。后续请求的 predictions 参数必须放入 predict 输出的整个工件对象，不能剥掉外层模型/数据/记录绑定；真实来源不接受裸映射。仅人工算术测试允许工程裸映射。校准来源组从 T2 partitions.json 取得，逐格 source 与协议也要核对，不能靠改 source_kinds 头部把工程数据变成真实证据。

Calibration 工件绑定实际权重、数据与组划分。缺类别或坐标覆盖保留未覆盖；头级正负齐全但仅某个输出坐标有证据，不能发布整个多标签头。模型继续更新后，评分器拒绝过期校准。

## T4：独立评估与宿主加载

报告同时保留 raw、calibrated、applied。拒答留在已知标签分母内，自然候选漏检计入召回，分类混淆矩阵含 unknown 列。多标签任务先对每个固定输出坐标按来源等权计算，再做坐标宏平均，避免常见坐标淹没稀少坐标；未覆盖坐标不删除。指标版本为 axis-source-coordinate-macro-v3-review1，包含二元/多类 Brier、ECE、原来源组 bootstrap 与候选匹配。

发布初值沿主计划：F1 .80、覆盖 .90、候选召回 .95、open 精确率 .90、closed→open ≤.05、未见 receiver F1 .70、同协议关键任务退化 ≤.03。三层分别核对；相关上下文能力还须有 provenance.evaluation_slice=unseen_receiver 的真实独立切片。无真值、缺输出坐标、缺基线、历史资料和工程来源不能通过。

宿主明确选择已审阅候选工件后构造服务：

    from ygo_kito.multifactor.calibration import Calibration, host_capabilities
    from ygo_kito.multifactor.scoring import CandidateScorer
    from ygo_kito.multifactor.analysis import RoleAnalyzer

    calibration = Calibration.load(calibration_path)
    capabilities = host_capabilities(
        release_manifest, calibration, trainer, evidence_ref=independent_report_path,
        assessment_report=independent_report, baseline_report=baseline_report,
    )
    analyzer = RoleAnalyzer(
        fact_provider,
        scorer=CandidateScorer(trainer, calibrator=calibration),
        capabilities=capabilities,
    )

host_capabilities 检查真实训练状态与工件绑定，并用实际评估/基线报告重算候选决定；手改 eligible 或错接报告会拒绝。基线须为不同模型、同记录和同指标版本；不能拿候选自身充当基线。发布函数位于运行时 calibration.py，宿主不反向依赖训练目录。函数仅返回映射，不写活动指针；真实宿主发布仍由后续发布指令执行。

CB hints 仅给显式声明支持的宿主 callable。纯接口工程测试已完成；legality/route_success 仍为 unknown，不产生真实搜索或合法 CB 证据。

## T5：独立环境价值支路

RoleTrainer.create_environment_adapter 创建独立支路。旧 v3 enable_lora 继续拒绝在基础角色路径安装 hook。

- head_only：冻结独立底座副本，只训练环境头。
- lora_head：仅给环境副本编码器的线性层加低秩增量，并训练环境头。
- full_copy：独立副本全量微调；比较配方默认学习率 .0001，其他两路 .001。

公共环境特征固定为 interaction_demand、resource_horizon、tempo_pressure、opponent_diversity，均在 [0,1]；独立支路同时消费基础图与上述结构化目标编码。environment_id、period、driver_version 仅追溯。反馈给投入价值目标 [0,1] 与 source.kind/partition/group/evidence_ref/confidence。真实源 environment_feedback 与工程源 engineering_fixture 不混用。source 必须为 train；使用准备记录时，其分区和来源组也须匹配。

    & 'E:\Ana\envs\pcacgate\python.exe' -B -m training.axis_generic.environment_v3 --config training/axis_generic/config.environment.v3.json

新配置 base 的 checkpoint/network/binding 与 release/calibration/assessment_report/baseline_report 均为空，正式开关关闭；真实环境适配须明确选择有真实训练及校准/验证依据的底座。输入 version 为 axis-environment-feedback-v3，records 各项含 record_id、observations、environment、value、source。全部反馈先检查，坏尾行不会让前行先更新。独立 adapter checkpoint 绑定数据、配方、底座能力证据、设备/Torch 环境和批边界游标，不能跨数据续跑。

workflow 的 environment-plan 生成同数据三路配方；environment-calibrate 用独立 validation 反馈拟合线性值校准；environment-assess 用真正 test 反馈与同记录基线比较来源等权 MSE。真实预测反馈记录还要带匹配的 adapter_id/base_id 和完整 environment 追溯。非有限校准系数拒绝评估。参数 max_mse/maximum_regression 默认 .10/.03，是环境值协议的显式界限，不是构筑定价；provider 会复查实际指标和真实训练组。

独立真实评估通过后，才能构造 EnvironmentProvider(adapter, context_provider, artifact) 并显式传给 RoleAnalyzer(environment_provider=...)。默认 disabled；observe 只记诊断，assist 才给环境值。工程适配器不能启用真实能力；环境失败只停该头。三个环境分支的更新、保存恢复与开关均不改变基础模型输出。

## 验证与继续工作

本轮最终受控检查为明确选取的 177 个方法，全部通过、0 skip、0 禁止调用；包含 22 个设计复查专属方法。首次错误与复验均保留在报告中。当前软件调用链完整；后续剩余是实际资料补标/准备、T2–T5 真实运行、GPU 实机、能力成绩和宿主选择发布，保留用户原运行限制。

当前不存在 train_base、prepare_base、prepare_balanced、finish_existing 等旧模块，也没有旧 v2 神经 CLI 分派。事实入口要求显式 --service；神经预测使用 workflow_v3 predict。当前三份配置为 config.v3.json、config.train.v3.json、config.environment.v3.json。旧文档和 runs 只作历史资料，不从那里挑运行入口。

本地明确工程检查可选取 tests.test_multifactor_review_v3、tests.test_multifactor_training_controls_v3、tests.test_multifactor_learning_v3、tests.test_multifactor_workflow_v3、tests.test_multifactor_environment_v3 等模块运行 unittest；不使用已删除的旧检查脚本或 discovery。实际 guard、选取清单和回执见本轮报告。
