# 外部 agent 接口、CodeBuddy 接管与对手配置

本地工程入口已有版本化JSON Lines、固定角色、真实CPU训练控制、卡组/对手注册及真实核心单席位动作。**这不是MCP服务器；未连接CodeBuddy/DeepSeek、未启动付费训练。** 默认训练后端关闭，可信宿主显式--local-cpu-control可启用固定两步决斗CPU配方，真实启动/暂停退出/保存/重启与故障恢复已验；通用长训练/云后端仍缺。当前入口见[整体验收](../reports/2026-10-23-engineering-delivery.md)与[本地控制说明](local-training-control.md)，不以本地通过代表provider或正式阶段通过。

## 启动与工具权限

```bash
cd /workspace/YGO-Kito
.venv/bin/python -m ygo_kito agent-serve --role monitor --state-root .cache/agent
# 一次请求可用：agent-call request.json --role monitor --state-root .cache/agent
```

每行一个请求、响应仅占一行；EOF关闭实际核心。请求格式：

```json
{"schema_version":1,"id":"status-1","method":"capabilities","params":{}}
```

响应统一为 `schema_version/id/ok/result` 或 `error.code/message`。重复字段、非有限数、超长输入、未知字段拒绝。Python `AgentBridge.dispatch()` 返回与线协议一致的 JSON 类型。

| 启动时固定角色 | 可用工具 |
| --- | --- |
| monitor（默认） | capabilities、runs.list/read/metrics、checkpoints.read、opponents.summary |
| trainer | monitor工具＋training.prepare、training.recover、training.control；执行须宿主显式CPU后端 |
| manager | monitor工具＋environment.runtime/register、deck.import/read、opponent.register、coding.prepare_handoff |
| opponent | capabilities、cards.lookup（公开静态卡库）、duel.open/next/status/submit_action/close |

角色/席位/资源路径/种子由宿主启动配置，工具参数不能改角色、换席位、注入原生响应或运行任意命令。编码管理与训练控制不共用一个角色，对手角色不能读取训练目录、完整牌表/审计日志或对方观察。

**这是一条应用工具边界，不是同用户文件系统沙箱。** 外部对手会话必须只获得固定 opponent 实例的封装工具，不同时授予 Bash、文件、进程或 manager/trainer 工具；否则能绕开应用接口读取本机文件。应在 CodeBuddy SDK/工具宿主的权限回调中执行该限制，实际宿主验证列在 EA-07，不宣称已完成。

## 合法对局与回退

```bash
.venv/bin/python -m ygo_kito agent-serve --role opponent --seat 1 --seed 1724 --profile configs/effect-duel-v1.json --controller-source local_contract_fixture
```

依次发送 `duel.open {}`、`duel.next {}`。next返回席位自己的合法 `request`、不透明 `state_version` 和决策期限；另一席位由可见 DTO 规则基线推进，不暴露其私有请求。`cards.lookup {"card_ids":[...]}`只查公开静态文本，不表示该卡存在于对手真实手牌/卡组。

```json
{"schema_version":1,"id":"action-1","method":"duel.submit_action","params":{"state_version":"使用next实际返回值","action_id":"使用当前合法候选ID"}}
```

当前窗口的非法动作或超时采用确定性合法候选回退并记录原因；旧窗口直接 STALE_STATE，不能推进新窗口。stdio 等待输入期间每250ms检查外部响应期限，不需要每次调用LLM。此计时不能打断阻塞的原生C++调用，独立进程看门狗仍属R-12未完成。预算耗尽/未知消息失败关闭，不伪造终局；主动close是中止，不算胜利。

可选 usage 字段包括 input_tokens/output_tokens、amount、currency、provider_request_id；仅登记为客户端报告且 billing_verified=false。缺金额保留未知，不当作0元/免费额度。原生响应索引与全状态审计不返回给对手；控制来源/声明provider/model与实际验证状态分开记录，工程本地驱动使用 local_contract_fixture，不能当真实DeepSeek对局。

## 训练监控与受控操作

训练进程可使用 `RunReporter.resources()` 收集本进程墙钟/CPU/峰值RSS；GPU等指标须由真实框架另行提供，未采集时不造0。可信训练端调用 `RunReporter.publish(snapshot)`，通过字段/有限数/版本校验后带写锁原子发布到 `STATE/runs/RUN_ID/status.json`。它不是外部agent写工具，监控读取无需LLM。M3a已接入实际CPU决斗训练端，M3b增加构筑目标/优化双模型；见[决斗说明](cpu-duel-training.md)及[构筑说明](cpu-building.md)。运行快照必须包含：

```json
{"schema_version":1,"run_id":"run-id","state":"created","revision":0,"model_versions":{},"metrics":{},"checkpoint_ids":[],"source":"trainer"}
```

这只是格式示例，不创建真实训练。runs.list在所选state root尚未发布时为空；契约测试样本明确使用source=local_contract_fixture。M3a/M3b实际CPU训练发布source=trainer、角色版本、参数更新计数和真实小型checkpoint，已通过此只读接口回读。构筑checkpoint的step为成对批次游标，运行metrics.steps为两个角色实际规范更新总数，恢复对照另列物理调用次数。检查点读取仅接受该运行登记的ID，核对元数据/字节数/SHA-256，拒绝路径越界，不反序列化权重。

`training.control {run_id,operation,expected_revision}`只允许start/pause/resume/stop/save_checkpoint。默认无后端，返回TRAINING_BACKEND_NOT_CONFIGURED且未执行；显式--local-cpu-control仅能管理本项目固定CPU配方，不把已有任意CLI命令变成可执行参数。training.prepare只收run_id，实际创建初始权重/版本绑定；training.recover需run_id/expected_revision，核验已退出失败任务的完整检查点再置paused。JSON启动、边界暂停退出、保存/新进程恢复及SIGKILL后连续性已有真实证据，见[指南](local-training-control.md)。

控制原子校验expected_revision，持久请求幂等、同运行版本仅一次操作；uncertain先查状态/检查点，不能自动重试。kernel期限及PID身份检查只保护受管本地worker，本地stop返回cloud_billing_stopped=false。managed任务以SQLite为权威，monitor的runs.read/metrics/checkpoints.read返回实际数据；status.json不是其最新状态。通用四模型长训练、云计费/停机与目标SDK/权限/外部provider仍待验证。

[M3c统筹与组流程](coordinator-model-group.md)另提供固定角色的coordinator-call，用于可信宿主的构筑托付/固定预测/任务租用/结果回收与只读历史；不属于opponent工具。四模型checkpoint及真实trainer指标沿用本页monitor接口回读，原生验证只执行当前支持的BO1工程范围。对手agent仍只能看本席位合法DTO，不得取得统筹任务中的双方牌表/种子/内部审计；宿主角色配置须与OS/进程权限隔离一起落实，不能将CLI的--role参数本身当系统沙箱。

## 卡组导入、绑定和操控方

用户将在本轮工程之后提供预定3＋8套，其中8套由DeepSeek操控；由我们负责导入配置。**尚未接收，不预填、不猜名单、不用工程样例替代，不阻塞本轮接口。** manager依次：

1. environment.runtime读取当前实际版本，environment.register登记环境。只有精确匹配锁定资源、无历史截止日的显式custom环境可标当前运行相容；官方/历史声明保留pending，不能凭声明认证。
2. deck.import使用 `deck_id/environment_id/source/format/content`，支持ydk文本或JSON的main/extra/side。检查40–60主卡、额外/备牌≤15、OCG身份、区域类型及三部分合计别名禁限张数。历史环境未就绪时只做结构检查并标待验，不误用今日禁表认证历史合法性。
3. opponent.register绑定 `opponent_id/deck_id/controller/provider/model/driver_version`，controller可为rule_baseline/bot/external_llm。注册不证明provider可用或机器人足够强，training_ready保持false直到后续真实验收。
4. 宿主启动固定席位：`agent-serve --role opponent --opponent-id ID --own-deck-id ID --seat 1`。双方必须绑定相同、仍与当前资源匹配的环境；旧ready标记不能绕过版本核对。额外卡组可先导入，但当前额外协议未实现时禁止据此启动真实对局。

同ID内容冲突拒绝，修改使用新版本ID，不覆盖他人配置。工程示例source=engineering_fixture；当前没有预装用户卡组或8个虚构DeepSeek对手。

收到实际数据后，我们将主动盘点现有机器人真实支持/可用性/卡表适配/强度证据，对照三个时期历史环境及收到的卡组覆盖，提出应补主题和优先级（EA-08/T-07）。机器人文件存在不是可用或强度证明，本批不提前猜定名单。

## CodeBuddy / DeepSeek 接入与未验证项

`CodingAgentAdapter`目前提供可替换的任务准备接口；manager的coding.prepare_handoff要求明确模型ID、稳定清单ID、工作分支和目标，输出约束/提交/建议argv。它不会启动CLI、登录、配置Key、改权限或自动调用付费后备端点。当前云端实测未找到codebuddy可执行程序，model_verified/executed均为false。

[Cloud Studio官方文档](https://cloud.tencent.com/document/product/1039/131814)说明其内置终端版CodeBuddy，提供非交互打印、模型选择和MCP入口，并列月度500 credit。该文档不能证明用户未来算力实例自带相同服务、SDK共用额度或DeepSeek通用API免费；须在实际环境核查CLI版本、模型列表、账户配额和计费。

后续宿主可参考[官方SDK](https://www.codebuddy.ai/docs/cli/sdk)、[模型配置](https://www.codebuddy.ai/docs/cli/models)和[MCP文档](https://www.codebuddy.ai/docs/cli/mcp)，把本地固定角色dispatch包装成受限工具；保持长连接保存对局状态，或直接在可信工具宿主调用Python接口。当前没有实现MCP/HTTP服务，不依赖Beta内部端点。模型示例不是可用性保证；不自动切换独立API端点或配置持久凭据。

付费训练前仍须完成模型组/CPU链路、真实对手资格和PC门槛，另获采购授权。最新用户已授权有界非付费CPU工程更新，见[M3a](../reports/2026-10-23-duel-cpu-m3a.md)；不启动腾讯云/付费训练，不合并PR、不使用重置卡，剩余20%时保存停止。工程测试、真实规则接口、外部provider端到端和模型能力分别验收。
