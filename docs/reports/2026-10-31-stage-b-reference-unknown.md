# 2026-10-31 Stage B (partial): unknown-aware reference feedback

本报告记录阶段 B 的两项实际结果：未知不再被当作零分/低分失败，以及 2207 候选在私有 70/56 参考下的真实评分。没有启动对局或训练。

## 私有评测数据与参考锚

- 已把 2026-10-29 交付的 `reviewed_semantics.json`、`calibration-manifests.json` 放到仓库外：
  `N:\YGO-Kito\evaluator-private\reference-scoring\`
- 根仓库 `.gitignore` 增加 `/evaluator-private/`；learner 输入不含参考牌表、语义库或私有审计。
- 2207 参考锚仍为 `reference_score=70`、`reference_raw=52.078062`、阈值 `56`；未改动校准字节。

## 实际候选评分（迁移后 2207）

候选来自 `2207-course-006/pre-policy-construction.weights`（迁移前的 40 主 + 15 额外 + 15 副），任务与牌表哈希：

- `task_sha256=b0323b78...`
- `deck_sha256=33db9296...`

评分结果（私有 audit）：

| 项 | 值 |
|---|---:|
| 正式分 | 5.156442 / 100 |
| 参考 raw | 52.078062 |
| 候选 raw | 3.83625 |
| 阈值 | 56.0 |
| 合法性 | legal |
| 已复核的当前有效功能 | 3 |
| 活跃区未知功能 | 33 |
| 轴/副轴/联动/泛用/条件泛用 | 全部 0 |
| `construction_semantics_status` | `scoped_functions_partially_reviewed` |

结论：当前候选的正式分远低于 56，但其中 33 个活跃功能仍是未知，3 个已复核功能不足以证明真实低分；因此本轮不再把 5.16 当作“低分失败”。

## 未知处理修正

- `Block.factor()`：`unavailable` 仍为已知 0；`unknown` 或任一所辖知识域未知返回 `None`，不再返回 0。
- `score_construction`：未知积木不参与求值，记入 `unknowns`；已复核积木仍形成部分 raw 分，但不再被当作完整评分。
- `CourseAdmissionPolicy`：
  - 缺卡文或没有任何已复核活跃功能 → `score=None`、未知；
  - 有未知活跃功能 → 保留部分分数，`force_optimization=False`、`context_review_required=True`、语义状态 `scoped_functions_partially_reviewed`；
  - 只有完整复核且低于 56 才 `force_optimization=True`。
- `reference_scoring_feedback`：未知/部分评分不进入 hint 计数、不累计失败；返回 `context_review_required=True`。
- 准入：历史期返回 `deferred`，原因 `construction_context_review_required`；`optimization_requested=False`、`hint_permission=False`。未把它写成低分强制优化。

同一候选的前后对比：

| | 修正前 | 修正后 |
|---|---|---|
| 分数 | 5.156442 | 5.156442（仅作部分参考） |
| 强制优化 | true | false |
| 未知/部分 | 记作低分路径 | `context_review_required=true` |
| 提示计数 | 可推进 | 不推进 |
| 准入原因 | `construction_score_below_reference_ratio` | `construction_context_review_required` |

## 验证

- `tests.test_reference_scoring`、`tests.test_course_admission_policy`、`tests.test_reference_hints`、`tests.test_reference_scope_revision`、`tests.test_restore_compatibility`：53 项通过。
- `tests.test_course_admission_loop`、`tests.test_forecast_twenty_fifty`、`tests.test_reference_integration`：19 项通过；`PrivateReferenceIntegrationTest` 需要未包含在公开树中的私有报告，仍按原发布说明单独排除。
- 真实 2207 评分探针在 WSL `venv-linux` 上运行，未执行引擎、未训练。

## 阶段 B 未完成

- B5 的“每个积木默认基础 1 分 + 目标主题动态赋分”尚未替换现有珠泪先验；替换后必须重算 2207/2210 的 `reference_raw`，不能沿用 52.078062 / 54.651347。
- B4：当前候选的效果情境只覆盖少量已复核功能（3 个），33 个活跃未知；需按当前构筑逐卡补条件/费用/次数/资源/冲突。
- B6：积木搭路线→填实际卡→合法性→最终得分的顺序和成功基础 CB 仍未接入；基础 CB 准入门槛保持。
- 因此阶段 C（真实学习循环、20/50 绑定、调度防饥饿）尚未开始。
