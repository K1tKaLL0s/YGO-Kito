# 固定 WindBot 来源：DTO 桥接准备与覆盖矩阵

本层只准备本项目合法玩家 DTO 的索引映射与静态覆盖记录。状态始终为 `prepared_not_connected`，没有 WindBot/AI.Server 进程、远程 provider、原生响应生成、真实规则对局或强度验收。未下载、编译或运行第三方代码；既有 Agent 协议与分期运行器不被替换。

固定来源为 `mellfy-puppy/ygo-tools-for-dsh@ab963c1cb9776bea4262ae1bba38f541ec70e357`。静态核验的 `skill/backend/ygopro2-duel.mjs`（blob `fe21077ad927b2dd33264c50592e78892afba52c`，`prepareSelectedAction` 附近）支持0基 `actionIndex/index`；`selectionIndexes` 在 factorizedSelection 模式下按唯一索引、范围和数量验证。它之后构造自己的响应，本项目不调用该路径。[固定来源](https://github.com/mellfy-puppy/ygo-tools-for-dsh/blob/ab963c1cb9776bea4262ae1bba38f541ec70e357/skill/backend/ygopro2-duel.mjs)。

固定项目的 `.NET Framework 4.8/x86`、`ExternalPolicyOnly` 条件及 `ygoagentskill-external-policy-v1` 只说明构建/外部策略候选结构。完整编译包含的 Executor 与 `ExternalPolicyOnly=true` 下的 YGOFTKExternal 不是相同驱动集合；64份 Executor 源文件、62份 YDK 文件也不自动组成64个已接入本工程的机器人。

## 现有接口与新增缺口

`agent_driver.Client` 已提供本地 JSON Lines 传输。`AgentBridge` 的 opponent 角色已有 `duel.next` 返回合法单席位 `DecisionRequest` 与 `state_version`，以及 `duel.submit_action` 旧窗口/非法动作/超时处理。新增 `external_policy_bridge.PreparedIndexWindow` 只补数字索引到这些已有 `action_id` 的严格转换，不另建引擎或传输。

```python
from ygo_kito.contracts import DecisionRequest
from ygo_kito.external_policy_bridge import PreparedIndexWindow

# live_window 是宿主实际取得的非terminal duel.next结果；seat由宿主固定。
request = DecisionRequest.from_dict(live_window["request"])
prepared = PreparedIndexWindow(request, live_window["state_version"], observer=seat)
packet = prepared.packet()
# 此处仅得到可审查数据，没有调用任何 provider。
reply = {"state_version": packet["state_version"],
         "request_sha256": packet["request_sha256"], "actionIndex": 0}
converted = prepared.translate(reply, current_request=request,
                               current_state_version=live_window["state_version"])
# converted只含已有duel.submit_action方法/参数，action_submitted仍false。
# 宿主另获相应调用授权后可复用client.call(converted["method"], converted["params"])。
```

`actionIndex` 和 `index` 都仅指本层 packet 所附 **当前合法 DTO 的 actions 顺序**。不是 WindBot 自己的候选顺序，也不是 native index。`selectionCandidates` 则按同一 DTO 已有合法动作的首次引用顺序列出窗口局部 ref；匿名目标仍匿名，不从卡库/牌表或原生消息恢复隐藏身份或位置。

回复必须带绑定的 `state_version/request_sha256`，并且 `actionIndex/index/selectionIndexes` 三者严格任选一个；外部源的优先级规则未照搬。布尔、负数、越界、重复索引、未知字段、原始 response bytes、旧窗口或被改过的请求均拒绝。缺连接或无转换时不模拟成功，不自动重试或回退一个动作。

`selectionIndexes` 目前只支持 MSG15 的无序卡片集合：数量在当前 bounds 内，并且必须唯一匹配已经列出的合法 `select` 动作。不会自行拼 native response 或创造未列出的组合。同引用对应多种动作时拒绝 factorized 模式；增删、排序、祭品/求和、落点、数值等其他窗口使用完整已有动作的 actionIndex。取消也必须选择明确的合法 pass 动作，不能传裸 `-1`。

玩家 DTO 由原契约检查：固定 observer、seed 为 null；hidden 对象不携身份。合法的己方手牌或依法获知的私有信息仍按原 DTO 边界保留，本层不读取对手手牌、整副牌表、种子、审计或原生 buffer。输出不是 upstream wire 兼容承诺，更不证明外部模型已连接。

## 完整静态覆盖矩阵

`coverage_matrix(period_ids, samples, drivers, listing_checks=...)` 生成完整的 **显式时期 × 样例牌表 × 驱动** 笛卡尔积，不根据主题名猜时期热度或驱动适配。现阶段可输入用户既定三期、实际6份公开样例和静态审计得到的驱动清单；例如3×6×64会产生1152条待核记录，不表示1152次对局或资格通过。

schema_version 为1，输入字段：

| 数据 | 字段 |
| --- | --- |
| sample | `sample_id/deck_sha256/artifact_sha256/source_pin/source_path`。deck为规范化牌表摘要，artifact为来源文件字节摘要，不能互换。 |
| driver | `driver_id/source_pin/source_path/mode`；mode为 `deck_executor` 或 `external_policy_only`。 |
| listing_check | `period_id/sample_id/deck_sha256/status/evidence_sha256`；仅接受 `unverified/blocked/rejected/checked_under_supplied_evidence`。 |

sample/driver 必须属于上述固定 pin；ID唯一、来源路径为仓库相对元数据路径，牌表/证据 SHA明确。不读取路径上的文件或执行代码。现有来源审计报告中的每个 sample 可按其 `source.source_pin/source_path/artifact_sha256` 投影；每期 `historical_listing_status` 和整条静态 check 摘要可写入 listing_check。源审计缺数据就保留 unverified，不填假截止或用户牌表。

`coverage_from_listing_audit(report, drivers)` 直接消费已有来源审计 JSON，只选择 `third_party_sample_not_user_deck` 条目并保留其牌表、文件与固定来源身份；两份工程 profile 不被改称 WindBot 牌表。`blocked_cutoff_unspecified` 映为矩阵 blocked，同时在 `source_status` 保留原因。每条源 check 和整体审计都绑定摘要，整个转换不运行第三方代码。

`coverage_from_source_inventory(inventory, report)` 可直接消费 `configs/windbot-source-inventory-v1.json` 和该审计报告，绑定整份64驱动目录证据摘要。63条 deck_executor 记录不是63个已合格成熟 bot，另一条 YGOFTKExternal 单列外部策略模式。按 basename 配对只属文件目录证据，不会改变每行 deck_driver_match。

输出保存来源清单、全部 rows、每行身份 SHA和 matrix SHA。行中分别记录静态 listing、`deck_driver_match:not_checked`、`driver_execution:not_run`，以及始终 false 的 native/historical/operation/strength 资格。只有 external_policy_only 的索引转换记录为 prepared_not_connected；普通 deck_executor 的桥接适用性为 not_assessed。卡表静态通过不能自动改变这些字段；声明 `strength_qualified` 等越级 listing 状态会被拒绝。

该矩阵是可重复的盘点准备。实际 Executor 构建/固定核心桥接、时期卡文和旧规则、完整合法操作、超时、对局吞吐与独立强度都须另有实测证据。DSH/provider 未配置不阻塞本地规则/冻结模型的小工程训练，也不能作为未完成这些自主桥接工作的原因。

## 单独接入本地冻结模型的正常运行证据

可信宿主真实完成采样/自然终局/私有重放/冻结模型重载、宿主重载、actor重绑和冻结权重检查后，可调用 `attach_local_snapshot_proof(matrix, proof, expected_scope=...)`。它只核摘要和精确 scope，不在本模块执行或重放原生测试，也不接受外部 policy 回复作为证明。

scope 必须逐项匹配宿主另外核实的 `period_id/period_context/versions/resources/profile_sha256/own_deck_sha256/opponent_deck_sha256/model_sha256/driver_version/driver_implementation_sha256/controller`；controller为local_snapshot，model指该对手快照。聚合 proof 的 source_component 明确 `components.duel`、原组checkpoint SHA、实际已更新的base模型、complete-episode边界与单独推理工件SHA；7个 passed 全为true，正常检查自身更新数为0，历史/强度标志保持false。summary SHA覆盖该字段之外的完整对象，错误scope、摘要、failed检查或跨WindBot行应用均拒绝。

通过后只在 `local_operational_references` 添加这组精确身份的 `normal_operational:true`，`applies_to_matrix_rows:[]`；1152条 WindBot行仍全部未运行，不能借本地Python模型成功宣称某个C# Executor已接通。`source_checkpoint_restore` 在此仅表示显式冻结推理模型/词表重载核对，不代表跨源码训练checkpoint的optimizer/RNG恢复或历史课程资格，输出 `training_checkpoint_recovery_verified:false`。

安全验证：`PYTHONPATH=src python -m unittest tests.test_external_policy_bridge -v`。测试使用明示合法 DTO、匿名选择和本地 transport fixture；不访问网络、不启动原生引擎或外部程序。
