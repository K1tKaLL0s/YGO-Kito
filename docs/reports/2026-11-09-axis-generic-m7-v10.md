# M7 V10 回收时序与资源复用实际验收

日期：2026-11-09，香港时间。用户允许对应测试及必要导入，继续禁止正式训练、真实资料准备、CB、原生引擎和 CI。先交付[V10 机械执行补充](execution/2026-11-09-axis-generic-m7-v10-execution-supplement.md)，再由主进程直接实施，无子代理，保留全部现有及并行改动。

## 实际结果

使用完整仓库 `N:\YGO-Kito\_publish_20261030`、既有分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`。已有 `E:\Ana\envs\pcacgate\python.exe` 实际为 Python 3.10.20；没有安装依赖或加载 Torch。

新增[专用测试模块](../../tests/test_multifactor_v10_resources.py) `V10ResourceRecoveryTests` 的五个方法首次全部通过：5 个明确选择、5 个实际运行、5 个成功，0 failure/error/skip/loader error，退出码 0，禁止动作尝试为空。运行器耗时约 0.286 秒（含必要导入，不作为性能验收）。没有源码失败或修复。

| 方法 | 实际对照及通过结果 |
|---|---|
| `test_recovery_is_available_only_at_its_declared_stage` | activation 的初始消耗和 post_resolution 的显式回收后消耗可共存；缺回收、过早 resolution、错误手牌区域和对手资源均失败。两个消耗保留同一实体追踪 ID、不同可用库存批次和原来源；输入不变 |
| `test_recovered_stock_and_aliases_do_not_duplicate_a_copy` | 同一回收库存的两个 selector 观察只有一份容量，不能支付两份请求；consume 和 distinct reusable 两种模式都拒绝复用同一槽，明确第二实体后才通过 |
| `test_unknown_or_unobserved_recovery_keeps_the_result_unknown` | 开放观察/known=False 回收结果保持 None，完整缺失为 False，明确 known 回收为 True；unknown 回收不进入已知消耗证据 |
| `test_occupancy_release_and_retention_have_explicit_boundaries` | occupy/retain 到 resolution 的预约在结束阶段仍有效，post_resolution 才可消耗；缺 available_until 不延长库存可用期，预约 mode/start/end 和同槽证据保持 |
| `test_recovery_does_not_reset_a_named_use_limit` | 回收后的卡库存不会重置同名有限额度；两个额度观察共用同一 pool 时第二次拒绝，显式独立名称额度才允许两次调用，四份卡/额度消耗各自占用不同槽 |

本批新增五个方法与先前 187 个通过 ID 的交集为 0，累计 192 个不同方法已有通过结果，累计物理执行 231 次（226＋5）。此前 Q1–Q5 的通过和失败/复验历史直接承接[Q5 汇总](2026-11-09-axis-generic-m7-q5.md)，没有重复旧业务集合。

## 证据含义和运行范围

生产求解器本批没有修改。显式回收输出作为新的可用库存批次提供，资源 source/stage/known 与同一实体追踪 ID 完整保留；同名限制使用独立的有限额度资源。求解器实际验证所给事实的分配、时序和冲突，真实卡效产生这些事实的规则正确性仍属于相应宿主/原生阶段。

运行仅导入标准库、轻量契约和条件求解模块。import/子进程审计及结束模块检查均为空：没有 Torch、模型前向/反向、工程更新、checkpoint I/O、正式训练或资料准备模块、CB/原生运行模块和子进程。没有运行真实资料准备、CB/provider/搜索、原生引擎或 CI；没有读取旧 runs、权重或数据库，活动/暂停/课程指针及 LoRA 不变。

## 文件、保护与回执

唯一新增的长期编程文件是上述五方法模块，既有生产源码及测试没有修改。新增本报告和机械补充，增量同步主计划当前状态及第 9 节、M7 A04/V10/当前剩余和 MASTER 末尾。主计划第 2–8 节、M7 历史/能力设计段及 MASTER 原有/并行内容保留。

`.cache/axis-generic-m7-v10-20261109-01` 内的 `selections.json` 为五个明确方法 ID，`v10-result.json` 与 stdout/stderr 为首次原始结果，`acceptance-summary.json` 为本批/累计去重集合，`manifest.json` 登记三共享文档的修改前字节保存。最终新链接、方法与保护段落、空白和 tracked 差异检查见 `document-review.json`。没有全仓重建、重复哈希或权重备份。

V10 先前列出的单独运行证据缺口已由本批闭合，当前授权内 M7 选定工程目标已完成。排除的 CB 提示接口仍未验收；真实资料/SQL 迁移、正式训练、独立评估/真实校准与能力发布、历史生产权重绑定和 GPU/真实宿主运行仍留对应阶段。V30 实际环境适配留 T5，T1–T5 未开始，整个 M7 不越过这些未执行范围登记完成。

没有 checkout/reset/clean/stash、恢复既有删除、新 worktree、提交、推送、合并或发布，全部既有和并行成果保留。
