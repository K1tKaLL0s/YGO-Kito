# W1／W4 完整条件与选择消费执行书

> 执行与历史记录。现行行为以 [现行设计](../../current/README.md) 为准；本文的日期状态和当时授权不自动适用于新任务。

最终运行指令已由用户改为结束本轮试运营：run-007已停止，12份候选Evaluation与原始存档、日志保留，参考评价与S5未完成，不自动恢复，不展开后续优化。以下实施与持续跟进步骤保留为历史；当前终态以[停止记录](../2026-11-10-construction-condition-selection.md#按用户最新要求结束本轮)为准。

2026-11-10，Asia/Hong_Kong。实际源码为 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`、HEAD `3f57198`。主进程执行，不启用子代理，不提交推送。已回读来源聊天实际用户消息、本轮交接报告、code-work 及 preserve-intent-and-execute／anti-overengineering。

## 目标、证据与边界

继续 W1-1／W1-2／W4-1 的通用语法消费，再以原 2207 环境和 course-006 权重评价已保存的 12 份候选及指定参考，完成真实 S3—S5。静态构筑评价印刷能力、投入和配套，不要求当前对局状态；未知修饰语继续给出具体原文原因，质量 v4、准入 v3、原公式与 80% 参考门槛不变。

证据来自 `.cache/construction-runtime-processing-20261110/run-001/resident-coverage-inspection.json`：完整己方存在条件与发动时点的组合仍 unknown；“怪兽或者有那个卡名记述的魔法·陷阱”等完整选择丢失或未解析。`effect_records._refine_record` 只对整个条件作固定匹配；`construction_inventory.selector/requirement` 只消费单一固定词序，`effect_blocks.record_operations` 可能优先保留缩短的旧 source。已有实体占用、区域返回、时间片和共同前缀修复直接复用。

允许修改 `effect_records.py`、`effect_blocks.py`、`construction_inventory.py` 及必要的 `construction_layer_flow.py` 版本／消费接线；只有出现已定位接口缺口时才修改 `construction_relations.py` 的同一路径。测试限新增 `test_construction_condition_selection.py` 与直接受影响方法，说明限本计划、报告、资料入口和验收表。禁止重建任务／牌表、人工选择候选、训练、CB／原生对局、安装依赖、discovery、改权重／课程指针／暂停文件／网络／词表、接管并行识别模块、读取或运行 Pro 辅助代码。保留混合工作区全部既有成果。

## 机械步骤

1. 条件组合：在 `effect_records._refine_record` 中，以已识别的完整存在选择和完整时点组成条件；仅在全部片段消费完时置为 recognized，并将己方配置需求留在 `activation_requirements`，沿既有库存路径检查。前提是原文和当前完整匹配已确认。验收方法为新测试中：存在必要配套时通过、缺件时 False、追加未知修饰语时 None，分别检查公共记录和最终 Evaluation。若未知条件被吞掉或缺件仍通过，停止本步并修正，不启动真实运行。

2. 完整选择：在 `construction_inventory.selector/query_supported/matches/requirement` 中补完整前置／后置区域词序、带数量的或者选择、卡名记述和完整排除；只对整句匹配返回需求。`effect_blocks.record_operations`／`effect_records._refine_record` 保留完整 source 及选择、数量、所有方和来源区域，不能让缩短的 legacy source 丢掉限定。消费仍为 `InventoryDependencies.item_requirement/specs/_check`；多区域不重复库存。新方法验证完整选择的正例、缺件、错误卡名、限定残留和公共 JSON。若只识别句子一部分或新选择绕过库存，停止并保留精确 unknown。

3. 指代与互斥：仅对完整发动时点中有明确被无效发动对象的“那张卡”绑定静态应对范围，不声称当前对象存在；明确“加入手卡或……”分别保留互斥处理，复用既有 choice／branch 和实体检查。前提是步骤 1—2 已有完整语法依据。验证一个实体可作任一处理但不能被两个共同处理重复使用，且未解析的指代仍 unknown。若需要新求解器或无法明确完整语义，保留该具体覆盖原因，不固定数量或全 true 掩盖。

   同路径定点补充：`effect_blocks.block_view` 排除选项发动头中的支付和“盖放的卡”这类名词修饰，防止将它们重复作处理；`_qualifiers/record_operations` 对明示“场上盖放的卡数量×100伤害”保留计数公式，删除旧扫描误填的固定 100。`_scope_choices` 将选项内的“加入手卡或送墓”展平为现有分支，保留共同返回、共享条件和未识别选项；原分支外的操作不能被删除。验证命令为上述新类及已有共同前缀／选项隔离方法；通过标准为九个新方法通过、数量与分支各自绑定正确、所有未知修饰语仍可见；若重复占用、丢选项或改成固定动态量，停在此路径修复。

4. 必要静态与恢复：语义变化后提升积木修订和规范化版本；沿现有 `restore_progress` 使不兼容计算失效，保留任务、逻辑图、12 份 40／15／15 牌表、批次顺序和更新计数。新方法先定点运行；最终与既有 74 个必要方法合组一次，使用已安装 Windows Python `-X utf8 -B`、`PYTHONPATH=src;.`，无 discovery／Torch／skip。对实际修改文件做语法与行尾检查。候选、图或顺序改变以及旧计算误复用时，停在恢复接口修复，不重建整项任务。

5. 真实入口：从 `.cache/construction-runtime-processing-20261110/run-001/kernel.json`（不用 tmp／旧 v19）恢复到全新输出目录。复用已安装 WSL `Chaos-Ubuntu-26.04` 和原 CPU venv，PYTHONPATH 指当前 publish。采用 development、120 秒内部保存片，无任务时间或总轮数上限；每片自动继续，持续跟进候选、参考、选择与真实 Gate。校验原权重更新计数不变及恢复不变量；入口参数以当前 `scripts/run_construction.py` 和准入说明为准。正常未达标回 S2，覆盖缺口按实际原文修复，不以训练替代。真实异常、权限拒绝或用户停止按事实处理；进入跑通阶段后不因上下文或交接主动中断。

6. 交付：更新本轮报告和验收表，区分静态方法通过、真实候选与参考评价、Gate 及剩余覆盖原因。通过标准是原流程到达真实结果且无已知未修程序缺口被计为完成。失败日志单独保留，不累计重复测试数，不从局部通过宣布整体 W1／W4 完成。

## 风险与连续性

run-005第13片的阶段交接定点：3份Evaluation已保存，而索引6的完整规范化结束后calculations被清空；随后质量评价片内到期未产生Evaluation。`ConstructionLayerAdapter.evaluate`在调用质量评价前就pop内部计算，导致下一片会重做已完成关系。先保持进程运行并补匿名反例：完整关系计算后令第一次质量评价返回timed_out，断言原functional-normalization-work-v1完整projections仍保留；JSON恢复后禁止调用关系计算、仅继续质量评价并得到原完整结果。目标 `normalize_function_uses` 与 `ConstructionLayerAdapter.evaluate`：用可选work_state输出保留既有完成work结构，质量评价返回有效Evaluation后才清除calculations；timed_out不清除。版本／事实语义不改，不将未完成质量评价当完成。反例确认及93项回归通过后针对已证实的程序阶段丢失恢复本轮进程，保留3份已完成Evaluation和原批次，只重算确已被旧实现丢掉的受影响候选；不为上下文／交接中止。

同次异常恢复补充：当前批次顺序前两份Side额外资源均0、第三份为3；实际错误已越过前序质量步骤，但 `ConstructionLayerAdapter.evaluate` 仅在整次返回时交回本地Evaluation，后续异常使本地已完成结果未进入kernel。目标 `construction_layer_flow.evaluate`、`construction_fill._fill_with_existing/_construction_cycle`：新增可选的逐候选完成通知，复用现有functional-candidate-batch-v1完整结构，把已完成Evaluation及尚存计算回交原session；原pending_phase、逻辑绑定、查询位置及候选计数一并保存，正常返回不得重复增加生成计数。默认无通知的直接调用保持原行为，不新建文件格式、评分器或后台任务。先以真实匿名cycle在第二份候选前抛异常，验证第一份完整Evaluation及原候选／顺序在session JSON中保留；恢复时不得重选逻辑或重评第一份，继续剩余候选。必要回归失败则仅修本路径，不启动模型；通过后立即续接原run-004 kernel。

run-004真实资源视图异常定点：393.398秒自动返回 `deck parts exceed DTO bounds`，栈定位 `_functional_relations → InventoryDependencies.processing_check` 将方向可用资源视图强造为DeckParts。方向视图可包含待选择的Side资源，原始候选仍40／15／15，不能提高DTO张数或删牌绕过。目标文件 `construction_inventory.processing_check`、`construction_layer_flow` 的两处消费者及定点测试：新增可选原始physical_inventory参数，保留view的main／extra数量作为现有分配器的inventory_counts，SkeletonSpec使用原合法候选（含Side）核对真实物理上界；处理缓存同时绑定view与原候选。两消费者显式传原deck；独立合法DTO调用继续兼容。先用额外可用资源17张但原候选15额外＋2张Side额外的匿名用例复现，验证不抛DTO异常且完整手卡处理正确；从原候选去掉某资源后不得凭view创造该实体，原Side共同容量回归继续有效。失败仅修本通道，不改DTO、门槛、牌表或求解器。必要定点与当前91项合组通过后，从run-004完整kernel立即续算。

run-003真实失分解释异常定点：316.777秒自动返回 `support fact has no Boolean completion`，栈在 `construction_quality._functional_loss_records`，不是实际计分步骤。`evaluate_functional_quality` 已将自身／共同条件明确False的用途所带未知主题条件排除出相关事实，失分解释却逐项强制 `support_value` 求值。目标文件仅 `construction_quality._functional_loss_records` 与 `tests/test_construction_functional_quality.py`：先用self=False及joint=False且携带未采用未知主题条件的匿名用途复现；再以已有三值 `support_state` 读取该解释条件，只为确定False生成失败原因，True跳过，未被当前得分情形选取赋值的未知条件保留在原用途诊断，不伪造Boolean。原输入schema仍要求所有原始事实存在，计分和硬条件仍使用严格完整求值；不扩张赋值枚举，不改变公式、预算、Gate或相关未知的完整性。验收为已不可用用途的分数仍精确0、完整性不被无关未知污染、原主题未知仍保留，重新使该用途可用时主题未知必须恢复为不完整。该反例及87项必要回归通过后从run-003完整kernel立即续算，兼容v21投影继续保留。

run-002真实ContractError定点修正：2404.228秒在 `_bind_automatic_themes` 的 `FunctionalUse.theme_conditions` 合约检查返回“support requires an explicit nonempty Boolean group”，并保存kernel退出；已有完整resident／going_first中单条关系及按原位置合并的支持检查无错误，不能把失败写成正常Gate不足。允许修改 `construction_layer_flow._all_support/_relation_support/_bind_automatic_themes`，复用现有布尔契约，用按128项分组的同运算嵌套树保留全部条件，不提高 `validate_support` 上限、不删条件或全置真。先以129项以上未知配合通过真实主题绑定接口复现，检查所有项False、首项True和最后项True时的真值及所有fact ID均保留；失败停在本接口，不重跑模型。同步对 `_all_support` 和关系投影转换的同类上限作必要回归。

同一路径的确定性复用：`_functional_relations` 不接收scope，输入是固定deck、当前main／extra视图、记录、别名、context、budget、dependencies和config；因此本次同一次规范化中完全相同main／extra视图的完整关系结果可以复用。仅在已完成投影存在且view的main／extra逐项相同时深复制其完整relation／operation_facts至新scope；不同视图不得复用，未完成状态不得当完成。调用方仍逐方向绑定条件、容量、用途与权重。目标文件为 `normalize_function_uses` 的现有projections循环，不另建缓存或求解器。定点测试用真实匿名规范化入口核对相同视图少一次关系计算、不同resident视图独立、三个scope及分数／unknown与旧完整计算一致；所有静态通过后沿最新run-002完整kernel恢复，不重建任务／图／12份牌表。该修正只改变契约表达和相同输入的计算复用，v21／b7语义及有效投影保留。

运行中定点补充（不中断进程完成诊断）：第7—9片的558个关系状态经规范JSON比较完全一致，但队列41→33→36，尚未完成resident。实际路径 `construction_relations._allocate_inventory_usage`／`_allocate_transfer_inventory` 生成含tuple的分配见证，`evaluate_relations.restore` 仅还原条件表达式；`value != states[fid]` 可能将JSON的list与tuple差异算成新事实。先在 `test_construction_calculation_resume.py` 用有物理库存分配的有限依赖链，比较整次计算与逐更新JSON续接；通过标准为相同完整结果和相同实际更新数，并在有限原更新数内结束。若反例未复现，不因此停止运行或修改比较逻辑。反例确认后，仅将本路径的状态比较改为递归等值比较：dict键值精确一致、list／tuple作为有序序列逐项比较，所有标量和序列顺序必须一致；不忽略库存、费用、次数、限制或资源见证。定点静态及83项必要回归通过后，在下一完整原子保存点处理已证实的程序恢复缺陷，并立即从最新完整kernel续算，保留全部任务、牌表和兼容状态，不为交接停止或创建新聊天。比较修正不改变功能语义／政策，不因容器表示差异重新生成候选。

现有记录可能有不同种类选择、旧卡文边界、动态量等其他具体缺口；它们只按真实原文逐项定位，不扩成全项目重审。修改失败保留当前明确差异与失败记录，不用 reset／clean 回滚混合工作区。每次压缩先回读真实用户消息和存档；优化修复阶段可以在安全原子步骤后提请新开，未经用户确认不创建。进入尝试跑通构筑流程后持续跟进，不为交接停机。当前没有待答问题。
