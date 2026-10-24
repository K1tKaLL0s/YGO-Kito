# 完整源码训练交接：CPU 工程检查与后续腾讯云门槛

本说明供任何有读文件、执行本地命令、UTF-8 stdio 能力的编程 Agent 接续，厂商 SDK 不是依赖。使用完整 Git 检出或[已核验自包含源码包](deployment-preparation.md)，不使用 DP 的 `_work`，也不依赖用户已关闭的本机。先读 `AGENTS.md`、`docs/plans/MASTER-CHECKLIST.md`、`generic-agent-integration.md` 及本文件；沿用 PR #1 → #2 → #3，当前没有合并或自动合并授权。

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

项目源通过 `PYTHONPATH=src` 使用，不依赖 editable 安装或某个外部 Agent；下列相对命令从完整源码根执行，安全检查脚本也支持绝对路径从异目录调用。标准库提供 JSON/SQLite/unittest；CPU 模型检查必须安装 Torch，缺失不以跳过制造通过。旧 schema4 从空牌表求解所需 **SciPy 1.16.3 已加入 CPU 哈希锁**；已有合法 base 的编辑仍沿用原路径。没有用替代求解策略掩盖缺依赖。

## 2. 安全检查与实际资源记录

```bash
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/check_merge_candidate.py \
  --output .cache/merge-check
.venv/bin/python scripts/training_handoff.py --root .cache \
  --output .cache/training-handoff.json
```

第一个命令只运行代码中明确白名单，并静态核对 DP 的 `native.py` / guard 及精确批准的时期禁表 hook。Git 检出使用固定提交原件；源码包使用已核验 manifest 和固定 DP SHA，`source_archive_commit` 不充当本地 Git HEAD。日志与 JSON 包含具体分组、依赖、退出状态及排除项；不是全量真实核心回归。该命令不运行 `tests.test_native_response_buffer`、真实 `integration_tests` 或历史 acceptance 故障脚本。源码更新后不要以旧测试数字代替新收据。

正常引擎验收另有实际证据：锁定源码编译、`native-smoke`、40张工程池普通终局与精确 `native-replay` 已完成；明确选取的正常引擎/普通对局/Agent单席位 **16 项测试通过**。见[当前诊断](../reports/2026-10-24-native-current-diagnosis.md)。这并非平台禁止运行普通引擎，也不表示完整珠泪/一般效果、历史规则、PC 或 GPU 已验。旧故障注入/保护页/崩溃复现仍不接续；最终源码需按实际变更复验相应正常路径。

第二个命令只做固定 `status/--help` 启动、依赖版本与锁摘要、现有原生资源的文件哈希校验、硬件和简单墙钟/CPU/峰值 RSS 记录。它不加载原生库或模型，不建/下载引擎，不启动训练。记录中的 `engine_ready_reported` 是原 CLI 声明，不能替代真实引擎验收。脚本退出 0 表示报告成功生成，**不表示资源齐全或正式门槛通过**。

启动耗时只代表启动速度。`reaped_children_max_peak_rss_bytes` 是已回收子进程的最大峰值，不是进程树总内存；控制器 RSS 单列。GPU 显存/占用、真实对局/样本吞吐和 PC 推理时延缺测时明确 unknown，不用 0 替代。stage2 group 已有显式 CPU/CUDA FP32 设备代码接口，但 GPU 尚未实测；腾讯云后续须在实际驱动、机型、批次、采样与完整课程上记录设备压力、速度、数值与恢复结果。

## 3. 牌表、时期与资源准备

用户的三套主构筑、八套对手构筑尚未提供；使用 `configs/user-deck-intake-template-v1.json` 登记空编号与待补项，按 [卡组收件说明](deck-intake.md) 进行检查。三期为 2022-07、2022-10、2026-10；禁表时期和发行截止日分别配置。模板不猜截止，不含“正式”测试牌表。

每期必须提供固定卡库、发行日期证据、指定节禁表、哈希与来源，且各牌表明确环境。缺失时只返回 pending/blockers，不产出可训练配置。结构合法不等于历史卡池/禁表/规则适用，也不等于对手有合格强度。三期静态预检成功后生成的配置仍不能绕过原生 runtime 兼容检查或准入为正式训练。

原生运行需要 `configs/native-sources.lock.json` 所列版本和 `engine-build/receipt.json` 对应的完整 source/library/cards/scripts/banlist。本云端这些普通工程资源已恢复且正常运行通过；源码包不包含它们，目标主机仍须明确准备并核对，不把旧路径存在当作已传输。现有 lock 是工程 smoke 组合，不是三期历史数据或 PC 兼容锁。[时期 runtime](period-runtime.md) 保留截止、发行允许池和所选禁限节，不能认证旧裁定/勘误或官方来源。

## 4. Agent 启动、任务控制与恢复

无训练权限的默认读取入口：

```bash
PYTHONPATH=src .venv/bin/python -m ygo_kito agent-serve \
  --role monitor --root .cache --state-root .cache/training
```

用 `agent_driver.Client(StreamTransport(...))` 发 UTF-8 JSON Lines；先取 capabilities，再查 runs.list/runs.read。接口是厂商无关本地协议，`provider_connected:false` 应原样保留。测试 backend 标记 `local_contract_fixture`，不能当作 CodeBuddy/DeepSeek/腾讯云已接通。

训练后端默认关闭。以下是**执行授权、资源与对应门槛具备后**的现有 CPU 工程启动命令，不在交接检查中自动执行：

```bash
PYTHONPATH=src .venv/bin/python -m ygo_kito agent-serve \
  --role trainer --root .cache --state-root .cache/training \
  --local-cpu-control --local-training-config configs/group-runner-v1.json
```

`configs/group-runner-v1.json` 是有界 CPU 工程配方，不是用户 3＋8 正式课程。`--local-cpu-control` 是已有宿主选择开关的名称；四模型 group 路径现在读取宿主配方中的设备字段，旧 standalone/legacy CPU 工具没有因此全部获得 CUDA 支持。RPC 不能指定 shell、文件、设备/provider 或替换配方。

stage2 group 的 CUDA 配方在保留原任务/分区配置后显式加入：

```json
{
  "execution": {"schema_version": 1, "device": "cuda:0", "dtype": "float32"},
  "allocated_gpu_count": 1
}
```

这只是需要加入完整 group recipe 的字段示意，不是独立可用配方。`allocated_gpu_count` 必须是宿主实际已分配数量，CUDA为1–8；默认 CPU为0，不能从可见设备数猜计费数量。CUDA不可用、设备不匹配或精度不支持时拒绝，不能自动降到CPU。GPU主机另需已冻结 CUDA/PyTorch/驱动环境；CPU哈希锁不能代替它。此代码接口未在真实GPU运行验收。

在已有腾讯云主机完成相应预检后，将宿主已核实的完整配方放至 `.cache/approved-group-recipe.json`，仍用同一固定协议入口：

```bash
mkdir -p .cache
PYTHONPATH=src .venv/bin/python -m ygo_kito agent-serve \
  --role trainer --root .cache --state-root .cache/training \
  --local-cpu-control --local-training-config .cache/approved-group-recipe.json \
  2> .cache/trainer-stderr.log
```

保持 stdio 连接，由参考 `Client` 依次能力发现、`training.prepare`、查询当前 revision，再提交 `training.control/start`。自动生成的 worker 日志在 `state-root/runs/<run_id>/worker-<generation>.log`。三期正式配方还需按[训练输入](training-input.md)与[时期宿主](period-runtime.md)填写 `period_inputs`、task、真实对手与隔离信息；不能仅修改工程配方的设备和期别名称就开始正式课程。

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

它复用 RunMonitor 检验长度与 SHA，不反序列化；无检查点为 unknown，空或损坏为 false。**字节完整不等于可恢复**：真正恢复仍由既有后端检查源码/资源/任务/特征、四模型/适配器/优化器/RNG、已消费阶段和数据索引。新检查点成对绑定设备元数据与设备 RNG；旧检查点缺设备字段只按 CPU 解释，不能隐式迁移 CUDA，CPU/CUDA或设备索引变化需另行明确迁移方案。保留整个 state-root 的 SQL、checkpoint、sidecar、阶段清单和数据分片，不能只复制 weights；完整已提交边界之外的原生半局不支持恢复。不要修改旧 receipt 或禁用绑定来迁移。

## 5. 日志、权限与后续验收

保存源码提交、依赖锁/实际版本、测试日志/回执、handoff JSON、run ID、只读状态/指标、worker 日志及整目录恢复材料。真实牌表、私有轨迹和权重留获准存储，PR 只放允许的聚合证据；对手角色不能读取 trainer 文件/工具。应用角色不是管理员权限沙箱。

仍有多项外部门槛，不能称仅剩牌表：目标腾讯云实例/计费授权与停机核验、真实GPU锁和压力/吞吐/恢复、三期历史发行来源/截止与官方禁限及旧规则核对、用户资料/课程比例和合格对手、独立评估与分类校准、PC标准回放/兼容，以及实际 Agent/provider 模型、权限、额度与法律许可。G-01/G-02/P-01 等整体门槛不因普通16项或CPU工程通过而自动勾选。现有本地 stop 不能证明腾讯云计费停止。保留已有简单资源/用量记录，不新增精密预算系统。Codex 剩余额度须当前实查，≤20% 保存停止，不使用重置卡。
