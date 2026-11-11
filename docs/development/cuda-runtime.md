# 本地 CUDA 环境与课程迁移

正式课程入口使用 `configs/local-cuda-runtime-v1.json`：WSL 中的独立 CPython 3.12.14、PyTorch 2.9.1+cu128。环境位于 `/home/chaos/.local/share/ygo-kito/cuda312`，底层 WSL VHDX 在 N 盘。Python 工具链位于同级 `python312`。该位置使用 Linux 原生文件系统，避免 DrvFS 逐文件加载依赖的开销。下载缓存和安装临时目录位于 E 盘 `CodexData/caches/ygo-cuda-*`；模型、课程和资源保持 N 盘。

依赖使用 `requirements/cuda-linux-py312.txt` 的精确版本及 wheel 哈希；CPU 软件回归继续使用 `requirements/ci-cpu.txt`。不升级认知训练使用的 `E:\Ana\envs\pcacgate`。新主机需自行指定符合要求的 Python 3.12 基础解释器和环境路径，安装命令为：

```bash
python3.12 -m venv /path/to/cuda312
/path/to/cuda312/bin/python -m pip install --require-hashes -r requirements/cuda-linux-py312.txt
/path/to/cuda312/bin/python -m pip check
```

PyTorch 2.9.1 的 CUDA 12.8 构建见[官方版本表](https://pytorch.org/get-started/previous-versions/)。当前驱动是否满足运行时要求按 [NVIDIA 兼容表](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)及实际计算核对。独立依赖锁包含运行时库，不需要另安装整套 CUDA 编译工具链。

## 只读检查和恢复

在 Windows 当前仓库执行：

```powershell
.\scripts\local-training.ps1 -Action Check -ResourceBase N:\YGO-Kito\_local_cpu_20261027
.\scripts\local-training.ps1 -Action ValidateRestore -ResourceBase N:\YGO-Kito\_local_cpu_20261027
```

`Check` 定位解释器、资源、续接状态和暂停标记。`ValidateRestore` 进一步加载完整模型、优化器、调度器、随机流、课程和 DataIndex，并要求实际 CUDA 设备一致；不启动 worker、不保存课程、不消费训练样本。`Resume` 仍检查原 training hold 和监督器，环境迁移不会解除暂停。可用 `-RuntimeConfig` 显式选择其他已配置 Linux CUDA 环境。

## 显式 CPU→CUDA 迁移

在课程暂停且没有未闭合事务时，用新环境运行下列入口。目标必须是资源根内不存在的新目录；源检查点不会覆盖。

```bash
PY=/home/chaos/.local/share/ygo-kito/cuda312/bin/python
BASE=/mnt/n/YGO-Kito/_local_cpu_20261027
$PY scripts/migrate_course_cuda.py --base "$BASE" \
  --source "$BASE/reports/optimization-20261031/2207-course-006" \
  --target "$BASE/reports/gpu-course-20261111/2207-course-006-cuda" \
  --device cuda:0 --cuda-seed 20261111 \
  --source-review "$BASE/reports/gpu-course-20261111/observed-bot-source-review.json"
```

命令先按现行结构兼容规则恢复源课程，再搬运真实四角色参数、Adam 状态和适配器。调度器、CPU RNG、独立采样 RNG、任务/词表、累计更新、课程和反馈游标保持；CUDA RNG 使用命令中的种子创建新边界。CPU 与 CUDA 的数值和随机序列不要求逐位相同，同一 GPU 边界的保存恢复及下一次更新必须一致。

当宿主源码已不同于历史资格证据时，`--source-review` 必须指向覆盖实际完整源码映射及固定证据哈希的审阅文件。迁移后会执行原有对手资格准入检查；它不会跳过源码、原生库或编译对手绑定，也不会把合成 GPU 更新充作新的对局资格。上面的路径是本机本批审阅，不是可复用于任意源码版本的通用许可。

课程 DataIndex 使用 SQLite 备份并验证逻辑身份。只复制当前宿主需要的配置、资格证据和被记录引用的局部对局材料。GPU 数量由 0 改为本机实际使用的 1，既有 active_seconds 与课程预算保留。迁移事件记录源检查点、设备、种子、旧学习状态与恢复结果。失败目标没有成功回执，不得接入正式 continuation；排查后只清理本次失败目标。

课程检查点清单保留整条链最初的 `owner_binding_sha256`。兼容恢复允许源码审计映射变化，但不能据当前源码重新计算旧清单所有权；文件哈希、大小、顺序、结构绑定与 DataIndex 仍逐项验证。旧格式从保存状态的 binding 推导所有者，新保存同时记录所有者和当前源码映射。

成功后把 `reports/course-continuation.json` 的 `state_root` 切到新目录，再执行 `ValidateRestore`。迁移命令本身不切换指针，也不解除 training hold。旧 CPU 边界作为本次跨设备迁移的来源证据保留；不再作为默认训练入口。原 run-007 与认知训练保持独立。

## 有界更新验证

```bash
$PY scripts/verify_cuda_migration.py --output /path/to/new-fixture-output
$PY scripts/verify_cuda_migration.py --base "$BASE" \
  --course "$BASE/reports/gpu-course-20261111/2207-course-006-cuda" \
  --output /path/to/new-course-verification-output
```

验证使用独立输出和明确的合成目标，四角色实际反向和优化器更新；从相同 GPU 边界恢复后比较参数、优化器及 RNG。它不保存正式课程进度，不计正式对局或学习能力成绩。验证进程限制为 2 个 CPU 线程和 20% GPU 显存配额。

单角色/构筑工程入口为 `python -m ygo_kito duel-train` 和 `build-train`，默认 `cuda:0`，可显式传 `--device`。原 `duel-train-cpu` 与 `build-train-cpu` 是同一实现的 CPU 回归别名，保留现有测试消费者；没有第二套旧训练实现。它们会真实执行有界工程训练，应在相应授权下使用。
