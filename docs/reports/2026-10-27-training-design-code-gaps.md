# YGO-Kito 训练设计—源码差异复核（只读）

- 审核时间：2026-10-27 UTC。
- 固定源码基准：公开仓库 `K1tKaLL0s/YGO-Kito`，main `c1157ca5add6c29149eccf7106226b1099e63d8c`。以下行号均指该提交，不是 CloudStudio 未提交工作树。
- 范围：通过 GitHub 连接器读取真实源码、配置和现行说明；本审核没有修改仓库、操作 CloudStudio、运行引擎/训练、暂停现场进程或核验现场权重字节。
- 现场不可见项：CodeBuddy 未提交的 5 文件修复、3 报告、功能 v2 最终结果及新训练实际计数。其结果须执行任务回读，不可用本报告替代。
- 最新用户纠正优先：用户提供构筑只供独立评估合理性，不能直接作 learner deck，也不能拆成固定张数/候选池/训练答案后换名使用。执行任务已由父端要求在小局边界暂停、隔离相关学习分支；本审核未代为确认暂停完成。
- 最新流程修订：用户明确不再设预检；纠正已知设计偏差后直接真实构筑、训练，运行具体出错再修。不新增preflight、独立功能场或资格批次作为开训门槛；合法动作、预算和断点保存保留为运行约束。
- 已读取同目录 `user_requirements.md` 第1–3节及C13/C14/U27/U28原文依据：先分别训练基础，再交替协作；LoRA用于后续适配。下文CG-14据此纠正“可学习LoRA就等于本次基础训练”的错位。
- 原始用户需求的最终逐条表由并行历史矩阵提供。本报告负责“可核源码事实→最小修正→何时需要”，不把旧文档中的误解重新升级成用户要求。

## 0. 先读结论

1. **现在最直接的错误是历史环境把参考牌表当 actor**：`ScenarioCourse._construct` 的 `fixed_theme` 分支直接读 `fixed_deck`，绕过构筑模型；必须先修此语义，不可继续该分支训练。
2. **已有不读参考牌表的模型参与构筑链**：公开卡池/禁表→程序提出有界主题/任务/三分区候选→现有目标/优化网络排序→具体合法性及有界路线核验。它不是网络逐卡自回归生成，也不是完整珠泪融合/任意 CB 推理。
3. **应直接训练基模本身，不是先要求凭空已有成熟基模**：用户已认可分别起步→基础形成后协作、LoRA后续适配。现入口base各1次工程更新后完全冻结、只学LoRA，不能叫正式基础模型训练；须接真实base阶段，而不是无限等待成熟权重。LoRA-only虽可产生更新，但不满足此处设计职责。
4. **普通 scenario course 自动学习的主要是决斗 LoRA**。另外三角色有真实反馈更新 API，但脚本/普通 run 没有替宿主自动提供标签、调度更新。不能把调用四个网络等同“四个网络均已学习”。
5. **20 机时是这次整个 CloudStudio 使用的新硬上限，不是旧 100 GPU 实例小时计划的余量**。现有项目台账不核算 0.5 机时/墙钟小时的全部实例使用，也不会自动停云实例。先获得参考隔离、真实、可恢复的进展；不能保证三期全部达标，更不能降低场数或阈值来报成功。
6. 最小修复优先。不要先重跑验收、独立计时、preflight/功能场/资格批次，或增加成熟模型/完整文本理解/PC GUI/外部LLM/GPU等前置。改正已知设计后直接真实自主构筑和base训练；在运行中记录来源、合法性、更新和保存证据，具体出错再针对修复。

## 1. 优先级的含义

| 标记 | 用法 |
| --- | --- |
| **N：本次恢复学习前必须处理** | 修正当前参考使用违规、避免带入其派生学习状态、明确本次总预算及安全保存停止边界；不是“所有设计都完工”门槛。 |
| **L：相应学习职责接线** | 为兑现该角色实际训练而补；可以分阶段交付。某角色尚未有合法标签时如实报告，不伪造、不阻断其他已授权的真实进展。 |
| **A：完整能力/终验前必须处理** | 固定正式评测口径并取得对应证据；不把达标验收倒置成开始学习的无限前置。 |
| **D：可延后** | 额外架构扩容、广泛任意CB、PC界面等改进。用户要求的base训练本身不是可省略项；不要求先取得成熟权重才开始训练它。 |

## 2. 参考牌表与 learner deck：确切路径和最小修正

### CG-01 / N：历史 fixed_theme 实际等于固定 learner deck

**现有事实**

- `src/ygo_kito/scenario_course.py:37–48`：历史环境只能 `fixed_theme`，且非 autonomous 必须有非空 `fixed_deck`。
- `scenario_course.py:238–244`：直接 `self.deck = DeckParts.from_dict(self.config["fixed_deck"])`，仅校验牌表，结果明确 `cb_verified:false`。
- `scenario_course.py:275–292`：`MatchParticipant("actor", self.deck)`，参考表成为实际 learner 对局牌表。
- `configs/training-scenarios-v1.json` 的两个历史期仍为 `construction_mode:existing_tearlaments_reference` 和 `main_slot`。
- `src/ygo_kito/training_scenarios.py:128–140` 把上述旧解释作为硬性校验；只改一份 host JSON 不够。
- 2610 路径不同：`scenario_course.py:245–270` 才调用 kernel 选择任务、生成构筑、检查 CB 标记。

[直接装入与 actor 绑定](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/scenario_course.py#L238-L292)
；[旧配置校验](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/training_scenarios.py#L128-L140)

**最小修正**

- 历史期保留“珠泪主题”，但 learner deck 改为构筑模型链输出；不把历史期简单改成不限制主题的 2610 autonomous。
- 取消历史 `fixed_deck` 作为训练输入；参考表只进入独立评审配置/目录，不进 learner host/kernel、初始化任务的答案、训练反馈标签或 actor profile。
- `_construct` 共用构筑链，首次 `base=None`；后续 base 只可用本干净分支自行生成的前一构筑。
- 更新 `training_scenarios.py` 与 JSON 的旧 construction mode/main-slot 含义，以及 CODEBUDDY/runner 说明。保留旧历史记录但明确被最新纠正覆盖。
- 不从参考表推导 `requirements`、主/额外/副固定卡张数、仅由参考卡组成的 pool、预写路线或偏好标签。允许输入的是实际时期卡池/禁表、用户明确主题及非答案式约束。

**直接训练的运行证据与可后做的回归，不是开训门槛**

- 参考文件不提供给 learner 配置、移出其输入范围时，仍能生成并记录实际 main/extra/side。
- 同源码、源权重、合法资产和RNG下更换独立参考文件的输出不变性，可留为后续回归；不得为此再开预检/独立批次或等待其通过才训练。
- 记录 learner 牌表的来源任务、模型摘要、候选/选择及构筑收据；不能以“牌表与参考不同”单独证明未读参考。

### CG-02 / N：已有构筑链可复用，但历史固定主题没有公开过滤参数

**可调用接口**

```python
proposals = models.kernel.propose_tasks()
selection = models.kernel.select_task(proposals, rank=...)
result = models.kernel.run_selected(selection, base=None)
# 实际输出 result["best"]["deck"] = {"main": [...], "extra": [...], "side": [...]}
```

- `src/ygo_kito/course_models.py:86–101` 建立两个独立 BuildTrainer 模型、全局课程词表和 kernel。
- `src/ygo_kito/autonomous_construction.py:35–49` 从宿主供给的 available IDs 排除缺卡、期外、非 OCG/Token 和禁卡；宿主另负责真实脚本可用性。
- `autonomous_construction.py:228–250` 枚举实际 catalog 的 setcode/种族事实。
- `autonomous_construction.py:280–329` 从基础任务继承目标/requirements/尺寸，再组成最多 128 卡的局部任务池。
- `autonomous_construction.py:344–420` 程序提出候选，目标模型评分选择；全部分数不区分时返回 unresolved，不用规则主题冒充模型选择。
- `autonomous_construction.py:453–469` 接图选择、卡绑定、具体填卡、现有验证器。
- `src/ygo_kito/build_semantics.py:107–174` 的 MILP 可从 base=None 建 main/extra/side 数量候选，执行别名合计禁限、尺寸与语义约束。
- `src/ygo_kito/construction_fill.py:254–308` 现有角色网络对候选评分；目标从空表开始，优化角色接此前自产构筑做合法编辑。

[完整 kernel](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/autonomous_construction.py)
；[三分区候选求解](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/build_semantics.py#L107-L174)
；[模型填卡排序](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/construction_fill.py#L254-L308)

**最小修正**

给 kernel 增加显式、纳入 binding 的允许主题/ThemeScope 约束，历史环境在候选排名截断前筛到真实珠泪主题事实；2610仍让模型在可用主题中自主选择。不要在 `propose_tasks` 返回后任意改候选内容或伪造 seal。不要靠“只要求主题卡1张”声称已满足合理主题构筑：主题强度/构筑合理性需独立评估；最低主题约束不擅自从参考表反推。

候选生成仍应明确标注 program proposal / model selection，而不是“模型已学会自主生成全部卡效”。

### CG-03 / N：已用参考表学习分支的状态隔离

**源码事实**

- `CourseModels` 保存四角色、适配器/优化器/RNG/内核状态：`course_models.py:145–191`。
- `scenario_course.py:390–404` 绑定配置、对手和完整 source_map；已有在途标记或配置变化拒绝直接续跑。
- `group_initialization.py:291–330` 的新任务初始化只复制参数、不继承优化器/RNG/账本，但 `effective` 会物化源 LoRA。若源参数已经从参考 learner 对局学习，换新账本并不能洗掉它。

[源参数迁移边界](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/group_initialization.py#L291-L330)

**最小处理**

1. 等现场确认暂停及最新完整边界；不删除 in-flight/索引，不为追求干净重写旧计数。
2. 旧参考学习分支、数据/标签、LoRA/优化器及派生 effective 权重整体保留为隔离证据，不接回新训练。
3. 新 course_id/state_root，从能够证明在参考 learner 使用前的四角色源重新 initialize；不修改旧 config 后强行 resume。
4. 不因现有分支污染就宣布原工程源一定污染。须回读源摘要与训练谱系；本审核不能证明现场 fcb4a3 源何时接触过哪些数据。
5. 若无法证明有干净源，可新增显式 fresh 初始化分支复用 `CourseModels.initialize(... initialization=None)`，记录未训练起点。当前 Python API 有此路径，但 host `validate_host_spec:45` 强制 source_group，需明确新模式而不是放松旧来源校验。**无需先获得成熟权重**。
6. 独立参考评审结果不自动转入训练反馈；若将来希望用其偏好训练，需用户另明确授权，不从本次“仅独立评估”推导出来。

## 3. 四模型实际职责与学习情况

| 角色 | main 中实际执行/学习 | 差异和最小接线 | 优先级 |
| --- | --- | --- | --- |
| 目标构筑 build_goal | kernel 对主题/任务排序；共享现有 BuildRanker 对无卡ID粗图程序候选和具体牌表评分。普通 course run 没有自动更新它。 | 用已索引 train 数据接 `apply_task_preference`、`apply_construction` 或明确图偏好，保留任务/目标身份；数据不得来自参考答案。无法给合法标签时报告“仅推理”，不伪造更新。 | L；“四角色都已学习”前须实际证据，不必阻断首条干净决斗更新。 |
| 优化 build_optimizer | 具体填卡、编辑和合法换备候选排序；换备只调用 no_grad 前向。 | 接真实、独立来源的构筑/图/填卡比较监督；给已生成牌表和换备质量学习的实际记录。不能把 legal side selection 称“换备模型已训练”。 | L/A。 |
| 决斗 duel | `CourseGameAdapter`在每个完整 train 小局新采样后真实 PPO 更新 LoRA；冻结验证不更新。 | 沿用当前策略鲜采样、实际终局和索引准入；不消费失败片段/旧策略/评测轨迹。保留非零参数变化、计数和恢复边界。 | 现有可执行主进展。 |
| 统筹 coordinator | ConstructionController调用实际 MLP advice，但规则最终决定；另有显式 host logged feedback 学习 API。普通 course不自动喂监督/维护完整旧预测账本。 | 复用现有 Coordinator 的候选/forecast/result/alert谱系与规则路由，接真实聚合训练日志；无forecast标签只学route，不伪造校准胜率。 | L/A；精确统计校准可阶段化，不新增第五大模型。 |

### CG-04 / L：有更新 API，不等于正式入口已调度四角色训练

- `src/ygo_kito/course_feedback.py:118–168`：真实支持 construction、coordinator、task_preference、graph_preference；需要准确 indexed train artifact/provenance。
- `src/ygo_kito/scenario_course.py:488–521`：`apply_feedback`仅宿主 API，在干净训练边界调用并保存；不会从一场输局偷偷生成构筑缺陷标签。
- `scripts/scenario_course.py:17–63`：只有 template/preflight/pilot/run 和 partition/max-matches，无 feedback 调度配置/CLI；普通 `ScenarioCourse.run`不调用以上反馈 API。
- `src/ygo_kito/course_game_adapter.py:457–492`：自动实际更新的是 duel session。
- `src/ygo_kito/match_runner.py:404–463`：换备是现有优化网络打分，`__call__`在 no_grad 中执行，能力标志仍 false。

[反馈 API](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/course_feedback.py#L118-L168)
；[课程宿主边界](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/scenario_course.py#L488-L521)
；[真实决斗更新](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/course_game_adapter.py#L457-L492)

**最小修正**：明确每角色标签来源、训练阶段/频率、artifact准入、更新上限、保存和已消费标记；接一个受控宿主反馈调用路径。不要强制每小局四角色同时更新；也不要仅为让角色计数非零循环喂工程标签。

### CG-05 / L/A：优化“偏好”目前不是竞技质量标签

- `src/ygo_kito/semantic_training.py:9–38,80–89`：监督来自卡池计数/显式偏好；标为 `competitive_quality_labels:false`，无严格比较则拒绝制造优化标签。
- `src/ygo_kito/build_training.py:144–180` 的默认 engineering dataset 仍有印刷攻击力弱代理，不能用到正式能力解释。
- 已有成对真实比较模式可参考：`build_feedback.py:27–40,118–188`、`construction_curriculum.py:59–84,182–229`；它固定候选、种子、双方先后、驱动与分区，且单场失利不直接归因构筑。
- 但该模式硬绑定工程可见规则驱动、工程 task/source；不是当前模型策略/合格bot的通用正式监督入口。不要只换 source 字符串。

**最小修正**：以模型自产构筑为候选，明确当前冻结策略/对手/分区的实际比较来源并按原证据边界接入；同分、未完成、错版本拒绝标签。可先用合法约束/明确训练偏好取得有限进展，竞技质量泛化留独立评估；不可拿参考牌表作“better”答案。

补充C09的小轴改进边界：`build_pipeline.py:152–166`普通edit_candidates只做单张移除/替换；`ModelSideboardPolicy`的深度2换备不是主构筑成组小轴替换。后续优化阶段应增加有界成组改卡候选并复用同模型评分/目标保持/合法校验，不能把单卡编辑能力宣传为已学习组合价值；无需在第一条基础训练更新前穷尽所有小轴。

### CG-06 / L/A：course 未接原有预测—百场提示—千场强制规则

- `scenario_course.py:368–375`：每100完整训练场只写 `hundred_match_review`事件，1000场无条件重构一次；不是对“预测明显偏高”的统计判断。
- `construction_controller.py:37–51`：context 的 completed_matches=0、forecast=None、has_forecast=False，虽有真实MLP前向，不代表持续统计统筹。
- 原机制在 `coordinator.py:202–230,276–360`、`coord_contracts.py:27–83`：不可变预测scope、实结果、预声明多次观察、warning/mandatory_rebuild与不可清除谱系，已存在可复用代码。
- 默认工程统筹标签/概率锚点见 `coordinator_model.py:34–43`；`course_feedback.py:128–141`明确拒绝把合成锚点冒充host真实监督。
- 默认 LoRA配置的统筹targets未包含forecast_head（`configs/lora-engineering-v1.json`）。即使共享encoder更新会影响预测，也不能说forecast_head已直接拟合/概率已校准。

[旧课程事件](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/scenario_course.py#L368-L375)
；[已有账本](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/coordinator.py#L202-L360)

**最小修正**：保留并接原规则账本/结果范围，不能以“每100写事件、每1000无条件重构”替换原设计。先固定当前可核的工程策略并保持 calibration pending；正式统计校准及历史“接近50%”规则在终验前单独冻结，不以此无限阻塞第一批学习。

## 4. CB与卡文：能输出哪些证据，不能承诺什么

### CG-07 / A，涉及原要求的具体CB时也属L

- `autonomous_construction.py:252–278` 自动提出的是同调/超量条件路线；不是融合及任意主题combo。
- `build_contracts.py:81–108` 的非semantic goal只有 normal_summon/synchro_summon/xyz_summon。
- `build_semantics.py:189–220` 的组合目标只接受同调/超量，以真实引擎发现路线；`constraints_satisfied`仅牌表约束。
- `construction_model.py:77–121`的轻量图是程序有界提案，现有网络排序选择，不是自行推导任意卡效定理。
- `construction_fill.py:144–245`核卡文来源、逐节点绑定和既有goal verifier，但明确 `graph_execution_verified:false`、`competitive_strength_verified:false`，成功结果仍为 `task_goal_verified_logic_unproven`。
- `autonomous_construction.py:453–469` 的 `cb_verified`是某attempt的既有目标路线成功，不应扩写成整张轻量图均可执行。
- `build_model.py:47–107`喂给网络的是card identity/公开属性/约束/注释等有界编码，不是完整任意卡文语义模型；CatalogBindingAdapter公开事实或来源审阅不能替代完整效果理解。

[范围与明确未证项](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/construction_fill.py#L144-L245)
；[组合目标支持范围](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/build_semantics.py#L189-L220)

**最小修正**

把证据分为：牌表合法/主题约束、粗图与卡文来源、具体目标路线成功、整图执行、竞技质量。不得仅改布尔标记放行。“珠泪融合CB”若属于当前所需训练目标，补明确融合/效果目标与原核心真实动作证据；否则如实保留未支持，不改成参考牌表代打或将无关同调/超量路线称珠泪完整CB。

**可延后**：任意牌组/任意图的全卡效语义、完整形式化和大模型替换。不要把这些扩成开始干净有界学习的条件；但已有明确CB要求也不能被“合法三分表”悄悄取消。

### CG-16 / L：自主kernel的效果积木与广义主题没有完整接入

- 用户三步是先效果标签积木/独立连接件→仅狭义主题筛主轴→具体卡文填卡/CB。当前`autonomous_construction.py:228–250,439–460`先枚举setcode/种族主题，然后用该单一主题tag建LogicCodec，并显式赋内部narrow分类；`_SharedLogicAdapter`复用网络排序，但不会凭此自动获得效果积木语义。
- `construction_logic.py:178–225`及独立service已有broad跳过主轴的接口；scenario自主入口却只枚举setcode/race，没有广义“堆墓均/除外均”任务候选，不能宣称已覆盖广义主题自主探索。
- 最小接线：任务/图候选提供独立的效果标签集合及ns/ss/送墓时发动等粗连接件，标签来源与未知状态显式保存；不要把field/race tag或原始整段卡文塞进同一标签冒充完成。历史珠泪保留狭义主题约束；2610的广义候选应走broad路径，跳过ThemeScope主轴筛选。复用现有ConstructionSession/Controller与模型评分，不新增第五大模型。
- 直接在真实构筑中输出所选效果积木、连接、主题分支及实际填卡/路线结果，运行不支持时针对该任务修复；不以全主题预检或全卡语义完工阻断所有学习。

## 5. 三环境与正式场数：保留正确实现，修错误语义

| 环境 | 保留的范围/阶段 | 当前源码注意点 |
| --- | --- | --- |
| 2207 | 珠泪主题，截止2022-09-30；独立训练/评估，外战BO3≥60%、强参考内战接近50%，原各200外+200内BO3及95%区间。 | 去掉固定learner参考表，不去掉主题。reference-only合理性评审与冻结强对手评测分开；把用户参考表同时作对手也不能未经授权默认为允许。 |
| 2210 | 珠泪主题，截止2022-12-31；不合并2207分母/数量，同原历史验收。 | 同上。 |
| 2610 | 自主主题→模型参与构筑/具体CB→既有人机BO1→当期合法常见卡组BO3；用户原话为冻结到11.1，精确日期边界待定。 | 不把旧文档的“日本当地含当日”当已获用户确认。当前只使用已能确认合法、卡库/脚本可用集合运行；未来最终池未确认不称已冻结，也不据此让整期永远等待。缺卡逐张排除。 |

### CG-08 / 保留场数，不新增计时预检

- `training_scenarios.py:29–56`已支持此前确认慢档、当前均值null，无需独立计时预跑。直接训练自身仍记录真实耗时及单位，不用新pilot延期开训；不得根据未确认统计口径悄悄降档/减少数量。
- 每环境完整600 BO1 +400 BO3，功能检查、冻结评估和新增自对抗不抵扣。
- `scenario_course.py:214–224`按完整场计数，先BO1达600再到BO3；`scenario_course_host.py:195–205`检查最坏1800小局种子和duel LoRA容量，旧max_updates=2不足。
- `course_volume_met`保留慢档6:4比例，阶段完成不是单纯“累计1000任意格式”；中途数量应照实报告。

[场数规则](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/training_scenarios.py#L29-L56)
；[容量](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/scenario_course_host.py#L195-L205)

**不要修成更低样本**。预算结束只表示本轮未完成且可续训，不表示失败或达标；有完整容量声明不意味着要在本次20机时内一次跑完。

### CG-17 / L：历史内外对手比例课程未由当前round-robin表达

- 需求矩阵U17/C05要求前两期前段其他主题较多、珠泪内战较少，随后提高内战比例；具体比例不是用户固定常量。
- `scenario_course.py:280–285`在当前stage/purpose内按bot_id排序循环选择，没有学习进度相关权重/内外战课程调度；coverage_label主要供后续分组统计，不能称比例课程已实现。
- 最小接线是显式记录历史内外对手分组与当前课程权重、按实际训练进度推进并保存调度游标；保留旧对手防遗忘。比例未定可用清楚声明的工程初值直接运行，不把调查最优比例设为前置。2610仍按其最新两阶段安排，不恢复已废弃固定珠泪主线。

## 6. BO3和终验口径

### CG-09 / 保留运行功能边界；证据来自真实训练，不另设功能批次

- `scenario_course.py:312–323`：actor用现有优化模型挑合法换备，对手明确keep_original baseline；输者决定下局先后，actor当前策略为always_first。不是对手也在模型换备。
- `match_runner.py:159–165`：换备保持各区张数及全原始卡多重集；`record_game:228–254`只有真终局且无异常计完成，先得两胜，大场draw留pending。
- `scripts/model_match.py` / `model_match_host.py:63,214`的冻结功能入口双方keep-side，不能替代上述模型换备学习功能。
- `ModelSideboardPolicy:404–463`有界搜索默认2次换入深度、16候选；不能宣传为穷尽全部合法换备或已学会竞技换备。

**最小修正**：在真实训练中报告实际side policy、候选/改动/库存校验、输者选先后和实际先后。出错针对该错误修复续跑；不新增独立功能场、资格批次或全套故障注入测试作为前置。

### CG-10 / A：终验不降阈值，不把算术字段当完成认证

- `scenario_course.py:450–485`：
  - 2610按真实 completed小局 actual_first分组；draw留分母，异常/未闭大场/未满窗口使阈值pending。
  - 历史按external/mirror分别给完整BO3胜率、样本数和Wilson95%区间；标签本身不认证实际对手强度。
- `training_scenarios.py:59–82`严格用>49%及>39%，仅第二阶段冻结评测；输出明确 arithmetic_only、formal_training_success_verified:false。
- 历史“接近50%”容差、95%区间通过方法、多次观察、BO3 draw裁决以及2610原独立200+200向自主主题的映射仍未冻结。
- `scenario_course.py:406–417`普通validation/final_eval只在两阶段训练最低量完成后才开放，冻结后不能回训同窗口。
- DataIndex `data_isolation.py:202–257,300–315`核actual opponent/content/seed和分区；它是数据准入机制，不证明外部对手强度，也不是OS文件读取隔离。

[实际统计](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/scenario_course.py#L450-L485)
；[2610严格阈值](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/training_scenarios.py#L59-L82)

**最小处理**：继续保留pending，不擅定新容差/减少独立评测。普通course不允许早期validation时，不伪造满场或放松分区，也不为开训另设冻结功能检查；直接训练，保留真实运行记录。正式终验时才应用对应冻结规则，尚未确定项不能用来拖延开始学习。

## 7. 新20机时预算与暂停恢复

### CG-11 / N：现有预算不能直接执行新CloudStudio整实例上限

**事实**

- 用户新授权：最多20机时，4核8G费率0.5机时/墙钟小时，约最多40墙钟小时；包括准备、训练、评估、失败、归档、等待和编辑器空转，不能加购。
- `training_plan.py:136–180`按gpu_count×墙钟统计GPU实例小时；gpu_count=0只单列CPU墙钟，所以CPU不会消耗旧GPU预算。这不是本次CloudStudio账户机时监控器。
- `scenario_course.py:72–77`当前每期wall上限仍历史25h/2610的20h；`active_seconds`不是实例全部开机时间。
- `scenario_course.py:329–350,419–447`核活动段预算并在小局边界保存，但未覆盖实例启动前后、初始化/预检全部时间、外部编辑器空转；独立自对抗另有账。
- 项目本地退出/pause不会停止云计费；自动关机设置、实际费率/剩余量与关机回执须现场读取，本审核未验证。

**最小修正/执行措施**

- 新建本次统一run/billing记录，单独登记20机时授权、0.5费率、实际已用、实例各开机段和活动用途，保留原100GPUh历史计划而不混为可用授权。
- 实例实际累计为总限；课程、准备、功能检查、自对抗、评测都从同一额度分配，未计量区间保守留出，不填0。
- 明确最后保存/回读/停机余量。当前自动关机保护先核实际触发点及关闭前保存策略，不因“长训需要”直接解除保护。
- 新局前同时检查下一小局、必要保存与实例截止余量；有界每次max-matches=1或少量批次。不要把4核当四倍加速。
- 预算不足在安全边界保存并停止实例，报告实际完成量/待续项；不调低600+400或阈值，也不以本地worker退出冒充计费结束。

**只有条件外推，不是新测时**：旧A10 CPU均值67.312秒。三期正式训练4200–5400小局的串行game-seconds约78.5–101.0墙钟小时/39.3–50.5机时；再加两个历史期最低独立评测约108.4–145.8墙钟/54.2–72.9机时，尚未计2610终验、准备与归档。此算式不能当当前CPU速度或不可能完成的严格证明，但明确不能承诺20机时全达标。

### CG-12 / N：恢复应保留干净谱系，不修账本来迁移

- 当前新course：用 `state_root/course/pause.request`，在完整小局提交边界退出；保留course checkpoint、DataIndex、manifest和完整状态。
- `scenario_course.py:403–405,791–808`拒绝在途不确定状态直接恢复；不删marker、不清索引、不自动重打半局。
- 修改构筑语义/source后不属于同绑定resume，须新course；旧已提交记录隔离归档。
- 原local-training控制链 `training.control/training.recover`只管其受控worker，不直接控制scenario_course进程；不要对错对象发“已暂停”回执。
- 归档最小集合：精确源码/未提交patch、host/course/资源与牌表来源摘要、四角色base/LoRA/优化器/调度器/RNG/游标、DataIndex/台账/阶段manifest、initial/latest/milestone、异常/在途证据、用量和最后进程/实例停机记录。外部参考原件在独立评审范围保存，不夹进新learner输入包。
- 保留严格总峰值<30,000,000,000字节；checkpoint保留策略和DataIndex页上限不是全工作区/日志/临时峰值容量证明，不靠删用户文件凑。

## 8. 自对抗：能做，但未集成为替代课程

### CG-13 / D（若本轮另启用则变N预算/隔离）

- `src/ygo_kito/selfplay_series.py:142–174`默认 `training_enabled:false`；训练要显式ratio和allocation（max_matches、每玩家小局、wall及prior）。
- `selfplay_series.py:316–323`轮换学习方；每小局更新当前actor duel LoRA；不是双方同时PPO。
- `selfplay_series.py:431–470`双方用各自优化模型合法换备，保留冻结对手和私有RNG。
- 初始/历史有效模型池可保留；标签或seed变化不能把同一实际策略伪装成独立终验。
- ratio字段目前主要为规划声明；没有与scenario course共同执行的混合课程调度器去落实整个样本比例。
- `selfplay_series.py:278–291`明确formal_training_matches=0、common_deck_coverage_qualified=false、formal_acceptance_verified=false，不能用自打50%冒充环境能力。
- 原100h上限检查及prior activity字段不等于这次20机时统一实例预算。

[默认关闭与分配](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/selfplay_series.py#L142-L174)
；[独立计数声明](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/selfplay_series.py#L278-L323)

**最小安排**：本次先参考隔离与干净外部阶段；自对抗可延后，不应为有限机时挤掉所需外部bot/常见卡组与终验。若用户确定加做，明确非替代的配比/独立state/index/预算，复用现有API，不先造新模型或新外部服务。

## 9. 基模与LoRA错位：训练基模本身，而不是要求先有成熟权重

### CG-14 / N+L：用户要求先基础训练，现成course却立即冻结base

**需求依据**：同目录需求矩阵C13原文认可“分别起步，再交替协作”：决斗PPO；目标学搜索/引擎验证样本；优化学冻结决斗模型和对手/预算下的候选比较；统筹先学成功调度日志。U27明确基础模型承担复杂随机卡组推理/使用/构筑，LoRA用于后续卡表/环境/新卡组适配。这不是“先凭空找到竞技成熟权重”的要求，而是要实际执行base学习。

**代码事实**

- `course_models.py:79–101`加载工程源后立刻建四AdapterSession；`lora.py:110–131`将全部base参数requires_grad=False，只给A/B优化器。增加课程场数并不会训练被冻结base。
- `group_runner.py:842–885`只在bootstrap给四base各1次工程更新，随后冻结；max_updates控制LoRA周期，不是多步base阶段。
- 现有来源base1+LoRA1仅工程起点。其后的LoRA更新可以是真更新，但不得计作“基模正式训练已完成/已形成基础”。
- **已有可复用全参组件**：`BuildTrainingConfig.batches`支持1..100000（`build_training.py:33–49`），`BuildTrainer.step:228–254`使用双模型各自base AdamW；`CpuTrainer.update:239–304`执行全参PPO；`CoordinatorModelConfig.steps:81–94`及`CoordinatorTrainer.step:125–160`执行base更新。
- **决斗不必重写引擎接线**：`CourseGameAdapter.__call__:481–491`在`adapter_session=None`时已走`current.update(episode)`的base PPO；有session才走LoRA。typed bot/model运行接口可复用。现成`training_runner.py:25–66,344`只接受两种弱DTO规则对手，不能直接当正式既有人机配置入口。
- 当前CourseModels `_check:114–127`要求四session常驻；保存/恢复`145–191,195–281`要求四adapter状态；`CourseFeedbackUpdater`也假定AdapterSession。故只把调用参数设None或在JSON加mode并不能完成base阶段，需阶段接线及真实checkpoint格式。

[真实base/LoRA分支](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/course_game_adapter.py#L481-L491)
；[全参双构筑](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/build_training.py#L184-L254)
；[立即挂载四LoRA](https://github.com/K1tKaLL0s/YGO-Kito/blob/c1157ca5add6c29149eccf7106226b1099e63d8c/src/ygo_kito/course_models.py#L79-L101)

**最小修复后直接执行，不加预检批次**

1. 增加显式`learning_stage:base|collaborative|lora_adaptation`或等价宿主状态，纳入checkpoint/binding；初始阶段不建立AdapterSession，不冻结base。可以用经核干净工程参数作起点，也可fresh，均不宣称已经成熟。
2. 复用已有trainer和实际合法对局：决斗以session=None做当前策略鲜采样全参PPO；目标以搜索+引擎核验的自产任务/候选样本学习；优化以固定决斗版本/对手/预算的候选比较学习；统筹以调度日志学习。不把参考答案或合成概率锚点填作真实训练标签。
3. 双构筑数据须匹配其实际task/词表及DataAdmission；不能把kernel选中任务的数据直接塞给不匹配的bootstrap task后绕过校验。可分角色/阶段训练，不要求四者同时更新；每角色base更新数、损失和参数摘要分别记账。
4. checkpoint支持base阶段adapter为空，保存实际四base优化器/调度器/RNG/任务/数据索引/阶段游标；恢复继续当前阶段。既有LoRA类不需重写，只在明确进入后续适配阶段时冻结实际base并新挂adapter。
5. 独立起步后按已确认顺序协作：固定决斗模型评构筑→更新构筑→训练决斗→重新评构筑。记录冻结身份，不能把决斗驾驶提升当优化收益。
6. 不虚设“成熟基模验收通过才可开始训练”。阶段能力如何形成由实际训练记录和后续评估判断；在20机时内没形成足够基础就保存待续，不能改称LoRA-only已替代该任务。

### CG-15 / L：三期继承和多步base来源格式需要显式支持

- 用户已认可2207→2210→2610，继承权重而从目标重新构筑，不是三期各随机重置。
- `group_initialization.py:256–280`硬要求source四base游标=1；任意多步base/独立决斗checkpoint不能直接作为现source_group。
- `CourseModels.save_state:174`的kind是course-four-role-full-state-v1，initializer只收完成的four-model-alternating-v1/complete-workflow-stage。因此当前不能直接把2207 course checkpoint当2210的source_group。
- 最小改为明确版本化的四角色参数导出/新期初始化路径：核真实base/adapter游标、模型/特征/词表、任务/资源/训练来源；按稳定卡ID映射，不伪造kind/cursor、不删旧恢复门禁。新期仅迁参数，优化器/RNG/数据/账本是否重建按明确初始化语义记录；同绑定resume仍保留完整原状态。
- 这项在进入下一期或消费多步base工件时接好，不要求先造完所有未来迁移方案才开始2207的第一条干净base更新。

## 10. 建议交执行任务的最小实现顺序

1. **先完成现场暂停回执与分支隔离**。保留最后完整小局/更新checkpoint，不再继续参考牌表actor。
2. **改历史learner deck来源**：修CG-01/02，令主题受限而牌表由模型链从空表产生；参考只给独立评审。同步新配置语义和说明，拒旧含义被静默续用。
3. **选可证明干净源，新course/state**，或显式fresh；接CG-14的真实base阶段而非立即冻结LoRA。直接生成实际main/extra/side并开始相应角色base训练，不先补任意全卡效系统。
4. **在统一20机时/停机保护内，直接真实构筑、训练**。由训练本身留下自产deck进入actor、自然终局、非零base参数变化、完整边界保存记录；运行具体失败就修该失败后续跑。已有结果能回读则回读，不先开preflight、独立功能场、资格批次或历史全套测试。
5. **按分别起步→协作推进四角色与统筹账本**，每项分别报告。缺标签保持pending，不以合成概率/参考答案填空，不把仅duel更新称四模型目标完成。
6. **按2207→2210→2610，保持原600+400及独立规则**。新期前接实际四角色参数迁移，不三期各随机重置。机时不足就归档待续；正式外评和未决统计口径在对应阶段闭合。
7. LoRA作为后续环境/新卡组适配，不替代用户要求的base训练。额外架构扩容、完整任意CB、PC界面/外部provider可后排；自对抗安排见CG-13，不替代常见卡组覆盖和独立终验。

## 11. 执行任务文件定位清单

### 第一批通常需要改

- `src/ygo_kito/scenario_course.py`：37–48配置；238–270构筑入口；275–292 actor绑定；368–375统筹占位；488–521反馈宿主边界。
- `src/ygo_kito/course_models.py`：79–101立即四LoRA、114–127检查、145–281保存恢复；接显式base阶段、adapter为空的合法状态及实际四base更新游标，不以LoRA-only代替基础训练。
- `src/ygo_kito/course_feedback.py`：现有25–36/118–168绑定AdapterSession；base阶段需明确路由到已有base优化器/损失与真实训练数据，不伪装适配器更新。
- `src/ygo_kito/autonomous_construction.py`：183–216绑定/参数；228–250主题事实；280–329任务继承/候选池；344–420任务排序；453–469构筑与CB收据。
- `src/ygo_kito/training_scenarios.py`：128–140历史构筑语义校验；不得顺手降59–82阈值或29–56场数。
- `configs/training-scenarios-v1.json`：历史reference/main-slot旧含义；不得将参考答案移作requirements。
- `src/ygo_kito/scenario_course_host.py`：32–48初始化声明；195–205目前只核duel LoRA容量；250–310模型/资产binding。接base阶段配置/容量；需要fresh时增加明确初始化模式，不放松旧来源契约。
- `scripts/scenario_course.py`：17–63真实CLI表面；需要宿主反馈接线时扩展明确受控接口，不加任意shell/RPC路径。
- `CODEBUDDY.md`、`docs/development/scenario-course-runner.md`、`docs/development/cpu-takeover-and-selfplay.md`及MASTER-CHECKLIST：纠正参考语义、记录新预算和实际实现/未决项，不涂改旧失败事实。

### 优先复用/参考，不默认改动

- `src/ygo_kito/construction_fill.py`、`construction_controller.py`、`construction_binding.py`、`construction_model.py`：现有粗图→绑定→填卡/模型选择。
- `src/ygo_kito/build_semantics.py`、`build_contracts.py`、`build_model.py`：合法三分区和真实支持范围。
- `src/ygo_kito/course_feedback.py`、`semantic_training.py`、`data_isolation.py`：明确标签、实际训练准入/分区。
- `src/ygo_kito/course_game_adapter.py`、`match_runner.py`：真实PPO与BO3/换备。
- `src/ygo_kito/coordinator.py`、`coord_contracts.py`、`coordinator_model.py`：已存在预测/结果/路由/历史机制。
- `src/ygo_kito/group_initialization.py`、`lora.py`：复用参数校验；下一期/多步base来源需CG-15格式接线，LoRA冻结行为本身无需为base阶段全局削弱。
- `src/ygo_kito/selfplay_series.py`、`model_opponents.py`：辅助自对抗与有效冻结快照，不替代外部评测。
- `src/ygo_kito/training_plan.py`：旧预算字段含义；新增本次CPU实例计量时不要误用GPU0为免费/无限额度。
- 参考模式：`build_feedback.py`、`construction_curriculum.py`的真实成对数据边界，不冒充可直接正式训练的现成配方。

## 12. 禁止作为本轮完成依据的说法

- “单测通过/预检ready，所以训练设计、真实CB、真实终局、四角色学习或强度验收全部通过。”
- “换了参考表文件名/主卡只改几张/从参考提取pool，就已经自主构筑且没读参考。”
- “建了四个LoRA对象，就四角色都在学。”
- “每100场review事件/1000场无条件重构，就已实现原统计统筹。”
- “基模各1步，所以不能训练”；或相反“工程起点已经成熟有竞技能力”。
- “自打50%/任意初始模型常见牌表对打，就等于强外部常见卡组覆盖。”
- “20机时肯定够三期达标”；或“为了预算将正式场数/门槛改小后宣布成功”。
- “本地worker退出/保存成功，所以CloudStudio停止计费”；必须有实例状态/停机回执。

