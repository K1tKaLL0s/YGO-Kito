# 2026-11-01 Phase 1 确定性修复与审计

本轮按 v3.1 的 Phase 1 范围执行：只做确定性修复，不启用相关性、自肃、cost 折扣或 1.2 奖励。官方 `implementation-validation-005` 的 59.210007 账本保留，正式训练仍暂停。

## 范围与改动

**代码**

- `src/ygo_kito/candidate_context.py`
  - `resource_count` 新增 `exclude_card_id` / `allow_self`；默认排除被审阅卡自身，避免额外卡组复制满足自己的素材条件。
  - 静态牌表不能证明 `hand` / `field` / `grave` / `banished` / `opponent_field`；这些区域不再按主/额外牌表计数，等 CB 路线证明。
  - 未知区域仍然 fail closed。
- `tests/test_phase1_deterministic_fixes.py`：覆盖自排除、允许自身、非牌表区域、未知区域。
- `scripts/check_merge_candidate.py`：把新增测试加入显式 CPU 白名单。

**私有审阅**

新增 `evaluator-private/reference-scoring/unit-block-v3-phase1`（v2 的 Phase 1 副本）：

- `102380` 熔岩魔神：撤销错误的 `removal` 块。该块 quote 是准备阶段 1000 伤害的维护效果，`requires` 为空；真实的条件性去除属于“对方 2 只怪兽”的召唤手续，Phase 1 不评分，等待重新审阅。
- `146746` 机关重联 愤怒钩舌：由评分器自排除；额外卡组 3 张自身不再满足“2 只机械族”素材条件，主卡组没有机械族素材，body 归零。
- `109401` 暗次元的战士：body ① 要求**除外的暗属性怪兽**，静态牌表不能证明除外区，body 归零；burn ② 作为独立路线保留 1.45 raw，不随 body 一起清零。

动作来源与路线描述在 `phase1-audit-001/action-routes.json`：记录 effect resolution / activation cost / summon procedure without effect / continuous 区分，以及 102380、146746、109401、114932、572850 的路线。Phase 1 **只记录，不把动作来源或路线状态用于加权**。

## 参考 raw

用当前 Phase 1 代码路径重算 2022-07 参考牌组（`reference_example=True`，unit priors）：

- `reference_raw = 53.88025`
- `reference_score = 70`
- `threshold = 56`
- `threshold_raw = 0.8 × 53.88025 = 43.1042`
- 参考牌组 41 张，包含 102380 / 146746 / 109401 / 39015 / 114932 中的 **0 张**；Phase 1 的自排除/区域修复不改变参考路径。
- 证据：`phase1-audit-001/reference-raw.json`。

## 候选 raw 与 56 门槛

| 项目 | v2 官方 | Phase 1 |
|---|---:|---:|
| 候选 raw | 45.575 | **44.475** |
| 区块 raw | 38.075 | 36.975 |
| 折算分 | 59.210007 | **57.780912** |
| 56 raw 门槛 | 43.1042 | 43.1042 |
| 距 56 raw | 2.4708 | 1.3708 |
| 距 56 折算分 | 3.210007 | 1.780912 |

Phase 1 下候选仍达到 56（`score_threshold_met=true`），但这是 **Phase 1 版本结果**，不是 Phase 2 最终准入；Phase 2 每改一次规则都要重新重算参考 raw。

## 三个问题积木的前后解释

| 卡 / 块 | v2 raw | Phase 1 raw | 说明 |
|---|---:|---:|---|
| 102380 removal | 1.333333 | 0 | 错误 quote/空条件，整块撤销；真实条件性去除待重审，不再无条件计分。 |
| 146746 body | 0.500000 | 0 | 自排除后无 2 只机械族素材；主卡组无机械族，body 不可用。 |
| 109401 body | 0.500000 | 0 | 要求除外暗属性，静态牌表不能证明；body 归零。 |
| 109401 burn | 1.450000 | 1.450000 | 作为独立路线保留；body 的错误不连带清零 burn。 |

直接移除的块合计 `2.333333` raw。由于通道上限会把释放的额度重新分配给同通道其他卡，其他卡合计回升 `1.233333` raw；最终净变化 `-1.100000` raw / `-1.429095` 折算分。不能把问题卡贡献逐项相减来解释净分数。

发生再分配的卡（非修复目标）：`28226490`、`84330567`、`92731385`、`33878367`、`572850`、`60362066`、`73956664`。这是通道 cap 的正常行为，不是新的得分来源。

## 测试状态

- 定点测试：`tests.test_optimization_20261031`、`tests.test_course_admission_policy`、`tests.test_reference_scoring` 共 **39 项通过**。
- 新增 Phase 1 测试：**3 项通过**。
- 新增测试已加入 `scripts/check_merge_candidate.py` 白名单；Phase 1 代码改动后的完整 CPU 白名单 `implementation-safe-cpu-007` 为 **1035 项、0 失败、0 错误、0 跳过、success=true**（墙钟约 2343 秒）。

## 未纳入 Phase 1

以下属于 Phase 2，本轮未启用：

- 主轴相关性（axis generic 0.25 / fill generic 0.8）；
- 自肃四档与自肃传播；
- cost 资源折扣与 1.2 CB 验证奖励；
- 每效果路线绑定参与计分（Phase 1 只有描述性 `action-routes.json`）；
- 互斥路线/备选能力的合计限制。

## 当前判断

Phase 1 的确定性修复已落地：三个错误计分来源被撤销或修正，参考 raw 与 56 raw 门槛同规则重算，候选 raw 44.475、折算 57.780912，仍高于 43.1042 / 56。下一步应先补完整 CPU 白名单，再决定 Phase 2 是否加入相关性、自肃、cost 偏好；不能把 Phase 1 的 57.78 当作 Phase 2 最终结论。

官方 005 账本、正式检查点、hold 与正式学习计数均未改动；未提交、推送或合并。

## 证据路径

- `N:\YGO-Kito\_local_cpu_20261027\reports\optimization-20261031\phase1-audit-001\summary.json`
- `...\phase1-audit-001\reference-raw.json`
- `...\phase1-audit-001\action-routes.json`
- `N:\YGO-Kito\evaluator-private\reference-scoring\unit-block-v3-phase1\phase1-manifest.json`
