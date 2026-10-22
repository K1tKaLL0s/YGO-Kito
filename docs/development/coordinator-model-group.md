# 统筹规则、学习原型与四模型工程闭环

本页落实[统一说明](../plans/2026-10-22-unified-development-spec.md)第2、5、6节。当前范围为固定真实核心与工程牌组的有界CPU流程；[M3c报告](../reports/2026-10-23-coordinator-m3c.md)区分实际更新、真实对局和合成统计，[M3d](lora-and-cloud-handoff.md)补充实际LoRA接口。完整模型能力、正式统计方案、LoRA迁移能力及PC门槛仍待验。

## 控制与模型分工

`Coordinator`是确定性程序，负责合法托付、固定预测、任务租用、结果事务、谱系预警和路由。`CoordinatorNetwork`是独立648参数MLP：14个聚合特征→16→16，输出7种路由建议及一个概率。它不共享三个Transformer的可训练权重，不在每次决斗动作前运行，不需要LLM。

当前MLP用8条明确标记的合成规则模仿/概率锚点记录训练，实际交叉熵＋MSE、两次AdamW更新。概率锚点不是实战胜率标签；`real_win_rate_supervision=false`、`calibration=pending`。它只提供建议，规则决定实际行为。例如本次预算耗尽时MLP仍建议继续验证，实际规则返回stop。该反例保留在日志中，不能据损失下降宣布已经学会调度。

规则优先级为：预算耗尽先停止并保留待重构状态；目标无效或必须重构返回目标侧；系统异常转诊断；操作错误转决斗训练；预警转优化侧；未登记预测先登记；其余分配冻结策略验证。当前公开托付只接收真实验证成功的条件目标，非法目标在入口拒绝；一般目标修复/完整错误归因和学习预算分配仍缺。

## 固定角色与结构化协议

命令 `coordinator-call INPUT --ledger PATH --role ROLE`接收严格JSON：

```json
{"schema_version":1,"id":"inspect","method":"forecast.read","params":{"forecast_id":"group-forecast"}}
```

| 宿主固定角色 | 可调用方法 |
| --- | --- |
| monitor | status、history、candidate.read、forecast.read、job.read |
| build_goal / build_optimizer | 上述只读方法，以及handoff.submit、forecast.register |
| coordinator | 上述只读方法，以及handoff.submit、forecast.register、job.schedule、route |
| duel_worker | job.read、job.claim、results.append |

角色与证据source由可信宿主设置，请求不能修改。默认不初始化缺失台账，monitor不能创建；首次创建须显式`--create`。台账绑定`real_engine`或`synthetic_contract_test`与固定反馈配置，二者不可混写。拒绝符号链接、其他SQLite应用、未知字段、跨版本/跨任务结果及角色越权。数据库事务保护整批结果；同结果完全一致时幂等，冲突拒绝并回滚。

托付字段包括candidate_id、parent_candidate_id、完整BuildTask、main/extra/side及两构筑模型SHA。真实托付再次执行卡表检查和核心条件目标验证；不是相信提交方的成功标志。任务及硬目标、环境/规则、卡表摘要保留在台账；同目标新候选须连回父谱系，不能换ID重置旧反馈。

预测须在该范围的任务分配前登记，绑定构筑、预测模型、冻结决斗策略/LoRA、对手牌表与驱动及权重、先后手分布、core/scripts/cards/协议/卡池/禁表和BO1/BO3单位。同卡表/范围不能用新ID或下调预测重开计数。新环境/驱动作为新层保存，旧结果和根谱系预警仍保留。

job.schedule只允许一个pending/leased任务，收回结果或查明在途状态后才能继续。job.claim独占租用；已租用/已完成不能再次领取。任务包含固定范围、席位、对手及控制器种子，种子只属控制审计，不交给策略。真实执行器重核策略SHA、对手牌表/驱动、席位和支持范围；当前只执行BO1、空额外卡组的工程对局，默认组命令无LoRA。M3d的[LoRA组命令](lora-and-cloud-handoff.md)要求显式活跃适配器及版本校验，不能只填版本字符串开启；未知范围明确失败。

## 百场/千场规则与待校准参数

`configs/coordinator-feedback-engineering.json`是工程配置：检查点25/50/75/100/125/250/500/750/1000，最小25场，差值0.10，族错误预算0.05，平局分0。**这些不是已批准的正式验收参数**；Q-04/E-01仍待冻结，当前配置强制标pending。不是仅在100/1000整点检查。

每条预测序号k分配alpha_k=alpha/[k(k+1)]；该预测有m个预设检查点。在场数n检查时，对[0,1]分数均值采用上界：

```text
upper = min(1, mean + sqrt(log(m / alpha_k) / (2*n)))
low   = upper < frozen_prediction - margin
```

在**冻结范围内各局分数独立、共同期望稳定、有界**的假设下，单侧Hoeffding界与有限比较的并集界给出每预测各次检查总错误上界alpha_k；再对k求和不超过alpha。自适应训练、相关对局、变化对手或未登记检查不能直接继承此结论。当前只实现条件性工程判定，没有实证校准误报/功效或证明真实样本满足独立性。原始来源：[Hoeffding 1963原论文公开副本](https://www.csee.umbc.edu/~lomonaco/f08/643/hwk643/Hoeffding.pdf)、[NIST有限比较与Bonferroni说明](https://www.itl.nist.gov/div898/handbook/prc/section4/prc473.htm)。

low在百场内产生reevaluate；百场以后、千场以内的任一预设点low产生mandatory_rebuild，同时保留预警。强制状态阻止普通验证任务，只允许保留硬目标、实际改变卡表并关联父版本的新候选进入rebuild_validation。操作/系统诊断或预算结束均不能删除强制状态。当前没有晋升或清除强制状态的API；新候选完整重验与受控晋升是明确剩余项，不能假装已经自动完成重新构筑。

报告中的25/125是完整工程配置对合成极低成绩样例计算出的首次触发位置，不是缩小100/1000，也不是正式固定阈值；检查点配置仍标pending，用户百场内提示/千场内强制的设计保持。正式训练计划不自动将工程默认值视为已冻结统计方案，见[澄清与交接](lora-and-cloud-handoff.md)。

win/loss/draw/timeout/crash/invalid_action全部进入总体分母，分类保留；失败不能删除。默认draw_score=0时预测目标为win_rate；非零平局分必须明确预测expected_match_score，不能将期望积分写成胜率。单局损失保留diagnosis=unknown，不自动归罪构筑。统计契约可接BO3单位，实际BO3/换备执行和正式评价仍缺。

## 实际CPU流程与恢复

```bash
.venv/bin/python -m ygo_kito model-group-cpu \
  --root .cache --state-root .cache/model-group \
  --run-id UNIQUE-RUN-ID \
  --task configs/build-engineering-v1.json \
  --feedback-policy configs/coordinator-feedback-engineering.json
```

该有界命令重新建立独立工程run：真实生成构筑监督并对目标/优化各更新两次；执行四步条件目标交替并托付已验证最佳候选；真实核心采样一局，决斗模型更新一次后冻结；学习统筹更新两次；登记未校准预测；分配并完成一局真实验证，回收结果并按预算停止。验证数据不进入当次PPO更新。共7次规范optimizer.step；恢复分支重跑验证不重复计入规范样本。

在任务pending且未claim时保存单个组checkpoint：四模型、全部优化器/调度器、各自RNG/批次游标、Python/Torch全局RNG、任务与监督/资源/代码绑定、SQLite快照字节和状态摘要。默认schema1；M3d显式LoRA组使用schema2，另含四角色适配器训练状态并要求预期兼容清单，缺失拒绝。恢复使用weights_only=True，目标目录必须不存在，重新验证所有绑定，实际再跑同一待验证对局；比较规范化轨迹/结果、四权重/适配版本和台账状态，不比较墙钟或推理时延。已租用的不确定任务不保存成可盲重试快照；没有半局原生状态恢复。M3a/M3b另有更新后续跑对照。

独立工程run用于重现证据，**不能当作生产台账替换入口**。未来可信训练宿主须固定持久台账与数据卷、恢复原谱系并审计备份；不能删除DB、另开smoke run或回退历史来消除预警。当前不是跨主机强防篡改日志服务，文件系统管理员仍能改文件，角色检查不是OS权限隔离。

本批已保存run可只读查询：

```bash
.venv/bin/python -m ygo_kito coordinator-call \
  .cache/m3c-group-proof/read-forecast.json \
  --ledger .cache/m3c-group-proof/runs/m3c-group-20261023-v1/coordinator.sqlite3 \
  --role monitor
.venv/bin/python -m ygo_kito agent-call \
  .cache/m3c-group-proof/read-group-checkpoint.json \
  --state-root .cache/m3c-group-proof --role monitor
```

监控不加载神经网络/原生对局，不调用LLM。外部对手仍只允许[单席位动作接口](external-agent-interface.md)，不能拿统筹台账、双方牌表、种子或审计记录作为策略输入。统筹/构筑上下文有本方牌表及任务信息，不能直接透传给对手。

`training.control`默认仍无后端；本命令不是外部agent的训练启动权。CodeBuddy/DeepSeek、SDK额度和真实外部端到端未验，没有配置凭据。[M3d](lora-and-cloud-handoff.md)已提供实际LoRA管理切片、无凭据CPU预检/预算入口和腾讯云受限接管说明；真实联调、正式迁移和既定阶段缺口仍待验，不扩本轮为PC应用。原学习ZIP/TODO保留，剩余20%保存停止，不使用重置卡。
