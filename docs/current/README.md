# YGO-Kito 现行设计

版本：2026-11-11。此目录是唯一现行设计入口；正文描述目标行为，执行进度、运行结果与历史授权记录放在 docs/reports。后续修改直接修订对应正文，并在修订表登记，不再向入口叠加阶段状态。

| 正文 | 内容 |
| --- | --- |
| [总体设计](architecture.md) | 产品目标、模型职责、数据与决斗边界 |
| [构筑流程](construction-workflow.md) | S0—S6、静态构筑、基础 CB、暂停与续接 |
| [构筑评分与扣分](construction-scoring.md) | 功能分、主题加权、P/V1/V2/S、Side 与未知 |
| [模型与服务接口](model-interfaces.md) | 数据身份、统一 Evaluation、学习反馈、Agent 与恢复 |
| [训练与验收](training-and-acceptance.md) | 三期课程、20/50 条件反馈、预算、正式验收 |
| [修订与来源](revision-map.md) | 旧稿有效内容去向、明确替代与未定参数 |

软件操作说明保留在 [development](../development)，最新运行状态见 [基线整合报告](../reports/2026-11-11-baseline-consolidation.md)。历史报告只证明当时结果，不覆盖这里的规则。项目资源位置、工作树及资产说明见 [仓库入口](../../README.md)。

本次归一不重启训练、构筑试跑或 CB；各作业仍按其实际暂停存档及后续用户指令执行。
