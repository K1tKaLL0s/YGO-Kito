# R6 起继续修复 YGO-Kito

2026-11-11，Asia/Hong_Kong。此摘要可独立执行。原任务是完成并验收 YGO-Kito 的 R0—R11 软件缺口。原聊天最近一条用户明确授权为“自主推进后续的所有工作，想新开任务或者直接在这里推进完都可以，复杂卡文余项必须完成修复，如果遇到引用当前官方口径后仍无法正确定义、分类，可以在完成其他各项修复后一并向我询问。同样请积极做好防叠甲、防过度工程工作，积极回顾各项设计和官方口径。模型调用仅允许使用6.1-sol MAX，如在剩余1%额度时仍未完成修复工作，允许使用重置卡”。由 gpt-6.1-sol/max 主进程直接实施，无待答事项、子代理或新工作树。先读忠实执行与去过度防御、防过度工程两技能和 `C:\Users\27499\.codex\instructions\code-work.md`。非 UI 代码交付每阶段机械执行书后，继续已经授权的实施和验证。

## 工作目录和有效设计

唯一完整源码检出是 `N:\YGO-Kito\_publish_20261030`，分支 `codex/optimization-20261031`，HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`。工具默认可能落在外层，所有源码及运行命令显式使用完整检出。现有工作树混杂，大量功能文件为原有 untracked；继续实际文件，不 reset、clean、restore、从 HEAD 重建、清理既有成果或提交、推送、合并。跳过 Pro 附带辅助核验代码的读取、运行及重建。训练、权重推理、参数更新、完整构筑、CB/native、GPU/PC 实测、安装和 run-007 处于既有暂停。授权范围包含纯静态软件测试、调度替身和离线标签合同。不改原生 ABI/guard，不做越界、SIGSEGV、故障注入、全局杀 Python、重启、凭据或权限变更。

从 [当前索引](../current/README.md) 进入 S0—S6、正式评分、统一规范和 11 月 4 日扣分设计，再看 [逐包方案](../plans/2026-11-10-design-implementation-repair-plan.md)、[机械执行书](../plans/2026-11-10-design-implementation-repair-execution.md) 及 [F01—F19 审计](../reports/2026-11-10-design-implementation-audit.md)。旧的待命、权限待答和 run-007 运行中记录是历史。

S0固定任务、硬条件、路线/必需发动、全时期池和区域。S1先做无卡 ID 逻辑，狭义才筛必需系列/种族轴，广义保留图。S2多轮优化及继续召回。S3候选和用户固定参考共享评价器及政策。S4完整合法候选按最终S排序，模型用于调度及同分辅助，选择、反馈和学习使用同一 Evaluation。S5保留合法性、配套、完整性和0.8参考比例，完成失败回S2，连续两次才提示。S6仅在静态通过且另获授权后执行 CB，两次正常失败回S2。开发无上线总时限/总次数，上线到期停新增并排空 S3—S5，用户停止优先。保留 log2、P/V1/V2/S、Main E1/0.9、Extra1/0.8、实际 Main 40–60、主题 +100%/+50%、Side 方向及参考比例。ID 用于实体及出处，代码沿同一事实、共享分配和唯一评分，不按具体卡名/ID补丁。静态配置从印刷能力和固定库存判断，不要求实际手牌、盘面、对方对象、特定随机命中或实际操作顺序。区分待算、语义未知和硬失败。

## 已完成、真实文件和证据

第一至第四批已关闭 R0、R1/R2 已报告的语义回归、R3 中的共享 DFS 和关系 facts→uses→joint 续算、R4/F06/F07、R8/F12。第四批 F04 原 129 替代反例已通过。首批、空墓和第四批验证结果只说明当时源码，不需重复。此后的真实工作见 [第五批计算和卡文记录](../reports/2026-11-11-design-implementation-repair-batch-5-calculation.md) 及 [固定参考执行书](../plans/2026-11-11-design-implementation-repair-reference-execution.md)。

R3 收口文件为 `src/ygo_kito/multifactor/conditions.py`、`construction_layer_flow.py`、`construction_quality.py`、`effect_records.py`、`effect_blocks.py`、`effect_block_rules.py` 及 `tests/test_multifactor_conditions.py`、`test_construction_static_entries.py`、`test_construction_functional_quality.py`、`test_construction_calculation_resume.py`、`test_construction_text_completion.py`。状态安排和随机实体分别保存 DFS/分配游标，随机全真/全假/混合保留对应确定性，费用及后续依赖的实际去向经替代核对。质量用 `functional-quality-work-v1` 保存一致补全索引和已解释失分；同一公式、完成才生成 Evaluation。卡片炮击士同形卡文的 1..N 随机费用、按实付量增益、破坏且送达墓地触发已接默认入口。三个支付选择共享一项功能。对实际中文库核对后，将有明确投入措辞的条款归为投入限制，未绑定选取数量仍有来源及局部作用域，已知费用范围消费原文片段。v26/b11 的合并静态 360 项无失败、错误、跳过、Torch 加载，11 个文件的 AST 与空白通过。字典保持 b11，当前规范化已因 R5 的原任务必要库存判定升为 v27，评分仍 v4。KONAMI 官方牌顶、翻开后选择、去向替代、卡片炮击士资料及差异详见第五批记录。已识别的具体余项直接按原文修，不能用待问代替实施；官方和原设计仍无法定界的少数内容等其他修复完成后一次问。

R5/F08/F09 源码修改 `construction_layer_flow.py`、`construction_fill.py`、`construction_progress.py`，既有回归修改 `tests/test_construction_workflow.py` 和 `test_construction_calculation_resume.py`。候选和固定参考共用 `ConstructionLayerAdapter.evaluate_inventory`。参考轴的逻辑为 None，原任务/牌表由 `assets.validate` 检查；保留宿主 required 用途、其中明确联合约束、宿主供应事实和评分主题，独立于候选自选图。必要牌、起始库存或指定发动实体明确缺席时原路线硬条件失败；实体存在时未获静态路线见证仍为未知，R9继续。固定参考缓存用 `construction-reference-binding-v1` 绑定实际卡库行、禁限/资源、时期、原任务、参考来源及库存、政策、规范化和宿主输入，静态算完后写入。图变而参考输入相同则复用。参考暂停时 `pending_reference` 为 `construction-reference-stage-v1`，保存候选生成种子和参考游标，`pending_phase.stage_3` 已含实际 S4 完成结果，`pending_quality=None`。旧的数字索引参考游标失效并继续其候选批次，政策或候选相关卡文真正变化使必要工作重新计算。候选 Evaluation、顺序和选择在同一参考阶段保持。F08正反例通过，零分参考仍按门槛拒绝，真正必需用途缺失得到失败。F09 12 个候选实际做 66 对比较，三片参考 JSON 恢复绕过填充，候选 ID/顺序/已选牌表一致。缓存测试确认图改复用，宿主事实、参考牌表相关原文、来源/政策改动重算。

证据统一位于 `.cache/design-implementation-repair-20261111-resume`。R3/b11 为 `verification-state-quality-card-text-b11-summary.json` 和同名 log、`artifact-validation-state-quality-b11.json`。R5 静态组 `verification-reference-v27-static` 为 153 项中 152 通过、1 条旧主题断言失败、0 错误/跳过、无 Torch。该测试仍等待随机送墓的实际命中，与用户 11 月 10 日明确纠正冲突。只改 `tests/test_construction_theme.py` 的该项，保留随机标记、无指定调用、Main 浓度和精确分数断言。其定向复验和默认入口对照共 2 项通过，见 `verification-reference-v27-static-theme-correction`。R5 最终六个文件 AST/空白通过，见 `artifact-validation-reference-final-v27.json`。本轮 command sessions 均已结束。

初次放大 R5 验证误纳入 `test_construction_binding.CatalogBindingTests.test_actual_candidate_and_model_scoring_pipeline_uses_catalog_adapter`，输出到达该方法，随后中止整批。该用例含随机初始化 CPU 模型的 forward。原课程权重和真实运行不在这项夹具中。保留初次日志 `verification-reference-v27.log`，只使用排除该精确方法并阻止 Torch 导入的静态组作为验收。所有后续组也先筛方法，`test_construction_cli` 含 intent 模型拟合用例，`check_merge_candidate` 含旧训练及引擎项，禁止整组未筛选执行。混杂工作树全局 diff check 另见未由本轮修改的 `construction_effect_blocks.py` 文件尾空行，目标源码检查通过，勿将其扩成新清理任务。

## 接下来实际做的工作

1. R6/F10/F11 直接进入实现。当前 `construction_quality.functional_delta` 每次对完整 Evaluation 重新 digest，`ConstructionLayerAdapter.evaluate` 仍重做片间已算候选的比较，`construction_fill` 多次深复制批次和状态，`construction_learning.comparisons/cycle_pairs` 对每个候选附带的同一比较重复验证。保持外部输入/恢复时的来源验证，内部用不可变的小比较数据，在一次批次的实际比较完成后保存下一对及已算结果。优先沿同一函数及现有批次，核对选择、门槛、学习共享相同 Evaluation 和比较数据。用真实夹具查哈希、比较、深复制工作次数；保留已完成 R5 的 12/66 跨三片证据，不把 R6 归为已完成。开发及上线排空仍用同一主循环，停在比较/保存安全边界。
2. R6 保存。现 `scripts/run_construction.py` 的 `write_json` 是 temp.replace，`checkpoint` 先写 kernel 再写 session，每片无统一版本记录，异常重写 kernel，`KeyboardInterrupt` 不在当前 `except Exception`；`--resume` 已读 kernel。沿 `AutonomousConstructionKernel.state_dict/load_state_dict` 绑定，选择单一 kernel 权威提交和安全版本记录，session 为带相应版本的导出。原权威文件及旧裸 kernel 可读，暂存/落后导出不作恢复来源。正常取消用共享 pause 信号，完成正在进行的安全写入，记录用户停止，优先于新阶段。用小文件和替身测试写入异常、导出失败、遗留 tmp、用户停止/恢复，禁止运行主 CLI 加载权重。原 run-007 只保留历史。
3. R7/F15 使本地服务受控 RPC 生命周期复用实际构筑调度及保存。实施明确 mode/片参数、创建/继续/进度/取消、幂等与原任务隔离，禁止外部任意文件路径、训练、native/provider 越权，验证隔离 CPU 替身。当前不涉及 UI。
4. R8/F13 只补离线来源证据、兼容冲突、自然组合和分项诊断。先核并行 M4/M5 和 `training/axis_generic/full18_sources.py` 真状态，原 46 个压力案例和数据拆分保留；无需训练/权重推理或接管其他成果。F12 已修。
5. R9/F14 通用静态 CB 目标表达和绑定/计划交接，含 link、ritual 及非召唤目标，保持随机动作可描述与特定命中依赖的区分。只用符号/静态测试，不执行 infer/search/CB/native。
6. R10/F17/F18 做纯软件取消隔离及资源监测的替身验证，C# watchdog 和原生调用分别记录，未测指标明确写未测。真实运行和 GPU/PC 指标另列，继续按原暂停。R11 对照 F01—F19、默认入口和设计验收，收口当前索引和安全 CI 登记。给真实修改、定向测试、未执行的整套 CI/构筑/引擎状态。

## 环境、剩余额度和交接

WSL `Chaos-Ubuntu-26.04`，源码 `/mnt/n/YGO-Kito/_publish_20261030`，CPU Python `/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -B`。环境 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. OMP_NUM_THREADS=2 MKL_NUM_THREADS=2`。从完整检出调用 `wsl.exe -d Chaos-Ubuntu-26.04 --cd /mnt/n/YGO-Kito/_publish_20261030 -- env ...`，若沙箱 WSL E_ACCESSDENIED 走正常 require_escalated 审查前缀。系统未知键警告与验证分开，不修 WSL。静态用例先确认无模型/引擎入口。N 盘资产 `_local_cpu_20261027/assets/native/engine-src`，固定中文库 `database/locales/zh-CN/cards.cdb`，禁表 `client/lflist.conf`。指定参考位于 `configs/user-deck-references/main-01-source-v1.json` 和 `main-02-source-v2.json`。已停 `.cache/construction-condition-selection-20261110/run-007`，数百 MB kernel/session、日志和既有权重/课程指针保留。不得读取大档来重复基线或恢复原运行。只读存储及具体许可沿用户 AGENTS。

实读用量在原聊天末段周用量已使用 97%，当时剩余 3% 和 1 张已有卡，未使用。下一阶段以实时 `get_usage_limits` 为准。只有修复尚未完成且实时剩余 ≤1% 时按用户已授权用一张现有卡，遵守工具审批、阈值及同一尝试的幂等键；不购买或换模型。

等待规则延续。没有待答问题就自主执行；一旦实际提出问题，等用户真实答复、撤回或授权自主决定。保留“待答问题—暂停范围—恢复条件”，检索、分析、选择、实现、交付与后台都暂停其依赖分支。沉默、工具 accepted、选项预选、超时均无授权；独立工作完成后把回复机会交还。长任务优先当前聊天并允许自动压缩；当压缩可能影响准确性、约束、文件状态、验证或形成合适交接边界时，完成正在执行的非破坏原子步骤，保留独立交接并依用户明确授权同模型新开本地聊天，确认主进程实际开始。重申这两条规则，别声称能看到精确上下文占用。新任务从 R6 开始实做，别只确认收件、重跑已稳定大组或清理混杂树。修完其余软件后才问仍不能依官方正确定义的卡文。
