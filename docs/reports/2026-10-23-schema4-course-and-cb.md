# Schema4长周期、索引恢复与真实CB语义增量

本批按[统一设计](../plans/2026-10-22-unified-development-spec.md)继续同一云端、工作分支与[PR #1](https://github.com/K1tKaLL0s/YGO-Kito/pull/1)。[可重复命令及边界](../development/schema4-course-and-cb.md)承接此前已通过的基础接口，没有改原始设计、学习TODO、main、权限或开启付费资源。

**本报告记录云端新代码的实测，不是当前PR代码已经升级的证明。** 静态工程配置发布被自动审批拒绝，云端提交保留；本批PR只计划发布共同公开投影、聚合证据和文档，代码/config仍停在前一已发布里程碑。相应新增清单项保留“部分完成：实现/测试完成，代码发布受阻”，不假勾选交付完成。

## 实现与验收范围

| 清单ID | 交付范围 | 未外推的能力 |
| --- | --- | --- |
| T06-03 | schema4实际接四模型基模/LoRA多周期、冻结评估、统筹反馈，组合目标复用同一运行器 | 正式三期课程、合格强对手和协同学习收益 |
| MG03-03 | 公开事实计数＋真实发动/非无效连锁处理＋条件同调/超量终场，实际双构筑学习/恢复和两侧目标见证 | 全文效果解析、任意CB/混轴、稳定性/抗打断/竞技构筑 |
| D08-02 | 已提交索引随组checkpoint保存/新目录恢复，实际更新准入、阶段消费和用途隔离 | 三期历史资料已齐备、全部旧加载器迁移或正式终验已通过 |
| T-07 | 固定DSH源码/许可/协议差异只读核验；当前规则/冻结模型接口保留 | DSH/WindBot已接固定core、实际操作/强度合格 |

云端代码保存点`342755b`先完成纯计数索引课程；`40d6d54d3b930f797b3b7858e8a716c1e7afb41c`接组合目标和稳定托付身份，`40d3e6510361aa000b87e72d44bd75c7023b6c6a`修正测试夹具并保留显式云端工件。最终完整回归/CLI均使用此代码，实现SHA-256为`d5f00f432a153269d517c20c2e6656e077829cd8362b059d7f92fa8838d13cd8`；文档整理未改受测Python源。上述为云端提交，不能误作GitHub已发布提交链接。

物理core/scripts/cards/client/Lua和协议仍沿锁定版本，未改脚本或注入起手制造通过。构筑特征升`build-task-catalog-candidate-v5-combined-native-objectives`；决斗仍`legal-player-dto-v5-private-knowledge-hierarchy`。模型组角色与独立权重不变。

## 真实目标与更新

公共目录按效果/主题/情境交叉召回救援猫，卡文/脚本SHA留出处、语义仍标lexical/static inference。schema4同时约束兽族计数，声明真实起手、救援猫发动及对应连锁处理、超量终场。合法DTO搜索自动找路线，没有预写动作顺序。真实核心记录救援猫从场上送墓、reason=128费用，发生在CHAIN_SOLVED之前；卡组特召与实际超量完成均由脚本执行。

链处理只说明该链已执行且未被无效，不推测任意效果收益；终场仍需核心独立证明。正监督同时绑定计数与原生路线，验证时实际独立重放；优化对比的双方都必须有目标见证。没有路线/偏好差异时拒绝造标签。新目标、起手、发动和连锁要求实际进入神经编码。

当前工程组合词表下，两构筑网络各17,969参数；已实际执行两批非零更新、从首批checkpoint恢复并精确匹配下一批及四步构筑。更广效果/目标仍未支持时保留unknown，不将搜索未找到作不可能负例。完整长周期和最终资源数值以本批最终收据为准。

## 索引和恢复

schema4基模更新及LoRA损失都要求训练准入；注册对手PPO另核自身实际新采样密封。用途、资源、任务/实际对手、种子和列表跨分区保护继续有效；静态监督复用与PPO新样本分开。

checkpoint嵌入已提交SQL索引快照/SHA，每次恢复生成新工作索引目录，和模型/优化器/LoRA/调度/RNG/数据标记/预算同一阶段保存。已终止尝试留下的未提交SQL不会跟着旧模型重新出现。保留验证、改用途数据、损坏索引和重复阶段在训练前拒绝，冻结评估不改权重或训练RNG。

`period_id`严格为当前engineering-custom，不能把2026社区资源重标成2022历史数据。当前真实训练/验证列表、对手及种子隔离得到工程证据；三期发行数据/官方禁表/跨期加载仍未完成。

## DSH接入的实际核验

只读锁定`mellfy-puppy/ygo-tools-for-dsh@ab963c1cb9776bea4262ae1bba38f541ec70e357`。其[固定README](https://github.com/mellfy-puppy/ygo-tools-for-dsh/blob/ab963c1cb9776bea4262ae1bba38f541ec70e357/README.md)声明0BSD插件、GPLv3 AI.Server/YGOPro2及各自数据许可；[WindBot许可](https://github.com/mellfy-puppy/ygo-tools-for-dsh/blob/ab963c1cb9776bea4262ae1bba38f541ec70e357/skill/resources/ygopro2-bridge/windbot/LICENSE)和[源码目录](https://github.com/mellfy-puppy/ygo-tools-for-dsh/tree/ab963c1cb9776bea4262ae1bba38f541ec70e357/skill/resources/ygopro2-bridge/windbot/source)另为MIT。

[桥接清单](https://github.com/mellfy-puppy/ygo-tools-for-dsh/blob/ab963c1cb9776bea4262ae1bba38f541ec70e357/skill/resources/ygopro2-bridge/windbot/bridge-manifest.json)标记`ygoagentskill-external-policy-v1`；[实际动作代码](https://github.com/mellfy-puppy/ygo-tools-for-dsh/blob/ab963c1cb9776bea4262ae1bba38f541ec70e357/skill/backend/ygopro2-duel.mjs#L812)按actionIndex、actionLabel或selectionIndexes生成其原生响应，运行路径涉及AI.Server.exe/WindBot.exe、YGOPro2房间和AgentPort。这与本工程固定core的版本化action_id会话存在可核的协议差异，不能直接混用。此结论是源码推断，不是实际互操作结果。

未运行随包二进制、未替换本工程卡库，也未启动provider。下一最小自主工程是从可核源码构建、固定core消息/房间桥接与合法观察映射，再实测非法动作/超时回退和具体牌表操作资格；最后另评强度。文件存在和MIT/0BSD许可都不能替代上述验收。此部分不需要等用户8套牌表或DeepSeek凭据才可继续准备，实际外部模型端到端则需目标环境。

## 发现的问题与修复

1. 首次schema4多周期在重复准入时误报“artifact ID cannot be overwritten”：DTO tuple经JSON保存变list。独立最小反例确认；规范化保存表示后相同数据重试幂等，不同数据仍拒绝。失败尝试保留此前checkpoint，未把丢弃的未提交更新算新规范阶段。
2. 原真实路线课程为四次各30秒检查预留123秒；计数课程实际只有一次30秒交替，因此误提前停止。按各工作流实际有限上限预留，保持每次总活动180秒，不放宽正式训练门槛。
3. 初版工程偏好在候选中全为平分，数据生成正确拒绝训练优化器；改成明确有差异的工程属性偏好，不发明胜率或收益标签。
4. 组合路线把计时嵌到native_route，统筹只排除顶层计时，导致等价托付账本不同。两次独立真实托付确认唯一差异为`validation.native_route.elapsed_seconds`；递归分离计时后，实际托付/账本一致性回归通过，原始计时仍保存在私有证明。
5. 长周期验收流程完成后，测试夹具的路径属性`run`遮蔽unittest方法，导致断言未执行。改为`run_dir`，最终完整回归重新执行全部实际流程和四项断言，未拿这次夹具错误当测试通过。

失败、诊断与最终通过分开保留；完整私有JSON仍不上传。

## 最终命令与证据

| 最终命令 | 结果 | 命令墙钟/子进程CPU |
| --- | --- | --- |
| `.venv/bin/python -m unittest discover -s tests -v` | [172项通过，无跳过](2026-10-23-course-final-unit.log) | 12.464 / 15.563秒 |
| `.venv/bin/python -m unittest discover -s integration_tests -v` | [172项通过，无跳过](2026-10-23-course-final-integration.log) | 1168.057 / 1223.524秒 |
| `.venv/bin/python -m ygo_kito build-train-cpu --root .cache --state-root .cache/course-final-build --run-id combined-final --task configs/build-combined-native-v4.json` | 退出0，stderr为空；完整stdout含私有路线，仅留云端 | 16.854 / 17.682秒 |

从2026-10-23T09:40:50.441802Z到10:00:47.820673Z，同源完整回归通过；新增4项单元、9项真实集成，未借用上批168/163通过结果。[命令/源码/日志哈希收据](2026-10-23-course-test-results.json)与[共同公开投影/聚合证明](course-cb-evidence/README.md)可审查。集成命令显式设置`YGO_KITO_COURSE_ARTIFACT_ROOT`到新的云端缓存目录，只保留本次真实工件，不从旧测试结果冒充通过。

长周期验收实际执行中断恢复、连续和阶段预算三次两周期流程，每次四基模预热后各角色两次LoRA更新，合计36次已确认物理优化器调用、9个提交训练整局、6个冻结评估整局；每个流程13个提交阶段。中断恢复与连续的模型/优化器/RNG/事件/模型版本/统筹账本一致；阶段预算恢复不重复更新、不重置总上限。最终中断恢复流程索引7个工件：4训练、3验证（含构筑各1份），5份完整决斗标记、6个构筑消费标记，未混入已丢弃尝试。

独立双构筑命令另有每角色2次规范更新，含恢复对照物理6次优化器调用；四步组合目标全有核心见证。真实恢复后的下一批损失与权重一致；篡改处理目标、用仅终场成功冒充指定连锁处理、无目标见证的优化对比、held-out/重标数据和损坏索引均拒绝。初始/训练后权重哈希、非零梯度与参数/适配器变化在聚合证明中分列，不能由此推断学会合理构筑或强对手策略。

5份被保留的真实整局在云端各独立重放，再导出双方逐字段一致的严格PublicEvent投影；另2个原生CB见证实际独立重放，只发布聚合验收布尔值/轨迹SHA，完整证据不上传。公开目录经禁止私有字段检查和大小/SHA核对。重放与恢复对照不增加独立能力样本。

实际CPU为AMD EPYC 9V74、PyTorch2.14.1+cpu、单线程，无CUDA/GPU或provider调用。三流程验收父进程墙钟308.571秒、父CPU102.921秒；中断worker的完整CPU与进程树峰值未知，未伪造总量。最终恢复流程累计活动80.558秒（180秒上限），记录1个未测量丢失段，最后报告worker峰值607457280字节（579.32MiB）。独立构筑进程内部墙钟13.965秒、CPU14.382秒、峰值391671808字节（373.53MiB）。子进程RUSAGE的累计高水位不冒充该CLI单独峰值，正式GPU吞吐、100h可达性和PC时延仍未知。

## 进入正式训练前的最小剩余工程

| 性质 | 最小后续 | 外部输入边界 |
| --- | --- | --- |
| 自主CPU工程 | 更广效果/情境事实与CB目标/错误分类；三期官方禁表、发行截止卡库与跨期数据加载；bot/DSH固定core桥接、真实操作资格/对手分布；标准回放与计时/看门狗 | 不能笼统归因用户尚未交牌表或腾讯云未开 |
| 用户资料 | 3＋8真实牌表、构筑目标/妥协范围，2026具体发行截止日及待定课程口径 | 用户后交，不阻塞接口与当前工程样例；收到后主动盘点机器人可用性/卡表/历史覆盖再建议主题 |
| 目标环境 | 指定PC客户端动作/连锁/标准回放与端到端资源；腾讯云实际吞吐/显存/成本、CodeBuddy模型/套餐和DeepSeek联调、计费停机 | 本云headless及本地stop不能替代，无凭据不伪造外部端到端通过 |
| 能力验收 | 三期训练、独立BO3/构筑概念与优化收益、陌生卡组LoRA对照 | 必须工程/环境门槛与另行付费授权后进行，不以工程loss或弱对手胜负放行 |

阶段1A/1B/PC、full_phase_1_delivered和formal_training_ready保持未通过。剩余20%保存停止、不用重置卡；当前无实时额度工具，08:45:22 UTC的49%仅为带时间的历史读数。原始轨迹、数据索引、模型与完整验收输出留云端，只发布共同公开历史与聚合收据。

## 代码发布阻碍

目标是原私密仓库PR #1的`configs/build-combined-heldout-v4.json`。自动审批两次拒绝，均未执行：其将保留任务、精确卡池/要求及版本标识判为未获准的私有任务配置。首次拒绝后做了只读来源核验：文件能完全由已发布工程样例及静态常量重建，卡池和原卡片要求继承旧样例，没有读取运行中的对局或用户3＋8牌表；同一版本名也已存在旧工程配置。以这项新证据对同一内容复核一次仍被拒，之后停止该动作。

未通过其他路径、改名、编码、补丁上传或省略审批来绕过。完整源码、三次云端提交、差异清单及可恢复补丁仅在本云端保留；代码/config不进入本次远端树，避免发布缺配置而不可运行的半套代码。允许的公开文档/投影另行更新PR，并明确与云端代码树不同。需要用户明确确认静态工程配置的发布范围后，才可恢复该具体写入；真实私有轨迹始终不在请求范围内。
