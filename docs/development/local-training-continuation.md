# 本机历史课程的状态与接续入口

当前源码使用 N:\YGO-Kito\_publish_20261030，旧 _local_cpu_20261027/source 仅保留.cache资产。下列入口用于既有CPU课程的检查和状态管理；后续训练与正式运行按 [现行训练设计](../current/training-and-acceptance.md) 使用GPU，GPU课程入口/状态迁移的未完成项见 [环境检查](../reports/2026-11-11-gpu-environment.md)。

在PowerShell中只读检查：

```powershell
N:\YGO-Kito\_publish_20261030\scripts\local-training.ps1 -Action Check -Job course -RunId local-course-001 -ResourceBase N:\YGO-Kito\_local_cpu_20261027
N:\YGO-Kito\_publish_20261030\scripts\local-training.ps1 -Action Status -Job course -RunId local-course-001 -ResourceBase N:\YGO-Kito\_local_cpu_20261027
```

脚本从自身所在工作树定位worker和supervisor，ResourceBase定位既有venv、reports与状态。独立工作树执行时显式传入N盘ResourceBase，避免把大体积资源写入应用的代码工作树。Check只解析现有迁移记录，不启动worker；Status核对已有进程身份，发行版未运行时只读保存状态。

Stop为指定现有run写合作式停止请求；Resume保留模型、优化器、调度器、RNG、DataIndex、游标及旧运行身份，在完整边界恢复。旧进程存活时拒绝第二个worker，完成标记不允许重放，training.hold.json仍生效。本轮未调用Start/Resume/Stop，不恢复暂停作业。

历史课程、原始比较及恢复证据保留于 _local_cpu_20261027/reports 与 source/.cache；资源绑定保持原位。已删除的local_foundation_fusion.py不再作为启动入口，当前已登记课程使用local_foundation_course.py。旧四段构筑流程已由S0—S6替代；历史运行结果只见对应报告，不作为现行设计。
