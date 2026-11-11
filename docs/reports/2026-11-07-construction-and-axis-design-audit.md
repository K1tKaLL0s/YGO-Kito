# 构筑评分 2.0 与轴／泛用模块的设计一致性、实现程度与质量审计

结论：新版构筑评分（修订版 2.0）与原始设计定稿在核心理念上同频，route-first→static-first 属于用户明确要求的有效修订而非漂移；但当前交付是"设计 + 未入库的参考核心"，不是已接线的生产实现，且现有评分代码存在一处会把未知区间压成完整分的确定算术错误。第二段会话的轴／泛用模块设计完善度较高，P0 有实改，但新契约（LabelCell、条件树、新指标、新划分）尚未进入 prepare／train／inference 活动链路，并存在三个可最小复现的语义缺陷。

核验日期为 2026-11-07。源码为 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，HEAD `3f57198` 加当前未提交工作区（87 修改、20 删除、113 未跟踪）。本轮只读审计；没有修改生产 Python 文件、模型、牌表或课程状态；没有提交；没有运行训练、基础 CB、原生引擎或有偿 API。

## 1. 执行范围与依据

审计对象：

- 当前权威检出 `N:\YGO-Kito\_publish_20261030` 及其历史工作树。
- 第一段会话 `session-1c303d24-b107-4076-a24b-10ff1b27ef4d`（构筑设计与评分）。
- 第二段会话 `session-73fc4d5a-a19f-4b63-b130-e23359162b79`（轴与泛用识别）。
- 原始设计定稿 [游戏王AI项目设计定稿.docx](../current/architecture.md)。
- 新上传构筑文档 `C:\Users\27499\Desktop\YGO-Kito_构筑流程与评分机制_完整优化方案_2026-11-03.docx`（修订版 2.0，SHA256 `72704f08f977f7f20fa2c6005774c26e940dfd48ee8db84cbab4fcc23c0d12bf`）。
- 新上传问题陈述 `C:\Users\27499\Desktop\YGO-Kito_问题陈述_路线目标与基础CB_2026-11-04.docx`。

版本判定：同名构筑文档存在两个内容不同的修订。历史 1.0 含固定 70/56 标尺、EvaluationContract、起手概率与实际换备，文本见[历史提取](../../.cache/review-20261103/plan-extract.txt)；当前 2.0 已撤回这些内容，文本见[当前提取](<N:/YGO-Kito/.cache/audit-20261107/construction-optimization-upload.md>)。本报告以 2.0 为准，不把 1.0 的问题计入。

有效约束：60/25/15 分区权重已于 11-04 明确作废；M1/v4 未获执行授权；静态评分不调用起手概率或基础 CB；训练继续暂停；2026-11-01 最终卡池未核前 fail closed。

证据边界：本轮的实测只有纯 CPU 只读探针与既有安全单测，不构成训练、CB 或原生引擎验收。探针回执见[评分反例](<N:/YGO-Kito/.cache/audit-20261107/score-probes/quality_pure_counterexamples_v1.json>)、[轴语义探针](<N:/YGO-Kito/.cache/audit-20261107/axis-probes/source_semantics_results.json>)、[安全单测日志](<N:/YGO-Kito/.cache/audit-20261107/axis-probes/safe_unit_tests.txt>)。

## 2. 构筑评分 2.0 与原始设计的一致性

### 2.1 同频项

- 静态与概率分离：2.0 明确静态评分不调用抽牌概率、实战表现与实际换入换出；未知不填零分或中点。原始设计"标签不能替代条件／成本／区域／时点""未知不等于否定"得到保留。
- 失分只计一次：先算潜在分 P、再算有效分 F，`D=P−F`，总分只用 F，不再二次扣分；同一功能多个原因失效不叠加罚金；同一缺件使两个功能失效则分别保留。与原始"共享收益一次、独立损失独立"一致。
- Side 只评换入价值、不要求换出名单：与原始 BO3 双向、Side 不能补足主构筑一致。方向增量 `F(R+Y)−F(R)`、方向权重和为 1。
- 参考比例准入：候选静态分与同口径参考分比较，比例为 0.8，明确"70 与 56 只是算例"，不保存固定锚点。比 1.0 的固定标尺更接近原始"参考是诊断、不是拟合模板"。
- 同主题只算一次、主题命中为 `field ∪ 记述`：对应 11-04 会话中用户当场确定的口径；保留"检索不继承堆墓标签""费用送墓不能触发被效果送墓收益"。
- 不自动扣分的结构：主卡超过 40、额外未填满、无轴归属、陷阱延后、非独立起动组件，均不单独罚分，与原始反对"浓度／空位自动加减分"一致。

结论：2.0 与原始设计核心同频。route-first→static-first 是 11-02 起用户明确要求的重构，属有效修订。

### 2.2 偏离与风险

**AUD-07-01／P1：槽位惩罚同端相减，可倒置区间并把未知压成完整分**

设计第 5.5 节写明：潜在分 P 已知、有效分范围 `[L,U]` 时，失分范围为 `[P−U,P−L]`。实现却对上下界同端相减：

- [construction_quality.py:807](../../src/ygo_kito/construction_quality.py#L807-L808) 使用 `row["lower"]−penalty["lower"]`、`row["upper"]−penalty["upper"]`；正确应为 `lower−penalty_upper`、`upper−penalty_lower`。

纯函数实测（真实 `_assemble` + `_slot_ledger`，Main 收益、40 个未知槽、0.2 预算）：

- B=[1,1] 得到总分 min 100 / max 80，区间倒置；
- B=[.8,1] 把本应 60..100 压成 80..80，同时 `complete=true`、`scope_complete=true`，而 `partial_items` 仍含未定项。

这是"未知被压成完整分"的直接算术错误，与 2.0 自身完整性要求正面冲突。它只在启用现有 v3 `slot_budget` 时触发；未跑完整 gate，不能声称生产 CB 已被误放行。

**AUD-07-02／P2：`x=E` 的调用型计量需要实测校准**

普通投入用 `x=40E/N`（受真实主卡数稀释），调用型用途用 `x=E`（不受 N 稀释）。设计用"同一功能只一种计量、关系层必须给出具体调用者"防重复，逻辑自洽；但它故意放开了单调性：在更大牌组中增加"已核实调用"的不同功能，可以在不提高密度的前提下抬高 S。这不是错误，但应在 A08／A11／A16 上验证；当前文档未给该情形的数值算例。

**AUD-07-03／P3：主题加成仍是"每命中一次 +α"**

2.0 用"珠泪堆墓必须自己的卡组到自己的墓地、且存在相容墓地用途"把"主题命中"与"功能兑现"分开，比 1.0 强；但"记述"命中本质是文本匹配，`珍珠世界`这类卡靠"文本提及主题名"拿分，仍需防止把"提及"当"属于该机制"。原始设计早已警告"tag 不能替代真实效果"，2.0 目前只靠规则谓词约束，未给反例测试。

### 2.3 交付与实现差距

**AUD-07-04／P1：随文代码包不在项目内，20 项测试无法复现**

2.0 第 10 节声称交付 `ygo_static_score.py`、测试、`demo.py` 与运行结果，并自述"已经运行验证的参考核心"。在活动检出与桌面均未检索到该文件（glob 无结果），其 20 项测试与运行结果无法在本仓库复现。文档自身也承认没有现有仓库、接线表只是"应修改的位置"，因此不算虚假陈述；但当前状态必须表述为"设计与未入库的参考核心"，不能表述为已接线生产。

**AUD-07-05／P2：设计声称"全候选先评后选"，实现仍是先选后评**

设计要求所有候选先完成同一套评价，再用于选择、反馈、学习和准入。实现是：两层比较 → 取 `best_deck` → 只对该副算质量 → 过 gate（[construction_fill.py:764](../../src/ygo_kito/construction_fill.py#L764-L771)）。属未完成的重设计，不应报成回归，但文档声称与代码顺序不一致。

**AUD-07-06／P2：A02／A04／A16／A20 覆盖不到生产接线**

主题开关影响全部下游（A02）、主卡量对 E 的归一化（A04）、缺证据不生成负例（A16）、重选后旧准入失效（A20）在文档中是抽象验收项，当前没有对应集成测试。

## 3. 构筑评分的现存实现缺陷

**AUD-07-07／P2：cycle 丢弃宿主 `losses` 与 `slot_uses`**

[construction_fill.py:667](../../src/ygo_kito/construction_fill.py#L667-L670) 只转发 `generic_fits`／`duplicate_purposes`／`side_deck`；`evaluate_quality` 的 `losses`、`slot_uses` 参数（[construction_quality.py:847](../../src/ygo_kito/construction_quality.py#L847-L848)）静默丢失。同一候选直接调用与经 cycle 调用可得不同判定：撤销不生效，已核实的 used／dead 声明变成未声明。该宿主接口启用这些声明时可达；未找到当前生产调用提供 `quality_evidence`。

**AUD-07-08／P2：同一收益按不同原因重复全额撤回**

[construction_quality.py:748](../../src/ygo_kito/construction_quality.py#L748-L782) 以 `(benefit_id, reason)` 去重，每次从原行重新取 `award`，没有该 benefit 的剩余上限。实测 A、B 各占 0.5 且满额，对 A 一次 `share=None` 后剩 50，两次不同原因后剩 0；同原因控制仍 50。自动 harmful 路径也可触发：两个 `problem_id` 均损害 A 会生成两个不同 `harmful:<problem>` 原因。违反现有 QualityLoss"撤回恰好已授予收益"的合同。

**AUD-07-09／P2：`verified=True` 的 unknown 槽位被计为 used**

[construction_quality.py:727](../../src/ygo_kito/construction_quality.py#L727-L744)：`dead` 以外的 verified 状态统一落入 else 计 used。40 张均 `SlotUse(...,'unknown',...,verified=True)` 时，明细 40 行 status=unknown，汇总却 used40／unknown0，惩罚 0..0；未声明控制组得到 0..0.2。不确定性被抹掉。

**AUD-07-10／P2：harmful fits 未绑定候选范围，牌外卡也能扣分**

[construction_quality.py:861](../../src/ygo_kito/construction_quality.py#L861-L868) 先把所有 verified harmful fits 转损失，而 generic 评分只遍历真实未分配卡与配置 problem（[construction_quality.py:589](../../src/ygo_kito/construction_quality.py#L589-L616)）。给现有 `acceptance_layout(0)` 附加当前库存不存在的 `card999999`、`damages=('entry',)` 的 harmful fit，entry 仍被撤回。不属于 RPC 注入，属宿主复用宽事实批时的范围绑定缺失。

**AUD-07-11／P2：gate／restore 不校评价器版本与任务摘要**

[construction_progress.py:74](../../src/ygo_kito/construction_progress.py#L74-L100) 只核 layer／policy_version／config digest／deck digest；`restore_progress` 精确记录值但同样不校 quality 记录自身 `version`／`task_sha256`。实测分别改为 `obsolete-evaluator`、全 0 摘要，绑定检查仍接受且结果不变；外层 task 绑定不能代替嵌入 quality 的 task 绑定，且 passed 恢复会跳过重算。

**AUD-07-12／P3：证据行复用上一循环残留的 copy**

[construction_quality.py:622](../../src/ygo_kito/construction_quality.py#L622-L624) 在按 code 循环中使用上一循环的 `copy`；多张未分配卡时 evidence 重复最后一张。评分行用 code 正确，未证明总分受影响。

**AUD-07-13／P3：`compare_quality` 无生产消费者且语义不当**

[construction_quality.py:934](../../src/ygo_kito/construction_quality.py#L934-L963) 比较毛收益 value／bounds，忽略 net／loss／slot penalty；全树只有定义与测试调用。属潜在 API 问题，不能描述成"当前候选排序必然忽略扣分"。

**边界纠正**：未跟踪的 construction_contract.py（历史源码路径：`../../src/ygo_kito/construction_contract.py`，现行已替代） 是无运行时消费者的未授权 M1 草案，其 70/56 与时期 substring 不能当在用缺陷。严格偏好学习确有消费链路（[construction_learning.py:114](../../src/ygo_kito/construction_learning.py#L114-L149)、[local_course_collaboration.py:261](../../scripts/local_course_collaboration.py#L261-L275)）；当前暂停与 updates=0 ≠ 代码永不训练。

## 4. 轴／泛用模块：设计完善度、实现程度与质量

### 4.1 设计完善度

方案覆盖 v8 契约、`LabelCell` 逐格掩码、条件树（`all/any/at_least_k/not`）、资源消耗与区域、来源分组与四类泛化协议、逐格损失与多任务权重、A00–A11 消融、T01–T22 语义用例、280 独立参考目标与四类验收线（[原方案保留文本](<N:/YGO-Kito/.cache/docx-extract/scheme.txt#L236-L431>)）。明确区分"未知／不适用／未评价"，禁止把 F1 或 generic 概率换算成构筑分，禁止对"多放本家／更多额外"施加单调约束，与原始设计同频。

未定或薄弱：

- OR 分支闭包语义未写死：要求"替代分支不能拼成虚假可行分支"（T06），但未规定"A 需要 B 或 C 时最小成员是 A+B 还是 A+B+C"，也未规定"只审查 A 未审查 B 时能否算完整"。
- 候选轴召回 ≥0.95 未给出新主题下"完整标注轴集合"的定义，无法判定分母。
- 载体／增强冲突消解只给了"可同时成立"，未给两者争夺同一资源时的裁决规则。

### 4.2 实现程度

- P0 是实改，但不是全迁移：主动入口已无 `site.addsitedir`（仅历史 `diagnose_existing.py` 保留）；`actor_absent`→None、`plan_known` 硬门控已撤（prepare_base.py:120（历史源码路径：`../../training/axis_generic/prepare_base.py#L120-L148`，现行已替代）、[scoring.py:145](../../src/ygo_kito/multifactor/scoring.py#L145-L149)）；数据配置指向 N 盘。但默认 config.json:10（历史源码路径：`../../training/axis_generic/config.json#L10`，现行已替代） 仍指旧 `v7-repo-001`，prepare_base.py:60（历史源码路径：`../../training/axis_generic/prepare_base.py#L60-L61`，现行已替代） 发现已有 dataset 就直接返回，旧缓存不会自动迁移。
- 确定性只条件性成立：`resolve_plan` 与 SQL 排序已稳定、种子已固定，但 `extra_ids` 仍按 set 遍历，`PYTHONHASHSEED` 只警告，`gzip.open` 未固定 mtime（[runtime.py:8](../../training/axis_generic/runtime.py#L8-L30)、prepare_base.py:193（历史源码路径：`../../training/axis_generic/prepare_base.py#L193-L201`，现行已替代））。固定启动环境下逻辑内容稳定，不能宣称无前提的逐字节可复现。
- 新契约未进活动链路：[analysis.py:99](../../src/ygo_kito/multifactor/analysis.py#L99-L125) 的 `migrate_v2_input` 只加 v3 envelope，[contracts.py:450](../../src/ygo_kito/multifactor/contracts.py#L450-L455) 的活动 `RoleInput.from_dict` 仍拒绝该产物（纯 CPU 探针证实）；训练仍读 legacy 五头浮点目标（[training.py:54](../../src/ygo_kito/multifactor/training.py#L54-L82)），不消费 `LabelCell`；conditions／splits／新 metrics 无 prepare／train／inference 消费者；mechanism 只是序列化元数据，未成监督或预测头。
- 应保留的旧能力：None 损失掩码、五独立角色输出、结构与构筑双 view、整包不广播成员标签都是真实现，不能说模型不存在。

### 4.3 质量缺陷

**AUD-07-14／P1：OR 分支闭包错误**

[functional_units.py:141](../../src/ygo_kito/multifactor/functional_units.py#L141-L192)：`minimum_members` 只沿 `required` 做闭包，`assess_unit` 把所有可满足的 alternative 组并进 `effective`，不选一个、不递归闭包。实测：

- A 需 B 或 C、库存 A+B+C → 错标 `exact_minimum=true`；
- B 还需缺失的 D、只有 A+B → 错标 `current_function_ready=true`；
- 只审查 A 未审查 B，A+B 仍标 `minimal_membership_complete`；
- A+B 被误判为 `single_card`。

另有静态路径：[scoring.py:180](../../src/ygo_kito/multifactor/scoring.py#L180-L198) 先按全 available 通过，默认候选却取 mandatory-only 最小集，不再拒绝，factor provider 可能收到缺分支的 A。可达路径为 Group／`Targets.validate`／`CandidateScorer`；本轮没有 shard 级 OR 使用量统计，不能反推历史训练已被污染。

**AUD-07-15／P1：条件求解器重复消耗同一资源**

[conditions.py:89](../../src/ygo_kito/multifactor/conditions.py#L89-L146)：ANY／`at_least_k` 各子项从原始库存计算并返回原始库存。单 A 库存时，`all(any(A), A)` 与 `at_least_k(A,A,k=2)` 都错判 satisfied；两个 A×1 的 leaf 不能合成 A×2；贪心 ALL 依资源顺序会把"任意区 A + 主区 A"的可行分配误判；`distinct_group` 未使用。该模块未接活动训练，不能据此否定旧 v7 指标。

**AUD-07-16／P1：指标丢弃全错角色，macro 虚高**

[metrics.py:31](../../src/ygo_kito/multifactor/metrics.py#L29-L43)：`precision+recall==0` 时 `f1=None`，`macro_f1` 把 None 过滤掉。perfect + 全错两角色 → macro=1.0，正确应 0.5。旧活动 [assessment.py:19](../../training/axis_generic/assessment.py#L19) 本来正确，新模块 bug 不影响历史报告。

次要：`splits` 按单一标识分组、不做跨标识连通；`scoring.py:160` 的解释字符串仍称"无 primary plan 扣 core/support"，与实际已撤门控矛盾；`runtime.data_root` 只定义无消费者（但配置已指 N 盘，不宜说环境仍混用）。

验证：轴语义探针以 Python 3.10.20 运行，`torch_loaded=false`，16 项安全单测全过、0 skip，13 个语义探针复现缺陷；回执含源码 SHA。

## 5. 基础 CB 问题陈述与当前实现的对应

上传的问题陈述是新问题的定义，不是已接受的解法。当前实现：

- 入口在执行授权与构造 gate 双重校验后才运行（[basic_cb_inference.py:168](../../src/ygo_kito/basic_cb_inference.py#L168-L178)）；默认 10 秒／16 次尝试／100 决策（[basic_cb_inference.py:220](../../src/ygo_kito/basic_cb_inference.py#L220)）。
- 候选排序仍称"existing goal model search order uncalibrated"，不是质量校准（[basic_cb_inference.py:196](../../src/ygo_kito/basic_cb_inference.py#L196)）。
- 只接受第一个通过 scope 校验的路线，明确不声称最优（[basic_cb_inference.py:226](../../src/ygo_kito/basic_cb_inference.py#L226-L239)）。
- 问题陈述记录的融合目标示例使用 `requires_opening_hand=[73956664,37961969]`（[cb-question-upload.md](<N:/YGO-Kito/.cache/audit-20261107/cb-question-upload.md#L46>) 第 46、141 行）；当前仓库该任务的配置记录为单卡 `[73956664]`（[20261027-pearl2207-v1_1.json:85](../../configs/training-auxiliary/20261027-pearl2207-v1_1.json#L85-L87)）。两种写法都把"通常召唤雷诺哈特并以其效果送墓"固化成"起手必须有该卡"，比实际路线更强；这是问题陈述所指"起手条件被不必要加强"的实例，不是新发现的配置错误。
- 弱搜索也可能给出引擎认证的见证；无关未知不必使见证无效；牌组中另有同卡副本时，额外起手卡不必使目标无效。

本轮未运行 CB，以上为实现与陈述的对应关系，不构成对问题陈述的验收。

## 6. 必须纠正的历史说法

1. "93 项测试已通过"：本轮只跑 16 项安全单测；历史数字不是本轮结果。
2. "517 项 CI 当前通过"：属历史记录，当前无 CI 运行。
3. "60/25/15 仍是要求"：已作废，不能当回归。
4. "优化器更新 0 次 ⇒ 无学习能力"：链路存在，只是未运行。
5. "未跟踪 M1 草案的问题 = 生产评分缺陷"：它是无消费者的草案。
6. "全候选先评后选已实现"：实现仍是先选后评。

## 7. 建议处理顺序

1. 先修 AUD-07-01（交叉端点，一行），补"未知槽 + 有惩罚"断言。这是唯一能直接把不确定压成满分、影响准入的确定错误。
2. 修证据转接：cycle 转发 `losses`／`slot_uses`，binding 校验 quality 记录自身 `version`／`task_sha256`（AUD-07-07、AUD-07-11）。
3. 修槽位与撤回语义：unknown 不得计 used；同一 benefit 撤回不得超过已授予额度（AUD-07-08、AUD-07-09）。
4. 轴模块三个 P1 按 OR 闭包 → 条件资源 → 指标顺序修，先补最小反例测试；这些模块未接训练，修完仍需 prepare／train 接线才算能力（AUD-07-14 至 16）。
5. 再决定 `ygo_static_score.py` 是否入库、A02／A04／A16／A20 集成测试；在此之前 2.0 只能算"设计与参考核心"，不能算已接线生产。

## 8. 复现与回执

- 评分反例脚本与回执（源码 SHA、4 组纯函数反例）：[quality_pure_counterexamples_v1.py](<N:/YGO-Kito/.cache/audit-20261107/score-probes/quality_pure_counterexamples_v1.py>)、[quality_pure_counterexamples_v1.json](<N:/YGO-Kito/.cache/audit-20261107/score-probes/quality_pure_counterexamples_v1.json>)。
- 轴语义探针与安全单测：[source_semantics_results.json](<N:/YGO-Kito/.cache/audit-20261107/axis-probes/source_semantics_results.json>)、[safe_unit_tests.txt](<N:/YGO-Kito/.cache/audit-20261107/axis-probes/safe_unit_tests.txt>)。
- 文档提取：[construction-optimization-upload.md](<N:/YGO-Kito/.cache/audit-20261107/construction-optimization-upload.md>)、[cb-question-upload.md](<N:/YGO-Kito/.cache/audit-20261107/cb-question-upload.md>)、[original-design.md](<N:/YGO-Kito/.cache/audit-20261107/original-design.md>)、[scheme.txt](<N:/YGO-Kito/.cache/docx-extract/scheme.txt>)。
- 未执行：训练、基础 CB、原生引擎、完整 gate／restore、完整 cycle、付费 API；未修改业务代码；未提交。
