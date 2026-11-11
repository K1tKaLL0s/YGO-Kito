# M7 Q1/Q2 验收机械执行补充

日期：2026-11-09，香港时间。用户明确授权按主执行书开始 M7 Q1/Q2，先交付本补充后直接执行，允许对应测试及必要导入；仍禁止模型前向、微型更新、训练、真实资料准备、CB、原生引擎和 CI。全部由主进程完成，不启用子代理，保留全部现有改动。后续工作由主进程按既定顺序安排，始终受这些明确禁令约束；当前没有待答问题。

## 目标、当前证据与范围

目标是取得 Q1/Q2 所选契约/语义用例的真实运行结果，包含新增 V11、V12，修复本范围内实际发现的问题，并登记实际运行和剩余范围。依据为[主执行书](2026-11-08-axis-generic-execution-plan.md)第 6–7 节、[M7 报告](../reports/2026-11-09-axis-generic-m7.md)和[四项专用用例补充](2026-11-09-axis-generic-m7-coverage-execution-supplement.md)。

当前完整检出仍是 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD 为 `3f57198e5e366152bbb672be8910e6800f8adbb4`。此前所有识别测试均未执行，只有文本检查。最新文本读取确认：Q1 的输入/标签方法不构造模型；机制元数据方法只调用 `encode_batch` 构造张量。Q2 的成员、分支、资源和 `prepare_function_candidate` 只做结构解析和宿主费用回调。单元模块的 `setUpClass` 仅设置 CPU 线程并读取已有小型开发夹具，不生成真实资料。

使用既有 `E:\Ana\envs\pcacgate\python.exe`；已确认实体存在并只读检查现有 Conda 历史和 Torch 文件，不安装或升级环境。首次授权运行会记录 Python/Torch 版本、实际路径和测试统计，不核验 GPU 或打开模型。N 盘本次读取约有 310 GiB 可用，足够保存小型日志。运行临时目录及缓存显式放入本任务 N 盘新目录；不搬迁或复制模型、旧数据与前批基线。

本批不先改生产源码或测试源码。允许新增本补充、`docs/reports/2026-11-09-axis-generic-m7-q1q2.md`，并增量更新主执行书的当前状态/授权、第 9 节、M7 报告当前状态和 MASTER 追加条目。旧第 2–8 节设计保留，历史零运行数字继续描述原批次。运行器、结果 JSON、stdout/stderr 和局部保存写入 `.cache/axis-generic-m7-q1q2-20261109-01`，不作为长期生产程序。

## 精确用例选择与执行方法

Q1 共 13 个方法，使用以下明确选择器：

- `tests.test_multifactor_analysis.AnalysisInputTests`：5 个。
- `tests.test_multifactor_labels.LabelCellTests`：2 个。
- `tests.test_multifactor_batch1.V3ContractTests`：5 个，包含 Targets 契约所需训练模块导入；不构造 trainer 或更新。
- `tests.test_multifactor_mechanism.MechanismContractTests.test_mechanism_is_not_encoded_as_input`：1 个，仅张量编码比较。

Q2 共 30 个方法：

- `tests.test_multifactor_conditions.RequirementTreeTests`：5 个。
- `tests.test_multifactor_batch1.AllocationTests`：6 个。
- `tests.test_multifactor_batch1.FunctionalBranchTests`：7 个，包含 V11/V12 新增方法。
- `tests.test_multifactor_batch1.SharedConstructionTests.test_constructed_group_uses_same_allocation_core`：1 个，仅工程关系到共用分配器的调用，不进入构筑执行、CB 或引擎。
- `tests.test_multifactor_units.MultifactorFunctionalUnitTests` 中以下 11 个明确方法：`test_function_contract_roundtrip_and_exact_joint_membership`、`test_transitive_and_cyclic_joint_requirements_preserve_shared_quantities`、`test_excess_members_are_not_silently_called_the_minimum_generic_unit`、`test_unknown_dependency_review_or_conditions_remain_unverified`、`test_a_member_other_function_is_a_separate_query_not_a_global_card_label`、`test_resolve_joint_unit_before_calling_whole_unit_cost_provider`、`test_optional_copies_are_costed_as_the_full_package_not_dropped_at_unit_resolution`、`test_gamma_driver_cases_are_explicit_development_labels_not_neural_success`、`test_opaque_member_renaming_preserves_derived_features`、`test_unit_context_and_derived_feature_spoofing_are_rejected`、`test_alternative_requirements_remain_explicit`。

不运行整个单元模块。明确排除其中 `test_any_missing_necessary_member_prevents_positive_genericity`、`test_package_and_member_roles_are_never_broadcast`、`test_untrained_public_outputs_null_even_for_positive_definition_case`、`test_requested_function_enters_features_and_unencoded_function_stays_unknown`：它们会构造 trainer、调用评分或训练路径，留在相应后续验证范围。V16 梯度和 V21 数据对照不混入本次 Q1/Q2。

运行前设置 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=<当前 src>;<当前仓库>`、`OMP_NUM_THREADS=2`、`MKL_NUM_THREADS=2`，TEMP/TMP、TORCH_HOME 和 Torch 编译缓存目录指向本任务的新 N 盘子目录。PATH 只在本次 shell 中前置现有 Conda 环境的常规 DLL 目录，不改持久配置。入口以 `-B` 禁止字节码落盘。

为执行运行边界，使用小型临时运行器调用 `unittest.TestLoader.loadTestsFromNames` 和 `TextTestRunner(verbosity=2)`，选择上述明确类/方法，不使用 discovery。运行器在加载所选测试前拦截 `torch.nn.Module._call_impl`、`RoleTrainer.__init__`、`RoleTrainer.train_supervised/train_preference`、`torch.optim.Adam.step/AdamW.step` 和 `torch.load`；拦截记录尝试并直接失败，不执行原动作。允许普通张量创建与 `encode_batch`。结果逐项记录成功、失败、错误和 skip；43 个仅是预期数，实际数由 runner 回执决定。

两组顺序运行，命令分别为：

```powershell
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q1q2-20261109-01/run_q1q2.py' q1
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q1q2-20261109-01/run_q1q2.py' q2
```

每组 stdout/stderr 单独保存。运行器和 JSON 只服务本次验收，不改项目测试入口或公共模型 API。

## 分步执行与逐项验收

| 步骤 | 目标文件/符号与前置条件 | 动作、行为与预期结果 | 不变量、检查方法与通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| S1 交付、局部保存和运行入口 | 本补充、三份拟改共享文档；选择器和调用路径已文本读取，新目录原不存在 | 先交付本补充，再保存当前主计划/M7/MASTER 三份字节并登记清单，写临时 runner 和明确选择器 | 不保存全树或权重、不计算哈希；保存副本逐字节相同；运行器没有 discovery、模型构造、前向或训练实际调用 | 新目录已占用、保存不一致或选择范围变化时先停相关写入；不删除旧目录 |
| S2 Q1 | 输入/标签/批一契约及选定机制方法；本补充已交付，环境变量就绪 | 允许必要导入并运行 Q1，记录环境、13 个实际结果和边界拦截尝试 | 全部选定方法执行成功、0 skip、0 failure/error，禁止调用尝试为 0；只编码张量，不前向或更新 | 导入/环境失败先记录并检查现有路径，不安装依赖或换解释器；具体断言失败进入 S4，不降低断言 |
| S3 Q2 | 资源/分支和 11 个明确单元方法；Q1 结果已记录 | 顺序运行 Q2，记录 30 个实际结果，单列 V11/V12 | 所选方法全部成功、0 skip、禁止调用尝试为 0；共享分配只处理工程库存，不启动 CB/引擎 | 具体失败进入 S4；发现必须执行模型路径则保留未执行项，不绕过运行器 |
| S4 具体失败诊断及必要修复 | 只有 S2/S3 真实失败所指文件/符号 | 读取失败处最新源码，对根因提出精确增量补充并交付，再实施必要修复；先重跑失败方法，再跑直接受影响选择范围 | 修复必须符合原语义和本次边界，不把 unknown 改负、不简化测试为实现自证；保留首次失败及最终结果 | 无法在允许范围修复则记录未完成，不强跑前向、更新、原生或 CI；回退仅撤销本批自有增量，不恢复整份旧文件 |
| S5 状态和证据同步 | 新 Q1/Q2 报告、主计划当前状态、M7 当前状态、MASTER 末尾；实际结果可用 | 按真实结果更新选择数、通过数、失败/排除项及 A/V 子范围；记录 Q3/Q4/Q5、集成和 T 阶段状态 | 只认可已跑方法；不把 Q1/Q2 成绩外推成模型、真实数据或整个 M7 已通过；原文/并行段落保留 | 共享文件有并行编辑时读最新增量合并，不能用保存副本覆盖 |
| S6 限定最终检查与交付 | 本批文档、runner/结果及必要修复路径；S5 完成 | 回读 JSON/日志/文档，核对选择数及限制，执行本批 tracked 文档的命令级 Git 空白检查，未跟踪新增行另查 | 结果可定位、数据一致；没有新增空白错误；禁止调用尝试及未授权运行数均为 0；不无故重复已通过测试 | 文档问题局部修正；没有新代码变化/失败/疑点不扩大或重复测试；之后在仍有效授权和禁令内安排后续工作 |

## 未完成范围和保护要求

Q3 工程数据/确定性，Q4 图、候选、服务和消费者，Q5 损失/恢复及相应集成分别登记；禁止前向/微型更新的部分继续待验证。真实资料准备、GPU 数值/设备、实际校准器和能力发布、真实宿主政策及旧权重相容性仍按对应阶段处理，T1–T5 不因本次 Q1/Q2 自动启动。

不切换活动模型、训练/课程暂停或 LoRA，不改构筑定价、学习政策、调度、数据库、原生接口或用户目标；不 checkout/reset/clean/stash、不恢复既有删除、不建 worktree，不提交、推送、合并或发布。保留全部 dirty/untracked/deleted 和并行构筑修改。后续具体修改先读最新文件并交付机械补充；本执行书不增设审批，也不解除明确禁令。

## 本批实际状态

Q1 13/13、Q2 30/30 首次运行均通过，0 failure/error/skip，所有禁止调用尝试均为 0；无需 S4 修复或重复测试。实际 Python 3.10.20、Torch 2.2.2，含导入的运行器耗时分别为 28.746 秒和 11.796 秒。结果及排除项见[本批报告](../reports/2026-11-09-axis-generic-m7-q1q2.md)，限定文档检查回执为 `.cache/axis-generic-m7-q1q2-20261109-01/document-review.json`。本批没有修改生产源码或测试源码，T 阶段未开始。
