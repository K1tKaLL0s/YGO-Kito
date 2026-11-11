# 设计实现修复机械执行书

日期：2026-11-10。用户已明确启动修复，要求严格依照设计和 R0—R11 逐包实施、验收。本文与[逐包方案](2026-11-10-design-implementation-repair-plan.md)共同构成执行书；方案各包的前置、动作、通过与停止条件继续适用，旧“待启动”状态由本次指令更新。

## 目标、证据与边界

目标是修复 F01—F19 对应的软件缺口：完整卡文进入唯一静态评价器，有限计算真实续接，S0—S6正确迁移，参考独立且同口径，保存与服务使用同一生命周期。当前基线为 `_publish_20261030` 实际工作树，分支 `codex/optimization-20261031`、HEAD `3f57198`；大量已有未提交修改、删除与未跟踪文件保持。本次不建立工作树、不从HEAD重建。

已有证据为 `.cache/design-implementation-audit-20261110/{probe-results,boundary-probes,current-card-projections}.json`；当前公开 `construction_cycle` 在已知完整失败时返回 `static_coverage_unresolved`，CB回优化在passed判定前丢失；`MODULES`漏登记7个近期模块；`recognition_evidence_validator`缺少ContractError导入；一次融合处理被投影为两个召唤功能。以定向回归固化，不重新全项目审查。

实施由当前主进程完成，不启动子代理。训练、权重推理、参数更新、CB/native、完整构筑、GPU/PC实测保持暂停，不恢复run-007。软件层调度替身和纯静态绑定验证属于本次范围。原规则、参考牌表、权重、课程指针、training.hold和run-007不写入。不修改protected native ABI/guard，不运行故障注入、越界实验或未筛选discovery。按方案保留不提交/推送/合并边界。

允许修改范围为方案逐包列明的 src/ygo_kito 模块、对应已有 tests、scripts/check_merge_candidate.py、scripts/run_construction.py、R8明确列出的离线数据生成模块以及当前文档；发现必须增加范围的真实依赖时先写明该依赖和验收，再改该依赖。不接管并行识别网络或训练成果。

采用现有 MechanismCatalog/effect_records → 处理结构 → InventoryDependencies/关系及共享整数分配 → normalize_function_uses → 唯一Evaluation → 比较/Gate/反馈的数据流；不增第二事实库、求解器或评分器。版本变化只失效相关计算，旧成果保留，不让旧Evaluation冒充新语义。

不变量：固定任务、卡池、硬条件、主题轴和区域；log2、P/V1/V2/S、Main E1/0.9、Extra 1/0.8、实际N、主要+100%/次要+50%、Side方向与参考0.8保持；同一实体和处理不重复使用；静态不索要当前盘面或实际顺序；随机不能指定命中；unknown不置真；只有完成失败计数；用户停止优先。

## 执行和逐包验收

统一验证前缀 P：在当前完整检出用已有WSL `Chaos-Ubuntu-26.04`，解释器 `/mnt/n/YGO-Kito/_local_cpu_20261027/venv-linux/bin/python -B`，设置 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. OMP_NUM_THREADS=2 MKL_NUM_THREADS=2`。不安装环境、不加载权重；命令中的测试名必须显式选定。证据保存到新目录 `.cache/design-implementation-repair-20261110`，不写审查证据或原运行档。

| 包 | 目标文件/符号、前置与确定动作 | 验证命令/方法和通过标准 | 失败时停止范围 |
| --- | --- | --- | --- |
| R0 | `scripts/check_merge_candidate.py:MODULES`及方案7个测试模块；用户已启动。将7模块显式登记，把原短反例加入workflow/text_completion/static_entries/calculation_resume/recognition相应类，使用公开入口和真实默认卡文路径，先保留未修复失败记录。 | P `-m unittest`后接所加完整方法名；AST读取MODULES验证7项均在且无重复。每个新增方法必须在相应缺陷未修时失败，不能以全真事实、跳过或宽泛异常达成通过。 | 意外训练/引擎调用则停止该检查，修复隔离；不跑全CI。 |
| R1 | `effect_records.py:_zones/record_operations`、effect_blocks/effect_mechanisms、relations:_record_outputs、inventory、layer_flow:_function_semantics；先有R0反例。分离来源/去向，通用数量择一与支付关联，恢复处理身份、次数/指代/延迟/替代范围，消费端同步。 | P定向text_completion/condition_selection/functional_flow方法；3/6 Extra里侧随机成本与1/2抽卡对应，一次免素材融合只一转换/家族；词序/同义/两次独立召唤对照，紧急瞬间移动不回退，原评分公式保持。 | 卡名/ID补丁、第二事实库、unknown置真均拒绝；只修本包，不放宽规则。 |
| R2 | `layer_flow:_bind_mandatory_impacts`、inventory限制和relations；R1身份稳定。以静态可满足使用安排表达发动后范围，可选用途不无条件并用；必需联合和整回合限制仍检验共同资源/冲突。 | P定向functional_flow/static_entries/runtime_processing；发动后/整回合、自己/对方、可选/必需、可排顺序/环逐项对照；无context.before仍可得静态确定结果，真实冲突失败。 | 仅注入实战顺序才能通过则本包不通过，不转交用户补盘面。 |
| R3 | `relations:_expression/_combine/_partial_allocations`、layer_flow:normalize/evaluate、quality:evaluate_functional_quality；稳定语义后接入现有工作状态，保存枚举栈/位置/去重，评分完成与失分分阶段累积。 | P显式relations/calculation_resume/functional_quality；129供应方案全部唯一覆盖；小片JSON恢复与一次完成等价，游标前进且不重复前缀，循环/共享实体/数量正反例。 | 提高常数、分数受切片改变或另起求解器均停止该包，先闭合游标。 |
| R4 | `progress:_functional_gate/record_reference_attempt`、fill:_construction_cycle/construction_cycle；允许用调度桩提前修短缺陷。由同一Evaluation区分完成通过/失败、计算待算、语义缺口、配置错误、停止；CB回S2优先于passed。 | P定向workflow/progress/runtime_processing纯静态；失败→下一片通过实际2片，pending不计失败，完成失败只计一次、两次提示；CB正常失败回S2，线上到期排空，用户停止退出。 | 不能改阈值或把片数当失败数；pending状态有矛盾则修实际生产状态来源。 |
| R5 | `fill`参考与pending_phase、`binding:CatalogBindingAdapter`、layer_flow及progress；R3/R4接口稳定。固定BuildTask硬条件独立于候选可选图，候选比较提交一次后续reference阶段，完整参考按任务/政策/评价器/资产/牌表绑定复用。 | P定向binding/progress/functional_flow/calculation_resume；合法参考缺可选节点可评，必需缺失失败；3片参考候选及66对比较只一次；输入变化使缓存失效，半成品不复用为完整。 | 剥离硬条件、跨版本缓存或改变候选ID则停本包。 |
| R6 | `layer_flow:evaluate`、`quality:functional_delta`、fill搬运与`run_construction.py`；R3/R5稳定。外部边界校验一次，内部复用已验证结果/小摘要；权威checkpoint提交记录及导出session，取消落盘真实原因后不再开片。 | P定向layer_flow/calculation_resume/cli；统计校验/复制/比较调用次数；受控文件API替身覆盖写入异常、取消、落后导出/tmp，恢复只读已提交权威版本；原档不删。 | 不删来源校验、不双文件同时成功依赖、不写run-007；性能结论只记实际测量。 |
| R7 | `service:HostConstructionBackend.run`、controller和agent注册；R4—R6后复用同一cycle/保存。宿主配置模式/片参数，受控session支持创建、继续、进度、取消，RPC不接收路径/训练/native/provider。 | P显式service/agent_tools CPU静态方法；实际RPC提交/进度/取消/恢复和重试幂等，任务候选不变、不同绑定不串用，线上Gate排空。 | 权限扩张或需要UI时停对应部分，仅做已授权后端。 |
| R8 | `recognition:recognition_evidence_validator`先修导入/待算；`training/axis_generic/full18_sources.py`等在核对并行状态后补离线有证据正负/兼容/组合标签，保持未知和拆分来源。 | P显式recognition及离线标签方法；pending有合同结果无NameError，真实异常可追踪；每个负例/兼容冲突有原文坐标、卡/组合/机制隔离；保留46压力案例来源。 | 不覆盖M4/M5/旧权重/训练配置指针；不训练，不把数据合同通过称能力提高。 |
| R9 | `basic_cb_inference:BLOCK_ROUTES/proposals`、build_semantics、route_search、LinearMainline/duel_planning；R1—R4后扩展link/ritual/非召唤目标与共享绑定，保持随机及依赖随机结果分别表达。 | 仅P明确静态符号/绑定方法；消费者实际接到目标结构，召唤/非召唤、随机可入主干/指定命中不可确定的对照通过。 | 不调用infer/search执行、不执行CB/native；引擎见证另待授权。 |
| R10 | 宿主引擎生命周期调用方、bot_qualification、agent_monitor:RunReporter.resources；纯软件补可取消超时执行边界和硬件/资源字段，ABI/guard不变。 | P受控普通阻塞替身与采样接口；到期只回收自身单元、保留日志；缺测=null/未测，CPU/RAM/GPU/IO/阶段时延有来源绑定。 | 真引擎/GPU/PC测量继续暂停；不故障注入、不全局杀Python、不改保护。 |
| R11 | 当前入口、MASTER-CHECKLIST、验收对齐表和开发说明；逐项对F01—F19记录实际包状态、版本、调用入口和证据。 | AST/导入→缺陷方法→受影响安全静态模块→CI登记核对；筛选后再决定可运行的白名单，不自动全CI。软件、完整构筑、训练、CB/native、GPU/PC分别写真实结果。 | 不把未运行标通过，不恢复原跑次、不重新命名旧模型排序；失败只修对应包。 |

每包完成先保存定向验证和精确未完项，再进入有前置的下一包。R0的缺陷失败是基线记录，后续包必须转绿；不将预期失败计为验收通过。R4可以在语义长包前先完成短调度修复，状态明确列出。

## 官方口径与错误处理

卡文边界按当前项目的实际完整中文文本消费，并核对KONAMI官方数据库对应日文卡文/Q&A；不把当前禁限覆盖2207任务的历史禁限。已核对：强欲而金满之壶为Extra里侧卡随机3或6作成本、每3抽1、发动后不能再用效果抽卡；简易融合是一次融合召唤扱い的特殊召唤，并非两次召唤。特殊召唤条件/素材例外不能因免素材被一并忽略。后续在涉及的具体规则处按需查官方，不扩大为卡池重新审计。

- https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=14144&ope=2&request_locale=ja
- https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid=6901&ope=2&request_locale=ja
- https://www.db.yugioh-card.com/yugiohdb/faq_search.action?fid=18666&ope=5&request_locale=ja

计算预算用现有pending及游标返回，不判失败；语义未实现保留具体原文诊断；合同/配置错误保留可追踪异常，不宽泛吞掉。兼容性由现有版本绑定校验，新增游标缺失时只重建相关计算。尚未验证的项目为逐包实现、R8标签的实际当前覆盖、R10真实设备指标；不以这些未验证项暂停无关已授权修复。

局部回滚只撤销本次对应差异，不能reset/clean/restore既有工作树或删用户成果。用户停止时保存当前非破坏性原子步骤，不开新阶段。长任务优先继续当前聊天；当继续压缩会损害约束或已形成适合交接的安全边界时，提交自包含进度并建议新聊天，未经明确确认不创建新任务。
