# 完整 18 项资料与脚本训练运行记录

2026-11-10，香港时间。用户授权保持全部 18 项训练范围，补齐资料并在全面就绪后通过脚本开始训练；用户安排 Dot 监控预计时间、重启对话检查。正式训练由本地脚本独立执行，Dot 到时检查结果。

## 当前阶段

2026-11-10 12:05:51（香港时间），完整 20 轮、420 次优化器更新及预留组校准、历史评估已全部完成，state/summary 均为 complete、error=null。接续读取完成快照，resumed_completed=true，没有追加训练更新。最终 checkpoint 和第 18 轮开发最优 checkpoint 均保留。新独立测试集不存在，模型未激活。用户最新要求暂不重启，等待另一构筑模型任务结束后由用户另行通知。下方早期启动记录仅描述当时状态。

最终准备与全任务检查已于 01:02 完成。自动入口返回退出码 0，summary.status=prepared、ready=true、missing=[]。实际 full18-readiness.json 核对全部 18 项及全部固定坐标在 train/selection/calibration 中的类别和至少两个标注来源组，结果全部通过；1775 条合并记录中有 1679 条包含新增审阅查询，127147 个已知格、4571 个未知格。实际分区为训练 1297、验证 390、历史评估 88、隔离 0，来源组与冻结的 22/3/2/3 完全一致。数据 ID 为 7ad386357c83375ed096101fd1be8265c565e46a8007fbb0fbb886da6852cc22。

01:03:04 通过 scripts/axis-generic-training.ps1 -Start 启动独立隐藏本地进程，PowerShell 启动 PID 53512，启动回执保存在 .cache/axis-generic-full18-20261109/launch-receipt.json。该回执仅证明进程启动；实际 CUDA 恢复、正式更新/checkpoint 与计时证据分别见下文。

后台 Python PID 61620，启动器退出后仍持续运行。01:09:08 进入 CUDA 实测，三个有效更新分别耗时 75.7135 / 74.7829 / 74.3446 秒，两个连续批及恢复后的重放各为 64 条、微批32，损失 0.647593 / 0.606368 / 0.606368。恢复后的下一步所有参数逐位相同、步数相同，recovery_equal=true；没有 CPU 回落、无跳过或非有限更新。实测 CUDA 峰值分配 425239552 字节，独立实测 checkpoint 保存在自动目录 timing/recovery-sample.pt，不替代正式基础模型。

01:13:35 完成实测，每轮 21 个有效批，开发选择86条、预留校准304条。开发预测两条实测4.969秒，外推完整开发每轮213.673秒；按实际分片加载外推每轮训练I/O46.796秒，校准/历史预测等后处理外推973.952秒。最多20轮初估37592秒（10.44小时）；patience4的最早可能停止轮为5，对应初估2.81小时，但不预测早停是否发生。初始估计完成香港时间11月10日11:40:08，含25%时间余量的检查时刻14:16:46。初始估计不包含实测后尚未完成的正式入口初始化；正式批/轮事件会持续刷新 estimate.json，最终以最新文件为准。

01:13:36进入正式 fit，01:14:37保存零步初始快照。01:15:55完成首个正式有效批：微批2个、有效64条、optimizer_updates=1、skipped=false、loss=0.6475930831、gradient_norm=0.5562592745。component_losses明确包含全部18任务，unrepresented_candidate_cells=0。checkpoint-e0000-b0000001-s000000001-f0.pt和latest.json已保存，游标epoch0/next_batch1；实际模型更新及恢复快照已经发生。后台进程仍为61620、状态running/stage=train，模型未激活。

首个正式批耗时70.742秒，实际进度刷新后的估计剩余35824秒（9.95小时），预计完成香港时间11月10日11:13:00，25%余量检查时刻13:42:16。结合初始三批测量的更保守检查时刻14:16:46，建议Dot首次安排11月10日14:20检查；此前无需保持本对话常驻。后续按最近10批中位数及完整每轮开发耗时更新 estimate.json，可能早停或随实际速度变化。启动验收后的本轮工作已结束，不等待整个训练完成；Dot到时续接完成结果检查。

## Dot 到时检查

自动目录的 dot-handoff.json 提供 PID、命令、日志、状态、估时及训练目录。estimate.json 是持续更新的估计；handoff 内的 estimated_check_at 是首次快照。到时重启本对话，读取 state.json、estimate.json、attempt-0002.log，并核对精确PID和正式训练目录 latest.json。status=complete 后查看 summary、best-development 与校准/历史评估结果；仍运行则按实际进度更新预计时间；失败则保留错误和已有工件，查明后使用同一 PowerShell -Start 从最近完整快照恢复。不重新补标、重建数据、削减任务、覆盖旧快照或激活模型。

只读取当前状态的命令为：

```powershell
& 'N:\YGO-Kito\_publish_20261030\scripts\axis-generic-training.ps1' -Status
```

## 实际来源与监督范围

源目录为 N:\YGO-Kito\data\axis_generic\v3\full18-20261110-008，包含 source-records.json、full18-evidence.json、full18-protocol.json、source-partitions.json 和 source-summary.json。原 118 个案例保留适用的旧审核标签；63 份不同接收牌表上构造有明确配置/目标的真实卡片功能查询，合计 1819 条源记录。14 个逐卡文审阅单位覆盖机制、轴成员/功能、功能角色、贡献、成对关系、位置、来源、迁移、兼容和实际副本配置比较。全部 18 项任务及网络、优化器和有效批量保持。

新增监督为 assistant_reviewed_weak_context，证据固定了本地真实卡文、所问功能、目标、可见资源与实际增删操作。它是有来源的弱标注，未冒充独立人类标注、引擎运行或真实对局。Normal Monster 的机制负例由完整卡文及类型确认；缺失的解析标签不作为负例。卡文机制标在真实卡节点上，轴成员负例不排除可能的替代素材。当前接收兼容和固有迁移分开，破坏必要成员的查询只监督其明确不完整性，不改作 closed 迁移样本。旧作用范围不完整的 generic 标签保留撤回历史，不从新 portability 反填。

旧 v6_2 的 8643 行只用于恢复全部历史来源关联，将原 30 个关联分量传到原案例及新查询。63 份牌表不计作 63 个独立来源组。按固定标注类别覆盖冻结训练 22 组、选模 3 组、校准 2 组、历史评估 3 组。分组在模型训练前决定，没有按预测成绩重选。所有当前资料保留 previously_consumed=true / final_eval_eligible=false；历史评估不能登记为新独立最终测试。

## 路径与真实执行

| 内容 | 路径 |
|---|---|
| 最终准备目录 | N:\YGO-Kito\data\axis_generic\v3\prepare-full18-20261110-006 |
| 自动状态及日志 | N:\YGO-Kito\data\axis_generic\v3\automatic-full18-20261110-002 |
| 本次基础训练 | N:\YGO-Kito\data\axis_generic\v3\base-full18-20261110-001 |
| 专项验证及早期失败日志 | N:\YGO-Kito\_publish_20261030\.cache\axis-generic-full18-20261109 |
| 机械执行书 | docs/plans/2026-11-09-axis-generic-full18-training.md |

运行解释器为 E:\Ana\envs\pcacgate\python.exe，Python 3.10.20 / Torch 2.2.2+CUDA12.1。现有 RTX 4060 Laptop GPU 总显存 8585216000 字节，准备预检时可用约 7.43 GB，N 盘约 332 GB 可用。硬件预检不代替实际模型更新/恢复验证。本任务无依赖安装或下载，全部新增资料、数据、日志和 checkpoint 位于本项目 N 盘。

## 验证及修正历史

15 个补标/查询/分组/计时专项方法最终通过，另有准备后哈希 ID 的来源识别专项通过；冻结划分专项已扩展为实际 prepare_records 后分区一致性检查并通过。首次 28 方法批次中 26 通过、2 个人工测试构造错误，分别为不存在的增卡计数字典键和被近重复规则合并的人工牌表；修正后保留首次和复验日志。后续一次测试使用不存在的 Observation.known 属性，改按真实 value 接口验证并通过。已通过的既有自动编排/恢复方法沿本次日志复用，没有无关整仓 CI。

真实源检查先后抓到错误的卡文引句、机制查询不在实际卡节点上、旧迁移标签对覆盖的影响和历史桥接变体被过滤后来源分量拆分；均在正式更新前修正。源资料 001–007 及未完成准备保留为诊断草稿，未用于正式训练。最终流程另确认通用随机划分会叠加在逐源冻结划分上，现以 1/0/0 的基线和逐源 validation/test reservation 表达冻结分区，不修改准备器语义。新 gate 从 provenance.source_record_ids 识别原始新补标身份，准备生成的哈希 record_id 不再导致误漏。

本轮累计 35 个不同方法均有最终通过记录（16 个补标/就绪/计时方法，17 个既有编排方法及 2 个受影响训练恢复方法），92 次物理执行、3 次中间测试构造错误均保留在 .cache/axis-generic-full18-20261109/test-history-summary.json。AST 7 个 Python 文件、4 个 JSON 配置/标注文件、PowerShell 语法及本次文档链接已通过。最终数据类别/坐标覆盖与 CUDA/运行实测须以本次自动目录中的实际报告为准；未通过就绪检查前不开始正式更新。模型激活、发布、CB/原生引擎、整仓 CI 不属于本轮。


## 2026-11-10 原实验接续与输入用途核查

10:39 的失败发生在 automatic_v3.postprocess → workflow_v3.evaluation_records → prepare_v3.verify_preparation_implementation，校准预测尚未写出。准备绑定的 11 个文件中只有 effect_count_limits.py 不一致；该共享文件在训练期间被构筑工作更新。Git 3f57198e5e366152bbb672be8910e6800f8adbb4 的对应文件与本次准备身份完全相同。没有把当前构筑源码回退，没有手改数据 manifest，也没有关闭版本或分片校验。

本实验专用恢复目录为 N:/YGO-Kito/data/axis_generic/v3/automatic-full18-20261110-002/prepared-runtime-20261110-001。source/ 只冻结本次准备所需的 11 个小型源文件；source-manifest.json 记录逐文件来源。resume.ps1 -Check 已核对数据身份、全部分片、自动运行身份、最终快照绑定及实际加载的次数解析器来源。resume.ps1 通过原 automatic_v3.run 接续；原训练器对 sampler.finished=true 直接返回，不再进行优化器更新。当前实验再次接续须使用此恢复入口，不能在已更新的共享准备实现上重新创建或覆盖原数据。

两项明确选取的现有 CPU 测试通过：test_full_local_pipeline_and_completed_restart_reuses_postprocessing、test_completed_run_rejects_corrupt_postprocess_binding。恢复脚本 PowerShell 语法检查通过。没有运行原生引擎、整仓测试、外部模型或付费 API。

实际训练目标仍是完整 18 项轴与泛用识别。独立逐分片检查确认 1297 条训练、390 条验证、88 条历史评估记录均包含相应任务标签。1819 条源记录均为 weak_context_annotation，其中 1701 条明确为助手审阅场景，118 条为旧案例；旧案例对应 63 副不同主/额外牌组，新增审阅覆盖 14 类功能单位。它们不是 1819 场实战或引擎金标。

次数信息是输入特征，不是训练输出头。准备建图会把次数解析为 effect_once_per_turn、按名/实例限制和条件节点；GraphNode.numeric_values、encode_graph_batch 和 GNN 的节点编码器实际消费这些值，训练和预测共用。保存图的离线评估不再运行次数解析，但现有实现仍检查该准备源文件的整体指纹，因此本次评估入口的代码依赖较宽。

真实 CPU 只读探针使用训练记录 record:8c5ead458492346efb922445f63744de 和第 18 轮最优权重：输入张量 371×786，次数属性第 124、128、132 列分别有 52、52、26 个非零节点。只屏蔽七个次数属性的值及已知掩码，轴成员、迁移性、来源输出的最大绝对 logit 差分别为 0.03369、0.02542、0.00969。该例询问羽毛扫与黑洞的清场功能，焦点两卡没有次数限制，探针中的次数特征来自牌组其他卡。结果仅证明网络受这些信息影响，未证明信息有益或对识别必要；本次没有据此改动特征或重训。

核查明细保存在恢复目录 data-purpose-audit.json。若后续验证特征价值，应先在开发集副本做只读屏蔽对照，再另设相同划分、配方和种子的训练消融；不能把一次输入敏感性变化当成性能增益，也不能用已消费历史评估选择新特征。

最新用户安排：另一项构筑模型任务仍在运行。本任务完成后只汇报训练与评估成果，暂不重启电脑；等待用户新的明确重启指令。


## 12:05 最终训练与后处理结果

接续中另发现一项初始化缺陷：复用 timing/measurement.json 时不会重新调用 seed_everything，新进程 cudnn_deterministic 默认为 false，而原快照为 true。其他 Torch、CUDA、线程与 TF32 字段一致。恢复入口现先初始化原有 seed 与确定性设置，再逐字段验证与快照环境完全相同；保留训练器原校验，没有暖启动或更改训练配方。attempt-0003 保留该首次接续错误，attempt-0004 成功。

原 20 轮训练没有跳批，420 个有效批次全部完成。第 1 轮开发来源宏平均准确率为 70.34%，第 18 轮最优为 95.27%，第 20 轮为 94.96%；第 1/20 轮平均批损失分别为 0.53178/0.06396。实际后处理使用第 18 轮快照 checkpoint-e0018-b0000000-s000000378-f0.pt，最终恢复快照 checkpoint-e0020-b0000000-s000000420-f1.pt 保持原样。

12:03:28 保存 304 条校准预测，12:03:35 完成全部 18 个训练头的 fitted 校准；12:05:44 保存 88 条历史预测，12:05:51 保存历史评估并标记 complete。历史评估为 3 个来源组，应用校准后的 18 项已覆盖任务 pooled F1 平均值为 87.68%。逐任务 pooled 与来源等权 F1 分列如下，避免混用指标口径。

| 任务 | 已知标签格 | pooled F1 | 来源等权 F1 |
| --- | ---: | ---: | ---: |
| axis_function | 1116 | 96.23% | 96.23% |
| axis_membership | 234 | 99.72% | 99.72% |
| axis_origin | 60 | 100.00% | 100.00% |
| axis_position | 60 | 69.54% | 69.66% |
| contribution | 138 | 100.00% | 100.00% |
| copy_preference | 9 | 100.00% | 100.00% |
| function_role | 375 | 95.58% | 95.59% |
| legacy:compatibility | 60 | 93.33% | 93.33% |
| legacy:generic_utility | 24 | 100.00% | 100.00% |
| legacy:large_axis | 7 | 0.00% | 未定义 |
| legacy:pairs | 6 | 100.00% | 100.00% |
| legacy:small_axis | 6 | 75.00% | 75.00% |
| legacy:strategic_core | 60 | 76.47% | 75.04% |
| legacy:support_role | 60 | 94.34% | 94.44% |
| mechanism | 3813 | 99.65% | 99.65% |
| pair_relation | 36 | 100.00% | 100.00% |
| receiver_compatibility | 60 | 78.37% | 77.14% |
| transferability | 60 | 100.00% | 100.00% |

较弱项目包括轴定位、接收兼容以及旧大轴头。旧大轴只有 7 个已知格（1 正、6 负），模型未召回该唯一正例；不能用 85.71% 的准确率掩盖其 F1=0。高分的旧泛用、成对关系与投入偏好头也分别只有 24、6、9 个历史已知格，样本规模随指标同时保留。

历史记录全部已有消费史，test 分区为 0，不能登记为新的独立测试。完整轴集合未标注，88 条记录的整集合轴 IoU/召回均无可计算结果；34 条记录存在候选数量上限诊断。这次给出的成员/功能指标针对已标注查询，不能替代任意牌组的全轴发现验收。报告额外列出的 state_readiness 是确定性支路，不属于本轮 18 个学习头；其无标签状态不改变 18 头校准已完成的事实。

summary.postprocess.status=complete；capability_accepted=false、model_activated=false。宿主 PID 46348 已退出。原数据、已有模型、全部快照及当前构筑源码未被覆盖；接续的新增内容仅为本实验冻结运行资料、日志、校准与评估工件。紧凑结果为 automatic-full18-20261110-002/result-summary.json，完整预测/评估在该目录 postprocess/。estimate.json 与 dot-handoff.json 已更新为完成、剩余 0，且明确禁止在用户新授权前重启电脑。
