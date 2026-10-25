# PR合并准备与云端Agent接续

## 来源、依赖和保留历史

| 工作线 | 核实提交 | 远端状态/依赖 |
| --- | --- | --- |
| [PR #1](https://github.com/K1tKaLL0s/YGO-Kito/pull/1) | `654971726c96469069a623c7bd366370b9b3a896` | open，base main@`8914e80`，未合并 |
| [DP草稿PR #2](https://github.com/K1tKaLL0s/YGO-Kito/pull/2) | `a7085e23a74fb04bff571c1c679e0097dd1ae430` | draft，base PR1分支@`6549717`，未合并 |
| 构筑逻辑 | `5d4336b` → `9958769f1884ffd5c2ea645b86d6164a8666e1d3` | 基于`6549717`，原分支保留 |
| 本整合候选 | merge `b60e798ca848e2ed23d20a6a312e236079c78d0b`；实现 `ca8532916fa971c60db6a3d9fac29e358b244478` | `codex/integration-merge-prep`，保留两作者父历史，无强推/删分支 |

DP的12文件完整普通合并，无文本冲突；其中native.py和guard逐字节保持`a7085e2`，未重新实现原生修复。作者报告的67 passed/2 explicit skips是其选定Windows审查证据；本轮没有把它冒充完整云端项目结果，也没有依赖 `_work` 或已关闭本机。

推荐依赖顺序：**PR1 → PR2 → 本整合草稿**。建议保留祖先历史的merge commit：PR1合入后将PR2 retarget到main，核对只剩DP增量；PR2合入后将本草稿retarget到main，核对只剩构筑/接续增量。当前本草稿base设为DP分支便于审查，作者分支均保留。若采用squash，需要重新核对整条stack的祖先和diff，不能直接假定相同。

本轮只准备候选，不执行GitHub合并或自动合并；远端候选提交和新草稿PR由最终发布回执确认。相对DP的审查差异包括构筑两提交、实际manager构筑桥接、启动/白名单测试和接续文档，不重新改动native.py/guard。查看[候选差异](https://github.com/K1tKaLL0s/YGO-Kito/compare/codex/dp-native-agent-hardening-20261025...codex/integration-merge-prep)。

## 实际新增集成

- manager-only `construction.plan/run`，宿主明确配置模型/审核文件，默认后端关闭；所有文件解析在workspace内，RPC无法选择路径/模型/训练/native开关。
- 实际DP Client经Loopback和**真实stdio子进程**调用项目入口、分类器和构筑控制器。服务推理复用现有模型，固定不做native验证、模型训练、API或统筹ledger提交；原CLI的显式支持范围不被RPC扩大。
- 修正长驻控制器返回上一轮模型选择证据的问题；每次请求新Session并清理本轮选择。坏/空checkpoint明确资源错误，随后继续plan，不使服务因EOFError退出。
- 完整源码启动检查：`status`和`--help`退出0，真实manager进程JSON Lines往返并正常EOF退出。分类plan可用；缺锁定卡库时构筑run返回资源缺失。没有据此称一般引擎ready。
- 新`AGENTS.md`及[通用Agent说明§11](../development/generic-agent-integration.md)提供厂商无关接续路径，不要求特定SDK，也不表示真实外部模型接通。

## 最终整合代码上的CPU证据

在实现提交 **`ca8532916fa971c60db6a3d9fac29e358b244478`** 上执行明确白名单：**188/188通过，0失败/错误/跳过，19.123秒**，开始于2026-10-24 18:42:23 UTC。后续提交仅文档与该次证据；源码聚合摘要须保持 `832c9ae6280ddf6024e6c2534e9424402dc9506378185a71bbda13a9f0e191b8`。

| 分组 | 数量 | 证据边界 |
| --- | ---: | --- |
| 构筑此前回归 | 104 | 当前整合源码重跑，含明确小合成拟合/图偏好更新，只验证代码 |
| DP安全CPU三模块 | 62 | Agent契约38、模型不变量10、checkpoint/准入14，不执行规则核心 |
| 原Agent工具兼容 | 10 | 本地协议/注册器/接续包 |
| 新构筑RPC | 9 | 实际Client→Bridge→Backend，卡库/审核数据明示合成 |
| 完整项目启动 | 3 | 完整源码CLI/真实stdio、角色及缺资源闭合 |

[逐项日志](2026-10-24-merge-prep-evidence/tests.log)、[机器回执与源码/DP双文件摘要](2026-10-24-merge-prep-evidence/results.json)。独立审查先运行74项安全检查，发现空checkpoint边界；修复后12项独立复验通过，无剩余普通工程阻碍。

**明确未执行**整个 `tests.test_native_response_buffer`、真实integration_tests、原生引擎、故障注入、SIGSEGV/越界读取复现和未筛选discovery。排除是本轮授权边界，不是把它们记为通过或运行时skip。没有重试原任务被拦截操作。

## CI与访问限制

GitHub connector读取PR1/PR2的PR-triggered workflow列表和commit statuses，均为空；这只表示未获得CI通过证据。补查两个提交的独立check-runs接口通过gh API返回 **Forbidden**，已停止该项查询，没有改写请求重试或绕过。因此完整CI check-run状态**未确认**，本地188项不代替CI。

新草稿若仍无远端检查记录，同样标未验证，不启用自动合并。没有新建会触发原生故障测试的CI配置。

## 剩余必需项与执行限制

- 合并/retarget由父任务确认，不能用本地测试替代PR审查和远端检查。
- 当前云端没有找到锁定`cards.cdb`，一般引擎`ready:false`。真实卡文/牌组/CB、PC和native端到端仍需完整锁定core/scripts/cards/banlist资源及另外允许的验证；不通过恢复被拦截故障工作补此依赖。
- 当前venv没有旧schema4从空牌表求解所需可选 `scipy==1.16.3`；现有合法base的编辑路径已测。没有安装新依赖。
- 实际外部编程Agent/provider/模型配置和授权未验证，DP持久去重/SQLite与本轮参考客户端都属于本地协议/fixture证据，不是真实外部模型连接。
- 生产模型权重、分类/胜率校准、正式语言/构筑/竞技泛化仍未验。没有扩大为能力训练或新产品功能。
- 源码实现摘要因DP新增文件/换行和本次桥接变化而改变，旧checkpoint须原提交复现或明确迁移，不能关闭资源/源码绑定门禁。
- 仅本云端/远端代码；不依赖本机。没有凭据/权限变更、付费资源/API、预算系统修复、强推、分支删除、合并或自动合并。

额度记录：父任务2026-10-24 18:31:26 UTC实际读取官方页为每周剩余75%，5天23小时重置；仅该时点有效。本执行环境无实时额度接口，不把旧值说成当前值；≤20%保存停止。
