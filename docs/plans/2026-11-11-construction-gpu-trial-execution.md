# GPU 构筑快速试运行执行书

用户目标：用 GPU 跑通一次当前构筑流程，检查真实牌库、效果积木、目标/优化模型、候选生成、统一评分和指定参考对比。使用当前完整工作树，由主进程直接执行，不使用子代理。本次为短试运行，不启动正式训练。

当前证据：正式入口 scripts/run_construction.py 只能按原检查点设备恢复，未提供设备选项；course-006 为已有权重来源。当前规范化 v30、积木 b19、评分 v4。旧 run-007 保留，新的完整运行不消费其旧版本评价。

允许范围：scripts/run_construction.py 的显式推理设备及运行回执；对应定点测试；本轮发现且直接阻断流程的构筑模块；本轮运行目录及报告、当前索引。保持原模型结构、卡池、卡文资源、评分公式、主题加权、0.8 参考门槛和原始检查点。禁止修改无关已有工作、UI、凭据、原生 ABI/响应保护及正式训练状态。

1. GPU 接线。目标 scripts/run_construction.py::main/advance_construction。前提为严格按原绑定成功恢复 CourseModels；新增显式 --device，只在恢复验证完成后迁移内存中的推理模型并同步运行设备，不改训练检查点或设备恢复校验。登记实际 forward 输出设备、调用数和峰值显存；CUDA 不可用直接报错。新增 --basic-cb，静态 Gate 通过后才由现有 provider 执行基础 CB。验证：定点 CLI/暂停回归与真实 CUDA forward。通过标准为实际模型输出位于 cuda:0、权重更新计数不变；设备异常停止本次运行，不降级。
2. 真实短运行。目标新目录 .cache/construction-gpu-trial-20261111/run-001；使用已有 course-006 checkpoint-1.weights、原 model-binding、2207 环境和 setcode-181，完整环境卡池、40/15/15 与独立指定参考。采用 online 短候选生成窗口、每片一轮，窗口到期后仍完成当前批次 S3—S5。验证为日志、候选/参考 Evaluation、Gate 与 YDK 输出；不以时间到期或进程退出替代通过。真实异常保留 failure/kernel，定位后仅修直接阻断点，并从兼容边界续接。
3. 评分与交付。目标本次报告；核对候选与参考的版本、政策、分数/区间、完整性、0.8 比较及硬条件，核对 S4 实际选择和 S5 结论。静态通过才继续 S6；否则报告真实失败/未完成原因。GPU 承担神经网络，现有卡文/约束/组合计算仍由 CPU 执行，分别记录。验收为可追溯真实牌表与评分对照、设备证据、耗时和问题定位。

回归仅覆盖本次接线及实际失败点，不跑未筛选 discovery 或故障注入。原始检查点和已有未提交工作保持；本次若涉及旧修改文件，仅保留本次差异，不整树提交。未知项为 CUDA 环境可用性、旧权重与当前资源恢复兼容性及完整静态评价实际耗时；出现真实阻断按日志说明，不虚构成功或降低评分要求。

快速规模补充：AutonomousConstructionKernel 的宿主 source_binding 接受 construction_candidate_budget（2..32），生成原任务时只覆盖每批候选数量。该选项纳入原有 source 绑定，完整卡池、目标、硬条件和评分不变。CLI --candidate-budget 2 在严格恢复之后构造本次独立 kernel，保留模型累计更新计数；续接必须使用同一预算，既有绑定会拒绝不同预算存档。验证为候选预算合法性、实际任务的完整池及候选数量；不改旧检查点中的任务或旧 run-007。

实际导出缺陷补充：run-004 在尚无 Evaluation 时返回当前骨架，旧 CLI 将一张骨架导出为 deck.ydk，同时两份 40/15/15 实际候选只在 pending_quality 中。修改 scripts/run_construction.py 的结果导出：完整当前候选才写 deck.ydk；未完成骨架写 skeleton.json；待评真实候选逐份输出 pending-candidate-XX.json/ydk 并标记 static_evaluation_pending，不冒充已选择/通过。测试使用不完整骨架和完整待评牌表，要求无默认 deck.ydk、待评牌表完整、评价状态真实。run-004 原始证据保留；对其保存数据在新 delivery 目录执行相同导出函数，不重算或重跑模型。
