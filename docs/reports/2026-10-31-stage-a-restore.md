# 2026-10-31 Stage A: restore version and explicit course migration

本报告只记录阶段 A（运行版本、恢复兼容、中断事务）。没有启动真实对局、PPO、优化器更新或新的训练；旧状态目录保持只读。

## 运行版本

- 工作分支 `codex/optimization-20261031`，基线 `origin/main` = `d01f07f`（PR #8 已合并）。
- `origin/main`、publication 分支和 PR #8 head 的 tree 同为 `00b08698ea4db147c4909bb92aefba619133deea`；既有修复已在 main，不再重复合并。
- 旧运行源 `_local_cpu_20261027/source` 只用于复现旧 checkpoint；新代码从 `_publish_20261030` 执行。

## 旧状态导出

在旧的 `formal-course-source-006` 运行时（WSL，`venv-linux`）中恢复：

- 源状态：`source/.cache/local-base-training-20261027/2207-course-005`
- 恢复结果：revision 16、`desired=ready`、27 条对局记录
- 导出：`reports/optimization-20261031/old-course-export.weights`（8,166,191 字节）
- 旧构建特征版本：`build-task-catalog-candidate-v5-combined-native-objectives`
- 旧 kernel 版本：`autonomous-catalog-task-course-v1`

## 显式迁移

使用 `scripts/migrate_coordinator_course.py` 的 `migrate_closed_course`，目标：

`reports/optimization-20261031/2207-course-006`

- 父 checkpoint SHA-256：`31784ea14850c4b458707af2f8b4b7fdda9f0c01d0e064acc3996125b7371e53`
- 源变更：48 个文件（新增模块与此前修复；逐项记录在 `coordinator-migration.json`）
- 构建：显式 v5→v6 迁移；旧张量与 Adam 矩保留，新 `mechanism` 投影零初始化、Adam 槽惰性
- kernel：v1→v2，`basic_cb_stage=after_construction`、`construction_flow=four_concrete_handoffs_then_basic_cb_inference_v3`
- 统筹：显式 v1→v2 聚合状态扩展；新增投影零初始化，旧张量/Adam/RNG 未变
- 学习状态：`build_goal=5`、`build_optimizer=0`、`duel_updates=27`、`coordinator_updates=37` 全部保留
- 计数器：`training_attempts.next_cursor=27`；无 legacy acknowledgment（见下）
- `training_executed=false`、`resume_authorized=false`、`optimizer_steps_added=0`、`active_seconds_added=0`
- 新代最终状态：`desired=paused`、revision 1；`course.save()` 后 `restore_latest()` 再次通过
- 旧 `selection/deck/construction` 被明确过渡清除；原文保存在 `pre-policy-construction.weights`，旧对局记录未改写、未重标为修复流程

## 中断事务（第 46 次）

唯一未完成记录是 `pearl-base-2207-v1-train-22`（24 局旧流程 + 本课程第 22 次 = 总第 46 次）：

- `status=aborted`，`complete=false`，`winner=null`
- receipt：`status=failed_or_uncertain`，错误为 `CPU sample budget exhausted; no terminal reward/update claimed`
- `sample_completed/model_update_started/model_update_completed` 全为 `false`；观察到 `training_cursor=22` 前后不变
- seed 701023 已隔离，下一 seed 701024
- 迁移保留该记录原字节，不计完成成绩、不重试、不补轨迹；新代 attempts 从 27 继续

该记录位于 corrected-flow offset 之前（归档区），不进入当前整改课程的准入记录。`migrate_legacy_attempt_gap_state` 另提供直接恢复旧 checkpoint 时的精确无更新确认路径，并有测试覆盖。

## 恢复兼容性

新增 `src/ygo_kito/restore_compatibility.py`：

- 课程绑定的 `source_map` 与模型绑定的 `source_files` 只作审计；不再作为恢复门禁
- 结构化比较保留：课程配置、模型 task/resources/period/vocabulary、规则 `rules_sha256`、bots、恢复所需数据
- 结构域变化返回具体原因；源文件增删/改行只在 `source_drift` 中报告
- `ScenarioCourse.restore_latest`、`CourseModels._candidate`、`local_foundation_course` 使用同一规则
- checkpoint 自身 `state_sha256`/`binding_sha256`、权重/优化器形状与 RNG 仍逐项核验

直接以新代码恢复 v5 旧 checkpoint 会在 vocabulary 检查处失败（预期），必须走上述显式迁移；迁移后的新代恢复已实际通过。

## 验证

- 新增 `tests/test_restore_compatibility.py`：6 项通过
- 相关模块：`test_scenario_course` 的迁移/部分证据/构造完成 3 组共 13 项通过；`test_course_models`、`test_training_admission`、`test_forecast_twenty_fifty` 与新增测试合计 28 项通过
- Windows 上完整 `test_scenario_course` 在 `ScenarioCourseTests` 处发生原生 0xC0000005，未据此判为代码通过；完整套件仍须在 Linux CI 运行
- 旧的 `2207-course-005/course/latest.json` 未变（仍为 checkpoint-16）
- 没有绑定 admission policy、没有调用 `CourseForecast`、没有执行 `course.run`

## 尚未完成

- 旧源与冻结 tar 的运行路径切换尚未整体替换到新代入口（迁移已证明新代码可承接）
- `observed_bot_source_review`、`source-drift.json` 和真实 bot 复验留到后续阶段
- 正式训练 hold 保持；`course-006` 为 paused，未授权 resume
