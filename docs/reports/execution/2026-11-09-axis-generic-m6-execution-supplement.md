# M6 机械执行补充

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

日期：2026-11-09，香港时间。用户已授权按主执行书实施 M6；本补充交付后直接由主进程执行，不启用子代理。后续交接指定 gpt-6.1-sol、推理强度 MAX。当前没有待答问题。

## 目标、当前行为与边界

目标为 A09/A10、V23–V27：交付三个分析服务、结果 DTO、明确能力状态及 off/observe/assist，并接入实际构筑消费者。`analysis.py` 当前只有 v2 迁移；`scoring.CandidateScorer` 当前只有旧候选评分并在模块导入时引入 Torch；`construction_recognition.py` 已有 M2 共用分配接口，必须保留。`construction_fill.py` 已承接构筑第七批的功能评价、恢复和 gate；只在完整候选生成后增加识别事实与记录接口，不重写构筑政策。

允许修改：`src/ygo_kito/multifactor/{contracts,analysis,scoring,__init__,__main__}.py`、`src/ygo_kito/construction_recognition.py`、`src/ygo_kito/construction_fill.py`，新增 `tests/test_multifactor_service.py`、`tests/test_construction_recognition.py`，更新本补充、主执行书、M6 报告和 MASTER-CHECKLIST。必要的新 DTO 不改变 M5 输入/特征或学习任务协议。

禁止修改：权重、活动模型指针、训练与课程暂停、LoRA、构筑评分/学习政策、调度、数据库和用户目标。不实施 M7 或 T1–T4。不创建 worktree，不 checkout/reset/clean/stash，不恢复既有删除，不提交或发布。不执行测试（包括收集/静态业务用例）、Python/项目/Torch 导入、AST/编译、构建、推理、训练、数据准备、CB、原生引擎或 CI。

## 确定的数据流

请求上下文保存规则、明确目标、模式、可见状态与抽样声明，不接受监督块。宿主注入的事实提供者读取已存在的卡效与库存；服务用共用 `build_analysis_graph` 构图、生成全部自然候选，再做功能契约和可选评分。缺失/未训练/未校准能力输出 unknown；原始诊断、校准结果、应用结果分开。可用能力必须显式给出 producer/version/验证依据，不能由更新计数推定发布。

构筑适配从现有资产生成规范事实。off 不调用 provider/scorer 或加载模型；observe 只追加结果记录。assist 仅把明确可用能力的事实交给宿主已有质量证据政策；宿主负责把它转换为现有 layer 的证据协议，现有 evaluator/gate 继续定价和判定。CB 的可选提示只含候选、资源、分支、时序及缺件，须由宿主明确声明接收；合法性和路线成功仍来自外部验证结果。

## 逐步机械实施与验收

| 步骤 | 文件/符号与前置条件 | 具体动作和预期结果 | 不变量、检查方法与通过标准 | 失败/回退边界 |
|---|---|---|---|---|
| S1 保存 | 上述允许路径；读到当前实际文件后 | 在 `.cache/axis-generic-m6-20261109-01` 保存相关小型源码与文档，登记原路径/原不存在状态、当前 tracked deletion；不复制数据或权重 | PowerShell 逐文件字节比较，所有存在路径副本一致，原不存在路径仅登记 | 路径已被占用或比较失败则停止写代码；不用 HEAD 恢复 |
| S2 契约 | `contracts` 的请求/能力/副本操作/结果 DTO，`analysis.RoleAnalyzer` | 新增服务上下文、能力、区域/数量操作及结果对象；保留原 AnalysisContext、DeckSpec 和迁移接口；服务注入事实/scorer/预算，实现 analyze_deck/assess_unit | 文本检查三入口、无监督块、缺失区域与空区分别输出；底层契约检查用明确别名；unit 定义和 receiver 实例分别评价 | 损坏请求抛 FactorContractError；事实能力局部失败保留 unknown，不能伪造零或启动模型 |
| S3 配置重算 | `analysis.compare_copy_change`，S2 已具备 | add/remove 都声明分区/数量；remove=null 是加量，add=null 是减量；实际应用后对前后完整配置重新读事实/构图/求解，输出相关依赖、调用、冲突、密度和分母差异 | V23/V24 用例源码覆盖 40/41/45/50/55/60、空/未知分区、等量替换及缺替代；只有明确抽样时复用 single_event_probabilities；整体偏好缺可靠比较证据时 unknown | 未知被改区域、移除不足、数量非法在调用 provider 前拒绝；不相乘接触概率、不硬编码合法张数 |
| S4 评分/兼容 | `scoring.CandidateScorer`、包导出和 CLI；S2 完成 | 增加 v3 事实查询评分路径，按能力逐头启停/按32查询分块；超过预算整头拒答；修正旧解释，旧接口保留；CLI 的分析路径无需加载 Torch/随机模型 | V25/V27 源码覆盖费用/效果和次数语义变化、去重；新头未发布不输出 applied；旧 large/small 无可靠映射保持 unknown | 单头异常只停该头；不修改模型加载绑定或以随机 logits 当结论 |
| S5 构筑消费者 | `construction_recognition`、`construction_fill.build_axis_skeleton/fill_with_existing/construction_cycle/_candidate_basic_cb`；读最新共享文件后增量补丁 | 在候选生成后调用可选 provider，记录到现有结果；assist 用宿主质量证据回调连接 layer，明确声明的 CB provider 接收提示；保留原 allocate_relation_group | V26 源码比较 off/observe 的顺序、分值、学习和 gate；assist 事实有 capability/producer/version，重复事实按结构身份去重；观察记录不进入学习证据 | provider 失效回到原构筑路径并记录局部原因；目标变化或隐藏定价停止该接线，逆向撤回本批补丁 |
| S6 用例/状态 | 两个新增测试文件、主计划/MASTER/M6 报告；S2–S5 文本修改完成 | 编写有意义的 V23–V27/A09/A10 用例源码，登记实现与剩余项；只标已实施、待验证 | 只用 PowerShell 文本/JSON/必要文件保护比较及 Git diff --check；检查范围外登记文件和既有删除；测试执行数0，运行能力不勾通过 | 若发现范围外并行变更，保留并说明；不覆盖以求摘要一致，不借构筑聊天测试成绩 |

## 验证与回退

本轮可执行检查仅为文件保护比较、文本/JSON 回读、差异和空白检查。未来授权运行时才执行两个新增测试模块及必要的构筑集成，不在本轮尝试。语法、导入、数值、实际模型与恢复行为均待验证。

回退只按本批修改前副本和增量补丁逐文件撤回本批变更；遇并行更新重新读取并合并，不整文件覆盖。源码指纹改变可能影响历史 checkpoint 恢复；保留原源码副本及全部权重，不关闭绑定校验。

## 本批实际状态

S1–S6 的源码与记录工作已实施，A09/A10 与 V23–V27 的运行验收仍待授权。新增25个服务方法及12个构筑接线方法的测试源码，执行数0；没有进行测试收集或项目导入。构筑并行更新至第九批，当前共享规范化为 v8，相关文件保留。静态回执使用保留 CRLF 的命令级空白规则，具体结果和独立交接摘要见 [M6 报告](../2026-11-09-axis-generic-m6.md)。M7 与 T1–T4 未开始，后续任务指定 gpt-6.1-sol、推理强度 MAX。
