# 2026-10-31 优化机械执行书

2026-11-02 状态：本文为历史实施记录。旧标量评分、私有情境账本、评分学习接口和重复构筑入口已被删除或迁移，不再作为当前执行指令。当前入口、边界和验收以 [统一执行书](2026-11-02-construction-unification.md) 为准。

这是本轮修改前已在对话交付的执行书及实施过程中明确的 A 线入口补充的落盘版本。主进程直接实施，不使用子代理。用户授权完成 A 线收尾、B 线评分与基础 CB、C 线真实学习闭环；正式训练继续暂停。本轮额度上限按开始时账户已用 88% 至最多 98% 控制，账户统计是共享窗口，并非任务独占计量。

## 目标与边界

实施位置为 `_publish_20261030`，基线 `3f57198`，分支 `codex/optimization-20261031`。运行资源沿用 `_local_cpu_20261027` 和已存在的 WSL CPU Python。不安装依赖，不启动 GPU/正式对局训练，不提交、推送或合并。

保留旧 `2207-course-005`、迁移后的 `2207-course-006/course/checkpoint-1.weights`、历史预测账本、训练 hold 和全部中止记录。对独立目录中的模型副本允许有限构建前向、原生规则验证和一次真实优化器更新。私有参考牌表、语义审阅与校准清单继续留在源码仓库之外的 `evaluator-private`。

当前实证：迁移检查点为 paused，记录 27 条；build_goal=5、build_optimizer=0、duel=27、coordinator=37。原有评分只有局部上下文，不能把缺失上下文算作低分失败。旧 20/50 策略在明显低于预测的样例上仍可能不触发。

## A：运行入口与恢复收尾

- 文件/符号：`local-training.ps1`、`local_training_worker.main`、`local_training_status.main`、`local_course_source_continuation.validate_continuation`、`local_foundation_course.run`、`ScenarioCourse._game`、`observed_bot_evidence.validate_source_review_schema`，以及准备入口 `prepare_paused_course_runtime.py`。
- 前置：迁移状态完整，hold 存在，没有待提交的对局或反馈事务。
- 动作：显式分离源码根、资源根、状态根；续跑入口使用当前源码与 course-006；允许不依赖冻结实现 tar 的状态指针；保留结构、资源、规则、词表、对手和模型完整性检查；增加只读 Check 动作。状态检查记录实际 worker 路径。恢复 bot 原始证明时逐项匹配已保存校验值，将证明持久化到新目录；执行源 review 作为宿主 sidecar 读取，避免改写学习权重绑定。
- 预期：Check 显示当前源码、新状态与 held=true；Resume 在启动前被 hold 阻止；原资格证明可由真实 adapter 重新绑定。
- 验证：PowerShell 解析与 `local-training.ps1 -Action Check -Job course`；带 hold 的 Resume 拒绝；`prepare_paused_course_runtime.py` 使用原始资格校验值和已完成普通对局回放证据执行真实绑定检查。
- 不变量/停止：任何历史证明字节、资格或结构域不匹配即停止该恢复步骤，不覆盖不同文件，不重新开训练来补证据。

## B1：单位积木、主题修正与实际候选评分

- 文件/符号：`reference_scoring.theme_priors`、`candidate_context.ReviewedCandidateContext`、`course_admission_policy`、`local_course_forecast.decide`、`local_foundation_course.execute_cycle`；私有 `unit-block-v1` 校准、语义与候选上下文文件。
- 前置：实际候选和公开卡文已存在，旧参考审阅可复用，参考内容不进入模型输入。
- 动作：默认每个效果积木基础分为 1；珠泪墓融等主题修正单独记录。建立新评分 epoch，不改旧权重/分数/失败计数；2022-07 与 2022-10 使用各自重标定参考。逐效果列出条件、代价、次数、资源、冲突；资源查询对每副实际牌表重新计算。缺少资源计已知不可用，缺少上下文先进入 review_context，再评分。仅完整且合法的严格分差产生构建偏好标签。
- 预期：未知不触发低分失败或提示；实际候选得到可追溯分数；新 epoch 断点恢复仍选择相同策略；其他主题不会沿用珠泪加成。
- 验证：定点测试覆盖主题隔离、候选资源缺失、未知排除、epoch 恢复和标签篡改拒绝；实际候选评分写入隔离验证目录。
- 不变量/停止：不复制参考牌表和参考可行性作为当前候选事实；无完整严格比较则不生成优化器标签。

## B2：符号积木优先的基础 CB

- 文件/符号：`basic_cb_inference.BLOCK_ROUTES/proposals/infer_basic_cb`、`AutonomousConstructionKernel.run_selected`。
- 前置：四次具体构建交接完成，卡组通过原任务约束。
- 动作：先枚举融合/同调/超量的符号模板，再绑定实际候选中的卡与素材；不同目标交错分配搜索额度。明确要求墓地自身作为素材的效果只要求该必要来源；手卡/场上可选来源不变成额外硬条件。规则引擎成功后才计算路线积木分，保留实际起手假设、素材移动与动作证明。
- 预期：实际牌表至少找到一条由原生核心确认的基础路线；unknown 和未展开状态无路线分，不冒充失败标签。
- 验证：正常原生 CB 搜索及具体路线证据；调度公平性、来源匹配、unknown 无分的回归测试。
- 不变量/停止：不修改原构建目标、卡组或原生 response guard；不预先指定固定 CB 组件约束构建；预算未确定保留 unknown。

## C1：预测差距的条件触发

- 文件/符号：`FeedbackPolicy.responsive_twenty_fifty`、`local_course_forecast.CourseForecast`。
- 动作：新增 v3 策略，新窗口使用“缺少的胜场数 > max(1, sqrt(n*p*(1-p)))”的工程判据。20 场后显著落后触发重评，50 场后仍落后触发重构。旧 v2 窗口及其原阈值保持可读，不改写历史预测。
- 预期/验证：19 场不触发；预测 0.5、20 场 2 胜触发重评；50 场 10 胜触发重构；接近或超过预测不触发；策略序列化往返与旧策略行为保持。
- 停止：非法统计或跨窗口数据拒绝。这个工程判据不声称是显著性检验。

## C2：真实构建学习闭环

- 文件/符号：`rubric_learning`、`semantic_training`、`local_course_collaboration.cycle`、`validate_paused_optimization.py`。
- 前置：同任务至少两副合法候选，完整审阅且严格分差；使用隔离模型副本、独立 DataIndex 和输出目录。
- 动作：释放的实际候选分数形成偏好样本，沿现有 DataIndex/反馈更新入口执行 build_optimizer 更新；保存参数变化与去重收据。下一次选牌读取更新后的模型，随后真实运行 goal→optimizer→goal→optimizer 四次具体牌表交接，读入已完成历史对局反馈。新构建任务由实际模型重新选择，候选不在新任务池内时按现有规则重新构建，不放宽卡池。
- 预期：有非零梯度、非零参数变化；下一阶段实际消费更新参数；重复同一反馈被拒绝；四阶段间输出/输入相接，完成反馈到新构建的闭环。
- 验证：定点真实 PyTorch 更新测试；从迁移权重运行有界验证，记录候选评分、CB、前后排序、下一轮四阶段和普通效果对局精确回放。核对生产检查点、latest 指针和 hold 均未变化。
- 不变量/停止：参考分不是胜率标签；不从单局或未知路线编造偏好；不将隔离验证权重写回正式课程。不满足严格比较或四次交接时报告实际失败并定位修复。

## 统一验证与回退

使用既有 WSL `venv-linux`，`PYTHONPATH` 指向当前 `src`，`PYTHONDONTWRITEBYTECODE=1`。真实隔离验证写 N 盘；完整 CPU 白名单首次使用 N 盘临时目录时发生严重 DrvFS I/O 等待，安全中断后改用已实测约 7.6 GiB 可用空间的 WSL `/dev/shm/ygo-optimization-20261031`，最终日志仍写 N 盘。运行 `scripts/check_merge_candidate.py` 的明确 CPU 白名单；不执行 fault reproduction、response-buffer 实验或无筛选 discovery。原生验证仅普通合法执行与回放。

代码用 git diff 检查；不撤销已有 DeepSeek 提交及用户文件。新增校准、验证和宿主 sidecar 与旧结果分开保存，失败证据保留。回退时恢复本轮修改文件并切回旧入口；正式模型和旧证据无需回滚，因为本轮不写它们。最终结果、剩余项和实际命令见同日实施报告。
