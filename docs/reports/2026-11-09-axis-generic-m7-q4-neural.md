# M7 剩余 Q4 神经编码、预测与评分实际验收

日期：2026-11-09，香港时间。用户明确允许对应模型前向和必要导入，仍禁止微型更新、训练、真实资料准备、CB、原生引擎和 CI。已先交付[本批机械执行补充](../plans/2026-11-09-axis-generic-m7-q4-neural-execution-supplement.md)，全部由主进程顺序执行，无子代理。

## 实际结果

复用 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`。使用已有 `E:\Ana\envs\pcacgate\python.exe`，实际 Python 3.10.20、Torch 2.2.2，CPU/FP32。没有安装依赖、更换环境、读取旧模型或开始 GPU/训练工作。

| 组 | 明确选择/实际运行 | 成功 | failure/error/skip | 退出码 | 含导入的运行器耗时 |
|---|---|---|---|---|---|
| q4_graph：v3 编码/预测 | 11/11 | 11 | 0/0/0 | 0 | 9.177 秒 |
| q4_legacy：旧网络兼容性质 | 6/6 | 6 | 0/0/0 | 0 | 5.455 秒 |
| q4_scoring：既有评分方法 | 4/4 | 4 | 0/0/0 | 0 | 18.929 秒 |
| q4_inference：新增无更新检查 | 4/4 | 4 | 0/0/0 | 0 | 8.817 秒 |
| 本批合计 | 25/25 | 25 | 0/0/0 | 四组均 0 | 约 42.38 秒 |

25 项首次全部通过，没有失败修复或重复测试。本批新方法 ID 与前批 132 个通过方法的交集为 0；累计 157 个不同方法已有通过结果，累计物理执行 191 次（前批 166＋本批 25）。前批历史见[Q1/Q2 报告](2026-11-09-axis-generic-m7-q1q2.md)及[Q3/Q4 事实路径报告](2026-11-09-axis-generic-m7-q3q4-facts.md)，本批没有重跑这些集合。

运行器对 RoleNetwork.forward 和 GraphRoleNetwork.forward 的实际方法调用分别记录 26 和 17 次；这两个数字包含包装层与委托图层，不能相加当作互不重叠的推理次数。服务分块原用例 mock 的 forward/logits 不计作真实图网络数值前向，实际图/副本评分由新增用例验证。

## 已验证的工程行为

既有 11 个 v3 图方法实际覆盖 90 卡三分区、标签/来源不进入张量、opaque context 不成为数值特征、全局边地址下排列等变、其他混批成员不改变有效评分、节点/边分块、独立单双流和路线开关、局面条件不污染结构流、候选支持集外的成员查询、有向关系查询和预算拒绝。6 个旧网络方法覆盖排列/集合不变性、padding、数量多重性、身份/来源隔离、方向依赖与对称兼容、初始化不改变宿主 RNG。

剩余两个服务评分方法和两个旧单元评分方法实际通过：32 查询分块、整头预算在前向前拒绝、未训练公共输出保持空、所问功能进入特征且未编码功能保持 unknown。旧单元中的两个训练方法没有混入本批。

新增[无更新测试模块](../../tests/test_multifactor_inference_v3.py)包含四个明确方法：

- `test_training_queries_do_not_change_inference_tensors_or_natural_domain`：显式额外查询只进入训练查询视图，所有共享张量不变；自然推理域不注入该查询，原记录不被修改；没有调用训练入口。
- `test_missing_natural_axis_remains_known_without_an_inference_query`：未召回监督仍为 known，只读编译给出 unrepresented_candidate_cells=1，普通推理域没有该轴，steps/优化器/计数/参数不变。
- `test_real_graph_scoring_streams_full_domains_without_updates`：对 40 个候选的 axis_function 和 axis_membership 实际前向，全部预期查询恰好返回一次、每块不超过 32，包含候选支持成员之外的 card:3；raw 数值有限且在 0..1，校准与应用层保持空。
- `test_real_copy_scoring_observes_both_configurations_without_updates`：完整前后配置实际替换 card:3→card:4，执行双图前向；偏好 raw 概率完整且归一，工程回调保持空校准/应用层，原 train/eval 模式分别恢复。

实际图和副本评分前后逐项比较全部 state_dict 张量、优化器 state_dict、steps 和更新计数，均未改变。模型模式变更只用于推理及恢复，不执行训练。工程 head_status 替身只隔离 API 准入；未修改真实训练计数或发布能力。旧服务用例中手工设置的状态计数仅为既有工程夹具，不能当作模型已训练证据。

## 运行边界与未执行项

四组禁止调用尝试均为空：没有进入 train_supervised/train_preference、backward、Adam/AdamW step、checkpoint 保存/加载、真实 prepare/来源读取、CB、原生核验、子进程或 CI。允许的操作限模型初始化、CPU 张量编码/前向/query readout、内存 state_dict 拷贝和只读标签编译；没有磁盘模型快照。TEMP/TMP、Torch 缓存、JSON 和日志均在本批 N 盘任务目录。

原 `GraphEncodingTests.test_training_injection_never_changes_encoder_or_natural_eval_domain` 和 `test_missing_natural_axis_stays_a_known_miss` 含训练入口，原文完整保留、没有执行；其 Q4 编码/域/已知漏检子范围已由新增无更新方法实际覆盖，原训练准入/skip 行为留 Q5。旧单元的 `test_any_missing_necessary_member_prevents_positive_genericity`、`test_package_and_member_roles_are_never_broadcast` 同样未运行。

V16 的双正格梯度、逐格损失/弱证据梯度、微型更新、严格恢复及下一步更新等 Q5 内容仍未执行。CB 提示接口/搜索/原生权威、真实资料/SQL 迁移、实际校准和能力发布、旧权重绑定及 GPU/设备数值仍按对应范围验收，T1–T5 未开始。

本批补齐了剩余 Q4 编码、预测、评分的所选工程检查。随机工程网络只验证机制与接口，不证明语义准确率、真实泛化或可发布能力；整个 M7 仍按 Q5/CB 等未完成项登记。

## 文件、回执与保护

本批唯一新增长期编程文件为上述 4 方法测试模块；没有修改任何生产源码或既有测试。新增本报告/机械补充，并增量同步主计划当前状态、M7 A/V 子范围和 MASTER。主计划第 2–8 节、历史报告及并行构筑内容保留，全部现有 dirty/untracked/deleted 不恢复或覆盖。

`.cache/axis-generic-m7-q4-neural-20261109-01/selections.json` 为精确选择器；四组 `*-result.json` 与对应 stdout/stderr 为原始结果；`acceptance-summary.json` 保存本批/累计去重集合和边界；`manifest.json` 只登记三份拟改共享文档的局部字节保存及三份新交付，未重建旧基线或复制权重。最终差异、链接、原内容保留和新增空白检查见 `document-review.json`。

没有切换权重、训练/课程暂停或 LoRA，没有改变构筑定价/学习/调度、数据库、原生接口或用户目标，没有 checkout/reset/clean/stash、恢复删除、新建 worktree、提交、推送、合并或发布。
