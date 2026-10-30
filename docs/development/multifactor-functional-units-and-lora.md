# 最小功能单元与可选 LoRA（用户确认协议 v2）

本增量继续只位于独立 `ygo_kito.multifactor` 包，不接活跃构筑/效果窗口，不改变主训练恢复或推进条件。`ddaf81e` 保留 v1 原件；本版输入/基础 checkpoint 升为 v2，旧工件须在原提交复现或另行显式迁移，不能关掉来源绑定强行恢复。

## 已确认的工作定义

五维仍为 `large_axis / small_axis / strategic_core / support_role / generic_utility`。大轴指相对投入较大或较完整的联动包，不一定是主轴；小轴是精简功能链或机制包，不一定次要。投入规模、核心性、依赖强度分别保留，既不设唯一官方张数标准，也不由小/大标签推出弱/强依赖或战略地位。

泛用性以**能完成所讨论功能的最小可用单元**为对象。必须同时说明上下文、目标功能、必要成员及数量、已知/未知条件和依赖审核范围；区分 `single_card` 与 `strict_joint`。整包的泛用正标签不属于其每一成员，成员身份也不反推单卡泛用性。成员可以承担启动、必要配套等作用，若要问其自己的泛用性，必须为该成员给出独立的功能/上下文查询。

这套工作协议正文在 `contracts.DEFAULT_LABEL_RUBRIC`，版本 `user-confirmed-functional-unit-v2`，SHA256 同时绑定 `AnnotationRecord / Supervision / RoleTrainer / checkpoint / adapter`。认可定义不等于模型已学会定义。改变标注量尺、功能边界或必要依赖须保留版本，不把同名标准静默覆盖。

## 通用联合依赖契约

`FunctionalContract` 保存功能必需的根成员、带来源的 AND 依赖、已审核成员、条件状态、上下文及可为空的时期引用。数量针对一次明示功能；共享配套数量用 max 合并，不盲目按启动卡副本数相乘。不同 OR 路线用不同契约表达，不把未完成的自动路线发现写成已有能力。

`minimum_members()` 求上述必要依赖的最小闭包，支持传递、共享、数量和有根循环。其“最小”严格相对于调用方声明的根/必要依赖，不证明已穷尽所有卡效、替代路线或规则；未知依赖审核及未知/不满足条件均保留未验证。`assess_unit()` 对实际成员/副本检查缺配套、额外成员、条件和来源，分别给出 membership_ready 与 exact_minimum。它不把文字或手工假设冒充真实引擎结果。

`Group.unit` 绑定该契约，`member_refs` 表示此候选实际纳入的成员/副本；所需数量、联动性、实际覆盖、依赖审核覆盖与条件状态派生为网络因子。卡名/ID 只做依赖端点相等性匹配，不嵌入神经网络。完整一致地重命名端点后张量不变。派生因子不接受调用方自由分数覆盖。

目标功能另以有来源的 `function_tags` 进入网络，区分无效发动、破坏、抽卡、检索、回收、送墓、堆墓、特殊召唤、启动和后续功能；它表达所问的功能，不宣告卡实际能完成。未知/未支持功能可留空，模型保留未知并不给泛用正标签/可用评分，不以名字或只存一段追溯文字冒充功能编码。这是有界工程词表，不是完整卡文语义解析器。

成员输出 `member_roles` 保留 `initiator / required_companion` 及数量，成员 `generic_utility` 固定不继承，保持 null。它是参与作用接口，不能当作成员自己的五维分类。训练 `Targets` 的泛用标签必须指向明确功能契约；正标签只允许 exact_minimum，缺必要成员、未审核或条件未决的单成员不能借整包标注通过。独立的成员负例必须显式提交，不从包标签自动生成。

候选接口 `prepare_function_candidate(context, contract, available_refs, ..., factor_provider)` 先解析必要单元。缺配套/未知范围时返回 unit_unresolved，不调用成本收益提供者；闭合后才把**实际整包成员与数量**交给宿主测量投入、废件、资源、自肃与目标收益。`proposed_refs` 可保留额外副本，不能只按最小单元核算而漏计投入；未提供时提议最小单元。泛用标签仍对应最小功能单元，完整数量方案另评效用/成本，不将带多余成员的方案冒称最小单元。它没有全池补位、单卡收益平均或卡名特殊分支，也不修改构筑会话。父端后续通过集成窗口统一语义接口，本增量不直接对接其未合代码。

## 定义案例与数据来源

`tests/fixtures/multifactor-functional-definition-cases-v2.json` 保存用户修订的三个对象：γ+Driver 整体、仅γ、仅Driver。只有整体在所讨论的响应功能和明示假设下具有严格联动泛用定义；两成员单走的定义标签为负，其他四维留未知。条件包括所讨论的对方怪兽效果响应、己方无怪兽、启动者在手、配套在可用区域、发动窗口/场地允许等，全部明确标为开发场景假设，没有假装跑过引擎。

卡效局部依据是 Konami 官方当前英文页：[PSY-Framegear Gamma](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=12070&ope=2&request_locale=en)、[PSY-Frame Driver](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=12067&ope=2&request_locale=en)。它们只支持功能和必要配套说明，不负责定义泛用性。记录的历史 OCG 时期资格为 null，不猜禁限、发售或实际运行资格。没有把网页相关牌表作为 learner 数据。

`AnnotationRecord` 保存精确输入、目标节点、五维软标签/null、来源、时期或未知、标注者、分区和 definition_case。用户讨论案例固定为 development，不能改写为 train/validation/final_eval；测试有限更新使用 `definition_development` 来源，状态仍是 engineering_only。来源字符串与分区标记不是全局防重标认证：真实生产数据仍须宿主已有不可变分区索引审核，同一案例及其改名/变体不得流入独立终验。

当前只备少量定义案例，没有抓取牌表、频率标签或所谓高质量真实训练集。后续应采集不同骨架、功能、必要配套、条件与投入变化下的人工标注及合法干预/配对反馈。独立留出必须按包/机制家族与案例谱系划分；整包和其单成员反例一起留出，不能拆到训练/终验两边。

## Base 与 LoRA 两阶段

第一阶段先用真实来源监督基础网络的概念和功能/依赖/情境表示，保存独立 base、特征/协议版本、分维监督记录与数据摘要，再做独立质量和校准评估。当前没有这些真实 base 学习或质量结果，更新计数也不能认证概念能力。

第二阶段才可选 LoRA，细调概念与卡片/组合在上下文中的匹配。正常 `enable_lora()` 要求五维 base 至少有声明为真实来源的监督记录；这只是防止随机 base 被静默当成已学概念，不是能力验收，也不是主训练的新门槛。随机或仅工程更新 base 只能显式 `engineering_mode=True`，仅接工程/定义开发来源，公开角色/评分保持 null，不能通过给 adapter 编造真实来源解除该边界。

LoRA 在 readout、角色、适配性、效用和成对兼容性投影上增加 `alpha/rank * B(Ax)`；B 零初始化，因此新适配器输出等于 base。只更新低秩矩阵，原 base 参数冻结，base Adam/计数/摘要不变。每个 adapter 独立保存矩阵、Adam、rank/alpha/seed、游标、分头/分角色更新、数据摘要；只绑定 base 参数/训练谱系摘要，不拷贝或覆盖 base 权重。

加载先在不连接基模的临时对象中核对并恢复权重、Adam 分组/参数/非空动量及更新元数据，完成后才安装或注册版本并切换。恢复失败不冻结 fresh 基模、不留下 hooks、不改变已有 bank/活动版本/优化器/推理；安装 hooks 自身抛错也撤销本次安装并恢复原 requires_grad 标志。新代码仍绑定自己的源码摘要，不隐式放行 `6e0c3d4` 的旧工件。

正常 adapter 模式拒绝 `engineering_fixture` 和 `definition_development`，工件中也不能包含这些更新。工程模式继续仅接工程/定义来源。公开状态按实际使用的版本判断，不能由基模状态替活动 adapter 背书：

| 推理来源 | 公开输出状态 |
| --- | --- |
| 未启用/已停用 adapter | 使用基模原有各头状态；有效基模不因 adapter 存在而额外拒判 |
| 活动正常 adapter，无对应真实监督更新 | 该头/该角色维为 untrained，公开概率/评分为 null，即便零增量恰好等于基模输出 |
| 活动正常 adapter，对应头有真实监督记录 | 仅该头/该维可给未校准建议，其余维不继承基模状态 |
| 活动工程 adapter，或活动版本混有开发/工程更新 | 全部只作 engineering_only 诊断，停用后可恢复原基模状态 |

`adaptation` 同时列出 inference_source、base_head_status、active_head_status，便于区分基模与活动版本。以上监督状态仍只是来源/更新记录，不是可靠性或能力验收。

卡片/组合的匹配通过其已知效果、功能、依赖、成本和上下文因子表达；LoRA 不新增卡 ID 或名字嵌入，也不将概念学习改成对卡名的记忆。

```python
# 正常适配需要独立加载已有真实监督 base；本轮没有该生产工件。
trainer = RoleTrainer.load(base_path)
trainer.enable_lora()  # 随机/仅工程 base 明确拒绝
trainer.create_adapter("context-v1", AdapterConfig(rank=4, alpha=4))
# 宿主显式提供 train_supervised / train_preference；本轮不启动正式训练。
trainer.save_adapter(adapter_path, "context-v1", data_cursor="source-revision:next-row")
trainer.activate_adapter(None)  # 恢复原 base 推理；不可趁机修改有绑定的 base
trainer.activate_adapter("context-v1")

restored = RoleTrainer.load(base_path)
restored.load_adapter(adapter_path)  # 检查 base/源码/特征/协议/学习率绑定并恢复 Adam
```

导入类为 `from ygo_kito.multifactor.training import RoleTrainer` 与 `from ygo_kito.multifactor.adapters import AdapterConfig`。多个 adapter 可独立创建/切换；停用返回 base 输出。adapter 绑定后如要继续改 base，应另开基础训练版本，旧适配器不能静默迁移。激活 adapter 时不能把其状态混存为 base checkpoint。CLI 可选 `--checkpoint BASE --adapter ADAPTER`，没有显式匹配 base 不加载 LoRA，也不默认读取活跃基模。

独立合成输入为 `docs/examples/multifactor-candidates-v2.json`，可用现有 Python 执行 `python -m ygo_kito.multifactor --input docs/examples/multifactor-candidates-v2.json --output .cache/multifactor-demo-v2.json`；`PYTHONPATH=src`。旧 v1 样例只供旧提交复现，当前 CLI 明确拒绝隐式迁移旧 schema。`scripts/check_multifactor_roles.py` 仅显式加载六组本模块测试；新增组专查加载失败事务、非空 Adam 下一更新及基模/活动版本状态组合。

## 输出与当前完成边界

未训练、工程/定义开发更新的公开角色概率、兼容性和 advisory_score 为 null；数值只在 diagnostic_role_probabilities/raw_utility 下标为诊断。即使某头有真实监督更新，未知必要单元仍不能作为已验证的泛用性输出。所有输出仍未校准、不是规则权威；当前没有生产权重或接入主训练。

本轮必要检查分开记录：结构不变性、模拟因子、官方卡效局部契约、通用联合依赖反例/定义案例，以及 LoRA 零增量、仅低秩更新、base 不变、独立版本/Adam/下一更新恢复、切换和错误绑定拒绝。定义案例符合契约，不等于模型通过独立泛化验收。

要称为可用能力，仍缺真实情境标签与 base 训练、陌生机制/包与成员反例的独立质量评估、概率/拒判覆盖校准，以及在已训练 base 上检验 LoRA 是否带来收益与是否遗忘。以上待做项只约束本额外模块的能力表述，不阻塞现有修复、正式主训练或之后由集成窗口安排的整合。
