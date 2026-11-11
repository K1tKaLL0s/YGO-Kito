# 轴与泛用识别 M6 实施记录

日期：2026-11-09，香港时间。状态：M6 源码已实施，全部运行验证待授权。用户明确要求先交付机械执行补充后直接修改；本批由主进程执行，没有子代理。后续交接指定 gpt-6.1-sol、推理强度 MAX。

## 范围与修改前保存

实际仓库为 `N:\YGO-Kito\_publish_20261030`，复用 `codex/optimization-20261031` 的既有未提交检出。没有 checkout/reset/clean/stash、新建 worktree、恢复删除、提交、推送或发布。主计划为 `docs/plans/2026-11-08-axis-generic-execution-plan.md`；修改前已交付同目录 `2026-11-09-axis-generic-m6-execution-supplement.md`。

`.cache/axis-generic-m6-20261109-01/manifest.json` 登记 21 条相关路径，18 个既有小型文件已复制并逐字节比较，2 个新测试文件及本报告原不存在；同时记录 20 个既有 tracked deletion。没有复制权重、大数据或重建 M0–M5 保存包。并行构筑在本轮推进至第九批，相关未提交修改继续保留；当前规范化版本为 v8，证据回调签名与本批接线兼容。

本批改动为 multifactor 的 `contracts.py`、`analysis.py`、`scoring.py`、`__init__.py`、`__main__.py`，构筑的 `construction_recognition.py`、`construction_fill.py`，两个新增测试文件及主计划/MASTER/本报告/机械补充。共享分配接口 `allocate_relation_group` 保留；构筑关系传播、功能规范化、计价、学习、调度、数据库和默认生产政策没有由本批改写。

## 三个分析服务

`RoleAnalyzer` 通过构造函数接收可选事实提供者、scorer、逐项能力状态和 `AnalysisBudget`。`AnalysisFacts` 只提供卡片行、效果快照、结构关系、功能种子、单元契约和实际库存资源；它不接受训练记录。底层 `functional_units.assess_unit` 在服务中明确别名为 `assess_function_contract`。

`AnalysisRequestContext` 保存规则/时期/格式、明确目标、off/observe/assist、可见状态、公共资源覆盖和可选抽样声明。监督/标签/来源划分区块不能作为请求上下文。它是服务 DTO，未扩充 M5 学习输入、受控特征或任务词表。

`analyze_deck` 用共用 `build_analysis_graph` 构图并完成自然候选枚举，返回 `DeckAnalysis`。`assess_unit` 返回 `UnitAssessment`，分别保留完整定义和接收牌表实例的功能契约检查；Side 不会直接充当 Main/Extra 的在用伴随件，未提供区域不能证明缺件。缺失区域与已知空区分别输出 unknown 和 not_applicable，浓度按实际所在分区总数计算。候选支持成员不是已识别的成员归属，主/次/辅助位置、来源及大型/小型旧摘要没有无依据映射。

`compare_copy_change` 返回 `CopyComparison`。add/remove 各自携带卡号、区域和数量；remove=null 是增加总数，add=null 是实际减量，两者都有时根据真实数量区分替换与混合变化。移除不足或修改未知区域在读取 provider 前拒绝。操作后对前后完整配置重新读取事实、构图与求解，结果携带相关功能、调用/依赖、资源评估和分母变化，不套用卡数加减分。

库存事实可以随实际候选重新供应；构筑默认事实适配把物理数量绑定到分区库存资源。共享池的整数需求仍由唯一条件求解器处理。无替代对象时整体偏好 unknown；有真实 add/remove、单项明确功能和已发布校准能力时才可使用跨配置偏好。多功能各自返回结果，没有宿主聚合规则时整体偏好 unknown。现有 M5 训练比较准入未改写；未来资料和校准仍需覆盖实际运行输入。

只有声明 `uniform_initial_single_sample_without_prior_movement`、区域和抽取张数时，服务才复用 `construction_relations.single_event_probabilities`。结果明确是本卡单次接触率；联合功能成功率保留 unknown，不相乘独立接触概率，不新增模拟器。

`ExternalLegality` 需要 producer/version/证据和确切牌表、目标、规则及上下文。缺外部结果或作用域不匹配时 legality=unknown；服务不会执行验证器。

## 能力和评分

`CapabilityStatus` 区分 unavailable、untrained、engineering_only、trained_uncalibrated、available、deterministic_only、disabled 和失败。可供 assist 的学习能力要求宿主显式提供校准、验证、producer/version 和证据；确定性事实也要有明确验证依据。本批没有发布任何能力。默认学习头不可应用，state_readiness 仍为确定性契约检查，environment_value 关闭。

`CandidateScorer.score_graph` 只消费显式注入的 v3 trainer。按整头查询预算检查后，以32个查询为块遍历完整事实域；超过预算整头拒答，32不是总候选上限。工程/未训练头拒绝输出识别结论，已训练未校准头只产生 raw。校准器由宿主注入，不能把默认阈值或 argmax 宣传为拟合结果。服务检查输出查询域、有限概率、分层查询对应和词表；一头失败保留其他头和事实。候选枚举超预算时，依赖该候选域的头不应用。

`score_copy_graphs` 在显式比较操作下使用 M5 的跨图偏好读出；保持目标、函数、时期/规则、可见状态和固定公共资源一致，只有经实际牌表数量核对的库存资源可以随操作变化。原始、校准和应用层分别返回。没有拟合校准、缺查询或缺完整配置时 unknown。

旧候选评分接口保留；解释文字不再暗示 core/support 需要 plan_known 硬门槛，两者可以并存。新服务的旧摘要只使用有依据的已应用能力；large/small 不按新卡数阈值重定义。

包导出三个服务及相关 DTO。CLI 新增 `--service analyze_deck|assess_unit|compare_copy_change`，接受 `axis-service-request-v3` 的事实请求，按分支延迟导入，不创建或加载模型。神经评分由宿主显式注入；旧 CLI 评分现在要求显式 checkpoint，避免无权重时自动构造随机模型。CLI 源码已提供，本批没有运行它。

## 实际构筑消费者

`ConstructionRecognitionProvider` 可把当前卡库/库存接到分析服务，或使用宿主注入的 analyzer 与上下文。provider 只收到任务副本，返回结果须绑定原目标、任务、模式和确切分区库存。

`build_axis_skeleton`、`fill_with_existing` 和 `construction_cycle` 都接收可选 `recognition_provider`、`recognition_mode`，默认 off。原流程保留在内部实现，公开包装入口负责安全时点和结果记录。候选完整生成后才分析；重复牌表只观察一次。

off 不触及识别 provider 或加载模型。observe 在整次构筑切片的排序、筛选、分值、学习输入、停止原因、gate 和 CB 授权全部确定后追加记录，避免观察耗时占用优化器/CB 的墙钟预算。它不把识别记录放进 session 反馈或 learning_candidates。

assist 通过 `assist_fact_view` 只交付确实有数据、明确可用的能力事实和覆盖信息。决策接线使用既有 functional quality 的宿主证据接口：宿主提供带版本的 `layer_policy(task, deck, layers, facts)`，输出仍由现有规范化器的语义绑定、冲突和逐候选检查处理。识别不提供 losses、slot_uses 或私有分值，不覆盖现有证据。回调或证据验证失败时仅返回原宿主证据，记录局部 unknown。待续评价绑定能力事实和宿主映射版本，绑定变化时不复用旧缓存结果。

当前没有默认层政策自动采用新头；旧 layer/质量协议缺相容映射时继续原路径。宿主显式提供的语义证据可影响现有 evaluator 的结果，分值与 gate 仍由原政策决定。默认 QUALITY_VERSION 与生产政策没有切换。

`_candidate_basic_cb` 仅向显式声明 `accepts_recognition_hints=True` 的宿主 provider 传递 assist 提示，内容限定为候选、资源、分支、时序和缺件，并标明 legality/route_success=unknown。原 CB 执行授权、gate、路线验证和成功结果处理不变；没有触发 CB 或原生引擎。统筹继续读取既有阶段结果，未改其网络/调度/数据库。

## 验证与未决项

新增 `tests/test_multifactor_service.py` 的25个方法和 `tests/test_construction_recognition.py` 的12个方法，共37个测试方法源码，覆盖 V23–V27/A09/A10 的行为边界，以及逐头失效、查询块/预算、跨配置偏好、CLI、宿主证据、延后观察、提示接收与缓存失效。执行数0，未进行测试收集。用例内的模拟评分和人工事实是明确的工程夹具，未用作模型能力证明。

仅执行文件/文本/JSON读取、必要文件保护比较和 Git 差异检查。静态回执为 `.cache/axis-generic-m6-20261109-01/static-review.json`：21 条登记路径中，12 条属于本批声明变更；范围外9条的7条内容一致，`construction_layer_flow.py`、`construction_relations.py` 的2条变化来自并行构筑第八/九批，均未覆盖。原20个 tracked deletion 未恢复，原 `allocate_relation_group` 函数体文本保持一致，声明文件行尾空格/制表符为0。

原有 CRLF 风格保留。默认 Git 空白规则把这些行的 CR 报为行尾空白，返回2；命令级使用 `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check -- <本批路径>` 返回0，没有修改 Git 配置。此回执只证明文本与文件保护检查；没有执行 Python、项目/Torch 导入、AST/编译、构建、测试、数据准备、前向/模型推理、训练、CB、原生引擎或 CI，没有加载 checkpoint。

尚待验证：语法与实际导入、37个新方法及相关集成的运行结果、真实牌表和卡效覆盖、实际校准器及能力发布、神经查询数值/设备行为、恢复和宿主政策兼容。A09/A10、V23–V27 未登记为通过。M7 和 T1–T4 尚未开始，旧 core/support 资料覆盖缺口及 M5 缓存身份变更继续保留。

## 独立续接摘要

原始目标是按主执行书分批迁移轴与泛用识别，并保留全部既有未提交状态。实际工作区 `N:\YGO-Kito\_publish_20261030`，复用分支 `codex/optimization-20261031`，交接定位 HEAD 为 `3f57198e5e366152bbb672be8910e6800f8adbb4`，不得据此覆盖工作区。仓库有大量 dirty/untracked/deleted 及并行构筑改动；没有提交、推送、合并或发布。

M0 保存完成，M1–M6 源码已实施，所有识别运行验证待授权。M6 的真实修改范围、接口与行为见本报告和机械补充；修改前清单 `.cache/axis-generic-m6-20261109-01/manifest.json`，静态回执在同目录。构筑已并行推进到第九批（当前规范化 v8），相关共享源码和文档继续读取最新后增量修改；不能拿本报告替代当前源码核对。静态核对为7个范围外文件一致、2个并行构筑更新保留、20个既有删除未恢复、共用分配函数体不变、CRLF规则的 diff --check 返回0；不是识别用例运行成绩。

现有旧配置、标签、数据、权重、活动指针、训练暂停、课程恢复和 LoRA 不变。M5 特征缓存身份变化未重建，旧 core/support 资料尚未进入图的弱标签保持 unknown。新增服务没有发布/校准能力，所有生产应用需真实 capability 与宿主政策依据；不能将随机输出、更新计数或并行构筑成绩当识别成绩。

下一阶段由用户明确指定范围后再进行：M7 的运行验证仍需对应授权；T1–T4 的资料准备、训练、消融校准与能力发布分别需要授权，不能因完成 M6 自动启动。当前禁令仍覆盖所有测试（含收集/静态业务用例）、Python/项目/Torch导入、AST/编译、构建、前向/推理、训练、实际数据准备、CB、原生引擎和CI。不得切换权重或暂停状态，不重建 M0–M6 基线，不恢复既有删除，不重复旧检查，不自行创建新聊天。本批没有待答问题或外部阻塞。

后续任务使用 gpt-6.1-sol、推理强度 MAX，由主进程执行，不启用子代理，除非用户另行明确修改。遵守提问等待规则：一旦提问，暂停所有依赖回答的检索、规划、实施和交付，真实回答前不得默认推进。长任务优先在当前聊天继续并允许压缩；当继续压缩可能损害约束/状态/证据保真，或达到安全交接边界时，先完成当前非破坏性原子步骤，再主动建议新聊天并提供完整独立摘要；未经用户明确确认不得创建，后续首条提示重申本规则。

建议新任务首条提示：

> 请使用 gpt-6.1-sol、推理强度 MAX，在 N:\YGO-Kito\_publish_20261030 承接轴/泛用识别。先读 AGENTS.md、代码执行细则、主执行书及 docs/reports/2026-11-09-axis-generic-m6.md。M0保存、M1–M6源码实施完成，识别模块全部运行验证待授权；保留所有 dirty/untracked/deleted 和并行构筑第九批及其后改动，不启用子代理，不 reset/clean/stash/checkout，不按 HEAD 重建，不提交发布。先依据本次用户明确指定的阶段与授权继续，未解除的测试/导入/编译/推理/训练/数据准备/CB/引擎禁令继续有效；权重、活动指针和暂停保持。任何代码修改先交付机械执行补充，非 UI 已授权工作可直接继续。遵守提问等待规则和上下文交接规则：优先在当前聊天继续；再次压缩可能影响准确性、状态连续性或验证证据，或形成安全边界时，完成原子步骤后主动建议新聊天并给完整摘要，未经明确确认不得创建，下一首条提示继续重申本规则。
