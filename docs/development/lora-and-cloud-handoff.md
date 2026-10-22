# LoRA 生命周期切片与腾讯云受限交接

依据[统一说明](../plans/2026-10-22-unified-development-spec.md)第9、11、13节；当前只验证小型工程基模上的适配器生命周期，不声称已经训练出可迁移的竞技基模。[M3d报告](../reports/2026-10-23-lora-handoff-m3d.md)提供实际参数更新、真实对局、资源与恢复证据。LoRA仍为基模后的常规持续适配路线，外部LLM不是核心模型。

## 先澄清百场/千场数字

M3c的25场提示、125场强制，是对“预测0.9、连续失败”的**合成记录**应用工程判定后，实际出现的首次触发位置。没有把百/千场缩成25/125，也没有将25/125写成固定触发门槛。

CPU工程命令默认的反馈文件仍为 coordinator-feedback-engineering.json：完整检查点25/50/75/100/125/250/500/750/1000，margin0.10、family_alpha0.05、draw_score0，calibration=pending。25是工程最小检查样本，125是百场之后的首个预设检查点；是否触发取决于数据和不确定性。

正式设计保留“百场内明显偏低提示、千场内明显偏低强制”，并保留多次观察控制及预测/谱系不可任意重置。**当前没有正式训练的已校准默认统计方案**；正式配置依赖Q-04/E-01，不自动引用工程默认值作为正式验收设置。统计条件及来源见[统筹指南](coordinator-model-group.md)。

## 实际适配器与兼容边界

实现位于[lora.py](../../src/ygo_kito/lora.py)，使用PyTorch权重参数化，对选定Linear应用 W + (alpha/r) B A。基模所有参数（包括embedding、bias、LayerNorm）冻结并清除梯度，只给A/B建立独立AdamW和调度器；每次更新前后重新核对完整基模哈希和无梯度条件。A随机初始化、B为零，初始输出保持基模；第一步A梯度可能为零，不把未变化的参数算成变化。

采用[LoRA原论文](https://arxiv.org/abs/2106.09685)的低秩增量思路，使用[本环境PyTorch 2.14参数化接口](https://docs.pytorch.org/docs/2.14/generated/torch.nn.utils.parametrize.register_parametrization.html)保证实际读取Linear.weight的Transformer路径也得到适配权重。未安装PEFT、下载外部权重、使用量化或合并基模；不能援引合并后的零额外延迟结论，当前开销按实际流程测量。

[工程配置](../../configs/lora-engineering-v1.json)给四角色分别指定适配器ID、Linear路径、rank4、alpha8和两次更新预算。目标/优化各1,024个可训练适配参数，决斗1,408，统筹340。FFN及部分输出投影是本次实验位置；目标层、秩、精度仍属Q-01待小试参数，不是最终模型决定。

保存/加载绑定：

- 精确基模SHA及显式base_version，角色、特征版本、目标层名/形状、rank/alpha与配置。
- 任务/规则/卡池/禁表/词表来源、实现和监督上下文的摘要；规则或卡库更新不能静默沿用旧绑定。
- A/B、独立优化器/调度器、RNG、更新游标及启用状态。独立适配文件不包含基模权重，需另外取得正确基模。
- 文件字节数/SHA、内部张量摘要、shape/dtype/有限性校验；加载使用weights_only=True。拒绝错误基模、角色、版本、上下文、目标、损坏文件及重复挂载，不隐式叠加。

AdapterSession.set_enabled(False)用于暂时停用，实测输出精确回到基模；unload移除参数化并核对完整基模SHA。版本切换必须明确卸载再加载相容文件；不原位改写旧适配文件，不承诺任意组合/合并有效。应用角色检查不是文件系统隔离，外部对手不能读取基模/适配文件。

## 模型组真实工程流程

    .venv/bin/python -m ygo_kito lora-group-cpu \
      --root .cache --state-root .cache/lora-group \
      --run-id UNIQUE-RUN-ID \
      --task configs/build-engineering-v1.json \
      --lora-config configs/lora-engineering-v1.json \
      --feedback-policy configs/coordinator-feedback-engineering.json

命令先用现有模型组流程建立有实际更新和恢复证据的工程基模，再冻结四基模，各更新适配器两次。目标用真实条件路线/明确张数失败，优化用明示印刷攻击力弱代理，统筹用明示合成规则/概率锚点，均不改成能力标签。

决斗适配使用**一局新采样的当前策略真实轨迹，进行两个有界PPO epoch**；不是两次独立新采样，也不混入旧策略/LLM轨迹。该采样器有独立策略RNG/游标，基模训练游标和优化状态保持不变；更新后冻结适配器。当前不支持PPO两epoch中途的原生/半批恢复。

适配后的目标→优化→目标→优化实际运行四阶段并真实重验，日志包含适配版本。若输出卡表没变，复用原已验证候选，不靠新ID重置历史；若变更，保留父谱系并重新托付。旧基模评价计数保留；适配策略以新的策略SHA/duel_lora版本登记新预测层。模型头概率仍未校准，一局输赢不用于宣称迁移增益。

模型组checkpoint schema2包含原基模完整状态、四适配器训练状态、RNG/游标及SQLite谱系快照。保存时只暂时卸载参数化以复用基模写入器，随后重新挂回原A/B；不会把增量永久合入基模。恢复须提供四角色的预期兼容清单，缺失时拒绝，不静默当作基模运行。实际验证器还要求显式传入活跃决斗适配器，校验其版本与冻结预测一致。

组保存边界仍是pending、未领取的验证任务；恢复到新目录后实际重跑真实对局，对照轨迹/结果/适配版本/台账一致。独立适配器另有实际保存→加载→下一更新一致的CPU测试。半局、多机、正式预算、旧任务退化与陌生牌组学习能力仍待验。

## 无凭据CPU预检与正式训练计划

    .venv/bin/python -m ygo_kito training-preflight \
      --root .cache --plan configs/training-plan-v1.json

预检实际执行CPU张量前向/反向、临时SQLite事务回滚、固定原生资产哈希核对，并报告Python/工具链存在性、CPU/磁盘、CodeBuddy可执行文件是否存在。没有凭据读取、登录、CLI/SDK调用、网络请求或资源启动；资产校验本身不冒充真实对局。缺资产时输出对应健康检查失败、退出2，不创建假训练或下载资源。

CPU预检成功退出0，仅表示这些本地检查通过。formal_training.ready始终false，本命令不验证/放行G-01/G-02/P-01等完整门槛。正式计划保存既定100 GPU实例小时上限，初始5/25/25/20/10/15分配；机型、GPU数、价格/币种、API费用上限和三期数据清单保持待定，paid_execution_authorized=false。将此字段改true会被当前规划接口拒绝，而不是绕过授权。

到新环境后先使用已审查源码、固定依赖/引擎锁和明确准备步骤恢复资源，再运行预检。历史checkpoint需使用其绑定的源码/资源，不能修改摘要来强行加载。当前缓存权重路径只是本云端位置；没有宣称已传输到腾讯云或提供用户下载链接。

## 实例小时台账与受控入口

    .venv/bin/python -m ygo_kito budget-call REQUEST.json \
      --ledger PATH/usage.sqlite3 --plan configs/training-plan-v1.json \
      --role monitor

可信宿主首次使用trainer及--create建账；source固定为host_reported_unverified或单独的synthetic_contract_test。monitor只能status/history/budget.check，trainer另可usage.record；未知启动/停止方法拒绝。请求使用schema_version/id/method/params，与既有JSON工具风格一致。

usage.record字段为event_id、stage_id、gpu_count、wall_seconds、activity、outcome、amount、currency、expected_revision。安装、下载、空转、训练、评测、checkpoint和等待停机确认均按**GPU数量×墙钟/3600**计入；失败/超时不能折扣或删除。GPU数0只登记CPU墙钟，不占GPU小时；CPU费用仍未知，不能写成免费。金额用十进制字符串或null、币种明确，按币种分别汇总，billing_verified始终false。

不可变计划/source、原子版本检查、事件幂等/冲突拒绝和超额记录保留均有测试。已超支的真实报告照记，后续admission返回不满足预算，不能为美化余量丢弃超支。budget.check仅是对已登记用量的估算，**不是并发资源预留、采购授权、云计费核验或自动停机控制器**；所有返回都execution_authorized=false。

台账的100h规划余量不是腾讯云账户余额，也不是Codex额度。正式API费用封顶、实时采集、资源租约/看门狗和云端停机确认仍待可信宿主接入。training.control后端仍未配置，本次没有让外部agent通过该工具启动任何训练。

## CodeBuddy接手与八个外部对手

当前云端没有CodeBuddy可执行程序，未验证DeepSeek模型、SDK、账号配额或外部端到端，也未配置凭据。[Cloud Studio官方页](https://cloud.tencent.com/document/product/1039/131814)描述该产品内置终端工具及每月500 credit，不能据此推断任意CVM同样自带、SDK共享额度或DeepSeek通用API免费。[SDK入口](https://www.codebuddy.ai/docs/cli/sdk)提供权限/自定义工具文档索引；本批模型/权限子页后续抓取502，实际目标版本须复核，不依赖未核实的SDK参数。

接手顺序：

1. 在目标环境只读核查codebuddy -V/-h、实际可用模型与配额/计费。当前没有可用模型ID，不填写猜测的DeepSeek版本，不自动切换独立API或付费后备端点。
2. 阅读统一稿、MASTER-CHECKLIST及本批报告，确认工作分支和实际head。先运行CPU预检/测试，保留学生ZIP/TODO；每批更新稳定ID及证据，普通向前提交至PR #1，不合并/强推。
3. 编码agent可在明确授权仓库内改代码/测试，但不获得云采购、账户权限或重置卡操作。监控使用固定monitor工具，确定性采集和只读摘要不必每次调用LLM；训练操作仍须后续可信后端和实际权限回调验证。
4. 对手agent用独立固定opponent会话，只取得该席位合法观察及state_version/action_id提交工具；不给Bash、文件、进程、manager/trainer/统筹台账。SDK工具白名单和OS/进程隔离须实际验证，不能仅凭--role宣称安全隔离完成。
5. 用户工程完成后提供3＋8套，由我们导入/检查/绑定三期卡池禁表并分配，8套拟交DeepSeek；当前未收到、不伪造、也不阻塞工程。真实模型/合法性/超时回退/费用与强度分别核验，未通过前不将注册对手算作training_ready。
6. 主动盘点已有机器人实际支持/可用性/卡表适配/强度，对照三期历史环境覆盖后建议补充主题及优先级；文件存在不是可用证据。保留无外部API的基础对手路径。

剩余20%时保存停止，不使用重置卡；当前工具没有实时额度读数，必须由经核实的宿主/人工读数驱动，不能把预算台账当额度监控器。未过PC/数据/模型门槛、缺具体采购授权时不启动腾讯云或付费训练。外部真实联调、PC兼容/压力与正式迁移验收明确留后，不扩本轮为PC应用。
