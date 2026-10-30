# YGO-Kito

**2026-10-30 source publication:** current code, scope and remaining limits are recorded in [the publication handoff](docs/development/publication-20261030.md). Training remains paused. Checkpoint and feedback archives are supplied separately; historical sections below describe their original delivery.


CPU接管与功能审计见[当前说明](docs/development/cpu-takeover-and-selfplay.md)：区分headless模型对战／对练和阶段3的GUI，沿用已确认慢档而不重新测时。新增冻结有效模型对手、独立自对抗历史池及仅热门主题的萌卡staging；正式训练仍需资产清单、资源／预算确认及用户通知。

本轮新增[实际自主课程与 BO3 入口](docs/development/scenario-course-runner.md)：复用四模型与有效 LoRA，提供目录候选／模型选择、构筑逻辑及 CB 核验、合法换备、逐小局更新、完整场计数、冻结评估和恢复。CPU 机制回归与历史真实模型对机器人终局分开记录；完整分期课程仍缺实际资产与资格，沿用用户确认慢档，不重新测时。草稿 [PR #4](https://github.com/K1tKaLL0s/YGO-Kito/pull/4) 不自动合并或训练。

游戏王 AI 项目的设计、资料与 CPU 开发仓库。

## 当前开发入口

**请先阅读 [统一开发说明与训练交付计划（2026-10-22，UTC+8）](docs/plans/2026-10-22-unified-development-spec.md)。** 本文承接《游戏王AI项目设计定稿.docx》1.0（2026-10-19），合并本轮逐项确认；明确更新处以统一说明为准，未更新的原定稿意图继续保留。原件不是实现完成证明。

**持续进度入口：[总工作清单 MASTER-CHECKLIST](docs/plans/MASTER-CHECKLIST.md)。** 每批完成后同步稳定任务 ID、状态和证据，符合验收条件才勾选；部分完成保持未勾选。该表索引全阶段进度，保留[第一阶段详细清单](docs/plans/2026-10-22-phase-1-cpu-checklist.md)，不替代统一规范。PR 已发布不表示已合并。

**工程基线已合并：[PR #1→#2→#3](https://github.com/K1tKaLL0s/YGO-Kito/pull/3)，main `7e92994d`。** 该main的517项CPU CI通过，作者分支保留。WindBot 在腾讯端已有特定 Executor 的真实终局，见 CloudStudio 来源报告；当前 Codex 容器仅源码齐全、没有 Mono／WindBot 可执行文件。新增[三环境训练准备](docs/development/autonomous-training-preparation.md)及[实际课程](docs/development/scenario-course-runner.md)单列2610自主课程与历史验收，不能将代码接线当作正式训练已就绪。已授权用户牌表接入见[收件说明](docs/development/user-deck-dataset.md)。本轮增量经独立草稿审查，不自动合并或训练。通用接续先读[AGENTS.md](AGENTS.md)和[Agent说明](docs/development/generic-agent-integration.md)。

**继续工程准备：[安全CPU CI](docs/development/safe-cpu-ci.md)、[3＋8牌表收件](docs/development/deck-intake.md)、[完整源码训练交接](docs/development/training-handoff.md)。** PR1→2→3已合入main；当前后续工程在[草稿PR #4](https://github.com/K1tKaLL0s/YGO-Kito/pull/4)。历史报告数字只适用原提交，不代替当前head检查。

**2026-10-24 独立新增：[构筑逻辑与非 LLM 入口](docs/development/construction-logic.md)。** 已补齐实际轻量可训练分类器、现有目标/优化模型的图候选选择与偏好训练、目录卡绑定及既有统筹连接。图由程序枚举、模型评分；小合成训练只验证代码，正式泛化和任意图合法 CB 未验，见[当前清单](docs/reports/2026-10-24-construction-trainable.md)。

- 模型组：决斗模型＋构筑目标/优化两个子模型，由轻量统筹模型和确定性程序包裹；三个执行模型独立小 Transformer，共享数据规范，不强制共享权重。
- 先训练基本模型组，LLM 后置且非必需。**LoRA 是基模后的常规持续适配路线**，不是旧文所说的完全可不开展。
- 开发与当前CPU接管准备使用云端Codex，原腾讯云A10结果按来源保留；100h总上限及原分配不自动扩大，CPU预算单位与长期任务宿主须明确。不重新测时，不自动授权付费或正式训练。
- 2207／2210保留珠泪主题，2610为自主主题／构筑／CB；目标→改进循环、合法可见信息和独立 BO3 验收保留，不用任意自弈替代常见卡组覆盖。
- 第一阶段交付可用代码、真实规则适配、资源导入、训练入口、恢复与交接；用户提供卡组后进入腾讯云第二阶段。GPU依赖安装、实测、调优与能力验收属于训练阶段，PC产品/客户端互操作归阶段3。**手机端及 YGOMobile 暂移出本期范围**。
- 构筑预测与实战反馈：百场内明显落后预警、千场内明显落后强制重构；具体统计阈值实施前冻结。

当前已有CPU骨架、固定上游源码构建的core、限定真实终局/重放，以及四个独立网络原型。历史v3完整公开卡库的决斗Transformer为266,018参数；v4匿名/卡名原型配置见[历史报告](docs/reports/2026-10-23-private-hierarchy-v4.md)，当前私有记忆特征已升v5，旧权重不静默兼容。原构筑词表的目标/优化各17,729参数，64卡工程词表各18,417参数；统筹MLP648参数。词表和实验大小不是最终容量冻结。已串通构筑托付、版本预测、冻结策略验证、回收及恢复；规则控制最终行为，统筹学习原型仍为明示合成监督。

本轮已发布[schema4长周期/真实CB/索引恢复](docs/reports/2026-10-23-schema4-course-and-cb.md)：四模型/LoRA课程、组合目标与同阶段SQL快照的代码/config已在用户明确批准静态工程配置后保存到[bb50555](https://github.com/K1tKaLL0s/YGO-Kito/commit/bb50555136c8d7bf40b7626a68ffb698587177e7)。[命令和边界](docs/development/schema4-course-and-cb.md)对应云端40d3e65受测源码；总清单T06-03/MG03-03/D08-02已按有界验收勾选，PR未合并，正式1A/1B/PC仍未通过。完整私有对局轨迹仍只留云端。

此前已发布[构筑语义、数据隔离与可执行对手](docs/reports/2026-10-23-semantic-indexed-opponents.md)新增schema4公开属性/主题计数约束与有限编辑、实际双构筑更新/恢复，及train/validation/final_eval索引准入。注册牌表含额外/副卡接真实核心，规则对手和冻结模型已实际对局/PPO/重放；不把注册或弱对手胜负当强度。固定源码MSG18多区无现成调用入口，版本限定分类与MSG24两种双区真实响应已闭合。[CPU命令](docs/development/semantic-indexed-opponents.md)仅导出共同公开历史/聚合证据，完整私有工件留云端。该发布版构筑特征为v4，旧权重不静默兼容；云端新特征版本及未发布状态见最新报告。

此前[合法私有记忆/盖放宿主v5](docs/reports/2026-10-23-private-knowledge-v5.md)补齐选定隐藏卡组MSG26、对方卡组确认后/洗切后选择及盖放宿主公共素材/真实破坏；该源163单元/155集成和独立7轨迹重放通过。[原CPU入口](docs/development/private-knowledge-v5.md)保留私有边界证据；当批MSG18多区无真实用例，本批补版本分类，仍不假称真实18多区。

此前[私有选择与完整候选分层v4](docs/reports/2026-10-23-private-hierarchy-v4.md)实现显式匿名／混合选择、全部14280合法卡名的神经分层决策及真实PPO/恢复；实际高位大数求和、控制交换和翻转召唤另有规则证据。[独立CPU入口](docs/development/private-selection-hierarchy.md)保存真实轨迹／收据，分开规范更新和恢复对照；完整回归与边界按源记录，不把工程前缀当模型能力。这些原v4缺口的选定真实机制由后续v5补齐，完整一般课程仍缺。

此前[MSG23特殊求和与公开历史v3](docs/reports/2026-10-23-protocol-history-v3.md)已有真实mode1／双值、指示物分配、多区域、排序、宣言和猜拳，以及版本化共同公开历史。显式新版profile启用；旧轨迹保留，私有候选与牌序不进入共同历史。[原CPU入口](docs/development/protocol-history-v3.md)继续保留历史范围，不代表一般卡池或竞技能力通过。

此前[MSG26、公开搜索与真实比较课程](docs/reports/2026-10-23-discovery-curriculum.md)已通过独立CPU命令：原生取消/增删/完成、无预写路线同调/超量探索与缺口扩池，真实比较源接四模型双周期，故障恢复与连续运行一致。[可重复入口](docs/development/discovery-curriculum.md)。这是有界工程证据，完整阶段/一般构筑/竞技能力仍待验。

此前[额外/素材与实战纠偏增量](docs/reports/2026-10-23-extra-material-feedback.md)已有真实同调/超量路线、MSG23及公开素材/除外观察、完整终局与成对规则驱动实战数据的双模型更新/恢复；[一条非付费CPU命令](docs/development/extra-material-feedback.md)已实际退出0，墙钟48.19秒、峰值326.82MiB、20份工件回读通过。108项完整集成已过，最后缓存修正后121单元及其中14项集成复验通过；各源版本/日志分开列明。完整阶段与竞技能力未据此通过。

此前[四模型交替CPU交付](docs/reports/2026-10-23-four-model-runner.md)已接成配置周期，含基模冒烟后冻结、LoRA适配、版本预测、冻结核心评估及规则反馈、真实崩溃/阶段预算恢复；默认课程仍明确用条件通常召唤/弱代理。新实战数据通过同一BuildTrainer显式接入，未静默替换课程。更广协议、一般组合发现/构筑能力、三期数据/合格对手及大规模课程仍缺。**full_phase_1_delivered及formal_training_ready仍false**；特征/源码更新后旧权重需原版本重现或显式迁移，原权重不覆写。无付费训练，云端开发不表示本机已同步。

预测/统计配置仍待校准；25/125是完整工程配置在合成样例上的首次触发，没有缩小百/千场设计。LoRA工程正确性不证明迁移能力，PC门槛和标准回放未通过。

运行与验收见 [CPU 骨架说明](docs/development/cpu-foundation.md)、[阶段任务清单](docs/plans/2026-10-22-phase-1-cpu-checklist.md)及[云端启动实证](docs/reports/2026-10-22-cloud-bootstrap.md)。本云端可执行：

```bash
cd /workspace/YGO-Kito
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/check_merge_candidate.py
PYTHONPATH=src .venv/bin/python -m ygo_kito --config configs/cpu.toml status
```

`duel-run` 仍拒绝一般对局；限定卡池的 [native-duel / native-replay](docs/development/normal-duel.md) 与原 [native-smoke](docs/development/native-smoke.md) 使用明确准备的真实资源。纯接口测试与合成夹具不计入真实引擎证据。原学习包保持不变，学生 TODO 与亲手新增测试仍由用户完成。

[native-effects / native-effect-replay](docs/development/selected-effects.md) 覆盖两个固定真实脚本路线，并区分费用、对象、否定与处理；控制器重放轨迹不作为玩家公开历史或策略输入。

[native-search / native-search-replay](docs/development/search-trigger.md) 覆盖合法卡组候选、选中后的公开确认、场上/卡组送墓诱发条件及同卡复活后的同回合次数限制；不向对手暴露未选候选或牌序。

[M2e 次数与发动资格回归](docs/development/count-reset.md) 补充跨回合重置、两张同名副本共享次数，以及检索后发动封锁与未检索对照；卡片汽车·D 只验证发动资格，没有执行其解放费用、抽卡或结束阶段处理。

[决斗模型CPU训练/恢复说明](docs/development/cpu-duel-training.md)提供明确的 `duel-train-cpu` 命令、工程配置和真实checkpoint/监控接口。只用既有云端CPU，不启动付费资源或外部API；模型权重在云端缓存保存，PR提交代码、原始指标和哈希。工程样例不替代用户牌组或独立能力验收。

[构筑目标/优化CPU说明](docs/development/cpu-building.md)提供 `build-train-cpu`、`build-check`、主/额外/副卡DTO及目标→优化→目标→优化接口。该历史批次的17张工程pool、监督和注册证据不等于一般构筑能力。用户输入现有三主六对手及原版／修订边界见[收件说明](docs/development/user-deck-dataset.md)，余下槽位与运行资格另核。

[统筹与四模型闭环说明](docs/development/coordinator-model-group.md)提供 `model-group-cpu`、分权 `coordinator-call`、固定预测/谱系/单在途任务、预设百场/千场反馈及完整组checkpoint；合成统计与真实结果分账。

[LoRA管理与腾讯云受限交接](docs/development/lora-and-cloud-handoff.md)提供 `lora-group-cpu`、`training-preflight`、`budget-call`，实际适配器/基模版本绑定、真实恢复和既定100h规划入口；CPU健康通过不放行正式门槛。CodeBuddy/DeepSeek真实联调、计费/停机核验和PC验证待验，不启动腾讯云或扩PC应用。

[一条命令与本地训练控制](docs/development/local-training-control.md)提供 `engineering-acceptance`、`cpu-runner-acceptance` 和宿主 `--local-cpu-control --local-training-config configs/cpu-runner-v1.json`。示范会有意终止自己管理的worker并验证恢复；每个worker有内核墙钟期限，本地停止始终不证明腾讯云计费停止。

[四模型交替指南](docs/development/four-model-runner.md)提供 `group-runner-acceptance`，宿主选择 `configs/group-runner-v1.json` 即可沿用同一JSON权限/控制入口；逐阶段保存四模型、全部优化器/适配器、调度/RNG/数据标记和累计预算，不自动续额。

[2026-10-21 旧阶段计划](docs/plans/2026-10-21-development-and-training-budget.md) 与 [旧技术复核](docs/reviews/2026-10-21-technical-route-review.md) 保留决策历史，不再作为最新选型入口。尤其旧文的 LoRA 可选、移动端后续排期、预算未分配和架构待讨论表述，不覆盖统一说明。

[M2f通用协议与完整效果对局](docs/reports/2026-10-23-general-protocol-m2f.md)新增效果描述、落点、选项/解放接口及4条40张工程效果牌组真实终局；[协议矩阵](docs/development/native-protocol-matrix.md)明确真实覆盖和拒绝范围。用户牌表收件以当前收件说明为准。额度停止阈值为20%，替代旧5%。

[外部 agent 接口与 CodeBuddy 接入指南](docs/development/external-agent-interface.md)提供分权本地JSON CLI、实际显式CPU控制、卡组/环境/对手池和真实核心单席位动作。外部模型未联调；本地CPU后端默认关闭，须宿主启用。本轮不调用 DeepSeek／CodeBuddy，已有模型驱动不冒称外部模型操作。

## 现行文档

- [游戏王AI项目设计定稿.docx](docs/current/%E6%B8%B8%E6%88%8F%E7%8E%8BAI%E9%A1%B9%E7%9B%AE%E8%AE%BE%E8%AE%A1%E5%AE%9A%E7%A8%BF.docx)

## 学习材料

- [游戏王AI项目亲手实作手册.docx](docs/learning/%E6%B8%B8%E6%88%8F%E7%8E%8BAI%E9%A1%B9%E7%9B%AE%E4%BA%B2%E6%89%8B%E5%AE%9E%E4%BD%9C%E6%89%8B%E5%86%8C.docx)
- [游戏王AI亲手练习包.zip](docs/learning/%E6%B8%B8%E6%88%8F%E7%8E%8BAI%E4%BA%B2%E6%89%8B%E7%BB%83%E4%B9%A0%E5%8C%85.zip)

## 技术参考

- [游戏王AI_技术选型调研_2026-10-18.docx](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B%E8%B0%83%E7%A0%94_2026-10-18.docx)
- [游戏王AI_技术选型调研_2026-10-18.pdf](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E6%8A%80%E6%9C%AF%E9%80%89%E5%9E%8B%E8%B0%83%E7%A0%94_2026-10-18.pdf)
- [游戏王AI_现有技术与混合部署调研.pdf](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E7%8E%B0%E6%9C%89%E6%8A%80%E6%9C%AF%E4%B8%8E%E6%B7%B7%E5%90%88%E9%83%A8%E7%BD%B2%E8%B0%83%E7%A0%94.pdf)
- [游戏王对战AI_项目核验与自建路线_2026-10-18.pdf](docs/reference/%E6%B8%B8%E6%88%8F%E7%8E%8B%E5%AF%B9%E6%88%98AI_%E9%A1%B9%E7%9B%AE%E6%A0%B8%E9%AA%8C%E4%B8%8E%E8%87%AA%E5%BB%BA%E8%B7%AF%E7%BA%BF_2026-10-18.pdf)

## 历史草案

- [YGO模型设计草案_小幅修订版(1).docx](docs/archive/YGO%E6%A8%A1%E5%9E%8B%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88_%E5%B0%8F%E5%B9%85%E4%BF%AE%E8%AE%A2%E7%89%88%281%29.docx)
- [YGO模型设计草案_小幅修订版.docx](docs/archive/YGO%E6%A8%A1%E5%9E%8B%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88_%E5%B0%8F%E5%B9%85%E4%BF%AE%E8%AE%A2%E7%89%88.docx)
- [YGO模型设计草案.docx](docs/archive/YGO%E6%A8%A1%E5%9E%8B%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.docx)
- [标签驱动游戏王AI_设计草案.pdf](docs/archive/%E6%A0%87%E7%AD%BE%E9%A9%B1%E5%8A%A8%E6%B8%B8%E6%88%8F%E7%8E%8BAI_%E8%AE%BE%E8%AE%A1%E8%8D%89%E6%A1%88.pdf)

## 归档说明

- [原件清单与 SHA-256](archive-manifest.json) 记录 11 份原件的来源 ID、字节数和哈希。
- 练习包保持 ZIP 原样，原归档时已静态检查其中 6 个教学文件；本次工程测试独立于学生练习，不解包覆盖或代填学生 TODO。
- 原件归档时未开始开发；现已有CPU骨架及自行初始化的决斗/构筑目标/优化/统筹原型工程更新，未启动付费训练或下载模型。仓库未收录密钥、账户配置、权重二进制、大型数据或无关私人资料；小型工程checkpoint在云端缓存保存。未核实的 ygo_work_handoff.zip 未收录。
- 原件均保留在原来源；两个小幅修订版的字节和哈希不同，分别归档。
- PDF 中原有的 C2PA Content Credentials 来源元数据保留在文件内。

