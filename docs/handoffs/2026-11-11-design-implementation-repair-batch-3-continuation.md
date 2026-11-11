# 空状态联合专项之后的独立接续

2026-11-11，Asia/Hong_Kong。本摘要可独立执行。用户已恢复并授权自主完成YGO-Kito全部剩余软件修复，必要时可自主新开同模型主聊天并立即开始，不再次询问是否启动；只用gpt-6.1-sol/max，主进程执行，不启动子代理、不创建新工作树。当前没有待答问题。本批已经形成状态专项的安全交接边界，下一主进程直接从R3真实续算实施，不能只确认收件后待命。

## 目标、权限与唯一真实位置

原目标：严格按有效设计及R0—R11逐包修复、验收全部软件缺口。继续应用`C:\Users\27499\.codex\skills\preserve-intent-and-execute\SKILL.md`和`anti-overengineering\SKILL.md`，先读`C:\Users\27499\.codex\instructions\code-work.md`。非UI执行书交付后可直接实施，无新增审批。复杂卡文余项必须修复；只有原设计和当前官方口径仍不能定义/分类的少数事项，完成其他修复后再集中询问。目前无需用户补卡文、参考、阈值、盘面或模型决定。

完整实施目录唯一为`N:\YGO-Kito\_publish_20261030`；工具默认cwd可能是外层`N:\YGO-Kito`，全部源码、命令必须显式进入完整检出。外层源码、`_local_cpu_20261027/source`、历史交付副本不能执行。沿混杂工作树，不reset/clean/restore、不从HEAD重建、不全量覆盖、不恢复已删文件、不提交/推送/合并、不清理既有成果。分支`codex/optimization-20261031`、HEAD`3f57198e5e366152bbb672be8910e6800f8adbb4`。许多长期源码本来是untracked，不能当本轮新文件删除。

训练、权重推理、参数更新、CB/native、完整构筑、GPU/PC实测和安装继续暂停；不恢复run-007。已授权静态软件测试、调度替身及离线标签合同。不得读取、运行或重建Pro资料随附的辅助验证代码。保护native ABI/guard；不故障注入、不越界/SIGSEGV、不全局杀Python、不重启电脑、不修改凭据/权限。

## 必须保留的设计

S0固定任务、硬条件、路线/必需发动、全时期池和区域。S1先无卡ID逻辑，狭义才筛必需系列/种族轴；广义仍保留图。S2多轮优化并继续召回。S3候选与原指定参考使用同一评价器/政策。S4完整合法候选按最终S排序，模型分只调度/同分辅助，选择/反馈/学习使用同一Evaluation。S5合法性、配套、完整性和0.8参考比例保持，完成失败回S2，连续两次完成失败才提示。S6仅静态通过并有独立授权后CB，两次正常失败回S2。开发无上线总时限/总迭代次数；上线到期停止新增并排空当前S3—S5；用户停止优先。

保留log2、P/V1/V2/S、Main E1/0.9、Extra1/0.8、实际Main40—60张、主要+100%/次要+50%、Side方向和原比例。不增第二评分器/求解器/事实库，不按卡名/ID打补丁，ID仅来源、实体及规则身份。不得重复同一实体、支付和收益。静态配置不索要当前手牌/墓地/对方对象/随机命中/实际顺序；程序未知与算法待算区分，不能置真。

## 首读资料

1. `docs/current/README.md`最新段落。
2. `docs/reports/2026-11-11-design-implementation-repair-batch-3-state.md`和本摘要。
3. `docs/plans/2026-11-11-design-implementation-repair-resume-execution.md`。已交付的R3具体执行书，按实际新增动作补充即可直接实施；还没有修改R3枚举/评分代码。
4. 原`2026-11-10-design-implementation-repair-plan.md`、`repair-execution.md`和审计报告`docs/reports/2026-11-10-design-implementation-audit.md`的F01—F19。
5. README有效链接的S0—S6、正式评分方案、验收对齐表、统一规范和11月4日扣分方案。Pro辅助代码跳过。历史待命/已全部完成/run-007运行说明不能覆盖最新状态。

第二批报告/接续和R1执行书保留复杂卡文细节；不要从头重做已通过的R4/F06/F07、R8/F12。377只是当时AST文件数。旧308/304包含重复导入测试类，不能当不同方法数。

## 第三批真实实现

仅四个程序文件：

- `src/ygo_kito/construction_layer_flow.py`。
- `src/ygo_kito/multifactor/conditions.py`。
- `tests/test_construction_static_entries.py`。
- `tests/test_multifactor_conditions.py`。

文档为状态专项执行书、R3续算执行书、第三批报告、本摘要及README/MASTER-CHECKLIST/repair-plan最新段。此前六个生产/三个测试文件的第二批成果保持，不覆盖。

规范化提升到`construction-function-normalization-v24`，字典仍`public-text-completion-20261111-b9`；评分v4与公式不改。新增状态合同是共享分配器Resource的`initial_zones`，Condition的`state_origins/state_destination/state_absent/state_binding/state_exclude_binding/state_destination_replace`；JSON加载处理tuple字段。默认不启用这些字段时仍走原分配语义。没有加载旧权重验证兼容性；旧Evaluation由现有规范化绑定失效并重评，原成果不覆盖。

`normalize_function_uses`的use_details新增已解析`activation_state_conditions`与`state_movements`。`_state_movements`解析完整支付/实体移动选择器、生成规格及非持续魔法陷阱规则离场；这些不是额外计分功能。`_bind_mandatory_impacts`保存`support_order`，对required/all组加入必要支撑前置；对同一完整处理中后置条件，把同effect的前置处理加入支持闭包。独立可选用途仍不无条件联合。

`_joint_state_order`使用原before图，按scope分别构建发动、支付、处理、规则离场事件；同一`relation_fact_id`的多功能投影合并为一个处理节点。源实体以card_id身份绑定，正常魔法先检查条件再放置，怪兽/墓地/手牌效果先确认其源位置；自身成本、后续自身动作和cleanup复用同一actor binding，不能换成另一同名副本。Token从uncreated进入场上，离场标ceased，不虚构牌表Token或可回收Token。

实体分配仍调用原`multifactor.conditions.solve_requirements`，没有第二分配器。其分支`_State`增加slot_zones、state_bindings、destination_replacements。空状态从未移动槽的可能起点中排除指定区域；已确定移动后该槽只在实际去向。移动数量按不同槽选择；两张可分两次各一张移走，同一张返回后可再移动。分支状态隔离。已启用去向替代只改后续移动，旧墓地卡不消失，原严格送墓限制继续由restriction消费者检查。

原新增空墓反例已修复；合法先用空墓、自身先检查后支付、真实足量清空、数量不足/选择器不符、不能复用一次清除、拆分清除、单副本返回后再次生产、Token空场、通常/持续魔法区别、同一效果的后置条件和替代前后均有默认统一评价回归。KONAMI官方fid12929确认通常魔法效果送墓后自身规则送墓；链接在第三批报告。第二批官方卡文/Q&A依据继续有效，不用现行禁限覆盖历史任务。

## 当前验证证据和开放缺陷

`.cache/design-implementation-repair-20261111-state/verification-current.log`及`verification-summary-current.json`：十个显式安全静态模块，按完整ID去重292项通过，0失败/错误/跳过，约58.4秒，torch_loaded=false。模块是text_completion、static_entries、condition_selection、runtime_processing、effect_block_dictionary、inventory、relations、functional_flow、layer_flow、multifactor_conditions。初轮290项出现14个无状态条件手工夹具缺fact_details的兼容错误，已修；早期日志保留。`verification-final.log`为加最后两个替代测试前的290全通过，当前292取current日志，不能相加。

`artifact-validation.json`最终覆盖上述四程序文件，AST/末尾换行/逐行空白零错误。Git按CRLF口径对本批文件diff --check通过。当前验证脚本按ID去重。不是完整CI，未训练/推理/CB/native/完整构筑。主进程所有测试command sessions已结束，不需要复用旧session ID。

同目录`open-regressions.log/json`为本批最终明确执行的两个开放反例：

1. `tests.test_construction_calculation_resume.CalculationResumeTests.test_f04_all_129_single_supplier_allocations_are_enumerated`：预算100000仍只出128且exhausted，普通失败。
2. `tests.test_construction_workflow.WorkflowTests.test_f08_reference_is_independent_of_optional_candidate_graph`：合法指定参考缺候选可选节点仍reference_invalid，普通失败。

这两项0错误/跳过、torch_loaded=false。原空墓失败已经转绿，不再列第三项未修。整个R0—R11没有全部完成。

## 下一阶段R3必须实际实施的内容

先读实际函数及R3具体执行书，然后直接修改，不停留在写方案。共享分配仍是递归`_Search.solve/sequence/atomic`，超过states/solutions后丢失生成器位置。`construction_relations._partial_allocations/_combine/_expression`、回收候选/数量/转移仍有128永久截断；这些函数本批没有改。`construction_recognition.allocate_relation_group`也默认调用共享solver一次，必须同步消费新游标。

R3执行书确定：将共享solver改为显式DFS任务帧，保留原子组合、all/any/at_least_k/not、预约、动态区域/绑定、去重及下一位置；输入绑定和完整栈可JSON恢复。保持同一实现，不新增求解器或提高常数。关系调用保留局部枚举工作和完成子结果，当前fact/use不完成时不能从队列永久弹出；在匹配/更新/用途/required组各阶段正确续接。旧队列续算和JSON等值判断保持。

`_joint_state_order`目前枚举拓扑安排后调用共享solver，尚未保存安排DFS栈和当前分配游标；这也是R3需要接入normalize工作状态的新增实际消费者，不能只修原三个函数。其预算目前可能返回None，但还不能下一片从断点继续。应保留完整的候选安排及分配状态。

随机移动还需在R3消费完整分支：不能因选到一次有利身份/避开而把后置空状态当确定。`_state_movements`目前只收完整可识别选择器/数量，随机送墓未必都有该元数据；核对实际字段并补消费者，不能将程序漏投影当用户缺盘面。没有对应的新失败方法，实施时需补正常回归。状态专项292通过不等于这些枚举/随机分支已经证明。

质量F05尚未改：`construction_quality.evaluate_functional_quality`每次重新枚举Boolean完成组合，`_functional_loss_records`超时后重算已有结果；adapter只保留已完成normalize投影。需独立阶段游标保存组合索引、分项累积和失分说明，超时不进入完整Evaluation缓存。切片JSON恢复后的score/loss_records/Evaluation ID必须与一次完成一致，不重复已处理前缀。

建议实际结构是每个计算单元保存显式帧/当前索引和已完成结果，外层现有continuation保存活跃单元；遇预算退出保留当前单元，不把它当缺规则或失败。具体代码仍要对照实际函数，不能盲从旧摘要。R3测试需覆盖129全方案、极小片JSON恢复、shared实体/费用、回收/循环、状态安排和质量两个阶段。

## 后续全部未完成包

R3之后R5/F08/F09：参考绑定原BuildTask硬条件，独立于候选可选图，但同一评价器/政策。候选比较提交一次，reference阶段续接，完整参考按任务/政策/评价器/资产/牌表绑定缓存；不剥硬条件或新建私有分数。

随后R6/F10/F11统一校验/数据搬运/权威checkpoint和正常取消保存；R7/F15受控RPC生命周期；R8/F13离线有来源负例/兼容冲突/自然组合与分项诊断；R9/F14通用静态CB目标/绑定/计划交接；R10/F17/F18纯软件取消隔离与资源监测；R11逐F收口。R4/F06/F07和R8/F12保留首批修复，不重复重写。

R8先核对并行M4/M5及`training/axis_generic/full18_sources.py`，不覆盖网络、权重、训练配置/指针。R9只静态符号/绑定/计划，不运行infer/search/CB/native。R10不改ABI/guard、不故障注入/越界/SIGSEGV、不全局杀Python；真实设备实测仍暂停。R11不能把完整CI/构筑/训练/引擎未运行写为通过。

## 执行环境和既有资产

WSL `Chaos-Ubuntu-26.04`，源码`/mnt/n/YGO-Kito/_publish_20261030`，已有CPU解释器`/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python`。前缀：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. OMP_NUM_THREADS=2 MKL_NUM_THREADS=2`并用`-B`。首次沙箱WSL的E_ACCESSDENIED经正常require_escalated审查成功，可沿`wsl.exe -d Chaos-Ubuntu-26.04`前缀，不绕过拒绝。旧wsl配置未知键警告不修系统配置。

示例：`wsl.exe -d Chaos-Ubuntu-26.04 --cd /mnt/n/YGO-Kito/_publish_20261030 -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 /mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -B -m unittest 完整静态方法名 -v`。不跑discovery或未经筛选的全CI；check_merge_candidate虽CPU名称仍含模型更新/引擎历史项。

run-007继续停在`.cache/construction-condition-selection-20261110/run-007`，原kernel409572012字节、session408615095字节，停止时间UTC+8为11月10日21:45:35/21:46:25；这些为上一批stat记录，本批未读/哈希/恢复大型档。原12候选静态完整数0、score.value空；旧模型顺序不是静态排名。原参考resident states1326/queue115/read_cursor41，S5gate=null、CB没跑，build_goal/build_optimizer5/0。保留原成果。

原权重/课程根在`_local_cpu_20261027/reports/course-continuation.json`、`reports/optimization-20261031/2207-course-006/model-binding.json`和`course/checkpoint-1.weights`；`reports/training.hold.json`不写。规则实体`_local_cpu_20261027/assets/native/engine-src`，中文库`database/locales/zh-CN/cards.cdb`，禁表`client/lflist.conf`。指定参考为`configs/user-deck-references/main-01-source-v1.json`和`main-02-source-v2.json`。已有资源不重下载，不执行旧source。

本主进程最后实读get_usage_limits为周usedPercent92（当次剩余8%）、1张可用重置卡，未使用。用户最新已更新旧20%停止/禁用卡规则：修复未完成且实时剩余≤1%时允许使用已有卡，使用前重新读实时值并遵守工具授权/阈值/幂等，不购买、不换模型。不要把本摘要当后续余额。

## 等待、上下文和禁止重复

当前无待答问题。真正提问后必须等待真实答案或用户明确授权自主决定；沉默、accepted、预选、时间已过都不等于同意。保留“待答问题—暂停范围—恢复条件”，检索/分析/实施/交付和后台/子代理同受约束；无独立必要工作则结束本轮交还用户。不能将后续无关消息当回答。此前重启暂停已解除，不能用旧暂停停工；训练等独立暂停仍有效。

长任务优先同聊天并允许自动压缩；当继续压缩可能损害准确性/约束/状态连续，或到合适安全交接边界，先完成当前非破坏性原子步骤，不再开新实施阶段，更新完整独立摘要并按已有自主接续授权创建同模型主聊天，确认新主进程开始。每次首条提示必须重申本节规则；不得编造精确上下文占用百分比。不创建工作树或子代理。

禁止重复：不重跑无变化首批344组；不把早期304/308执行次数当不同方法数或累计各组；不重写R4/F12；不复建旧源码/权重/运行档；不把临时脚本当第二项目入口；不安装或恢复暂停流程；不只更新文档或保留unknown后宣布修复完成。下一步是R3实体分配/关系/质量真实续算的实际代码。
