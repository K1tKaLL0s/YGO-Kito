# R1/R2空状态联合消费执行书

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

2026-11-11，Asia/Hong_Kong。承接R0—R11原执行书及R1补充；主进程实施，沿已有模型决定，无子代理、无新工作树、无UI。当前已真实复现`StaticEntryTests.test_absence_condition_cannot_follow_uncleared_required_grave_production`失败：`activation_state_conditions`存在，但默认统一评价仍放行强制先送墓再空墓。修复后继续原R3、R5及后续包，不把本专项完成写成全部完成。

目标：同一静态联合用途的状态改变、空状态检查及清空手段必须存在相容安排。空墓/空场是发动前条件，不是牌表禁投条件；自身支付在其后。保留独立可选用途和未指定次序时先用空状态效果。允许修改`construction_layer_flow.py`、必要的`construction_relations.py`、`construction_inventory.py`及现有static_entries/relations测试、当前状态文档；本专项不改评分公式、原任务硬条件、参考、权重、训练配置或既有运行档。规范化版本随消费语义提升，原评价按已有绑定失效，旧结果保留。

技术路线：将已解析发动/操作状态条件和完整支付/实体移动选择器接入`use_details`；在既有`_bind_mandatory_impacts`构建必需联合组之后，用同一组的来源、操作、数量、实体候选和before边生成状态次序约束。生产必须在检查之后，或其实际匹配实体在检查前由合法清除用途移出。清除数量与不同实体复用既有`multifactor.conditions.solve_requirements`整数分配，次序复用`construction_relations.order_possible`；不增加事实库、评分器或外部求解器。生成Token使用其明示规格，不查Main库存；同一效果的条件先于自身成本，公共支付只消费一次。

| 步骤 | 目标、前置与确定动作 | 预期与验证 | 失败停止条件 |
| --- | --- | --- | --- |
| 1 | `construction_layer_flow.normalize_function_uses`的`use_details`；已存在scoped record和InventoryDependencies。复制完整`activation_state_conditions`和操作`state_conditions`，将成本及真实移动的完整选择器/数量/来源去向规范化为状态关系元数据，保留原文、effect/operation身份及生成规格。 | AST检查；现有text_completion和static_entries字段、默认入口回归保持。元数据不能声称当前盘面已存在。 | 无法完整识别的选择器保留局部诊断，不删限定、不按卡名补丁。 |
| 2 | `_bind_mandatory_impacts`及同模块内部状态关系函数；步骤1完成。仅对required/all联合组消费状态条件和必需生产；生成可行次序分支并联合既有边。生产在检查前时，必须用同组实际可用清除用途、匹配选择器和足量不同实体建立生产→清除→检查；一个清除不能重复覆盖多批资源。没有相容分支记录有来源的失败硬条件。 | 原空墓反例转绿；新增未强制顺序、自身支付、真实清空、数量不足、清除选择器不符、空场Token及方向隔离对照。每例经过默认normalize和唯一质量评价。 | 不允许仅凭有墓地相关卡推断非空；不允许只有清除标签就放行，或忽略原before边、改为用户缺盘面。失败只修当前差异。 |
| 3 | `NORMALIZATION_VERSION`提升；状态消费已通过定向验证。执行显式static_entries、text_completion、functional_flow、runtime_processing、relations、inventory模块，按完整测试ID去重并保存本批日志。 | P前缀沿原执行书，`-m unittest`后接明确模块/方法；0失败/错误/跳过。AST/行尾及本批实际差异检查通过；R3/R5仍单列开放。 | 测试意外触发训练/推理/native立即停止该检查；不运行discovery或未经筛选全CI。 |

证据写入`.cache/design-implementation-repair-20261111-state`。失败时只撤销本批确切差异，不reset/restore/clean、不覆盖混杂工作树；用户停止时结束当前非破坏性原子步骤并保存。训练、权重推理、CB/native、完整构筑、GPU/PC、run-007继续暂停。未知候选选择需由既有分配给出见证；预算待算保持可继续状态，不能当成合法或正常失败。当前没有待答问题或新增审批。

实施中补正：只给生产和清除建立配对边不足以保持多次移动的实体身份，也不能正确表达一批两张由两次各一张清除。确定改为扩展现有共享整数分配器`multifactor/conditions.py`，保持其默认合同和既有分配路径。`Resource.initial_zones`表示静态可能起点（不是当前盘面）；`Condition.state_origins/state_destination/state_absent`只在显式启用的联合状态处理中使用。共享分支随每次实际选择保存同一物理槽的可能区域，移动后区域唯一；空状态从匹配槽的可能区域中排除该区，不能从未知直接断言非空；Token以未生成区域开始。静态用途的已有before图枚举相容拓扑安排，生成条件、支付、处理、规则离场事件序列交同一分配器；不另写实体分配器。旧的“生产批次一次消费”临时实现由本次扩展替换，不保留双轨。

新增步骤的目标文件为上述共享分配器、layer_flow和现有static_entries测试；先实现可选字段的严格校验、序列化、分支区域更新，默认字段不改变原行为，再将`_joint_state_order`统一接入。通过标准增加：两张由两次各清除一张；单一实体合法返回后再移动；仅有一次清除不能清掉两批；普通魔法处理后的规则送墓、条件在自身支付前、可选处理在先前处理后、方向库存隔离。运行原multifactor条件静态测试和上述六模块；不调用其网络/训练。失败仅停该扩展相关动作，保留原文诊断和既有已通过结果。

同一状态消费者还须读取已识别`grave_destination_replace`：在对应效果处理节点启用未来去向替代，不改既有墓地库存；普通魔法规则离场同样受其影响。允许在上述Condition/_State增加显式去向替代字段，复用当前分支状态，步骤验收补充“替代前的墓地卡仍在、替代后的规则送墓改除外、替代前后顺序不可交换”。严格送墓成本及原功能冲突仍由已有restriction合同验收，不放宽。
