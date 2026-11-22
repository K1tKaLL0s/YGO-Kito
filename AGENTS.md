# YGO-Kito Agent 须知

本文件是本仓库唯一的 Agent 说明，适用于全部检出（统筹、构筑、决斗）及 Codex、Gemini、CodeBuddy、DeepSeek 等编程 Agent。2026-11-22 合并原 AGENTS.md 与 CODEBUDDY.md；原 CloudStudio CPU 接手说明见 `git show ba65e84:CODEBUDDY.md`。

## 先读
- [统一设计书](docs/current/design.md)与[资料入口](docs/current/README.md)；当前优先级、在办事项与接续任务书见[18 项实施清单](docs/plans/2026-11-12-comprehensive-optimization-plan.md#order-18)。
- 统一设计书与实施清单维护在统筹树 `N:\YGO-Kito\_publish_20261030`（分支 codex/coordinator）；本机从构筑或决斗检出接手时，直接打开[统筹树实施清单](N:/YGO-Kito/_publish_20261030/docs/plans/2026-11-12-comprehensive-optimization-plan.md#order-18)与[统筹树统一设计](N:/YGO-Kito/_publish_20261030/docs/current/design.md)。
- 工程入口：[安全 CPU CI](docs/development/safe-cpu-ci.md)、[训练交接](docs/development/training-handoff.md)、[牌表收件](docs/development/deck-intake.md)、[本地 Agent](docs/development/generic-agent-integration.md)。
- 优先级：当前明确用户指令 > 设计书 > 历史报告。运行结果以实际记录为准，历史报告不证明当前能力。

## 如实报告
- 本地测试、CI、真实引擎、外部模型和训练分别报告。没有 CI 记录不算通过，任何 skip 视为失败。18 项优化使用统筹树实施清单的顺位，按对应行更新状态和验收。其他项目事项更新 [MASTER-CHECKLIST](docs/plans/MASTER-CHECKLIST.md)。
- 程序枚举的候选、已有模型的评分选择和真实参数更新分开记录，不能写成模型已自主掌握构筑。缺模型的分类器拒判。
- 未知、未读取、经审阅无独立功能三者不混用；不填零，不伪造完整分或通过。fixture 与本地参考客户端不等于真实外部模型已接通。
- 平局不算胜，异常和超时保留在分母内。验收口径见设计书[正式能力验收](docs/current/design.md#正式能力验收)。

## 构筑
- 按 S0–S6 与统一 Evaluation 执行：先出无卡 ID 粗逻辑，标签与粗连接独立；仅狭义主题筛主轴，广义跳过筛轴但保留图；在完整时期卡池内检索，不从预筛卡名单反推逻辑或封闭卡池。优化不得静默改变用户目标；未知卡效、未验图边不得宣称为合法 CB。
- 卡效按机制类型修复：先核对锁定的 YGOPro Lua、公共 helper 与 core API，复用现有卡效记录、库存谓词、实体分配和评分入口；类型覆盖用锁定库的同类效果验证，涵盖不同脚本写法与语义近似的反例。禁止无条件逐卡修复或调优：卡名、卡号只用于定位证据和回归见证；只有同机制检索与对照证明缺陷仅属一张卡时才可单卡处理，并记录根因、对照范围与证据。
- 用户参考牌表只用于独立评价与允许的分层提示，不作生成种子，不装入 learner。

## 规则资源与时期
- 设计截止：2207 为 2022-09-30，2210 为 2022-12-31，2610 为 2026-11-01（含日本当地当日正式 OCG 发售）；2610 禁表为 2026-10-01 生效表。卡池按实际正式发行与来源逐项核对，未齐则 fail closed，不用合成日期或旧 null 夹具冒充最终池；训练期间不自动加新卡。
- 3＋8 模板是空收件槽，历史发行截止逐期显式填写，不按月份或旧说明推断。`deck_intake` 记录不是可训练配方。

## 运行与安全边界
- 本仓库是完整项目，DP 的 `_work` 只是部分审查副本。CPU Python 只做软件回归；训练与正式运行用 GPU，见 [GPU 环境](docs/reports/2026-11-11-gpu-environment.md)与 [CUDA 运行](docs/development/cuda-runtime.md)。GPU 实机、吞吐和正式训练属于训练阶段，不是软件开发的前置门槛。
- 安全合并检查：`OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .cache/ci-cpu-venv/bin/python scripts/check_merge_candidate.py`，环境按 `requirements/ci-cpu.txt` 哈希锁建立。只跑 CPU 白名单；guard 及 ABI／响应逻辑保持 DP 版本，另接受 da1dd3a 的 conditional-CB 起手初始化字节；native 只允许可逐字还原的历史禁表选择 hook。通过不外推为原生规则正确，正常引擎回归单列。
- 不运行故障注入、SIGSEGV／越界读取复现、`tests.test_native_response_buffer` 或未筛选 discovery。普通锁定资源构建、合法对局／重放及明确选取的正常真实回归已获授权。
- 本地 Agent 为 JSON Lines；manager 构筑后端须宿主显式配置；RPC 不能开启训练、native 验证、外部 provider 或指定文件路径。
- 机器人部署见[维护范围部署](docs/development/maintained-bot-deployment.md)；不能用旧 dsh 副本、源码登记或 ExternalPolicyOnly 代替完整 Executor。
- 遇权限、访问或代理拒绝，停止该具体动作并报告，不换工具、镜像或代理绕过（先例见 [bot 工具链阻塞](docs/reports/2026-10-25-bot-toolchain-block.json)）。不改凭据和权限，不启动付费训练或付费 API。

## Git 与合入
- 接手先看相关工作树状态，保留既有未提交修改，只提交自己改动的路径。
- 不强推，不删作者分支，不开自动合并，不自动部署。合入 main 须有当前有效授权（现行见[实施清单授权](docs/plans/2026-11-12-comprehensive-optimization-plan.md#handoff-18)）且最终提交 CI 通过；每步核对实际 head／base 与未审变更，合并与发布状态分别报告。
- 已完成迁移的旧代码与重复源码副本及时删除，历史由 Git 管理。

## 训练、checkpoint 与恢复
- 正式训练当前暂停（`N:\YGO-Kito\_local_cpu_20261027\reports\training.hold.json`）；run-007 与 checkpoint/latest 不因整理而恢复或改写。正式训练须先提交启动清单，并收到用户明确的开始指令。
- checkpoint 绑定模型布局、词表、资源、数据与游标，按结构兼容性判断能否恢复，无关文件变化不强制迁移。从 `.weights` 做 effective 初始化只继承参数，不是旧任务 resume。
- 暂停：向 `state_root/course/pause.request` 写请求，在小局提交边界保存并等待进程退出，不得中途杀进程假称已保存。恢复须核对同源码与工件绑定并显式 `resume:true`，只移除自己建立的 `pause.request`。遇 `in-flight.json`、未裁决异常或 checkpoint／DB 不一致先检查，不删标记，不清索引，不自动重打。

## 额度
- 额度一律用当时实读值，到停止线前留出提交、更新文档和保存进度的余量。一般任务剩余 ≤20% 时保存并停止，不使用重置卡；18 项系列的累计上限与当前停止线以[实施清单授权](docs/plans/2026-11-12-comprehensive-optimization-plan.md#handoff-18)为准。

## 存储
- 本机工作树、缓存与 WSL 资源位置见外层 `N:\YGO-Kito\AGENTS.md`。生成文件写入运行前指定的 `.cache` 任务目录。
