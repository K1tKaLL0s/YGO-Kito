# 腾讯云现有主机的部署准备与源码包

本入口为已获准取得的**现有主机**做静态部署预检，或者在当前云端生成本地源码包。它不采购、登录或创建腾讯云资源，不读取凭据，不调用外部模型，不启动训练或原生规则。需要完整项目源码；先读 `AGENTS.md`、`training-handoff.md` 和当前总清单。

既有 `training_handoff.py` 负责观察资源、启动与登记 checkpoint 字节；`training-preflight` 是旧 CPU 健康检查。新增 `scripts/deployment_prepare.py` 补的是：可移交源码包的确定性文件清单、逐文件校验，以及显式部署阈值、锁版本、日志位置和恢复输入的门禁。它没有替代模型运行器或建立另一套预算系统。

## 1. 本地准备与校验包

在已提交的完整工作分支执行：

```bash
python scripts/deployment_prepare.py bundle \
  --output .cache/ygo-source.tar.gz
python scripts/deployment_prepare.py verify .cache/ygo-source.tar.gz
```

`bundle` 拒绝选定源码目录中尚未提交或未跟踪的改动，拒绝 symlink 和过大文件；输出文件以独占方式创建，不覆盖旧包。仅收录 Git 已跟踪的 Python/脚本、配置、依赖锁、测试、README/AGENTS 与开发/计划说明。`.git`、`.cache`、报告、真实牌表、原生资源、模型/检查点二进制、轨迹与凭据目录不收录。配置中的工程例子仍是例子；把用户数据保留在批准的独立数据位置。

包内 `deployment-manifest.json` 固定原提交、文件长度及 SHA256；同一提交、同样源码产生相同 tar.gz 字节。`verify` 逐成员校验，不解压或执行；拒绝链接、路径穿越、重复/额外成员、缺文件与 checksum 改变。它只证明这个包内部一致。普通哈希清单没有签名，不能认证发布者；从获准可信来源另核对提交和包 SHA256。

接收方可以使用完整 Git 检出，也可将已核验源码包由自己的获准文件工具安装到独立空目录。预检与安全 CPU 脚本支持无 `.git` 的包安装，先按 manifest 检查所有源码字节；不会误用父目录其他 Git 仓库的 HEAD。包不包含恢复/原生数据，它们须另行传递并核验。

安全 CPU 脚本在本仓库 Git 检出中仍用 `git show` 核对 DP 固定提交与精确批准的时期禁表 hook；在无 Git 包中，以固定 DP SHA256 检查 guard，并要求 native 原字节匹配，或仅精确撤销两处调用替换及唯一 hook 后匹配同一固定 DP SHA256。其他响应/ABI改动不能借 manifest 放行。回执写明 `checkout_kind:source_archive`、`tested_head:null` 与单独 `source_archive_commit`：归档声称的来源不是本地 Git 证据，仍须从可信来源核实包 SHA/提交；此校验不运行原生代码。

这里的无 Git 包指没有本仓库 `.git` 元数据。安全白名单中的隔离分支/交接测试仍需要系统 `git` 可执行程序来建立临时无远端 fixture；依赖 wheel 锁不安装系统 Git，缺少该工具会明确失败。

在安装好的源码根可执行 CPU 检查环境与安全启动预检：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements/ci-cpu.txt
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python scripts/check_merge_candidate.py \
  --output .cache/source-package-check
.venv/bin/python scripts/training_handoff.py --root .cache \
  --output .cache/source-package-handoff.json
```

CPU锁现已包含 SciPy 1.16.3，覆盖旧 schema4 空表求解所需依赖。包不附原生资源与恢复目录，缺这些资源应如实报告，不能用 `status.engine.ready=false` 推断显式 native 工具未实现。

## 2. 显式配置现有主机

复制空模板至 `.cache` 中获准的私有配置路径，填写当前真实值：

```bash
mkdir -p .cache
cp configs/deployment-host-template-v1.json .cache/deployment-host.json
python scripts/deployment_prepare.py preflight \
  --config .cache/deployment-host.json \
  --output .cache/deployment-preflight.json
```

配置与报告是本地文件，不上传。所有配置路径为 workspace 内显式相对路径，解析后的 symlink 不得逃出 workspace。配置只接受固定字段，没有 shell、云启动、付款、provider 或训练命令。

| 字段 | 必须填写/含义 |
| --- | --- |
| `expected_source_commit` | 实际核对过的40位提交；源码改动不得静默沿用旧绑定。 |
| `dependency_lock` | 已冻结锁的路径与 SHA256，以及精确 Python/Torch 版本。逐项比对哈希锁中的已装依赖版本，缺失或不同会阻止。 |
| `runtime_device` | `cpu` 或 `cuda`，不自动回退。字段表示部署目标，不证明该训练运行器已支持该设备。 |
| `minimum_hardware` | 显式 CPU 核数、RAM、可用磁盘、CUDA 设备数和每设备总显存下限；缺值不猜机型或阈值。CPU 模式的两个 CUDA 下限必须为整数0。 |
| `native_root` | 锁定原生资源根；只调用既有文件哈希校验，不加载动态库、执行卡效或自动下载构建。 |
| `log_directory` | 检查目标/最近已存在父目录的可写权限；预检不创建该日志目录。不能用权限位检查替代实际训练运行日志。 |
| `resume` | fresh 模式其余三项必须 null；resume 指定 state-root、run ID 与已登记 checkpoint ID。 |
| `evidence` | 可选的 `{id,path,sha256}` 引用列表；只验证非空文件字节，不认可其中自称“passed”的能力结论。 |

`requirements/ci-cpu.txt` 是 Linux x86_64/CPython3.12 的 **CPU 工程检查锁**，包含 Torch2.9.1+cpu、NumPy2.3.5 与 SciPy1.16.3。它不适用于 CUDA 训练；配置 CUDA 但仍指定这个 CPU wheel 时预检明确阻止。stage2 group 已有显式 CPU/CUDA FP32 设备代码接口，目标GPU锁、驱动、数值/吞吐和恢复仍未实测。不能把本脚本的 CUDA 可见性或代码存在写成真实GPU训练通过。

## 3. 真实观测与拒绝边界

CPU 可用核数考虑当前 affinity 和 Linux cgroup v2 CPU quota；内存报告取物理 RAM 与当前 cgroup v2 限额的较小值，磁盘为 workspace 文件系统的实际 free。无相应平台接口时为 unknown，并且对应门槛不通过。它们是资源容量观测，不是压测/利用率结论。

Torch 只查询本机 CUDA 是否可用、可见设备数量和各设备总显存。无 CUDA 或 CPU-only wheel 会明确返回 blockers；设备显存不伪造为0，也不启动 GPU 小训练补证。总显存不等于当时空闲显存，设备可见不等于完整课程吞吐、数值或恢复验收；实际设备压力和速度由有界运行器另采。

恢复预检复用既有 `RunMonitor`，只接受 source 为 trainer、状态 created/paused/failed 的指定运行中已登记且非空、长度/SHA正确的 checkpoint。不存在、空或坏制品、fixture 状态均阻止恢复输入检查。既有 failed 状态仍须先由训练协议 recover，随后 resume。**不反序列化，所以不证明源码/数据/设备/优化器/RNG/课程索引绑定可恢复**；真正运行器仍需按其原门禁验证，不能只传一份 weights。

旧CPU checkpoint 不因更改宿主 `runtime_device` 或 recipe 就隐式转CUDA；设备元数据与设备RNG必须成对匹配，旧缺字段制品只按CPU解释。跨设备/设备索引恢复须另行验证明确迁移，不能放松源码/资源/阶段绑定。

普通真实运行并未被本预检禁止。本云端另已实际编译锁定资源，完成 `native-smoke`、普通终局与精确重放，以及16项正常引擎/普通对局/单席位接口测试；见[引擎诊断](../reports/2026-10-24-native-current-diagnosis.md)。此证据与源码包静态预检分开，旧故障复现/保护页实验仍排除；当前一般卡池、历史规则、正式能力和GPU不能据此宣布通过。

## 4. 现有腾讯云主机的训练入口与门槛

取得相应运行授权并准备真实资源后，CPU工程配方可沿用：

```bash
PYTHONPATH=src .venv/bin/python -m ygo_kito agent-serve \
  --role trainer --root .cache --state-root .cache/training \
  --local-cpu-control --local-training-config configs/group-runner-v1.json
```

它只启动受控协议宿主；由 `Client` 的 prepare/状态检查/start 请求实际启动有界 worker。`--local-cpu-control` 保留原开关名，stage2 group 的完整宿主 recipe 现在可选 `execution:{schema_version:1,device:"cuda:0",dtype:"float32"}` 与实际 `allocated_gpu_count`，再用同一 `--local-training-config` 指定。旧 standalone CPU工具未全部扩为GPU。GPU配方必须另冻结目标环境锁；缺CUDA拒绝，无隐式CPU回退。完整示例与恢复步骤见 [training-handoff](training-handoff.md)。

正式三期配方不能直接复用两周期工程样例：先准备真实[训练输入](training-input.md)和[时期宿主](period-runtime.md)，以及目标/验证任务、可执行对手、隔离种子和相应时期的官方来源/旧规则范围。用户3＋8牌表仍待接收，但不是仅剩依赖。实例/执行授权、GPU运行与吞吐恢复待目标主机核实。2A可先用合法工程数据；正式能力评测另验。PC产品/客户端互操作后置，真实provider仅在选择其可选对手/辅助路径时核实，不阻塞本地规则/冻结模型基线。

退出0表示包生成/包完整性核验成功，或所有**静态部署检查**通过；预检有 blockers 退出2并保留 JSON。报告始终 `formal_training_ready:false`、`training_started:false`。阶段门槛、相应数据、合法对手、真实GPU执行与训练授权由上层独立汇总；PC产品不列为基础训练前置，不能把 `deployment_checks_passed:true` 升格成这些结论。

本脚本没有腾讯云 SDK 或价格假设。是否已获准运行、机型/采购/费用、设备数量、依赖许可、停云计费、实际 provider、Codex 当前额度都须从各自真实来源核实。已有本地停止不代表计费停止；不新增精密预算系统。
