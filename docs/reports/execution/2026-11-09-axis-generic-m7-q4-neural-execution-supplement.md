# M7 剩余 Q4 神经编码、预测与评分机械执行补充

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

日期：2026-11-09，香港时间。用户明确授权继续 M7 剩余 Q4，先交付本补充后直接执行，允许对应模型前向及必要导入；仍禁止微型更新、训练、真实资料准备、CB、原生引擎和 CI。全部由主进程完成，不启用子代理，保留全部既有改动，后续在此边界内自主安排，无待答问题。

## 目标、当前证据与边界

依据为[主执行书](2026-11-08-axis-generic-execution-plan.md)、[M7 当前索引](../2026-11-09-axis-generic-m7.md)和[此前实际结果](../2026-11-09-axis-generic-m7-q3q4-facts.md)。Q1/Q2、Q3 工程及 Q4 事实路径已有 132 个不同方法通过、166 次物理执行。没有与本次有关的新源码变化时复用这些结果，不重跑前批全套。

实际完整检出为 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`，不能据此恢复文件。继续使用已有 `E:\Ana\envs\pcacgate\python.exe`，前批实测 Python 3.10.20、Torch 2.2.2，不安装或升级依赖。CPU、FP32 小型随机初始化工程网络足以验证此次前向机制，不加载旧权重或启动 GPU/训练。

最新源码读取确认：`GraphEncodingTests` 有 13 个方法，其中 2 个直接调用 `train_supervised`；`MultifactorStructureTests` 中明确的排列/padding/身份/对称性方法只做前向；两个剩余服务评分方法不更新但会构造 trainer，其中分块方法 mock 了 logits；两个旧单元评分方法只做前向并要求未训练输出拒答。已有真实评分 API 为 `CandidateScorer.score_graph/score_copy_graphs`，使用 inference_mode、按 32 查询分块并恢复模型原模式。

本批不把训练方法改成无训练以规避限制。两项混合用例和所有 Q5 原文保留，另以独立无更新用例覆盖必要 Q4 子范围，并增加真实评分 API 的前向及状态不变断言。随机初值、工程状态门槛替身和工程校准回调只验证数值/协议流程，不构成训练、拟合、校准准确率或能力发布证据。

## 文件范围与确定路线

新增 `tests/test_multifactor_inference_v3.py`（4 个专用方法）、本补充和 `docs/reports/2026-11-09-axis-generic-m7-q4-neural.md`。只增量更新主计划当前状态/授权与第 9 节、M7 当前状态/A/V 子范围和 MASTER 追加条目；原主计划第 2–8 节、前批报告和旧测试均保留。

初始不修改生产实现或既有测试。真实失败发生后，先读取最新根因文件并交付精确文件/符号/修改/不变量/复验的修复增量，再处理必要问题。禁止对照 HEAD 重建、覆盖未跟踪成果、恢复删除、checkout/reset/clean/stash 或新建 worktree。训练/课程暂停、LoRA、活动指针、权重、真实资料和数据库、构筑定价/学习/调度、原生接口及用户目标保持；不提交、推送、合并或发布。

临时运行器、明确选择器、逐项 JSON、日志和小型保存放在新目录 `.cache/axis-generic-m7-q4-neural-20261109-01`，只保存三份拟改共享文档并逐字节核对，不重建旧全树基线、复制模型或计算额外哈希。模型比较的 state_dict 克隆只在内存中进行。

## 精确选择与新增方法

本批预期 25 个明确方法，四组顺序运行：

1. `q4_graph`：`tests.test_multifactor_learning_v3.GraphEncodingTests` 除 `test_training_injection_never_changes_encoder_or_natural_eval_domain`、`test_missing_natural_axis_stays_a_known_miss` 外的 11 个。覆盖 90 卡三分区、标签/来源隔离、opaque context、全局边地址排列、混批、节点/边分块、双流/路线开关、局面/结构流隔离、全域成员查询、有向查询及预算拒绝。
2. `q4_legacy`：`tests.test_multifactor_structure.MultifactorStructureTests` 的 6 个方法：`test_group_and_relation_permutation_equivariance_and_set_invariance`、`test_batch_padding_cannot_change_valid_node_scores`、`test_symmetric_sum_pool_retains_multiplicity_without_position_features`、`test_opaque_ids_names_sources_and_member_order_never_enter_tensors`、`test_directed_dependency_is_encoded_and_pair_compatibility_is_symmetric`、`test_initialization_preserves_host_rng`。只验证兼容的旧编码/网络性质，不运行该模块的 loss/checkpoint/CLI 子进程方法。
3. `q4_scoring`：服务的 `test_candidate_scorer_streams_all_queries_beyond_first_block`、`test_candidate_scorer_query_budget_rejects_before_forward`，以及旧单元的 `test_untrained_public_outputs_null_even_for_positive_definition_case`、`test_requested_function_enters_features_and_unencoded_function_stays_unknown`，共 4 个。原两个调用训练的旧单元方法仍排除。
4. `q4_inference`：新增 `InferenceWithoutUpdatesTests` 的以下 4 个。

| 新方法 | 输入/动作与预期行为 | 明确断言 |
|---|---|---|
| `test_training_queries_do_not_change_inference_tensors_or_natural_domain` | 复用已有工程图/记录，声明额外 training_queries，比较普通编码和 training=True 的查询视图 | 节点/边/上下文等张量相同；额外查询只进入显式训练域，不进入自然域；不调用任何训练方法 |
| `test_missing_natural_axis_remains_known_without_an_inference_query` | 未召回轴只有已知监督格，调用 `compile_records` 的只读准入和普通编码 | compiled 为空、未表示候选计数为 1、原标签仍 known、自然推理域无该轴；trainer steps、优化器状态和更新计数保持零 |
| `test_real_graph_scoring_streams_full_domains_without_updates` | 40 个自然候选、3 张实际卡，随机初始化 v3 网络；工程 head_status 替身仅让 API 进入 raw 诊断，实际执行 axis_function 和 axis_membership 的前向/分块评分 | 全部预期查询恰好返回一次，每块不超过 32；包含候选支持集外的 card:3 成员查询；raw 为有限 0..1 数值，校准/应用层为空；模型模式、全部参数、steps、优化器和更新计数不变 |
| `test_real_copy_scoring_observes_both_configurations_without_updates` | 同一目标/功能的完整前后配置真实替换 card:3→card:4；实际双图前向，工程校准回调只返回空校准/应用层 | raw 完整偏好概率有限且归一、回调绑定任务；原 train/eval 模式分别恢复，全部参数/优化器/计数不变；不虚构已应用偏好 |

新增四项复用现有 `build/config/record/trainer` 工程夹具，不改其定义或原方法。只读编译标签格和 training=True 查询编码不是训练执行；运行器对训练入口和 backward/step 全部拦截。

## 运行方法与约束

每组使用明确 `unittest.TestLoader.loadTestsFromNames`，不 discovery。允许 CPU 随机模型/trainer 构造、张量编码、模型前向、query readout 和内存 `load_state_dict`，不允许磁盘 checkpoint 读写。运行器记录真实 RoleNetwork/GraphRoleNetwork forward 调用，但不将 mock 的服务 logits 当真实神经结果。

在加载所选测试前，失败拦截 `RoleTrainer.train_supervised/train_preference/save/load/warm_start`、Adam/AdamW step、Tensor.backward/autograd.backward、torch.save/load、完整 prepare/真实来源读取、CB provider/提议、原生目标核验与子进程启动。`provider=None` 的纯 not_run 状态构造仍可保留，但所选神经方法不调用构筑流程。禁止动作被尝试即失败，不能跳过或转成通过。

环境沿用 `-B`、`PYTHONDONTWRITEBYTECODE=1`、当前 src/仓库 PYTHONPATH、OMP/MKL 各 2、现有 Conda DLL 路径；TEMP/TMP、Torch 缓存显式指向本批新的 N 盘目录，不设置持久环境或下载缓存。模型测试限定 CPU；不以 CPU 工程前向结果代替未来 GPU/设备或模型能力验收。

```powershell
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q4-neural-20261109-01/run_acceptance.py' q4_graph
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q4-neural-20261109-01/run_acceptance.py' q4_legacy
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q4-neural-20261109-01/run_acceptance.py' q4_scoring
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q4-neural-20261109-01/run_acceptance.py' q4_inference
```

## 分步实施与验收

| 步骤 | 目标/符号与前置条件 | 具体动作与预期结果 | 不变量、验证方法与通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| S1 交付和局部保存 | 本补充、三份共享文档；最新用例/调用路径已读，新目录和新测试文件原不存在 | 先交付补充，再保存文档当前字节、登记路径，写 4 个专用方法和临时 runner/selections | 原文保存逐字节一致；旧用例不删改；无持久权重、真实准备或额外环境安装 | 路径已占用/锚点变化则读最新处理，不覆盖旧产物 |
| S2 既有 Q4 图和兼容性 | 11+6 个明确方法；环境及禁止动作拦截已就绪 | 顺序执行 q4_graph、q4_legacy，记录实际方法和真实前向 | 全部方法通过、0 skip/failure/error、禁止动作尝试 0；只 CPU 编码/前向，不反向/更新 | 具体失败进 S4；不以新模型或宽松容差掩盖问题，不调用训练 |
| S3 评分和新增无更新检查 | 4+4 个明确方法；新测试已文本回读，旧方法原文保留 | 执行 q4_scoring、q4_inference，核验拒答/分块/成员全集/双图评分和状态不变 | 原子更新、训练、反向、checkpoint、真实准备/CB/原生/CI 均不发生；所有方法通过且参数/优化器/计数不变 | 具体失败进 S4；工程门槛替身不能写成真实能力已训练或发布 |
| S4 实际失败处理 | 仅真实失败涉及的文件/符号；首次结果已保存 | 读取根因，先交付精确修复增量，再局部修改；复验失败方法和直接受影响集合 | 保留旧断言含义及首次失败，保护所有现有和并行改动；禁止部分不执行 | 需要禁止行为时保留未完成；只逆向撤销本批自有增量，不恢复整文件 |
| S5 状态与报告 | 新报告、主计划当前状态、M7 当前/A/V 子范围、MASTER 末尾；实际结果可用 | 分别登记编码/预测/评分的工程结果、更新为 0 和仍未运行的 Q5/CB/T 范围 | 不把随机网络准确率当能力；V16/恢复仍待；主计划第 2–8 节和历史报告保留 | 共享文件变化则读最新增量合并，不覆盖并行写入 |
| S6 最终限定检查 | 本批差异、JSON/log、文档和新增测试 | 核对实际选择/通过 ID、前向与禁止调用、源码增量、链接和新增空白，tracked 路径命令级 Git 检查 | 所选方法和必要修复闭合；不重复无关已通过集合；保留有效回执 | 发现具体并行影响只核对/复验相关方法；没有仍可独立推进的本批允许工作时交付真实状态 |

## 保留未运行范围

两项含 `train_supervised` 的原 GraphEncoding 方法、两个旧单元训练方法和全部 Q5 的实际训练/损失/微型更新/保存恢复继续保留，V16 双正格梯度未运行。没有新增训练授权，不能因允许模型前向而执行 backward/step 或训练入口。CB 提示方法/执行、真实资料/SQL 迁移、旧权重加载绑定、实际校准和能力发布、GPU/设备及 T1–T5 均不由本批自动完成或启动。M7 整体验收按真实剩余范围登记。

## 本批实际状态

四组分别 11/11、6/6、4/4、4/4，25 项首次全部通过，0 failure/error/skip，禁止动作尝试均为空，没有进入 S4 修复。真实 RoleNetwork/GraphRoleNetwork forward 方法调用分别为 26/17（包装与委托层，不相加当独立推理次数）。实际图和完整副本评分的参数、优化器、steps、计数及模型模式不变断言通过。累计 157 个不同方法有通过结果、191 次物理执行。

新增测试 4 个，旧源码/用例不改，完整结果见[本批实际报告](../2026-11-09-axis-generic-m7-q4-neural.md)和 `.cache/axis-generic-m7-q4-neural-20261109-01/acceptance-summary.json`。主计划第 2–8 节及历史保留，最终限定文档检查见同目录 `document-review.json`；Q5/V16/CB/真实资料和 T 阶段未因本批开始。
