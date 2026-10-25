# YGO-Kito 云端接续

先读 README、`docs/plans/2026-10-22-unified-development-spec.md`（包括第18节）、MASTER-CHECKLIST，以及当前 `docs/development/generic-agent-integration.md` 和 `construction-logic.md`。原件/历史报告不是当前能力证明，当前明确用户指令优先。

- 本仓库是完整项目；DP 的 `_work` 为部分审查副本，不能独立启动。使用当前完整检出及已安装 CPU Python，不依赖关闭的本机。
- 构筑逻辑为无卡 ID 轻量图，标签与粗连接独立。狭义才筛主轴；广义跳过第二阶段但保留图。目标→优化不得静默改变用户目标；未知卡效/未验图边不得宣传为合法 CB。
- 新入口分类器可训练；缺模型拒判。程序枚举图/卡候选、已有模型评分选择，不能写成模型已自主掌握构筑。
- Agent 为本地 JSON Lines，manager 构筑后端须宿主显式配置；RPC不能打开训练、native验证、外部provider或指定文件路径。fixture/本地参考客户端不等于真实外部模型已连接。
- 不运行故障注入、SIGSEGV/越界读取复现或 `tests.test_native_response_buffer`，也不运行未筛选 discovery。用户已新授权普通锁定资源构建、合法对局/重放与明确选取的正常真实回归，且已成功；不能把旧修复任务的拦截误作所有当前引擎运行被禁止。遇当前具体拒绝只停止该动作，不绕过。
- 安全合并检查：`OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 .cache/ci-cpu-venv/bin/python scripts/check_merge_candidate.py`（先按`requirements/ci-cpu.txt`哈希锁建立该环境）。它只运行明确 CPU 白名单，guard及ABI/响应逻辑保持DP版本；native仅允许可逐字还原的历史禁表选择hook。不能将其通过外推到原生规则正确性；正常引擎回归单列。
- 不改凭据/权限，不启动付费训练/API，不强推、删作者分支或开启自动合并。用户2026-10-25已新授权：复核已确认设计、修正必要问题且最终commit CI通过后，依次将PR1→PR2→PR3合入main；每步核对实际head/base及未审变更，不能将后两项只合回旧功能分支。旧“不合并”限制由本次明确授权更新；仍不自动部署。发布/合并状态分别报告，具体拒绝停止该动作、不换工具绕过。
- 旧 checkpoint 绑定源码/数据摘要。新增文件或换行改变后不能绕过绑定来恢复；保留原版本复现或另行明确迁移。
- 新增维护范围全部机器人部署见 `docs/development/maintained-bot-deployment.md`，不能以旧dsh副本、源码登记或ExternalPolicyOnly代替完整Executor。用户已专项批准固定Ice/Pure构建、签名Debian Mono安装及127.0.0.1有界验证；不是仍在等用户批准。当前安装因uid1000/系统目录权限失败，配置的签名源索引又被HTTP代理403拒绝，见 `docs/reports/2026-10-25-bot-toolchain-block.json`；停止该路径，不换镜像/代理/工具绕过。未运行Android/libWindbot PostBuild或公网Test1。CPU socket fixture、被动DLL文件和真实WindBot加载/正常对局须分别报告，未闭合新增项前不执行条件合并。
- 更新 MASTER-CHECKLIST 和当前证据，分别报告本地测试、CI、外部模型与真实引擎。没有 CI 记录不能记为通过。额度须当前实际核实，不能沿用历史值；≤20%保存停止，不使用重置卡。
- 后续工程先看 `docs/development/safe-cpu-ci.md`、`training-handoff.md`、`deck-intake.md`。CPU CI使用`requirements/ci-cpu.txt`哈希锁；缺依赖或任何skip均失败。3＋8模板为空收件槽，历史发行截止逐期显式填写，不能用月份或旧说明自动推断。`deck_intake`记录不是可训练运行配方。

- 阶段划分按最新澄清：云端headless规则兼容/数据隔离/实际GPU与恢复检查属于训练；PC产品/客户端互操作归阶段3，LLM/provider仅可选，不阻塞本地基线。三个设计截止显式为2022-09-30、2022-12-31、2026-11-01；2026期包含日本当地11月1日当日正式OCG发售，禁表仍为2026-10-01生效的2026.10节。截至2026-10-25仅日期已选（date_selected），最终卡池未到日/未核；11月1日JST当日及之后按实际正式发行与来源逐项核对，未齐仍fail closed，不用合成日期或旧null夹具冒充最终池。
- 当前软件交付目标是可调用代码、资源整理导入、训练入口、恢复与自包含交接；用户提供卡组后进入腾讯云第二阶段。此前把GPU实机、性能调优、正式训练或能力验收当作当前开发完成前置的表述有误，予以纠正：GPU锁安装、实机检查和吞吐/数值/恢复验证属于第二阶段启动与训练工作，不是当前软件开发阻碍，不另加泛化门槛。
