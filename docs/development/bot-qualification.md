# 机器人配套牌表及正常运行资格检查

`scripts/bot_qualification.py`统一检查固定完整源码注册表，不把目录存在、配套YDK合法、程序集构造成功或正常终局混为一项。无需先收到用户正式3＋8牌表；默认actor是已有native smoke的40张普通怪兽工程池，明确不是正式构筑，也不训练任何模型。

先按[机器人部署](maintained-bot-deployment.md)完成完整来源的fetch/install。下面仅查文件、卡表、限额与来源，不加载native库或启动C#：

```bash
PYTHONPATH=src python scripts/bot_qualification.py \
  --installed-root .cache/prepared-bot-sources --native-root .cache \
  --report .cache/bot-listing-plan.json
```

可用 `--actor-profile`明确选择已有测试profile、`--actor-seat`选择席位。报告不复制actor牌表，只记摘要；保留全部220条来源，147条原桌面配置和source-only库来源分别显示。原配YDK读取失败、未知卡、OCG身份、张数或别名合计限额问题均列明，拒绝项不删除、不自动改卡、不退回别的bot。该检查口径是锁定工程资源的2026.10节，不认证发行截止或历史规则；不能以某旧YDK在此被拒断言对应策略不可用。使用用户牌表的训练仍走原收件、分期宿主及实际profile绑定。

已准备[精确Monarch506变体](maintained-bot-deployment.md)时加 `--variant-root .cache/monarch506-overlay`。该库字节变体保留独立来源ID、完整Pure运行上下文与manifest，不计作原Pure同名实现已覆盖；矩阵会增加第148个桌面候选，但仍保留220条原来源。

只有获准工具链具备、完整程序集/资源/构造审计真实通过后，才显式选择实际正常对局。`--audits`文件形状为source ID→`{path,sha256}`；原来源key为`ice/pure`，变体另用`pure-with-library-monarch506-exact-v1`及其独立审计。以下命令不会自动安装工具或取得执行授权：

```bash
PYTHONPATH=src python scripts/bot_qualification.py \
  --installed-root .cache/prepared-bot-sources --native-root .cache \
  --audits .cache/actual-build-audits.json --mono /usr/bin/mono \
  --execute --bot-id REPLACE_WITH_EXACT_BOT_ID \
  --seconds 60 --max-decisions 3000 --report .cache/bot-normal-result.json
```

默认显式执行选择全部桌面候选；`--bot-id`可重复，未选项仍在报告内。生产入口只能调用实际 `BotSourceRegistry.training_adapter`，不接受room、策略、引擎或process-runner回调替代真实Executor。每个候选须保同一源、牌表、profile、资源和实现身份；失败注明audit gate、启动或正常对局阶段，不静默跳过。先独占预留报告并落盘“未完成”标记，再允许任何执行；已有报告不覆盖且零调用。日志/卡组原文不进入错误摘要，启动半途不明时保留`null`，不能写成已知未启动。

`seconds`同时传入自管C#会话watchdog，并由宿主在每个决策检查；不声称能硬中断正在执行的原生core调用。退出清理可能有短暂grace，不能拿CPU fixture当实机时限证明。只有真实core终局且至少一次由该bot作出合法选择，才记该行`normal_duel_verified:true`；所有所选项是否通过另有独立字段。过程不更新模型、训练索引或能力标签，历史合法性和强度始终未据此认证。

当前云端没有可用Mono；本轮只实际运行只读矩阵及明确CPU控制fixture，未调用`--execute`。原专项授权仍有效，系统权限和已配置签名源HTTP403阻碍仍按[实际回执](../reports/2026-10-25-bot-toolchain-block.json)处理，未重试或绕过。
