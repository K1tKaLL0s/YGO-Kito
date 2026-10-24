# YGO-Kito 云端接续

先读 README、`docs/plans/2026-10-22-unified-development-spec.md`（包括第18节）、MASTER-CHECKLIST，以及当前 `docs/development/generic-agent-integration.md` 和 `construction-logic.md`。原件/历史报告不是当前能力证明，当前明确用户指令优先。

- 本仓库是完整项目；DP 的 `_work` 为部分审查副本，不能独立启动。使用当前完整检出及已安装 CPU Python，不依赖关闭的本机。
- 构筑逻辑为无卡 ID 轻量图，标签与粗连接独立。狭义才筛主轴；广义跳过第二阶段但保留图。目标→优化不得静默改变用户目标；未知卡效/未验图边不得宣传为合法 CB。
- 新入口分类器可训练；缺模型拒判。程序枚举图/卡候选、已有模型评分选择，不能写成模型已自主掌握构筑。
- Agent 为本地 JSON Lines，manager 构筑后端须宿主显式配置；RPC不能打开训练、native验证、外部provider或指定文件路径。fixture/本地参考客户端不等于真实外部模型已连接。
- 当前合并准备不运行故障注入、SIGSEGV/越界读取复现或 `tests.test_native_response_buffer`，也不运行未筛选 discovery。之前平台拦截未确认解除，不能借集成重做受限操作。
- 安全合并检查：`OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 /workspace/YGO-Kito/.venv/bin/python scripts/check_merge_candidate.py`。它只运行明确 CPU 白名单，并核对 DP `native.py` 与 guard 成对保留；不能将其通过外推到原生规则正确性。
- 不改凭据/权限，不启动付费训练/API，不强推、删作者分支、合并或开启自动合并。按本轮授权保存可审查候选；发布/合并状态分别报告。
- 旧 checkpoint 绑定源码/数据摘要。新增文件或换行改变后不能绕过绑定来恢复；保留原版本复现或另行明确迁移。
- 更新 MASTER-CHECKLIST 和当前证据，分别报告本地测试、CI、外部模型与真实引擎。没有 CI 记录不能记为通过。额度须当前实际核实，不能沿用历史值；≤20%保存停止，不使用重置卡。
