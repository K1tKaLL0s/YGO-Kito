# 构筑模块代码核对与旧入口清理

2026-11-10 更正：后续[2207真实构筑尝试](2026-11-10-2207-construction-attempt.md)在默认入口暴露了未覆盖边界。识别信息误当必需目标已最小修复、2项检查通过；参考与模型工作池不一致仍使程序异常中止，W4-1已重开，固定清单当前12／13完成。下文147项是此前静态阶段的真实记录，不能继续作为整体可运行或全部实现完成的确认。

2026-11-09，实际源码 `N:\YGO-Kito\_publish_20261030`。主进程按[机械执行书](execution/2026-11-09-construction-module-cleanup-execution.md)核对[正式优化方案](../current/construction-scoring.md)、主次目标百分比修订、38 条验收及补充结构，并检查实际训练调用点。此前“全部完成”的表述不能替代逐项源码证据。本轮又发现并补齐原方案第 10.1 节的连续不足提示，修复监督版本、预算读取和模型状态恢复问题，删除明确无业务调用的旧实现。

当前构筑代码使用质量 v4 `functional_log2`、准入 v3、规范化 v13；原公式及主目标额外 +100%、次目标额外 +50% 保持。147 个不同静态测试方法均取得最终通过结果，实际分组及中间失败见下文。没有运行训练、CB、真实模型推理、原生引擎、完整 CI 或 Linux 监督进程，也没有修改权重、课程状态、暂停文件和指针。无子代理、待答问题或本轮未处理的已确认代码缺口。

## 设计与实际调用

| 设计要求 | 当前代码与调用关系 | 核对结论及直接证据 |
| --- | --- | --- |
| 第 2、9 节：目标骨架一次，优化模型持续完成构筑 | `ConstructionController`／`construction_fill.construct_task` → `construction_cycle` → `build_axis_skeleton`、`fill_with_existing` | 固定任务、自主主题及恢复共用循环。`model_group`、`lora_group`、`build_training`、`group_runner` 仍有实际消费者，保留这些调用；返回的 `best_deck` 是当前结果投影。9 个当前进度测试及 F1281 对照通过。 |
| 第 3–5 节：固定政策、实际功能、同口径最终 S | `host_construction_quality`／`AutonomousConstructionKernel.quality_for_task` → 自动主题规则 → `normalize_function_uses` → `evaluate_functional_quality` | 规则由原任务及固定卡池确定；候选不能改权重。17 个自动主题测试、28 个纯计分测试通过。没有加入卡组专用评分。 |
| 第 6–8 节：自身条件、共同要求、限制、Side 及相关未知 | 既有 `construction_inventory`、`construction_relations` 与效果适配；实际整数资源、完整代价和换备容量 | 复用既有检查，没有新增资源分配器。17 个库存测试及 49 个功能适配测试通过；缺少必要局面、未解析条件和预算边界仍明确保留。 |
| 第 9 节：先逐候选评价，后选择、保留和学习 | `fill_with_existing` → 当前质量比较 → `construction_learning`；`quality_selection_allowed`／`select_retained` | 删除旧保留排序和旧层优先分支；未评完候选保存队列而不按旧分发布。当前分数进入反馈和严格偏好标签。3 个纯静态选择／消费契约及恢复重选测试通过。 |
| 第 10.1 节：静态准入、参考及连续不足提示 | `construction_gate`、`record_reference_attempt`、循环后的 `session.record_feedback` | 此前缺失的提示已接到下一轮优化输入。两次确认低于参考门槛后依次检查主轴、副轴、泛用；参考缺失、unknown、错误、暂停和预算不计失败，恢复不重复计数，政策修订重置。6 个提示测试通过。 |
| 第 10.2 节：旧档和政策变更 | `restore_progress`、`revise_quality_policy` | schema 2 原字典及来源归档后转待重评；schema 3 继续当前评价。旧标量和旧准入不复用，不重生成骨架或丢失进度。F193、F220、F1281 和进度／提示恢复对照通过。 |
| 第 11 节：旧机制退出、真实调用同步 | `scripts/design_supervisor.py`、`scripts/local_course_collaboration.py`、CPU 测试白名单 | 监督改用当前质量及准入契约，检查骨架与完整候选各自的证据，支持现有嵌套条件、字段子类及等级条件；活动脚本已同步新的质量选择名称。4 个直接静态监督测试通过。 |

F 后接数字沿用[验收表](execution/2026-11-09-construction-acceptance-alignment.md)的测试文件定位。正式训练调用点仅作源码和字段衔接核对；本轮运行证据不扩展为真实模型或训练完成成绩。

## 实际缺口和修复

| 问题 | 修复 | 通过证据 |
| --- | --- | --- |
| 只有库存停滞计数，没有两次确认不足及分阶段提示 | 在已有 continuation 中记录完成的参考比较，以原任务、政策、候选版本和迭代归属；实际循环消费并放入后续反馈 | `ReferenceAttemptTests` 6 项；真实静态循环得到 `[None, main_axis, secondary_axes, generic]`，JSON 恢复、政策修订及非失败原因对照通过。提示只谈功能和配套，不带参考卡名、配方或精确投入。 |
| 监督脚本仍接受旧准入 v2，也未按当前目标骨架职责读取证据 | 改接当前 v3／v4 绑定，核对候选自己的门槛、完整性、原任务硬条件及指定参考；骨架读取部分提案，优化读取完整候选记录 | `StaticSupervisorTests`：当前部分骨架通过；旧版本、错牌表、失败硬要求拒绝。 |
| 监督复用公开条件判断时没有读取等级字段 | 查询补齐 `level`，删除过时重复条件判断 | 等级满足／不满足、嵌套条件和原生字段子类对照通过；修复前确实复现 `KeyError: level`。 |
| 事实预算为零仍调用卡效解析 | 在 `dependencies.specs` 前检查剩余预算 | 保留的零预算测试复现后通过；预算为零不读取效果记录。 |
| 候选评分临时 `eval()` 后未恢复调用方原模式，非法分数退出也会残留状态 | 评分块以 `try/finally` 恢复原 `training` 标志 | 正常分数与非法 NaN 分数两种静态替身检查通过；不执行模型前向或参数更新。 |
| 入口仍有不可进入的旧分支、旧类型和误导名称 | 删除下表所列实现；严格要求当前评价单位；同步调用方及维护文档 | 活动源码、脚本无悬空导入；旧接口不存在、旧政策和旧评分参数拒绝；当前排序、重选、旧档迁移及反馈通过。 |

## 删除项及保留理由

| 删除项 | 调用依据与当前替代 |
| --- | --- |
| `src/ygo_kito/construction_contract.py` | 70／56 草稿只被其专属测试导入，没有业务或训练调用。当前政策与正式契约由 `construction_quality`／`construction_progress` 承担。同步删除专属 `test_construction_contract.py` 的 7 个草稿测试。 |
| `GenericFit`、`DuplicatePurpose`、`SideValue`、`SlotUse`、`QualityLoss`、`SideDeck` 及旧七项常量、旧版本别名 | 只有旧百分制测试消费这些类型。旧档迁移保存原字典，不构造这些类型。删除 `test_construction_quality.py` 的 44 个旧 API／旧算法测试；不把删除记成测试通过。 |
| `construction_candidates.retained_order` | 仅旧分支和旧测试调用；当前逐候选评价及最终 S 排序已接管。 |
| `construction_layer_flow.compare_layer_candidates`、旧 `_evaluate_layers` 多候选排序 | 生产只需要单候选投影，其旧排序结果被丢弃。改成 `_project_layers`，保留当前诊断。13 条只针对旧最终层排序的断言退出；仍有用途的 7 条诊断／预算／上下文检查保留并通过。 |
| 填卡、摘要、绑定、恢复及重选中的不可达旧算法分支 | 当前政策验证之后不可能执行的旧百分制、选中后补评分、schema 2 新建、旧单位摘要和重复版本分支移除。schema 2 读取仍属有效迁移。 |
| `layer_selection_allowed` 旧名称 | 实际判断已按最终质量，改名 `quality_selection_allowed`；本地课程脚本和测试同步，不留第二个别名入口。 |
| 上述三个已删文件的孤立字节码 | 仅删除这三个文件对应的 `.pyc`，逐个核对目标在当前工作区；没有批量清理其他缓存。 |

旧测试退出后的有效要求仍有当前覆盖：功能身份／重复证明／改名、完整性与相关未知、同一损失不重复结算、原任务硬要求、Side 隔离及方向、错政策／错牌表拒绝，分别由现行 28 个纯计分、49 个功能适配、17 个库存、17 个自动主题及进度／选择测试承担。9 个进度测试和原编辑追踪测试迁移至当前政策，保留原行为断言；未用删除失败测试代替修复。

没有删除：当前轴／库存／关系诊断、骨架依据、偏好环检查仍用的 `order_by_layers`、正式公开的 `evaluate_quality`／`compare_quality`、有效训练调用者、schema 2 原始资料和历史报告。公开入口即使本仓调用少，也不能据此判为死代码；只删除已明确被当前路径替代且无实际消费者的实现。

## 实际验证记录

| 当前检查组 | 不同方法数 |
| --- | ---: |
| 纯功能计分 | 28 |
| 实际功能适配与候选循环 | 49 |
| 自动主题／目标 | 17 |
| 库存、对象及素材 | 17 |
| 当前进度、反馈及恢复 | 9 |
| 保留的层诊断／预算／上下文 | 7 |
| 候选生成、编辑追踪和模式恢复 | 5 |
| 提示 6、旧入口拒绝 2、直接监督 4 | 12 |
| 明确选取的纯静态选择／消费契约 | 3 |
| 合计 | 147 |

首次上述 147 项执行得到 145 通过、2 失败；一个断言仍硬编码规范化 v12，另一个依赖已退出的层排序且缺少当前效果条件。前者改为核对现行版本常量，后者提供完整卡文、发动条件与整份代价，并对照配套缺失／存在时实际 S=0／1 的选择；没有把 unknown 置真。两项修正后定点通过。

其后清理重选重复分支、测试未用导入及孤立字节码，最终 6 个相关方法通过。监督等级字段复现后修复，最终 4 个直接监督方法通过。按每个方法的最后一次实际结果汇总，147 个不同方法均通过，无未闭合失败、error 或跳过；不是同一次“147 项全绿”，也不把定点复查重复累计为新方法。

原始记录：[首次 147 项 JSON](../../.cache/construction-cleanup-20261109/static-review-first.json)、[文本](../../.cache/construction-cleanup-20261109/static-review-first.txt)；[最终 6 项 JSON](../../.cache/construction-cleanup-20261109/static-review-final-focused.json)、[文本](../../.cache/construction-cleanup-20261109/static-review-final-focused.txt)；[最终监督 4 项 JSON](../../.cache/construction-cleanup-20261109/static-review-final-observer.json)、[文本](../../.cache/construction-cleanup-20261109/static-review-final-observer.txt)；[逐方法最终结果汇总](../../.cache/construction-cleanup-20261109/static-review-summary.json)。这些进程均未加载 Torch。早期还复现并闭合了零预算读取、模式未恢复、夹具临时目录受限及待评夹具混入完整零分备选等问题，没有隐藏为 skip。

收尾检查：17 个本轮 Python 文件语法及顶层导入、174 个活动源码／脚本的旧名称引用、18 个构筑 CPU 白名单模块路径、8 份维护文档的 257 个本地链接、验收表 48 个测试方法定位通过；38／12／13 行数量保持。实际记录见[源码与文档检查](../../.cache/construction-cleanup-20261109/final-source-document-checks.json)。此前 68 项报告的内容摘要只对应当时文件，不冒充本轮源码摘要。147 项不包含真实模型入口、参数更新、CB、Linux 监督进程或完整 CI。

当前[验收表](execution/2026-11-09-construction-acceptance-alignment.md)保留原 38 条及 12 行补充结构，把本轮漏验补入 W4-1／W5-3／W6-2。固定清单仍为六包 13 项，不另建无终点的加固项目。模块软件实现及本轮实际检查范围已闭合；必要输入的 unknown 与真实训练成绩按各自记录判断。
