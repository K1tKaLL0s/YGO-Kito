# 轴与泛用识别 M0–M2 首批实施记录

日期：2026-11-08，香港时间。实施目录：`N:\YGO-Kito\_publish_20261030`。

本聊天授权：按执行书实施 M0–M2，保留全部现有改动，仍不运行测试、推理或训练。状态为“M0 保存完成；M1–M2 已实现、待验证”。未将任何验收用例登记为运行通过。

## 1. 代码结果

| 批次 | 实际修改 | 当前状态 |
|---|---|---|
| M0 | 在 `.cache/axis-generic-m0-20261108-01` 保存整个当前 multifactor Python 包、共享文件和受影响既有测试源码；manifest 记录原存在/不存在、大小、分支、HEAD、修改前 Git 状态；复制前后逐文件字节比较 | 保存与复制内容核对已完成 |
| M1 契约 | 公共 DeckSpec、UnitSpec、AnalysisContext、CandidateInsert 归入 contracts；analysis 保持原导出名；RoleInput 主加载器读取 `axis-input-v3` 的 observations 外壳并保留旧 v2/v7 路径 | 已实现，未执行回读用例 |
| M1 标签 | LabelCell 接受布尔/数值/受控类别，LabelSet 按任务校验值域并保留 annotation_complete；Targets、AnnotationRecord 使用逐格状态与证据，旧数值/None 在显式边界迁移 | 已实现，未执行标签/损失用例 |
| M2 单元 | minimum_member_branches 递归闭合 required 与每条 alternatives；每条路径分别绑定结构和局面条件；不把多个可行包合并；旧 minimum_members 遇歧义要求选择分支 | 已实现，未执行闭包用例 |
| M2 资源 | 有界回溯，支持 all/any/at_least_k/not、整数多供给、物理池别名、共享消耗、占用/保留时段、distinct、显式观测覆盖与 unknown/overflow | 已实现，未执行求解用例 |
| M2 消费 | prepare_function_candidate 默认最小包与显式包均在成本调用前复查；复杂条件需分支感知的成本 provider；构筑简单、已知、无前置索取的 InputGroup 委托同一个分配核心 | 已实现，未执行消费用例 |

没有进入 M3 的候选轴与新版图构造、M4 的数据准备/划分、M5 的新网络头、M6 的服务接线和 M7 的运行验收。network.py 只加了 v3 入口拒绝保护，防止旧编码器丢弃新字段。新任务标签已可存储和校验；当前旧训练器遇新 task_labels 明确拒绝，等待 M5 接入。

## 2. 关键接口与语义

RoleInput v3 使用 `schema_version="axis-input-v3"`，实际观察位于 observations。包含 analysis_mode、analysis_context、deck、unit、visible_state、insertion 与现有图对象。主加载器允许外层 provenance，但不把它保存在 RoleInput 中；迁移器把旧 mechanism 注释移到 provenance.legacy_mechanism，记录写入者须把该监督材料保存在外部记录中。v3 observations 禁止把旧 mechanism 监督字段混入。

DeckSpec 每个分区用 None 表示未知，用空 tuple 表示已知空。candidate_insert 必须声明三分区增减量和槽位上限，校验移除数量、插入后的总数及所声明单元的实际存在。state_evaluation 要求所评单元/功能与可见状态。v3 可容纳空图及至多 512 个待编码组；旧 v2/v7 仍保持 1–64 个组，新图的实际编码留在后续批次。

LabelCell 的 known mask 从 status 派生，unknown/conflict/not_applicable 的 value 均为 null。LabelSet.get 对未出现的坐标保持 unknown，完整标注标志不会让任意字符串自动成为负标签；生成负例还须明确被标注的成员全集。旧五角色目标会迁成 LabelCell，训练消费者只读取 known 且有正证据权重的格。角色证据权重已移出归一化分母，避免全弱证据批次抵消自身权重；完整的来源组多任务损失仍属于 M5。

条件求解入口：`solve_requirements(tree, resources, coverage=False, budget=SolverBudget(), state_provided=False)`。coverage 默认采用开放观测；明确完整库存可传 True，或者只声明特定原子查询的完整范围。not 仅接受一个不占用资源的 reusable 谓词子树，读取提供的观测，不因同表达式中的临时分配而宣称对象不存在。资源标记 reusable 也不能免除 consume 的支付。

Resource 可声明 resource_id/pool_id、整数 capacity、deck_section、state_zone、跨阶段 available_until、选择器别名和事实来源。共享 pool 的多个描述共享物理槽位。每个解独立返回 matched_resources、consumed、occupied、retained、residual_conditions；未选分支不合并资源。搜索上限默认为深度 16、4096 状态、128 解；超限可返回已证明的见证，但不得把未遍历范围判为不成立。失败搜索的局部资源冲突保留在 rejected_allocations/conflicts，不能作为成功分支的冲突。

FunctionalContract 保留原接口，新增结构 requirements 与 state_requirements。Dependency 可附 BranchConditions 及与 alternatives 一一对应的 alternative_conditions，确保成员和其资源/状态条件属于同一路径。KnownCondition 新增 scope，旧未注明 scope 的记录按 state 迁入；结构限制须显式声明 structure。没有可见状态时 readiness 保持 unknown，不因此撤销结构完整性。

`minimum_member_branches` 返回带稳定 branch_id 的成员和条件分支。`assess_unit` 返回所有分支，chosen_branch 默认 null；存在多个可行包时不输出合并的 minimum_members。`prepare_function_candidate` 对唯一可行包可继续，对多个可行包返回 branch_selection_required；搜索未完成返回 branch_search_incomplete。复杂条件使用 branch_factor_provider(members, assessment)；缺失时返回 branch_cost_provider_required，不先算一个丢条件的价格。

## 3. 共享构筑适配范围

新增 construction_recognition.allocate_relation_group，并在 construction_relations._group 的 InputGroup 路径调用。它复用既有 Resource.accepts、已建立的 matches、实际供给数量与资源池，再委托 multifactor.conditions；没有增加第二套选择器或条件分配算法。

当前仅无损委托完全已知、无前置 inputs/claims、无条件残余、无回收和重叠库存池的供给。不能完整转换的输入返回 None，继续保留原 conservative 关系传播和原始条件。完整效果依赖、重叠库存、回收次序及真实构筑服务接线仍属于后续接线范围；没有因为新增适配器就宣称所有构筑资源事实已经统一完成。

共享 construction_relations.py 对 M0 的文本差异仅为四行委托调用。构筑权重、收益定价、通关阈值、CB 和原生引擎均未修改。

## 4. 验证及现有改动保护

本聊天只执行文件复制/读取、Git 状态/文本差异和空白检查；没有启动 Python，没有导入项目模块，没有做语法编译或测试收集，没有加载权重或执行前向、优化器、训练、CB、引擎及构建。

已完成的文本检查：

- M0 复制文件与源文件逐字节比较一致。
- 受影响文件回读；construction_relations 对 M0 的改动仅为上述委托调用。
- Git 空白检查按 CRLF 合法行尾配置进行，避免把原有 Windows 行尾当作整文件新增空白。
- 修改前已有的所有 tracked deletion 状态仍保留；未 reset、clean、恢复删除或创建新工作树。
- training.hold.json 的 formal_training_authorized_now=false、automatic_release=false 仍保持。本聊天没有改动该文件。

测试源码已更新 analysis/conditions/units 的新契约断言，并新增 test_multifactor_batch1.py，覆盖四模式回读、逐格标签、替代递归、跨分支条件绑定、池别名、回溯、at_least_k、占用/保留/distinct、unknown/overflow、Side 隔离、默认候选复查及共享构筑委托。所有测试均未执行；本报告没有通过数。

检查期间发现 MASTER-CHECKLIST.md 被构筑聊天追加了新的首批记录。该并发内容完整保留；本聊天只在其最新内容后追加自己的状态，不沿用构筑聊天的测试授权或测试结果。

## 5. 文件与恢复

核心改动在 multifactor/{contracts,analysis,annotations,training,network,conditions,functional_units,scoring,__init__}.py。共享改动为 construction_relations.py 的委托以及新增 construction_recognition.py。验证源码为三个既有测试文件和新增 test_multifactor_batch1.py。另更新执行书状态、本报告和总清单。

M0 manifest 是本批恢复索引。恢复时逐文件逆向合并本批差异；若文件已有后续或并发修改，不能直接整文件覆盖。尤其不能用 M0 的 MASTER-CHECKLIST 快照覆盖构筑聊天的新记录。回退副本不含数据、权重或运行产物。

旧权重未覆盖，当前包源码指纹已改变，旧 RoleTrainer.load 的严格绑定仍保留。恢复原模型须使用它原本相容的源码与回执，不能删除校验强行加载。首批回退副本保存的是本次实施前工作树，不据此声称它已与全部历史 checkpoint 匹配。

## 6. 未完成与下一步

A01–A05 中本批对应的代码路径已实现，但全部运行验收仍待执行。已知需要以后确认的项目为语法/导入与序列化回读、分配结果、既有模块回归、分支成本接口，以及共享构筑适配的真实输入表现。未通过运行验证之前不将本批登记为能力达标，也不启用 assist 或切换模型。

本批没有外部阻塞或待答问题。后续可按执行书进入 M3；若用户先允许定点验证，则只运行与本批相关、被明确允许的检查。当前测试、推理和训练禁令继续有效，不自动转入下一批。
