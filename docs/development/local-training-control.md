# 本地训练控制与本轮整体验收

新增[四模型交替运行器](four-model-runner.md)：在[决斗多轮](../reports/2026-10-23-multiround-runner.md)基础上接入目标/优化/决斗/统筹及四角色LoRA、逐阶段检查点、冻结评估/反馈和累计预算核对。当前仅工程条件路线/弱代理/合成统筹课程，阶段1与正式ready继续未通过。

[交付表与证据](../reports/2026-10-23-engineering-delivery.md)按统一说明区分已完成的最小工程链、后续必需工程、能力验收和外部依赖。**本命令成功不代表完整阶段1A/1B或正式训练通过**；输出保留full_phase_1_delivered=false、formal_training_ready=false。

当前软件开发完成按可调用代码、资源整理导入、训练入口与恢复交接验收；用户提供卡组后进入腾讯云第二阶段。GPU锁安装、实机性能调优、正式训练及能力验收属于第二阶段，不是当前开发前置；此前将它们混作软件开发阻碍的表述有误。PC产品与可选provider也不阻塞本地非LLM基线。

## 一条命令重现本轮支持范围

    .venv/bin/python -m ygo_kito engineering-acceptance \
      --root .cache --state-root .cache/engineering-delivery \
      --run-id UNIQUE-DELIVERY-ID

run-id须唯一且≤24字符，已有目录拒绝覆盖。该命令实际执行CPU预检、固定真实引擎、四模型更新与LoRA组恢复、JSON本地训练控制、受控子进程故障/恢复、时间上限、隐藏信息和版本负测，最后登记CPU用量。CLI有180秒Unix内核计时上限；没有下载、账户登录、外部provider或云实例操作。它会有意终止自己启动的测试采样进程，故障注入在证明中明确标记。

工程卡组、弱代理/合成统筹监督和少量真实对局不能当能力达标；用户3＋8套、通用卡池、正式BO3、LoRA迁移、PC和CodeBuddy/DeepSeek实际联调另验。既有原件/学习ZIP/TODO不改写。

## 显式启用真实CPU后端

默认agent入口继续关闭训练后端。可信宿主可启用固定trainer角色：

    .venv/bin/python -m ygo_kito agent-serve \
      --root .cache --state-root .cache/local-training \
      --role trainer --local-cpu-control

也可逐次使用agent-call INPUT.json与相同参数；worker独立存活，有自己的内核计时器。monitor不用该启用标志；opponent带该标志会被拒绝。不传配方时保留原决斗CPU两次更新冒烟路径；可信宿主可启用配置驱动的多轮路径：

    .venv/bin/python -m ygo_kito agent-serve \
      --root .cache --state-root .cache/local-training \
      --role trainer --local-cpu-control \
      --local-training-config configs/cpu-runner-v1.json

配方由宿主CLI加载，JSON工具请求仍只收run_id及白名单操作，不能传shell、可执行文件、GPU或任意配置路径。cpu-runner-v1仅支持决斗；改用configs/group-runner-v1.json可启用[四模型CPU周期](four-model-runner.md)，保留同一权限/控制/监控入口。它已支持工程课程的可配置周期，不宣称一般构筑/三期大数据或100h吞吐已验。

各请求严格采用schema_version/id/method/params：

    {"schema_version":1,"id":"prepare-1","method":"training.prepare","params":{"run_id":"my-cpu-run"}}

prepare实际核验固定资产、建立独立CPU模型并保存initial检查点，状态created、steps0；没有把初始化权重算成训练更新。同run-id拒绝覆盖；响应丢失先读取已有状态，不重新创建。

    {"schema_version":1,"id":"read-1","method":"runs.read","params":{"run_id":"my-cpu-run"}}
    {"schema_version":1,"id":"start-1","method":"training.control","params":{"run_id":"my-cpu-run","operation":"start","expected_revision":0}}

之后每次先读取当前revision，操作可为start/pause/resume/stop/save_checkpoint。worker进度也会增加revision；不得硬编码后续版本或在旧版本上盲试。同请求ID/同参数的control结果持久幂等，冲突拒绝；已保留为uncertain的操作先查状态和检查点，不能自动重试。

## 操作的实际含义

| 操作 | 实际行为与边界 |
| --- | --- |
| start | 重新验证配方/代码/资源/初始检查点，原子校验revision及单worker额度，启动固定项目模块子进程 |
| pause | 请求在完整对局/更新/检查点边界退出worker；首次采样前可停在step0，示范流程实际停在step1。长时间无响应时仅对匹配PID起始时间/模块/运行ID/代次的本项目进程发信号，回到最后已登记检查点 |
| save_checkpoint | 暂停时重新保存已验证完整模型/优化器/调度器/RNG/游标；运行时等待下一真实边界，未保存不宣称成功 |
| resume | 只允许paused；在新进程实际加载完整检查点并从下一采样继续，不复用历史rollout作新PPO数据 |
| stop | 结束该本地worker，保留最后检查点和实际状态；返回scope=managed-local-cpu及cloud_billing_stopped=false |

每个state-root最多一个活跃受控worker。默认冒烟为2次更新；新配方显式指定max_updates、validate_every、checkpoint_every、wall_seconds、CPU模型配置、训练种子游标以及验证种子/对手/卡组。配置支持1～100000轮并严格限制有限预算，当前仅短CPU运行通过实测，未验证100h吞吐或全部协议。训练配方及资源绑定不能通过请求改写。Linux进程身份检查及应用角色不构成对文件系统管理员的隔离；外部opponent仍不能得到Bash/文件/进程或trainer工具。

## 多轮、验证与数据用途

默认新配方是4轮：每轮真实核心完成一局、从当前策略的本席位轨迹实际PPO更新；第2/4轮各验证一局并标记定期检查点。每轮都会保存恢复检查点，checkpoint_every控制定期保留标记，**没有减少实际写盘次数**。暂停/停止在完整轮次（含该轮验证）边界生效，异常时回到已提交边界。

训练使用visible-effects-first-v1；验证冻结为visible-effects-last-option-v1，其选项提示14实际选末项，另保留不同卡组张数变体及不重叠种子。对手版本摘要包含实际驱动选择、牌表、代码与资源；改名或重排同一牌表不能充当独立构筑。两者都是弱工程协议代理，未经合格对手/强度验收。验证仅推理，检查模型、训练游标及policy/batch/Torch/Python RNG没有变化；验证结果不触发更新或自动晋升。

data/train与data/validation分别保存完整本席位轨迹分片，只有合法玩家DTO及动作/价值/奖励标签；context.seed为空，隐藏身份/攻防为空或省略，不含对手私有请求、完整卡组顺序或原生审计。种子、版本、终局与文件哈希只进入控制器轮次清单。持久分片供审计，**恢复后不从分片继续PPO**；只加载权重/优化器/调度器/RNG/游标，然后重新调用真实核心采样，拒绝验证/旧版本/已消费episode。

这是工程train/validation隔离；还没有三期完整数据分片、一般构筑监督划分、资格对手池或独立BO3终验集。固定验证种子可多次评估，不称为独立终验。

可重复短验收（run-id唯一）：

    .venv/bin/python -m ygo_kito cpu-runner-acceptance \
      --root .cache --state-root .cache/runner-delivery \
      --run-id UNIQUE-RUNNER-ID

命令只接受3～8轮/每运行≤180秒的短验收配方，并有意终止自建验证worker一次。它与不间断运行比较实际参数、更新、RNG和验证轨迹，检查预算边界及用量幂等，保存experiments/ID/proof.json；不是正式100h训练。

## 故障与时间预算

崩溃后不能直接resume，先检查状态、再显式恢复：

    {"schema_version":1,"id":"recover-1","method":"training.recover","params":{"run_id":"my-cpu-run","expected_revision":CURRENT_REVISION}}

recover要求已退出的failed任务，核验长度/SHA、基模/特征/实现/资源版本、优化器/RNG/游标及配方。新运行器只采纳下一检查点、轮次清单、训练分片及所需验证分片都完整且绑定一致的未登记轮次；缺少完整发布则隔离检查点/清单，已声称完整却数据或版本校验不符时拒绝恢复。恢复前也验证最后已提交轮次的数据/谱系。强制中断的新运行器pause保留failed，必须显式recover。不能凭文件名或metadata重造成功更新，恢复后paused再用新版本resume。

本地active墙钟预算含初始化及各worker活动段，暂停后的等待不计活跃训练；原冒烟默认60秒，新配方默认180秒。宿主可在配方声明有限上限（最大360000秒），此配置能力不授权启动100h任务；当前只运行短CPU验证。运行器在开始新轮前预留整局及该轮验证的最大时长，不足则在已提交边界停止。每个worker仍用Unix ITIMER_REAL配合SIG_DFL设置内核期限，包括意外阻塞的C++；见[Python官方说明](https://docs.python.org/3.12/library/signal.html)。超限保留检查点，未完成采样不伪造终局/训练更新。

进程异常退出时活动墙钟保守按观察到的上界扣预算，未知的子进程CPU段以unmeasured_worker_segments标记，不填假精确值。epoch中途/原生半局状态未保存；从完整边界恢复会重做未登记工作。主进程和子进程分别采集资源，单进程峰值不能当进程树合计峰值。

新运行器把初始化和每个worker代次的用量先写入控制SQL的usage_outbox，再登记state-root/cpu-usage.sqlite3。事件ID稳定，回读台账后才处理丢失确认；同段重复查询/恢复不重复登记，新代次重新采样的实际耗时照记。CPU墙钟单列、gpu_count=0、金额未知，未声称免费或核实计费；包含验证/保存的worker活动段统一计入train活动，原始outbox保留测量/上界来源。100 GPU小时及5/25/25/20/10/15规划保持不变，CPU秒数不冒充GPU小时。跨机器/重启的资源租约与云计费仍未实现。

**本地worker退出、暂停或180秒命令期限都不证明腾讯云计费停止。** 没有CVM生命周期API、实际计费核验或云停机确认；未获具体采购/执行授权及对应训练门槛未过时，仍不启动付费训练。PC产品P-01属于后续阶段3，不作为腾讯云headless基线前置；实际规则资源兼容仍独立检查。

## 监控与交接

managed任务的SQLite记录是状态权威；status.json只保留初始兼容入口，勿以直接读该旧文件代替runs.read/runs.metrics。monitor始终只读且不加载Torch/权重、不调用LLM；checkpoints.read核验登记文件字节/SHA。私有配方、种子/审计与worker日志不作为玩家输入；对手角色不能读取runs或训练控制。

CodeBuddy目标环境仍须实际核查CLI/SDK、模型、额度、权限回调与隔离；500 credit不能当通用免费API。用户工程后提供3＋8套，8个对手槽预留DeepSeek操控计划，由我们导入/绑定；真实provider尚未接通，不阻塞本地规则/冻结模型基线。按实际来源盘点机器人能力与三期覆盖，不因文件存在而宣称可用。接手优先读[当前训练交接](training-handoff.md)；[LoRA/腾讯云指南](lora-and-cloud-handoff.md)保留原工程范围。

剩余20%保存停止、确认重置后才继续，不使用重置卡。当前没有实时额度读取器，active秒数/100 GPU小时规划都不是Codex余额。手机暂缓，LLM非核心，Python亲手学习仍由用户实践。
