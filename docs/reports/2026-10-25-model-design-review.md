# 模型组与训练链路独立设计审阅

日期：2026-10-25。审阅基线：`9be7668`，并核对本轮工作区的模型组修正。本文对照统一设计第2、4、5、6、7、9、10、12、18节与最新阶段澄清，检查实际源码和已有正常测试证据，不以清单勾选代替实现。

本轮起初为只读审阅；root随后授权修正 `group_runner.py`、`coordinator.py`及对应测试中的具体反馈接线问题。修改及针对CPU测试已完成，生产源码与测试停止修改。未提交、推送或合并，未运行原生故障、进程终止、未筛选discovery、付费训练或外部API。

## 结论

三个执行模型、独立统筹网络、目标/优化交替、实际训练损失、四角色LoRA和完整阶段边界恢复均有实际实现，并非只有接口占位。学习统筹当前提供未校准建议，程序规则作最终控制，符合第一阶段先采用规则调度的设计。

发现并修正当前必需的反馈接线缺陷：多对手验证中台账分配与实际执行身份可能不同；强制重构的子候选验证仍被错误标为普通验证；预警后的优化候选被评估入口误拒；旧子候选可绕过后来才触发的强制重构。后两项由独立验收者补充复现。新增契约测试覆盖修正及拒绝边界；最终统一回归和合并判断由root独立完成。没有将GPU、调优、正式能力、PC或可选LLM增设为软件合并前置。

“第一阶段可调用工程”不表示全部训练设计已经完成。主模型跨期权重初始化是已确认设计要求的**本轮必需软件入口**，不能因实际训练在第二阶段就把缺少该代码视为无需补齐；root已另行分配实现，本文不替未冻结模块背书。受控候选晋升与正式BO3的现状另列如下，不能写成已实现或仅缺实测。

## 按实际调用核对设计

| 已确认要求 | 实际实现与消费路径 | 准确边界 |
| --- | --- | --- |
| 三个执行模型独立，决斗快速选择合法动作 | `duel_model.PlayerEncoder/DuelActorCritic`为轻量Transformer actor/critic；`BuildTrainer`创建两套独立`BuildRanker`、优化器、调度器并核对参数存储不相交。`CpuTrainer.sample_episode`的动作内循环直接调用决斗模型和引擎，不经过统筹或LLM。 | 模型结构和调用已实现。PC端到端1–3秒、竞技操作能力属于后续实测；输入超出显式token/action预算会拒绝，不宣称支持任意规模。 |
| 策略只看合法信息，历史与随机性隔离 | `PlayerEncoder.encode`接受typed玩家请求，拒绝控制器seed及隐藏身份/数值；编码公开历史、合法私有观察和合法动作。完整审计、原生响应和双方牌表保留在私有工件。 | 可见信息契约已有代码。完整原生规则覆盖由对应规则审阅负责，本报告不重新认证所有卡效。 |
| 目标与优化分工，保留目标、张数和真实条件 | 目标侧使用BCE；优化侧使用偏好成对损失。`alternate_build`执行目标→优化→目标→优化，每步重验，保留`task.sha256`及可复现改动。`GroupState.execute_stage`实际调用这些角色，随后用候选牌组采样。 | 评分是候选排序，候选由有界程序产生。旧课程的攻击力代理、真实规则对手成对比较和schema4显式属性偏好分别标明，不冒称竞技构筑质量。 |
| 轻量构筑逻辑、狭义/广义路由及反馈重构 | `ConstructionSession`绑定原始请求与任务摘要，保存图修订祖先及反馈；`LogicModelAdapter`复用两套`BuildRanker`选择有界程序图，并有实际偏好训练/保存加载；`ConstructionController.run → construction_cycle`执行两角色阶段1/2/3并调用既有统筹建议及可选真实台账托付。 | `providers()`是实际模型适配方法，而非唯一依赖夹具。图候选生成仍是程序，功能标签不能因此成为合法卡效。模型图能力与分类泛化没有被小合成训练证明；缺入口权重继续拒判。 |
| 统筹统一调度、版本托付和反馈 | 独立`CoordinatorNetwork`由聚合上下文产生路由建议和概率；`route_with_model`先取权威规则上下文，再运行真实MLP并记录建议；`Coordinator`负责候选、预测、租用、结果事务及谱系。组运行器有六阶段循环和可恢复游标。 | 首阶段规则权威符合设计。默认监督是明确合成规则/概率锚点；新增显式host标签可训练，但来源摘要不等于真实性认证，概率未校准。没有宣称自动归因所有输局或已学会预算分配。 |
| 百场内提醒、千场内强制重构，不能重命名重置 | `FeedbackPolicy`预登记25/50/75/100/125/250/500/750/1000等检查点，结合差值与单侧不确定性界；`Coordinator._results/_required/_schedule`保存不可改预测、结果及根谱系预警，并阻止普通任务绕过必须重构。 | 不是只在100/1000整点检查；25/125是特定合成极低成绩的触发结果，不是替代用户阈值。正式差值、重复观察统计方案和独立性仍待第二阶段冻结/验证。 |
| LoRA持续适配、冻结基模和回退 | `AdapterSession`实际参数化Linear权重，仅训练A/B；每次检查基模摘要与无梯度；支持独立优化器/调度器/RNG、启停、卸载、保存和精确兼容加载。group bootstrap后冻结四基模，再各自更新适配器。 | 不隐式叠加、合并或跨上下文加载；实现不是PEFT包装占位。陌生任务收益、遗忘、发布质量门槛和低资源PC开销仍未验。 |
| 当前策略采样、训练/评估隔离 | `CpuTrainer.update`检查当前模型SHA、策略版本、实际新采样摘要及完成边界。registered LoRA还须`DataAdmission`。`semantic_curriculum`和`DataIndex`绑定实际对手身份、种子、时期/版本及train/validation/final_eval，验证数据不会成为本轮PPO标签。 | 普通CPU PPO为单次有界更新；独立LoRA冒烟可对一份当前策略rollout作两个预定epoch，不等同复用旧策略/外部LLM数据。正式吞吐和大数据课程是第二阶段工作。 |
| 保存、恢复和指标 | `GroupState.save_to/restore`保存四模型、全部优化器/调度器、四适配器、模型与控制器RNG、阶段游标、数据标记、索引和SQLite台账；核对源码/资源/任务绑定及较新预算状态。评估比较全组训练状态指纹。`RunReporter`记录实际墙钟、进程CPU时间及RSS；训练报告保存损失、熵、价值/策略损失、参数变化和真实对局推理时延。 | 只恢复完整对局/完整工作阶段，不宣称原生半局、半批或多机恢复。GPU数值、吞吐/显存及PC性能是各自阶段实测；未测GPU值不伪造。 |

## 本轮确认并修正的问题

### 1. 多对手验证未执行台账实际分配的对手

原触发条件是分期validation有多个实际对手。`group_runner.evaluate`按`episode_cursor=index`轮转实际adapter，而`Coordinator._schedule`按该局seed从冻结scope分布抽取对手，两者不保证一致。返回的job只核scope、席位、牌表和seed，没有核对实际对手。此外`evaluation_scope`会按ID规范化scope；原代码比较未规范化局部scope，会对合法的反序输入直接误报。

本轮纯CPU复现使用真实`Coordinator` SQLite/API与显式合成契约数据：宿主绑定顺序为opponent-02、opponent-01，seed=1分配opponent-01；旧的第0位置会取opponent-02。反序scope也会在台账规范化后与旧局部对象不等。

修正：

- 以`forecast.register`返回的规范化scope核对job。
- 新增`_scheduled_validation_cursor`，按租用对手ID、牌表SHA与`opponent_identity`三者精确定位本期validation绑定；拒绝同身份别名重复、未知/不匹配身份及没有sampling weight的条目。
- 用该绑定索引取得实际adapter，再核对实际对手牌表、驱动/模型身份与job一致。
- 实际game seed继续使用本局recipe seed，policy seed继续使用同一validation分区；额外与期别manifest精确比较。改变的是对手选择遵循已分配job，而非按scope排序或局序猜测。

`semantic_curriculum.opponent`中这个索引只选择绑定/profile，再重绑actor；lookup返回的其他seed不进入采样器。既有`DataIndex.ingest_episode`仍按实际`summary.opponent_binding`核对冻结数据集，并禁止物理seed跨目的，未放宽admission或跨分区限制。

### 2. 强制重构子候选仍使用普通验证purpose

原`evaluate`固定提交`purpose="engineering_validation"`。一旦根谱系产生mandatory_rebuild，即使目标/优化已交付不同卡表且保留父版本，既有`Coordinator._schedule`仍正确拒绝普通purpose，使组路径无法进入已经支持的`rebuild_validation`。

新增`_validation_job_purpose`：没有必须重构时保持旧purpose；必须重构时，仅当台账确认候选响应了当前告警才选`rebuild_validation`。原根候选明确拒绝，原卡表换ID仍由既有候选唯一性门禁拒绝。根/子版本警报均保留，没有新增清除、降预测或重置场次的接口。

### 3. 预警后的优化候选被再次评估入口误拒

独立验收用真实账本的26条显式合成loss触发`reevaluate`，再提交改变牌表的子候选。根谱系保留预警，使实际route为`build_optimizer`；原`evaluate`只接受`register_forecast/build_goal`，因此在新预测前异常退出。

路由检查现由`_validation_job_purpose`统一处理，允许已完成构筑阶段后的优化候选登记新预测/验证，仍保留根预警。`diagnose/train_duel/stop`继续拒绝，未把告警改为清除操作，也没有缩短现有每轮四段目标/优化交替。

### 4. 仅有父节点不能证明响应了本次强制重构

独立验收先创建A→B，再通过公开`dispatch`完成B的125条显式合成loss。B自己触发mandatory后，旧判断仅因parent非空就允许同一B、同一预测继续`rebuild_validation`，没有任何新的构筑版本。

`Coordinator`现于新候选首次接受的事务内记录宿主生成的`rebuild_after_forecasts`，内容为当时本根谱系已存在的mandatory forecast ID集合。`_rebuild_validation_eligible`与`schedule`重新核对候选确实改动父牌表，且创建锚点精确覆盖当前根mandatory集合。此外读取该根所有mandatory预测关联的失败牌表SHA集合，候选不得与其中任一牌表相同，防止把B失败原牌表重新挂到旧父A、只改环境/driver冒充新重构。此前已有候选、过早创建的后代均不合格；新mandatory来自后续forecast时，原锚点不能自动响应新告警。重试相同handoff保留首份回执，不会刷新锚点；旧台账候选缺少锚点时保守拒绝，创建响应当前告警的新版本可继续。

没有加入“根谱系永久只能使用从未出现的卡表”的门槛：不同于当前全部mandatory失败牌表的既有有效构筑，可以作为新版本重新接受、保留来源与当前锚点并重验。新增CPU同时覆盖失败B换父/环境/driver后的实际schedule拒绝，以及先前有效A核心仍具备重验资格。

该诊断放在route回执的`rebuild_validation_eligible`字段，不加入统筹网络14维上下文，不改变公共请求schema或删除旧数据。组入口提前拒绝不合格候选；schedule事务再次核对，不能依赖过期route绕过。

## 本轮测试和已有证据的界限

初轮新增3项CPU契约测试，先单独3/3、再同模块6/6通过。追加修正后，新增warning与当前mandatory版本门禁测试；最终明确4模块 **27/27通过（1.264秒）**，包含先前子集，不累加成更多独立测试。`git diff --check`通过。

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=src \
  .cache/ci-cpu-venv/bin/python -m unittest \
  tests.test_group_runner tests.test_coordinator \
  tests.test_coordinator_model tests.test_coordinator_supervision -v
```

测试使用实际台账/API、统计判定和身份函数；合成结果只用于契约，不是125场实际对局。未以mock模型或伪原生终局替代训练证据。新多对手接线尚未在本轮重新跑真实多对手对局/完整group周期，应明确区别于下列已有正常证据，最终回归由root组织。

- [训练与恢复正常结果](2026-10-24-pretraining-evidence/normal-results.json)及`.cache/pretraining-engine/verified-training-recovery-tests.log`保存15项真实正常训练/恢复检查：决斗非零更新、双构筑独立更新及下一更新一致、四模型真实托付、四角色LoRA及卸载/恢复。这是已有证据，本轮没有重跑。
- [普通group](2026-10-24-pretraining-evidence/group-normal-proof.json)与[分期group](2026-10-24-pretraining-evidence/period-group-normal-proof.json)保存实际完成的四角色worker/检查点及冻结评估；普通/分期为不同scope，工程日期不冒充已审计历史池。
- [两期snapshot正常结果](2026-10-24-period-opponent-evidence/period-snapshot-normal-results.json)为4项测试：两场自然终局、两次精确重放和两次重绑开局。actor为`PublicRulePolicy`，opponent为同一已更新base duel组件的冻结推理迁移，本轮0训练更新，不是主模型跨期训练恢复、最新LoRA或强度资格。

这些历史结果绑定各自源码/资源，不能把它们改写为当前补丁的全套重新验收记录，更不能用当前源强行恢复旧checkpoint。

## 本轮必需实现与后续验收边界

以下明确区分“尚无代码”与“已有工程但未做能力验收”，不将后者变成当前软件交付的新门槛：

1. **主模型跨期继承入口属于本轮必须补齐的代码。** 初验时`GroupState.__init__`总是新建`BuildTrainer/CpuTrainer/CoordinatorTrainer`；严格restore要求原task/period/resource/source绑定，缺少可信宿主显式将前期主模型权重迁入新期的路径。已有snapshot迁移仅是对手的冻结推理。root已另行分配独立模块，并接入初始化/保存/恢复，待冻结后独立验收；处理卡片/标签词表、基模/适配器选择、来源SHA及优化器重置/继承语义，不得通过擦除cutoff或放宽旧恢复绑定实现。实际GPU迁移训练效果归第二阶段，这不免除现在交付可调用入口的要求。
2. **强制重构后的受控晋升仍缺。** 本轮打通子候选重验，但现台账没有清除或晋升API，根谱系强制状态永久保留。保留证据是正确的；未来须新增经明确验证后解除当前运行阻挡、同时保留原预警历史的受控转移，不能宣称已完成全自动重构晋升。
3. **正式BO3/换备执行、能力指标与统计冻结未完成。** 当前正常组执行BO1，契约可表达BO3不等于已有换备执行器。统一设计的BO3场数、分项胜率/区间、启动/废件/抗打断概念、陌生牌组公平LoRA对照，须在2B/2C实施并报告达标/未达标/证据不足。失败类型的结果契约已有；不能据此宣称所有真实异常/重试已纳入正式统计。
4. **正式学习内容未被工程小试证明。** 当前主要为有界程序候选排序，工程静态偏好/有限真实比较及合成统筹监督；不是模型已自主理解完整卡文或学会通用CB。图偏好训练、实际反馈记录和可扩训练标签入口可调用，自动质量归因与已校准调度仍需真实训练数据。
5. **GPU、调优与能力归第二阶段，PC归第三阶段。** 目标GPU锁安装、CUDA实际数值/恢复/吞吐、正式训练及迁移收益，不是当前软件merge前置。PC产品、GUI/客户端互操作与低资源实机验收后置；外部LLM/provider可选。历史全库资料由指定独立流程取得，未知资料继续拒绝，不以合成资源替代。

本审阅没有运行新的完整训练或原生测试，没有更改原生绑定/guard、费用或权限设置。反馈接线修正交root与独立验收者复核，跨期初始化及新增bots部署由对应执行者交付后另验；当前不宣称整体验收通过或允许合并。
