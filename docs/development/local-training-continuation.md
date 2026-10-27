# 本机基础训练与断线接续

当前独立工作树为 `N:\YGO-Kito\_local_cpu_20261027\source`。原 `N:\YGO-Kito` 工作树保留。本机 CPU 路线使用既有 `Chaos-Ubuntu-26.04`、项目隔离的 Linux Python 环境和锁定资源；Windows 与 Linux 的 Python 包分别安装。

## 启动、查看与安全停止

在 PowerShell 中运行：

```powershell
N:\YGO-Kito\_local_cpu_20261027\source\scripts\local-training.ps1 -Action Start -Job course -RunId local-course-001
N:\YGO-Kito\_local_cpu_20261027\source\scripts\local-training.ps1 -Action Status -Job course -RunId local-course-001
N:\YGO-Kito\_local_cpu_20261027\source\scripts\local-training.ps1 -Action Stop -Job course -RunId local-course-001
N:\YGO-Kito\_local_cpu_20261027\source\scripts\local-training.ps1 -Action Resume -Job course -RunId local-course-001
```

`Start` 创建隐藏的普通 WSL 客户端进程，并以独立会话运行注册的学习任务。项目独占锁记录 Linux PID、启动时间和 boot ID。`Status` 验证现存进程身份并报告心跳年龄；发行版未运行时只读取保存状态。`Stop` 写入合作式停止请求，在完整小局、配对案例或参数更新边界保存后退出。

`Resume` 复用同一运行和课程身份，读取完整模型、优化器、调度器、RNG、DataIndex 与游标。已有完成标记拒绝重复执行；不确定的在途对局或更新保留，要求检查，不能自动清除后重打。旧进程仍存活时禁止第二个学习进程。

日志、启动回执和状态位于 `_local_cpu_20261027/reports/local-training/<RunId>/`。短暂聊天连接或外网中断不参与本地进程生命周期。所需数据已在本机时可以继续运行。主机睡眠、关机和 WSL 关闭会中断进程；脚本没有安装服务、开机任务或修改电源、网络与安全设置。

## 实际学习链

`local_foundation_fusion.py` 是第一个具体课程实例：效果标签与独立粗连接、狭义主题主轴、具体公开卡文绑定、模型排序填卡、合法动作搜索与回放，再由实际核验样本更新目标基础参数。

`construction_effect_blocks.py` 当前收录珠泪的人工公开卡文评审实例。消费者使用通用标签、卡文摘要和来源绑定；任务/证明接口支持已有通常召唤、同调、超量与新增的效果处理型融合目标。具体融合证据绑定已处理效果链、融合原因素材移动、目标召唤和公开场面。仅特殊召唤一只融合怪兽不足以证明融合召唤。

这些是有界目标路线证据。任意整张效果图的执行、任意卡效理解、过程型/接触融合、使用对方素材等范围仍需各自实现和验证，不能由第一个实例推出完成。

`local_foundation_comparison.py` 使用冻结的实际决斗模型、同一已审计 C# 对手、4 个训练种子、双方席位与两份实际生成且有目标路线证据的构筑，执行 16 个正常 BO1 和私有回放。两次以上不同种子支持且各配对方向一致时才形成训练偏好。全负、平分或矛盾结果不补造标签。这些比较不计正式场数，也不作为独立强度验收。

`local_foundation_course.py` 通过现有 `ScenarioCourse` 接续基础参数 PPO 与完整大场计数。已有比较的正常终局/回放和相同资源身份可作为本期 bot 运行证据，保留原回执与明确源码迁移记录，不另加资格批次。`local_course_collaboration.py` 在训练块之间继续四段构筑推理、引擎样本目标学习、真实调度记录学习与冻结驾驶比较。优化角色只消费实际严格比较，缺标签时如实保持未更新。

初始本机课程只供应已有且当期合法的 CyberDragon bot 基线。常见主题、强参考内战与独立验收覆盖仍需补齐；不能将这个对手改名充抵覆盖。预测监督尚未完成时不得将整百事件或无条件重构作为预测反馈证据。四段推理、各角色基础参数更新与竞技改善分别记账。

## 状态与资源

完整状态位于 `.cache/local-base-training-20261027/`，课程有独立的 checkpoint、DataIndex、模型绑定、原始构筑证明与反馈消费账本。正式训练沿用每期完整 600 BO1 + 400 BO3 的慢档。训练、构筑比较、独立评估分开计数；未完成和异常不充场数。

Linux 原生 core 与完整 Ice WindBot 在本机重建。固定源码来源见 `configs/native-sources.lock.json`、`configs/bot-sources-v1.json`。实际构建/审计回执记录本机二进制摘要，与云端旧二进制分开保留。运行缓存从这些本机锁定字节生成，逐文件核对身份，减少 DrvFS 小文件开销；不替换引擎规则或合法可见 DTO。

`pack_formal_course_source.py --base <本机项目基目录>` 保存不可变的 Python 执行快照。已建缓存不能被静默覆盖；修改执行代码后需要明确迁移并保留旧记录。运行时读取资源、磁盘、停止请求和既有预算条件，Codex 当前剩余额度到 20% 时保存停止，不使用重置卡。

GitHub 草稿 PR #8 保存云端原始恢复包和源码改动。本机继续成果更新同一草稿 PR，保持不合并。模型、优化器、RNG 和训练账本属于用户授权公开的恢复资产；第三方 CDB、Lua、core 与 bot 运行文件按固定来源和许可恢复。恢复包本身不是完整第三方运行环境。
