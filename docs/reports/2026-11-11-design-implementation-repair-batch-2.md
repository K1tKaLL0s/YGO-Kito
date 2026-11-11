# 设计实现修复第二批

2026-11-11，Asia/Hong_Kong。用户重启电脑后明确“继续修复”。本批沿唯一完整检出实施，由主进程执行，没有子代理。继续应用preserve-intent-and-execute和anti-overengineering，依据[原逐包方案](../plans/2026-11-10-design-implementation-repair-plan.md)、[原执行书](../plans/2026-11-10-design-implementation-repair-execution.md)和[R1补充执行书](../plans/2026-11-11-design-implementation-repair-r1-execution.md)。

## 实际结果与开放边界

本批修复剩余五类卡文的通用投影和默认消费者，并补齐固定数量翻开选择的同类处理。当前九模块按测试ID去重为271项：270通过、1项空墓联合条件反例失败，0错误/跳过；另两个R3/R5反例分别失败。因此当前共三项明确开放的缺陷回归，R0—R11没有全部完成。

R1/R2的新确认联合状态条件缺口是：必需先送墓、没有清空墓地的配置，随后要求空墓发动，现程序仍放行。不能以本批已识别空墓条件宣布该联合检查也已修复。R3真实续算和R5参考独立性等包仍开放。

| 对象/机制 | 已接入的生产行为与证据 |
| --- | --- |
| 旧式次数和流星龙 | 效果开头“1回合1次”按该实体/该效果记录；计数池随实际副本数扩展，独立于实体支付库存。破坏效果响应、攻击宣言、按被引用效果除外后的结束阶段回场保留时点和编号；后者需前置除外效果支持。无效后的破坏作用于响应卡，不虚构自己的当前对象。翻开/返回只是按调整数决定攻击许可的处理，不产生独立返回收益；不指定实际随机命中。 |
| 阿拉弥赛亚之仪 | 空场条件保留为发动前状态；按明示规格生成Token，不要求牌表投入Token。可选放置保留独立空场条件并检查实际同名搭档库存。其整回合发动限制区别手牌/墓地效果、通常召唤后的场上效果和有既有关系支持的特殊召唤入口，未将限制一概删除。 |
| 武神-目一箇 | 完整支付进入同一cost记录；“其他的”排除发动的同一实体，允许同名另一副本。“和那只怪兽卡名不同”绑定对应支付，按有限支付名字分支复用现有整数分配。场上的发动源在这些非场上支付/接收处理中保留，不能再同时占手牌或墓地位置。去掉实体集合不相交的虚构回收边。两个选项及公共选择包装均可被现有消费者完整消费。 |
| 金满而谦虚之壶及同类翻开选择 | 3/6支付绑定翻开3/6、加入1、余下2/5按选定顺序回底；除外数量的引用不再投影第二次除外。翻开、选取、回底是同一次完整处理，只计实际加入手牌的功能，不能当作指定卡检索。伤害减半是修正，不是造成伤害。固定翻开3、选1、余下回卡组使用同一处理结构，也不产生独立翻开/回卡组收益。 |
| 次元吸引者 | 空墓条件在支付前检查的语义保留，自身从手牌送墓为成本；全局去向替代成为持续到下一回合结束的规则功能，不虚构一张立即被除外的卡。共享限制消费区分后续送墓功能/严格送墓成本、无关破坏/解放及本效果自身先支付；强制在替代后送墓的联合用途失败，独立可选用途可安排在替代前。空墓本身与其他必需处理的联合约束仍见上方开放反例。 |

上述“支持”是静态配置的用途/配套结论，不是当前实战状态或真实引擎见证。本批未使用全真quality_evidence覆盖，也没有改变评分公式。

## 文件与版本

六个生产文件：`src/ygo_kito/effect_count_limits.py`、`effect_records.py`、`effect_blocks.py`、`construction_inventory.py`、`construction_relations.py`、`construction_layer_flow.py`。三个测试文件：`tests/test_construction_text_completion.py`、`test_construction_static_entries.py`、`test_construction_relations.py`。

关键接口为`ResourcePool.count_inventory`（按副本计算次数容量，不占实体支付库存）、`activation_state_conditions`（已解析的状态条件）、`generation`（明示Token规格）、`different_name_from_cost`（支付指代）、`processing_role/selection_group/quantity_binding`（同一次翻开处理），以及`grave_destination_replace`（全局去向替代）。这些继续走现有记录、共享分配和唯一评价器；没有第二事实库、求解器或评分器。状态条件字段已经存在，但联合约束消费尚未闭合。

规范化升为`construction-function-normalization-v23`，字典修订为`public-text-completion-20261111-b9`。保留log2、P/V1/V2/S、Main E1/0.9、Extra 1/0.8、实际N、主要+100%/次要+50%、Side方向和0.8参考比例。旧评价由已有版本校验标stale并重新评价，原成果不覆盖。没有测试旧权重推理兼容性，未动权重和课程指针。

## 验证证据

证据目录为`.cache/design-implementation-repair-20261111-r1`。首轮304次测试执行出现一个旧字典样本的重复计数池异常；已修复，保留`verification.log`。`verification-final.log`及`verification-summary-final.json`记录随后304次执行通过、0失败/错误/跳过，约57.9秒，`torch_loaded=false`。这些早期次数包含被其他测试模块导入的重复测试类，不能当作304个不同方法；此组在新增空墓联合反例前完成。

随后固定数量翻开选择泛化与同义限制修正的34次专项复验通过，见`excavation-verification.log`；支付实体修正的14次通过见`processing-verification-3.log`，早期失败日志保留。组间有重复，不能将数量简单相加。当前九模块最后一次共308次执行（约57.4秒），来自271个不同方法；按日志测试ID去重为270通过、1失败，37次重复执行的结果全部一致，0错误/跳过、`torch_loaded=false`。原始结果见`verification-current.log`、`verification-summary-current.json`，去重账目见`verification-unique-summary.json`。临时验证脚本已加入按ID去重，后续直接重跑会包含真实失败，不自动排除开放方法。

三项开放反例均明确执行并失败，见`open-regressions.log`，没有skip或expectedFailure：

- `tests.test_construction_static_entries.StaticEntryTests.test_absence_condition_cannot_follow_uncleared_required_grave_production`：先必需送墓、再空墓发动，无清空手段，仍无失败硬条件。
- `tests.test_construction_calculation_resume.CalculationResumeTests.test_f04_all_129_single_supplier_allocations_are_enumerated`：预算100000仍被128截断。
- `tests.test_construction_workflow.WorkflowTests.test_f08_reference_is_independent_of_optional_candidate_graph`：独立合法参考仍受候选可选图影响。

九个本批程序文件的AST、末尾换行、逐行空白检查见`artifact-validation.json`；实际差异使用`git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check -- <本批文件>`，不把工作树其他文件的CRLF当作本批待修故障。未运行完整CI、权重推理、训练、CB/native、GPU/PC实测或完整构筑。

同一14条本地卡文只读投影已更新为`r1-card-projections.json`及`projection-summary-final.jsonl`。原始card_id只作来源和实体身份，不按卡名/ID打补丁。已知次数的无效退款政策仍保留原始未知；静态没有执行无效事件，不据此阻断已知印刷次数。不能将这些原始记录字段和程序尚未消费的联合状态条件混为一类。

## 设计与官方核对

当前[流星龙卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=9117&ope=2&request_locale=ja)明确区分各效果次数、破坏效果响应、攻击宣言除外和对应结束阶段回场。项目按这些时点和对象关系消费，不把回场投影为无条件立即召唤。

[阿拉弥赛亚之仪官方补足说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=16748&ope=4&request_locale=ja)保留无Token发动条件、可选放置及整回合场上怪兽效果限制。[武神-目一箇官方卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=15973&ope=2&request_locale=ja)区分“其他卡”支付和两个选项中与支付怪兽不同卡名的选择。

[金满而谦虚之壶官方补足说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=15756&ope=4&request_locale=ja)列明3/6成本、对应翻开数量、选1与余下回底，并区分整回合抽卡限制和处理后伤害减半。[次元吸引者官方补足说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=14740&ope=4&request_locale=ja)列明空墓发动条件、手牌送墓成本及到下一回合结束的全局去向替代。本批只核对相关卡文/裁定，不以当前禁限覆盖历史时期任务。

## 原数据与接续

仍在`codex/optimization-20261031`、HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`，未commit/push/merge，未创建工作树。混杂修改、删除、未跟踪成果保持。run-007未恢复，kernel409572012字节、session408615095字节，mtime与原停止点一致；没有读取或重新哈希大型档案。暂停文件、权重、原卡库、参考与配置未写入。

最近一次额度读取为周usedPercent91（当次剩余9%），1张可用卡，未使用；将来使用前必须再次读取实时值。原20%停止/禁用重置卡条件已被用户最新≤1%授权更新，不购买、不换模型。

本批形成安全交接边界；后续先修空状态联合约束，再做R3、R5及其他未完成包。用户已授权必要时自主新开同模型主任务并立即开始；完整状态见[第二批独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-2-continuation.md)。当前没有需要用户重新补资料或决定模型的待答问题。训练、CB/native、完整构筑和run-007继续暂停。
