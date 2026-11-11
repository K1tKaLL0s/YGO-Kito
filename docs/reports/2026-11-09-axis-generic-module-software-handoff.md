# 轴与泛用识别整个模块源码与工程交付续办

接续完成（2026-11-09）：本摘要的源码待办已由后续主进程完成；当前使用[软件完成报告](2026-11-09-axis-generic-software-completion.md)和[软件入口说明](../development/axis-generic-software-v3.md)。下方交接内容保留交接当时状态，不能据此重新启动已完成的源码工作。真实运行限制继续有效。

日期：2026-11-09，香港时间。本摘要供新任务独立接续；用户已明确允许主进程选择新开任务或在原聊天继续。

## 修正后的总目标与权限

用户原意是让主进程自主完成整个“轴与泛用识别模块”的源码和允许的工程交付，不是只做 M7，也不是做完一个小批次便停止等待下一条指令。原任务把续办范围限在 M7，已向用户明确纠正。

原任务询问完整模块授权是否解除运行禁令，用户明确回答：“保留上述运行限制，完成全部源码和允许的工程交付”。所以总目标包含后续 T1–T5 所需的数据准备、训练、消融、校准、独立评估、能力接线及环境适配代码与工程验收；正式训练、真实资料准备、CB、原生引擎和 CI 仍不运行。不得以这些实际运行尚未获准为由，把可实现、可用夹具验收的后续源码继续全部留待将来。实际模型能力和真实阶段仍准确记为未验证。

全部由新任务主进程执行，不启用子代理。允许对应测试、必要导入，以及此前已明确放行的工程模型前向/反向、微型更新、任务临时 checkpoint 保存恢复；不改变既有/活动权重、暂停/课程指针或构筑政策。没有提交、推送、合并、发布、新 worktree、checkout/reset/clean/stash、恢复既有删除或覆盖未跟踪成果的授权。

CB 相关源码可核对/补齐。提示 DTO、宿主显式同意等纯接口夹具必须先核对实际调用路径，并拦住真实搜索/provider/原生入口，确保不执行 CB；不能借接口测试启动真实 CB。原任务因范围较窄将一个 CB hints 工程方法排除，后续应据实际路径判断它能否作为不执行 CB 的工程契约测试完成，不把函数名字本身当作真实搜索。

## 真实文件和当前状态

项目目录 `N:\YGO-Kito`，实际完整实施仓库 `N:\YGO-Kito\_publish_20261030`。所有项目命令使用后者作为 workdir，不能在父目录或旧 _local_cpu/_work 副本运行。当前分支 `codex/optimization-20261031`，定位 HEAD `3f57198e5e366152bbb672be8910e6800f8adbb4`，只作定位。工作树有大量长期既有和并行构筑的 dirty/untracked/deleted，必须原样保留；新任务与当前检出共用本地项目，不建 worktree 或切换分支。

M0 保存、M1–M6 源码及 M7 文档/专用源码已经交付。M7 的 Q1–Q5 与 V10 当前选定工程范围已有 192 个不同方法通过、231 次物理执行。最近 V10 五项首次全过，0 failure/error/skip/禁止调用；这是工程证据，不是正式训练或模型能力成绩。主计划原第 2–8 节继续保留制定时状态，最新结果看页首与报告。

关键入口：

- [主执行书](execution/2026-11-08-axis-generic-execution-plan.md)，特别第 4、8 节的整个模块设计与 T1–T5；[M7 索引](2026-11-09-axis-generic-m7.md)记录 A01–A10、V01–V30 的已验子范围。
- [当前开发说明](../development/multifactor-role-analysis.md)；仓库 `AGENTS.md` 及其引用的统一规范、构筑/训练说明。用户最新权限优先于历史说明。
- `src/ygo_kito/multifactor/{contracts,conditions,semantics,axis_candidates,network,graph_network,task_queries,training,graph_training,scoring,adapters,analysis}.py`。
- `training/axis_generic/{prepare_v3,train_v3,assessment}.py`、`config.v3.json`、`config.train.v3.json`、`ASSESSMENT_PROTOCOL.v3.json`。
- `src/ygo_kito/construction_recognition.py` 与 `tests/test_construction_recognition.py` 的 `test_cb_hints_require_available_assist_facts_and_explicit_provider_support`。

必须保留此前实际修复：graph_training.save 的 Windows 分支用不覆盖目标的 os.rename，其他平台保留 os.link；包标签旧断言核对 LabelCell 状态/值；新增并发目标保护方法。更早的 assist 无 prior 使用 `{}` 中性回退、消费者 UTF-8/计时/Mock/本地发动句夹具修复也保留，不重新修改并行构筑公共夹具或解析器。

最近新增的 `tests/test_multifactor_inference_v3.py` 有四个无更新工程方法，`tests/test_multifactor_v10_resources.py` 有五个资源回收方法；原 `test_multifactor_learning_v3.py` 包含 V16 双正格梯度及严格恢复/竞态方法。不得为新阶段清空这些成果。

## 已执行证据与禁止重复事项

- [Q1/Q2 报告](2026-11-09-axis-generic-m7-q1q2.md)：13＋30 项首次通过。
- [Q3/Q4 事实路径](2026-11-09-axis-generic-m7-q3q4-facts.md)：Q3 35、Q4 54 个不同方法最终通过，含 V21 内存 SQL ASC/DESC 与 hash seed 四格工程子进程；初始失败、具体修复和复验保留，前阶段累计 132/166。
- [Q4 神经](2026-11-09-axis-generic-m7-q4-neural.md)：25 项首次全过，CPU 编码/预测和实际完整查询/副本评分；累计 157/191。
- [Q5](2026-11-09-axis-generic-m7-q5.md)：首轮 29 项 24 通过、1 failure、4 error；精确修复并新增竞态后六项复验全过，30 个不同方法/35 次执行，累计 187/226；工程 Adam step 22，save/load 16/14，临时文件结束无残留。
- [V10](2026-11-09-axis-generic-m7-v10.md)：5 项首次全过，累计 192/231，生产与既有测试未改。

相应 `.cache/axis-generic-m7-{q1q2,q3q4-facts,q4-neural,q5,v10}-20261109-01` 目录保留原始 JSON/日志；后四批有 acceptance-summary.json，Q1/Q2 直接看 q1-result.json/q2-result.json。V10 document-review.json 已通过：主计划 2–8 节、M7 历史/能力段、MASTER 原内容保留；13 个新增链接有效、无新增空白、tracked diff check 退出 0。

没有新代码影响或具体疑点时，直接复用这些证据，不重跑全套、不做 discovery、全仓哈希或重建基线；新阶段修改后只验收新行为和直接受影响集合。真实资料、正式训练、真实 CB/引擎及 CI 全部仍未执行。

## 本轮初步观察与下一步顺序

这些是刚读取文件得到的初步观察，尚不是整个模块源码审计结论。新主进程先核对设计与实际符号，形成总机械执行补充后直接实施，不再仅更新 M7 状态：

1. 先把主计划 T1–T5 每阶段拆成“需要交付的代码/工程验收”和“被禁止的真实运行”。核对已有实现，复用有效部分；明确整个软件交付退出标准。缺真实数据不能自动变成源码阻塞。
2. T1 的 prepare_v3 已有来源隔离/缓存/迁移工程检查；继续核对入口和输入契约及软件缺口，只用人工记录或临时 SQLite/gzip 夹具，不打开真实 catalog/deck_cache 或生成真实分片。
3. T2：当前 config.train.v3.json 是 64/2、CUDA、batch 16、epochs 12、minimum_improvement .0001、formal_training=false；主计划第 8 节建议 AdamW/weight_decay/dropout、微批 32/有效 64、最多 20 轮/耐心 4/最小改善 .002。当前 train_v3 的循环按批调用 RoleTrainer.train_supervised，graph_training 用当前 Adam 路径。应核对哪些是既定需求、哪些只是运行建议，补齐实际需要的优化器/批量/早停/恢复配置，不能盲目把旧方案数字当缺陷或为对齐数字跑正式训练。工程夹具允许有限计算和保存恢复，真实配置继续暂停。
4. T3/T4：当前 train_v3.fit/_fit 主要是基础训练和 validation 开发评估；finish 明确 development-only，返回 calibration_fitted=false/capability_accepted=false。ASSESSMENT_PROTOCOL.v3.json 声明分组隔离和 raw/calibrated/applied，CandidateScorer 接受 calibrator 回调。初步文件定位没有看到独立 v3 消融/拟合校准/发布工作流，需继续确认后补齐实际软件缺口，保证训练、选模、校准、最终评估来源隔离，未覆盖类别拒绝能力发布。只跑人工工程对照，不消费真正留出资料或激活模型能力。
5. T5：当前 RoleTrainer.enable_lora 对 axis-graph-v3 明确拒绝，environment_value 仍 disabled；adapters.py 已有旧版绑定底座的工程 LoRA 机制，目标是旧 readout/role/compatibility/utility/pair 模块。继续核对 v3 环境支路及隔离/保存恢复的代码需求，补齐可工程验收的实现，保持既有基础路径输出不变、默认环境能力关闭；真实环境反馈/训练/能力收益继续未验证。不要仅因真实阶段未获准而把全部环境软件留空，也不要据随机工程更新释放能力。
6. 核对纯 CB hints/宿主同意握手能否在真实搜索入口拦截下完成契约验收；真实 CB/原生引擎继续为 0。必要源码接线可改，但不能改变构筑定价/政策或代替并行构筑任务。
7. 每批按真实依赖推进，不每批向用户重新索取同一授权。完成全部源码、必要新测试与直接回归、配置/CLI/API/文档和自包含交付后，再给出整个模块的软件完工结论；运行能力未验范围单列，不以 M7 结束作为总目标结束。

## 执行规则、环境和交接要求

正式规划/修改长期编程文件前，读取 `C:\Users\27499\.codex\instructions\code-work.md`，交付其要求的机械执行书；先读真实代码，再列明确文件/符号、动作、不变量、验证命令、通过和失败条件。非 UI 机械书不是审批门槛，交付后继续已授权实施。读取并应用 `C:\Users\27499\.codex\skills\preserve-intent-and-execute\SKILL.md`，不扩展成额外全局审计或反复证明。

已有可用环境 `E:\Ana\envs\pcacgate\python.exe`，Python 3.10.20/Torch 2.2.2。此前工程检查使用 -B、PYTHONDONTWRITEBYTECODE=1、PYTHONPATH=实际仓库/src;实际仓库、OMP/MKL 各 2 线程，TEMP/TMP/Torch 缓存/日志在 N 盘本任务专属 .cache 子目录；Windows 必要时 PATH 加该 E 环境 Library/bin/Scripts 等 DLL 目录。不要升级或复制环境，不需要 GPU 实机或安装新模型来完成软件交付。新大体积资产走 E:\CodexData 的既有存储规则，本任务没有真实下载/训练需求。

用户 AGENTS 提问等待规则继续有效：一旦提出实质选择或权限问题，依赖该答案的检索、设计、实施及交付全部暂停，收到真实回答才恢复，不把沉默、预选或工具 accepted 当同意。本次运行权限问题已经真实回答，没有待答事项，不要再问是否解除禁令。

长任务优先继续并允许自动压缩。若压缩或阶段边界会损害准确性、约束、文件状态或验证质量，先完成当前非破坏性原子步骤，再主动建议新任务并给出独立交接；未经用户明确授权不创建。用户已对本次续办给出“新开或原处继续均可”的选择权。后续交接首条提示仍须重申本规则，不声称精确上下文占用百分比。

新任务首条提示建议：按本摘要自主完成整个轴与泛用识别模块的源码与允许的工程交付，先交付总机械执行补充后直接实施；不要停在 M7 或逐批等指令。保留正式训练/真实准备/CB/原生/CI 禁令，主进程执行，无子代理，保留全部改动，复用已通过证据并按实际修改做必要验证，直到整个软件目标完成。
