# M7 Q1/Q2 实际验收记录

日期：2026-11-09，香港时间。用户明确授权 Q1/Q2 对应测试及必要导入，并允许主进程自主安排后续；模型前向、微型更新、训练、真实资料准备、CB、原生引擎和 CI 仍禁止。修改/执行前已交付[机械执行补充](execution/2026-11-09-axis-generic-m7-q1q2-execution-supplement.md)。全部由主进程完成，无子代理。

## 实际结果

复用 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`。使用已有 `E:\Ana\envs\pcacgate\python.exe`，实际 Python 3.10.20、Torch 2.2.2，没有安装或升级依赖。

| 组 | 明确选择/实际运行 | 成功 | 失败/错误/skip | 命令退出码 | 含导入的运行器耗时 |
|---|---|---|---|---|---|
| Q1 | 13/13 | 13 | 0/0/0 | 0 | 28.746 秒 |
| Q2 | 30/30 | 30 | 0/0/0 | 0 | 11.796 秒 |
| 合计 | 43/43 | 43 | 0/0/0 | 两组均 0 | 约 40.54 秒 |

两组首次运行均通过，没有失败修复或重复测试。没有修改生产源码、测试源码或夹具。精确选择器和 11 个单元方法见机械补充；实际逐方法成功清单、异常明细及环境位于 `.cache/axis-generic-m7-q1q2-20261109-01/q1-result.json` 和 `q2-result.json`，stdout/stderr 同目录分组保存。

Q1 覆盖输入四模式、迁移/回读、缺失/空区、标签状态和部分标注、Targets 契约、机制元数据不进入旧编码张量。Q2 覆盖 all/any/at_least_k/not、聚合供给/回溯/共享库存、占用/保留/独立实体、Side/未知/预算、递归成员/替代分支及逐功能评价、整包费用回调和有限构筑委托同一分配器。

新增 V11 `test_v11_fifteen_extra_cards_are_cost_resources_not_members` 和 V12 `test_v12_removing_extension_keeps_base_function_complete` 均实际通过；分别覆盖 15 张 Extra 费用与成员隔离的正反对照、删除扩展目标/成员/费用后保留基础功能。对应预算未知和 Side 的既有 Q2 用例也通过。这些是工程语义断言，不是实际卡效全覆盖或模型能力成绩。

## 执行边界与排除项

临时运行器只按明确类/方法调用 unittest，不使用 discovery。在加载测试前，对模型 `_call_impl`、trainer 构造/训练入口、Adam/AdamW step 和 checkpoint 加载安装失败拦截；两组 `forbidden_call_attempts` 均为空。允许的张量编码比较没有执行神经网络。TEMP/TMP、Torch 缓存和日志均显式指向本批新的 N 盘任务目录，未写入旧 runs 或权重。

没有执行模型前向、优化器更新、训练、checkpoint 加载、真实资料准备、CB、原生引擎或 CI。没有 GPU 核验、独立 AST/编译/构建步骤或付费/外部模型调用。必要 Python/项目/Torch 导入和 43 个测试的执行已由本批授权，不能继续写成本批“所有导入/测试均为 0”。

单元模块的四个方法未运行：`test_any_missing_necessary_member_prevents_positive_genericity`、`test_package_and_member_roles_are_never_broadcast`、`test_untrained_public_outputs_null_even_for_positive_definition_case`、`test_requested_function_enters_features_and_unencoded_function_stays_unknown`。它们构造 trainer 或调用评分/训练路径；不把本批成绩写成整个模块通过。V16 梯度和 V21 对照也未混入本批。

## 当前状态与后续

本批 Q1/Q2 允许范围已完成，相关输入/标签契约、资源/分支和功能语义有真实工程通过证据。A01–A10 的整体目标仍按各自未运行子范围登记，不能把 43 项通过扩大为所有 A/V 已验收。V11/V12 的专用工程断言已通过，V16/V21 和其他未运行项仍待各自运行结果。

后续按主执行书安排 Q3 的工程分组/缓存/指标/确定性，再处理 Q4 的图/候选/服务/消费者及相应集成；前向和更新相关方法继续受禁令约束。Q5、真实资料准备、实际校准/能力发布、真实宿主兼容及 T1–T5 均不因本批结果自动完成或启动。首批 M7 和四项源码补充中的零运行数字继续保留为各自历史记录，当前状态以本批及后续实际报告为准。

本批只保存三份拟改共享文档的当前字节，清单见 `.cache/axis-generic-m7-q1q2-20261109-01/manifest.json`，未重建旧基线、计算哈希或复制模型。共享文档增量同步及最终文本检查见同目录 `document-review.json`。全部既有 dirty/untracked/deleted 和并行构筑内容保留；没有 checkout/reset/clean/stash、恢复删除、新建 worktree、提交、推送、合并或发布。
