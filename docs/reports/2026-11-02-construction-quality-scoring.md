# 完整构筑质量评价实施报告（2026-11-02，第二次修订）

本报告对应 2026-11-02 评审后的实现：评价项改为全局评分项、展示分组与总分分离，覆盖率与供给深度分开，deferred／not_applicable／unknown 三态分开，未知项输出区间。第一版报告中的三处事实错误已在§6 修正。正式训练、CB、native 与生产参数更新仍暂停；没有提交、推送或修改 checkpoint。

## 1 实现范围

| 文件 | 变更 |
|---|---|
| `src/ygo_kito/construction_quality.py` | 重写为 `construction-quality-evaluation-v2`：七个全局评分项、展示投影、三态、覆盖率/深度分离、区间输出、跨区限制、未分类卡位 |
| `src/ygo_kito/construction_progress.py` | 门槛绑定区间与 deferred；新增 `quality_scope_deferred`（`require_complete_scope` 时） |
| `src/ygo_kito/construction_fill.py` | 汇总与反馈改用评分项与区间；优化反馈给出“哪一项、哪个缺口” |
| `src/ygo_kito/course_admission_policy.py` | 重选后重算门槛仍传入该候选自己的质量记录 |
| `tests/test_construction_quality.py` | 24 项纯 CPU 检查 |
| `docs/development/2026-11-02-unsettled-scoring-decisions.md` | 登记表第二次修订：C8–C18、Q1–Q10、三处错误修正 |
| `docs/development/2026-11-02-scoring-paired-judgment-worksheet.md` | 判断表第二次修订：P1 有效份修正、P4 拆分、P5/P6/P7/P8 重写 |
| `docs/reports/2026-11-02-construction-quality-tests.json` | 本轮 189 项机器回执 |

## 2 评价结构（v2）

七个评分项各自带全局权重，Main／Extra／Side／跨区只是展示分组：

| 评分项 | 展示分组 | 回答的问题 | 数据来源 |
|---|---|---|---|
| `supply.main` | main | 必需功能是否被供给；有目标时投入是否达到目标 | 功能行 K／E／状态 |
| `supply.extra` | extra | 定向目标是否覆盖 | `mode=target` 功能行 |
| `continuation` | main | 必需用途与联合必需能否接续 | uses、joint_required |
| `limits` | cross | 同时使用限制与共享资源是否相容 | constraints、joint conflicts |
| `duplication` | extra | 额外重复位是否有声明用途 | 折扣台账＋宿主声明 |
| `generic` | main | 已声明环境问题是否被未分类卡位解决 | 声明判断＋未分类卡位 |
| `side_plan` | side | 已声明问题是否被换备回答、换后原要求是否保留 | 显式换备方案 |

关键规则：

- **覆盖率与深度分离。** 未声明目标时，供给行记 `coverage=1.0` 而 `value=None`，该项为 unknown 并给出 `supply_depth_unevaluated`；不再出现“一张和三张都得 1.0”。
- **三态。** `deferred`（本阶段不评价）、`not_applicable`（任务不要求）、`unknown`（证据缺失）分别记录，互不替代。
- **限制跨区。** `limits` 不属任何单一分区；未声明限制且无 `limits_verified` 事实时记 unknown，不记“不适用”。
- **未分类卡位。** 只有显式声明的泛用判断才参与 `generic`；其余未分配卡位列为 `unclassified_slots`，不自动得分，也不从供给与接续分析中删除。
- **总分。** 每个适用项有 `lower`／`upper`：已知部分按 `q`，未知部分按上限 1；`total.min`、`total.max`、`complete`、`scope_complete`、`weights_effective` 一并输出。complete 时 `min == max == value`。
- **展示不改分。** 总分只由评分项与权重计算；`display` 是投影。测试直接以 `weights_effective × items` 复算总分并比对。

## 3 已执行的标定对照（阶段性供给比较，不是完整分）

使用固定验收量（匿名 ID），政策声明 `targets={convert:6.0}`、`function_weights={convert:2.0}`、`default_target=3.0`，并**显式将 `limits`、`generic` 记为 deferred**——所以这两个数只代表供给深度这一阶段比较，不能当完整构筑分：

| 功能（必需，Main） | 参考 K／E | 参考值 | 候选 K／E | 候选值 |
|---|---:|---:|---:|---:|
| 入口 entry | 10／9.4 | 1.000 | 10／9.4 | 1.000 |
| 转换 convert（目标 6、相对权重 2） | 7／6.6 | 1.000 | 4／3.8 | 0.633 |
| 随机准备 random | 14／13.2 | 1.000 | 7／6.6 | 1.000 |
| 定向准备 targeted | 4／3.8 | 1.000 | 5／4.7 | 1.000 |
| 手牌处理 hand | 7／6.6 | 1.000 | 9／8.4 | 1.000 |
| 场上处理 field | 2／1.9 | 0.633 | 6／5.6 | 1.000 |
| **阶段性总分** | | **94.761905** | | **89.523810** |

`complete=true`、`scope_complete=false`（两项 deferred）；入口有效投入双方同为 9.4，评分不宣称参考入口更强；参考优势在已声明的转换瓶颈，候选优势在场处理，属真实取舍。

同一对照若**不**把限制与泛用 deferred，则两项因“未验证限制”“未声明环境范围”记 unknown，记录变为：参考 `min=31.587302, max=98.253968`，候选 `min=29.841270, max=96.507937`，`complete=false`。这正是“未知只给范围、不给单点分”的预期行为。

## 4 标定发现

0. **排序没有被政策反转。** 同一对牌表只改政策声明：Δ = S_候选 − S_参考分别为 0.000000、−5.238095、−6.111111、0.000000。参考从未落后；政策改变的是差距大小与饱和程度。第一版报告“排序不能当结论”属过度表述，已更正。
1. **只有供给项参与时标尺压缩。** 该对照只有 `supply.main` 在范围内，多数行已饱和，差距仅 5.24 分；要承接“参考至少约 70”的人工尺度，必须让接续、限制、泛用、Side 真正参与，而不是调权重。
2. **占位效率尚未进标量。** 文档 52.22%／44.76% 是主轴模块分母（18／21），整副已分配位口径为 30.3%／44.8%，方向相反；密度仅作证据，进标量前必须声明口径。
3. **未声明目标不再等于满分。** 旧实现退化为覆盖分（工程夹具 100.0），现改为 unknown + 范围。
4. **参考比例线仍不能先定。** 阶段性 94.761905 的 80% 为 75.808924；候选 89.523810 仍会通过。须在完整范围（接续、限制、泛用、Side 全部适用）下重算参考，再设线。

## 5 未定细则与结构闸门

未定项缩减为 Q1–Q10（目标值、功能权重、评分项权重、饱和曲线、通过线、泛用范围、Side 粒度、占位效率、未知优先级、阶段划分）；2026-11-02 评审已确定 C8–C15（覆盖/深度分离、三态、限制未验证、全局权重、必要条件分离、未知给范围、事实复用收益一次、未分配不自动泛用），C16–C18 为实现方向。详见[登记表](../development/2026-11-02-unsettled-scoring-decisions.md)。

结构选择写入 `UNSETTLED_STRUCTURE` 并随记录输出；`structure_accepted` 未置真时门槛返回 `quality_structure_not_accepted`；`require_complete_scope` 为真且存在 deferred 时返回 `quality_scope_deferred:<items>`。

## 6 评审驱动的修订

| 评审意见 | 修订 |
|---|---|
| §0 未展示反转，Δ 方向要明确 | 文档与登记表改为 Δ = 候选 − 参考，明确“打平或参考领先”，不再说排序反转 |
| P1 小美人鱼应 +1.0 | 判断表改为 +1.0、融合组件 3.8→4.8、入口 9.4→8.5；并注明只能作整体取舍 |
| P7 未构造 18 对 21 | 重写为同为 40 张、同等必要功能的占位比较，承认裁 3 张会变 37 张 |
| 覆盖分／供给分／完整分混用 | 供给行拆 `coverage` 与 `value`；deferred／NA／unknown 三态；阶段由 `deferred` 显式声明 |
| 未声明限制被当成不适用 | 新增 `limits_verified`，未核实一律 unknown |
| 两层等权造成隐藏权重 | 改为七个全局评分项＋展示投影；新增“分组不改总分”测试 |
| 未知项需要上下界 | 输出 `total.min`／`total.max`／`weights_effective`；partial 项按范围比较 |
| 去重表述过严 | 改为“同一事实可支持多项判断；同一项收益只计一次”，并写入记录 |
| 未分配卡位只进泛用 | 泛用只认显式判断；其余列 `unclassified_slots`，不删不改 |
| P4 需拆纯重命名与改名分组 | 拆成 P4a（保留全部名称引用与同名分组）与 P4b（改变分组） |
| P5 是证据题不是权重题 | 改为三种处理情形（必需未核实／非必需／与阶段无关） |
| P6 需明确替换对象与备选/共同必需 | 要求说明替换对象或接受 41 张；区分两种关系 |
| P8 可能已由硬要求判不满足 | 改为硬要求题，选项含“直接判不满足” |
| 权重层级混淆 | 政策分层写清：`function_weights` 为功能相对权重、`weights` 为评分项相对权重、`total.weights_effective` 为归一后实际权重；`metrics` 与 `pass` 同时存在时两者都必须通过 |

## 7 测试与验证

- 新增 24 项：阶段化供给比较、无目标不算满分、半声明目标给区间、未声明范围保持 unknown、必需项不可删、改名不变、限制跨区与未验证、接续计一次并记录可选用途、重复位声明、泛用不自动给分、Side 三态、deferred 与 NA 区分、总分只由 items 与权重决定、评分项权重改变区间、完整记录无区间、比较把 partial 记为 unresolved、门槛四项绑定、结构未接受、deferred 范围、政策校验、外来记录拒绝、无执行依赖。
- 批量回执：`python -X utf8 .cache/construction-quality-20261102/run_checks.py` → **189 项通过，0 失败／错误／跳过**，24.446 秒，Python 3.12.1、Windows-11-10.0.26200。见[回执](2026-11-02-construction-quality-tests.json)。
- 未纳入的既有失败仍单列、未宣称通过：`test_construction_logic`／`model`／`cli` 因夹具 `BuildAssets` 缺 `receipt`；`test_autonomous_construction` 一项仍断言拆分前状态名。

## 8 剩余事项

1. Q1–Q10 仍需你判断或声明；尤其 Q1 目标值与 Q2 功能权重决定标尺。
2. 生产政策未写入；实际运行仍返回 `quality_policy_unconfigured`。
3. 真实 2207 参考与候选未用该评价器重算（需时期卡库与关系上下文）。
4. 泛用范围、Side 换备、密度基准尚无声明；占位效率仍只作证据。
5. 构筑与 CB 的分工、CB 失败原因分类仍是设计（C18），未接线；训练与 CB 继续暂停。
6. 政策修订路径缺失：当前在一轮绑定构筑中变更政策会显式报错以保持比较口径，但还没有“保留候选与进度、作废旧通关、按新政策重评”的入口；这是评审 C18 的后半段，未完成。
