# 2026-11-11 独立 CUDA 环境与真实课程迁移

## 实施范围

主进程建立独立 Python 3.12 CUDA 环境，将已闭合的旧 CPU 课程迁移至新的完整状态目录，验证四角色真实更新及恢复，接通正式入口并保留课程暂停。认知训练的 pcacgate 环境、配置、权重、运行进程和并行源码不属于本次修改范围；没有启动长时间课程、远程作业或新增对局资格。

实施前已交付机械执行书，按环境/依赖锁、实际训练状态迁移、入口与回归、文档清理、选择性提交顺序执行。真实恢复发现清单兼容缺陷后另行交付精确修复补充。

## 环境与依赖

| 项目 | 实测结果 |
| --- | --- |
| 解释器 | CPython 3.12.14 |
| PyTorch / CUDA / cuDNN | 2.9.1+cu128 / 12.8 / 91002 |
| NumPy / SciPy | 2.3.5 / 1.16.3 |
| GPU | RTX 4060 Laptop GPU，计算能力 8.9，8,585,216,000 bytes |
| 驱动 | 617.42 |
| 正式环境 | `/home/chaos/.local/share/ygo-kito/cuda312` |
| Python 工具链 | `/home/chaos/.local/share/ygo-kito/python312` |
| 实体存储 | N 盘 WSL VHDX；安装下载与临时缓存使用 E 盘 |
| 依赖锁 | `requirements/cuda-linux-py312.txt`，28 个精确版本和 wheel 哈希 |
| 锁文件 SHA256 | `26b4f7ea73343fe9282131aab4c10ddec99be976603a27e06d6e563d7606bbfb` |

使用 `--require-hashes` 安装，`pip check` 无冲突，项目 editable 安装成功；实际已安装版本与 CUDA 锁一致。128×128 CUDA 矩阵前向/反向及有限数检查通过，峰值 allocated 17,302,528 bytes。锁文件最终统一为 LF，依赖版本和 wheel 哈希未变化。

环境在 Linux 原生文件系统中，资源保留 N 盘原位置。旧 `E:\Ana\envs\pcacgate` 不升级，CPU 锁仍供软件回归。正式本地入口通过 `configs/local-cuda-runtime-v1.json` 定位此环境，不再调用资源根内旧 CPU venv。

## 课程与恢复合同

迁移源为 `N:\YGO-Kito\_local_cpu_20261027\reports\optimization-20261031\2207-course-006`。源 checkpoint-1 SHA256 为 `67de51d0910d144ae71b4c89352486f227f534fdda8e8ccb39809ab96c8d5637`，active_seconds 为 3975.8590677600023。原 27 条记录仍属历史记录，不能改称本次新增正式对局。

迁移先恢复真实源对象，再移动四角色参数、Adam 状态和适配器；保留调度器、CPU/独立采样 RNG、学习游标及课程反馈。CUDA 使用种子 20261111 建立显式新随机边界，不声称 CPU→CUDA 逐位连续。DataIndex 使用 SQLite 备份并验证逻辑身份。普通恢复的设备合同保持严格。

首次真实恢复失败于 `restored checkpoint manifest is not anchored by the current checkpoint`。诊断确认保存与当前绑定仅 `source_map` 不同，源文件哈希与清单相符。修复让检查点链保留原 `owner_binding_sha256`，旧格式从保存 binding 推导；新状态继续记录当前源码。未关闭文件哈希、大小、顺序、结构、DataIndex 或对手资格校验，也未修改历史源权重。

随后新边界的首次安全加载拒绝迁移事件中 `torch.__version__` 的 TorchVersion 对象。公共入口改为保存 `str(torch.__version__)`。仅对本次尚未发布的目标作元数据修复，受限加载只临时允许该已知类，语义树摘要前后一致；重写后立即以普通 `weights_only=True` 加载通过。目标文件哈希由 `7ddf4e7ac9d0ffb5dd3892076c7711838fdbb67329b0a38f3fd7df6dad73c264` 变为 `e8cd8ad58880135dfe832cab6ad9031eba2baf343f202e2e395cffef0ec82352`，源 CPU 文件未改动。原失败日志和修复回执分别保留，未将最初命令记作一次成功。

真实迁移已通过完整恢复及既有对手资格准入，目标为 `reports/gpu-course-20261111/2207-course-006-cuda`。DataIndex 逻辑身份为 `7bd241c776bf61f80435f954e5b809dff204330f17b11cc6d4204efb79430d5a`。目标/优化更新为 5/0，构筑 batch 为 5，决斗更新/episode 为 27/27，统筹更新为 37，training_attempt_cursor 为 27；现行有效课程计数 BO1=2、BO3=0，均保留旧值。新成功回执 `cuda-migration.json` 的 `restore_verified=true`，`formal_training_started=false`。

## 验证记录

- 独立合成夹具：四角色前向均在 cuda:0，反向及优化器实际改变参数；从同一 GPU 边界恢复后，下一次 loss、参数、优化器、调度器、适配器及 RNG 结果一致。峰值 allocated 68,854,272 bytes。
- 真实课程首次合成更新检查在决斗输入处拒绝占位卡号 1，正式词表校验保持正确。验证工具改为使用当前模型词表中的卡号，在新的独立输出目录复验；失败检查没有保存正式课程进度。
- 真实课程复验通过：基础训练四角色前向均在 cuda:0，实际反向/优化器/调度器更新后，从同一边界恢复的下一次 loss、参数、优化器、调度器与 RNG 一致。峰值 allocated 99,681,280 bytes（约 95.1 MiB）。CPU/LoRA 夹具与真实基础状态两条路径均有实际 GPU 证据。
- 新 CUDA 环境定向批：59 项，首次 56 通过、2 失败、1 错误、0 跳过。两个失败是 CPU 锁依赖断言在 CUDA 环境中的预期不匹配；同一部署模块 13 项在此前 CPU 环境逐项通过。启动测试旧夹具错误已修复，单独复验通过。未把首次整批登记为全通过。
- 清单修复批：8/8 通过，包含实际存储检查点、历史格式及两次源码漂移的保存恢复、清单篡改拒绝和结构兼容单元检查。
- 相关保留策略批：8/8 通过，覆盖最近/初始/里程碑检查点保留、文件及清单篡改、用户文件不进入清理集合和空间上限。
- 原 CPU 全组选定检查两次在 240 秒限时内未完成。另有未修改的 pilot 索引限制测试失败，未扩大为本次修复任务。旧 Windows Python 3.10 的 tomllib/unittest 环境限制不作为项目 Python 3.12 结论。

原始结果保留于 `.cache/gpu-migration-20261111`，失败与复验分别记录。没有完整 CPU 白名单、远程 CI、真实课程吞吐或长期稳定性结论。四角色合成更新不是对局训练成绩。

14 个本次 Python 文件的 AST、8 份说明中 37 个本地链接、PowerShell 解析和锁文件哈希一致性检查通过。E 盘本次专用下载/安装临时缓存已核对非联接后清理，移除 4,123,937,724 bytes 下载内容；正式环境与原 CPU 迁移来源保留。

## 使用与当前边界

操作见 [CUDA 环境与课程迁移](../development/cuda-runtime.md)。`Check` 检查解释器与路径，`ValidateRestore` 完整恢复并运行既有对手准入检查，不启动 worker。完整 `course/latest.json` 是恢复权重来源；旧 initial-pointer 仅支持尚未形成最新边界的历史导入，不再为新迁移生成重复初始全量权重。

`duel-train`、`build-train` 默认 CUDA；原 CPU 命令为同一实现的回归别名。没有复制一套旧执行器。资格源码审阅覆盖本次实际统筹工作树，包括当时并行认知源码的哈希；换到不同源码状态仍须通过精确审阅，不能把此回执复用于任意工作树。

有界验证完成后，已在 active.mutex 保护下将 `reports/course-continuation.json` 原子切到新 CUDA 目录。切换前核对源 CPU 与新 CUDA 检查点的哈希均未被验证过程改写。`reports/training.hold.json` 保持原样，未启动正式课程，也没有消耗新的课程训练计数。

正式 PowerShell `Check` 和 `ValidateRestore` 均成功。后者实际返回 `required_device=cuda:0`、`restored_device=cuda:0`、`restore_verified=true`、`training_held=true`、`worker_started=false`，使用独立 cuda312 解释器及当前统筹源码。完整结果见 [机器可读验收回执](2026-11-11-cuda-course-migration.json)。

临时传输包、一次性脚本和验证权重清理 35,991,372 bytes，Linux 原生临时测试源码清理 18,601,131 bytes。小型原始结果、失败/复验日志及真实完整状态继续保留。既有 CPU 来源与仍供回归使用的 CPU 环境不属于临时副本，不删除。
