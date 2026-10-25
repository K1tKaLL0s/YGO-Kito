# 三期训练输入编译、加载与隔离

`training_input.py` 连接用户 [3＋8 收件](deck-intake.md) 与已有 profile、对手绑定和 `DataIndex`。它提供实际可加载的数据对象，不另建采样器、训练器或恢复架构，不生成监督/对局，不启动原生核心或 provider。

没有 `period_inputs` 时，既有 `semantic_curriculum.inputs` 继续接受原 `engineering-custom` 课程并现场登记工程本地规则对手，group runner 沿用原固定 task/profile 路径。新增的显式宿主路径按 scope 加载资料：默认 `whole-plan` 要求完整 3＋8/三期，显式 `selected-period` 只消费所选期的实际主槽/对手、资源与已实现驱动，保留截止并核对课程和采样种子。普通 `BuildAssets` 仍不能通过改 period 名称或清空截止获得三期资格。

## 显式输入

`configs/user-training-input-template-v1.json` 是空白策略模板。默认 whole-plan 每期显式指定一个主卡组槽、实际六项 `Versions`、已有 adapter revision，以及 `train/validation/final_eval` 各自的对手、游戏 seeds 和 policy RNG seed。完整计划要求三个主槽、八个对手槽都被明确使用；selected-period 只要求该期实际用到的槽和三个分区，不据此宣称完整计划齐备。不默认划分比例或种子，不通过槽位改名制造独立终验。

每个对手条目为 `{slot_id, binding}`。`binding` 使用现有 `FrozenOpponent.binding` 完整格式：牌表内容、驱动实现摘要/版本、快照模型摘要及双方实际 profile 绑定。它必须与收件牌表、控制方和当期归属相符。用户输入与合成契约输入通过策略的 `source` 分开，不能将 `engineering_fixture` 绑定放进 `user_supplied` 配置。

默认 whole-plan 的 `compile_training_inputs(intake, policy, workspace)` 会重新检查三期来源文件和 11 份资料。缺任何资源/截止/分区/版本只返回 `pending_input`；矛盾或泄漏直接拒绝。编译结果保留每期完整截止和三源摘要，`formal_training_ready` 保持 false。

显式传入 `selected_period="2022-07"` 时只编译该期主槽及各分区实际选用的对手、来源、截止与版本；不要求其他期卡池已经核验或已经收到其他主槽。manifest 标记 `scope="selected-period"`，未选期为 `unselected_not_validated`，仍不表示完整计划就绪。`load_training_inputs(..., runtime_assets={"2022-07": actual_runtime}, selected_period="2022-07")` 要求 runtime 键集精确等于该 scope，访问未选择期通过 ContractError 拒绝。省略参数继续要求完整三期 3＋8；全计划收件/登记不会部分放行。2026期已选2026-11-01截止（含JST当日正式OCG发售），禁表仍2026-10-01/2026.10；截至2026-10-25最终池仍待到日及来源核验，不阻塞未选择它的2022单期工程运行。

隔离沿用现有 `opponent_identity`：同一排序牌表内容＋驱动实现/版本＋模型快照不得跨 train/validation/final_eval，改 opponent ID 或调整牌序无效。物理版本相同的游戏种子不能跨目的重用，card_pool 显示标签不改变此规则。DataIndex 后续在真实数据入库时还会重新检查，编译阶段不造空 episode 占位。

## 真实加载与 group runner 钩子

```python
from ygo_kito.training_input import load_training_inputs

loaded = load_training_inputs(intake, policy, workspace,
    runtime_assets={"2022-07": july_runtime, "2022-10": october_runtime,
                    "2026-10": current_period_runtime})
selection = loaded.for_runner("2022-07", "train", episode_cursor=0)
# selection: assets、实际 DeckParts、Versions、旧格式 profile、opponent_binding、
# 游戏 seed、policy_seed、dataset_spec 与完整 period_context。
loaded.freeze_partition(existing_data_index, "2022-07", "train")
```

每个宿主 runtime 必须明确具备：

- `period_context`：`period_id/release_cutoff/catalog_sha256/release_manifest_sha256/banlist_sha256/banlist_section`，精确匹配本期。
- `environment`：保留真实 `release_cutoff` 与精确 `versions`，不能投影成当前环境的 null 截止。
- `receipt`：实际 core commit、scripts、cards、client_protocol、banlist 资源摘要。
- 真实 `rows/limits`：加载器独立对照提供的历史卡库/禁限，并重验双方牌表。
- `assert_training_opponent(binding, profile)`：对照实际注册器及驱动验证 FrozenOpponent 绑定，缺此方法拒绝；单纯配置一个 hash 不能启用驱动。选择每条采样输入时再次核对该绑定。

加载后的 profile 可直接由现有 `group_runner.profile_deck` 等输入函数消费；`dataset_spec` 直接交给现有 `DataIndex.freeze`。`freeze_partition` 只冻结指定目的的数据集元数据，未生成任何轨迹或标签。返回数据为副本，篡改已加载 manifest 会被摘要门禁拒绝。`require_task(period, task)` 要求现有构筑 task 原样保留历史截止，随后由实际资产检查；不会生成伪历史 task。

group runner 的显式 `period_inputs` 描述符由 [period_host](period-runtime.md) 加载；它取实际 profile/对手和版本，并把输入摘要、截止和物理来源加入原运行/恢复绑定。此路径只接受已有 schema4 `indexed-semantic-course-v1`，由其 DataIndex 对真实对手轨迹执行数据准入；缺该课程的旧配方明确拒绝。train seeds 必须逐项等于 bootstrap seed 加配方推导的适配 seeds，validation seeds/policy_seed 必须精确匹配；训练 policy_seed 使用所声明分区值，冲突拒绝。

原阶段事务、DataIndex 快照和 PPO fresh-data 准入继续使用。bootstrap 选择对手游标 0，适配阶段按已提交 duel 更新数加 1 选择对手，validation 按实际 seed 序号选择；不会沿用首个对手填充其他分区。构筑后 actor 牌表改变时由真实宿主重新绑定 FrozenOpponent/profile，再冻结相应数据集；数据集 ID 包括 actor 和实际对手身份，不能沿用原主卡组的 `own_deck_sha256/profile_sha256`。本模块不会静默改原训练配方或启动本地 worker。

## 外部依赖与测试证据

现有普通 `BuildAssets` 没有历史 `period_context`，会被此加载器拒绝。新增 `PeriodBuildAssets/PeriodNativeEngine` 实际核对锁定物理资产，并显式使用所选禁限节、发行允许池和保留截止的环境；宿主 loader 接入已有规则 baseline，以及明确 artifact/model SHA、来源和推理迁移的 `local_snapshot/frozen-duel-greedy-v1`。bot/external_llm 未接实际传输时仍拒绝，不回退为本地模型。真正历史来源、旧裁定/勘误与具体驱动资格仍须验证。合成兼容对象仅存在于测试，生产没有 fallback；用户牌表、来源/截止日期及外部模型资格也不能由模板填充。

安全测试命令：`PYTHONPATH=src .cache/ci-cpu-venv/bin/python -m unittest tests.test_training_input tests.test_period_runtime tests.test_period_host -v`。测试使用明示合成文件/runtime，真实调用旧 profile DTO、group 输入检查和 DataIndex 数据集冻结，验证缺资源关闭、跨期/跨目的隔离及拒绝当前环境冒充；不加载规则核心、不造训练 episode、不运行缓冲故障测试或外部 API。单独的真实资源模块验证宿主和 group 输入、精确采样种子、两个真实规则对手的轮换、分期正常条件目标；它没有运行完整分期 group 训练或作历史规则认证。
