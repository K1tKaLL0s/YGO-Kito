# 空状态联合消费修复

2026-11-11，Asia/Hong_Kong。主进程在原完整检出继续，无子代理、新工作树、提交或安装。依据[状态专项执行书](../plans/2026-11-11-design-implementation-repair-state-execution.md)，原空墓联合反例已转绿。当前十个明确安全静态模块按完整测试ID去重292项全部通过，0失败/错误/跳过、`torch_loaded=false`。R3、R5及后续包尚未完成，完整CI未执行，训练/推理/CB/native/完整构筑/run-007仍暂停。

## 接入的实际行为

`normalize_function_uses`将已有`activation_state_conditions`、操作自身状态条件及完整移动选择器传给同一`_bind_mandatory_impacts`。required/all联合组及单一完整处理的必要前置使用已有before关系，枚举相容的静态用途安排，再由现有`multifactor.conditions.solve_requirements`分配实际副本；没有新增求解器、事实库或分数。

共享分支保存每个物理槽的可能区域、实际移动后的唯一去向及发动源绑定。未给当前盘面时，空状态排除该区域的可能起点；先前确定送墓后不能再次凭空选为空墓。条件在自身支付之前；后置可选放置在已执行的前置处理之后。一个清除不能清掉两批实体，两张可以由两次各一张的清除处理；同一张真实返回后可继续移动，不增加副本。不同函数对同一处理的投影合并为同一处理事件。

Token以明示规格从未生成状态进入场上，离场后不能成为可回收的牌表库存。通常/速攻等非持续魔法陷阱的发动源在处理后产生规则离场，持续/装备/场地类不套用该规则。已识别去向替代只改变启用后的未来去向，不清除原墓地卡，也不改变原有严格送墓成本/送墓功能的restriction判定。规则离场不新增计分收益。

[KONAMI官方问答fid12929](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=12929&ope=5&request_locale=ja)明确区分通常魔法的效果送墓与随后自身规则送墓；本次按该通用规则接入，不按卡名/ID打补丁，原始ID只作实体和来源身份。既有次元吸引者的替代范围继续沿第二批已核官方口径。

## 文件和合同

四个程序文件为`src/ygo_kito/construction_layer_flow.py`、`src/ygo_kito/multifactor/conditions.py`、`tests/test_construction_static_entries.py`、`tests/test_multifactor_conditions.py`。原有tracked/untracked状态保留，未恢复删除文件或清理既有成果。

共享分配器新增可选状态合同：`Resource.initial_zones`，`Condition.state_origins/state_destination/state_absent/state_binding/state_exclude_binding/state_destination_replace`；默认值保留原静态分配行为。JSON转换严格处理新增tuple字段，分支隔离和不同副本测试通过。数据仍由同一事实、库存和共享分配流进入唯一质量评价器。规范化为`construction-function-normalization-v24`，字典仍b9；原log2、P/V1/V2/S、Main/Extra折算、主要/次要加权、Side方向和0.8参考比例不变。旧Evaluation按现有规范化绑定失效，旧结果不覆盖。

## 验证和后续

证据目录`.cache/design-implementation-repair-20261111-state`。`verification.log`为初轮290项，14个诊断容器兼容错误已定点修复；`verification-final.log`记录随后290项全通过。再补去向替代与规则离场正反例后，`verification-current.log`及`verification-summary-current.json`记录当前292项全通过，约58.4秒。该脚本先按完整ID去重，不将导入测试类的重复执行或分组复验相加。

新增专项涵盖原空墓失败、无指定顺序、条件后自身支付、清空数量/选择器、共享清除、拆分清除、单副本返回、Token、通常/持续魔法区别、同一效果的后置条件及去向替代。共享条件原测试和新增守恒/JSON/分支隔离测试均在292项中。

AST/空白检查覆盖这四个实际程序文件，Git差异按项目CRLF口径检查。没有修改权重、课程指针、暂停文件、原卡库/参考或run-007，没有加载训练/推理/native。

本批最后明确复验的R3/F04、R5/F08仍为两个普通失败，0错误/跳过、未加载Torch；见同证据目录`open-regressions.log/json`。AST/行尾最后复验仍零错误。所有本主进程测试command sessions均已结束。

R3仍须使共享分配、状态安排及其实体分配预算真正续接，保留随机身份分支的影响，不以有利随机命中或避开替代确定结论；R3关系与质量阶段的128截断/重算也未在本批修改。R5参考仍须独立于候选可选图。下一步按[真实续算执行书](../plans/2026-11-11-design-implementation-repair-resume-execution.md)和[完整独立接续](../handoffs/2026-11-11-design-implementation-repair-batch-3-continuation.md)实施，不能将本专项通过写成全部软件完成或完整构筑通过。
