# 安全 CPU CI

`Safe CPU contracts` 在 PR 打开、更新、重开、转为可审查以及 main 推送时运行；草稿 PR 也运行。人工 `workflow_dispatch` 只有该 workflow 已在默认分支存在后才可从界面使用。它不部署、不调用 provider、不准备或执行原生引擎，也不运行未筛选的测试发现。

CI 使用 GitHub 默认 `ubuntu-24.04` runner、Python 3.12.14、CPU-only PyTorch 2.9.1，限制 OMP/MKL 各2线程；单任务15分钟、安装10分钟、测试4分钟。没有配置外部付费服务或提高仓库权限，token 仅 `contents: read`，检出后不持久化凭据。GitHub Actions 可用包含额度和实际计费由仓库账户决定，本实现未读取或更改账单设置，不保证任何 runner 分钟免费。

`requirements/ci-cpu.txt` 针对 Linux x86_64/CPython3.12 锁定全部运行依赖及 wheel SHA256。PyTorch 的 cp312 CPU wheel 来自官方 CPU 索引，其他依赖来自 PyPI；安装使用 `--require-hashes`，不安装 CUDA、SciPy、provider SDK、卡库或原生核心。该锁不是腾讯云 GPU/CUDA 训练环境锁。

完整历史 `fetch-depth: 0` 用于静态比对 DP `a7085e2` 中 native.py 与 guard 的原字节，不执行二者；不能把浅克隆缺提交的问题当作原生验证通过。三个 actions 固定到已核实的 tag commit，不使用可变分支。

安全入口在任意工作目录都可调用：

```bash
python /path/to/YGO-Kito/scripts/check_merge_candidate.py --output /path/to/evidence
```

它先检查 CPU Torch/Numpy 必需依赖，再仅加载 `MODULES` 中明确列出的测试模块。旧模块内部可选 Torch 的 skip 不能制造成功：依赖缺失立即失败，任何运行时 skip 也使检查退出非零，并在收据保存原因。模型小样本更新为工程测试，不是正式训练能力。启动测试使用完整项目入口与真实 stdio 子进程，卡数据/模型夹具均明确标识。

整个 `tests.test_native_response_buffer`、真实 `integration_tests` 不在白名单。排除项不是运行时 skip，也不计为通过；SciPy 的空表 MILP 路径、真实规则、实际 provider、用户3+8套牌组和正式能力仍需各自资源与验收。CI只保留7天的 `tests.log` 与聚合 `results.json`，不上传缓存、数据库、权重、私有轨迹或用户卡表。

本地测试回执会记录实际 Python/Torch/Numpy 版本，不能把既有云端 Torch2.14.1 的结果称为这个2.9.1锁的重建结果。源码与CI配置本地通过，也不能称远端Actions通过；以对应提交的实际workflow结果为准。收据 `ci_verified:false` 保持这一边界，平台的workflow结论另行核对。

依据：[GitHub workflow语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)、[完整历史检出](https://github.com/actions/checkout)、[Python依赖缓存](https://github.com/actions/setup-python)、[PyTorch官方CPU安装](https://pytorch.org/get-started/previous-versions/)。
