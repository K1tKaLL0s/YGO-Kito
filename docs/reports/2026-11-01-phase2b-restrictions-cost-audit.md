# 2026-11-01 Phase 2B/2C 自肃与 cost 折扣审计

本轮在 Phase 2A 阶段相关性之上，启用**块级自肃因子**与**静态 cost 折扣**；1.2 的 CB 验证奖励仍不进入 construction_score。官方 005、Phase 1/2A 账本保留，正式训练暂停。

## 规则

- 自肃：块级 `restriction_factor`，0.5 conflicting、0.8 non-impacting/acceptable；支持 `restriction_group` 传播（同组取最小因子）。本轮候选与参考没有需要跨卡传播的计分块，组机制以合成测试覆盖。
- cost：非本家 cost 且无已验证触发 → 0.8；主轴/本家无触发 → 1.0；1.2 仅 CB 验证后另算，construction 拒绝 `cost_discount > 1.0`。
- 主题级自肃：珠泪没有固有额外自肃；“额外全融合”是构筑选择，不是主题锁。俱舍式固有锁不在本轮牌表中。

## 参考 raw 重算

| 项目 | Phase 2A | Phase 2B/2C |
|---|---:|---:|
| reference_raw | 52.2943 | **49.808332** |
| reference_score | 70 | 70 |
| threshold | 56 | 56 |
| threshold_raw | 41.83544 | **39.8466656** |

参考牌组下降 2.485968 raw，原因是若干参考卡的锁/费用被折扣；56 仍是参考的 80%。

## 候选结果

| 项目 | Phase 2A | Phase 2B/2C |
|---|---:|---:|
| 候选 raw | 42.545 | **42.052** |
| 区块 raw | 35.045 | 34.552 |
| 折算分 | 56.949801 | **59.099349** |
| 距 56 raw | 0.70956 | **2.2053344** |
| 距 56 分 | 0.949801 | **3.099349** |

候选择折算分上升，但不是因为候选更强：参考 raw 下降更多，56 门槛随之下降。候选 raw 本身下降 0.493。

## 逐卡变化

| 卡 | Phase 2A raw | Phase 2B raw | 变化 | 原因 |
|---|---:|---:|---:|---|
| 28226490 | 3.219787 | 2.647454 | −0.572333 | 自肃 0.8（不能作为融合素材；对目标角色非阻断） |
| 114932 | 1.160000 | 0.928000 | −0.232000 | cost 0.8（非本家 cost、无已验证触发） |
| 84330567 | 3.252857 | 3.274207 | +0.021349 | 通道 cap 再分配 |
| 92731385 | 6.112384 | 6.204287 | +0.091903 | 通道 cap 再分配 |
| 33878367 | 0.642857 | 0.664207 | +0.021349 | 通道 cap 再分配 |
| 38436986 | 2.399211 | 2.462689 | +0.063479 | 通道 cap 再分配 |
| 572850 | 5.965454 | 5.989176 | +0.023722 | 通道 cap 再分配 |
| 73956664 | 4.414787 | 4.504318 | +0.089531 | 通道 cap 再分配 |

39015 的 Synchro 锁在 body 上（body 已为 0），109401/44818 的 cost 折扣落在已为 0 的块上，因此当前候选没有额外的可见下降。

## 自肃与 cost 明细

- 候选：28226490 全块 0.8；39015 ① body 0.5（body 0）；146746 全块 0.5（不可用）。
- 参考：94977270/83326048 0.5；34267821/21044178/98829635/27519978/27381364 0.8。
- cost：114932 0.8；39015 body 0.8（0）；109401 body 0.8（0）；44818 0.8（0）；参考按 `block.costs and relevance != main_axis → 0.8`。
- 1.2：未应用。当前候选没有“本家 cost 本家 + 实际触发”的已验证块；1.2 需要 CB 证据，属于构造分之外的独立奖励。

## 代码与数据

- `Block` 新增 `restriction_factor`、`cost_discount`、`restriction_group`；`Policy` 新增 `apply_restrictions`、`apply_cost_discount`、`restriction_groups`；`score_construction` 在 relevance 之后应用，并记录审计字段。
- `CourseAdmissionPolicy` 新增对应参数；只有启用时才写入 binding。
- 私有 `unit-block-v3-phase2b`：Phase 2A 副本 + 块级自肃/cost 因子 + `phase2b-manifest.json`；参考 raw 更新为 49.808332。
- 新增 `tests/test_phase2b_restrictions_cost.py` 4 项（含自肃组传播与 construction 拒绝 1.2），加入 CPU 白名单。

## 测试状态

- 39 项既有定点测试通过。
- Phase 1 3 项、Phase 2A 3 项、Phase 2B 4 项通过。
- 最终 Phase 2 代码的完整 CPU `implementation-safe-cpu-009`：**1042 项、0 失败、0 错误、0 跳过、success=true**（墙钟约 2229 秒）。`008` 因启动后代码又加入 restriction group 而被终止，不计通过。

## 判断与剩余项

Phase 2B/2C 的机制已落地：自肃因子、组传播、cost 折扣、1.2 拒绝进入 construction。当前候选在 Phase 2 最终规则下为 **42.052 raw / 59.099349 折算**，仍过 56；但这主要是参考 raw 下降带来的校准效应，不是候选强度提升。

剩余：完整 CPU 009、102380 真实条件性去除重审、每效果路线绑定参与计分、互斥路线合计限制、未取得 CB 的候选标 `unverified`、1.2 的 CB 验证奖励。正式训练仍暂停；官方 005/检查点/hold/计数未改。

## 证据

- `N:\YGO-Kito\_local_cpu_20261027\reports\optimization-20261031\phase2b-audit-001\summary.json`
- `...\phase2b-audit-001\candidate-score.json`
- `...\phase2b-audit-001\reference-raw.json`
- `N:\YGO-Kito\evaluator-private\reference-scoring\unit-block-v3-phase2b\phase2b-manifest.json`
