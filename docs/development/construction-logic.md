# 构筑逻辑与非 LLM 入口

2026-10-24；独立新增工程实现，基线为远端 `codex/phase-1-cpu-foundation` 的 `6549717`。本次不承接原生崩溃/缓冲区修复、导出或预算工作。

## 三阶段

1. **构筑逻辑**：先表达无具体卡 ID 的轻量图。节点是效果及信息标签；连接件独立，用 `ns`、`ss`、`送墓时发动` 等宽泛描述。分支、合流、替代路径可以直接表示，合流不自动解释为精密 AND 条件。图不执行卡效，也不解析条件语言。
2. **主题主轴筛选**：仅狭义主题执行。根据有来源的字段 `setcode` 或种族 `race_any` 找主轴候选；混轴各自保留明确最低张数。保留通用/辅助卡候选池，不把整副卡组硬过滤成纯轴。广义主题从第一阶段直接到第三阶段。歧义或低置信只保留第一阶段，等待澄清。
3. **卡文填卡与核验**：复用现有候选生成、数量约束、目标/优化评分、卡表合法性、支持范围内的目标核验接口。按当前完整卡文审核具体节点绑定。粗逻辑、词命中、文本摘要和合法牌表都不能替代合法 CB。

珠泪、植物、神碑、堆墓、除外只是默认词典例子。词典可以扩展；未知裸名保留未决，未见过的“X主题／字段／族”显式词槽可识别为狭义，但不会捏造该主题的真实字段代码。

## 数据和修改

`construction_logic.py` 提供 `LogicTag / LogicMetadata / LogicNode / LogicConnector / ConstructionLogic`。标签身份只有 `dimension + value`；来源、层次、说明在独立元数据中。单标签不含 `·`，只有联合展示用 `·`。旧 `BuildTask` v1–4 及其注释编码保持原接口。

`ConstructionSession` 绑定原始自然语言目标和完整 `BuildTask` 摘要。`submit_logic` 与 `revise_logic` 记录父版本、修订号、角色、原因和反馈；可以替换整个图。需求、填卡、决斗和各模型反馈用 `record_feedback` 输入。变更用户目标须显式建立新的请求/会话，不能借优化修改旧任务。`to_dict()` 可保存完整目标、图、阶段记录和反馈。

`logic_cycle` 调用已有目标、优化角色的图提议提供者；`construction_cycle` 将每个角色的阶段 1/2/3 串成 **目标→优化**，下一次调用继续循环并承接反馈。每次填卡失败都留下未满足项。新图未通过时，返回的旧候选携带原图和原验证范围，不能用它证明新图。

本变更**没有新增模型，也没有训练图生成/图绑定权重**。图提议者和具体卡绑定者是可注入接口；缺少时返回 `graph_provider_unavailable / binding_provider_unavailable`，不会用规则图模板伪装模型已学会。示例 JSON 是明示工程示意。两个已有 `BuildRanker` 通过旧 `BuildEncoder.batch` 复用；没有提供模型时仅采用标记 `engineering_order_untrained` 的候选次序。

## 入口分类器

`build_intent.py` 的 `classify_build_intent` 用可扩领域词典、词边界、显式词槽、否定作用域、主轴/外挂角色及组合/替代意图特征分类。它是非 LLM、未训练的工程文本分类器；置信为未校准的路由分，不是统计准确率。只靠某主题词出现不会直接决定路由。

| 请求 | 路由 |
| --- | --- |
| 植物族堆墓 | 1→2→3 |
| 不要珠泪和神碑，只要堆墓 | 1→3 |
| 神碑只作外挂，以堆墓为目标 | 1→3 |
| 植物族或者龙族堆墓 | 1，待澄清 |
| 星河织梦主题 | 1→2→3；第二步需要有来源的主题事实 |
| 未收录的裸名称 | 1，待澄清或扩展词典 |

入口只判断构筑范围，不把自然语言全部编译成数量/排除约束；具体硬要求仍须显式保留在原 `BuildTask`。复杂省略、双重否定、跨句指代等自然语言泛化未完成校准/训练；需要继续扩词典和保留反例，而非宣称任意表述均已理解。

词典 JSON 形状为 `{"terms":[{"canonical":"星河织梦","kind":"theme","aliases":["星织"]}]}`。`kind` 支持 `theme / field / race / mechanism`。CLI 的 `--lexicon` 在默认词典上扩展，别名冲突拒绝；Python 也可用 `DEFAULT_LEXICON.extended(...)`。

## 第三阶段的证据边界

`FillProposal` 单独保存具体三部分牌表、节点→卡绑定、所选连接路径，并绑定任务/图摘要。卡数量仍由 `DeckParts` 和现有校验器处理。

`NodeTextReview` 明确为 `satisfied / unsatisfied / unknown`，须覆盖节点标签及绑定卡，给出来源、解释、当前卡文摘要和实际摘录。评审者收到完整公开卡文和静态属性；系统核对摘要、摘录与来源，但**不声称因此形式化理解卡效**。没有评审者或评审未知时不进入真实目标核验；明确不满足时拒绝，并将问题反馈给后续构筑逻辑修订。

回退绑定任务、图版本、当前意图和主题主轴约束；主轴最低数量变化不能借旧缓存通过。相同节点/卡集合的旧评审被明确否定时缓存失效，卡集合顺序无关。缓存/返回值深复制，防止调用方误改后续证据。

默认生产适配 `existing_goal_verifier` 委托 `build_pipeline.verify_goal`。它只验证旧接口支持的具体目标：通常召唤、限定同调/超量、schema4 约束及组合目标。资源缺失或未支持时如实未验；不修改原生绑定，也不扩大其验证范围。

- `list_constraints_verified_logic_unproven`：具体卡表约束通过，效果执行未证。
- `task_goal_verified_logic_unproven`：既有具体目标核验通过，任意图边仍未证。
- `graph_execution_verified` 固定为 `false`；本次没有任意构筑逻辑→完整合法 CB 的通用证明器。

## CPU 入口

在隔离工作区使用已安装 Python，不安装依赖：

```bash
cd /workspace/YGO-Kito-construction
PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m ygo_kito construction-plan \
  --request '不要珠泪，只要堆墓' \
  --logic configs/construction-logic-example-v1.json
```

该命令不加载 Torch、不访问卡库、不执行引擎。图结构通过不代表能填卡。

`construction-fill-check` 接受 `--request --task --logic --proposal`，可提供 `--scopes --reviews --lexicon --root`。默认不会执行引擎；显式 `--verify-existing-goal` 才调用现有支持接口。CLI 返回 JSON 中的 `status / unmet / graph_execution_verified` 必须一起判断，退出 0 只表示请求已正常处理。

工程测试使用合成卡库和明确标记的评审/验证夹具，真实运行现有卡表校验和两个独立评分器前向。已有纯计数目标接口实际运行且不声称效果执行。正常路线核验适配的委托关系用 mock 验证；本轮未执行原生引擎、付费训练、外部 API 或任意故障注入。复现命令与完成/未完成清单见[本轮报告](../reports/2026-10-24-construction-logic.md)。
