# 构筑前效果语义与机制接口

本增量使用有边界的中文卡文句式识别，不按卡 ID、主题名或八张卡的答案表分支。
这是程序识别与候选提议，不能称为已训练模型的卡效理解或陌生主题泛化。

## 数据与未知

`effect_mechanisms.analyze_card(row, cards_sha256)` 保留来源摘要和编号效果。
每个 `EffectSemantics` 包含：

- 触发事件、效果送墓原因、原始条件句及额外条件是否识别；
- 发动前费用和处理中的操作，分别记录 `reason=cost/effect`；
- 明确取对象的选择句、数量与区域；处理时选择与取对象不混同；
- 同名各效果次数与同名多个效果共享次数；
- 区域移动、素材回卡组底部、融合召唤、素材包含墓地自身等关系；
- 单卡固有限制、玩家当回合限制、额外融合限制和离场除外的适用范围；
- 各维度的 `knowledge` 与未识别部分。空列表不等于已证明没有费用/限制。

只有识别到的正面能力用于功能标签与召回。未知句式、未识别的额外条件、
非两素材公式、接触融合和一般脚本控制流均不猜测。
卡名包含/公开种族的素材匹配只提议候选，不能代替核心的融合素材检查。

`MechanismCatalog.summarize(core_ids)` 汇总墓地效果触发、融合机制、资源流和限制。
`summon_lock_assessment.reviewed_effects` 明列已识别效果；其他效果仍列为未知。
`global_no_summon_restriction` 恒为 `None`，不能把若干效果没有玩家召唤锁扩写成
整副牌无自肃。持有熔岩魔神与实际召出它的当回合限制也分开表达。

## 实际调用

次数记录使用 `count_limits` 数组，允许同一效果带有多个不同主体的限制。
每条记录分开保存次数主体、效果索引、`count_event`、每回合重置与适用条件/期限，
以及发动无效、效果无效、处理未适用三种结果的计数语义。
`effect_count_limits.negation_counting` 只查询已匹配主体的观察，不维护/替代引擎计数器。

已接入父端核实的[使用次数规则（17200）](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=17200&request_locale=ja)、
[Trap Trick 限定的陷阱卡发动次数（22010）](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=22010&request_locale=ja)，
及[全局怪兽效果发动限制（7813）](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=7813&request_locale=ja)。
完整明确句式与适用范围必须匹配，不能由“发动”一词推导无效后退款。
标准同名卡一回合只能发动一张的无效细则仍未知；
[23158 的特定种族排除/跨回合限制](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=23158&request_locale=ja)
没有匹配句式时保留未知，交真实核心判断，不扩写为一般发动规则。

`CourseModels` 使用的同一个 `AutonomousConstructionKernel` 在 `_pool` 与
`_route_goals` 中先消费机制信息。补池只保留：已声明主题事实、可识别支持功能、
公开素材属性或已识别泛用功能，不再用可用卡 ID 顺序填容量。
容量不足返回缺口/未知；用户明确固定的卡继续保留，不擅自换目标。
预算导致缩池时先移除支持分数较低的非固定候选。

当前新增的融合提议识别“召唤成功→效果定向从卡组送墓→墓地融合→两素材回卡组”
结构，从实际卡文和素材公式取得起手、融合效果与目标。没有这种证据则不猜融合路线。
已有明确宿主目标继续保留，并通过 `goal_proposal_origin=host_explicit_route` 标明；
不能把宿主指定的教学答案称作模型自主推导。

阶段1图继续使用无卡 ID 轻量标签；推导的机制标签是程序图提议，与用户明确要求分列。
狭义主题仍按字段/种族选主轴，广义仍跳过该步。四次目标/优化交替及之后的基础 CB
由现有构筑流程负责，本增量未新增最终 CB、全图或全卡效完备门槛。

`BuildEncoder.batch` 与课程任务选择的 `_task_batch` 均提供真实 `mechanisms` 张量，
同一组 `BuildRanker` 的小型线性投影消费该张量。特征包含效果送墓、墓地融合、
资源回流、费用、对象、次数、玩家通常召唤限制、额外融合限制、素材限制和未知标记。
次数特征还分开输入上限、使用/发动主体、发动无效计入/不计入/未知，不能只编码“有次数限制”。
图评分入口没有卡片语义张量时继续走已有图编码；未另造构筑模型。

`construction_effect_blocks.reviewed_effect_blocks()` 默认从识别结果生成有来源的粗标签。
`REVIEWS=()` 仅保留旧脚本导入兼容；显式外部评审表仍可提供，但与自动识别来源分开。
绑定器保留具体效果语义供后续选卡/解释使用；这不认证图连接已执行。

## 版本与旧权重

- 构筑编码：`build-task-catalog-candidate-v6-effect-mechanisms`。
- 自主构筑状态：`autonomous-catalog-task-course-v2-effect-mechanisms`。
- 卡文识别：`public-effect-clauses-v2`。

课程词表和自主构筑绑定也明确记录卡文识别版本，旧语义缓存不能借相同张量维度静默恢复。

旧 checkpoint 直接恢复仍拒绝，不改写旧版本字段来冒充兼容。
`build_model.migrate_legacy_ranker` 提供显式 v5 模型/Adam 扩展接口，要求旧特征版本和
源 checkpoint SHA-256，复制旧参数/矩，将追加的机制投影置零，新增 Adam 参数等待
正常首次更新时建立状态。原输入不变；返回单独迁移说明。

该接口不迁移整组 checkpoint 的源码、词表、课程、数据索引和 LoRA 绑定。
整合宿主须另行记录实际绑定迁移、保留旧工件，并重建/清空旧候选缓存。
已有 LoRA 参数化模型不由这个基础权重接口猜测迁移。置零投影保证旧预测在迁移点
不因随机新权重变化；后续学习仍需真实训练信号，不能称为已学会机制。

## 隔离验证边界

2026-10-28独立复核的定点修正保留了原机制编码和语义召回：

- 发动句分隔支持“才能发动（…）。”，发动前从卡组送墓归于费用；括号说明保留为未知条件。
  分隔边界未识别时，候选操作的原因保持未知，不进入正向操作/效果标签。
- “融合召唤的这张卡”这类状态/修饰句不再当作融合召唤执行指令。
- 墓地融合要求已识别的发动条件；起手关系只读取同一效果的送墓处理。
  无祭品手卡起手仅针对普通1～4星主卡怪兽，不假定高星、额外或特殊召唤怪兽的入场路径。
  起手所依赖的额外条件、费用/对象和未识别处理未解决时，不输出该确定起手提议。
  这没有新增全卡效或整图完备要求；已识别能力与未决部分仍分别保留。

`MechanismCatalog.construction_mechanism_groups(pool, core_ids)` 复用同一组关系提议，导出
现有构筑窗接口的三字段包：`group_id / zones / source`。
`kernel.construction_mechanism_groups(selection)` 可在构筑开始前调用；只读已封存的任务/主题。
消费者可直接传给其已有 `portfolio(..., mechanism_groups=groups)`，或由宿主显式安装到
`assets.construction_mechanism_groups`。本模块不复制组编辑算法、不修改消费者源文件，
关系包仍是提议，不带合法CB或强度通过标记。

仅运行 `tests.test_effect_mechanisms`、`tests.test_construction_binding`、
`tests.test_construction_model` 等明确选定的 CPU 回归；不启动课程训练或原生引擎。
新增用例用匿名主题和变化后的卡号检查效果句式迁移、费用/处理送墓、资源流、
限制范围、未知处理，以及机制变化确实改变目标和候选池。

`CourseModels → ScenarioCourse._construct → kernel → 四段构筑` 用例使用真实模型和
绑定器，仅关闭原生核验边界；未核验 CB 仍被 learner 拒绝，未发生参数更新。
Windows 上仅为导入 POSIX 课程模块提供测试内 `fcntl` 哨兵；任何文件锁调用都会失败。
因此这项用例证明推理接线，不验证 POSIX 锁、核心规则、完整课程恢复或竞技能力。

本分支最终执行 `tests.test_effect_mechanisms tests.test_construction_binding
tests.test_autonomous_construction -v`：36项通过（Windows CPU，2026-10-28）。
另外选定的 `tests.test_construction_model` 为8项通过、1项失败；失败项
`test_concrete_binding_covers_requested_tags_across_active_branches` 已在原始
`fefd44cf7d894a670e2c70d94d30d26d225cb264` 源码隔离副本复现同一断言失败。
其无显式required_tags的图候选没有包含测试要求的全部标签，由图候选专窗整合，
本分支未修改construction_model/build_pipeline/组编辑/反馈文件。

WSL只读查询 `wsl --list --quiet` 返回 `Wsl/E_ACCESSDENIED`，未重试或改道执行Linux任务。
Windows测试内的导入哨兵不执行文件锁；Linux课程生命周期未在本分支重验。
当前真实卡库只读识别能提出雷诺起手、水仙目标以及三种人鱼的条件融合候选，
并分别保留熔岩魔神的单卡固有限制/当回合玩家限制和卡雷多哈特素材限制。
这些是语义提议检查，不是新增真实核心CB、正式课程或模型能力成绩。

本轮保存完整命令和逐项输出，执行
`python -X utf8 -m unittest tests.test_effect_semantic_review tests.test_effect_mechanisms tests.test_construction_binding tests.test_autonomous_construction -v`：
45项通过。额外直接加载原始fefd44c的v5模型类再次执行非空Adam迁移专项：1项通过；
27组旧动量非零，旧参数Adam步数从2续至3，新投影首次建立第1步状态。
扩展、序列化恢复和继续更新后的参数/动量逐张量一致，未手填模拟动量。
构筑窗041c72b的原版`portfolio`也实际消费了该关系包，保持强度未知。
原始日志和代码摘要位于本任务交付的`effect-review-round2`目录，不作为正式训练数据发布。
