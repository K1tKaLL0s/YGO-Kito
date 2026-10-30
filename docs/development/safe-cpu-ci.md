# 安全 CPU CI

`Safe CPU contracts` 在 PR 打开、更新、重开、转为可审查以及 main 推送时运行；草稿 PR 也运行。人工 `workflow_dispatch` 只有该 workflow 已在默认分支存在后才可从界面使用。它不部署、不调用 provider、不准备或执行原生引擎，也不运行未筛选的测试发现。

CI 使用 GitHub 默认 `ubuntu-24.04` runner、Python 3.12.14、CPU-only PyTorch 2.9.1，限制 OMP/MKL 各2线程；单任务15分钟、安装10分钟、测试4分钟。没有配置外部付费服务或提高仓库权限，token 仅 `contents: read`，检出后不持久化凭据。GitHub Actions 可用包含额度和实际计费由仓库账户决定，本实现未读取或更改账单设置，不保证任何 runner 分钟免费。

`requirements/ci-cpu.txt` 针对 Linux x86_64/CPython3.12 锁定全部运行依赖及 wheel SHA256，现已包含 **SciPy 1.16.3**，供已有 schema4 从空牌表求解路径使用。PyTorch 的 cp312 CPU wheel 来自官方 CPU 索引，其他依赖来自 PyPI；安装使用 `--require-hashes`，不安装 CUDA、provider SDK、卡库或原生核心。该锁不是腾讯云 GPU/CUDA 训练环境锁。

完整历史 `fetch-depth: 0` 用于静态比对 DP `a7085e2` 中 native.py、guard 与精确批准的时期禁表 hook，不执行原生规则；不能把浅克隆缺提交的问题当作原生验证通过。无本仓库 `.git` 的源码包先核完整 manifest，再按固定 DP SHA 核对原字节或精确可逆 hook；归档来源提交单列，不伪造 `tested_head`。三个 actions 固定到已核实的 tag commit，不使用可变分支。

安全入口在任意工作目录都可调用：

```bash
python /path/to/YGO-Kito/scripts/check_merge_candidate.py --output /path/to/evidence
```

它先检查 CPU Torch/Numpy/SciPy 必需依赖，再仅加载 `MODULES` 中明确列出的测试模块。旧模块内部可选 Torch 的 skip 不能制造成功：依赖缺失立即失败，任何运行时 skip 也使检查退出非零，并在收据保存原因。模型小样本更新为工程测试，不是正式训练能力。启动测试使用完整项目入口与真实 stdio 子进程，卡数据/模型夹具均明确标识。

整个 `tests.test_native_response_buffer` 和真实 `integration_tests` 不在这个 CPU CI 白名单。排除项不是运行时 skip，也不计为通过，不能据此声称普通引擎运行被禁：本云端另已实际完成正常 `native-smoke`、`native-duel/replay`，以及 `integration_tests.test_native_engine/test_normal_duel/test_agent_duel` 共 **16 项正常测试通过**，见[普通真实引擎诊断](../reports/2026-10-24-native-current-diagnosis.md)。这份有界证据与 CPU CI 分开记录，不等于一般卡池、三期历史规则或 GPU 训练通过；旧保护页/故障注入/崩溃复现继续排除。CI只保留7天的 `tests.log` 与聚合 `results.json`，不上传缓存、数据库、权重、私有轨迹或用户卡表。

stage2 四模型 group runner 已有宿主配方显式选择 CPU/CUDA 的代码接口；当前 CI 使用 CPU-only wheel，验证 CPU 兼容、恢复与缺 CUDA 明确拒绝，不把这些测试称为 GPU 数值、吞吐或恢复实测。旧 CPU checkpoint 不能通过改设备字段隐式迁移到 CUDA。实际 GPU 锁、驱动、硬件压力、正式课程与外部模型仍分别验收。

本地测试回执会记录实际 Python/Torch/Numpy 版本，不能把既有云端 Torch2.14.1 的结果称为这个2.9.1锁的重建结果。源码与CI配置本地通过，也不能称远端Actions通过；以对应提交的实际workflow结果为准。收据 `ci_verified:false` 保持这一边界，平台的workflow结论另行核对。

依据：[GitHub workflow语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)、[完整历史检出](https://github.com/actions/checkout)、[Python依赖缓存](https://github.com/actions/setup-python)、[PyTorch官方CPU安装](https://pytorch.org/get-started/previous-versions/)。

## 2026-10-30 publication coverage

The explicit allowlist now includes course admission, controlled CB setup (fake library only), prospective 20/50 feedback, mechanism recall, reference scoring and the optional multifactor module. The private reference audit test remains a separately named class and requires local reports; public CI excludes it and does not upload reference reports.

The native byte audit also accepts the exact reviewed `da1dd3a` conditional-CB setup implementation. This extension validates a 1–5-card own-hand inventory and preserves the default shuffled five-card setup; ABI declarations, callbacks and response handling are unchanged. Its complete bytes are pinned alongside the original DP implementation and period hook. Any further native or guard change is still rejected. This static review and the fake-library setup tests do not execute the native core.
