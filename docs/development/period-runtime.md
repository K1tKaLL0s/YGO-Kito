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

`load_period_host(recipe)` 仅在选项不存在时返回 None。存在但资料未齐直接报错：先完整编译，随后构造三个实际 `PeriodBuildAssets`，逐分区实际生成 baseline adapter 与已冻结 binding 精确比对，最后调用 `load_training_inputs`。它返回 `host.loaded/period_id/assets/for_runner/require_task/opponent_for/rebind_actor`，不启动 core 或 worker。

`semantic_curriculum.inputs` 在显式 `period_inputs` 时自动加载宿主（或复用调用者传入的 `period_host`），要求 train/validation task 都保留完全匹配的环境/截止，且 cfg.period_id 对应选定期别。源码/配置绑定加入输入 manifest 与描述符摘要。旧 `engineering-custom` 路径继续保留。

分期 group 配方必须使用已有 schema4 索引课程，否则无法提供实际对手轨迹的 DataAdmission，输入阶段明确拒绝。独立正常条件目标验证不受此课程要求限制；它仍通过分期资产的 profile 包装、精确任务校验和实际 engine factory 执行。

批量绑定策略对象时每次检查对象/卡事实/上下文封印，加载输入按期完整核物理资源，开 core 前仍再次完整核验；避免每一个同源对手都重复扫描整个脚本树。策略对象本身的建立不证明执行过原生对局。

## 证据边界

安全 CPU：`tests.test_period_runtime` 与 `tests.test_period_host` 使用明示合成文件和模拟物理收据，仅验证宿主门禁及普通接口，不需要 core，不用 skip 制造通过。

单独允许的真实资源检查：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest integration_tests.test_period_runtime -v`。该模块使用实际锁定卡库/禁表/已构建库、明确工程日期与允许池，实际加载三期输入和规则 baseline、冻结 DataIndex 分区；并经合法选项完成正常召唤、验证 actor 重绑后开局和精确宿主重载。新增检查实际调用 `group_runner.inputs/runtime_assets`，核对精确 seeds/profile，轮换两个实际规则对手，并通过真实 `verify_goal` 验证分期低等级通常怪兽的正常条件召唤。条件目标来自实际自己的初手，因此仅证明接口接通，不测抽到目标的概率。私有证据检查另用实际卡效路线发现并精确重放 v5 分期超量召唤，检查训练证据准入及 key 不进入监督投影；完整 baseline 对局自然结束后再通过分期 factory 精确重放。汇总留在 `.cache/pretraining-engine/period-runtime-proof.json`。没有运行完整分期 group 训练、故障注入、kill、越界/缓冲故障实验、付费训练或外部 API。

工程日期清单和当前 core 的成功调用不能认证历史发行事实、旧裁定/勘误、时期规则或驱动强度。正式三期资料、用户卡组、provider 资格和独立能力验收仍是不同事项；所有历史/官方资格标记仍 false。
