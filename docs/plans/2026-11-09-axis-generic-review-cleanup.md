# 轴与泛用模块设计核查、质量修复与旧入口清理执行书

2026-11-09，香港时间。主进程执行，不使用子代理；无待答问题。用户本轮明确授权全面检查、必要修复及删除确认不再调用的旧入口/代码/规则。继续保留真实资料准备、正式训练、CB、原生引擎、CI、活动权重/指针、提交推送的运行限制。

## 目标与完成标准

对照主设计 A01–A10、T1–T5 检查实际源码与消费者，不仅复述前批测试。完成标准：设计项有实现与证据映射；发现的确定性缺陷修复并有对应反例；当前准备/训练/评估路径不再依赖旧运行器；删除的代码有调用搜索依据和明确替代入口；允许的工程检查通过，真实阶段仍准确登记。

当前证据：prepare_only 经 prepare_base 引入旧聚合特征/准备栈；prepare_v3 仅需 prepare_base.targets 的旧标签审核函数，却因此牵入整套旧实现。train_base、prepare_balanced、finish_existing、check_scopes 和 historical 下五个生成/改写脚本没有当前生产消费者。features_graph 的 v3 薄适配和训练查询辅助仍被专属测试使用，不能直接整文件删除。src 的 legacy DTO、网络和适配器仍有明确兼容接口/测试与 CI 引用，不以“旧”字样直接删除。

质量核对已定位：基础训练在早停决定写入 checkpoint 前保存，可在中断恢复时多训；固定临时 JSON 文件名会被残留阻塞；副本偏好存在单图查询与实际双配置比较两条特征路径；CLI 预测直接按 resume 加载会改变 RNG 并要求训练运行环境；校准/评估只检查来源头部与裸预测映射，尚需核对逐格来源和工件绑定；环境运行器没有先验证整份反馈的图/来源再开始首批更新。下面按实际依赖修复，不将前批“完成”结论当作本次核查结果。

## 路线、文件与逐项验收

| 步骤 | 目标与前置 | 明确动作、不变量 | 验收与通过标准 | 失败处理 |
|---|---|---|---|---|
| R1 当前入口和废弃代码 | training/axis_generic 的旧文件、prepare_only/prepare_v3/features_graph、scripts/check_multifactor_roles.py；先完成源码调用搜索 | 将仍需的旧标签审核抽到 legacy_import.py；准备入口直连 prepare_v3；features_graph 只留 v3 观察适配/查询辅助，移除旧聚合与身份规则。删除 train_base.py、prepare_base.py、prepare_balanced.py、finish_existing.py、features_v4.py、check_scopes.py、五个 historical/*.py、只供旧运行器的 config*.json 和旧 ASSESSMENT_PROTOCOL.json。保留原始 JSON 资料、所有 runs/权重、现行 v3 配置和公共兼容库 | rg 明确搜索 src/scripts/tests 和当前 training 源码（排除 runs、缓存）；测试旧模块不再可导入，prepare_only 不加载旧模块；原 v3 适配与人工 SQLite 迁移检查通过 | 发现真实消费者则先迁移调用和验收，不删除；不恢复用户已删除文件，不清理 runs 或资料 |
| R2 训练控制与恢复 | train_v3、graph_training、training.RoleTrainer；R1 的导入可用 | 统一有效批量更新实现，零证据头不受 AdamW 衰减；早停/完成状态随边界 checkpoint 一起保存；可变元数据原子替换；保存/恢复最优引用与分区身份；正式训练前检查选择任务覆盖。增加只读 inference 加载模式，既不恢复优化器/RNG，也不允许更新 | 人工微批/整批对照、零证据头不变；在 epoch 保存后的确定中断点恢复不多训，best 指针一致；损坏/旧实验拒绝；推理加载不改变宿主 RNG | 非有限数值或绑定不符停止当前操作；不覆盖历史权重，修复本轮增量 |
| R3 校准、评估与发布质量 | calibration.py、workflow_v3.py、assessment.py、task_queries.py、metrics.py；R2 推理可用 | 逐格来源与协议核对；预测工件绑定模型/数据/记录，实际入口拒绝误接；训练/选模/校准/最终组隔离。检查多标签固定坐标宏平均、拒答分母、候选漏召回；提供匹配报告的显式宿主接线 | 新反例覆盖伪装来源、错模型/记录预测、缺标签坐标、少数坐标劣化、JSON 文件 CLI 往返与分片身份；无法满足覆盖的头拒绝发布 | 只停失败能力；不得用随机工程更新发布真实能力 |
| R4 副本偏好链 | graph_network.score_preference、graph_training、train_v3.predict_saved、prepare_v3、scoring.score_copy_graphs、task_queries；先核对实际数据结构 | 让训练、开发/最终评估与服务使用同一双配置比较表示；比较必须有实际操作、同目标/功能/规则和独立来源。单图的旧伪比较不得继续当作真实副本偏好训练入口 | 实际两配置人工样本贯通准备→微型更新→预测→校准；非法/缺操作/跨分区比较在更新前拒绝；服务和评估原始概率一致 | 不伪造另一个牌表或比较标签；真实数据不齐仅限制该真实阶段，源码用夹具验收 |
| R5 环境完整入口 | environment.py、environment_v3、analysis；前述底座加载可用 | 整份反馈先验证，坏尾行不得让前行先更新；恢复绑定/游标检查完整。校准/评估工件、真实底座依据和环境 provider 保持一致，三种独立支路不污染基础模型；整理重复/未用代码 | 三模式保存恢复、坏尾行零更新、源组/底座/校准不符拒绝、零置信游标推进；off/observe/assist 与基础输出不变 | 发现基础状态变化立即停止该环境路径；不启用实际环境能力 |
| R6 全模块复核与交付 | contracts/conditions/functional_units/axis_candidates/semantics/splits/analysis、consumer、配置/文档；R1–R5 完成 | 将 A/T 每项映射到符号和有效测试，复用未变证据，补真实发现的边界反例；删除清单、当前唯一入口和剩余真实阶段同步文档 | 对本次修改运行明确选取的 unittest，拒绝 skip/禁止调用；AST/JSON/链接/差异检查；旧名称只剩历史说明/资料引用，活动路径不导入 | 未闭合缺陷如实保留为未完成，不以原测试数量或旧报告替代修复 |

## 执行约定

R1 补充：将建议训练配置合并到唯一当前 config.train.v3.json，删除重复的 config.train.software.v3.json；保留 config.v3.json、config.environment.v3.json。goal_semantics.py 仅仍需的旧资料置信/指名核对函数并入 legacy_import.py，删除其余旧文本计划规则与原文件。模块 __main__ 只保留必选 --service 的事实入口，移除旧 v2 神经评分参数/分派；新版神经预测使用 workflow_v3 predict。旧 scripts/check_multifactor_roles.py 无当前调用者，删除并在当前使用说明给出明确 v3 检查命令。公共 legacy 库仍留兼容测试，不作为训练入口。

R4 数据边界补充：v3 四块记录可带顶层 comparison，字段固定为 right（右配置观察块）、left_key、right_key、operation。observations 为左配置，copy_preference 标签的 subject 必须匹配这两个引用；operation 使用与服务相同的 add/remove/可选 kind，不接受旧说明字符串。prepare_v3 对右配置重新构图，input_key 同时绑定两配置和实际操作；splits 将两配置的牌表/卡引用都纳入来源隔离。network.encode_batch 追加右配置图并记录成对索引；RoleNetwork.score_queries 的副本头统一委托 graph_network.score_preference；单图旧比较直接拒绝。对照包括两端同为 query:unit、实际改动不符、右侧保留卡隔离及服务/批量预测概率一致。

R3 宿主绑定补充：发布决定函数移至运行时 calibration.py，workflow_v3 仅复用，不让宿主反向依赖 training 目录。候选记录绑定实际评估和基线报告摘要；基线必须是不同模型、同记录和同指标版本。host_capabilities 接收实际 assessment_report/baseline_report 并重算发布决定，拒绝错文件或手改 eligible。预测 CLI 输出带 version/model_id/dataset_id/records_id 的完整工件；真实校准/评估不再接受丢失这些绑定的裸映射，工程算例仍可使用小型裸映射。

R7 目标条件反事实（最后设计对照发现）：graph_network.encode_graph_batch 原来仅编码模式、分区数量和局面/资源存在标志，RoleInput.context 中实际提供的目标因子未被读取。目标文件 network/graph_network/task_queries/graph_training/environment 和专属测试。确定方案：显式白名单为 CONTEXT_FACTORS 中非 plan_ 的可观测上下文因子，按原四通道契约编码为独立 intent；不解析不透明目标文本、不恢复旧计划词规则。条件化头在查询/双配置 readout 中消费 intent，mechanism/成员/轴功能/来源/固有迁移性及旧规模头不消费，axis_position 按其主/辅/支持语义改用条件路径。单/双流都保留该边界，路线开关不混入目标标签。环境副本可消费同一目标表示，其 LoRA 仅改独立副本。更新编码指纹，旧语义权重不隐式恢复。验收：只改显式目标因子时，条件头 logits 可变化，结构头及机制 logits 逐值不变；只改 plan_known/plan_reference_coverage、不透明 context_ref、标签或来源时不改变 intent；实际服务 context_provider 提供的目标因子传到评分器。验证失败停止对应能力修复，不做正式训练。

R7 去重/一致性补充：prepare_v3.input_key 同时绑定这些实际编码的 intent 四通道，避免同一物理图在不同目标下被合并为标签冲突；旧 plan_ 字段和来源名仍不影响键。graph_training._intrinsic 排除目标/接收预算因子及当前公共库存，仅保留单元定义和格式/时期/规则边界，允许有明确证据的同单元跨目标迁移性一致性。反例要求不同目标保留两条监督、同组不跨分区，且显式 intrinsic 配对不被错误拒绝。

解释器 E:\Ana\envs\pcacgate\python.exe，实际 workdir N:\YGO-Kito\_publish_20261030。-B、PYTHONDONTWRITEBYTECODE=1、OMP/MKL 各 2，TEMP/TMP/TORCH_HOME、日志和人工工件使用 .cache/axis-generic-review-20261109-01。不 discovery、不运行整仓 CI、不访问真实 catalog/deck_cache、不启动搜索或原生。对新变化使用 tests.test_multifactor_review_v3 及直接受影响的候选、数据、学习、工作流、环境和消费者方法。

改动前将明确待删的未跟踪源码/配置与受改源码的小型副本记录到本任务缓存，供本轮纠错；该缓存不在训练入口目录，也不是新运行入口。不复制任何模型/资料，不全仓哈希。删除采用明确相对路径清单，先验证最终绝对路径在本仓库目标目录内，逐文件删除，不沿目录联接递归。旧模型恢复继续使用对应相容源码；不关闭已有来源/版本检查。

如果进一步源码核对发现本表未列出的具体实现缺陷，先在此补充目标符号、动作和反例，再修改；不扩成无关项目重构。
