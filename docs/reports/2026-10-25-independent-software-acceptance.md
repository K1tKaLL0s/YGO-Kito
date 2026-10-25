# 2026-10-25 独立软件验收

验收对象：`/workspace/YGO-Kito-construction`，基线 `9be766876a26c1b5692c87c196bf98b007c9051d` 及当前未提交的 group_runner 对手/强制重构修正。验收者直接阅读规范及源码，不以 MASTER-CHECKLIST 勾选或作者报告代替实现证据。本文为独立软件审查，不执行提交、推送或合并。

## 当前结论

**初验发现的两项具体反馈软件阻塞现已闭合，包括首次修正后发现的同牌表变体。** 当前修正使预警后的改进候选可以再次验证；强制重构要求新接受的真实改动候选覆盖当前全部 mandatory 锚点，并拒绝当前 mandatory 所涉失败牌表的环境/驱动/旧父节点改名。归一化 scope 与租用对手的实际适配器也已有一致性检查。下文保留发现、反例、修正与独立复验链条；没有把未来训练能力增加为门槛。

初验后主线程新增范围的复核结果：跨期主模型权重继承模块与实际保存工件已有独立证据；完整维护范围 bots 的源锁、全量盘点、离线源部署已通过核验，**实际可运行 bot 及训练桥接仍未完成**。未执行第三方 bot，不能将源注册表的 loaded 状态当作运行/对局/训练已连接。因此本文不对新增完整可运行 bots 范围或整个合并流程作“全部完成”结论。

当前软件的其余受检主干已有可调用实现及明确拒绝边界：独立角色模型、无卡 ID 构筑图、狭义主轴、卡文绑定、真实轻量分类器与拒判、LoRA、通用本地 Agent、时期与用途隔离、完整阶段恢复。没有据此认定正式构筑/决斗能力、预测校准或全部卡效正确性通过。

## 阻塞一：预警后的改进候选被评估入口拒绝

- 位置：`src/ygo_kito/group_runner.py:evaluate` 的路由检查（本轮初验第 711–714 行）；关联 `coordinator.py:_route` 与 `coord_contracts.py:rule_route`。
- 触发：候选 A 的冻结预测 `.9`，实际账本达到首次低胜率检查点，产生 `reevaluate`，尚未产生 `mandatory_rebuild`；目标、硬约束不变，提交实际改变卡表的子候选 B。
- 实际行为：账本按根谱系保留预警，B 的实际路由为 `build_optimizer`；`evaluate` 仅接受 `register_forecast` 或 `build_goal`，在登记 B 的新预测前抛出 `ContractError("rule coordinator did not grant versioned forecast stage")`。
- 影响：既有构筑阶段完成后的改进候选不能继续验证；运行会因应当正常处理的提醒而中止。
- 独立复现：使用 `tests.test_coordinator.CoordinatorContractTests` 的实际 SQLite 账本与 `source=synthetic_contract_test` 结果契约，生成 25 条 loss 并完成原模板任务，得到 26 场；提交改变卡表的 B，再调用实际 `evaluate`。输出为 `warning=True / rebuild_required=False / actual_route=build_optimizer`，随后得到上述实际异常。仅将最前面的牌表验证隔离为空操作以定位路由门控，未替换 `route`、统筹模型或 `evaluate`；没有采样或 native 调用。此证据只证明控制分支缺陷。

## 阻塞二：有父节点的旧候选可继续绕过本次强制重构

- 位置：`src/ygo_kito/group_runner.py:_validation_job_purpose`；`src/ygo_kito/coordinator.py:_schedule`。
- 触发：先有 A→B，B 自己的预测累计到强制重构阈值；之后没有新候选，没有改变 B。
- 实际行为：`_validation_job_purpose(B, route)` 只因 `B.parent_candidate_id` 非空而返回 `rebuild_validation`；账本也仅检查非空父节点，接受同一 B、同一预测的下一次任务。
- 独立复现：未 mock 任何生产函数，通过实际公开 `dispatch` 顺序执行 B 的 125 次 `job.schedule→job.claim→results.append`，均为明确合成 loss。随后实际 route 为 `build_goal / mandatory_rebuild=True`，未调用任何新的 `handoff.submit`，同一 B 的 `rebuild_validation` 任务仍安排成功。输出：`new_candidate_after_alert=False`，`same_affected_candidate_accepted_for_next_job=already-existing-child`。
- 影响：“曾经是某候选的子节点”被当作“已响应当前强制重构”的证据。当前 runner 的相同卡表复用分支也可能选回旧 B，不能仅凭本周期调用过构筑角色认定它已有改动。门控应核对与触发强制重构的候选之间的有效谱系关系，同时保留旧预测、结果和根预警；不能靠清告警或改 ID 解决。

### 首次修正后的独立复核

实际阅读修正源码并执行 `tests.test_group_runner tests.test_coordinator`：**18 tests，5.772 秒，全部通过，无 skip。** 预警 `build_optimizer` 现由实际评估调用的 `_validation_job_purpose` 接受，`diagnose/train_duel/stop` 仍拒绝；第一项闭合。候选首次接受时保存当前 root 所有 mandatory forecast IDs 为不可由 RPC 提交的 `rebuild_after_forecasts`，重试保旧锚点；旧 B、过早创建的子候选及与直接父节点同卡表只换环境的候选会拒绝。旧计数、告警没有清空。

独立反例仍发现第二项变体：A→B，B 自己 125 次实际公开账本 schedule/claim/result 合成 loss 触发 mandatory；之后提交 D，**父节点选择旧 root A、牌表完全等于失败 B，只更换 environment_id**。D 新锚点正确，且牌表与 A 不同，于是 `_rebuild_validation_eligible=True`。给 D 登记新冻结 driver 的新 scope（`actor_policy_sha256` 改变；旧 scope 不能重登记的保护保持有效），实际 `_validation_job_purpose` 与 `job.schedule` 均允许 `rebuild_validation`。输出为 `actually_scheduled=d / same_losing_deck=True / old_root_forecast_still_mandatory=True`。因此不能只比较与调用者选择的直接父节点的差异；尚需封闭对当前强制重构失败牌表的环境/旧父节点改名绕过。上述复现仍全部为 `synthetic_contract_test`，无 native。

### 最终反馈修正复验：两项均闭合

最终使用最小门控：候选首次接受的 mandatory forecast 集合必须仍等于当前 root 全集；与直接父节点必须实际改卡；且不能等于当前任一 mandatory 预测所涉失败牌表 SHA。没有加入“root 全历史永久未出现过的牌表”要求；未处在失败集合的旧有效核心可以新版本重新验证。`rebuild_after_forecasts` 是宿主产生的只读证据，重试不刷新，不是 RPC 可填写的绕过开关。

重新实际阅读最终修正并执行同两模块：**18 tests，1.684 秒，全部通过，无 skip**。其中实际账本新 scope 的 schedule 已拒绝上述同 B 牌表换旧父节点/环境/驱动变体；旧有效不同牌表允许。最终 `coordinator.py` SHA256：`a424572c2e5d4d9ae36ebffea2d40c3388646da6eb8f3b9ff6efccc92d64586c`。

另独立通过未 mock 的公开账本调用验证多 mandatory：A 的冻结预测先累计 125 次合成 loss；之后新 B 获准重构验证，预先创建 C；B 自己再累计 125 次 loss 后，当前 mandatory 集合成为 `['bf', 'forecast']`。C 的旧锚点明确失效；两次告警后真正改变卡表的新 D 由实际 `job.schedule` 成功安排 `rebuild_validation`，A/B 旧预测计数均保留 125。没有删除、清空或下调历史告警、结果和预测。此测试与统计例子均不是实际对局能力证据。

## 源码核查与实现边界

| 设计要求 | 直接核查的实现 | 验收判断 |
| --- | --- | --- |
| 决斗、目标、优化、轻量统筹分工 | `duel_model.DuelActorCritic`、`build_training.BuildTrainer`、`coordinator_model.CoordinatorTrainer`；分别构造 Transformer/MLP 与优化器；构筑角色还检查参数存储不重叠 | 可调用代码存在；没有新增 LLM，规则仍掌握权限与最终调度 |
| 目标→优化且保留用户硬约束 | `build_pipeline.alternate_build` 四阶段、每次 `verify_goal`、固定 task SHA；`construction_logic.ConstructionSession.check_goal` | 目标与数量/禁限/卡池约束没有被优化模型静默改写；代理偏好未冒称竞技强度 |
| 先粗图→仅狭义主轴→具体卡 | `construction_cycle` 实际顺序为每角色 stage1/2/3；`select_main_axes` 广义跳过、狭义要求有来源 setcode/race；`fill_with_existing` 后置具体候选与数量 | 粗图 DTO 不含具体卡 ID，连接件与标签独立；通用卡仍保留在 pool；粗连接不被当合法 CB |
| 图候选与角色模型实际接线 | `LogicModelAdapter` 使用现有两个 BuildRanker 打分、`train_preference` 实际更新、`ConstructionController` 组合目录绑定与现有统筹 | 程序枚举有界图，模型评分选择；没有冒称模型自主生成任意图；缺权重/零更新/未泛化均明示 |
| 真实轻量非 LLM 分类/拒判 | `LinearIntentClassifier` 字符 ngram/词/词典证据特征、softmax 训练、权重保存；默认 Session 使用未训练模型 | 真正有可训练权重；缺训练、低置信、低 margin、低词汇覆盖均拒判；规则标签不直接决定模型输出；否定/别名/外挂/组合等有明确 CPU 用例 |
| 卡文与规则验证分层 | `CatalogBindingAdapter`、`evaluate_fill` 的文本哈希/引文/节点标签覆盖/牌表/现有目标收据核查 | 功能关键词只召回，不认证效果；未知保留；任意图边执行始终 `graph_execution_verified=False` |
| 百场提醒/千场强制重构 | `FeedbackPolicy` 默认预登记 25/50/75/100/125/250/500/750/1000；账本不可变预测、结果、谱系告警与规则优先 | 非整点才检查、包含不确定性与重复观察控制；正式校准仍 pending；本轮两处闭环阻塞已修正并独立定点复验 |
| 评估任务与实际对手 | `evaluate→forecast.register→job.schedule→job.claim→semantic_curriculum.opponent→LoadedTrainingInputs.for_runner→PeriodBuildAssets.rebind_rule_opponent` | 当前补丁使用账本归一化后的 scope；由租用任务的 ID/牌表哈希/实际 driver identity 反查可选 binding；再核实际 adapter 的同三项身份；seed 与 policy_seed 仍使用冻结时期 partition |
| 训练/验证/终验及时期隔离 | `compile_training_inputs`、`load_training_inputs`、`DataIndex`、`semantic_curriculum` | 实际对手身份由牌表内容/实现/驱动/模型计算，改名或改卡序不能跨用途；物理版本同种子、同内容、持出牌表跨用途被拒；训练准入检查 train；selected-period 不伪造其他时期 |
| 第三期日期与发行来源 | `deck_intake.cutoff_timing/_environment`、`historical_listing`、`PeriodBuildAssets.assert_integrity` | 日本日期未到 2026-11-01 时拒绝最终池准入；日期已选和实际可用池分开；2026.10 禁表与发行截止分开；未把当前未齐资料设为软件合并新门槛 |
| LoRA | `AdapterSession` 的冻结基模、目标层/上下文/特征/基模绑定、参数真实更新、停用/卸载与恢复 | 接口和工程训练/恢复已实现；拒绝隐式叠加/不兼容恢复；新任务收益与旧任务退化仍属正式训练验收 |
| 通用 Agent | `AgentBridge`、`HostConstructionBackend`、本地 JSON Lines 服务 | 固定宿主角色和配置；manager 构筑推理可接现有控制器；RPC 不能提供路径、开训练、开 native 验证或 provider；真实外部模型未连接不阻塞本地基线 |
| 完整恢复 | `GroupState.save_to/restore`、阶段事务、嵌入 ledger/index、四模型/优化器/调度/RNG/适配器/游标/预算绑定 | 未完成阶段不冒充完成；拒绝在途评估 checkpoint；源码与资源改变拒恢复；数据索引恢复使用新目录隔离未提交写入；GPU 实机恢复仍归阶段2 |

## 新增跨期初始化复核

已直接阅读冻结的 `group_initialization.py` 及 GroupState 接线，独立执行 `tests.test_group_initialization`：**8 tests，1.705 秒，全部通过，无 skip**。模块读取一次固定 SHA 的源文件 bytes，再从同一 bytes 以 weights-only 加载；检查完整组 done/角色/特征/模型与 LoRA/物理与任务上下文。`effective` 显式物化保存的低秩增量，`base` 明确选择原基模；卡嵌入按稳定 ID、注释按完整规范身份映射，新身份和 padding 保留目标初值。先校完四角色再原位加载，失败回滚；新优化器、RNG、游标、数据和账本不继承。

明确工程来源 `period_context=null` 可以使用，始终保留 `historical_training_verified=False`；同/逆向迁移可供显式旧环境复习，不额外增加方向门槛。来源/目标 cutoff 与环境分别记录，不把源现成卡表或轨迹复制成新期主构筑答案。旧 GroupState.restore 继续要求同源码/数据/资源绑定；初始化是新任务权重导入，两者没有混成放松恢复。

当前实际接线为 recipe 宿主 `initialize_from`→四个 fresh trainer 建好后导入→首次阶段前的新 ledger→checkpoint 保存/恢复 provenance。新模块 8 项使用自有小网络与明示合成 done 文件，只验证文件/矩阵契约；不证明真实历史训练。

主线程随后完成非 mock 的 `GroupState` 实际构造、`save_to`、删除源副本后 `restore` 冒烟，收据为 `.cache/group-initialization-host-latest.json`，保存工件为 `.cache/group-initialization-host-6fibxkfa/initialized-group.weights`。我独立以 weights-only 读取实际工件，重新计算四模型参数摘要，全部等于 provenance 的目标摘要；目标游标为 `bootstrap/0`，adapter、data、consumed 为空，target binding 摘要匹配，源副本实际已不存在。源码恢复路径不重导源权重，仍核同绑定。主线程收据记录恢复后四模型与 provenance 相同、原源未改；此处没有把收据中结论替代实际参数核对。

该实际源 SHA256 为 `ac8f1a048a9cf9b01a5f544944b5fa4663338aa54f00a7688f121ef99ad21863`，来源上下文是旧工程 `2022-10 / release_cutoff=2022-10-01`、各基模 1 次更新和保存的 LoRA；不是确认截止 2022-12-31 的正式该期池。目标也是普通工程任务（`period_context=null`），没有冒充未来第三期最终池或实际历史能力。该冒烟没有新的采样、训练或 native 调用。受检的跨期模块/接线未再发现阻塞。

## 新增完整 bots 范围：源部署通过，运行仍阻塞

直接阅读 `bot_deployment.py` 的锁校验、源码/工程文件全量盘点、tar 包成员与摘要检查、惰性安装、typed registry 及审批包生成。实际独立运行 `tests.test_bot_deployment`：**14 tests，0.203 秒，全部通过，无 skip**；另对实际 `.cache/bot-source-review/maintained-bot-sources-v1.tar.gz` 调用 `verify_bundle`，在临时目录仅写被动源码后重新全量盘点。**815 个源文件全部按 SHA256 与 Git blob SHA1 核过**，不是只检查几个 Executor 样例。

- 固定 source lock：`configs/bot-sources-v1.json`，规范 SHA256 `9a4aaa5948292d4e2f1b99df1b72dfa4cd53808c702c494aecd80ecedbd631b6`。
- 实际全量 inventory：`.cache/bot-source-review/inventory.json`，规范 SHA256 `d72ad7ff39a541f1ecacc8eea7a7f4544beba937813dd6bc98da95ae04b82348`；220 个来源实例，Ice/Pure/Library 为 73/74/73，按代码字节保留 81 组，211 条 bot.conf 配置记录。
- 固定 commit/许可、所有 Executor 编译包含、跨源 YDK 候选及主题别名均可核。没有缺失牌表资源候选，但同名多版本必须明确绑定；不能据候选存在宣称历史牌表合法/强度达标。14 个 icon/sqlite 等二进制资源只有 metadata，未下载或执行。
- `BotSourceRegistry.statuses` 的 `loaded_source_registry` 只表示源字节和索引通过。`runtime_loaded/normal_duel_verified/training_connected` 为 false；`training_adapter` 对所有来源明确拒绝，指出未实现/未验的 YGOPro loopback room→本项目 ctypes/seat DTO 桥。

**新增可运行 bots 的确切剩余动作**：安装/冻结 Mono/MSBuild 及 Linux 引用与所需二进制资源，完整编译 Ice/Pure 固定源码，在隔离 loopback 宿主执行正常对局，并完成合法观察/动作的房间协议桥接。目标是固定版本完整桌面实现；不是运行 Android 库 PostBuild 或公共远端服务器。本文只核对了会生成审查命令的 `approval_packet`，没有执行安装、第三方构建或进程，动作状态为**未执行/待安全审批及实现**；本验收者没有收到或绕过自动审批拒绝。具体审批结果由主线程按其实际工具回执另报。

源部署交付已具备，新增完整运行交付仍不能验收。未把“源码存在”或命令审批包当作 bot 已可运行，也没有把未来 GPU/PC/LLM 能力条件加入这个判断。

## 本轮实测证据

在仓库已建的 CPU 锁环境执行以下明确模块，无 discovery、故障注入、native、付费服务或外部模型：

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONPATH=src \
  .cache/ci-cpu-venv/bin/python -m unittest -v \
  tests.test_group_runner tests.test_coordinator tests.test_intent_model \
  tests.test_construction_logic tests.test_construction_model \
  tests.test_construction_binding tests.test_training_input tests.test_lora \
  tests.test_construction_service tests.test_training_checkpoint_contract
```

结果：**108 tests，2.720 秒，全部通过，无 skip。** 实际 Python `3.12.14`、Torch `2.9.1+cpu`、`torch.version.cuda=None`。初验 `group_runner.py` SHA256 为 `7e70e24a19910398b3109d091442073bba8d1b621ca1a586923ce0af19e2d09e`，`coordinator.py` 为 `e303a6515221a83b1a208c52feb0a7210025fe37c147637b45c90da369b70b64`。包含实际小型模型参数更新/保存/下次更新恢复、实际 SQLite 账本、现有模型与目录绑定组合；合成卡/结果/文本判断始终只是代码路径证据。本轮两个额外最小复现独立于既有通过测试，说明通过清单尚未覆盖这些反馈状态转换。

本轮未运行完整安全 CPU CI；没有声称远端 CI、当前正式真实引擎或 GPU 实机结果。已有历史引擎/CI报告不代替本轮事实。主线程仍须在新增范围完成后复核最终源码及最终提交 CI，再依用户授权按 PR1→PR2→PR3 合并 main。

GPU 安装、吞吐/数值调优、正式模型能力与迁移验收属于阶段2；PC 产品与客户端互操作属于阶段3；LLM/provider 为可选后置；历史全库由既定 DP 路径另取。本文未把这些事项添加为当前软件合并门槛。
