# 本机闭合基础恢复点003

压缩包：`20261027-local-foundation-003.tar.gz`，15857745字节。
SHA-256：`12ddad1cb71c2c5055ff5736aefae9c6aab7092ea3cb9ba0527931efe70d8155`。

这是已闭合的 goal2/optimizer0/duel1/coordinator3 状态和16局真实冻结驾驶比较。两构筑得分均0，没有严格优化标签，正式计数0。当前本机后续训练进度另见 `docs/reports/2026-10-27-local-continuation.zh-CN.md`。

从当前PR分支取得文件后，先解包到新目录：

```powershell
python scripts/unpack_local_snapshot.py --archive artifacts/checkpoints/20261027-local-foundation-003.tar.gz --manifest artifacts/checkpoints/20261027-local-foundation-003.manifest.json --output N:\YGO-Kito\_local_cpu_20261027\imports\github-local-003
```

解包器核对完整hash/成员清单并保留不同的既有文件，不加载模型。完整状态及DataIndex位于包内 `.cache/local-base-training-20261027/2207-base-005`、`2207-base-006`；当时的精确执行源码位于 `frozen-execution-source-006`。原binding和绝对运行路径保留，映射到新位置须按明确迁移记录恢复参数、优化器、RNG和游标，不伪造旧身份。

运行资产没有包含第三方CDB、Lua、core或bot文件。固定来源/commit/hash见项目两个source锁和包内 `runtime-identities`。本机已有这些锁定字节和编译产物，直接复用；不同编译器/路径需实际重新构建并明确迁移。源码工作树、运行环境与状态的接续用法见 `docs/development/local-training-continuation.md`，不得把恢复包本身当作完整第三方运行环境。

旧云端002包与原始manifest、patch保持原样。参考构筑只作独立评判，不载入learner。
