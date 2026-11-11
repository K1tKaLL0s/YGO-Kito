# 设计实现修复第一批

日期：2026-11-11，Asia/Hong_Kong。承接用户“现在启动修复，严格依照设计和 R0—R11 方案逐包推进并验收”的新指令；由主进程执行，未启动子代理。本批按[机械执行书](execution/2026-11-10-design-implementation-repair-execution.md)实施，当前为分包进度，不是R0—R11全部完成。

## 包与缺陷状态

| 包/缺陷 | 当前实现及验收边界 |
| --- | --- |
| R0 / F16 | 原7个近期安全测试模块已显式登记一次；原短反例转成有区分力回归，包括默认卡文路径、开发循环、CB回优化、识别待算、129供应方案和参考独立性。R3/F04、R5/F08仍是明确失败的缺陷回归，未用skip或expectedFailure隐藏。 |
| R1 / F01、F02 | 已修Extra来源与除外去向、3/6合法支付分支及1/2抽卡关联、一次召唤处理身份、免素材效果召唤、结束阶段/第二次准备阶段延迟、效果召唤实体的离场替代、装备对象及原攻击力倍数、旧式“在1回合”卡名次数、选择器与原文绑定。共享记录、字典、库存、关系和默认规范化均消费修正结构。R1仍部分完成，剩余复杂卡文见下节。 |
| R2 / F03 | 已把无实战顺序输入时的可满足静态安排与明确联合要求分开；保留整回合限制、自己/对方、同一效果自身处理、必需联合冲突与顺序环。复用关系模块的顺序一致性检查，按卡片/用途方向限定局部处理ID，关系供应前提产生顺序边。已完成对应软件专项，整体仍受R1未覆盖语义及R3枚举边界约束。 |
| R3 / F04、F05 | 未实施。129个可选供应方案仍被128截断；表达式/分支续算和质量完成枚举/失分阶段游标仍须修，未以提高常数代替续接。 |
| R4 / F06、F07 | 已修。统一从Gate理由区分完成失败、算法待算、语义缺口和配置错误；开发完成失败继续S2；同一片重试不增失败计数、两次完成失败才提示。CB回优化优先于静态passed并保留静态证据。公开调度入口的开发/上线排空/用户停止及静态CB记录替身专项已覆盖，未执行CB。 |
| R5 / F08、F09 | 未实施。合法参考仍会受候选可选图约束；新公开入口回归已复现。参考续片及完整参考缓存/一次候选比较仍待修。 |
| R6、R7 / F10、F11、F15 | 未实施。大体积Evaluation搬运、单一权威checkpoint、正常停止保存、RPC生命周期仍保持方案开放。 |
| R8 / F12、F13 | F12已修：ContractError导入明确，静态待算返回定义好的合同错误；验证器内部NameError/RuntimeError/TypeError向调用方传播，外部策略不可用与合同拒绝仍局部记录。识别离线标签、兼容负例、自然组合与分项诊断未改，F13仍开放。 |
| R9、R10 / F14、F17、F18 | 未实施；通用CB目标表达、宿主取消隔离和资源监测后续按方案处理。真实CB/native、GPU/PC实测仍暂停。 |
| R11 / F19 | 本批更新当前入口、总清单、方案状态与接续文件；全部包的最终验收尚未完成。 |

## 当前剩余卡文与版本

规范化已升 `construction-function-normalization-v22`，字典修订为 `public-text-completion-20261110-b8`。原log2、P/V1/V2/S、Main E1/0.9、Extra 1/0.8、实际Main张数、主要+100%/次要+50%、Side方向及参考0.8保持，未修改 `construction_quality.py` 的评分公式。`selector_source`仅绑定解析来源，不创建另一功能家族。

完整旧Evaluation沿现有版本检查保留为stale并重评，未改写旧结果或原运行档。本批没有验证旧课程权重的新源码推理兼容性，旧权重和课程指针未动。

有界只读卡文投影在 `.cache/design-implementation-repair-20261110/r1-card-projections.json`。强欲而金满之壶、紧急瞬间移动、装备旧文、三眼怪的记录对应本批修正；简易/简素融合及部分壶仍保留 `count_negation_policy` 记录。静态评价只使用已知印刷次数，不把尚未执行的“发动被无效是否退还次数”当作前提，也未推断其真实退款规则。

R1仍有实际程序缺口：流星龙的旧式时点/次数与作用域、武神-目一箇支付实体与不同卡名指代、阿拉弥赛亚之仪空场/衍生物及可选处理、金满而谦虚之壶完整翻开/选择处理、次元吸引者空墓条件及全局去向替代。本批保留对应原文和未知；不能将它们解释成用户缺卡文、缺盘面或须补同义结构化输入。该清单是当前有界投影的剩余，不是全卡池完整性声明。

## 实际文件变更

生产/脚本共11个：

- `src/ygo_kito/effect_records.py`、`effect_blocks.py`、`effect_count_limits.py`、`effect_mechanisms.py`：支付、作用范围、处理身份与完整源文本投影。
- `src/ygo_kito/construction_inventory.py`、`construction_relations.py`、`construction_layer_flow.py`：统一消费、实体来源/去向、静态限制及顺序一致性。
- `src/ygo_kito/construction_progress.py`、`construction_fill.py`：Gate分类、完成计数和调度状态。
- `src/ygo_kito/construction_recognition.py`：待算异常与实现错误边界。
- `scripts/check_merge_candidate.py`：7个模块登记，未启动完整白名单。

对应12个测试文件：`tests/test_construction_workflow.py`、`test_construction_text_completion.py`、`test_construction_static_entries.py`、`test_construction_calculation_resume.py`、`test_construction_recognition.py`、`test_construction_runtime_processing.py`、`test_construction_progress.py`、`test_construction_functional_flow.py`、`test_construction_inventory.py`、`test_construction_relations.py`、`test_effect_block_dictionary.py`、`test_construction_layer_flow.py`。旧断言的迁移均保留实际库存、未知限定、来源/所有者、整数资源、次数或顺序的负例，不靠全真事实获得通过。

临时验证脚本及收据只在新的 `.cache/design-implementation-repair-20261110`；未覆盖原审查证据。

## 验证

最终合并回归：14个明确筛选的纯静态模块，按测试ID去重后344项通过，0失败、0错误、0跳过；约76.9秒，返回0。另有2个开放缺陷回归分别失败，未计入上述通过组：R3/F04的129方案截断、R5/F08的参考图约束。完整白名单CI未执行，项目全量测试尚未全绿。已保留首次失败、修复过程和后续日志。最终收据为 `verification-final-4.log` 与 `verification-summary.json`，开放反例另存 `r3-open-regression.log`、`r5-open-regression.log`；实际 `torch_loaded=false`。

23个本批改动程序文件完成AST检查，0语法错误；跟踪文件 `git diff --check` 通过，未跟踪源码另做语法及末尾换行检查。具体清单与原run-007元数据见 `artifact-validation.json`。测试收据不能升级为完整构筑、训练或规则引擎验收。

解释器仍为现有WSL `Chaos-Ubuntu-26.04` 的 `/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -B`，源码指向本完整检出 `src`。没有安装或修改环境；未运行未筛选discovery、完整CI、参数更新、真实模型权重推理、训练、CB/native或完整构筑。

run-007的kernel为409572012字节，session为408615095字节；mtime仍分别为2026-11-10 21:45:35、21:46:25（UTC+8），与交接一致。未读取大型存档内容、未重算其哈希、未恢复运行。原训练暂停文件、权重、配置及参考牌表未改。

## 设计和官方核对

按S0—S6、正式评分方案、扣分修订与用户“静态配置，不索要当前盘面或实际顺序”的最新纠正实施。官方核对仅用于对应卡文/裁定，不将当前禁限覆盖历史时期规则。

强欲而金满之壶以Extra里侧卡随机3或6作为成本，每3张抽1；其限制从处理后生效，此前已经效果抽卡仍能发动。见[官方卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=14144&ope=2&request_locale=ja)和[官方补足说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=14144&ope=4&request_locale=ja)。

简易融合的一次效果特殊召唤按融合召唤处理；免素材不取消被召唤者的特殊召唤条件/指定素材限制。见[官方卡文](https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=6901&ope=2&request_locale=ja)及[官方Q&A](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=18666&ope=5&request_locale=ja)。

“发动的回合”须覆盖先前行为，不能通过把特殊召唤放在发动前避开；见[强欲而谦虚之壶官方补足说明](https://www.db.yugioh-card.com/yugiohdb/faq_search.action?cid=8993&ope=4&request_locale=ja)。静态安排与必需联合用途的处理是项目设计对上述作用范围的消费，不是官方另行定义的构筑评分规则。

## 接续

本批在当前检出实施，分支仍为 `codex/optimization-20261031`、HEAD `3f57198`，未commit/push/merge。大量任务前既有修改、删除与未跟踪成果继续保留。后续先完成R1未闭合语义，再执行R3续算、R5参考、R6/R7生命周期及R8余项/R9/R10/R11；R4不需从头重写或恢复实跑证明。

本批形成适合交接的安全边界；R3涉及关系枚举、JSON状态和评分阶段多处同步变更，后续应使用[独立接续摘要](../handoffs/2026-11-11-design-implementation-repair-continuation.md)。未经用户明确确认不创建新聊天。训练、CB/native、完整构筑及run-007的暂停边界不因接续而解除。
