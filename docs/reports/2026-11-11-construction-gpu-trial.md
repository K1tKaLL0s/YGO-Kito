# 2026-11-11 GPU 构筑快速试运行

结论：本次未跑通构筑全流程。真实 GPU 推理和两份完整候选生成已通过；统一静态评分未完成，因此没有候选最终分、参考分、80% 比较结果或准入结论，基础 CB 未执行。此前 R0—R11 的静态修复通过记录不能代替这次实际运行结果。

按用户“快速试运行”的范围，主进程在发现静态组合评价持续增长后请求安全保存结束。本次没有用户主动暂停指令；程序通用 SIGINT 标签记录为 `user_pause`，实际停止发起者为助手，已在 inspection.json 中单独注明。无正式训练、参数更新或旧 run-007 恢复。

## 实际输入及阶段结果

使用当前完整源码 `_publish_20261030`，规范化 v30、效果字典 b19、质量评分 v4。既有 course-006/checkpoint-1.weights 严格按原资源及模型绑定恢复后，显式把本次内存推理模型放到 cuda:0。原检查点不改写，不改变训练恢复的设备校验。

环境为 2022.7 禁表、2022-09-30 发行截止、setcode-181 珠泪目标；原环境允许的 12,237 个卡号全部保留。宿主每批候选预算明确设为 2，牌表目标 40/15/15，参考比例仍为 0.8。参考使用原指定 2207 牌表，不作候选种子。online 的 120 秒仅停止新增候选，按设计继续排空当批评价；它不是总运行硬超时。

| 检查项 | 本次真实结果 |
| --- | --- |
| 资源校验、原权重恢复 | 通过 |
| S0 任务固定、S1 逻辑及骨架 | 完成，任务与过程已保存 |
| GPU 推理 | 目标模型 12 次、优化模型 11 次、统筹模型 1 次；输出均为 cuda:0 |
| S2 候选生成 | 生成 2 份 40/15/15 牌表 |
| S3 候选统一静态评价 | 0 份完成，2 份待评；第一份仍在 resident 投影 |
| 指定参考统一评价 | 未开始形成 Evaluation，参考分为空 |
| S4 静态分排序、S5 80% 参考比较 | 未完成，Gate 为空 |
| S6 基础 CB | 已在宿主显式授权，但静态前提未满足，未执行 |
| 参数更新 | 前后均为 build_goal=5、build_optimizer=0 |
| 保存恢复资料 | revision=11；kernel 与 session 内容一致，无遗留 tmp 文件 |

运行环境为 WSL、Python 3.12、PyTorch 2.9.1+cu128、CUDA 12.8、RTX 4060 Laptop GPU。峰值张量分配显存 37,841,920 字节（约 36.1 MiB），峰值保留显存 39,845,888 字节（38 MiB）。这属于小模型推理实测，正式 GPU 训练、反向更新及训练恢复未在本次执行。

## 本次修复

1. 真实 CLI 原先没有 GPU 选择，按旧 CPU 检查点继续运行。新增显式 `--device` 和实际 forward 设备回执，CUDA 不可用时报错。
2. 首次 CUDA 前向真实触发确定性 CuBLAS 配置缺失。入口在加载 Torch 前设置缺省 `CUBLAS_WORKSPACE_CONFIG=:4096:8`，保留确定性计算；后续 24 次实际 CUDA 前向成功。
3. 新增宿主候选预算选项及源绑定。本次使用 2，完整卡池、目标和评分保持；不同预算存档不能混恢复。
4. 暂停时旧导出把一张未完成骨架写成默认 deck.ydk，而两份完整待评候选只留在存档。现修正为骨架单独写 skeleton.json，待评候选逐份导出并标记未评价，完整当前候选才写默认 deck.ydk。已用本次真实存档调用修正后的导出函数。

两次启动定位另有命令/临时环境问题：首次 workspace 指向 source 子目录过窄，已恢复为资产总根；单独恢复的 /tmp 规则缓存在下一次调用时不存在，改为同一 WSL 命令内解包既有缓存并立即运行。完整资源校验保持，资源阶段从直接跨盘约 232 秒降到约 5 秒。未下载、编译或替换规则资源。

## 尚未通过的运行瓶颈

用户后续已将“枚举及其他直接计算方式可能造成计算量过大”列入待优化事项。该解释作为待验证的性能原因保留，本轮不继续优化或恢复试运行；当前先交付两份候选的中文卡名及投入数量。

有效 run-004 总耗时 583.011 秒（9 分 43 秒，含启动和终态导出），完成 10 个内部保存片。最终第一份候选读入 30 个卡片记录，resident 关系计算保留 727 个状态、27 项队列、79,228 个累计分配步骤，尚未进入用途与联合用途的后续游标。活动项是 theme joint fact。kernel 增至 58,991,162 字节，result 因包含过程与续算资料为 173,950,005 字节。

前后存档中的队列和分配步骤有变化，不能据此判为死循环；实际结论是当前 CPU 静态组合评价与状态保存开销不满足这次快速试运行，GPU 推理没有解决此处瓶颈。相关实现入口为 construction_layer_flow.py 的规范化/关系投影及 construction_relations.py::relation_index、_shared_allocation。下一步应从本次真实活动项剖析分配枚举和重复状态成本，修复后恢复同一批候选，再验证候选及指定参考的完整计分。没有降低公式、删参考、截断后填零或把模型排序分当成最终静态分。

## 工件与验证

- [完整检查摘要](../../.cache/construction-gpu-trial-20261111/inspection.json)
- [修正后导出目录索引](../../.cache/construction-gpu-trial-20261111/delivery/candidate-exports.json)
- [待评候选 1](../../.cache/construction-gpu-trial-20261111/delivery/pending-candidate-01.ydk)、[待评候选 2](../../.cache/construction-gpu-trial-20261111/delivery/pending-candidate-02.ydk)
- [候选 1 中文卡名及数量](../../.cache/construction-gpu-trial-20261111/candidates/candidate-01.json)、[候选 2 中文卡名及数量](../../.cache/construction-gpu-trial-20261111/candidates/candidate-02.json)
- [GPU 实际调用回执](../../.cache/construction-gpu-trial-20261111/run-004/device.json)、[完整运行日志](../../.cache/construction-gpu-trial-20261111/run-004.log)
- [权威存档](../../.cache/construction-gpu-trial-20261111/run-004/kernel.json)、[终态摘要](../../.cache/construction-gpu-trial-20261111/run-004/summary.json)

run-004 原始 deck.ydk 保留了修复前的一张骨架导出，是缺陷证据，不是交付构筑。用户使用上方 delivery 中两份完整待评牌表；它们均尚未通过质量评价。

设备、候选预算、暂停/恢复共 6 项回归通过；导出补修后的 CheckpointTests 3 项通过，合计 7 个不同测试方法，无失败或跳过。4 个受影响编程文件 AST 通过，按既有 CRLF 行尾检查无新增空白错误。未运行全量 CI 或原生故障测试。工作树原有大量未提交、未跟踪修改，本次没有把它们合并成提交，也没有远程推送。

[执行书](execution/2026-11-11-construction-gpu-trial-execution.md)记录实施范围及实际补修。
