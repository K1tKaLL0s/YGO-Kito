# M7 Q5 梯度、工程更新与严格恢复机械执行补充

日期：2026-11-09，香港时间。依据[主执行书](2026-11-08-axis-generic-execution-plan.md)第 7、9 节和用户最新授权，先交付本补充，再直接执行。沿用已加载的忠实执行技能及代码执行细则，全部由本聊天主进程顺序完成，不启用子代理，没有待答问题。

## 目标、证据与边界

实际完整仓库 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`。HEAD 不代替当前大量 dirty/untracked/deleted 文件。前批累计 157 个不同方法通过、191 次物理执行，见[Q4 报告](../reports/2026-11-09-axis-generic-m7-q4-neural.md)；这些方法不因本批扩大授权而重跑。

已文本读取当前 `tests/test_multifactor_learning_v3.py`、`test_multifactor_structure.py`、`test_multifactor_units.py` 和 `tests/multifactor_helpers.py`，以及 `training.py`、`graph_training.py` 的更新/保存恢复路径和 `train_v3.py` 的暂停入口。V16 现有专用方法要求 carrier/enhancer 同一 LabelSet 双正格、BCE=ln(2)、两个 bias 梯度均为 -0.25、一次工程更新和一次头计数。v3 恢复检查显式架构/数据/划分/标签协议/recipe、运行环境及 Adam 状态，保存使用新文件 no-replace；旧版恢复检查原接口相容和下一步更新。实际行为由本批测试确定，不提前登记通过。

本批允许必要导入、CPU 前向/反向、工程夹具上的有限优化器更新、任务专属 checkpoint 保存/读取/恢复/warm_start，及 gzip 工程分片的游标比较。使用已有 `E:\Ana\envs\pcacgate\python.exe`（前批实际 Python 3.10.20、Torch 2.2.2），不安装或升级环境。现测 N 盘空闲 333048008704 字节；小型工程产物、TEMP/TMP、Torch 缓存和日志均放入新任务目录 `.cache/axis-generic-m7-q5-20261109-01`。

正式训练入口、真实资料/来源读取与准备、CB/provider/搜索、原生引擎和 CI 继续禁止。当前模型权重、真实 runs/分片/数据库、活动指针、暂停状态、LoRA 和构筑政策均不切换。没有旧训练 checkpoint 读取，不调用 `fit/_fit/finish` 或 `main_config(formal_training=True)`；暂停测试仅调用原 `main_config({'formal_training':False})`，应在准备/设备前拒绝。

## 明确选择器与通过标准

全部通过标准：选定数=实际运行数=成功数，failure/error/skip/loader error 为 0，禁止动作尝试为空；每个方法保持原断言。选择器存于任务目录 `selections.json`，不使用 discovery 或整模块执行。

| 组 | 明确类/方法（`tests.` 前缀） | 数量和行为 |
|---|---|---|
| q5_masked | `test_multifactor_learning_v3.MaskedLearningTests` 全部当前 12 方法 | V16 双正格梯度、全部 learned 头独立损失/计数、unknown/conflict/not_applicable/零置信度无前向更新、弱证据不抵消、未监督头不变、来源组权重/逐格来源、错误协议/坐标拒绝、确定性与环境头不计数、明确偏好和同定义一致性 |
| q5_deferred | `test_multifactor_learning_v3.GraphEncodingTests.test_training_injection_never_changes_encoder_or_natural_eval_domain`、`test_missing_natural_axis_stays_a_known_miss`；`test_multifactor_units.MultifactorFunctionalUnitTests.test_any_missing_necessary_member_prevents_positive_genericity`、`test_package_and_member_roles_are_never_broadcast` | 4；原保留方法实际训练准入/skip、缺成员拒绝及包标签不广播 |
| q5_legacy | `test_multifactor_structure.MultifactorStructureTests.test_partial_multilabel_loss_masks_unknown_role`、`test_weights_optimizer_metadata_and_next_update_resume_exactly`、`test_checkpoint_source_and_feature_binding_refuse_silent_migration`、`test_changed_annotation_protocol_cannot_mix_or_silently_restore` | 4；旧版掩码、优化器/游标和下一步精确恢复、来源/特征/协议拒绝 |
| q5_recovery | `test_multifactor_learning_v3.RecoveryTests` 全部当前 5 方法 | v3 RNG/模型/下一步更新精确恢复，数据/架构/缺绑定拒绝，warm_start 只复制编码器并清空头/状态，不覆盖既存文件，Adam 形状损坏拒绝 |
| q5_runner | `test_multifactor_learning_v3.RunnerTests` 全部当前 4 方法 | 5 条工程 gzip 记录的同序剩余批次、不读最终集、暂停配置提前拒绝、开发选择分数与类别覆盖 |
| 合计 | 29 个不同方法，含既有 V16 专用方法；本批不预设新增长期用例 | 预计累计 186 个不同方法；实际执行数按真实失败/复验记录 |

运行器在原方法外计数 RoleNetwork/GraphRoleNetwork forward、Tensor/autograd backward、Adam/AdamW step、trainer 工程调用和 torch.save/load，不替换梯度、损失、参数或恢复验证。每次更新须位于当前选定方法，且 CPU/hidden_dim=16；原小规模夹具和来源不变。两个 forward 层及两层 backward 可能包装委托，分别报告，不相加为独立操作数。checkpoint I/O 在执行前解析路径，只允许本任务 `tmp` 子树；允许旧版测试覆写其刚创建的临时文件，v3 原 no-replace 断言保持。

`tests.multifactor_helpers.task_temporary_directory` 仅在运行器内改为相同 `tempfile.TemporaryDirectory` 语义、dir 指向本任务 `tmp`，随后加载测试模块；不修改长期 helper。标准上下文只清理本批自己创建的临时子目录；JSON/日志和首次失败回执保留。真实准备/正式训练/CB/原生及子进程入口由运行器拦截；测试允许的只读 train_v3 helper 和暂停分支保留原实现。

## 修改范围与分步实施

正常路径只新增本补充、实际报告 `docs/reports/2026-11-09-axis-generic-m7-q5.md` 和任务目录临时选择器/运行器/回执，增量更新主计划当前状态及第 9 节、M7 报告 A/V 末列/剩余项、MASTER 末尾。主计划第 2–8 节、历史报告与并行内容保留。没有预定生产或既有测试修改；真实失败涉及这些文件时，先交付精确机械修复增量，保存该处当前内容，再修复实际根因，不弱化断言。

| 步骤 | 文件/符号、前置条件 | 动作及预期结果 | 不变量、命令/方法和通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| S1 交付并局部保存 | 本补充；共享三文档和新任务路径已核对，均无待答问题 | 先交付本书；保存三份共享文档原字节和 manifest，再写明确 selections/runner | 保存逐字节相等；新任务路径不覆盖；历史成绩只复用 | 已存在路径/共享锚点变化则读当前并增量合并，不能按旧快照覆盖 |
| S2 损失与保留方法 | `MaskedLearningTests` 及 q5_deferred 四个方法；CPU 和边界拦截就绪 | 顺序执行 q5_masked、q5_deferred，记录双格梯度、更新及拒绝分支 | 每组按原断言全部通过，禁止动作 0；原未知/已知格与来源语义不变 | 保存首次失败，转 S4；不得用真实资料/正式训练补救 |
| S3 保存恢复与游标 | q5_legacy/recovery/runner；tmp 路径已限定 | 顺序执行旧版兼容、v3 严格恢复和只读工程游标方法 | 参数/优化器/计数/RNG/下一步断言及拒绝断言通过；保存读取只在任务临时目录 | 序列化/绑定具体失败转 S4，不放松 weights_only/架构/协议或使用旧权重 |
| S4 精确失败修复 | 只限实际失败涉及的源码/夹具；首轮结果已保留 | 文本读取根因，先交付具体修复增量，再局部实施；复验失败项及直接受影响方法 | 不删减原业务断言；保留并行改动与失败历史；已通过且不受影响项不重复 | 需要禁止动作时保留该项待验证；仅可逆向撤销本批自有增量，不恢复整文件 |
| S5 状态和文档 | 三共享文档、本报告/补充；实际 JSON 可用 | 登记 Q5 实际结果、工程更新与 checkpoint 次数、V16/28/29 证据和真实剩余范围 | 合并旧 157 个方法去重，物理执行含复验；工程通过不发布能力 | 共享并行变更按最新内容增量处理；旧批次状态保留历史语境 |
| S6 最终限定检查 | 本批差异、回执和新增链接；选定范围已完成或有具体未完成项 | 核对实际 ID/禁止动作/路径、保护区、A/V 编号和新增空白；tracked 文档命令级 diff --check | JSON 完整，路径无越界，原文保留，无新增空白；不另跑 CI/编译/已通过集合 | 有具体差异则只处理该差异；不据未授权后续阶段扩大本批工作 |

环境使用 `PYTHONDONTWRITEBYTECODE=1`、`-B`、当前 `src`/仓库 PYTHONPATH、OMP/MKL 各 2 线程；临时输出根显式设本任务目录，PATH 仅补现有 E 盘环境 DLL 路径。依次执行：

```powershell
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q5-20261109-01/run_acceptance.py' q5_masked
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q5-20261109-01/run_acceptance.py' q5_deferred
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q5-20261109-01/run_acceptance.py' q5_legacy
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q5-20261109-01/run_acceptance.py' q5_recovery
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q5-20261109-01/run_acceptance.py' q5_runner
```

## 结束边界

完成本批所选 Q5 工程验收和必要修复后，CB 提示接口、真实资料/SQL 迁移、正式训练/独立评估/真实校准与发布、历史生产权重和 GPU/真实宿主验证仍按对应阶段登记，T1–T5 不自动开始。没有提交、推送、合并、发布、新 worktree、checkout/reset/clean/stash、恢复既有删除或覆盖未跟踪成果。

## S4 精确修复增量（首轮完成后、修改前交付）

首轮 29 个方法已全部实际运行，24 通过、1 failure、4 error、0 skip，禁止动作尝试为空。q5_masked 12/12、q5_legacy 4/4、q5_runner 4/4 首次通过，不重复；q5_deferred 的包标签方法停在旧标量元组断言，尚未更新；q5_recovery 的四项均在原 `os.link(temporary,path)` 返回 WinError 5，序列化实际完成，但还未进入恢复。既存文件不覆盖方法已通过，原始结果和日志保留。

已核对 `Targets.__post_init__` 会将旧数值转成 `LabelCell`，这是当前既定契约。只将该断言改为精确核对唯一包 key、四格 unknown/None 和一格 known/1，原训练/engineering_only/成员不广播断言不删。Windows `os.rename` 在目标存在时抛 FileExistsError；同目录新文件发布保持不覆盖语义，其他平台保留 `os.link`。依据为 [Python 3.10 官方 os.rename 文档](https://docs.python.org/3.10/library/os.html#os.rename)，不改用可覆盖的 replace，也不改变 ACL 或提升权限。

| 步骤 | 目标文件/符号与前置条件 | 具体修改及预期结果 | 不变量和验证/通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| F1 局部保存 | `src/ygo_kito/multifactor/graph_training.py:save`、`tests/test_multifactor_units.py:test_package_and_member_roles_are_never_broadcast`、`tests/test_multifactor_learning_v3.py:RecoveryTests`；首轮回执已保存、当前片段已重读 | 保存三份文件当前字节到本任务 before；在 manifest 登记这次增量 | 保存逐字节相等，不重建旧基线或恢复任何既有改动 | 锚点被并行修改则读最新合并，不覆盖旧快照 |
| F2 修复实际根因 | 上述 save 和包标签方法；F1 完成 | `save` 仅在 `os.name=='nt'` 分支调用同目录 `os.rename`，else 原 `os.link`；保留早期 exists 拒绝、payload、finally 临时清理和所有恢复校验。包断言按上述逐格状态/值更新 | 保持 v3 no-replace；不放松损失/恢复/状态断言；不修改模型、数据、头或正式 runner | 保存仍被拒绝则保留真实错误，不使用覆盖或权限绕过 |
| F3 补充直接对照 | `RecoveryTests.test_checkpoint_publish_preserves_a_concurrent_file`；F2 修改前已明确测试方案 | 在实际发布调用前模拟另一个写入者刚创建目标，再调用当前平台原始 publish；断言 FileExistsError、并发内容原样、data_cursor 不变且临时文件清理 | 在任务 tmp 内使用真实文件系统的 no-replace 操作，只模拟竞态时序；没有引擎/正式训练/外部数据 | 不用 mock 成功替代实际 no-replace；出现覆盖或残留先修 save |
| F4 精确复验 | q5_repair 的六个明确方法：首轮包标签失败 1、恢复错误 4、新竞态 1 | 新增独立选择组 expected=6 后运行同一受限 runner，结果另存，不覆盖首轮 | 六项全部通过、0 skip/failure/error/禁止动作；恢复下一步/RNG/Adam 和 warm_start 原断言保持。原 24 个已通过方法复用 | 新失败保留后继续具体诊断；没有直接影响不重跑其他组 |

新增一个竞态方法后，本批目标为 30 个不同方法；预期首轮 29＋本次复验 6＝35 次物理执行。实际累计按方法 ID 与前批 157 个方法去重，不能把 6 项全当新方法或把首次 24 项写成全批首次通过。

## 本批实际状态

S4 两处精确修改和一个新增竞态对照已实施，六项复验全部通过。本批 30 个不同方法有通过结果，物理执行 35 次；累计 187 个不同方法、226 次物理执行。原已通过 24 项及前批集合不重复，禁止动作尝试均为空。实际 Adam step 22、Tensor/autograd backward 各 22（委托层分开计数）、torch.save 16、torch.load 14，全部路径在本批 tmp，结束无临时条目。正式训练、真实资料/CB/原生/CI 及生产权重读取均未发生。

当前 selections 已将原 5 个 Recovery 方法冻结为明确 ID，初次类选择器保留在 selections-before-freeze.json；首次失败、六项复验与完整边界见[实际报告](../reports/2026-11-09-axis-generic-m7-q5.md)。最终限定检查见任务目录 document-review.json。M7 剩余 CB 提示接口及 T 阶段仍按结束边界保留。
