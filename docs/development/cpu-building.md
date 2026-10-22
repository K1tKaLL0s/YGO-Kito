# 构筑目标与优化模型 CPU 切片

本入口继承统一说明1.1的目标/优化分工及“目标→改进→目标→改进”流程。它是工程切片，不替代标签交叉检索、CB推导、额外组合、情境构筑概念和真实对局纠偏的原设计。LLM不在必需路径，未启动腾讯云、GPU、付费训练或API，也没有新下载模型/依赖。

## 两个独立模型与程序边界

`BuildRanker`的架构代码可复用，目标和优化各自实例化独立的卡片embedding、Transformer编码器、评分头、优化器和调度器；没有共享可训练参数。默认各17,665参数，1层/宽32/4头/FF64，仅是工程配置，Q-01最终参数仍待小试冻结。此前决斗模型仍是独立权重。

`BuildEncoder`是共用的确定性特征编排：任务目标、固定卡最低/最高张数、三部分张数、显式情境标签及候选构筑，配合实际公开卡库的属性。标签使用“·”，保留layer/source/subject/condition，工程目标与工程代理标签不能冒充卡效事实。完整公开效果文本被读取并记录来源摘要；当前没有完整效果语义编码、主题/效果/情境交叉再检索或自动标签推导。未知注释词表/卡池与版本不兼容直接拒绝。

任务ID、控制器种子、训练标签、核心审计与未来抽卡不进入网络。模型对**约束程序生成的有界候选**打分，程序负责独立卡表校验和最终真实核心验证；不声称神经网络自身已经学会规则或合理构筑。当前17张显式pool只属于工程样例，不能当永久封闭召回池；MG-02再检索仍待实现。

## 输入、输出和合法性

`BuildTask`提供版本化JSON，字段见 `configs/build-engineering-v1.json`：

- `environment`：明确core/scripts/cards/协议/卡池/禁表版本，当前只接受与固定资源完全相符的custom环境。官方历史期/发行截止日未经核验不能借用当前禁表宣称通过。
- `goal`：当前只支持 `normal_summon`；明确目标卡，以及玩家0、第一回合、本方实际起手必须含目标卡的起始条件。任意CB/多步效果目标尚不支持，不能猜成成功。
- `sizes`、`pool`、`requirements`：主/额外/副卡的确定张数、允许候选与各区域固定卡最低/最高张数。目标卡须有明确主卡最低数量。
- `annotations`、`source`、`candidate_budget`：分层上下文与来源，候选预算2～32。工程样例明确标`engineering_fixture`，不会替代用户待提供的3＋8套卡组。

完整构筑的输出固定为可解析的 `{"main":[...],"extra":[...],"side":[...]}`，与现有注册器JSON导入一致，已有实际集成往返测试。三部分别名/张数合计禁限、OCG身份、主/额外类型、Token禁止、允许卡池与用户固定约束均由共享校验器检查。优化候选在评分前过滤，输出后再验；违反目标不能作为静默妥协。

`build-check`只检查卡表和硬约束，明确输出 `route_status=not_evaluated`、`construction_quality_status=not_evaluated`，不把合法牌表当已实现目标：

```bash
.venv/bin/python -m ygo_kito build-check \
  --root .cache --task configs/build-engineering-v1.json \
  --deck path/to/three-section-deck.json
```

工程样例主卡40张、额外空、副卡1张。非空额外卡表也有实际合法性测试，但当前原生适配器未装载额外卡组，路线返回 `unsupported_route`，不得忽略额外后冒充整副构筑的真实成功。副卡校验不代表换备/BO3功能验证。

## 真实条件路线与失败分类

对支持的低星通常怪兽目标，验证器使用原始核心、实际卡库和真实发牌；检查本方合法观察是否满足声明起手条件，在限定审计种子中尝试，记录未满足的尝试。它不会修改已发出的手牌或真实牌序以伪造达成，也不将挑选到的条件起手宣称为随机起手稳定率。

动作从真实提示中选择并通过会话绑定提交。卡片刚进入怪兽区时可能仍处于召唤响应窗口；只有公开场面保留目标卡且已收到真实 `MSG_SUMMONED=61` 才记录成功。这个切片只验证条件召唤路线，不是完整决斗或复杂效果推导。

- 卡表/固定要求违反：`ContractError`或监督中的明确`hard_constraint_failure`。
- 已实际验证的条件路线：`verified_success`，保留起始条件、随机依赖、实际响应指纹/事件种类及版本。
- 未支持区域/目标：`unsupported_route`；预算没找到：`not_found_within_budget`，不能标“不可能”或自动生成负标签。

默认每条路线最多16个种子尝试、100次决策/10秒，整个交替接口最多4阶段/30秒；预算可在所写CPU上限内收紧。检查发生在原生调用之间，阻塞核心看门狗仍待R-12，不能冒充正式比赛计时。

## 真实CPU训练与checkpoint

```bash
cd /workspace/YGO-Kito
.venv/bin/python -m ygo_kito build-train-cpu \
  --root .cache --state-root .cache/agent \
  --run-id my-build-proof \
  --task configs/build-engineering-v1.json \
  --training-config configs/build-training-smoke.json
```

要求新run ID，重复运行/检查点名称拒绝覆盖。复用现有Python 3.12.14、Torch 2.14.1+cpu、NumPy 2.3.5。Torch只在模型命令导入，基础命令仍不依赖Torch；资源缺失时非零退出且不造成功。

本命令先实际生成工程监督，保存分层来源和数据摘要：目标模型2条真实条件路线为正例、2条违反主卡张数的候选为显式硬失败负例；未知或未支持路线不作负例。优化模型使用2组合法且保留硬约束的构筑比较，标签只是**主卡怪兽印刷攻击力均值**，不是启动、稳定性、抗打断或胜率。输入编排不接收这些标签或控制器审计。复用监督不混入决斗PPO的on-policy采样。

目标使用实际BCE损失，优化使用实际pairwise logistic损失。每个模型各2次AdamW更新，保存两份成对checkpoint；从batch-1实际恢复，重新执行第二批，要求两模型的损失/参数变化与连续运行完全一致。规范4次optimizer.step，含恢复对照物理执行6次，不能重复计作新训练。

checkpoint含两个模型/优化器/调度器、RNG、批次游标、任务/词表/监督摘要和实现/资源版本；只允许两角色均完成更新后的边界，半更新的模型组拒绝保存。恢复采用`weights_only=True`，资源/任务/数据绑定不符拒绝；本独立构筑命令不保存LoRA，M3d另有[四角色适配与组恢复](lora-and-cloud-handoff.md)。多机/正式预算或半局原生状态仍未恢复。旧M3a等checkpoint须使用其绑定的源码/资源，不能在改源码后绕过摘要检查。

## 目标→优化交替接口

`alternate_build(task, assets, models, encoder, base=None)`支持从零或现有构筑起步，按目标/优化/目标/优化执行。每阶段记录角色、模型SHA、规则版本、原任务SHA、候选、验证状态、未校准评分、预算及逐卡张数改动；默认LoRA空版本，M3d可显式传入两构筑角色的lora_versions摘要。改动能对前一构筑重放校验，任务固定，模型不能改写用户目标。

每个选中候选重新由真实核心验证条件目标。预算耗尽或无法验证时只返还此前已验证候选及未满足项；“最佳”目前只按明示的工程攻击力代理比较，不代表最佳实战构筑。原始结果包含末次优化使代理下降的实际记录，不以参数已更新宣称质量已学成。

训练状态以source=trainer发布到既有RunReporter，`agent-serve --role monitor --state-root STATE`可读真实指标及登记checkpoint。`training.control`仍未接后端，CodeBuddy/DeepSeek端到端未验；这个CPU命令不授予外部agent启动训练的权限。

构筑独立切片结果保留在[M3b交接](../reports/2026-10-23-building-cpu-m3b.md)；当前[M3c统筹/四模型流程](coordinator-model-group.md)已接收构筑托付并实际冻结策略验证、回收结果及组恢复。三个执行Transformer和648参数学习统筹均仅为原型，统筹规则优先/合成监督/预测待校准，1A/1B/PC门槛仍未通过，见[总清单](../plans/MASTER-CHECKLIST.md)。LoRA与原始学习实践保留，学生ZIP/TODO不改。剩余20%保存停止，不使用重置卡；云端无实时余额接口，不声称当前额度。
