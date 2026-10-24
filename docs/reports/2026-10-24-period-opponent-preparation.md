# 分期训练准备增量：截止、来源与非LLM驱动

本批在原整合分支继续，PR依赖仍为1→2→3。没有合并、付费训练、外部模型调用、第三方程序执行或原生故障实验。前批311项CPU、23项正常引擎和实际CPU更新/恢复仍是[原版本证据](2026-10-24-pretraining-engineering.md)，不能替代本批新增路径的检查。

## 已补代码与阶段边界

- 两个历史设计截止显式为2022-09-30、2022-12-31；2026截止仍null，缺值拒绝放行。禁表生效日与发行截止分别配置。
- 新计划去除PC产品P-01前置；旧计划仍按原字节读取，有效训练门槛排除PC。基础训练不依赖LLM/provider，未改预算计算或付费启动能力。
- 默认whole-plan仍完整验证11槽和三期。宿主可显式选selected-period，只验证已选期实际主槽、分区对手、来源/截止/版本、物理root和模型；未选期明确unselected_not_validated，不能for_runner/require_task。2026缺资料不再阻塞已齐的2022单期工程运行。
- 分期宿主可绑定现有PublicSnapshotPolicy/frozen-duel-greedy-v1，核对本项目完成更新的CPU模型、词表、资源和文件摘要。跨期/旧未分期模型必须明确推理迁移，actor修改后重绑目标profile；这不是跨源码恢复旧训练器，也不是历史或强度资格。

## 实际来源审计

[来源索引](../../configs/historical-listing-sources-v1.json)保存锁定CDB、社区禁表、2份既有工程profile和6份固定来源YDK。第三方数据来自mellfy-puppy/ygo-tools-for-dsh@ab963c1cb9776bea4262ae1bba38f541ec70e357；只读取卡号文本，不把它们当正式用户牌表、历史主流或获许可训练数据。

实际只读审计为8份×3期共24项，结构在当前锁定CDB下通过且无未知卡号；三个逐卡发行来源全缺，故没有一项认证为历史合法。社区2022.7节拒绝Albaz，2022.10节拒绝Tearlaments/Albaz；2026.10节拒绝Tearlaments/Albaz/Labrynth/Swordsoul/Kashtira，所有2026总状态仍因截止null而blocked。逐卡数量/限额与检查摘要见[聚合原始结果](2026-10-24-historical-listing-summary.json)，完整报告留在云端`.cache/historical-listing-audit/report.json`。

已核官方日期URL和缺字段在[官方来源状态](../../configs/official-source-evidence-v1.json)。先前官方HTML下载被代理403拒绝，本批没有重新访问该路径或换工具绕过。两份变更公告不等于完整累计表；固定社区禁表不自动获得官方认证。历史正式资料只需可靠覆盖所选允许池和课程涉及的卡/机制，不能以本审计猜发行日、旧文本或完整效果语义。

## 静态第三方覆盖与桥接

[实际目录清单](../../configs/windbot-source-inventory-v1.json)有64个Executor源文件、62份YDK。63条deck_executor记录包含通用文件，不等于63个成熟bot；YGOFTKExternal单列external_policy_only。固定源码为.NET Framework4.8/x86，外部策略构建条件与完整Executor构建不同，尚未认证本工程协议/核心兼容。

新增PreparedIndexWindow将固定席位当前合法DTO中的0基索引严格映到已有action_id，绑定state_version和请求摘要。组合只接受已列出的合法MSG15无序集合；未知、越界、旧窗口、原始响应和隐藏字段拒绝。它没有传输/进程启动，状态为prepared_not_connected，详见[桥接说明](../development/static-windbot-bridge.md)。

实际生成3期×6份公开样例×64驱动=1152行[静态矩阵聚合](2026-10-24-static-windbot-coverage.json)：576未核、192静态拒绝、384截止未定阻塞；所有第三方驱动均not_run，历史/操作/强度资格false。完整矩阵留在`.cache/static-windbot-coverage/report.json`。本地Python冻结模型的正常运行证据另列local_operational_references，不应用于任何WindBot行。

## 本批检查与待更新证据

来源/旧收件24项、纯DTO桥接13项、宿主/输入/runtime44项针对CPU检查通过；另有只读独立审阅和6项选期边界检查通过。新增正常引擎、最终安全白名单、源码包与CI结果在收尾后按真实收据补入本节。

首次未训练actor对冻结模型的CpuTrainer有界采样未能终局，0更新，没有记为通过。100步合法聚合诊断显示模型有正常召唤/pass而非持续shuffle，callback_errors=0；弱actor的失败不能推断驱动不兼容。后续正常检查使用已有PublicRulePolicy作actor、同一已更新base作冻结对手，保留原上限和模型；仍不评估其强度。失败证据不删除。

## 腾讯云接续与真正剩余依赖

1. 按[自包含交接](../development/training-handoff.md)取得完整源码/新包，安装CPU锁，用既有脚本准备锁定native，运行明确普通检查；不要使用旧59dd60b包代替本批新增源码。
2. 2A硬件工程试跑需要已获准目标GPU主机、实际CUDA/驱动/哈希锁及运行参数，再做数值/采样/恢复/吞吐/显存检查。当前只有CPU，不能伪造目标GPU证据；不需要先完成PC产品或连接LLM。
3. 2B正式分期训练需要用户3＋8及目标/分区，2026明确截止、相应历史发行/累计禁表/所需规则证据。所需对手按真实牌表与独立操作/强度记录选择，不能把源文件数或本批普通对局当成熟bot资格。
4. 真正选择WindBot/外部provider路径时，才需相应固定实现的可信构建/传输/兼容/时限与权限验收；不阻塞现有本地规则/冻结模型工程基线。未安装或编译未知第三方代码；这不是已完成的外部接通。

正式模型规模、课程配比和能力统计在实际小试/评估前冻结，不以本批合成测试或一局胜负替代训练能力。PC标准客户端互操作/UI/本地性能归阶段3。没有额外云账号、凭据或资源权限的申请。

PR3元数据更新此前被自动审批拒绝，标题/说明尚未更新；本批遵父任务指令不重试，不更换工具。代码和仓库报告可照已授权流程提交推送，此拒绝不阻塞独立工作。额度工具在本环境不可读，当前数值由父任务实查；不把历史64%当即时余额，达到20%保存停止。
