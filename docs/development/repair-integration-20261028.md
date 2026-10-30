# 2026-10-28 核心修复集成与恢复交接

核心四路修复已接入独立分支，最终 19 项跨模块检查通过。真实 checkpoint16 尚未通过旧运行时恢复/新代迁移，原训练目录只读，训练 hold 保持有效。额外多因子模块只登记，不导入基模或活跃训练，也不作为核心恢复门槛。

## 版本与来源

集成目录：N:\YGO-Kito\_migrated\CodexData\2026-10-28\task-13\integration；分支 codex/integration-20261028。基线为 PR8 的 5cf3dc1ca189e794a5bd5a915b2e24a0070a4095，tree 9376d994c733862461029e622a026787b4cadcaf。通过授权 GitHub GET 和可读本地缓存构成单提交浅仓，757 blob、802 对象核对。这不是完整 clone，没有读取被拒绝的原 .git。

| 输入 | 独立复核后的版本 | 集成方式 |
| --- | --- | --- |
| 监督 WIP | ZIP 22725e86b0a8841fe82072d0ce430d976ccb9f7edc6edae78cb14a25c3fa5c11 | 提交 2862156；Side/task/proof 和预设 CB 保护保留 |
| A 决斗 | 7ab0dcc → bb5deab/72bdc79 → 2933367dc0329872688a48eaaed3c83155124d5e | 当前累计 repair 只应用一次，不重复叠 followup/runtime |
| B 构筑 | 041c72bbc6a2fb3288e0aec419c12fd3be9a641b | 19 个最终 blob 逐一核对导入，all-v2 已包含其余增量 |
| C 统筹 | 77b5c5551dc15191c796aaea9f707e536ac36e36 | 最终累计 patch 和 3 个共享 adapter 合入；旧 2de499f 仅历史 |
| D 效果 | 0850819 + 45fb85a224b4c99a723bc9cd1bb9a2051c5bd54e | 语义 v2、构筑 v6、autonomous v2 严格绑定 |
| 额外模块 | ddaf81ee01990f5f047f0694188980a9475b77f2 | 仅登记，等父端定义和用户确认 |

所有交付摘要见 configs/repair-integration-inputs-20261028.json。专窗 27/111/32/45 项报告各有覆盖边界，不等于本集成代码原生全能力验收。

## 已完成的接口收口

- 目标→优化→目标→优化→基础 CB 推理。四个具体输出真实交接；参考构筑不作为 learner。任务准入与基础 CB 分离，unknown 不作失败负标签，没有额外最终 CB 门槛。
- 生产、计数、监督和断言统一 basic-cb-inference-*.json；缺号不覆盖旧证据。真实 recorder 输出被独立 audit 子进程读到。未完成时 basic_cb=None 保持 None/False。
- 同一个 CycleBudget 到新 provider、内部 route verifier 和每对候选比较；持久 cycle_id 隔离目录、比较 namespace、DataIndex/feedback ID。
- forecast 分别校 CB task/deck 主体摘要，以及 best/retained 自己 validation.attempts 的任务证明。复核回执只要求任务验证与基础推理已执行，不要求 CB 成功。
- 机制 producer 取 theme core 与 task.pool 的交集，包内所有卡必须在池中；在 controller 开始前真正传入 portfolio，缩池不导出池外融合目标。
- 决斗读取 basic_cb.routes 各自的派生 task/proof、校验归属并净化审计字段；课程传实际 deck。LoRA 完整动作分页、saved bias、loss/probe 和统筹可空 route label 同时保留。
- 新实测修正：CB 派生任务为已经在牌组中的目标/开局素材添加局部最小数量；换备增加上下文 token 时同步给机制通道补零。原构筑目标不被派生要求修改。
- 生产 worker 实际安装 before/after unit callback。缺失、失联、违规、hold 均停止并保存边界；独立 PID/run_id、启动 ticks、boot ID、策略/脚本摘要和心跳必须匹配，不能以主进程 passed 代替监督。

## 原课程与 009

原 source 的 115 个绑定模块与冻结 formal-course-source-006.tar 一致，006 SHA256 为 3e1296fd468e7fb51b7b34c89f37cd6091511e0e02f2bf215c5be0df6b5f75cc。监督 WIP 11 文件与 github-source 一致，但训练 source 仅 3/11 相同；五个包模块、worker 和两个测试不同/缺失。不能称原 source 已安装修复。

checkpoint16 SHA256 为 31784ea14850c4b458707af2f8b4b7fdda9f0c01d0e064acc3996125b7371e53，latest 匹配。只做一次 CPU weights-only 元数据读取，摘要未变，没有旧运行时 restore。goal5/optimizer0/duel27/coordinator37、非空 Adam、RNG、账本完整保留；旧 24 BO1 与修正 2 BO1 独立保存，不作能力验收。

009 仍只有 clean task、route001、provenance、progress 四文件，progress 停 actual_four_concrete_handoffs，无完整四步/CB/summary。route001 为 constraints_satisfied，effect/strength 均未验证。CIM 查询被拒绝，活进程仍 unknown；没有重启或换方式枚举。历史 13+4 丢失结果仍 unknown。

## 显式恢复与迁移

scripts/migrate_coordinator_course.py 要求旧运行时 restore_latest 和完整绑定/账本检查后的 export；在独立新目录生成并再次完整恢复。实际旧恢复应使用校验后的课程副本，避免旧 DataIndex 构造器写原索引。

组合迁移保留旧构筑张量及非空 Adam，增加零机制投影和 lazy Adam 槽，统筹扩展 scope/budget。实际构造器产生目标绑定，物理卡/词表/环境索引、游标、RNG、已有模式、调度器、历史和预算逐项比较。父索引使用 mode=ro，只在新代实例化 DataIndex。

旧 session/fill/feedback/seal 保存在带摘要的 pre-mechanism-kernel.weights，现场语义缓存重新建立，不重放学习。明确传 transition_to_postconstruction_cb=True 时，只在新代移除旧 source 固定 route/activation/resolution 和强制图要求，保留一般约束/偏好；基础 task 必须没有待删除的显式卡需求。旧现场另存 pre-policy-construction.weights。新代从未构筑状态暂停，旧对局记录/计数不改写为新流程证据，不重置课程额度。

合成验证采用 PR8 基线原始四模块，身份固定在 tests/legacy_course_5cf3dc1/provenance.json。真实旧版模型产生非空 Adam 和 session，经旧 restore/export、新组合迁移及新 restore，父目录所有文件字节摘要一致。这验证工具和接口，不代表 checkpoint16 已迁移。

## 证据与剩余事项

原始失败、修复复测、每次命令、每例结果、源码摘要保存在 docs/reports/repair-integration-20261028。最终 cohort 19/19，零 skip。此前半程夹具实际上跑完、错误类名、UTF-8 启动参数遗漏、真实接口错误和 SQLite 父索引写事务都保留历史；未做原生游戏或正式训练。

CI allowlist 增加跨模块、严格旧版迁移、监督 13 个子进程合同，以及真实 Linux daemon→生产 unit guard：健康进程放行一个合成单元，进程退出后保存暂停并阻止第二单元。CI 的实际提交/run/结论另记；旧 run 40607096034 是 failure，不能据此称新代码通过。

1. 被拒绝：本机 WSL Python 返回 Wsl/E_ACCESSDENIED，真实 checkpoint16 的旧恢复/新代迁移及该宿主独立监督接线尚未完成；没有换入口绕过。原 N 盘 Git 查询 Permission denied，已停止；源码准备通过授权 GitHub GET 完成。
2. Unknown：009 进程 CIM 查询被拒绝，不能认定已退出或重复启动。
3. 物化失败：ocg-negation-rules-2026-10-28.zip，期望 SHA256 3de42295f00998d836b3f8e6b7bf16e180f8f02bfef00787e4fae1eb197b4ad3。当前支持的 consumer-local Library helper 返回 library file transfer failed: download failed，本机 ZIP 不存在；未猜 URL/通用下载绕过。docs/rules 与机器资源纳入待可用交付，资料不能自动充作决策能力。
4. 网络替代：Git CLI clone 的既有代理连接失败，未改代理；同 PR 发布使用授权 GitHub 连接器。训练 hold 仅由父端在必要真实验证和恢复授权后协调；额外模块不阻塞。

发布追加结果：GitHub create_tree 第一次被自动审批拒绝，理由为目标/授权未核实；只读 get_repo/get_user_login 随后证明仓库公开、连接账号就是 owner 且有 push 权限，PR8 头仍为原 5cf3dc1。基于新证据的一次重试仍被拒绝，理由为缺少审批认可的直接用户发布授权。两次均没有创建确认或 ref 更新，已停止该动作，不能改走 CLI/另一工具绕过。新 CI 未触发，原 run failure 保持。具体记录见 publication-blocked.json；本地 patch/恢复包可审阅后由父端解决此发布授权阻碍。

后续授权记录：2026-10-28 03:11:48 UTC，用户直接确认允许本次代码和文档更新同一公开 draft PR8，不合并、不训练、不额外公开资产。原 create_tree 路径在这次确认后已获审批，完整交付 tree 已逐字节身份匹配。此前两次拒绝记录保留为历史；实际远端提交及对应 CI 结果在 PR8 描述和消费者本机 publication-result.json 中记录。本段为 ref 更新前快照，不将上传授权等同于原课程迁移或恢复训练许可。
