# 构筑逻辑与非 LLM 入口

2026-10-24；独立新增工程实现，基线为远端 `codex/phase-1-cpu-foundation` 的 `6549717`。首次框架提交 `5d4336b` 后继续补齐可训练/实际调用实现，见[当前增量报告](../reports/2026-10-24-construction-trainable.md)。本次不承接原生崩溃/缓冲区修复、导出或预算工作。

## 三阶段

1. **构筑逻辑**：先表达无具体卡 ID 的轻量图。节点是效果及信息标签；连接件独立，用 `ns`、`ss`、`送墓时发动` 等宽泛描述。分支、合流、替代路径可以直接表示，合流不自动解释为精密 AND 条件。图不执行卡效，也不解析条件语言。
2. **主题主轴筛选**：仅狭义主题执行。根据有来源的字段 `setcode` 或种族 `race_any` 找主轴候选；混轴各自保留明确最低张数。保留通用/辅助卡候选池，不把整副卡组硬过滤成纯轴。广义主题从第一阶段直接到第三阶段。歧义或低置信只保留第一阶段，等待澄清。
3. **卡文填卡与核验**：复用现有候选生成、数量约束、目标/优化评分、卡表合法性、支持范围内的目标核验接口。按当前完整卡文审核具体节点绑定。粗逻辑、词命中、文本摘要和合法牌表都不能替代合法 CB。

珠泪、植物、神碑、堆墓、除外只是默认词典例子。词典可以扩展；未知裸名保留未决，未见过的“X主题／字段／族”显式词槽可识别为狭义，但不会捏造该主题的真实字段代码。

## 数据和修改

`construction_logic.py` 提供 `LogicTag / LogicMetadata / LogicNode / LogicConnector / ConstructionLogic`。标签身份只有 `dimension + value`；来源、层次、说明在独立元数据中。单标签不含 `·`，只有联合展示用 `·`。旧 `BuildTask` v1–4 及其注释编码保持原接口。

`ConstructionSession` 绑定原始自然语言目标和完整 `BuildTask` 摘要。`submit_logic` 与 `revise_logic` 记录父版本、修订号、角色、原因和反馈；可以替换整个图。需求、填卡、决斗和各模型反馈用 `record_feedback` 输入。变更用户目标须显式建立新的请求/会话，不能借优化修改旧任务。`to_dict()` 可保存完整目标、图、阶段记录和反馈。

`logic_cycle` 调用已有目标、优化角色的图提议提供者；`construction_cycle` 将每个角色的阶段 1/2/3 串成 **目标→优化**，下一次调用继续循环并承接反馈。每次填卡失败都留下未满足项。新图未通过时，返回的旧候选携带原图和原验证范围，不能用它证明新图。

现在提供具体实现：`LogicCodec` 无卡 ID 编码/解码图，`rule_graph_candidates` 按明确请求的基本标签枚举有界粗图，`LogicModelAdapter` 用现有目标/优化 **同一组 BuildRanker 对象和优化器**评分选择。图特征进入已有 numeric/kind/position 投影，卡 ID 槽保持 0，没有把标签索引冒充旧卡嵌入，也没有另造大网络。`train_preference` 真实执行图偏好损失、反向传播和优化；独立图 checkpoint 绑定特征版本、词典、原任务和旧卡词表，可保存模型/Adam状态并连续恢复。原四模型 checkpoint 不被静默迁移。

候选由程序枚举、模型选择；不声称神经网络自由生成任意图。图词表中的标签作为本次明确请求的必要特征钉住；运行时改词表拒绝，绑定器会在可达分支并集中覆盖这些标签，但标签覆盖仍不证明效果实际执行。示例 JSON 仍是工程示意，不是训练成果。

`CatalogBindingAdapter` 是实际目录绑定者：读取现有候选牌表的卡文/属性，对种族/字段做真实公开属性匹配，按来源绑定审核记录支持功能标签，选择可达路径并给出节点→卡绑定。功能关键词只召回，未知卡效仍返回 `unknown`。不存在虚构的自动卡文理解器。

`ConstructionController` 直接组合上述模型适配和绑定器，真实调用既有 `CoordinatorTrainer.advice`。有已核验候选和真实源 ledger 时，经旧 `Coordinator` 的 `handoff.submit` 及 `route_with_model` 写入托付、取得规则权威路由并记录实际网络建议。无托付时只运行预构筑聚合上下文的建议，不假装已完成账本/决斗循环。

## 入口分类器

`intent_model.py` 的 `LinearIntentClassifier` 是实际可训练的 CPU 线性 softmax 分类器：字符 ngram、英文词及词典/作用域辅助特征经归一化后学习权重；`fit / predict / save / load` 均已实现。预测输出实际模型分数、margin、词汇覆盖和模型摘要，置信/差距/覆盖不足拒判；无模型或未训练一律 `ambiguous`。新 CLI 和会话都走此模型路径。旧 `build_intent.py` 规则判别仅作辅助实体/作用域特征及兼容函数，其固定规则置信不进入模型预测。

小合成拟合仅检验实现，未证明生产语义泛化或置信校准。下表描述路由意图；只有实际模型接受该类别且主题事实已明确时才进入相应阶段，不能当作任意表述的能力成绩。

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

该命令不加载 Torch、不访问卡库、不执行引擎。未提供 `--intent-model` 时会拒判并只保留第一阶段；图结构通过不代表能填卡。可显式拟合工程样本并加载（输出须选未存在路径）：

```bash
PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m ygo_kito construction-intent-fit \
  --input configs/construction-intent-engineering-examples-v1.json \
  --output /tmp/ygo-intent-engineering.json --epochs 180 --learning-rate 3
PYTHONPATH=src /workspace/YGO-Kito/.venv/bin/python -m ygo_kito construction-plan \
  --request '我要堆墓' --intent-model /tmp/ygo-intent-engineering.json
```

`construction-fill-check` 接受 `--request --task --logic --proposal`，可提供 `--intent-model --scopes --reviews --lexicon --root`。默认不会执行引擎；显式 `--verify-existing-goal` 才调用现有支持接口。CLI 返回 JSON 中的 `status / unmet / graph_execution_verified` 必须一起判断，退出 0 只表示请求已正常处理。

`construction-run --request TEXT --task TASK --intent-model MODEL --required-tags TAGS --binding-data DATA` 执行真实图选择和绑定；TAGS是基本标签数组，不是用户手写整张图。`--logic-checkpoint`可加载图偏好训练权重；不提供则两个现有小模型随机初始化、图训练计数为0。`--base`可给已有合法牌表，用旧有界编辑路径；无base的schema4从零生成仍需要旧模块的可选SciPy依赖。绑定数据是 `CatalogBindingAdapter.to_dict()` 格式的事实映射、来源绑定审核和召回词。显式 `--verify-existing-goal --candidate-id ID --state-root DIR` 才启用具体目标核验及既有统筹账本托付。

工程测试使用明示合成卡库/审核数据，实际运行分类拟合、两模型图偏好更新/恢复、图选择、目录绑定、旧填卡评分、计数目标接口及既有统筹网络/SQLite账本，整链没有图/绑定 provider 夹具。本轮未执行原生引擎、正式训练、外部 API 或任意故障注入。复现命令与完成/未完成清单见[当前报告](../reports/2026-10-24-construction-trainable.md)；[首次框架报告](../reports/2026-10-24-construction-logic.md)保留历史范围。
