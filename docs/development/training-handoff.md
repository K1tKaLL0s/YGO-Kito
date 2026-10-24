# 完整源码训练交接：CPU 工程检查与后续腾讯云门槛

本说明供任何有读文件、执行本地命令、UTF-8 stdio 能力的编程 Agent 接续，厂商 SDK 不是依赖。使用完整 Git 检出，不使用 DP 的 `_work`，也不依赖用户已关闭的本机。先读 `AGENTS.md`、`docs/plans/MASTER-CHECKLIST.md`、`generic-agent-integration.md` 及本文件；沿用 PR #1 → #2 → #3，当前没有合并或自动合并授权。

这里交付可重复的 CPU 工程检查和训练收件/恢复步骤，**不是正式训练就绪证书**。`formal_training_ready` 保持 false；真实规则、PC、三期数据、对手资格、生产权重与 GPU 吞吐另验。本轮不执行原生故障、崩溃复现、未筛选测试发现、付费训练或外部模型调用。

## 1. 源码、解释器与依赖

从已授权私有仓库取得完整源码，核对提交与 PR 头。保留旧提交以复现旧 checkpoint；不要覆盖用户分支或关闭源码/数据摘要门禁。

```bash
git status --short --branch
git rev-parse HEAD
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements/ci-cpu.txt
```

`requirements/ci-cpu.txt` 固定 Linux x86_64、CPython 3.12 的 CPU 检查环境；CI 的 Python 小版本、runner 和实际版本见 workflow 与测试收据。安装前确认所选平台；CPU wheel 不能充当 CUDA/GPU 训练锁。非此平台需单独冻结依赖，不静默混用。

项目源通过 `PYTHONPATH=src` 使用，不依赖 editable 安装、当前目录或某个外部 Agent。标准库提供 JSON/SQLite/unittest；CPU 模型检查必须安装 Torch，缺失不以跳过制造通过。旧 schema4 从空牌表求解另需 `pyproject.toml` 中固定的可选 SciPy；已有合法 base 的编辑不依赖它。本轮不为缺 SciPy 自动安装或改求解策略。

## 2. 安全检查与实际资源记录

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/check_merge_candidate.py \
  --output .cache/merge-check
.venv/bin/python scripts/training_handoff.py --root .cache \
  --output .cache/training-handoff.json
```

第一个命令只运行代码中明确白名单，并静态核对 DP 的 `native.py` / guard 原字节。日志与 JSON 包含具体分组、依赖、退出状态及排除项；不是全量真实核心回归。不运行 `tests.test_native_response_buffer`、`integration_tests` 或历史 acceptance 故障脚本。源码更新后不要以旧测试数字代替新收据。

第二个命令只做固定 `status/--help` 启动、依赖版本与锁摘要、现有原生资源的文件哈希校验、硬件和简单墙钟/CPU/峰值 RSS 记录。它不加载原生库或模型，不建/下载引擎，不启动训练。记录中的 `engine_ready_reported` 是原 CLI 声明，不能替代真实引擎验收。脚本退出 0 表示报告成功生成，**不表示资源齐全或正式门槛通过**。

启动耗时只代表启动速度。`reaped_children_max_peak_rss_bytes` 是已回收子进程的最大峰值，不是进程树总内存；控制器 RSS 单列。GPU 显存/占用、真实对局/样本吞吐和 PC 推理时延缺测时明确 unknown，不用 0 替代。腾讯云后续须以实际机型、批次、原生采样与完整模型课程再采这些指标；当前 CPU 代码不接受 GPU 启动参数。

## 3. 牌表、时期与资源准备

用户的三套主构筑、八套对手构筑尚未提供；使用 `configs/user-deck-intake-template-v1.json` 登记空编号与待补项，按 [卡组收件说明](deck-intake.md) 进行检查。三期为 2022-07、2022-10、2026-10；禁表时期和发行截止日分别配置。模板不猜截止，不含“正式”测试牌表。

每期必须提供固定卡库、发行日期证据、指定节禁表、哈希与来源，且各牌表明确环境。缺失时只返回 pending/blockers，不产出可训练配置。结构合法不等于历史卡池/禁表/规则适用，也不等于对手有合格强度。三期静态预检成功后生成的配置仍不能绕过原生 runtime 兼容检查或准入为正式训练。

原生运行需要 `configs/native-sources.lock.json` 所列版本和 `engine-build/receipt.json` 对应的完整 source/library/cards/scripts/banlist。现有 lock 是工程 smoke 组合，不是三期历史数据或 PC 兼容锁。此轮缺资源应报告，不自动运行原生准备/故障命令补证据。

## 4. Agent 启动、任务控制与恢复

无训练权限的默认读取入口：

```bash
PYTHONPATH=src .venv/bin/python -m ygo_kito agent-serve \
  --role monitor --root .cache --state-root .cache/training
```

用 `agent_driver.Client(StreamTransport(...))` 发 UTF-8 JSON Lines；先取 capabilities，再查 runs.list/runs.read。接口是厂商无关本地协议，`provider_connected:false` 应原样保留。测试 backend 标记 `local_contract_fixture`，不能当作 CodeBuddy/DeepSeek/腾讯云已接通。

训练后端默认关闭。**后续另获相应执行授权、资源与门槛具备后**，既有 CPU 宿主入口是：

```bash
PYTHONPATH=src .venv/bin/python -m ygo_kito agent-serve \
  --role trainer --root .cache --state-root .cache/training \
  --local-cpu-control --local-training-config configs/group-runner-v1.json
```

这是固定 CPU 工程配方，不是 GPU 或用户 3＋8 正式课程。RPC 不能指定 shell、任意路径、GPU/provider 或改变配方；不在这次交接检查中启动它。

| 当前状态/动作 | 正确接续 |
| --- | --- |
| 新任务 | `training.prepare {run_id}`；成功后查 state/revision/checkpoints。prepare 不具有 control 的 ID 缓存语义；丢失答复先查状态，不重新造任务。 |
| created | `training.control {run_id,operation:"start",expected_revision}` |
| running | pause/save_checkpoint/stop，先读最新 revision；不争抢正在运行的 worker。 |
| paused | resume，使用当前 revision 和新逻辑动作 ID。 |
| failed | 先 `training.recover {run_id,expected_revision}`，核验后 paused，再 resume；不能直接 resume。 |
| 同一次 control 重试 | 保留相同 ID 和完全相同参数，跨 Client/Bridge 读取持久结果；不要换 ID 再执行。 |
| uncertain | `retry_allowed:false`，先查状态/检查点，不能自动重试。 |

恢复前可只读检查登记字节：

```bash
.venv/bin/python scripts/training_handoff.py --root .cache \
  --state-root .cache/training --output .cache/resume-inventory.json
```

它复用 RunMonitor 检验长度与 SHA，不反序列化；无检查点为 unknown，损坏为 false。**字节完整不等于可恢复**：真正恢复仍由既有后端检查源码/资源/任务/特征、四模型/适配器/优化器/RNG、已消费阶段和数据索引。保留整个 state-root 的 SQL、checkpoint、sidecar、阶段清单和数据分片，不能只复制 weights；完整已提交边界之外的原生半局不支持恢复。不要修改旧 receipt 或禁用绑定来迁移。

## 5. 日志、权限与后续验收

保存源码提交、依赖锁/实际版本、测试日志/回执、handoff JSON、run ID、只读状态/指标、worker 日志及整目录恢复材料。真实牌表、私有轨迹和权重留获准存储，PR 只放允许的聚合证据；对手角色不能读取 trainer 文件/工具。应用角色不是管理员权限沙箱。

后续腾讯云启动前明确机型/计费授权、CUDA 锁、真实采样吞吐、G-01/G-02/P-01、三期数据和独立验收配置；另核实实际 Agent/provider 的模型、权限和额度。现有本地 stop 不能证明腾讯云计费停止。保留已有简单资源/用量记录，不新增精密预算系统。Codex 剩余额度须当前实查，≤20% 保存停止，不使用重置卡。
