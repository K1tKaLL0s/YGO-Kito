# 2026-11-01 Phase 2A 阶段相关性审计

本轮按 v3.1 的 Phase 2 顺序，只加入第一项偏好：**fill 阶段的主轴相关性**。自肃、cost 折扣、1.2 奖励和路线传播仍未启用。官方 `implementation-validation-005` 与 Phase 1 账本保留，正式训练暂停。

## 规则

| 相关性 | fill 乘数 | 用途 |
|---|---:|---|
| main_axis | 1.0 | 珠泪主轴积木 |
| support | 0.9 | 主轴支援/终端保护/检索等 |
| generic | 0.8 | 通用 body/burn/removal/变属性 |
| off_theme | 0.2 | 只用于副卡组；副卡本身仍为 0 |

候选的通用卡块标为 `generic`（39015、114932、109401 burn、146746、44818、50755、62121、96540、98905）；珠泪卡的支援块标为 `support`（如 33878367 body、38436986 变表示、60362066 removal/recycle、74920585 negate/search、84330567 保护/无效/body、28226490 removal/body、6767771 boost/search、73956664 body、92731385 search/body）；其余主轴块保持 `main_axis`。参考牌组按同一 fill 表使用卡级映射：珠泪主轴 1.0，地天使/影依/素材代用/白雪/条件泛用 0.9，其他主/额外 0.8，副卡 0.2（副卡仍为 0）。

## 参考 raw 重算

Phase 2A 改变计分规则，因此参考牌组必须用同一规则重算：

- `reference_raw = 52.2943`（Phase 1 为 53.88025，下降 1.58595）
- `reference_score = 70`
- `threshold = 56`
- `threshold_raw = 0.8 × 52.2943 = 41.83544`（Phase 1 为 43.1042，下降 1.26876）

56 仍是参考牌组的 80%，不是固定旧分母。

## 候选结果

| 项目 | Phase 1 | Phase 2A |
|---|---:|---:|
| 候选 raw | 44.475 | **42.545** |
| 区块 raw | 36.975 | 35.045 |
| 折算分 | 57.780912 | **56.949801** |
| 56 raw 门槛 | 43.1042 | 41.83544 |
| 距 56 raw | 1.3708 | **0.70956** |
| 距 56 分 | 1.780912 | **0.949801** |

Phase 2A 下候选仍达到 56，但余量从 1.78 分缩到 0.95 分；这是 Phase 2A 版本结果，不是最终准入。

## 逐卡变化

| 卡 | Phase 1 raw | Phase 2A raw | 变化 | 标签 |
|---|---:|---:|---:|---|
| 109401 | 1.450000 | 1.160000 | −0.290000 | generic |
| 114932 | 1.450000 | 1.160000 | −0.290000 | generic |
| 39015 | 1.000000 | 0.800000 | −0.200000 | generic |
| 84330567 | 3.566667 | 3.252857 | −0.313810 | support |
| 74920585 | 2.900000 | 2.610000 | −0.290000 | support |
| 28226490 | 3.388596 | 3.219787 | −0.168810 | main/support |
| 60362066 | 2.900000 | 2.755000 | −0.145000 | main/support |
| 6767771 | 3.076168 | 2.931168 | −0.145000 | main/support |
| 38436986 | 2.534211 | 2.399211 | −0.135000 | main/support |
| 33878367 | 0.666667 | 0.642857 | −0.023810 | support |
| 73956664 | 4.438596 | 4.414787 | −0.023810 | main/support |
| 92731385 | 6.064765 | 6.112384 | +0.047619 | main_axis |
| 572850 | 5.917835 | 5.965454 | +0.047619 | main_axis |

92731385 和 572850 的小幅上升来自通道 cap 再分配，不是新增来源。净变化 `−1.93 raw / −0.831111 分`；参考 raw 同步下降，因此 56 门槛也下降，候选仍过线。

## 代码与数据

- `reference_scoring.Block` 新增可选 `relevance`；`Policy` 新增 `stage`、`stage_relevance`、`relevance_by_key`；`score_construction` 在 block offer 和 unit witness factor 上应用相关性，并记录 `relevance`/`relevance_factor`/`pre_relevance_offer`。
- `CourseAdmissionPolicy` 新增 `stage`/`stage_relevance`/`relevance_by_key`；只有启用 stage 时才把这些字段加入 binding，避免改变旧 epoch 的 binding。
- 私有 `unit-block-v3-phase2a`：Phase 1 副本 + 逐块 generic/support 标签 + `stage-relevance.json`；参考 raw 更新为 52.2943。
- 新增 `tests/test_phase2a_stage_relevance.py` 3 项，并加入 CPU 白名单。

## 测试状态

- 39 项既有定点测试通过。
- Phase 1 新增 3 项通过。
- Phase 2A 新增 3 项通过。
- 完整 CPU 白名单 **Phase 2A 代码改动后尚未重跑**；`implementation-safe-cpu-007`（1035 项）是 Phase 1 结果，不能用来宣称 Phase 2A 全量通过。

## 判断与剩余项

Phase 2A 证明了一个重要点：相关性同时压低候选和参考，56 门槛会跟着下降，因此不能只看候选分数下降就断言“变差”；但候选余量只剩约 0.95 分，后续自肃和 cost 折扣很容易把它推下 56。

尚未启用：自肃四档与传播、cost 资源折扣、1.2 CB 奖励、每效果路线绑定参与计分、互斥路线合计限制。下一步建议先补 Phase 2A 的完整 CPU，再决定 Phase 2B 自肃是否加入；不要用当前 56.95 作为最终准入。

## 证据

- `N:\YGO-Kito\_local_cpu_20261027\reports\optimization-20261031\phase2a-audit-001\summary.json`
- `...\phase2a-audit-001\candidate-score.json`
- `...\phase2a-audit-001\reference-raw.json`
- `N:\YGO-Kito\evaluator-private\reference-scoring\unit-block-v3-phase2a\phase2a-manifest.json`
