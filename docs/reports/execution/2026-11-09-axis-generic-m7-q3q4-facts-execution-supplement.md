# M7 Q3 与 Q4 事实路径机械执行补充

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

日期：2026-11-09，香港时间。承接用户“后续工作可以自行安排，直到全部完成”的授权，在已通过 Q1/Q2 的基础上继续主执行书顺序；模型前向、微型更新、训练、真实资料准备、CB、原生引擎和 CI 仍禁止。全部由主进程完成，不启用子代理，保留全部现有改动，无待答问题。

## 目标、证据与文件范围

目标是完成不触发上述禁令的 Q3 工程分组/标签/缓存/指标/确定性，以及 Q4 候选/图/事实服务/构筑消费者和相应接线检查。Q1 13 项、Q2 30 项已首次通过，见[实际报告](../2026-11-09-axis-generic-m7-q1q2.md)，没有改动这些受测源码，本批复用其结果，不重跑。

依据为[主执行书](2026-11-08-axis-generic-execution-plan.md)、[M7 报告](../2026-11-09-axis-generic-m7.md)和最新实际测试源码。已文本读取 Q3 两份测试、prepare/assessment 入口；Q4 候选、服务、消费者及所用工程夹具。Q3 的准备只调用 `prepare_records` 处理代码内工程记录，少量 gzip/清单临时文件属于测试缓存，不调用真实 catalog/deck_cache 或完整 prepare。Q4 的服务评分由 Mock 提供契约数字，不构造神经网络；构筑夹具使用合成目录和已生成候选，学习/引擎为关闭或断言不应调用的回调。名含 training 的两项候选用例只检查图特征委托和查询视图，不进入训练入口。

复用 `N:\YGO-Kito\_publish_20261030` 当前检出和已有 `E:\Ana\envs\pcacgate\python.exe`（本次已实际核验 Python 3.10.20、Torch 2.2.2）。不安装或升级环境。新增本补充和 `docs/reports/2026-11-09-axis-generic-m7-q3q4-facts.md`；增量更新主计划当前状态、第 9 节、M7 当前状态和 MASTER 追加记录。运行器、明确选择器、结果和临时文件写入新目录 `.cache/axis-generic-m7-q3q4-facts-20261109-01`；只保存本批拟改三份共享文档，不重复建立源码/全树基线，不复制权重。

初始不修改生产源码或测试。若发生真实失败，先读最新根因文件，交付包含具体文件/符号、动作、不变量和专项复验范围的增量修复补充，再修复；不降低原验收语义，不将工程夹具解释成真实能力。所有既有 dirty/untracked/deleted 与并行构筑改动保留。

## 精确选择和运行边界

Q3 预期 35 个：`tests.test_multifactor_splits.GroupSplitTests` 2 个、`MetricTests` 2 个；`tests.test_multifactor_data_v3.SourceComponentsTests` 10 个、`LabelPreparationTests` 14 个、`FixedMetricTests` 7 个。包含 V21 内存 SQLite 正反序以及两个 PYTHONHASHSEED × 两个 SQL 方向四格子进程。四个子进程只执行已读过的 `_v21_sql_preparation_snapshot`，不生成真实资料或调用模型。

Q4 事实路径预期 54 个：

- `tests.test_multifactor_candidates.CandidateGenerationTests` 8 个、`SharedGraphTests` 10 个、`TrainingDelegationTests` 2 个，共 20 个。
- `tests.test_multifactor_service.ServiceTests` 中除 `test_candidate_scorer_streams_all_queries_beyond_first_block`、`test_candidate_scorer_query_budget_rejects_before_forward` 外的 23 个明确方法。这两项构造 trainer，留后续模型评分检查。其余服务用例只用事实和 Mock 的契约输出，包含三个服务、分区分母、完整副本重观察、raw/calibrated/applied、能力与失败隔离及事实 CLI。
- `tests.test_construction_recognition.ConstructionRecognitionTests` 中除 `test_cb_hints_require_available_assist_facts_and_explicit_provider_support` 外的 11 个明确方法。排除项会调用 `_candidate_basic_cb`，即使其回调为工程夹具，本批也不执行。其余包含 off/observe 等价、assist 宿主事实政策、观察延时/预算隔离及未到达 CB 的集成断言。

实际选择器将按上述类和明确排除规则写入 `selections.json`，执行前确认 35/54 数量；不使用 discovery，不运行整份 service/consumer 模块中的排除项。未执行的神经编码/等变/成员评分、V16 梯度、Q5 损失/恢复和 CB 提示用例继续待验证。

运行环境沿用 Q1/Q2 的 `-B`、`PYTHONDONTWRITEBYTECODE=1`、当前 src/仓库路径、OMP/MKL 各 2 和现有 Conda DLL 路径；TEMP/TMP、Torch 缓存均显式放到本批 N 盘目录。运行器在加载测试前拦截模型调用、trainer 构造/训练、Adam/AdamW step、checkpoint 加载；另拦截真实 `prepare/load_sources/load_legacy_sources`、CB 入口/提议和原生目标核验。所有拦截均计数并失败，不执行原动作。

`subprocess.run` 只允许 Q3 中 `sys.executable -B -c` 调用固定 V21 快照、固定 ASC/DESC 参数、PYTHONHASHSEED 为 1/97 的四个进程；记录其种子/方向/退出码。Q4 不启动任何子进程。子进程继承本批临时目录、无字节码和线程环境。脚本超时或非零退出直接失败，不重试/降级/换解释器。四个子进程是工程测试进程，不是子代理。

顺序执行：

```powershell
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q3q4-facts-20261109-01/run_acceptance.py' q3
& 'E:\Ana\envs\pcacgate\python.exe' -B '.cache/axis-generic-m7-q3q4-facts-20261109-01/run_acceptance.py' q4_facts
```

## 逐步实施与验收

| 步骤 | 目标/符号与前置条件 | 具体动作和预期结果 | 不变量、检查方法与通过标准 | 失败/停止或回退 |
|---|---|---|---|---|
| S1 交付与准备 | 本补充、三份拟改共享文档、临时 runner/selections；Q1/Q2 已有通过结果、新目录原不存在 | 先交付本补充，再局部保存、写明确选择器和拦截运行器 | 原文副本逐字节相同；35/54 选择数可定位；只使用工程夹具与本批临时路径 | 目录冲突或保存/选择错误则停相关动作，不清理旧文件 |
| S2 Q3 | 两个 split 类、三个 data_v3 类；工程准备入口已读、运行器就绪 | 运行 35 个方法及其 V21 四格子进程，保存逐项结果和子进程控制 | 全部选定方法通过，0 skip/error/failure；禁止动作尝试 0；四格方向/种子和退出码记录完整 | 具体失败按 S4 处理；真实数据入口或模型调用被尝试时直接失败，不解除拦截 |
| S3 Q4 事实与接线 | 20 候选/图、23 服务、11 消费者方法；明确排除三项已核对 | 运行 54 个明确方法，包含观察延时/预算隔离及 assist 事实接线 | 所选方法全部通过，0 skip；前向/更新/训练/真实准备/CB/原生尝试均 0；不把 Mock 输出当模型推理成绩 | 具体失败按 S4；需要模型/CB 的行为只登记未执行，不代跑排除项 |
| S4 实际失败修复 | 仅实际失败相关文件/符号；已保存首次日志 | 先交付精确修复增量，再局部修改并复验失败方法和直接受影响集合 | 保留最初失败和最终结果；修复符合原语义，不用宽松断言、吞错或输出重排掩盖失败 | 若必须越过明确禁令才能修复/验证则保留未完成；回退只撤本批自有增量，不覆盖共享文件 |
| S5 文档同步 | 本批报告、主计划当前状态、M7 当前状态、MASTER 末尾；真实结果可用 | 登记每组方法数、失败/修复、V21 和接线实际结果，更新尚未运行的完整矩阵 | 只认实际工程证据；不勾选完整 Q4、Q5、全部 A/V 或整个 M7；所有历史/并行记录保留 | 共享内容变化则读最新增量合并，不使用保存副本恢复整文件 |
| S6 限定检查与收尾 | 本批差异/JSON/日志和必要修复文件 | 检查结果一致、禁止调用、原文保留和新增空白，tracked 路径命令级 Git 检查；无新证据不重跑已通过 Q1/Q2 | 工程结果和未运行范围可追溯，所有明确禁令保持；只在剩余允许范围继续 | 没有仍可独立推进的允许工作时报告实际完成及受禁令保留项，不自行启动禁止阶段 |

## 保留项

本批不能完成神经网络实际前向、微型更新、恢复下一步更新、V16 双正格梯度、真实资料准备/SQL 迁移、实际校准和能力发布。Q4 的模型部分、Q5 及排除的 CB 接口方法分别保留；V30 和环境 LoRA 留 T5。训练、课程、活动模型、LoRA、构筑定价/学习政策、调度、数据库和原生接口均不改；不提交、推送、合并或发布，不 checkout/reset/clean/stash、不恢复删除或新建 worktree。

## S4 精确修复增量：Windows 夹具读取编码

实际 Q3 为 35/35 通过。Q4 初次 54 项中 44 成功、10 error、0 failure/skip；10 项均在 `tests/test_construction_logic.py:fixture_assets` 的公共夹具读取后，因标签连接符被误解码而由 `BuildTask` 拒绝，尚未进入接线断言。首轮 JSON/日志保持不变。

必要只读环境诊断已执行，回执 `q4-encoding-diagnosis.json`：当前 `preferred_encoding=cp936`、`utf8_mode=0`；同一 UTF-8 工程 JSON 按默认编码读取后“·”数量为 0，显式 UTF-8 读取为 3。根因是测试夹具 `Path.read_text()` 未声明文件编码，不是生产标签契约失败。本修复不切换全局 UTF-8 模式、不改 JSON 或放宽连接符要求。

| 目标/关键符号 | 前置条件与具体动作 | 预期行为、不变量和逐项验收 | 失败/回退 |
|---|---|---|---|
| `tests/test_construction_logic.py:fixture_assets` | 先保存该文件当前完整字节；将唯一的 `configs/build-engineering-v1.json` 读取调用改为 `read_text(encoding="utf-8")` | 在同一 cp936/UTF-8 mode 0 环境正确读取 UTF-8 夹具；其他字符、函数、测试、生产契约及并行增量完全保留。反向替换本行后应与保存原文逐字相同 | 如锚点不唯一或出现并行变化，读最新增量合并；其他失败另行诊断，不恢复整份文件 |
| 本批 `run_acceptance.py`、`selections.json` | 保存两份当前文件；新增 `q4_fixture_retest`，只选择首轮 10 个 error 的明确方法，预期 10；将“零子进程”条件从仅匹配 `q4_facts` 改为所有非 q3 组 | 复验仍带原模型/更新/准备/CB/原生拦截，禁止调用尝试为 0，0 子进程；只新增复验选择，不改变原 Q3/Q4 断言或结果 | 选择数/来源不符停止；不覆盖首轮 q4_facts 结果，不重跑已经通过且不受夹具修复影响的 44 项 |
| 结果及交付文档 | 按同一解释器和原环境运行 `run_acceptance.py q4_fixture_retest`，保存独立 JSON/log | 10/10 成功、0 skip/error/failure；与首轮 44 个成功 ID 合并后是 54 个唯一明确方法，完整 Q4 事实集合有通过证据。Q1/Q2/Q3 不重跑 | 有剩余 error 则保留并按具体根因继续 S4；不可为通过而进入禁止路径 |

本增量先交付后实施，由主进程完成。仅修复一处测试基础设施编码；没有修改真实数据、生产源码、用户目标或模型。复验命令沿用本批解释器/临时目录/拦截，只将组参数改为 `q4_fixture_retest`。

## S4 第二次精确增量：assist 空证据与消费者夹具

编码修复后 10 个原 error 已全部越过编码入口；本次复验结果为 2 成功、4 failure、4 error，原始记录另存为 `q4_fixture_retest-result.json`，不覆盖首轮。新增真实根因为：assist 无既有 evidence 且当前候选没有可用能力时，`recognition_quality_evidence` 返回 None，而既有功能规范化器只接受 mapping；另有两个完整结果比较把真实 profiler 耗时混入语义相等、一个无限制 Mock 被误用为带 analyze_candidate 属性的对象、一个失败政策夹具选择了没有 draw 功能的首个候选。

运行器还拦截一次 `_candidate_basic_cb(..., provider=None)`。已读取该函数：provider=None 分支只构造 not_run 状态和任务/牌表绑定，不调用 provider、提议或引擎；此前拦截过宽，不是已执行 CB。真实 provider 分支与 CB 提议继续禁止。

| 文件/符号 | 前置条件与确定修改 | 预期结果、不变量与验收 | 失败/回退 |
|---|---|---|---|
| `src/ygo_kito/construction_recognition.py:recognition_quality_evidence.evidence` | 先保存当前字节；仅把“没有 existing 时的 prior”从 None 改为空 mapping `{}` | 空能力/无可用补充或 mapper 失败时交给原规范化器的仍是合法空证据，不触碰价格、标签、验证依据或能力状态；有 existing 时继续原样调用和返回其内容；off/observe 的 callable 身份不变。现有 unavailable assist、可用事实政策和 pending quality 方法验证实际消费者结果 | 不改 `_merge_function_evidence` 的 mapping 要求，不吞掉生产错误；若产生新失败按具体根因继续，不整文件回退 |
| `tests/test_construction_recognition.py:ConstructionRecognitionTests` | 先保存当前字节；setUp 中只固定 `construction_relations.perf_counter` 为 0 并注册清理，不改 time.monotonic；去重用例的 Mock 增加真实 callable spec 并断言记录成功；mapper failure 用例改选含 draw 卡的 `decks[1]`，先断言可用事实并断言 mapper 实际调用 | 两次完整 off/observe 结果和 session 比较仍原样保留；时间扰动仍使用 0→10000 的 monotonic 证明预算隔离；去重验证真正调用一次并产生有效记录；政策异常确实被触发且回退既有证据。其他方法/夹具不改 | 不删除耗时字段、放宽全结果相等或跳过失败用例；若 spec/候选能力不符则保留实际失败 |
| 临时 `run_acceptance.py` | 原禁止拦截保留；CB helper 改为只允许 provider 严格为 None 的原 not_run 分支，单独计数 status_only；非 None provider 和提议仍失败 | 不调用 CB provider、不运行 CB 搜索/原生；不把前次状态查询误报为实际 CB。其他模型/更新/加载/真实准备拦截不变 | 非 None provider 被尝试则失败，不以 Mock 或状态码豁免 |
| `selections.json` 与复验结果 | 新增 `q4_consumer_retest`，明确选择原 Q4 的 11 个非 CB 消费者方法；同一解释器、cp936 环境及拦截运行 | 11 个直接受影响的方法全部通过、0 skip/error/failure，禁止动作尝试 0。和原首轮 43 个候选/图/服务成功 ID 合并为 54 个唯一 Q4 事实方法；Q1/Q2/Q3 不重跑。首轮及第一次复验结果保留 | 若仍失败，只处理该失败，不能扩大到前向、训练、CB 或 CI |

本增量包含一处生产兼容性修复及对应测试夹具修正，先交付后实施。新增保存只涉及上述两个将改的源码文件，不建立全树基线。复验命令为本批 `run_acceptance.py q4_consumer_retest`；通过后再记录真实最终结果，不能预先记通过。

## S4 第三次精确增量：给事实夹具补全发动句

第二次增量后的 11 项消费者复验为 8 成功、3 failure、0 error/skip，禁止动作尝试为 0。受控事实诊断 `q4-facts-diagnosis.json` 显示候选 0/1/3 的能力声明均有 validated，但实际 functions/units 都为 0，因此 assist 正确拒绝把空能力交给宿主政策。

源码原因已定位：公共功能夹具的卡 2 文本是 `①：自己从卡组抽1张。`，既有 `effect_mechanisms._effect` 只在完整“可以/才能发动。”句后把操作认定为 effect；该不完整夹具的 draw 操作为 unknown，`semantics._operation_functions` 正确不把它当已知功能。本批不放宽解析器或 assist 准入。

只在 `tests/test_construction_recognition.py` 将公共 `fixture` 导入命名为 `functional_fixture`，增加局部同名 wrapper：调用原夹具后，把本地 assets 的卡 2 文本补成 `①：自己主要阶段可以发动。自己从卡组抽1张。`，原样返回其他 task/assets/graph/binder/decks/policy。这样保留正常观察器、候选过滤、版本化宿主政策及完整断言，不注入模型标签或虚构能力，不修改并行构筑的公共夹具或生产解析器。无 draw 卡的候选 0 仍保持空事实，继续覆盖上一增量修复的 `{}` 中性回退。

前置条件是本文件已保存且旧方法仍保留；修改后同一 cp936 环境运行原 11 个非 CB 消费者方法，以新组 `q4_complete_fixture_retest` 保存结果，不覆盖前次结果。由于局部 fixture 被这些方法共享，11 项为直接受影响复验范围。通过标准仍为 11/11、0 failure/error/skip、0 禁止动作尝试和 0 子进程；此前 Q1/Q2/Q3 与 43 个候选/图/服务成功项不重跑。若剩余失败继续按具体事实诊断，不能放宽 unknown、能力或宿主绑定规则。

## 本批最终实际状态

Q3 35 项首次通过，V21 四格子进程均退出 0。Q4 初次 44 成功/10 error，经上述增量后最后 11 个消费者全部通过，0 failure/error/skip、禁止动作尝试为空；与初次 43 个未受影响成功 ID 合并后，完整覆盖原 54 个明确 Q4 事实方法。结合 Q1/Q2 的 43 项，共 132 个不同方法取得通过结果，实际执行 166 次（含必要复验）。各次初始失败和复验 JSON/log 均保留。

实际修复为一处生产 `{}` 空证据回退、一处公共测试 UTF-8 读取及本地消费者夹具；没有更改生产解析器、标签准入、政策或模型。完整记录见[本批报告](../2026-11-09-axis-generic-m7-q3q4-facts.md)，最终保护/差异检查见 `.cache/axis-generic-m7-q3q4-facts-20261109-01/document-review.json`。剩余模型/更新/真实准备/CB/原生/CI 禁令有效，M7 整体未完成，T1–T5 未开始。

## S6 并行插入与共享方法复验

收尾首次文档核对为 requires_review，仅 MASTER 旧前缀不完全相同。实际差异只有并行构筑 W1-1 页首摘要插入，以及本批追加；原内容没有丢失，保留并行插入，不回写共享文档。该摘要自述规范化 v10，本识别任务不承接其成绩。

实测相关文件更新时间显示：W1 的 layer_flow/relations/quality 和公共功能测试修改发生在 Q4 首轮之后、最后 11 项消费者通过之前，因此最终消费者已使用这些最新文件。早先另有两个通过方法直接使用后来改动的 `construction_relations`，本次只追加精确复验：`tests.test_multifactor_batch1.SharedConstructionTests.test_constructed_group_uses_same_allocation_core` 和 `tests.test_multifactor_service.ServiceTests.test_contact_probability_only_uses_declared_single_sample`。

不改任何项目源码。临时选择器增加 `q_shared_recheck`（预期 2），以原运行器/拦截执行，单独保存 JSON/log；两个方法须全部通过、0 failure/error/skip、禁止动作尝试 0、子进程 0。最终仍为 132 个不同方法，物理执行数相应增加 2；其余不受并行变更影响的已通过方法不重复。最终回执保留 MASTER prefix=false 和识别并行插入后原内容完整两个实际字段，不把首次 requires_review 隐藏。
