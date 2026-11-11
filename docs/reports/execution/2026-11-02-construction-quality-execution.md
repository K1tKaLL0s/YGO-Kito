# 完整构筑质量评价实施书（2026-11-02）

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

本文件是[质量评价交接说明](2026-11-02-deepseek-construction-quality-handoff.md)第 6 节要求交付的机械执行书，对应本轮实际修改。范围仅限后端评价、政策与门槛接线及纯 CPU 定点测试；正式训练、CB、native 与生产权重继续暂停。

## 1 目标、目标行为与非目标

| 项 | 内容 |
|---|---|
| 原始任务 | 复用现有两层事实补齐“完整构筑质量评价”，并按同一规则接入候选选择、优化反馈与 `construction_gate` |
| 目标行为 | 新增一个纯入口，把 `axis`／`relations` 已有事实整理为 Main／Extra／Side 分区分数和五组评价，输出完整分或明确的未完成原因、已知缺口与相关未知；政策、通过线可版本化绑定；候选按同一政策重算并随保存恢复保留 |
| 非目标 | 不新建效果词典、不重解析卡文、不恢复旧参考归一评分器、不写死 60／25／15 或 70／56、不以 CB 结果参与构筑门槛、不改模型特征或训练路径、不产生卡名或主题配方 |
| 验收标准 | ①同一牌表交换“参考／候选”身份结果不变；②卡名与模块改名不改变分数；③未知不填 0 或 0.5，只列为 unknown；④不适用的 Extra／Side 不参与分母，也不允许候选删除必需分区来提高分数；⑤同名 0.9／0.8 折扣只在有效投入里生效一次；⑥参考与候选在同一政策下可比较并给出双向取舍；⑦门槛缺质量记录或不完整时不通过；⑧参考比例线使用政策内固定的参考分，不随候选改分母；⑨保存恢复后通关记录与质量记录一致 |

## 2 当前行为与真实证据

下表的行号为实施前位置，用于定位原始职责；实施后同一符号可能因新增内容下移。
| 现状 | 文件与位置 |
|---|---|
| 第一层输出功能 K／E／密度、分区 A／U、卡位与折扣台账 | `src/ygo_kito/construction_layers.py:375`（`evaluate_axis`）、`:306`（`_ratio`）、`:266`（`_discount_weights`） |
| 第二层输出 uses、joint_required、constraints、quantities、inventory_dependencies | `src/ygo_kito/construction_relations.py:777`（`evaluate_relations`）、`:943`（`compare_configurations`） |
| 门槛只接受 `axis`／`relations` 路径，缺政策返回 `quality_policy_unconfigured` | `src/ygo_kito/construction_progress.py:20`（原 `quality_policy`）、`:39`（原 `construction_gate`） |
| 优化轮按候选重算两层并写门槛、保存 continuation | `src/ygo_kito/construction_fill.py:588`（`construction_cycle`）、`:700`（候选与门槛）、`:746`（`finalize`） |
| 重选后重算门槛时未携带质量记录 | `src/ygo_kito/course_admission_policy.py:37` |
| 政策未配置是当前真实状态，不是待用户补指标 | `docs/development/construction-admission.md:3` |

固定验收量（匿名 ID）已在 `tests/test_construction_layers.py:237` 复现：入口 9.4／9.4、送墓融合 6.6／3.8、主轴随机堆墓 7.6／6.6、整副骨架 13.2／6.6、分母 18／21 与 31／21、额外占位 0.95／0.866667。本实施复用同一布局做评分标定。

## 3 允许与禁止修改范围

| 允许 | 禁止 |
|---|---|
| 新增 `src/ygo_kito/construction_quality.py` | 修改 `construction_layers.py` 的统计语义或返回 DTO |
| `construction_progress.py` 的政策与门槛扩展 | 修改 `construction_relations.py` 的求解与状态机 |
| `construction_fill.py` 的候选质量重算与反馈 | 改动 `build_contracts.py`、模型特征、训练和 CB 路径 |
| `course_admission_policy.py` 传入已保存质量记录 | 恢复旧评分器、参考归一公式、固定 56 线或私有评分账本 |
| 新增 `tests/test_construction_quality.py` 与本轮文档 | 重置/清理工作区既有未提交修改、自动提交或推送 |

## 4 技术路线与接口边界

- 纯函数入口：`evaluate_quality(evaluation, *, policy, generic_fits=(), duplicate_purposes=(), side_plan=None)`。`evaluation` 就是现有 `evaluate_layers` 记录；只读取 `axis` 与 `relations`，不重新解析卡文、不访问模型。
- 五组评价落到已定义分区，避免同一事实重复计分：
  - Main：`supply`（必需功能的覆盖与有效投入深度）、`continuation`（必需用途与联合必需的支撑状态）、`generic`（轴外未分配卡位对已声明环境问题的适配）。
  - Extra：`supply`（`mode=target` 的目标覆盖）、`limits`（声明的同时使用限制与共享资源冲突）、`duplication`（额外重复位声明的备用／续航用途）。
  - Side：`side_plan`（已声明问题、换入换出是否成立、换后原要求是否保留）。
- 归一化只使用显式声明量：`quality.targets[function_id]`、`quality.default_target`、`quality.weights[function_id]`、`quality.zone_weights`、`quality.dimensions`。未声明目标时记为 `coverage_only_without_declared_target`，不虚构阈值；权重缺省为适用项等权。
- 去重契约写入返回记录 `deduplication`：每个功能或用途只进一个维度；有效投入只在供给深度使用；折扣台账的 `effective` 不再用于追加重复惩罚；`joint_required` 只在 continuation 计一次；未分配卡位只进 generic；不使用卡名或主题配额。
- 未知处理：`value=None` 并进入 `unknowns`；维度 `status=partial`，分区 `status=partial_evidence`，总分 `complete=false` 但仍保留 `known_value`，不填 0 或 0.5。
- 政策：`quality_policy` 接受 `version/source/metrics` 加可选 `quality`、`pass`；`metrics` 路径根新增 `quality`；空 `metrics` 仅在带 `pass` 时合法；未知键一律 `ContractError`。
- 通过线：`pass` 支持 `absolute` 与 `reference_ratio`；后者要求固定的 `reference_id`、`score` 与 `QUALITY_VERSION`，门槛 = `ratio × score`，在门槛记录里保留比例、参考分与来源版本。
- 门槛绑定：`construction_gate(..., quality=None)` 校验 `policy_version`、`quality_config_sha256`、`deck_sha256`；`quality_binding` 记录 required／present／complete／value；新增原因 `quality_evaluation_missing`、`quality_evaluation_incomplete`、`quality_pass_line:<kind>:<status>`。无 `quality`／`pass`／`quality` 路径的旧政策行为不变，`GATE_VERSION` 不升级，旧 continuation 可读。
- 循环接线：`construction_cycle(..., quality_evidence=None)` 接收宿主提供的 `generic_fits`／`duplicate_purposes`／`side_plan`；每份候选按同一政策重算，写入 `row['quality_evaluation']`，随 `retained_candidates`、`candidate`、`continuation` 保存；阶段记录、`stages` 与统筹反馈带分数与最差缺口；恢复时校验质量记录未变。

## 5 分步实施与每步不变量

| 步 | 目标文件／符号 | 前置条件 | 修改动作 | 预期结果 | 验证 | 通过标准 | 失败停止条件 |
|---|---|---|---|---|---|---|---|
| 1 | `construction_quality.py`：`quality_config`、`pass_policy`、`GenericFit`、`DuplicatePurpose`、`SideSwap`、`SidePlan` | 已读两层 DTO | 新增类型与严格校验；未知键、非正数、非布尔、权重和≠1 全部拒绝 | 政策与证据有唯一合法形状 | `python -X utf8 -m unittest tests.test_construction_quality.QualityPolicyTests` | 全部通过 | 任一非法输入被接受即停止 |
| 2 | 同上：`_supply`、`_continuation`、`_limits`、`_duplication`、`_generic`、`_side` | 固定验收量已复现 | 五组行级计算，保存 `basis`／`target`／`weight`／`gaps`／`unknowns` | 每行可解释且单一归属 | 同上，`CompleteQualityTests` | 定向数值与依据匹配 | 出现同事实双计或未声明阈值即停止 |
| 3 | 同上：`_zone`、`_total`、`evaluate_quality`、`compare_quality` | 步 2 | 分区分数、适用性、权重、未完成原因与比较方向 | 参考>候选且给出双向取舍 | `CompleteQualityTests`、`.cache/construction-quality-20261102/probe_quality.py` | 布局 0 高于布局 1，转换瓶颈行领先，取舍列出 | 方向相反且无法解释即停止 |
| 4 | `construction_progress.py`：`quality_policy`、`_quality_source`、`_pass_line`、`_quality_binding`、`construction_gate`、`restore_progress` | 步 3 | 新增质量路径、通过线、绑定与恢复校验 | 缺记录／不完整／异候选不通过，且旧政策不变 | `tests.test_construction_progress`、`QualityGateTests` | 旧测试与新增门槛测试全通过 | 旧政策结果变化即回滚该步 |
| 5 | `construction_fill.py`：`_deficiencies`、`_quality_summary`、`_gate_feedback`、`construction_cycle`、`construct_task` | 步 4 | 每候选重算质量、写阶段与反馈、保存恢复 | 质量随候选与 continuation 绑定 | `QualityGateTests` | 通关候选质量完整、恢复到同值、篡改被拒 | 保存记录与门槛不一致即停止 |
| 6 | `course_admission_policy.py` | 步 5 | 重算门槛时传入已保存质量记录 | 重选后仍用同一质量证据 | `tests.test_course_admission_policy` | 既有用例通过 | 出现另一来源质量即停止 |
| 7 | `tests/test_construction_quality.py`、本轮报告与回执 | 步 1–6 | 14 项定点测试与机器回执 | 可重复的验收证据 | `.cache/construction-quality-20261102/run_checks.py` | 179 项通过、0 失败／错误／跳过 | 任一失败即停止并记录 |

## 6 错误处理、边界与兼容性

- 输入错误一律 `ContractError`：非 `combined` 记录、两层库存不一致、未声明政策、非正目标或权重、显式权重不足和为 1、未知键、非类型化证据、`side_plan` 问题与换备不匹配。
- 适用性：任务未要求额外功能时 Extra 记 `not_applicable` 并说明原因，声明的使用限制仍接入 Main 一次；任务未要求 Side 时 Side 不适用；要求 Side 但无换备方案时记 unknown 并附缺口。
- 未知：不完整状态不阻断已知改进的展示，但门槛必须 `complete` 才可能通过。
- 兼容：未声明 `quality`／`pass` 且无 `quality` 路径的政策，门槛输出除新增的 `quality_binding={'required': False}` 外与旧行为一致；`GATE_VERSION` 仍为 `construction-before-cb-v2`，旧 continuation 可恢复；旧通关记录没有质量绑定，恢复时不触发新校验。
- 回归风险：`construction_cycle` 新增关键字参数不改变既有调用；阶段字典新增 `quality_evaluation`／`quality_summary` 字段；`finalize` 与重选路径改用候选自身的质量记录。

## 7 测试与验证方案

- 定点：布局对照、改名不变、未知处理、必需项不可删除、Extra／Side 不适用、额外重复位声明、限制与接续、泛用条目、Side 换备、政策校验、比较校验、门槛绑定、参考比例线、保存恢复与篡改拒绝、无 Torch／CB 导入。
- 环境：Windows Python 3.12.1（CPU Torch 2.9.1 未用于本批），`PYTHONPATH=src`，`-X utf8`。
- 命令：`python -X utf8 -m unittest tests.test_construction_quality`；批量回执 `.cache/construction-quality-20261102/run_checks.py`。
- 通过标准：0 失败、0 错误、0 跳过；回执写入 `docs/reports/2026-11-02-construction-quality-tests.json`。

## 8 风险、回滚、停止条件与未验证假设

- 回滚：删除新模块与测试、还原 `construction_progress.py`／`construction_fill.py`／`course_admission_policy.py` 的本轮改动即可；不改动已保存 continuation 的读法。
- 停止条件：旧政策结果发生变化、保存恢复无法重现质量记录、评分方向与文档量算相反且无法解释、需要虚构阈值才能比较。
- 未验证假设：①生产政策的 `targets`／`weights`／通过线尚未确定；②真实 2207 参考与候选尚未用本评价器重算（需时期资源，不在本批执行）；③卡位效率尚未进入标量，需要声明的密度基准；④政策声明量之外的环境适配仍需宿主逐条判断。

## 9 实施路由

主进程直接实施：改动集中在一个新模块与三处接线，接口由现有 DTO 决定，定点测试可独立复现；无需子代理分工。

## 10 实施结果

见[实施报告](../2026-11-02-construction-quality-scoring.md)与[机器回执](../2026-11-02-construction-quality-tests.json)。
