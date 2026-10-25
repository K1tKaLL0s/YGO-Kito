# Agent、训练收件与机器人覆盖审阅

2026-10-25，只读审阅起始提交 `9be766876a26c1b5692c87c196bf98b007c9051d`，起始工作树干净。本轮只新增本报告，不修改生产代码、配置或历史证据；未启动原生对局、worker、第三方程序或外部provider，也未执行故障实验。没有代替父任务合并、推送或核定最新CI。

本地非LLM基线的收件、分期加载、训练控制与完整边界恢复已有真实接口，并非仅DTO或provider占位。审阅期间父任务正在修正组评估的两处具体接线问题，见下文；不能据接口存在声称起始提交无缺陷。本报告不是全仓库正确性证明或能力验收。当前可用代码、资源整理导入、训练入口和恢复交接，与后续腾讯云训练实测分开；GPU锁安装、硬件/性能调优、正式训练与能力验收属于第二阶段，PC产品归第三阶段，LLM和第三方WindBot运行均不是当前软件合并前置。

## 1. 核对的真实实现

| 范围 | 实际代码与行为 | 验证边界 |
| --- | --- | --- |
| 通用Agent协议 | `src/ygo_kito/agent_driver.py:172` 的StreamTransport与`:205`的Client传递UTF-8 JSON Lines；请求ID、响应ID和错误契约独立于厂商。`agent_bridge.py:26`固定宿主角色及方法白名单；`:107`声明provider未连接 | 本地参考客户端可调用，不代表CodeBuddy、DeepSeek或其他外部模型端到端连接。`coding.prepare_handoff`是另一个可选准备功能，不是本地训练依赖 |
| 训练接入 | `cli.py:505`只有宿主显式trainer角色和`--local-cpu-control`才建立LocalCpuBackend；RPC不能提交shell、任意配置路径或切换provider/设备。`agent_bridge.py:154`prepare，`:159`recover，`:235`control | 默认关闭后端；能力发现不自动开启训练。开关保留CPU旧名，group配方已有显式设备接口，未声称全部旧工具支持CUDA |
| 状态、重试、错误 | `agent_registry.py:184`用SQLite保存请求指纹、结果和唯一run/revision预留；丢失答复同ID同参数回读，换参数拒绝，未确定结果不自动重做。Bridge按revision和状态约束start/pause/resume/stop/save_checkpoint；failed须recover后resume | `training.prepare`不具有control的ID缓存语义；答复丢失应先查运行，不重新创建。角色是应用接口权限，不是可抵御同宿主任意Python代码的OS沙箱 |
| 3＋8收件 | `deck_intake.py:73`保留main-01..03及opponent-01..08，显式时期、JSON/YDK、控制类型与来源。`:174`重核卡库/发行清单/指定禁表节，`:215`逐牌表/逐期核区域、张数、别名合计限额与允许池 | 这是可调用解析/校验代码，不是只写DTO。空模板不会变正式牌表；缺来源/卡库/截止/控制字段则pending。`store_intake`只保存不可运行收件记录，不把登记成功当驱动接通 |
| 环境与加载 | `training_input.py:150`编译实际牌表、profile、来源摘要、双方驱动绑定和分区；`:295`加载时独立比对物理runtime。`period_host.py:139`接实际PeriodBuildAssets与已有规则/冻结CPU对手；`:208`确有snapshot分支 | 默认whole-plan验证完整三期/11槽；selected-period只验证选期，未选期不可访问。旧`environment.register/deck.import`兼容RPC仅认可当前精确custom runtime，历史训练走显式收件/宿主，不能靠改标签或null截止放行 |
| 隔离 | `training_input.py:196`按物理版本拒跨用途种子，`:209`按实际牌表内容＋驱动实现/版本＋模型拒跨train/validation/final_eval对手；`data_isolation.py:80/106/134`在冻结、入库及训练准入再次核查 | 换ID、调牌序或改card_pool标签不能制造独立样本。编译不虚构episode；保留语义课程DataAdmission及原PPO新鲜数据要求 |
| 恢复与指标 | `local_training.py:139/403`核验并恢复已提交边界；`group_runner.py:383/430/575/839`核源码/资源/配方、四模型/适配器/优化器、RNG、课程索引、台账与阶段谱系。`RunMonitor`从托管SQLite读权威状态，checkpoint读取只验字节 | 真正恢复不只验weights SHA；半局恢复不支持。旧CPU检查点不隐式转CUDA，源码绑定改变也不放宽。静态字节完整与可反序列化恢复分开，handoff额外拒绝空制品 |

分期宿主操作缓存只在单次同步操作内复用；每次命中/成功退出重读来源文件字节及路径、核对manifest/runtime/model封印，异常后清空。checkpoint、manifest、SQL发布前另有检查；不是跨操作长期信任旧文件。构筑改变actor时重新绑定对手/profile，避免把旧actor摘要继续当新数据证据。

指标中stage提交数、真实optimizer更新数、训练/验证episode、CPU时间、峰RSS、未测worker段和简单用量分别记录。`agent_driver.metric_gaps`把未采集指标保留unknown；`RunMonitor.checkpoint`的`integrity_verified`不等于训练可恢复。峰RSS不是进程树总和，启动耗时不是样本吞吐；本地pause/stop不代表腾讯云计费停止。以上边界不要求当前开发先做第二阶段GPU实测。

审阅收尾看到父任务在`group_runner.evaluate`的并行修正，属于现有接口内的必要正确性修复：

- **多对手触发**：原实现自行保存forecast前的scope及轮换下标；账本会规范化对手排序，并按种子加权租用对手。多对手输入可能因scope排序不等而拒绝，或实际adapter与租用对手不一致。最小修正是采用登记返回的规范scope，按租用的opponent ID/牌表/实际driver身份唯一解析分期cursor，再核对采样adapter；保留原验证seed和policy seed。
- **强制重构触发**：继承mandatory_rebuild的已修改子候选若仍用`engineering_validation`调度，会被原账本正确拒绝。最小修正是此路径使用`rebuild_validation`，无已修改子候选则拒绝；不能清除旧预警或改名重置历史。

本轮只读检查了该修正差异及对应CPU契约测试代码，没有修改它或执行新group测试。下面74项不包含`tests.test_group_runner`，不能充当上述并行修正的验收；最终提交及相应测试/CI由父任务统一核对。这是具体接线问题，不引入新的模型泛化或GPU前置。

## 2. 本轮检查与既有证据分层

本轮独立运行以下明确CPU模块，**74项通过，3.259秒，退出0，无失败/错误/跳过**：

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .cache/ci-cpu-venv/bin/python -m unittest \
  tests.test_agent_contract tests.test_agent_lifecycle \
  tests.test_deck_intake tests.test_training_input -q
```

Agent lifecycle的实际stdio/重连/去重/错误测试使用显式`FixtureLifecycleBackend`和`source=local_contract_fixture`，checkpoint是惰性测试字节，不启动训练。收件/输入测试使用明示合成卡库、发行资料及runtime，覆盖拒绝缺失、未来截止、环境错配和跨分区；不能称为真实历史卡池或用户卡组通过。

另只读核对既有证据，未重跑，也不将其旧提交扩大为当前head的全量验证：

| 保存的实际检查 | 原范围/版本 | 本报告采用的结论 |
| --- | --- | --- |
| [普通引擎与训练恢复汇总](2026-10-24-pretraining-evidence/normal-results.json) | 6d23fc9：23项真实正常核心、15项实际CPU训练恢复；82fdfde：普通group 2项、分期group 3项 | 当时真实代码确有采样、参数更新、冻结评估和完整边界恢复，不是lifecycle fixture；不能据旧记录声称当前head全量重验 |
| [分期冻结CPU正常检查](2026-10-24-period-opponent-evidence/period-snapshot-normal-results.json) | 4项通过、36.365秒；两期共2次自然终局、2次私有重放、2次actor重绑开局 | actor为已有PublicRulePolicy，对手为实际更新过的同一冻结CPU base模型；该检查自身0次训练更新，未恢复旧训练器 |
| [2022-07 proof](2026-10-24-period-opponent-evidence/period-snapshot-2022-07-proof.json)、[2022-10 proof](2026-10-24-period-opponent-evidence/period-snapshot-2022-10-proof.json) | 工程发行清单截止09-30、12-31；精确period/profile/model/driver/resources scope | 本轮重新计算两份summary摘要均匹配，7个passed均true。这里只核保存证明完整性，不是本轮重新执行native |

两份proof的模型SHA为`44e318f4563cc13c15dce1ebb7d9c0966a2beb1fcb5c0ee05164418d39b732e7`，源group制品SHA为`ac8f1a048a9cf9b01a5f544944b5fa4663338aa54f00a7688f121ef99ad21863`。提取的是完成1次更新的`components.duel` base组件，不是最新LoRA或成熟策略。`source_checkpoint_restore`指显式冻结推理模型/词表重载，不代表跨源码训练optimizer/RNG恢复。初次未训练actor的采样耗尽失败仍保留；后续规则actor成功没有删除该失败或证明模型强度。

## 3. 当前可执行对手与第三方目录的区别

| 对手/准备层 | 当前可执行性 | 已保存证据 |
| --- | --- | --- |
| `visible-effects-first-v1`、`visible-effects-last-option-v1` | 本地PublicRulePolicy、FrozenOpponent及PeriodRuleOpponent有真实实现，无LLM依赖 | 普通与分期实际对局；两者主要共享启发式，后者在MSG14选末项，不是两套成熟主题bot |
| `frozen-duel-greedy-v1` | PublicSnapshotPolicy与PeriodSnapshotOpponent实际加载明确SHA的本项目CPU权重，eval/no_grad且核资源/词表/来源/边界；没有合适权重时拒绝 | 上述两期正常proof；模型1步更新不代表强度，通过仅适用于精确scope |
| WindBot 63条`deck_executor`记录 | **未构建、未桥接本工程core、未运行**；包含通用源码，不是63个成熟bot | 固定源码路径/Git blob清单；配对样例只按basename目录证据 |
| `YGOFTKExternal` | `external_policy_only`，未运行外部进程或provider | .NET Framework4.8/x86及ExternalPolicyOnly条件仅静态读取；与完整Executor构建不是同一集合 |
| `PreparedIndexWindow` | 纯DTO索引→当前合法action_id的可调用准备层；不调用provider或native响应，状态`prepared_not_connected` | 明确state/request绑定、索引和匿名信息边界测试；不是upstream wire或外部连接成功证明 |

第三方固定源为`mellfy-puppy/ygo-tools-for-dsh@ab963c1cb9776bea4262ae1bba38f541ec70e357`。本轮只读仓库已保存的[64源/62YDK清单](../../configs/windbot-source-inventory-v1.json)、[6样例来源索引](../../configs/historical-listing-sources-v1.json)、[逐期审计摘要](2026-10-24-historical-listing-summary.json)及[1152行矩阵聚合](2026-10-24-static-windbot-coverage.json)，没有下载、编译或执行第三方代码。

当前inventory规范JSON摘要为`6779aaf029752d20d9574d64cd275c8666c2b8cebb7f14645f2e668f1ea9e267`，与矩阵的`driver_inventory_sha256`相符；文件原字节SHA另为`6faf7bf5edeeb711ec8d87aee40af45ea9e1f027c6b42d2b277d1c40c274ab52`，两者口径不同。64条记录中63条deck_executor、1条external_policy_only；62条有唯一basename配对YDK，DoEveryThing/Lucky无配对。完整清单保留每项实际路径和Git blob SHA，不以文件名推断历史热度或可执行强度。

父任务如需挑选8个**后续核验候选**，可从以下61个有YDK配对的deck_executor目录名中选择；这是完整目录投影，不是推荐八套或已核历史主流，也不写入用户opponent-01..08：

| 目录范围 | 实际driver_id |
| --- | --- |
| A–D | Albaz、Altergeist、Apophis、Archfiend、BE2025、Blackwing、BlueEyes、BlueEyesMaxDragon、Brave、Burn、ChainBurn、CyberDragon、DarkMagician、Dogmatika、Dragun、Dragunity |
| E–L | Evilswarm、Exosister、FamiliarPossessed、Frog、Gravekeeper、Graydle、GrenMajuThunderBoarder、Horus、Kashtira、Labrynth、Level8、Lightsworn、LightswornShaddoldinosour |
| M–R | Maliss、MalissOCG、MathMech、MokeyMokey、MokeyMokeyKing、Neko、Nekroz、OldSchool、Orcust、Phantasm、PureWinds、Qliphort、Rainbow、Rank5、Ryzeal |
| S–Z | ST1732、SacredBeast、Salamangreat、SkyStriker、SuperheavySamurai、Swordsoul、Tearlaments、ThunderDragon、TimeThief、ToadallyAwesome、Trickstar、Witchcraft、Yosenju、Yubel、Zefra、ZexalWeapons、Zoodiac |

此外1份配对YDK属于YGOFTKExternal，不归入上述deck_executor候选；DoEveryThing/Lucky仅有源码记录。61＋1＋2＝64条源记录，配对文件数61＋1＝62。只有下列6份YDK已实际读入逐期列表审计，其余配对YDK没有本工程逐卡/逐期审计，不能视为同等资料已整理。

此清单**只覆盖dsh固定旧副本，不是整个WindBot生态**。父任务另只读提供的新线索单列为上游候选：`IceYGO/windbot@dec0535f8669dca01457a898890a968139711b19`有`ChaosRitualExecutor.cs`（光与暗之仪式，不是光暗龙）；`YGOMobile@6207d220dd5c027ec97e4b400ac60ef50eaf1bd3`的`mobile/assets/data/conf/bot.conf`列有ChaosRitual与Elfnote（耀圣）。这些未纳入上述旧64源/62YDK/1152矩阵，本轮也未独立下载、编译或执行，不能把旧副本缺文件推广成“没有现成bot”。候选选择可先保留纯轴基准；巳剑光暗等混轴或战报存在不证明优于纯轴，本报告不据此替用户决定八套。

下表**只报告该轮指定社区禁表节的数量限额**；每份样例当时发行记录均未知，任何“未拒绝”都不表示该时期已经发行、历史合法或可由该Executor正确操作。

| 固定来源样例 | 2022.7限额 | 2022.10限额 | 2026.10限额 |
| --- | --- | --- | --- |
| Tearlaments | 未拒绝 | 拒绝 | 拒绝 |
| Albaz | 拒绝 | 拒绝 | 拒绝 |
| Labrynth | 未拒绝 | 未拒绝 | 拒绝 |
| Horus | 未拒绝 | 未拒绝 | 未拒绝 |
| Swordsoul | 未拒绝 | 未拒绝 | 拒绝 |
| Kashtira | 未拒绝 | 未拒绝 | 拒绝 |

旧矩阵为3期×6样例×64驱动＝1152行：576未核、192静态拒绝、384截止未定阻塞，**第三方1152行全部not_run、normal_operational/operation_qualified/strength_qualified均未通过**。两个本地Python冻结模型proof单列为local_operational_references，不应用于任何WindBot行。旧审计的2026 cutoff是null；本次日期选择不改写该原始结果或将它称为11月1日卡池审计。

## 4. 日期、数据接续与具体限制

当前用户已选2026期截止2026-11-01，含日本当地JST当日正式OCG发售；禁表仍2026-10-01生效/2026.10。本轮只读调用`cutoff_timing`实际返回`as_of_date=2026-10-25`、`cutoff_selected=true`、`cutoff_reached=false`、`final_card_pool_verified=false`、`status=awaiting_cutoff_date`。日期选择与最终池分开，11月1日当日及之后依实际正式发行/可信来源核对；不提前放行，不创建自动任务。

可靠社区资料可用于整理与交叉核验，正式结论保留可信依据和未知项，不把官方原HTML作为唯一数据来源。百鸽本轮仅有[局部来源审阅](2026-10-25-baige-source-review.md)；公开卡文/announcement可staging，不能等同正式OCG release_date或available_in_period，TCG先售也不能替代OCG日期。完整历史资料由既定数据工作线另取，本报告不重复访问受拒路径、不宣称全库已导入。

| 触发条件 | 当前真实行为 | 接续方式及是否构成当前必修代码缺口 |
| --- | --- | --- |
| 用户尚未提供3＋8或所选期资料不齐 | pending/明确拒绝，不制造正式牌表 | 用户实收后用现有收件/编译/宿主接口导入；本轮未发现因此缺少解析或连接接口 |
| 选择bot/external_llm作为分期实际对手 | `period_host.py:217`拒绝，未回退规则或冻结模型 | 只有启用该可选路径才需真实合法动作传输/固定实现接线；不是本地基线或当前软件合并的硬前置 |
| 将旧CPU/旧源码训练checkpoint直接用于新CUDA/新实现 | 设备/实现/资源/阶段绑定不符时拒绝 | 保留原源码复现；现有显式snapshot迁移只推理，不冒充训练恢复。没有在本报告中绕过绑定或新增迁移要求 |
| 实收卡组涉及现有不支持的机制/目标 | 原接口应明确unsupported/unknown或拒绝 | 届时按具体触发定位最小适配，不以一般机制/竞技泛化全部完成另设当前软件门槛；现有有限proof也不能预先保证该牌组能力 |

父任务可据当前实现和相应最新测试/CI分别审阅后，按已授权PR1→PR2→PR3流程处理；本报告没有执行合并，也不将GPU实测、付费训练、PC、可选provider或第三方bot资格追加为软件merge门槛。
