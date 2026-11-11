# 轴与泛用 v3 自动训练交付与真实资料准备

2026-11-09，香港时间。主进程直接实施，无子代理。用户要求准备正式训练并交付一键本地运行脚本；本轮不启动长时正式训练。用户随后指定新文件保留在 N 盘本项目内，已应用到数据、工件、日志和临时目录。原始资料、旧 runs、活动模型与既有/并行源码改动保留，没有提交、推送、CB、原生引擎、整仓 CI 或模型激活。

## 交付

仓库根的 [Start-Axis-Training.cmd](../../Start-Axis-Training.cmd) 为双击正式启动/恢复入口；[PowerShell 入口](../../scripts/axis-generic-training.ps1) 默认只准备，`-Start` 明确启动，`-Status` 只读保存状态。[使用说明](../development/axis-generic-automatic-training.md) 给出完整路径、命令和恢复方法。[机械执行书](execution/2026-11-09-axis-generic-automatic-training.md) 包含原范围和实际准备暴露问题的实施补充。

新增 automatic_v3.py 和 config.automatic.v3.json，只编排现有 v3 API。配置、输出身份、来源组、实际 best、完整预测工件和后处理绑定保持；同一命令可恢复，完成后再次启动没有新训练更新。默认记录本地日志、事件、阶段、错误、耗时、CPU 用时、CUDA/磁盘与峰值分配，运行时不调用 Codex 或外部模型/API。校准/评估明确配置，消融/环境实验使用既有独立显式入口。

train_v3.py 的 inspect_data 与实际 fit 共用选模预检，覆盖全部 18 任务；没有自动删除选择任务。首次更新前写初始快照；已发布但 latest 未提交的 checkpoint 通过当前完整绑定恢复，缺失可重建元数据重建。Windows 原子 JSON 替换遇同一路径短暂 WinError 5/32 时有限重试 6 次，持续拒绝仍失败，不改权限或退化为非原子写入。

## 真实来源与准备

读取的真实源为 118 个原案例和 v6_2 的 8525 条 train/validation 记录，合计 8643 条，目录涉及 2565 卡。旧源全部 previously_consumed=true，来源关联组成 30 个隔离组；不能标为新的独立测试。原始已知标签数量：large_axis 3007、small_axis 2866、strategic_core 1320、support_role 1686、generic_utility 7015。以上为迁移前原始单元数，不能当作迁移后的有效训练数。

20 个原案例 unit=null 暴露导入器兼容错误，已按空的可选单元元数据读取，功能未提供时保留 unresolved，不虚构标签。数据迁移继续撤回未审的变体与不在当前观察中的旧目标角色。

真实图准备暴露规范化对成组对称子图的重复枚举。先保留诊断，再将颜色 rank 改为完整元组比较，叶子仅比较精确属性类和全边表，最终仍序列化完整原数值。单点 twins 用完整边交换证明；整体对称支路用已安装 NetworkX 3.4.2 的有界精确自同构剪枝。唯一颜色固定节点的全部边界边进入匹配标签。没有近似 WL 键、卡名角色规则、丢行或减少源范围；现有准备实现指纹使旧语义缓存不能混用。优化后的两个较重原例为 740/717 节点，实测 1.015/0.844 秒；这不是整批平均时间。

准备每 128 条记录输出进度。早期无进度尝试及第一次自动准备在写入数据前停止，诊断/日志保留；最终完整准备使用相同源和新实现重新执行。

本次交付时，完整准备已经交由普通本地后台进程继续执行，尚未登记正式训练就绪。有效启动回执为 `N:\YGO-Kito\data\axis_generic\v3\preparation-local-launch.json`（2026-11-09 23:25:34 +08:00，prepare_only，PowerShell PID 114696，Python PID 42256）。已在启动器退出后的另一工具调用中确认 attempt 3 持续运行并写入 prepare 状态。23:23:55 的首次沙箱后台启动未存活，原 preparation-launch.json/空输出保留，不把它登记为有效后台进程；随后通过平台批准的普通本地进程启动成功。

先前前台准备已确认处理到 256/8643，切换时仍未发布数据；后台按同一来源从头执行，不能把这 256 条写成全量完成。

实时结果由脚本自行写入 `N:\YGO-Kito\data\axis_generic\v3\automatic-formal-20261109-001` 中的 state.json/events.jsonl，结束时生成 summary.json、coverage.json 和 reserved-partitions.json。准备目录为同级 prepare-formal-20261109-001，训练目标为同级 base-formal-20261109-001。本次后台命令没有 Start，不会进入训练；即使用户随后显式 Start，当前仅有旧五项角色标签的源也不能满足完整 18 任务，预检会明确拒绝而不缩减任务。真实迁移后的类别/坐标/校准组统计以自动产出的覆盖报告为准。

## 设备与验证

现有 Python 3.10.20、Torch 2.2.2、CUDA 12.1，RTX 4060 Laptop，8585216000 字节显存；CUDA 实际单元素分配及算术通过，不是只检测设备名。N 盘预检可用 333044621312 字节。解释器复用 E:\Ana\envs\pcacgate\python.exe，没有新安装或下载。

工程测试只使用有界人工 CPU 记录及项目内临时 checkpoint。覆盖：真实入口默认不训练、缺任务/零权重拒绝更新、CUDA 不可用拒绝回落、初始快照、未保存批次与连续训练数值一致、已发布快照元数据中断恢复、已完成不重复训练/预测、OS 锁、配置错绑、后处理错绑、准备原子发布/缓存、退出码与失败日志。规范化另用全部 64 个四节点无向图的穷举同构/改名和 8 个相同三节点支路、边数量变化/预算拒绝对照。

首轮 13 项有 11 通过、2 error：一项为测试误读 RoleInput 序列化层级，一项为状态文件短暂占用。修正后的两项均通过；随后相关 17 项全部通过，进度输出后的准备测试及精确规范化测试亦通过。最终交付集合为 21/21 通过（17 项新测试、4 项受影响既有测试），0 failure/error/skip，耗时 27.315 秒；全部批次共 65 次方法执行，首次 2 个 error 保留。静态结果见 .cache/axis-generic-automatic-20261109/validation-summary.json。

所有逐批日志保存在 `.cache/axis-generic-automatic-20261109`，包括 tests-first.log、tests-fixes.log、tests-final.log、tests-prepare-progress.log、tests-canonical.log、tests-canonical-final.log、tests-isomorphism.log、tests-isomorphism-boundary.log、tests-delivery.log，及真实源/图性能诊断。首次错误没有从历史抹除。此前整个模块 177 项结果按未变范围复用，本次不重跑全仓审计。
