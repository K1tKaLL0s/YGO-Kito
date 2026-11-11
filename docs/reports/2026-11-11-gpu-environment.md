# 2026-11-11 GPU 环境检查

结论：现有 GPU 环境可运行项目四角色的 CUDA 小样计算、参数更新与状态恢复；正式训练与正式运行统一采用 GPU 的要求已写入现行设计。Python 版本和旧课程设备入口仍需迁移，未将环境小样写成完整课程验收。

## 实测环境

| 项目 | 实测 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU，8 GiB，计算能力8.9 |
| 驱动 | 617.42 |
| Python | E:\Ana\envs\pcacgate\python.exe，3.10.20 |
| PyTorch / CUDA runtime | 2.2.2 / 12.1 |
| cuDNN | 8801 |
| CUDA 可用 | true |
| 小样峰值 CUDA allocated | 69,089,280 bytes，约65.9 MiB；不含其他进程和驱动占用 |

基础128×128矩阵前向、反向和有限数检查通过。通过实际计算验证运行时兼容；PATH 未发现 nvcc，现成 Torch CUDA wheel 的本次计算不依赖本地 nvcc。未安装或修改驱动、Torch和CUDA。

## 项目级小样

临时检查使用现有模型和仓库合成夹具，固定 CUBLAS_WORKSPACE_CONFIG=:4096:8，所有结果位于 cuda:0。决斗模型参数改变、损失有限、保存恢复相同；目标/优化两个模型分别改变11,340/11,080个参数元素，配对状态保存恢复相同；统筹实际更新后保存，恢复后的下一次更新与原进程一致。检查未读取正式训练权重，未启动原生对局或正式训练。

首次夹具遗漏构筑batch_cursor更新，保存合同正确拒绝；修正夹具完整角色更新边界后，在新输出目录全项通过。重复输出路径也按独占创建合同被拒绝，未覆盖已有检查产物。检查脚本和原始结果保留于 .cache/consolidation-20261111/gpu_check.py 与 gpu-final/results.json；摘要纳入本报告，缓存不强制入Git。

Torch提示未编译Flash Attention，当前常规attention计算正常；不能据此推定长序列吞吐。

## 真实入口与剩余项

认知入口 scripts/axis-generic-training.ps1 默认使用上述Python，配置training/axis_generic/config.train.v3.json明确device=cuda:0，脚本设置CuBLAS和线程环境。另一项v30/b19训练工作正在准备/执行，按其专门配置与回执运行，本轮不改其环境、配置或状态。

构筑 scripts/run_construction.py 已有 --device cuda:0，并记录实际forward的参数/输出设备；CUDA不可用会拒绝，旧CPU训练检查点只作显式推理迁移，不改写原权重。原GPU短试运行已证明24次前向，但完整静态评价、S4/S5与CB未通过，本次不重跑。静态评分、规则引擎、I/O仍含CPU工作，GPU可用不会自动消除其性能瓶颈。

pyproject.toml要求Python>=3.12，而当前GPU环境为3.10.20；源码路径导入及本次小样可运行，但该环境不符合标准安装声明。正式整项目运行应配置独立Python>=3.12的CUDA环境，再验证所用依赖及完整入口；不直接升级正在使用的共享pcacgate环境。

旧duel-train-cpu/build-train-cpu等命令及local_foundation_course.py保留CPU工程语义。CourseModels.from_state、checkpoint_execution严格绑定设备/RNG，不能通过改元数据冒充CPU→GPU训练迁移。后续正式课程需显式GPU初始化或经过验证的训练状态迁移；本次检查没有完成这项入口改造，也未恢复暂停课程。

CPU白名单环境为WSL Python3.12/Torch2.9.1+cpu，仅作软件回归。GPU原生引擎整链路、真实课程吞吐、显存容量边界、长时间稳定性与正式能力验收仍按实际课程测试。
