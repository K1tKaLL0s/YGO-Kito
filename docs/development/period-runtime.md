# 分期真实资产、规则驱动与宿主加载

`period_runtime.py` 与 `period_host.py` 将 [训练输入](training-input.md) 接到实际 `BuildAssets`、当前已构建 core、已有公开规则策略和 group runner 的显式宿主钩子。输入未齐或实际资源不符时关闭，不用工程夹具替代生产数据。

## 资产与实际引擎

`PeriodBuildAssets(root, period_id, environment, workspace, adapter_revision=5, evidence_source=...)` 先复用收件模块检查实际卡库、发行清单和明确禁限节，再由真实 `BuildAssets/verify_resources` 核对卡库及完整禁表文件与已构建 native 资源逐字节摘要一致。发行清单产生显式允许池，实际 rows/limits 和来源/环境具有封印。历史截止始终保留，`environment_for(kind)` 不把它变成 null 或偷偷换适配版本。

`check_task/validate/facts/effect_receipts` 继续使用原构筑接口；任务卡池另须处于明确发行允许池内。`engine_factory(root, **NativeNormalEngine参数)` 创建真实 `PeriodNativeEngine`，开 core 前重新核实际来源、日期、允许池和 profile 的主/额外/副卡。它复用原 native 协议和响应路径，只覆盖普通 Python `_deck_limits()` 选择及对外可见的精确 `RunContext.versions`。ABI、DP 响应 guard 和原生库不在此模块改写。

目标验证器生成的可信 profile 先经 `adapt_goal_profile(profile)` 包装为宿主选定的 adapter revision。它保留双方主/额外/副卡的身份、顺序和数量，只补空字段并改变观察框架；旧版本不能承载额外卡时明确拒绝，不能删卡适配。`engine_factory` 自身继续严格拒绝版本不匹配的原始 profile，环境截止不受此包装影响。

私有 adapter 4/5 的路线搜索在同一次搜索的全部 prefix 分支中复用一个独立随机 selection key；成功后的原始私有 `route_evidence` 保存 `private_selection_key_audit_only`，重放必须校验并复用。旧 v2 证据不新增此字段，非私有版本不得带该 key。缺失/格式错误的私有 key 直接拒绝，不能以当前环境替代分期重放。key 不进入构筑模型的监督投影，公开构筑/统筹回执另行递归剥离此字段；需要重放的宿主应保留原私有证据。

每期版本保存实际 core/scripts/cards/client protocol，并将禁限版本绑定到明确所选节和实际文件摘要。现有 `BuildTask` 对显式 custom＋ISO 截止的描述扩展仍由实际资产精确检查；官方或 community 声明没有因此获得认证。

## 实际规则对手与重绑

`assets.bind_rule_opponent(profile, opponent_id, seat=1, driver_version=...)` 只接受现有两种 `LOCAL_DRIVERS`，实际创建复用 `PublicRulePolicy` 的 `PeriodRuleOpponent`。它是 `FrozenOpponent` 子类，具备原训练器使用的 `policy.choose/binding/profile/versions/assert_runtime`，并提供 `select` 和 `_profile`。收到的动作仍来自合法席位 DTO，输入包含版本和种子不可见边界检查。未实现的 external_llm/bot 不会被默认为 baseline。

冻结绑定沿用现有字段，`registered_record_sha256` 标识本次明确冻结的驱动配置；本类不绕过当前 registry 的历史运行门禁，配置没有被伪装成旧数据库中已验证的历史记录。`strength_qualified/external_provider_verified/historical_rules_verified/official_sources_verified` 保持 false。

`bind_snapshot_opponent(profile, opponent_id, checkpoint, checkpoint_sha256, model_sha256, model_source=..., migration=...)` 接入本项目现有 `PublicSnapshotPolicy` 与 `frozen-duel-greedy-v1`。仅接受 workspace 内明确 SHA 的 CPU duel checkpoint，核对完成对局边界、更新/游标、完整资源收据、特征版本、源 profile 摘要、实际模型及词表；词表必须覆盖所选允许池。策略冻结为 eval 且无梯度，训练种子、优化器、checkpoint 路径和来源说明不进入策略输入。内存模型/词表/来源封印和文件字节仍会复查。

模型的 `model_provenance` 将源 binding/profile/period/versions、模型和词表摘要、完成边界以及目标 period/cutoff/profile 分开记录，并纳入原标准绑定的 `registered_record_sha256`。`same-period-inference` 要求源 checkpoint 自身携带且匹配精确时期上下文和版本；旧未分期或跨期 CPU 模型必须明确填写 `explicit-inference-migration`。该迁移只冻结推理，不恢复旧源码绑定的训练器，也不表示历史训练、LoRA 最新策略或合格强度。模型来源/迁移信息保留在宿主，actor 重绑保留源信息并重算目标 profile，现有 `rebind_rule_opponent` 名称兼容两类已实现对手。bot/external_llm 仍需实际传输实现，不回退为本地模型。

构筑改变 actor 牌表后调用 `assets.rebind_rule_opponent(binding, actor_deck, purpose=...)` 或 `opponent.rebind(...)`。新 profile 和 `own_deck_sha256` 实际重算，对手的排序牌表/驱动身份保持；旧绑定不能提交为新 actor 的证据。之后由原 DataIndex 对相应实际 episode 和目的重新准入。

已有 `opponent_pool.replay_private(root, trace, engine_factory=assets.engine_factory)` 可显式使用同一分期资产重放完整私有轨迹，包括原 selection key、所选禁限和可见版本；省略 factory 时保持原普通引擎路径。宿主不能省略此参数后把当前环境的重放称为分期重放。

## 受限宿主描述符

group recipe 可显式加入 `period_inputs: "configs/具体描述符.json"`，并使用 `configs/period-host-template-v1.json` 填写以下宿主配置：

```json
{
  "schema_version": 1,
  "intake": "configs/实际收件清单.json",
  "policy": "configs/实际分期输入.json",
  "period_id": "2022-07",
  "native_roots": {
    "2022-07": "宿主明确准备的目录",
    "2022-10": "宿主明确准备的目录",
    "2026-10": "宿主明确准备的目录"
  }
}
```

这是格式示意，不是实际可运行数据。模板的期别/目录为 null，要求宿主明确填写；intake、policy 和 native roots 均必须在 workspace 内，描述符必须在 repository configs 下，RPC不能替换它们。

描述符可选 `snapshots: {"2022-07": {"opponent-07": {"path": ".cache/明确模型.weights", "sha256": "实际文件摘要", "model_source": "可追溯的本项目模型来源", "migration": "explicit-inference-migration"}}}`。每个条目必须对应实际 `local_snapshot` 槽；controller.model 仍是模型参数 SHA，文件 SHA 不替代模型 SHA。缺条目、未绑定来源、路径越界、未知 driver 或未使用条目均拒绝。

`load_period_host(recipe)` 仅在选项不存在时返回 None。描述符缺 `scope` 时沿用 `whole-plan`：完整编译三期 3＋8，逐期构造实际资产和规则/冻结模型对手，再精确核对分区 binding。显式 `scope: "selected-period"` 时只核 descriptor.period_id 的主槽、实际各分区对手、来源/截止/版本和实际 root/snapshot；其他期保持 `unselected_not_validated`，`formal_training_ready=false`。2026期截止现已选2026-11-01（含JST当日正式OCG发售），禁表仍2026-10-01/2026.10；截至2026-10-25仅date_selected，最终卡池未到日/未核。未选期缺资料不阻止已齐2022的单期工程运行，请求未选期会明确拒绝。整计划收件/登记要求没有因此改变，也不将缺资料自动补成当前环境。

它返回 `host.loaded/period_id/assets/for_runner/require_task/opponent_for/rebind_actor`，不启动 core 或 worker。

`semantic_curriculum.inputs` 在显式 `period_inputs` 时自动加载宿主（或复用调用者传入的 `period_host`），要求 train/validation task 都保留完全匹配的环境/截止，且 cfg.period_id 对应选定期别。源码/配置绑定加入输入 manifest 与描述符摘要。旧 `engineering-custom` 路径继续保留。

分期 group 配方必须使用已有 schema4 索引课程，否则无法提供实际对手轨迹的 DataAdmission，输入阶段明确拒绝。独立正常条件目标验证不受此课程要求限制；它仍通过分期资产的 profile 包装、精确任务校验和实际 engine factory 执行。

批量绑定策略对象时每次检查对象/卡事实/上下文封印，加载输入按期完整核物理资源，开 core 前仍再次完整核验；避免每一个同源对手都重复扫描整个脚本树。策略对象本身的建立不证明执行过原生对局。

`prepare`、`verified/restore`、阶段事务和 `save_to` 使用操作内作用域，共享一次完整加载的宿主；嵌套课程检查和四角色 adapter 检查复用同一对象。每次命中和成功退出都重新读取描述符、intake、policy、实际加载各期卡库/发行清单/禁表及 snapshot 的字节摘要，并检查路径、manifest、runtime receipt、冻结模型和内存封印；不使用 stat 捷径或跨操作缓存。异常退出也清空作用域，下一次独立入口重新完整加载。保存 checkpoint、发布准备状态及提交阶段记录前另有显式来源检查；原 `resource_binding` 与开 core 前完整资源检查保留。预算与 reserve 数值不因减少重复加载而提高。

## 固定完整WindBot构建的可选宿主配置

维护范围、源码/资源安装与完整程序集审计见[机器人部署](maintained-bot-deployment.md)。已有本地基线不依赖它；用户新增“包含全部已有机器人”交付范围另行跟踪。下面是宿主描述符的字段形状，路径与摘要必须来自真实安装/构建，不能将示意写成已通过审计：

```json
{
  "bots": {
    "2022-07": {
      "opponent-01": {
        "source_id": "ice",
        "executor_id": "ChaosRitualExecutor",
        "installed_root": ".cache/prepared-bot-sources",
        "build_audit": {"path": ".cache/bot-build/audit.json", "sha256": "<真实审计文件SHA256>"},
        "mono": "/usr/bin/mono"
      }
    }
  }
}
```

该字段加入原有完整period描述符，不是独立牌表或课程。对应收件slot必须明确 `controller:"bot"`、同一精确 `model:executor_id` 和实际factory返回的driver_version；policy绑定必须等于实际adapter.binding。`installed_root`、audit与固定lock均在workspace内，Mono是宿主明确的绝对工具路径。只支持获准的完整Ice/Pure桌面实现；lib/Android保持源码交付，不隐式运行。

`PeriodBuildAssets.bind_bot_opponent`调用完整 `BotSourceRegistry.training_adapter`，由真实源/程序集/卡库/YDK审计门禁建立 `WindBotOpponent`。`CpuTrainer.sample_episode`对该明确类型使用 `managed_engine_factory`：原PeriodNativeEngine保留日期/卡池检查、ABI与响应guard，附加宿主可见事实投影及本机房间；policy.choose只返回当前LegalAction。退出/异常关闭进程与连接。actor构筑修改后重新绑定实际profile与同一bot源码/审计，不能默默回退rule策略。

没有真实完整构建审计或资源变化时拒绝；runtime构造通过、一次对局、历史合法与策略强度是不同状态。当前云端Mono安装因系统权限和配置签名源代理403失败，未执行C#；Python socket/host fixture或正常引擎投影测试不能填成WindBot已运行。未将GPU、PC或可选LLM加为软件门槛。

## 证据边界

安全 CPU：`tests.test_period_runtime` 与 `tests.test_period_host` 使用明示合成文件和模拟物理收据，仅验证宿主门禁及普通接口，不需要 core，不用 skip 制造通过。

单独允许的真实资源检查：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest integration_tests.test_period_runtime -v`。该模块使用实际锁定卡库/禁表/已构建库、明确工程日期与允许池，实际加载三期输入和规则 baseline、冻结 DataIndex 分区；并经合法选项完成正常召唤、验证 actor 重绑后开局和精确宿主重载。新增检查实际调用 `group_runner.inputs/runtime_assets`，核对精确 seeds/profile，轮换两个实际规则对手，并通过真实 `verify_goal` 验证分期低等级通常怪兽的正常条件召唤。条件目标来自实际自己的初手，因此仅证明接口接通，不测抽到目标的概率。私有证据检查另用实际卡效路线发现并精确重放 v5 分期超量召唤，检查训练证据准入及 key 不进入监督投影；完整 baseline 对局自然结束后再通过分期 factory 精确重放。汇总留在 `.cache/pretraining-engine/period-runtime-proof.json`。没有运行完整分期 group 训练、故障注入、kill、越界/缓冲故障实验、付费训练或外部 API。

工程日期清单和当前 core 的成功调用不能认证历史发行事实、旧裁定/勘误、时期规则或驱动强度。正式三期资料、用户卡组、provider 资格和独立能力验收仍是不同事项；所有历史/官方资格标记仍 false。

冻结模型的独立正常检查为 `PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest integration_tests.test_period_snapshot -v`。它只提取本项目已经完成更新的 group `components.duel`，保留原制品和来源 SHA；这是保存时暂停 adapter 的已更新 base 组件，不称最新 LoRA。先前未训练 CPU actor 的有界采样耗尽作为失败保留，不宣称终局；该轮检查固定已有 `PublicRulePolicy` 做 actor、同一冻结模型做 opponent，不替换模型决策。两期分别绑定 2022-09-30 和 2022-12-31 的明确工程发行清单，该轮夹具中2026保持null/未选择，不改写成当时已选11月1日。实际自然终局后使用同一分期 factory 重放，并核对模型/词表重载、actor 重绑与 RNG 隔离。它不按旧 implementation binding 恢复训练器。聚合结果分别写 `.cache/pretraining-engine/period-snapshot-2022-07-proof.json` 和 `period-snapshot-2022-10-proof.json`，私有轨迹和提取模型另留当前云端缓存，不投影为 WindBot 运行资格。
