# 2026-10-25 独立软件验收

验收对象：`/workspace/YGO-Kito-construction`。初验基线 `9be766876a26c1b5692c87c196bf98b007c9051d` 及当时未提交的 group_runner 修正；随后修正已进入 `6ec5a2521d014ac4516c4b160df16d9874e5a591`，新增房间/合法投影继续单独复核。验收者直接阅读规范及源码，不以 MASTER-CHECKLIST 勾选或作者报告代替实现证据。本文为独立软件审查，不执行提交、推送或合并。

## 当前结论

**初验发现的两项具体反馈软件阻塞现已闭合，包括首次修正后发现的同牌表变体。** 当前修正使预警后的改进候选可以再次验证；强制重构要求新接受的真实改动候选覆盖当前全部 mandatory 锚点，并拒绝当前 mandatory 所涉失败牌表的环境/驱动/旧父节点改名。归一化 scope 与租用对手的实际适配器也已有一致性检查。下文保留发现、反例、修正与独立复验链条；没有把未来训练能力增加为门槛。

初验后主线程新增范围的复核结果：跨期主模型权重继承模块与实际保存工件已有独立证据；完整维护范围 bots 的源锁、全量盘点、完整构建输入及 Python 合法桥接代码已有有界验证，**实际 C# 运行和桥接互操作仍未验证**。未执行第三方 bot，不能将源注册表的 loaded 状态当作运行/对局/训练已连接。因此本文不对新增完整可运行 bots 范围或整个合并流程作“全部完成”结论。前次有界受检修正已闭合；针对 `26a39f8` 的新增续验又核到可独立补齐的协议事件、私有对象连续性及来源封印缺口，已逐项修正并定点复验；最后真实正常检查又揭示既有 XYZ 路线的新增安全拒绝回归，现已用有来源的连续可见 Type 缓存修复并复验，下文保留完整链条。不能把 Mono 缺失当作这些代码工作的停止理由。实际编译/运行仍有独立环境依赖阻塞，不能据 CPU/投影证据合并。

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

## 新增完整 bots 范围：初次源部署与后续运行边界

直接阅读 `bot_deployment.py` 的锁校验、源码/工程文件全量盘点、tar 包成员与摘要检查、惰性安装、typed registry 及审批包生成。实际独立运行 `tests.test_bot_deployment`：**14 tests，0.203 秒，全部通过，无 skip**；另对实际 `.cache/bot-source-review/maintained-bot-sources-v1.tar.gz` 调用 `verify_bundle`，在临时目录仅写被动源码后重新全量盘点。**815 个源文件全部按 SHA256 与 Git blob SHA1 核过**，不是只检查几个 Executor 样例。

- 固定 source lock：`configs/bot-sources-v1.json`，规范 SHA256 `9a4aaa5948292d4e2f1b99df1b72dfa4cd53808c702c494aecd80ecedbd631b6`。
- 实际全量 inventory：`.cache/bot-source-review/inventory.json`，规范 SHA256 `d72ad7ff39a541f1ecacc8eea7a7f4544beba937813dd6bc98da95ae04b82348`；220 个来源实例，Ice/Pure/Library 为 73/74/73，按代码字节保留 81 组，211 条 bot.conf 配置记录。
- 固定 commit/许可、所有 Executor 编译包含、跨源 YDK 候选及主题别名均可核。没有缺失牌表资源候选，但同名多版本必须明确绑定；不能据候选存在宣称历史牌表合法/强度达标。14 个 icon/sqlite 等二进制资源只有 metadata，未下载或执行。
- 初次源部署版本中，`BotSourceRegistry.statuses` 的 `loaded_source_registry` 只表示源字节和索引通过。`runtime_loaded/normal_duel_verified/training_connected` 为 false；当时 `training_adapter` 对所有来源明确拒绝。随后新增的实际受审 managed adapter 与门控见续验，不将初版拒绝分支误写为最终 API 尚不存在。

**新增可运行 bots 的确切剩余动作**：取得可用的已批准 Mono/MSBuild/Linux 依赖环境，使用已准备的完整源码/二进制资源编译 Ice/Pure，实际执行全 Executor 反射/构造检查，在隔离 loopback 宿主核验已实现的合法观察/动作协议桥接与正常对局。目标是固定版本完整桌面实现；不是运行 Android 库 PostBuild 或公共远端服务器。

**授权与阻塞更新（2026-10-25 续验）**：用户已批准签名 Debian Mono 安装、完整固定 Ice/Pure 构建和有界 `127.0.0.1` 验证，先前“待用户审批”已过时，不再作为阻塞理由。实际安装仍失败，证据为 `docs/reports/2026-10-25-bot-toolchain-block.json`：系统 `apt-get install --no-install-recommends mono-devel` 在 uid1000、无 sudo 下无法读取配置片段和打开 `/var/lib/dpkg/lock-frontend`；保留既定源与签名验证的 workspace APT 索引请求又被配置代理对三个 snapshot Debian InRelease 地址返回 HTTP403，已下载索引为 0。APT exit0 不能当索引成功。主线程已停止，未换镜像、代理或工具重试绕过。

动作状态为**已授权但外部环境依赖失败/网络代理拒绝**，不是自动审批拒绝；Mono 未安装，C# 未编译，第三方运行/正常对局均未执行。需要具备已批准工具链，或有合法安装权限和可访问签名包源的执行环境。本验收者不重复失败动作，只继续被动资源/协议代码/明确 CPU 契约检查。新增房间与合法投影落盘后另行列明受检证据，不以 fixture 当 runtime。

源部署交付已具备，新增完整运行交付仍不能验收。未把“源码存在”或命令审批包当作 bot 已可运行，也没有把未来 GPU/PC/LLM 能力条件加入这个判断。

### 续验：完整构建输入、实际房间与合法投影

14 个二进制资源随后按用户已授权范围取得并核固定来源（仅被动字节，没有 DLL/.NET 加载）。我独立对 `.cache/bot-source-review/complete-bot-build-inputs-v2.tar.gz` 重新 `verify_bundle`：**829 个成员通过**，当前锁规范 SHA256 为 `d54f892a52a0770e60c64a842b13b412cd778a5ac2887815850ad7eae96c153b`，inventory 为 `c405d35aac9aad63f3d5bb94dc6bc355abb0b9c328691d16355f52243d0a71a1`。实际 Ice/Pure 全量计划分别为 73/74 个 Executor，`executed/runtime_loaded` 均为 false；旧 815 成员摘要保留为先前源部署历史，不替换成新包证据。

新增 `bot_build_audit.py` 与自有 `BotAssemblyAudit.cs` 准备完整项目构建、反射全部注册类型/精确属性和全构造检查，禁止缩减 Executor 或用 ExternalPolicyOnly 子集替代。注入 runner 的测试回执强制为 `injected_process_contract_check`、runtime/constructors false，生产 registry 要求实际完整审计回执、程序集/目录/全部 YDK/工具链/本地 Python 实现摘要一致。独立执行 source/build audit 及两个时期 host 分派用例：**27 tests，0.552 秒，全部通过**；未调用 Mono、C# 编译器或第三方构造。

实际代码审查发现并交 owner 修复了两个来源/版本缺口：生产 registry 曾允许 `room_factory` 回调替代实际 C# 进程，却保留固定 WindBot 身份；驱动摘要曾只覆盖两个类，遗漏实际投影和响应 helper。当前生产回调参数已移除，只有受审 `actual_room→windbot_session` 路径；完整 room/projection/registry/build audit 模块和 Mono/compiler/MSBuild 文件摘要被纳入并持续核对。低层 fixture 用例保留明确测试边界，不能进入生产 registry 冒充实际 C# 驱动。

`windbot_room.py` 的实际 socket 握手要求 loopback、随机 token、固定协议和完整己方牌表；异常/超时关闭连接且不接替旧连接。当前窗口按固定 observer、完整合法请求摘要、state_version、deadline 和一次性使用约束，将返回字节映射为既有 action_id；正常提交仍走原 `submit/validate_selection/response guard`。`windbot_projection.py` 经 Python 委托代理读取已返回的消息，不修改原 CDLL 函数签名、native.py 或响应 guard；仅查询合法 CardView 已有身份的标量，隐身对象保空记录，对手抽牌清 ID、手牌用本地匿名末位、deck 序号不传原索引。早期跨模块事件字段不一致已修正，Journal→frame→LAN codec 的组合用例已加入；早期独立 24 项 room/projection CPU 用例为 0.348 秒全部通过，不外推后续继续新增的检索/extra 范围。

冻结前续验又定位并修正了两处直接边界：对手隐藏卡组卡移入 overlay 的身份按固定协议已经公开，projection 保留合法 ID，但 room 谓词一度遗漏 overlay 并错误拒绝；以及非 observer hand/extra 的公开引用需要分配独立匿名别名，不能保留原始私有 vector 序号。前者已用实际 Journal→LAN codec 组合回归闭合；后者最终为 `lock=overlay OR p!=observer`，我独立运行最后该别名回归通过。对手 hand 的 position bit 不被误当公共身份，只有显式合法公开事实才能带身份；未知/过期别名仍拒绝。

`WindBotOpponent` 已钉住初始 root、seat、versions、profile/_profile、policy 及其两个低层回调身份；生产 registry 不接受 callback 替身。时期 host 新增实际 registry 分派、build audit 路径与 source 绑定；PeriodBuildAssets 的 bot 绑定/重绑仍核时期资源与双方牌表，普通采样器仅对该 typed adapter 进入受管 engine factory。所选两个 host 用例明确使用 patched registry/bind fixture，不冒称 C# 运行。

我独立执行 room/projection **44 项 CPU 用例全部通过（2.202 秒）**，其后只对新增子进程生命周期跑 **3 项 fixture 用例全部通过（0.041 秒）**，再对最终私有别名改动跑 **1 项定点回归通过**，未为重复验证重新运行全部 408 项。生命周期清理只持有本次 Popen：关闭房间、wait、必要时 terminate/kill 后 reap；单个 daemon Timer 同时覆盖两提示之间闲置，cleanup lock 防重复竞争。无法确认回收时记录 `uncertain` 并抛异常，不标成功；不修改 native、向其他 PID 发信号或做故障注入。上述测试用注入 Popen 对象，没有启动 C# 或发送实际进程信号。首次误填测试类名导致的 unittest loader error已改为正确 LoopbackTests 后重跑；不是生产源码失败。

该次冻结源码：`windbot_projection.py` SHA256 `5d95b096a1adc472f94255662584b5b2e85fab565558f9bac1635fdd76df6e49`，`windbot_room.py` 为 `d55fbc14928a27bc3d0100639d2c9e03aa29f81704146b58230eac754be78e3f`。主线程/实现者对这两份冻结源码整组 47 项 CPU（26 projection＋21 room）通过；我没有将其重写为自己重复运行过整组。

已独立读取并核规范 summary 摘要、文件 SHA 和源码逐项绑定的公开收据 `docs/reports/2026-10-25-windbot-projection-evidence/normal-and-search-xyz.json`（文件 SHA256 `cce107dcfe9beb9068fe8c2083a2a55ccfe48753f1ac3bd81c87246677c94fba`）。其该次两个真实核心正向检查分别是：normal 218 次合法提交、110 frame、7 回合**自然终局**；既有检索/Rescue XYZ 路线 22 次提交、18 frame、窗口内虚拟检索与公开素材投影通过，**该路线探针不是自然终局对局**。两项均绑定上述最终源码，走原 submit/guard，`csharp_windbot_executed=false`，无新训练或历史/强度资格。先前 unsupported 记录保留，不用后来成功改写早期失败。

当时有界桥接明确拒绝：无无序表示的私有 deck confirmation、已不匹配当前合法槽的公开 confirmation、已识别隐身 hand/extra 的不明移除连续性、绑定匿名对象后的 extra shuffle、未实现事件 30/35/36/37/42 等，以及不支持的私有区原 chain 触发位置。这些边界与两个正向检查一起报告，不以有界工程通过冒充通用协议/所有 Executor 的实际操作能力。

**该次冻结版本的有界续验结论：上述已修正问题闭合；不表示全部协议事件已经覆盖。完整 C# 编译、反射/构造、实际正常 WindBot 对局和互操作证据仍为 0，因 uid 权限与既定签名 APT 源 HTTP403 受阻。用户授权已经具备，不需重复申请同一许可；没有换镜像/代理/工具绕过。当前新增完整运行范围仍不能验收或据旧 CI 合并。**

### `26a39f8` 后续独立审查与增量验收

直接对照固定 Ice/Pure `GameBehavior.cs`、核心 `libduel.cpp/field.cpp/processor.cpp`、客户端 `single_duel.cpp` 及当前 `public_history.consume`，确认仍可在无 Mono 情况下完成的代码工作：补齐当前 Native 已消费、但投影尚拒绝的事件，维护已公开 hand/extra 与匿名对象连续关系，正确路由私有 deck confirmation，以及为 library 独有 Monarch506 变体提供明确完整构建计划和结构化失败报告。这些工作已交原 owner，不由本验收者修改生产源码。

已发具体接口约束：31 的首位置在 deck 时只发指定 viewer，不能让另一席记住代码；固定 C# ConfirmCards 要求现存槽对象，不能借用选择窗口的越界临时槽。Chaining 第二组原触发位置由固定客户端读取后丢弃，可以保 controller 并归零私有位置；第一组实际激活对象仍须合法公开身份和独立本地别名。匿名 hand/extra/deck 关联失效时，清 Python 字典不等于清 C# 对象，空 query 记录会保留旧 ID；必要的 code0 清除须在 OnDraw/OnMove 读取旧对象和执行回调之前，而非仅在帧末快照覆盖。额外素材的 host 校验也须先作 native→local 别名映射，不能直接将私有原序号与本地序号比较。

事件编号独立核对：30 为 ConfirmDecktop，42 为 ConfirmExtratop，DeckTop 为 38；三者均未在固定 Ice/Pure 注册处理器，不能把字节传输等同策略已使用该知识。35 deck/grave swap 包含墓地额外怪兽插入 extra 的张数变化；36 set shuffle 的既有合法 DTO 只暴露旧公开槽，不允许转发隐藏置换。另 54/55/56/81/83/120/130/131/133/160/165/170 已有 Native 消费分支而投影缺失，已报主线程安排或明确边界。95 Unequip 则是客户端已有处理器、Native 当前尚无消费分支；早期将它并列为“Native 已支持”不准确，已当场更正，不凭 room fixture 冒称整条路径可用。

独立又发现 36 的旧槽原始顺序本身可编码隐藏随机置换：核心先洗牌对象，再按此顺序写旧槽并分配目的槽。主线程已将普通 `public_history` 旧槽规范排序，未改 native/guard/ABI；我直接复核源码并执行 `tests.test_public_history_privacy`，**2 tests，0.002 秒，全部通过**，反序旧槽和不同隐藏目的槽均产生相同公开 DTO，该具体隐私缺口闭合。

新 `bot_qualification.py` 提供只读完整来源牌表合法性矩阵和显式实际运行入口。审查先定位全局 `any(is True)` 压平 unknown、秒数未接真实 session、缺 variant 独立行、CLI 实际运行后才保留报告四处问题，主线程均已修正并冻结。当前三态归并保留 unknown；`session_seconds` 接入真实房间 watchdog 和绑定；宿主循环另检查秒数/决策数，明确不会硬中断正在执行的 native 调用。报告在任何工作前独占保留，已有报告时零调用返回；执行入口没有 room/policy/runner/engine-factory 注入参数，仍要求生产 registry 的实际完整 C# 审计。只有真实 terminal 且 bot 至少选择一次才记该行正常对局通过，fixture 单列。

独立执行 `tests.test_bot_qualification`：**8 tests，0.158 秒，全部通过**。另直接使用实际 829 文件被动 registry 与 `.cache` 锁定资源，只读重新构造既有 normal 工程 actor 及两份列表矩阵，分别与 `.cache/bot-qualification-current-listing-plan.json`、`bot-qualification-variant-current-listing-plan.json` 完全相等；没有加载 native 或 C#。220 个 origin ID 全保留；普通 Ice/Pure 147 候选中 44 份原 YDK 符合当前工程 2026.10 列表，103 份因张数/限额拒绝。含精确 variant 后为 148 候选、44 合法/104 拒绝；唯一新增 library Monarch506 行绑定 Pure runtime 与正确 variant manifest，该原 YDK 当前列表不合法。列表拒绝不等于策略不可用，也不证明历史发行、历史课程或强度资格。`period_host` 可选 `variant_root` 的 workspace manifest 引用与 PeriodBuildAssets 重绑透传已直接核读，旧配置兼容。资格准备与受控执行代码的受检问题闭合，实际所有 C# 行仍未运行。

`bot_overlay.py`、完整构建审计和 registry 变体接线随后冻结。独立执行 `tests.test_bot_build_audit tests.test_bot_overlay`：**17 tests，0.797 秒，全部通过**；含注入 runner 的结构化 timeout/缺文件/无效输出契约，以及现存 OS `false` 工具的一次正常非零退出与回收检查，没有执行第三方 C# 或 native。`BuildAuditError.report` 保留阶段、argv、返回码、独占日志摘要、已完成/未执行步骤与 fixture 标志；actual 审计进程已启动而结果不明时使用 `runtime_loaded=null/unknown`，不伪记未加载。

另独立对实际 `.cache/bot-source-review/monarch506-desktop-overlay-v1` 的 **384 个文件**和压缩包核验通过；variant SHA256 为 `d9d9f78b2ba4ef5c0cc7520cf9d1d943b70784938542725fb8ae8a351c1723b4`，包 SHA256 为 `179d5f93abf2fbb74170c9e2e55220b8ca46bb44b261620ebb0c61ff90640d45`。重新计算全部 74 类构建计划，与实际落盘 `monarch506-overlay-full-build-plan.json` 完全一致。原 Pure 完整项目只替换确切 library Monarch506 文件并附原 MIT；原 73/74 固定源不修改，无 Executor 裁剪。variant 摘要、完整 Python 模块、程序集/工具链与明确 session 秒数进入绑定、持续核查和 rebind。测试中改写的 future-audit schema 是明示合成 validator 输入，未进入真实 room factory，不能用作 .NET 实测证据。精确变体准备的受检路径通过，实际编译、构造、对局仍为零。随后独立定点又发现结构化诊断边界：runner 执行后日志丢失时，未受保护的 `file_sha(log)` 会抛裸 `FileNotFoundError`，丢失阶段/步骤报告；CLI 的通用输入失败分支还会把已执行或未知状态压成未执行。已用自有 fixture runner 仅移除它自己的临时日志后返回 0 稳定复现（`structured_report=False / stage=None`，无实际第三方进程），并交主线程/owner 修正；不以 17 项先前通过遮盖此例。修正后 `log_digest` 捕获日志不可读，保留 `log_sha256=null/log_error`、已执行步骤和 actual 三态，原 timeout 主失败不被摘要异常覆盖。我独立核源码并运行新增两项回归，**2 tests，0.064 秒，全部通过**，该诊断缺口闭合。

新 room 的六项定点 CPU 契约独立通过（0.018 秒），覆盖 private31、完整未知状态清除、30/38/42、36、原有消息布局及 95 的既有拒绝边界。另已交 owner 处理一项真实组合问题：私有确认后同帧 35 交换使 deck 变小时，room 只按最终 counts＋50/90 计算旧向量上限，会误拒交换前合法确认或清除；不能以这些单层 fixture 的通过替代跨模块组合复核。room 随后以公开 deck/grave/extra 守恒并集与离开次数提供旧向量上限，并在 35 之前以公开旧墓地身份和源锁目录原始 type 刷新 C# 分类；独立两个新增用例通过（0.004 秒）。仍待 Journal 生成及正常路径的组合复核。

继续逐字段核固定客户端还发现 HINT 接收者的真实隐私错误：`single_duel.cpp` 明确将 1/2/3/5 发送给消息 player，将 4/6/7/8/9 发送给另一席，10/11 广播；当前 Journal 和 room 曾对所有非广播项统一按 `player==observer` 处理，把第二组路由反了。尤其脚本 OPSELECTED(4) 不是当然公共知识，固定 C# 会写 chain announces 并调用 Executor 回调。owner 已最小修三组路由并保持消息原 chooser 字段。独立 room 新增单项 CPU 通过（0.003 秒）；另独立直接调用实际 Journal.consume 验证两 observer×两 source×11 hint 共 **44 例全部通过**，错误接收者的敏感值不进入 Journal 对象，该缺口闭合。

来源封印又单独复核：旧四个完整模块虽已优于 class 片段，仍未覆盖 `native→public_history/private_knowledge/extra_observation` 及 `native_protocol→private_selection/advanced_protocol/sum_protocol` 等实际传递依赖；例如本次 36 公开 metadata 修正会改变 bot 观察，却不会改变旧 driver 身份。组 checkpoint 的全实现绑定不能替代 opponent scope 身份。主线程已新增 `implementation_identity.py`，将规范相对路径的整个 `src/ygo_kito/**/*.py` 文件摘要映射纳入真实 driver；closure validator 每次重算完整映射核查，含新增/删除，保留原第三方程序集/资源/工具链封印。独立 **3 tests，0.004 秒，全部通过**，使用自有临时文件验证增删改、相同 basename 子模块、缓存文件不入身份及链接拒绝；未改生产源码。已直接核 registry 的摘要输入及持续 validator 接线，该来源缺口闭合。

最终 Journal/room 冻结后，独立运行 **12 项增量 CPU 用例，0.059 秒，全部通过**（11 项新增及已知隐身手牌移除的改动回归）。实际覆盖 Journal→frame→room 的私有确认按席路由、既有 Deck 占位的无序绑定、抽牌/移动前完整旧状态清除、hand/extra shuffle、35 缩小向量与原始 Extra 分类、36 完整清除和去置换、70 私区触发序号归零与已公开类型、首次新墓地 handler 的真实当前 dynamic Type 前置，以及 HINT 路由。已直接核查 70 公共 handler 以当前合法同槽、同 code 的既有标量 query Type 前置，不再用目录 base Type 覆盖变形状态；缺该证据时明确拒绝。未增加隐藏查询、改变 native ABI 或响应 guard。

该中间冻结 `windbot_projection.py` SHA256 为 `b973bec02bd784f79fd4d2047e7f31901a99adc32dd030684dfaeae3a6f24bc4`，room 为 `d80894499e00925aba812295a4c78fefe9f444846e0b51635a0c069c4d6d7422`。实现者整组 37 projection＋31 room 共 68 CPU 通过是其单独记录，我未将它冒称自己重跑整组。该中间版本保留的可达接口/语义边界为：旧 adapter 缺 PrivateReveal/混合私区确认；公开确认对象已不在当前合法槽；同缓冲重复 35 缺新公开墓地身份；overlay70 的固定客户端临时对象不能保留前置类型；公共70缺当前同槽同code动态记录。以上均拒绝，不猜隐藏排列、历史动态状态或借宿主冒充素材。另已独立核固定 core：55 仅在 `field.cpp:swap_card` 双方 ONFIELD 检查后唯一一处发送；私区 vector55 是当前 pin 不可达的输入保护，不列为待开发缺口。95 在 `common.h` 的宏已注释，core 无发送，同样不因保留 legacy codec 增设当前实现要求。

最后真实正常检查又给出具体回归，不能由 12 项 CPU 通过封口：全树 `944c8c38e5ebff00860a9daeba9f8e2390bfd53a1f219a92dc7918f19532c41c` 的 `search-xyz-attempt-20261025T084246226652Z.json` 明确 `failed_or_unsupported`，原因为 `public chain handler has no current same-slot visible dynamic type`。新 `transport_frame` 仅按最终 pending 的同槽 handler 查 TYPE，已有 Rescue Cat 检索→XYZ 路线在 handler 移走后无法通过；这是相对于先前真实路线的功能退化，安全拒绝不等于该路径已闭合。已独立读实际失败收据并交主线程/owner，要求合法 source-bound 中间可见状态证据，不用目录 base Type 或新墓地动态值冒充原场上状态。同期两个 private 机制与 normal 收据通过，但不能称四机制全通过；早期失败保留。

主线程授权的最小修正仅保存上次合法可见 query 的同槽/同 code/Type 及 request SHA；按已发往固定 C# 持久对象的事件顺序，仅穿过 HINT/CHAINING，任何其他状态事件都使该缓存失效。70 在后来 cost MOVE 之前保留该客户端对象已知的 Type，不用末态墓地类型或目录原始类型回填旧场上状态。当前同槽可见动态记录仍可直接使用；缺当前证据和连续缓存时继续拒绝。我独立核该实现并运行新增针对性 CPU，**1 test，0.006 秒，通过**，其中 printed type2 与真实 query type17 刻意不同，phase 插入使缓存拒绝，来源 request SHA 也逐项核对。

随后独立读取该次四份 08:51 正常核心原始收据，并重新计算整个 Python 包：**95 个文件，摘要 `30ad514908ceac441e359805acc5aa415ea7ae1afe22816e3383c60d41016da8`**。四份完整 map 均与当前源码逐字相同，原 submit/guard 路径为 true，C# 为 false。normal 为218次提交/110帧/7回合自然终局；XYZ为22次/18帧、虚拟检索和公开两素材成功、连续 Type 缓存使用1次，既有路线恢复；`crescent-private` 为11次/3帧及76次完整擦除，`rescue-confirmed` 为16次/5帧及74次擦除，两者都实际合法提交选择并继续编码后续本席请求。这三个机制探针没有冒称自然终局，历史/强度/训练标志均false。08:42失败收据仍保留。

公开增量聚合为 `docs/reports/2026-10-25-windbot-projection-evidence/private-continuity-and-normal.json`，文件 SHA256 `e029a4e23c964d0bddfc7816cfe2c0770ad7e318c4c67cacadc7be1d684bd1fe`、规范 summary SHA256 `f934e00391a0cb2e64757797eec27a482028885577d4d0e3c965206eef2ec857`。已独立核 summary 重算、全 source_tree、四份原始收据字节摘要、聚合每行与原收据（仅去重复 map）完全一致，以及旧失败文件存在。

70缓存修正后的冻结 projection SHA256 为 `2076ccb956fc3f613eb5853d4fec03f599c36ae134b9b15a0d645bb42231cea4`，room 为 `d80894499e00925aba812295a4c78fefe9f444846e0b51635a0c069c4d6d7422`。上述具体软件回归已闭合；本验收者只回读正常核心收据，没有自行重跑 native。

主线程最后又要求核对 public31 历史槽：独立判断这是现成公开信息可补的接线点，不应归因 Mono。public_history31 已给出公开身份、controller/zone 与公开区域 sequence，Journal 已保当时独立 local alias，可按原 client 事件顺序在后续 Move 前编码；需要本帧/此前未消费 event_ref 的一一绑定、精确多重集、公开序号与私区无序语义区分。

该项随后最小实现并冻结：公开 event_ref 只能来自本帧新 history suffix，精确匹配 reveal/message31/viewer 与配对的身份/位置多重集；公开区 sequence 按历史核，hand/extra 保持 None 并仅用 Journal 当时独立 alias 和公开旧向量上限。proof 绑定实际最终 message_index，同内容两次确认也须两个不同 ref。Window 拒本帧 ref 重用；Room 在成功响应后保存整个历史前缀摘要/长度，阻止跨帧重证、篡改或截断，Observation 自身禁止重复 event ID。私有 knowledge_ref 与公开 public_ref 互斥。

独立源码审查还及时发现并交 owner 修正临时加 ref 未进入最终编译 loop 的中途接线错误，不用手工 room fixture 冒充已接通。独立执行新 room 三项 CPU（0.150 秒）及真实 Journal→frame→codec 三项 CPU（0.012 秒），全部通过：确认后隐藏移出导致旧对象无当前槽仍可按原事件顺序编码，复用/错 ref/ID/公开 seq/消息索引/历史前缀均拒，原隐藏卡号不进入 frame。该可独立实现点闭合。完整 C# 构建/构造/真实 WindBot 对局仍为零且环境阻碍不变，不对新增完整运行范围或合并给出通过结论。

最终公开证据为 `docs/reports/2026-10-25-windbot-projection-evidence/public-confirmation-and-final-mechanisms.json`：文件 SHA256 `09cae9e103c60c00225cd1f2f5366f0d7b4747b0fa95ca979d7592412546ec00`，规范 summary SHA256 `fc8a896834cb8e1a85c7ae37a554a28a9839176d46ffa436945ec11972a7a936`。已独立重新计算 summary、完整 **95 个 Python 源文件**映射，以及全部五份原始收据文件摘要；聚合各行与原始收据（仅省重复 source map）完全一致。最终全树摘要为 `d19a310867616257ead51d8bea2cdb146687dd2b5b6aa22603f18d6ce56a27bd`，最终 projection 为 `23f02af625d56ff1405936ad73242a3c1e783d748c718c3a9bab3024ef33a5f7`、room 为 `a819ca43cfe977d42643220f17cec6988b334a497fcca2c1d7ee1610bd5224fc`。

09:10 最后同一全树的五机制均通过：normal 218次/110帧/7回合自然终局；XYZ 22次/18帧、连续 Type 缓存1次、检索和两素材路线完成；private 两机制仍为11次/3帧、16次/5帧且合法提交后继续编码；新增 `confirm-extra` 为12次/8帧、两个公开确认 ref/两次立即 extra shuffle，末态敌方额外身份全 hidden 时仍准确编码之前公开确认。五份均走原 submit/guard，C#、训练、历史/强度资格全部 false。实现者完整 75 项 CPU（41 projection＋34 room）和4个正常方法/5机制证据分列；本验收者只做上述增量 CPU 和原始收据独立回读，没有重复运行 native 或全局 CI。旧 08:42 失败与 08:51 旧树聚合的文件摘要也已按实际字节核实并保留。

最终判断：本轮已识别且可独立修正的软件接线、隐私、连续性和来源问题全部闭合；不再把已经补齐的 public31 历史槽列为缺口。当前仍明确拒绝缺 PrivateReveal/混合私区证据、扩展之外的混合 public-deck pool、同缓冲重复35缺中间公开墓地、固定 C# overlay70 临时对象、缺当前及连续可见 Type 证据等范围；30/38/42无序公开事实不冒称消费者有牌顶顺序模型，55/95的当前 pin 不可达输入保护不新增开发门槛。

实际 C# 工具链/构建/构造/正常 WindBot 对局仍为0：已批准的 Mono 安装因 uid1000 系统权限和既定签名 APT 源代理 HTTP403 失败，非自动审批拒绝或仍等用户批准，未重试/绕过。新增完整实际运行范围不能验收，仍不得据这些 CPU/宿主投影证据合并；最终提交与统一 CI 由主线程另核。


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

本验收者未重复运行完整安全 CPU CI。已读取主线程保存的实际 GitHub 回执 `docs/reports/2026-10-25-design-review-evidence/6ec5a25-ci.json`：PR3 head `6ec5a25` 的 run `40170732886`、job `121100853915` 成功，408/408、无 skip；PR 合并检出为 `0a7e7d8c4d6e3c597cd4f3b31e90c0ddda727494`，implementation SHA256 `30a179db9051c0aedd39b591ec39745623ae945a1ce83b59b0cd0b49f58d1334`。这是该候选的 CPU/合成契约证据，未覆盖续验中后来新增的 room/projection/binary 代码或第三方运行；没有将回执的 `ci_verified:false` 改写为该脚本自身验证过远端 CI。新增范围未验不得据旧 408 项结论合并。主线程仍须核最终源码、实际最终提交 CI 及当前用户范围，再依用户授权按 PR1→PR2→PR3 合并 main。

GPU 安装、吞吐/数值调优、正式模型能力与迁移验收属于阶段2；PC 产品与客户端互操作属于阶段3；LLM/provider 为可选后置；历史全库由既定 DP 路径另取。本文未把这些事项添加为当前软件合并门槛。
