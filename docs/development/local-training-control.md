# 本地训练控制与本轮整体验收

[交付表与证据](../reports/2026-10-23-engineering-delivery.md)按统一说明区分已完成的最小工程链、后续必需工程、能力验收和外部依赖。**本命令成功不代表完整阶段1A/1B或正式训练通过**；输出保留full_phase_1_delivered=false、formal_training_ready=false。

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

也可逐次使用agent-call INPUT.json与相同参数；worker独立存活，有自己的内核计时器。monitor不用该启用标志；opponent带该标志会被拒绝。后端只支持当前固定的**决斗CPU两次更新配方**，不接受命令、可执行路径、GPU、模型下载或任意训练配置。通用四模型长期训练运行器仍属必需工程缺口。

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

每个state-root最多一个活跃受控worker，当前每运行最多2次真实完整对局更新。训练配方及资源绑定不可通过请求改写。Linux进程身份检查及应用角色不构成对文件系统管理员的隔离；外部opponent仍不能得到Bash/文件/进程或trainer工具。

## 故障与时间预算

崩溃后不能直接resume，先检查状态、再显式恢复：

    {"schema_version":1,"id":"recover-1","method":"training.recover","params":{"run_id":"my-cpu-run","expected_revision":CURRENT_REVISION}}

recover要求已退出的failed任务，核验长度/SHA、基模/特征/实现/资源版本、优化器/RNG/游标及配方。只有已完整保存但尚未登记的下一检查点，才在重新验证后登记；未发布完整文件的残留移入隔离目录保留证据；已声称完整却校验不符时拒绝恢复。不能凭文件名或metadata重造“成功更新”。恢复后paused，再用新版本resume。

本地active墙钟预算含初始化及各worker活动段，暂停进程退出后的等待不计活跃训练；默认60秒，可信Python宿主可在prepare时收紧到1～60秒，请求不能提高上限。每个worker用Unix ITIMER_REAL配合SIG_DFL设置内核期限，不依赖Python回调在C++返回后才能执行；见[Python官方说明](https://docs.python.org/3.12/library/signal.html)。超限保留已登记检查点、停止worker，未完成采样不伪造终局/训练更新。

进程异常退出时活动墙钟保守按观察到的上界扣预算，未知的子进程CPU段以unmeasured_worker_segments标记，不填假精确值。epoch中途/原生半局状态未保存；从完整边界恢复会重做未登记工作。主进程和子进程分别采集资源，单进程峰值不能当进程树合计峰值。

**本地worker退出、暂停或180秒命令期限都不证明腾讯云计费停止。** 没有CVM生命周期API、实际计费核验或云停机确认；未获具体采购授权且G-01/G-02/P-01等未过时，仍不启动付费训练。

## 监控与交接

managed任务的SQLite记录是状态权威；status.json只保留初始兼容入口，勿以直接读该旧文件代替runs.read/runs.metrics。monitor始终只读且不加载Torch/权重、不调用LLM；checkpoints.read核验登记文件字节/SHA。私有配方、种子/审计与worker日志不作为玩家输入；对手角色不能读取runs或训练控制。

CodeBuddy目标环境仍须实际核查CLI/SDK、模型、额度、权限回调与隔离；500 credit不能当通用免费API。用户工程后提供3＋8套，其中8套DeepSeek操控，由我们导入/绑定；后续主动盘点真实机器人能力与三期历史覆盖，不因文件存在而宣称可用。接手细节继承[LoRA/腾讯云指南](lora-and-cloud-handoff.md)。

剩余20%保存停止、确认重置后才继续，不使用重置卡。当前没有实时额度读取器，active秒数/100 GPU小时规划都不是Codex余额。手机暂缓，LLM非核心，Python亲手学习仍由用户实践。
